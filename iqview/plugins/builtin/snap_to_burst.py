"""iqview/plugins/builtin/snap_to_burst.py

Built-in IQView Plugin: Snap to Burst.

For every Rect overlay in the active scope, searches for a signal burst inside
its time/frequency bounds. If a burst is found, reshapes the Rect to fit
tightly around the burst in both time and frequency (with optional time and
frequency margins), updates the overlay's cached baseband IQ (`o.iq`, `o.fs`), and
populates all extracted burst parameters as metadata.
"""

from __future__ import annotations

import numpy as np
from scipy import fft as sp_fft
from scipy import signal as sp_signal

from iqview import PluginResult


PLUGIN_NAME        = "Snap to Burst"
PLUGIN_DESCRIPTION = (
    "For every Rect overlay in scope, detects the burst inside its bounds, "
    "reshapes the Rect to fit tightly around the burst in time and frequency, "
    "and populates all extracted signal parameters in metadata."
)
PLUGIN_CATEGORY    = "Post-Processing"
PLUGIN_NEEDS_WIDEBAND_IQ = False

PLUGIN_DOC = """# Snap to Burst

Inspects every `Rect` overlay in the active scope, searches for a signal burst inside its time and frequency bounds, reshapes the `Rect` to fit tightly around the burst, updates the overlay's baseband IQ (`o.iq`, `o.fs`), and writes all measured burst parameters into `o.metadata`.

### Algorithm & Operation

1. **Baseband Extraction**: Extracts the complex baseband IQ inside each `Rect` overlay via `o.get_samples(samples, info)`.
2. **Time-Domain Burst Detection**:
   - Computes the smoothed instantaneous power envelope `|IQ|^2` using a moving-average window of length `smooth_window_us`.
   - Estimates the local noise floor from the lower percentile of the envelope and verifies that the burst exceeds the noise floor by at least `threshold_db`.
   - Finds contiguous active intervals, merges gaps shorter than `min_gap_ms`, selects the highest-energy burst inside the box, and expands both ends by `margin` samples.
3. **Frequency-Domain Tight Fitting (OBW)**:
   - Computes the windowed FFT power spectral density of the time-cropped burst and subtracts the spectral noise floor.
   - Locates the lower and upper frequency edges containing `obw_percent`% of the burst's spectral power, then widens that span by `freq_margin_percent`% of the measured bandwidth (default 10%), split equally above and below the center. The result is clamped to the original overlay.
4. **Baseband IQ Refinement & Parameter Extraction**:
   - Down-converts, filters, and resamples the cropped burst to the new tight frequency bounds so `o.iq` and `o.fs` match the reshaped `Rect`.
   - Extracts and stores `fc_hz`, `bw_hz`, `obw_hz`, `cfo_hz`, `t_start_s`, `t_end_s`, `duration_ms`, `snr_db`, `peak_snr_db`, `papr_db`, `rms_dbfs`, `num_samples`, and `sample_rate_hz` in `o.metadata`.
"""


PLUGIN_PARAMS = {
    "threshold_db": {
        "type": "float",
        "default": 6.0,
        "label": "Detection Threshold (dB)",
        "tooltip": "Minimum burst SNR above the local noise floor (dB) required to snap.",
    },
    "obw_percent": {
        "type": "float",
        "default": 99.0,
        "label": "Occupied BW Fit (%)",
        "tooltip": "Percentage of burst spectral energy used to fit tight frequency bounds (50–99.9%).",
    },
    "smooth_window_us": {
        "type": "float",
        "default": 25.0,
        "label": "Envelope Smoothing (µs)",
        "tooltip": "Moving-average smoothing window duration in microseconds for time-edge detection.",
    },
    "min_gap_ms": {
        "type": "float",
        "default": 0.1,
        "label": "Merge Gap (ms)",
        "tooltip": "Merge intra-burst gaps shorter than this duration in milliseconds.",
    },
    "margin": {
        "type": "int",
        "default": 0,
        "label": "Time Margin (samples)",
        "tooltip": (
            "Extra safeguard samples kept on each side of the snapped burst "
            "([max(0, start - margin), min(N, end + margin)])."
        ),
    },
    "freq_margin_percent": {
        "type": "float",
        "default": 10.0,
        "min": 0.0,
        "label": "Frequency Margin (%)",
        "tooltip": (
            "Extra bandwidth around the fitted burst, as a percent of its occupied "
            "bandwidth. 10% makes the box 1.1× the measured BW, split equally above "
            "and below. The box stays inside the original overlay."
        ),
    },
    "update_tag": {
        "type": "bool",
        "default": True,
        "label": "Update Overlay Tag",
        "tooltip": "Update the overlay display tag with snapped Fc, BW, and SNR.",
    },
}


def _find_tight_burst_time(
    seg: np.ndarray,
    fs: float,
    threshold_db: float,
    smooth_window_us: float,
    min_gap_ms: float,
    margin: int,
    fallback_noise_floor: float | None = None,
):
    """
    Locate the strongest burst inside `seg` and return
    `(s0, s1, raw_s0, raw_s1, noise_floor, mean_pwr, peak_pwr)` or `None` if no burst found.
    """
    n = len(seg)
    if n < 8 or fs <= 0:
        return None

    pwr = (seg.real.astype(np.float64) ** 2) + (seg.imag.astype(np.float64) ** 2)
    win_len = max(1, min(n // 4, int(round((smooth_window_us * 1e-6) * fs))))
    if win_len > 1:
        kernel = np.ones(win_len, dtype=np.float64) / float(win_len)
        env = sp_signal.lfilter(kernel, [1.0], pwr)
        for k in range(min(win_len - 1, n)):
            env[k] = np.mean(pwr[: k + 1])
    else:
        env = pwr

    # Estimate local noise floor from the quietest 10% of the time envelope
    p10 = float(np.percentile(env, 10.0))
    low_samples = env[env <= p10]
    noise_floor = float(np.median(low_samples)) if len(low_samples) > 0 else max(p10, 1e-20)
    if fallback_noise_floor is not None and fallback_noise_floor > 0:
        noise_floor = min(noise_floor, float(fallback_noise_floor))
    noise_floor = max(noise_floor, 1e-20)

    p90 = float(np.percentile(env, 90.0))
    peak_env = float(np.max(env))
    thresh_mult = 10.0 ** (threshold_db / 10.0)

    # Check if there is a burst significantly above the noise floor
    if peak_env < noise_floor * thresh_mult:
        return None

    # Combine noise-floor threshold and -10 dB plateau threshold for tight edge snapping
    thresh_noise = noise_floor * thresh_mult
    thresh_plateau = max(p90, peak_env * 0.5) * 0.10
    thresh = max(thresh_noise, min(thresh_plateau, p90 * 0.5))

    above = env >= thresh
    if not np.any(above):
        above = env >= thresh_noise
    if not np.any(above):
        return None

    padded = np.concatenate([[False], above, [False]])
    diffs = np.diff(padded.astype(np.int8))
    raw_starts = np.where(diffs == 1)[0]
    raw_ends = np.where(diffs == -1)[0]
    if len(raw_starts) == 0:
        return None

    min_gap_samples = max(1, int(round((min_gap_ms * 1e-3) * fs)))
    merged_starts = []
    merged_ends = []
    for a, b in zip(raw_starts, raw_ends):
        if merged_starts and (a - merged_ends[-1]) <= min_gap_samples:
            merged_ends[-1] = int(b)
        else:
            merged_starts.append(int(a))
            merged_ends.append(int(b))

    # Pick the candidate burst with highest integrated energy
    best_idx = 0
    best_energy = -1.0
    for idx, (a, b) in enumerate(zip(merged_starts, merged_ends)):
        if b <= a:
            continue
        e = float(np.sum(env[a:b]))
        if e > best_energy:
            best_energy = e
            best_idx = idx

    raw_s0 = int(merged_starts[best_idx])
    raw_s1 = int(merged_ends[best_idx])
    if raw_s1 <= raw_s0:
        return None

    # Recompute noise floor from samples strictly outside [raw_s0, raw_s1] if available
    outside_mask = np.ones(n, dtype=bool)
    outside_mask[raw_s0:raw_s1] = False
    if np.count_nonzero(outside_mask) >= 4:
        noise_floor = max(float(np.median(pwr[outside_mask])), 1e-20)

    s0 = max(0, raw_s0 - margin)
    s1 = min(n, raw_s1 + margin)

    burst_pwr = pwr[raw_s0:raw_s1]
    mean_pwr = float(np.mean(burst_pwr))
    peak_pwr = float(np.max(burst_pwr))
    return s0, s1, raw_s0, raw_s1, noise_floor, mean_pwr, peak_pwr


def _fit_tight_burst_freq(
    burst_iq: np.ndarray,
    fs: float,
    orig_fc: float,
    orig_f0: float,
    orig_f1: float,
    obw_fraction: float,
    threshold_db: float = 6.0,
    freq_margin_fraction: float = 0.10,
):
    """
    Estimate tight `[new_f0, new_f1]`, `obw_hz`, `cfo_hz`, and `est_time_noise_floor`
    from the burst's spectrum, rejecting both out-of-band noise and distant spectral sidelobes.
    """
    n = len(burst_iq)
    if n < 8 or fs <= 0:
        return orig_f0, orig_f1, orig_f1 - orig_f0, 0.0, None

    nfft = min(4096, max(64, 1 << int(np.ceil(np.log2(min(n, 2048))))))
    # Use Welch-style overlapping segments if burst_iq is longer than nfft, else single windowed FFT
    if n >= nfft:
        step = max(1, nfft // 2)
        win = np.hanning(nfft).astype(np.float32)
        win_norm = float(np.sum(win ** 2))
        acc = np.zeros(nfft, dtype=np.float64)
        n_frames = 0
        for start in range(0, n - nfft + 1, step):
            frame = burst_iq[start : start + nfft] * win
            acc += np.abs(sp_fft.fftshift(sp_fft.fft(frame, n=nfft))) ** 2 / max(win_norm, 1e-12)
            n_frames += 1
        spec = acc / max(1, n_frames)
    else:
        win = np.hanning(n).astype(np.float32)
        win_norm = float(np.sum(win ** 2))
        seg_win = burst_iq * win
        spec = (np.abs(sp_fft.fftshift(sp_fft.fft(seg_win, n=nfft))) ** 2).astype(np.float64) / max(win_norm, 1e-12)

    rel_freqs = sp_fft.fftshift(sp_fft.fftfreq(nfft, d=1.0 / fs))

    # Smooth spectrum slightly across bins so multi-tone / FSK dips stay connected
    smooth_bins = max(3, nfft // 128)
    if smooth_bins > 1 and len(spec) > smooth_bins:
        k_smooth = np.ones(smooth_bins, dtype=np.float64) / float(smooth_bins)
        spec_smooth = np.convolve(spec, k_smooth, mode="same")
    else:
        spec_smooth = spec

    # Estimate spectral noise floor per bin (so time-domain noise power is ~ spec_noise * nfft / n)
    spec_noise = max(float(np.percentile(spec_smooth, 20.0)), 1e-25)
    est_time_noise_floor = spec_noise

    peak_spec = float(np.max(spec_smooth))
    thresh_mult = 10.0 ** (max(threshold_db, 6.0) / 10.0)

    # Reject out-of-band noise AND distant spectral sidelobes below (1 - obw_fraction) of peak
    rel_floor = max(0.005, min(0.10, 1.0 - obw_fraction))
    gate_thresh = max(spec_noise * thresh_mult, peak_spec * rel_floor)

    active_bins = spec_smooth >= gate_thresh
    if np.any(active_bins):
        sig_spec = np.where(active_bins, np.maximum(0.0, spec - spec_noise), 0.0)
    else:
        sig_spec = np.maximum(0.0, spec - spec_noise * 2.0)

    total_spec_pwr = float(np.sum(sig_spec))
    if total_spec_pwr <= 1e-20:
        sig_spec = spec
        total_spec_pwr = float(np.sum(sig_spec)) + 1e-30

    cdf = np.cumsum(sig_spec) / total_spec_pwr
    tail = 0.5 * (1.0 - obw_fraction)
    idx_lo = max(0, min(int(np.searchsorted(cdf, tail)), nfft - 1))
    idx_hi = max(idx_lo, min(int(np.searchsorted(cdf, 1.0 - tail)), nfft - 1))

    df = float(fs / nfft)
    obw_hz = max(df, float(rel_freqs[idx_hi] - rel_freqs[idx_lo]))
    cfo_hz = float(np.sum(rel_freqs * sig_spec) / total_spec_pwr)

    f_center_est = orig_fc + 0.5 * float(rel_freqs[idx_lo] + rel_freqs[idx_hi])
    # Widen the measured occupied bandwidth by freq_margin_fraction (0.10 = 10% extra).
    pad = max(0.0, float(freq_margin_fraction))
    bw_fit = max(obw_hz * (1.0 + pad), df * 2.0)

    new_f0 = max(orig_f0, f_center_est - 0.5 * bw_fit)
    new_f1 = min(orig_f1, f_center_est + 0.5 * bw_fit)
    if new_f1 <= new_f0:
        return orig_f0, orig_f1, obw_hz, cfo_hz, est_time_noise_floor

    return new_f0, new_f1, obw_hz, cfo_hz, est_time_noise_floor


def _subband_ddc(
    burst_iq: np.ndarray,
    in_fs: float,
    in_fc: float,
    target_f0: float,
    target_f1: float,
):
    """Shift and filter `burst_iq` from `(in_fc, in_fs)` to `(target_fc, target_bw)`."""
    n = len(burst_iq)
    target_bw = max(1.0, target_f1 - target_f0)
    target_fc = 0.5 * (target_f0 + target_f1)
    if n < 8 or in_fs <= 0 or target_bw >= in_fs * 0.96:
        return burst_iq, in_fs

    duration = n / in_fs
    out_len = max(8, int(round(duration * target_bw)))
    out_fs = out_len / duration if duration > 0 else target_bw

    X = sp_fft.fft(burst_iq)
    f_offset = target_fc - in_fc
    center_bin = int(round(f_offset * duration))

    pos_count = (out_len + 1) // 2
    neg_count = out_len - pos_count
    rel_bins = np.concatenate([
        np.arange(0, pos_count, dtype=np.int64),
        np.arange(-neg_count, 0, dtype=np.int64),
    ])
    idx_bins = (center_bin + rel_bins) % n

    bin_freqs = sp_fft.fftfreq(out_len, d=1.0 / out_fs)
    cutoff = target_bw * 0.5
    H_lpf = (1.0 / (1.0 + (np.abs(bin_freqs) / max(cutoff, 1e-9)) ** 12)).astype(np.float32)
    scale = np.float32(out_len / float(n))

    X_sub = X[idx_bins] * (H_lpf * scale)
    out_iq = sp_fft.ifft(X_sub, overwrite_x=True).astype(np.complex64, copy=False)
    return out_iq, out_fs


def run(samples: np.ndarray, info) -> PluginResult:
    import copy

    result = PluginResult()
    if not info.overlays:
        result.warning("No overlays exist in the current session to snap.", title="Snap to Burst")
        return result

    params = info.params
    threshold_db     = float(params.get("threshold_db", 6.0))
    obw_percent      = float(np.clip(params.get("obw_percent", 99.0), 50.0, 99.9))
    smooth_window_us = max(1.0, float(params.get("smooth_window_us", 25.0)))
    min_gap_ms       = max(0.0, float(params.get("min_gap_ms", 0.1)))
    margin           = max(0, int(params.get("margin", 0)))
    freq_margin_percent = max(0.0, float(params.get("freq_margin_percent", 10.0)))
    update_tag       = bool(params.get("update_tag", True))

    obw_fraction = obw_percent / 100.0
    freq_margin_fraction = freq_margin_percent / 100.0

    t_start_scope = float(info.t_start)
    t_end_scope   = float(info.t_end)
    f_start_scope = float(info.f_start)
    f_end_scope   = float(info.f_end)

    candidates = [
        o for o in info.overlays
        if o._shape_name() == "RECT"
        and o.duration > 0
        and o.bandwidth > 0
        and o.t_end >= t_start_scope and o.t_start <= t_end_scope
        and o.f_end >= f_start_scope and o.f_start <= f_end_scope
    ]
    total = len(candidates)
    if total == 0:
        result.log("No Rect overlays found in active scope.")
        result.warning("No Rect overlays found in active scope to snap.", title="Snap to Burst")
        return result

    n_snapped = 0
    for idx, o in enumerate(candidates):
        if info.is_cancelled():
            break

        info.progress(
            int((idx / max(1, total)) * 95),
            f"Snapping overlay {idx + 1}/{total} to burst…",
        )

        orig_t0, orig_t1 = float(o.t_start), float(o.t_end)
        orig_f0, orig_f1 = float(o.f_start), float(o.f_end)
        orig_fc = float(o.f_center)

        seg, seg_fs = o.get_samples(samples, info)
        if seg is None or len(seg) < 8 or seg_fs <= 0:
            continue

        # Pass 1: Initial time detection on full-box IQ (or fallback to spectral noise floor
        # if the burst already fills >90% of the time box)
        _, _, _, _, spec_nf = _fit_tight_burst_freq(
            seg,
            fs=float(seg_fs),
            orig_fc=orig_fc,
            orig_f0=orig_f0,
            orig_f1=orig_f1,
            obw_fraction=obw_fraction,
            threshold_db=threshold_db,
            freq_margin_fraction=freq_margin_fraction,
        )
        time_fit = _find_tight_burst_time(
            seg,
            fs=float(seg_fs),
            threshold_db=threshold_db,
            smooth_window_us=smooth_window_us,
            min_gap_ms=min_gap_ms,
            margin=margin,
            fallback_noise_floor=spec_nf,
        )
        if time_fit is None:
            continue

        s0, s1, raw_s0, raw_s1, noise_floor, mean_pwr, peak_pwr = time_fit
        burst_time_iq = seg[s0:s1].copy()
        core_iq = seg[raw_s0:raw_s1] if raw_s1 > raw_s0 else burst_time_iq

        # Pass 2: Tight frequency fit on the time-cropped burst
        new_f0, new_f1, obw_hz, rel_cfo_hz, _ = _fit_tight_burst_freq(
            core_iq,
            fs=float(seg_fs),
            orig_fc=orig_fc,
            orig_f0=orig_f0,
            orig_f1=orig_f1,
            obw_fraction=obw_fraction,
            threshold_db=threshold_db,
            freq_margin_fraction=freq_margin_fraction,
        )

        # Pass 3: Refine time edges on the subband-filtered IQ if frequency narrowed significantly
        if (new_f1 - new_f0) < 0.85 * (orig_f1 - orig_f0):
            sub_full_iq, sub_full_fs = _subband_ddc(
                seg,
                in_fs=float(seg_fs),
                in_fc=orig_fc,
                target_f0=new_f0,
                target_f1=new_f1,
            )
            sub_time_fit = _find_tight_burst_time(
                sub_full_iq,
                fs=float(sub_full_fs),
                threshold_db=threshold_db,
                smooth_window_us=smooth_window_us,
                min_gap_ms=min_gap_ms,
                margin=margin,
            )
            if sub_time_fit is not None:
                sub_s0, sub_s1, sub_raw_s0, sub_raw_s1, noise_floor, mean_pwr, peak_pwr = sub_time_fit
                new_t0 = orig_t0 + (sub_s0 / float(sub_full_fs))
                new_t1 = min(orig_t1, orig_t0 + (sub_s1 / float(sub_full_fs)))
                tight_iq = sub_full_iq[sub_s0:sub_s1].copy()
                tight_fs = float(sub_full_fs)
            else:
                new_t0 = orig_t0 + (s0 / float(seg_fs))
                new_t1 = min(orig_t1, orig_t0 + (s1 / float(seg_fs)))
                tight_iq, tight_fs = _subband_ddc(
                    burst_time_iq,
                    in_fs=float(seg_fs),
                    in_fc=orig_fc,
                    target_f0=new_f0,
                    target_f1=new_f1,
                )
        else:
            new_t0 = orig_t0 + (s0 / float(seg_fs))
            new_t1 = min(orig_t1, orig_t0 + (s1 / float(seg_fs)))
            tight_iq, tight_fs = _subband_ddc(
                burst_time_iq,
                in_fs=float(seg_fs),
                in_fc=orig_fc,
                target_f0=new_f0,
                target_f1=new_f1,
            )

        if new_t1 <= new_t0:
            continue

        new_fc = 0.5 * (new_f0 + new_f1)
        new_bw = max(1.0, new_f1 - new_f0)
        new_dur_ms = (new_t1 - new_t0) * 1e3

        snr_db = float(10.0 * np.log10(max(mean_pwr / max(noise_floor, 1e-20), 1e-12)))
        peak_snr_db = float(10.0 * np.log10(max(peak_pwr / max(noise_floor, 1e-20), 1e-12)))
        papr_db = float(10.0 * np.log10(max(peak_pwr / max(mean_pwr, 1e-20), 1.0)))
        rms_dbfs = float(10.0 * np.log10(max(mean_pwr, 1e-20)))
        cfo_from_orig_hz = float((orig_fc + rel_cfo_hz) - orig_fc)

        # Reshape Rect tightly around the detected burst
        new_points = [(new_t0, new_f0), (new_t1, new_f1)]
        o.points = new_points
        o.iq = tight_iq
        o.fs = float(tight_fs)

        new_meta = copy.deepcopy(getattr(o, "metadata", {}) or {})
        new_meta.update({
            "snapped": True,
            "fc_hz": round(float(new_fc), 2),
            "bw_hz": round(float(new_bw), 2),
            "obw_hz": round(float(obw_hz), 2),
            "obw_percent": round(float(obw_percent), 1),
            "cfo_hz": round(float(cfo_from_orig_hz), 2),
            "t_start_s": round(float(new_t0), 6),
            "t_end_s": round(float(new_t1), 6),
            "duration_ms": round(float(new_dur_ms), 4),
            "snr_db": round(float(snr_db), 2),
            "peak_snr_db": round(float(peak_snr_db), 2),
            "papr_db": round(float(papr_db), 2),
            "rms_dbfs": round(float(rms_dbfs), 2),
            "margin_samples": int(margin),
            "freq_margin_percent": round(float(freq_margin_percent), 2),
            "num_samples": int(len(tight_iq)),
            "sample_rate_hz": round(float(tight_fs), 2),
        })
        o.metadata = new_meta

        if update_tag:
            o.display_str = f"{new_fc / 1e3:.1f} kHz | {snr_db:.1f} dB"

        summary_line = (
            f"Snapped Burst | Fc: {new_fc:,.1f} Hz | BW: {new_bw:,.1f} Hz (OBW: {obw_hz:,.1f} Hz)\n"
            f"Time: {new_t0:.6f}s .. {new_t1:.6f}s ({new_dur_ms:.3f} ms)\n"
            f"SNR: {snr_db:.1f} dB (Peak: {peak_snr_db:.1f} dB) | PAPR: {papr_db:.1f} dB | RMS: {rms_dbfs:.1f} dBFS"
        )
        o.hover_str = summary_line

        update_kwargs = {
            "points": new_points,
            "iq": tight_iq,
            "fs": float(tight_fs),
            "metadata": new_meta,
            "hover_str": summary_line,
        }
        if update_tag:
            update_kwargs["display_str"] = o.display_str

        result.update(o.id, **update_kwargs)
        n_snapped += 1

    result.log(f"Snapped {n_snapped}/{total} Rect overlay(s) to burst")
    if n_snapped == 0 and total > 0:
        result.warning(
            f"Could not detect burst signals exceeding threshold ({threshold_db} dB) in any of the {total} candidate box(es).\n\n"
            "Try lowering the Detection Threshold or checking overlay bounds.",
            title="Snap to Burst",
        )
    info.progress(100, "Done")
    return result

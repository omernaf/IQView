"""iqview/plugins/builtin/burst_energy_detector.py

Built-in IQView Plugin: Burst Energy Detector.

Fast wideband/sub-band burst detector that finds bursts in time, estimates
each burst's occupied frequency span [f_lo, f_hi], places `Rect` overlays,
and attaches baseband `o.iq` and `o.fs` for zero-copy downstream processing.
"""

from __future__ import annotations

import numpy as np
from scipy import fft as sp_fft
from scipy import signal as sp_signal

from iqview import PluginResult
from iqview.overlays import Rect


PLUGIN_NAME        = "Burst Energy Detector"
PLUGIN_DESCRIPTION = (
    "Fast wideband/sub-band burst energy detector that places Rect overlays "
    "around detected bursts and caches baseband IQ for downstream demodulation."
)
PLUGIN_CATEGORY    = "Detection"


PLUGIN_PARAMS = {
    "threshold_db": {
        "type": "float",
        "default": 8.0,
        "label": "Threshold above Noise Floor (dB)",
        "tooltip": "Energy threshold in dB above the estimated median noise floor.",
    },
    "min_duration_ms": {
        "type": "float",
        "default": 0.2,
        "label": "Min Burst Duration (ms)",
        "tooltip": "Ignore bursts shorter than this duration in milliseconds.",
    },
    "min_gap_ms": {
        "type": "float",
        "default": 0.1,
        "label": "Merge Gap (ms)",
        "tooltip": "Merge adjacent bursts separated by less than this gap in milliseconds.",
    },
    "smooth_window_us": {
        "type": "float",
        "default": 50.0,
        "label": "Smoothing Window (µs)",
        "tooltip": "Moving-average smoothing window duration in microseconds.",
    },
    "estimate_freq_bounds": {
        "type": "bool",
        "default": True,
        "label": "Auto-Fit Frequency Bounds (OBW)",
        "tooltip": "Estimate each burst's occupied frequency bounds [f_lo, f_hi] via FFT.",
    },
    "debug": {
        "type": "bool",
        "default": False,
        "label": "Debug Plot (Power Envelope)",
        "tooltip": "Open a plot tab showing the smoothed power envelope, threshold, and detected bursts.",
    },
}


def _extract_subband(work_iq: np.ndarray, fs: float, fc: float, f_start: float, f_end: float):
    """If [f_start, f_end] is narrower than the full band, DDC to the sub-band."""
    sub_bw = max(0.0, f_end - f_start)
    sub_fc = 0.5 * (f_start + f_end)
    total_in = len(work_iq)
    duration = total_in / fs

    if sub_bw <= 0 or sub_bw >= fs * 0.96:
        return work_iq, fs, fc

    num_sub = max(16, int(round(duration * sub_bw)))
    sub_fs = num_sub / duration if duration > 0 else sub_bw

    X_full = sp_fft.fft(work_iq, workers=-1)
    f_offset = sub_fc - fc
    center_bin = int(round(f_offset * duration))

    pos_count = (num_sub + 1) // 2
    neg_count = num_sub - pos_count
    rel_bins = np.concatenate([
        np.arange(0, pos_count, dtype=np.int64),
        np.arange(-neg_count, 0, dtype=np.int64),
    ])
    idx_bins = (center_bin + rel_bins) % total_in

    bin_freqs = sp_fft.fftfreq(num_sub, d=1.0 / sub_fs)
    cutoff = sub_bw * 0.5
    H_lpf = (1.0 / (1.0 + (np.abs(bin_freqs) / max(cutoff, 1e-9)) ** 12)).astype(np.float32)
    scale = np.float32(num_sub / float(total_in))

    X_sub = X_full[idx_bins] * (H_lpf * scale)
    sub_iq = sp_fft.ifft(X_sub, overwrite_x=True).astype(np.complex64, copy=False)
    return sub_iq, sub_fs, sub_fc


def _estimate_burst_freq_bounds(
    burst_iq: np.ndarray,
    fs: float,
    fc: float,
    f_min_clamp: float,
    f_max_clamp: float,
    obw_fraction: float = 0.98,
):
    """Estimate [f_lo, f_hi] of a burst using its power spectrum."""
    n = len(burst_iq)
    if n < 16:
        return f_min_clamp, f_max_clamp

    nfft = min(4096, max(64, 1 << int(np.ceil(np.log2(min(n, 2048))))))
    win = np.hanning(min(n, nfft)).astype(np.float32)
    seg = burst_iq[: len(win)] * win
    spec = np.abs(sp_fft.fftshift(sp_fft.fft(seg, n=nfft))) ** 2
    freqs = sp_fft.fftshift(sp_fft.fftfreq(nfft, d=1.0 / fs)) + fc

    # Subtract median noise floor per bin so broadband noise doesn't inflate OBW
    noise_bin = float(np.median(spec))
    sig_spec = np.maximum(0.0, spec - noise_bin * 1.5)
    total_pwr = float(np.sum(sig_spec))
    if total_pwr <= 1e-20:
        sig_spec = spec
        total_pwr = float(np.sum(sig_spec)) + 1e-30

    cdf = np.cumsum(sig_spec) / total_pwr
    tail = 0.5 * (1.0 - obw_fraction)
    idx_lo = int(np.searchsorted(cdf, tail))
    idx_hi = int(np.searchsorted(cdf, 1.0 - tail))
    idx_lo = max(0, min(idx_lo, nfft - 1))
    idx_hi = max(idx_lo, min(idx_hi, nfft - 1))

    bw_est = max(float(freqs[idx_hi] - freqs[idx_lo]) * 1.15, fs / 64.0)
    f_center = 0.5 * float(freqs[idx_lo] + freqs[idx_hi])
    f_lo = max(f_min_clamp, f_center - 0.5 * bw_est)
    f_hi = min(f_max_clamp, f_center + 0.5 * bw_est)
    if f_hi <= f_lo:
        return f_min_clamp, f_max_clamp
    return f_lo, f_hi


def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()
    if samples is None or len(samples) < 16:
        return result

    fs = float(info.fs)
    fc = float(info.fc)
    t_start = float(info.t_start)
    f_start = float(info.f_start)
    f_end = float(info.f_end)

    params = info.params
    threshold_db     = float(params.get("threshold_db", 8.0))
    min_duration_ms  = max(0.0, float(params.get("min_duration_ms", 0.2)))
    min_gap_ms       = max(0.0, float(params.get("min_gap_ms", 0.1)))
    smooth_window_us = max(1.0, float(params.get("smooth_window_us", 50.0)))
    est_freq_bounds  = bool(params.get("estimate_freq_bounds", True))
    debug            = bool(params.get("debug", False))

    work_iq = np.asarray(samples, dtype=np.complex64)
    info.progress(10, "Extracting active frequency band…")
    sub_iq, sub_fs, sub_fc = _extract_subband(work_iq, fs, fc, f_start, f_end)
    n_samples = len(sub_iq)
    if n_samples < 8:
        return result

    info.progress(30, "Computing smoothed power envelope…")
    pwr = (sub_iq.real.astype(np.float64) ** 2) + (sub_iq.imag.astype(np.float64) ** 2)
    win_len = max(1, int(round((smooth_window_us * 1e-6) * sub_fs)))
    if win_len > 1 and win_len < n_samples:
        kernel = np.ones(win_len, dtype=np.float64) / float(win_len)
        env = sp_signal.lfilter(kernel, [1.0], pwr)
        for k in range(min(win_len - 1, len(env))):
            env[k] = np.mean(pwr[: k + 1])
    else:
        env = pwr

    # Robust noise floor estimation (median of lower half of envelope)
    p50 = float(np.percentile(env, 50.0))
    low_samples = env[env <= p50]
    noise_floor = float(np.median(low_samples)) if len(low_samples) > 0 else max(p50, 1e-20)
    noise_floor = max(noise_floor, 1e-20)
    thresh_linear = noise_floor * (10.0 ** (threshold_db / 10.0))

    above = env > thresh_linear
    padded = np.concatenate([[False], above, [False]])
    diffs = np.diff(padded.astype(np.int8))
    raw_starts = np.where(diffs == 1)[0]
    raw_ends = np.where(diffs == -1)[0]

    min_gap_samples = int(round((min_gap_ms * 1e-3) * sub_fs))
    min_dur_samples = max(2, int(round((min_duration_ms * 1e-3) * sub_fs)))

    # Merge closely spaced bursts
    merged_starts = []
    merged_ends = []
    for s0, s1 in zip(raw_starts, raw_ends):
        if merged_starts and (s0 - merged_ends[-1]) <= min_gap_samples:
            merged_ends[-1] = int(s1)
        else:
            merged_starts.append(int(s0))
            merged_ends.append(int(s1))

    # Filter by minimum duration
    starts = []
    ends = []
    for s0, s1 in zip(merged_starts, merged_ends):
        if (s1 - s0) >= min_dur_samples:
            starts.append(s0)
            ends.append(s1)

    info.progress(65, f"Packaging {len(starts)} detected burst(s)…")

    for idx, (s0, s1) in enumerate(zip(starts, ends)):
        if info.is_cancelled():
            break

        b_t0 = t_start + (s0 / sub_fs)
        b_t1 = t_start + (s1 / sub_fs)
        b_dur_ms = (b_t1 - b_t0) * 1e3
        seg = sub_iq[s0:s1].copy()

        mean_pwr = float(np.mean(env[s0:s1]))
        peak_pwr = float(np.max(env[s0:s1]))
        snr_db = float(10.0 * np.log10(max(mean_pwr / noise_floor, 1e-12)))
        peak_snr_db = float(10.0 * np.log10(max(peak_pwr / noise_floor, 1e-12)))

        if est_freq_bounds:
            b_flo, b_fhi = _estimate_burst_freq_bounds(seg, sub_fs, sub_fc, f_start, f_end)
        else:
            b_flo, b_fhi = f_start, f_end

        b_fc = 0.5 * (b_flo + b_fhi)
        b_bw = max(1.0, b_fhi - b_flo)

        ov = Rect(
            t_start=b_t0,
            f_start=b_flo,
            t_end=b_t1,
            f_end=b_fhi,
            color="#00e676",
            alpha=0.20,
            border_width=2,
            border_color="#00e676",
            display_str=f"Burst #{idx + 1} ({snr_db:.1f} dB)",
            hover_str=(
                f"Burst #{idx + 1} | Fc: {b_fc:,.1f} Hz | BW: {b_bw:,.1f} Hz\n"
                f"Duration: {b_dur_ms:.3f} ms | SNR: {snr_db:.1f} dB (Peak: {peak_snr_db:.1f} dB)"
            ),
            metadata={
                "burst_index": int(idx + 1),
                "fc_hz": round(float(b_fc), 2),
                "bw_hz": round(float(b_bw), 2),
                "duration_ms": round(float(b_dur_ms), 4),
                "snr_db": round(float(snr_db), 2),
                "peak_snr_db": round(float(peak_snr_db), 2),
            },
        )
        # If the burst was narrowed in frequency, shift & resample its cached IQ to match [b_flo, b_fhi]
        if est_freq_bounds and b_bw < sub_fs * 0.90 and len(seg) >= 16:
            t_vec = np.arange(len(seg), dtype=np.float64) / sub_fs
            f_shift = b_fc - sub_fc
            if abs(f_shift) > 1e-3:
                seg = (seg * np.exp(-2j * np.pi * f_shift * t_vec)).astype(np.complex64)
            seg, burst_fs = ov._resample_to_bw(seg, sub_fs, b_bw)
            ov.iq = seg
            ov.fs = burst_fs
        else:
            ov.iq = seg
            ov.fs = sub_fs

        result.add(ov)

    if debug:
        env_db = 10.0 * np.log10(np.maximum(env, 1e-20))
        thresh_db_line = np.full_like(env_db, 10.0 * np.log10(thresh_linear))
        t_axis = t_start + np.arange(n_samples, dtype=np.float64) / sub_fs
        regions = [
            {
                "x_start": t_start + (s0 / sub_fs),
                "x_end": t_start + (s1 / sub_fs),
                "color": "#00e676",
                "alpha": 0.20,
                "label": "ACTIVE",
            }
            for s0, s1 in zip(starts, ends)
        ]
        result.set_plot_tab_title("Burst Detector Debug")
        result.add_plot(
            title="Power Envelope (dB)",
            y={
                "Envelope (dB)": env_db,
                "Threshold (dB)": thresh_db_line,
            },
            x=t_axis,
            fs=sub_fs,
            x_label="Time",
            x_units="s",
            y_label="Power (dB)",
            regions=regions,
        )

    result.log(f"Detected {len(starts)} burst(s)")
    info.progress(100, "Done")
    return result

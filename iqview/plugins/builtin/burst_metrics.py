"""iqview/plugins/builtin/burst_metrics.py

Built-in IQView Plugin: Burst Metrics (SNR & OBW).

Measures SNR (dB), Occupied Bandwidth (OBW, Hz), Carrier Frequency Offset
(CFO, Hz), and Peak-to-Average Power Ratio (PAPR, dB) on `Rect` overlays,
annotating their `hover_str` and `metadata`.
"""

from __future__ import annotations

import copy
import numpy as np
from scipy import fft as sp_fft

from iqview import PluginResult


PLUGIN_NAME              = "Burst Metrics (SNR & OBW)"
PLUGIN_DESCRIPTION       = (
    "Measures SNR, 99% Occupied Bandwidth (OBW), Carrier Frequency Offset (CFO), "
    "and PAPR for each Rect overlay and annotates hover tooltips & metadata."
)
PLUGIN_CATEGORY          = "Analysis"
PLUGIN_NEEDS_WIDEBAND_IQ = False


PLUGIN_PARAMS = {
    "obw_percent": {
        "type": "float",
        "default": 99.0,
        "label": "Occupied BW Percentage (%)",
        "tooltip": "Percentage of integrated power used to define Occupied Bandwidth (e.g. 99.0).",
    },
    "fit_freq_to_obw": {
        "type": "bool",
        "default": False,
        "label": "Snap Overlay Freq Bounds to OBW",
        "tooltip": "When enabled, adjusts each Rect overlay's [f_start, f_end] to match the measured OBW.",
    },
    "debug_plots": {
        "type": "bool",
        "default": False,
        "label": "Debug Plots (Burst PSD & OBW)",
        "tooltip": "Open a plot tab showing the Power Spectral Density (dB) and shaded OBW span for up to 5 bursts.",
    },
}


def _measure_burst(iq: np.ndarray, fs: float, obw_percent: float = 99.0):
    """Compute spectral and time-domain metrics for a baseband burst."""
    n = len(iq)
    if n < 8 or fs <= 0:
        return None

    pwr = (iq.real.astype(np.float64) ** 2) + (iq.imag.astype(np.float64) ** 2)
    mean_pwr = max(float(np.mean(pwr)), 1e-24)
    peak_pwr = max(float(np.max(pwr)), 1e-24)
    rms_dbfs = float(10.0 * np.log10(mean_pwr))
    papr_db = float(10.0 * np.log10(peak_pwr / mean_pwr))

    nfft = min(4096, max(64, 1 << int(np.ceil(np.log2(min(n * 2, 2048))))))
    win = np.hanning(n).astype(np.float64)
    win_norm = max(float(np.sum(win ** 2)), 1e-20)
    if n <= nfft:
        spec = (np.abs(sp_fft.fftshift(sp_fft.fft(iq * win, n=nfft))) ** 2) / win_norm
    else:
        # Average overlapping segments (Welch-style)
        step = max(1, nfft // 2)
        seg_win = np.hanning(nfft).astype(np.float64)
        seg_norm = max(float(np.sum(seg_win ** 2)), 1e-20)
        acc = np.zeros(nfft, dtype=np.float64)
        count = 0
        for s0 in range(0, n - nfft + 1, step):
            seg = iq[s0 : s0 + nfft] * seg_win
            acc += (np.abs(sp_fft.fftshift(sp_fft.fft(seg, n=nfft))) ** 2) / seg_norm
            count += 1
        spec = acc / max(1, count)

    freqs_rel = sp_fft.fftshift(sp_fft.fftfreq(nfft, d=1.0 / fs))

    # Estimate noise floor per bin from the lowest 25% of spectral bins
    sorted_spec = np.sort(spec)
    noise_bin = max(float(np.median(sorted_spec[: max(4, nfft // 4)])), 1e-24)
    total_noise = noise_bin * nfft
    total_power = max(float(np.sum(spec)), 1e-24)
    sig_power = max(total_power - total_noise, total_power * 0.05)
    snr_db = float(10.0 * np.log10(max(sig_power / max(total_noise, 1e-24), 1e-6)))

    # Subtract baseline noise before integrating OBW CDF
    clean_spec = np.maximum(0.0, spec - noise_bin * 1.25)
    clean_sum = float(np.sum(clean_spec))
    if clean_sum <= 1e-24:
        clean_spec = spec
        clean_sum = total_power

    cdf = np.cumsum(clean_spec) / clean_sum
    frac = float(np.clip(obw_percent / 100.0, 0.50, 0.999))
    tail = 0.5 * (1.0 - frac)
    idx_lo = int(np.clip(np.searchsorted(cdf, tail), 0, nfft - 1))
    idx_hi = int(np.clip(np.searchsorted(cdf, 1.0 - tail), idx_lo, nfft - 1))

    f_lo_rel = float(freqs_rel[idx_lo])
    f_hi_rel = float(freqs_rel[idx_hi])
    obw_hz = max(float(fs / nfft), f_hi_rel - f_lo_rel)

    # Carrier Frequency Offset (spectral centroid within OBW)
    obw_slice = clean_spec[idx_lo : idx_hi + 1]
    obw_freqs = freqs_rel[idx_lo : idx_hi + 1]
    obw_sum = float(np.sum(obw_slice))
    if obw_sum > 1e-24:
        cfo_hz = float(np.sum(obw_freqs * obw_slice) / obw_sum)
    else:
        cfo_hz = 0.5 * (f_lo_rel + f_hi_rel)

    psd_db = 10.0 * np.log10(np.maximum(spec, 1e-24))

    return {
        "snr_db": snr_db,
        "obw_hz": obw_hz,
        "cfo_hz": cfo_hz,
        "papr_db": papr_db,
        "rms_dbfs": rms_dbfs,
        "f_lo_rel": f_lo_rel,
        "f_hi_rel": f_hi_rel,
        "freqs_rel": freqs_rel,
        "psd_db": psd_db,
    }


def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()

    params = info.params
    obw_percent     = float(np.clip(params.get("obw_percent", 99.0), 50.0, 99.9))
    fit_freq_to_obw = bool(params.get("fit_freq_to_obw", False))
    debug_plots     = bool(params.get("debug_plots", False))

    t_start_scope = float(info.t_start)
    t_end_scope   = float(info.t_end)
    f_start_scope = float(info.f_start)
    f_end_scope   = float(info.f_end)

    candidates = []
    for o in info.overlays:
        sh = o.shape.value if hasattr(o.shape, "value") else str(o.shape)
        if sh != "RECT":
            continue
        if o.t_end < t_start_scope or o.t_start > t_end_scope:
            continue
        if o.f_end < f_start_scope or o.f_start > f_end_scope:
            continue
        candidates.append(o)

    if not candidates:
        result.log("No Rect overlays found in active scope.")
        return result

    MAX_DEBUG_PLOTS = 5
    debug_items = []
    n_measured = 0

    for idx, o in enumerate(candidates):
        if info.is_cancelled():
            break

        if idx % max(1, len(candidates) // 10) == 0:
            pct = int((idx / max(1, len(candidates))) * 95)
            info.progress(pct, f"Measuring burst {idx + 1}/{len(candidates)}…")

        burst_iq, burst_fs = o.get_samples(samples, info)
        if burst_iq is None or len(burst_iq) < 8 or burst_fs <= 0:
            continue

        metrics = _measure_burst(burst_iq, burst_fs, obw_percent=obw_percent)
        if metrics is None:
            continue

        snr_db   = metrics["snr_db"]
        obw_hz   = metrics["obw_hz"]
        cfo_hz   = metrics["cfo_hz"]
        papr_db  = metrics["papr_db"]
        rms_dbfs = metrics["rms_dbfs"]

        new_meta = copy.deepcopy(getattr(o, "metadata", {}) or {})
        new_meta.update({
            "snr_db": round(snr_db, 2),
            "obw_hz": round(obw_hz, 2),
            "obw_percent": round(obw_percent, 1),
            "cfo_hz": round(cfo_hz, 2),
            "papr_db": round(papr_db, 2),
            "rms_dbfs": round(rms_dbfs, 2),
        })

        base_hover = (getattr(o, "hover_str", "") or "").strip()
        kept_lines = [
            ln for ln in base_hover.splitlines()
            if not ln.startswith("Metrics:")
        ]
        kept_lines.append(
            f"Metrics: SNR {snr_db:.1f} dB | OBW({obw_percent:g}%): {obw_hz:,.1f} Hz | "
            f"CFO: {cfo_hz:+,.1f} Hz | PAPR: {papr_db:.1f} dB"
        )
        new_hover = "\n".join(kept_lines)

        update_kwargs = {
            "hover_str": new_hover,
            "metadata": new_meta,
        }
        if fit_freq_to_obw:
            fc_orig = float(o.f_center)
            new_flo = fc_orig + metrics["f_lo_rel"]
            new_fhi = fc_orig + metrics["f_hi_rel"]
            if new_fhi > new_flo:
                update_kwargs["points"] = [(float(o.t_start), new_flo), (float(o.t_end), new_fhi)]

        result.update(o.id, **update_kwargs)
        n_measured += 1

        if debug_plots and len(debug_items) < MAX_DEBUG_PLOTS:
            debug_items.append((idx + 1, o, burst_fs, metrics))

    if debug_plots and debug_items:
        result.set_plot_tab_title("Burst Metrics (PSD & OBW)")
        for b_num, o, burst_fs, metrics in debug_items:
            fc_orig = float(o.f_center)
            freqs_abs = fc_orig + metrics["freqs_rel"]
            regions = [{
                "x_start": fc_orig + metrics["f_lo_rel"],
                "x_end": fc_orig + metrics["f_hi_rel"],
                "color": "#00e5ff",
                "alpha": 0.22,
                "label": f"OBW ({metrics['obw_hz'] / 1e3:.2f} kHz)",
            }]
            result.add_plot(
                title=f"Burst #{b_num} PSD",
                y={"PSD (dB)": metrics["psd_db"]},
                x=freqs_abs,
                fs=burst_fs,
                x_label="Frequency",
                x_units="Hz",
                y_label="Power (dB)",
                primary_mode="FREQ",
                regions=regions,
            )

    result.log(f"Measured SNR & OBW on {n_measured} burst(s)")
    info.progress(100, "Done")
    return result

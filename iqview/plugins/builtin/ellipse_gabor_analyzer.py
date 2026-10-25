"""iqview/plugins/builtin/ellipse_gabor_analyzer.py

Built-in IQView Plugin: Ellipse Gabor Pulse Analyzer.

Demonstrates why `Ellipse` overlays are fundamental in RF Time-Frequency analysis:
1. Exact Iso-Energy Geometry of Localized Pulses: Under the Heisenberg-Gabor
   uncertainty principle (sigma_t * sigma_f >= 1 / 4*pi), Gaussian-enveloped RF
   pulses (pulsed radar pings, GFSK/GMSK hops, UWB impulses, EMI spikes) have
   exact elliptical constant-dB contours in the spectrogram.
2. Corner-Free 2D Radial Gabor Apodization: Eliminates the 21.5% empty corner
   noise of a `Rect` bounding box (1 - pi/4) and suppresses 2D rectangular
   corner Gibbs ringing via smooth radial cosine tapering in normalized
   elliptical coordinates rho(t, f).
3. Window-Free Time-Bandwidth Product (TBP = 4*pi * sigma_t * sigma_f):
   Distinguishes unmodulated transform-limited pulses (TBP ~ 1.0) from
   internally modulated / phase-coded / spread pulses (TBP >> 1.0).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy import fft as sp_fft, ndimage, signal as sp_signal
from scipy.signal.windows import hann

from iqview import PluginContext, PluginResult
from iqview.overlays import Ellipse


PLUGIN_NAME = "Ellipse Gabor Pulse Analyzer"
PLUGIN_DESCRIPTION = (
    "Fits 2D Heisenberg-Gabor uncertainty ellipses to RF pulses/transients, "
    "measures Time-Bandwidth Product (TBP), snaps drawn Ellipses to iso-energy "
    "contours, and extracts corner-free radially apodized IQ."
)
PLUGIN_CATEGORY = "Analysis"
PLUGIN_NEEDS_WIDEBAND_IQ = False
PLUGIN_BATCH_SECONDS = None
PLUGIN_RUN_ON_MAIN_THREAD = False


PLUGIN_DOC = """# Ellipse Gabor Pulse Analyzer

Utilizes **`Ellipse`** overlays to analyze, classify, and filter **localized RF pulses, radar pings, FHSS hops, and transient anomalies** using **Heisenberg-Gabor Time-Frequency Physics**.

### Why Use an `Ellipse` Instead of a `Rect`?

1. **Exact Physics of Localized RF Pulses**:
   By the **Heisenberg-Gabor Uncertainty Principle** ($\\sigma_t \\cdot \\sigma_f \\ge \\frac{1}{4\\pi}$), a localized Gaussian-enveloped RF pulse has spectrogram power density:
   $$P(t, f) = P_0 \\exp\\!\\left(-\\frac{(t - \\mu_t)^2}{2\\sigma_t^2} - \\frac{(f - \\mu_f)^2}{2\\sigma_f^2}\\right)$$
   In decibels ($10\\log_{10} P$), **every constant-power contour ($-3\\text{ dB}$, $-10\\text{ dB}$, $95\\%$ energy) is mathematically an exact axis-aligned `Ellipse`**:
   $$\\frac{(t - \\mu_t)^2}{r_t^2} + \\frac{(f - \\mu_f)^2}{r_f^2} = 1$$
2. **Eliminating the 21.5% Dead-Corner Noise & 2D Gibbs Ringing**:
   The four corners of a `Rect` ($1 - \\frac{\\pi}{4} \\approx 21.5\\%$ of box area) contain zero simultaneous peak-time and peak-frequency signal energy, and sharp box corners create 2D `sinc` sidelobes. Radial elliptical Gabor apodization tapers smoothly along normalized radius $\\rho(t, f) \\in [0, 1]$ with **zero corner artifacts**.
3. **Modulation Classification via Time-Bandwidth Product ($\\text{TBP}$)**:
   Computes window-free Gabor spreads $(\\sigma_t, \\sigma_f)$ on the radially-isolated waveform to evaluate:
   $$\\text{TBP} = 4\\pi \\, \\sigma_t \\, \\sigma_f \\ge 1.0$$
   - **$\\text{TBP} < 1.65$ (Cyan)**: *Transform-Limited / Unmodulated Pulse* (pulsed radar ping, UWB impulse, calibration logon).
   - **$1.65 \\le \\text{TBP} < 5.0$ (Green)**: *Shaped Narrowband / Compact Hop* (GFSK, GMSK, shaped symbol burst).
   - **$\\text{TBP} \\ge 5.0$ (Amber)**: *Internally Modulated Burst* (Barker/PSK phase-coded radar, chirped pulse, multi-symbol packet).

---

### Dual Operating Modes

1. **Analyze & Snap Drawn `Ellipse` Overlays**:
   - Draw an **Ellipse** around any pulse, transient, or hotspot on the spectrogram.
   - Extracts corner-free radially-apodized baseband IQ into `o.iq`, measures $(\\mu_t, \\mu_f, \\sigma_t, \\sigma_f, \\text{TBP}, \\text{Coherence } \\eta, \\text{Gaussianity } R^2)$, and optionally **snaps the `Ellipse`** onto the exact $p\\%$ 2D iso-energy contour!
2. **Auto-Detect Localized Pulses $\\rightarrow$ Create `Ellipse` Overlays**:
   - When no `Ellipse` overlays exist in scope (or when explicitly selected), detects localized pulses/transients, fits Gabor `Ellipse` contours around each, color-codes them by $\\text{TBP}$ class, and plots the **Radial Energy Falloff $P(\\rho)$ vs. Ideal Gaussian Logon**!
"""


MODE_AUTO = "Auto (Analyze Drawn Ellipses, or Detect Pulses)"
MODE_ANALYZE = "Analyze & Snap Existing Ellipses"
MODE_DETECT = "Detect Localized Pulses -> Create Ellipses"


PLUGIN_PARAMS = {
    "mode": {
        "type": "choice",
        "default": MODE_AUTO,
        "choices": [MODE_AUTO, MODE_ANALYZE, MODE_DETECT],
        "label": "Operation Mode",
        "tooltip": "Auto analyzes/snaps existing Ellipses if present, otherwise auto-detects localized pulses.",
    },
    "threshold_db": {
        "type": "float",
        "default": 10.0,
        "min": 3.0,
        "max": 60.0,
        "label": "Pulse Detection Threshold (dB)",
        "tooltip": "Minimum pulse SNR above background noise floor (dB) in auto-detect mode.",
    },
    "containment_pct": {
        "type": "float",
        "default": 95.0,
        "min": 50.0,
        "max": 99.5,
        "label": "2D Energy Containment (%)",
        "tooltip": "Percentage of 2D Gaussian pulse energy enclosed by the fitted Ellipse radii (95% -> 2.45 sigma).",
    },
    "snap_ellipses": {
        "type": "bool",
        "default": True,
        "label": "Snap Drawn Ellipses to Contour",
        "tooltip": "When analyzing user-drawn Ellipses, refine center and radii to fit the measured Gabor contour.",
    },
    "max_duration_ms": {
        "type": "float",
        "default": 50.0,
        "min": 0.05,
        "max": 5000.0,
        "label": "Max Pulse Duration (ms)",
        "tooltip": "In Detect mode, ignore continuous carriers longer than this duration (ms).",
    },
    "lock_ellipses": {
        "type": "bool",
        "default": False,
        "label": "Lock Created Ellipses",
        "tooltip": "If False, N/S/E/W cardinal handles on detected Ellipses remain interactively draggable.",
    },
}


# Variance restoration factor when clipping a 1D Gaussian energy profile at 1% (-20 dB) of peak
_GAUSS_TRUNC_1PCT_COMP = 1.0111


def _extract_iq_slice(
    samples: Optional[np.ndarray],
    info: PluginContext,
    t0: float,
    t1: float,
) -> Tuple[np.ndarray, float]:
    """Safely extract IQ samples for `[t0, t1]` using `info.extract_iq` or `samples`."""
    fs = float(info.sample_rate)
    t_lo = max(0.0, min(float(t0), float(t1)))
    t_hi = max(float(t0), float(t1))
    if t_hi <= t_lo or fs <= 0:
        return np.empty(0, dtype=np.complex64), t_lo

    seg = info.extract_iq(t_lo, t_hi)
    if (seg is None or len(seg) == 0) and samples is not None and len(samples) > 0:
        s0 = max(0, int(round((t_lo - float(info.t_start)) * fs)))
        s1 = min(len(samples), int(round((t_hi - float(info.t_start)) * fs)))
        if s1 > s0:
            seg = samples[s0:s1]
            t_lo = float(info.t_start) + s0 / fs

    if seg is None or len(seg) == 0:
        return np.empty(0, dtype=np.complex64), t_lo

    return np.asarray(seg, dtype=np.complex64), t_lo


def _classify_tbp(tbp: float) -> Tuple[str, str, str]:
    """Return `(class_label, short_tag, hex_color)` for a measured Heisenberg-Gabor TBP."""
    if tbp < 1.65:
        return "Transform-Limited Pulse", "Transform-Lim", "#00E5FF"
    if tbp < 5.0:
        return "Shaped / Compact Pulse", "Shaped", "#00E676"
    return "Internally Modulated Burst", "Modulated", "#FFAB00"


def _analyze_elliptical_region(
    seg_wb: np.ndarray,
    seg_t0: float,
    fs: float,
    fc_world: float,
    t_center_init: float,
    f_center_init: float,
    r_t_init: float,
    r_f_init: float,
    containment_pct: float,
) -> Optional[Dict[str, Any]]:
    """
    Apply corner-free 2D radial elliptical Gabor filtering around `(t_center_init, f_center_init)`
    with radii `(r_t_init, r_f_init)`, then compute window-free Gabor moments `(mu_t, mu_f,
    sigma_t, sigma_f, TBP)`, radial profile `P(rho)`, and apodized baseband IQ.
    """
    n_seg = len(seg_wb)
    if n_seg < 16 or fs <= 0 or r_t_init <= 0 or r_f_init <= 0:
        return None

    # Mix candidate ellipse center frequency to 0 Hz baseband
    f_shift = float(f_center_init - fc_world)
    t_vec_rel = np.arange(n_seg, dtype=np.float64) / fs
    t_vec_world = seg_t0 + t_vec_rel
    seg_bb = (seg_wb.astype(np.complex128) * np.exp(-2j * np.pi * f_shift * t_vec_rel))

    # Choose STFT window matching candidate ellipse aspect ratio d_t / d_f ~ r_t / r_f
    ideal_nper = int(np.sqrt(max(16.0, fs * (r_t_init / max(r_f_init, 1.0)))) * 1.2)
    nperseg = 1 << int(np.clip(np.round(np.log2(max(16, ideal_nper))), 4, 11))
    while nperseg > 16 and nperseg > n_seg // 2:
        nperseg //= 2
    noverlap = (3 * nperseg) // 4

    f_rel_un, t_stft_rel, Z_un = sp_signal.stft(
        seg_bb,
        fs=fs,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        return_onesided=False,
        boundary="zeros",
        padded=True,
    )
    f_bb = np.fft.fftshift(f_rel_un)
    t_stft_world = seg_t0 + t_stft_rel
    Z_sh = np.fft.fftshift(Z_un, axes=0)
    pwr_2d = np.abs(Z_sh) ** 2

    # Normalized elliptical radius grid rho(f, t)
    u_t = (t_stft_world[np.newaxis, :] - t_center_init) / max(r_t_init, 1e-12)
    u_f = f_bb[:, np.newaxis] / max(r_f_init, 1e-12)
    rho_grid = np.sqrt(u_t ** 2 + u_f ** 2)

    # Ensure at least center pixel is included for ultra-compact ellipses
    if not np.any(rho_grid <= 1.0):
        k_c = int(np.argmin(np.abs(f_bb)))
        m_c = int(np.argmin(np.abs(t_stft_world - t_center_init)))
        rho_grid[k_c, m_c] = 0.0

    in_ell = rho_grid <= 1.0
    out_ell = rho_grid > 1.15
    noise_2d = (
        float(np.median(pwr_2d[out_ell])) / float(np.log(2.0))
        if np.any(out_ell)
        else float(np.percentile(pwr_2d, 20))
    )
    mean_in_2d = max(float(np.mean(pwr_2d[in_ell])), 1e-30)
    peak_in_2d = max(float(np.max(pwr_2d[in_ell])), 1e-30)
    # Clamp noise floor to single-precision dynamic range on noiseless synthetic captures
    noise_2d = max(noise_2d, peak_in_2d * 1e-8, 1e-30)
    snr_db = float(10.0 * np.log10(max((mean_in_2d - noise_2d) / noise_2d, 1e-6)))
    peak_snr_db = float(10.0 * np.log10(max(peak_in_2d / noise_2d, 1e-6)))

    # Smooth radial Tukey-Cosine Gabor filter: 1.0 inside rho<=0.9, cosine roll-off 0.9..1.25
    floor_g = 1e-4  # -80 dB out-of-ellipse stopband
    taper = np.zeros_like(rho_grid, dtype=np.float64)
    taper[rho_grid <= 0.90] = 1.0
    trans = (rho_grid > 0.90) & (rho_grid <= 1.25)
    taper[trans] = 0.5 * (1.0 + np.cos(np.pi * (rho_grid[trans] - 0.90) / 0.35))
    gain_2d = floor_g + (1.0 - floor_g) * taper

    _, rec_bb = sp_signal.istft(
        np.fft.ifftshift(Z_sh * gain_2d, axes=0),
        fs=fs,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        input_onesided=False,
        boundary=True,
    )
    z_clean = np.asarray(rec_bb[:n_seg], dtype=np.complex128)

    # --- Window-Free Gabor Moments directly on isolated z_clean(t) & Z_clean(f) ---
    in_time_span = np.abs(t_vec_world - t_center_init) <= (1.15 * r_t_init)
    if np.count_nonzero(in_time_span) < 4:
        in_time_span = np.ones(n_seg, dtype=bool)

    t_sub = t_vec_world[in_time_span]
    z_sub = z_clean[in_time_span]
    env_t = np.abs(z_sub) ** 2
    env_floor = max(float(np.percentile(env_t, 15)) * 1.5, 0.01 * float(np.max(env_t)))
    w_t = np.maximum(env_t - env_floor, 0.0)
    w_t_sum = float(np.sum(w_t))
    if w_t_sum <= 1e-30:
        w_t = np.maximum(env_t, 1e-30)
        w_t_sum = float(np.sum(w_t))

    mu_t = float(np.sum(t_sub * w_t) / w_t_sum)
    var_t = float(np.sum(((t_sub - mu_t) ** 2) * w_t) / w_t_sum)
    sigma_t = max(np.sqrt(max(var_t, 0.0)) * _GAUSS_TRUNC_1PCT_COMP, 0.5 / fs)

    # Zero-padded high-resolution FFT for exact spectral spread sigma_f
    n_fft_hi = min(65536, max(256, 1 << int(np.ceil(np.log2(len(z_sub) * 4)))))
    Z_hi = sp_fft.fftshift(sp_fft.fft(z_sub, n=n_fft_hi))
    f_hi = sp_fft.fftshift(sp_fft.fftfreq(n_fft_hi, d=1.0 / fs))
    in_f_span = np.abs(f_hi) <= min(0.495 * fs, 1.15 * r_f_init)
    if np.count_nonzero(in_f_span) < 4:
        in_f_span = np.ones(n_fft_hi, dtype=bool)

    f_sub_hi = f_hi[in_f_span]
    spec_f = np.abs(Z_hi[in_f_span]) ** 2
    spec_floor = max(float(np.percentile(spec_f, 15)) * 1.5, 0.01 * float(np.max(spec_f)))
    w_f = np.maximum(spec_f - spec_floor, 0.0)
    w_f_sum = float(np.sum(w_f))
    if w_f_sum <= 1e-30:
        w_f = np.maximum(spec_f, 1e-30)
        w_f_sum = float(np.sum(w_f))

    mu_f_rel = float(np.sum(f_sub_hi * w_f) / w_f_sum)
    var_f = float(np.sum(((f_sub_hi - mu_f_rel) ** 2) * w_f) / w_f_sum)
    sigma_f = max(np.sqrt(max(var_f, 0.0)) * _GAUSS_TRUNC_1PCT_COMP, fs / (2.0 * n_fft_hi))
    mu_f_world = float(f_center_init + mu_f_rel)

    # Physical Heisenberg-Gabor Time-Bandwidth Product: TBP = 4 * pi * sigma_t * sigma_f >= 1.0
    tbp_raw = float(4.0 * np.pi * sigma_t * sigma_f)
    tbp = max(1.0, tbp_raw)
    coherence_pct = float(np.clip(100.0 / tbp, 0.0, 100.0))

    # 2D Bivariate Gaussian containment factor: P(r <= k*sigma) = 1 - exp(-k^2 / 2) = p
    p_frac = float(np.clip(containment_pct / 100.0, 0.50, 0.995))
    k_contain = float(np.sqrt(-2.0 * np.log(max(1.0 - p_frac, 1e-6))))
    rt_fit = float(k_contain * sigma_t)
    rf_fit = float(k_contain * sigma_f)

    # True 2D Spectrogram Elliptical Fit (accounting for Hann STFT window spreads)
    # Hann |STFT|^2 RMS spreads: sigma_wt = 0.14145 * Tw, sigma_wf = 0.57735 * df
    sigma_wt = 0.14145 * (nperseg / fs)
    sigma_wf = 0.57735 * (fs / nperseg)
    rt_2d = float(k_contain * np.hypot(sigma_t, sigma_wt))
    rf_2d = float(k_contain * np.hypot(sigma_f, sigma_wf))
    rho_2d_fit = np.sqrt(
        ((t_stft_world[np.newaxis, :] - mu_t) / max(rt_2d, 1e-12)) ** 2
        + ((f_bb[:, np.newaxis] - mu_f_rel) / max(rf_2d, 1e-12)) ** 2
    )

    rho_edges = np.linspace(0.0, 1.35, 19)
    rho_centers = 0.5 * (rho_edges[:-1] + rho_edges[1:])
    pwr_clean_2d = np.maximum(pwr_2d - noise_2d, 0.0)
    p2d_peak = max(float(np.max(pwr_clean_2d[rho_2d_fit <= 0.5])) if np.any(rho_2d_fit <= 0.5) else float(np.max(pwr_clean_2d)), 1e-30)
    pwr_norm_2d = pwr_clean_2d / p2d_peak

    shell_lin = np.zeros(len(rho_centers), dtype=np.float64)
    for b_idx in range(len(rho_centers)):
        sh_m = (rho_2d_fit >= rho_edges[b_idx]) & (rho_2d_fit < rho_edges[b_idx + 1])
        if np.any(sh_m):
            shell_lin[b_idx] = float(np.mean(pwr_norm_2d[sh_m]))
        elif b_idx == 0:
            shell_lin[b_idx] = 1.0
        else:
            shell_lin[b_idx] = shell_lin[b_idx - 1] * 0.5
    shell_lin = shell_lin / max(float(np.max(shell_lin)), 1e-30)
    shell_norm_db = 10.0 * np.log10(np.maximum(shell_lin, 1e-4))

    # Ideal 2D Gaussian logon curve & pixel-wise 2D axis-aligned Gaussian R^2
    ideal_gauss_lin = np.exp(-0.5 * ((k_contain * rho_centers) ** 2))
    ideal_gauss_db = 10.0 * np.log10(np.maximum(ideal_gauss_lin, 1e-4))

    eval_mask = rho_2d_fit <= 1.25
    if int(np.count_nonzero(eval_mask)) >= 6:
        y_meas = pwr_norm_2d[eval_mask]
        y_pred = np.exp(-0.5 * ((k_contain * rho_2d_fit[eval_mask]) ** 2))
        # Optimal linear scale alpha = <y_meas, y_pred> / <y_pred, y_pred>
        alpha_fit = float(np.dot(y_meas, y_pred) / max(float(np.dot(y_pred, y_pred)), 1e-30))
        ss_res = float(np.sum((y_meas - alpha_fit * y_pred) ** 2))
        ss_tot = max(float(np.sum((y_meas - np.mean(y_meas)) ** 2)), 1e-12)
        gauss_r2 = float(np.clip(1.0 - ss_res / ss_tot, 0.0, 1.0))
    else:
        ss_res = float(np.sum((shell_lin - ideal_gauss_lin) ** 2))
        ss_tot = max(float(np.sum((shell_lin - np.mean(shell_lin)) ** 2)), 1e-12)
        gauss_r2 = float(np.clip(1.0 - ss_res / ss_tot, 0.0, 1.0))

    # Re-center & decimate radially-apodized baseband IQ to fitted bandwidth `2 * rf_fit`
    bw_fit = 2.0 * rf_fit
    c0 = max(0, int(round((mu_t - rt_fit - seg_t0) * fs)))
    c1 = min(n_seg, max(c0 + 4, int(round((mu_t + rt_fit - seg_t0) * fs))))
    iq_crop = z_clean[c0:c1] * np.exp(-2j * np.pi * mu_f_rel * (np.arange(c1 - c0) / fs))
    out_fs = fs
    if 0.0 < bw_fit < fs * 0.95 and len(iq_crop) >= 16:
        target_len = max(8, int(round(len(iq_crop) * (bw_fit / fs))))
        iq_out = np.asarray(sp_signal.resample(iq_crop, target_len), dtype=np.complex64)
        out_fs = float(len(iq_out)) / max(len(iq_crop) / fs, 1e-12)
    else:
        iq_out = np.asarray(iq_crop, dtype=np.complex64)

    return {
        "mu_t": mu_t,
        "mu_f": mu_f_world,
        "sigma_t": sigma_t,
        "sigma_f": sigma_f,
        "rt_fit": rt_fit,
        "rf_fit": rf_fit,
        "tbp": tbp,
        "coherence_pct": coherence_pct,
        "gauss_r2": gauss_r2,
        "snr_db": snr_db,
        "peak_snr_db": peak_snr_db,
        "rho_centers": rho_centers,
        "shell_norm_db": shell_norm_db,
        "ideal_gauss_db": ideal_gauss_db,
        "iq_bb": iq_out,
        "fs_bb": out_fs,
    }


def _format_ellipse_annotation(
    idx: int,
    metrics: Dict[str, Any],
    containment_pct: float,
) -> Tuple[str, str, Dict[str, Any], str]:
    tbp = metrics["tbp"]
    cls_name, short_tag, color_hex = _classify_tbp(tbp)
    tag = f"TBP={tbp:.2f} ({short_tag}) | SNR {metrics['snr_db']:.1f}dB"
    hover_md = (
        f"### Gabor Uncertainty Ellipse #{idx} — {cls_name}\n"
        f"| Metric | Value |\n"
        f"| :--- | :--- |\n"
        f"| **Time-Bandwidth Product ($4\\pi\\sigma_t\\sigma_f$)** | **{tbp:.3f}** (Min Limit = 1.000) |\n"
        f"| **Transform-Limit Coherence ($\\eta$)** | {metrics['coherence_pct']:.1f}% |\n"
        f"| **Gabor Centroid ($\\mu_t, \\mu_f$)** | {metrics['mu_t'] * 1e3:.3f} ms, {metrics['mu_f'] / 1e6:.6f} MHz |\n"
        f"| **RMS Spreads ($\\sigma_t, \\sigma_f$)** | {metrics['sigma_t'] * 1e6:.2f} µs, {metrics['sigma_f'] / 1e3:.2f} kHz |\n"
        f"| **{containment_pct:.0f}% Contour Radii ($r_t, r_f$)** | ±{metrics['rt_fit'] * 1e6:.1f} µs, ±{metrics['rf_fit'] / 1e3:.2f} kHz |\n"
        f"| **Gaussian Logon Fit ($R^2$)** | {metrics['gauss_r2']:.3f} |\n"
        f"| **In-Ellipse Mean / Peak SNR** | {metrics['snr_db']:.1f} dB / {metrics['peak_snr_db']:.1f} dB |\n"
        f"| **Corner Noise Excluded vs. Rect** | 21.5% ($1 - \\pi/4$, radial Gabor taper) |"
    )
    meta = {
        "pulse_class": cls_name,
        "tbp": round(tbp, 4),
        "coherence_pct": round(metrics["coherence_pct"], 2),
        "mu_t_s": round(metrics["mu_t"], 9),
        "mu_f_hz": round(metrics["mu_f"], 2),
        "sigma_t_s": float(f"{metrics['sigma_t']:.6e}"),
        "sigma_f_hz": round(metrics["sigma_f"], 2),
        "r_t_s": float(f"{metrics['rt_fit']:.6e}"),
        "r_f_hz": round(metrics["rf_fit"], 2),
        "gaussian_fit_r2": round(metrics["gauss_r2"], 4),
        "snr_db": round(metrics["snr_db"], 2),
        "peak_snr_db": round(metrics["peak_snr_db"], 2),
    }
    return tag, hover_md, meta, color_hex


# ---------------------------------------------------------------------------
# Workflow 1: Analyze & Snap Existing User-Drawn Ellipses
# ---------------------------------------------------------------------------

def _analyze_existing_ellipses(
    ellipses: List[Any],
    samples: Optional[np.ndarray],
    info: PluginContext,
    containment_pct: float,
    snap_ellipses: bool,
    result: PluginResult,
) -> PluginResult:
    fs = float(info.sample_rate)
    fc = float(info.center_freq)
    n_ell = len(ellipses)

    best_m: Optional[Dict[str, Any]] = None
    best_snr = -1e9
    tbp_t: List[float] = []
    tbp_v: List[float] = []

    for idx, o in enumerate(ellipses, start=1):
        if info.is_cancelled():
            return result
        info.progress(
            10.0 + 80.0 * ((idx - 1) / max(1, n_ell)),
            f"Analyzing Gabor Uncertainty on Ellipse {idx}/{n_ell}...",
        )

        ct, cf = float(o.center[0]), float(o.center[1])
        rt, rf = abs(float(o.radii[0])), abs(float(o.radii[1]))
        if rt <= 0.0 or rf <= 0.0:
            continue

        # Bound per-ellipse window to 2M samples max, with ample skirt margin (>= 2x radius)
        rt_work = min(rt, 800_000.0 / fs)
        margin_t = max(2.0 * rt_work, 128.0 / fs)
        t_w0 = max(0.0, ct - margin_t)
        t_w1 = ct + margin_t
        seg, seg_t0 = _extract_iq_slice(samples, info, t_w0, t_w1)
        if len(seg) < 16:
            continue

        m = _analyze_elliptical_region(
            seg_wb=seg,
            seg_t0=seg_t0,
            fs=fs,
            fc_world=fc,
            t_center_init=ct,
            f_center_init=cf,
            r_t_init=rt_work,
            r_f_init=rf,
            containment_pct=containment_pct,
        )
        if m is None:
            continue

        tag, hover_md, base_meta, col_hex = _format_ellipse_annotation(idx, m, containment_pct)
        merged_meta = dict(o.metadata or {})
        merged_meta.update(base_meta)

        upd_kwargs: Dict[str, Any] = {
            "display_str": tag,
            "hover_str": hover_md,
            "metadata": merged_meta,
            "iq": m["iq_bb"],
            "fs": m["fs_bb"],
        }
        if snap_ellipses:
            # Clamp snapped radii within sensible bounds of the user-drawn box
            new_rt = float(np.clip(m["rt_fit"], max(2.0 / fs, 0.05 * rt), 1.35 * rt))
            new_rf = float(np.clip(m["rf_fit"], max(fs / 65536.0, 0.05 * rf), 1.35 * rf))
            new_ct = float(np.clip(m["mu_t"], ct - rt, ct + rt))
            new_cf = float(np.clip(m["mu_f"], cf - rf, cf + rf))
            upd_kwargs["center"] = (new_ct, new_cf)
            upd_kwargs["radii"] = (new_rt, new_rf)
            upd_kwargs["color"] = col_hex

        result.update(o.id, **upd_kwargs)
        tbp_t.append(m["mu_t"])
        tbp_v.append(m["tbp"])
        if m["snr_db"] > best_snr:
            best_snr = m["snr_db"]
            best_m = m

    if best_m is not None:
        result.set_plot_tab_title("Gabor Ellipse Analysis")
        result.add_plot(
            title="Radial Profile vs Gaussian",
            y={
                "Measured Pulse Energy (dB)": best_m["shell_norm_db"],
                "Ideal Heisenberg-Gabor Logon (dB)": best_m["ideal_gauss_db"],
            },
            x=best_m["rho_centers"],
            x_label="Normalized Elliptical Radius ρ",
            x_units="r/r0",
            y_label="Normalized Power (dB)",
            primary_mode="TIME",
        )
        if len(tbp_t) >= 2:
            order = np.argsort(tbp_t)
            t_sorted = np.asarray(tbp_t)[order]
            v_sorted = np.asarray(tbp_v)[order]
            result.add_plot(
                title="Pulse TBP Timeline",
                y={
                    "Measured TBP (4π·σ_t·σ_f)": v_sorted,
                    "Heisenberg Minimum Limit (1.0)": np.ones_like(v_sorted),
                },
                x=t_sorted,
                x_label="Pulse Center Time",
                x_units="s",
                y_label="Time-Bandwidth Product",
                primary_mode="TIME",
            )

    result.log(
        f"[Ellipse Gabor Analyzer] Analyzed {len(tbp_v)} Ellipse overlay(s) "
        f"(snap={'ON' if snap_ellipses else 'OFF'})."
    )
    return result


# ---------------------------------------------------------------------------
# Workflow 2: Auto-Detect Localized Pulses -> Create Gabor Ellipses
# ---------------------------------------------------------------------------

def _detect_pulse_ellipses(
    samples: Optional[np.ndarray],
    info: PluginContext,
    threshold_db: float,
    containment_pct: float,
    max_duration_ms: float,
    lock_ellipses: bool,
    result: PluginResult,
) -> PluginResult:
    fs = float(info.sample_rate)
    fc = float(info.center_freq)
    max_dur_s = float(max_duration_ms) * 1e-3

    batch_dur = min(max(0.05, float(info.duration)), max(0.05, 2_000_000.0 / fs))
    overlap_dur = min(0.005, 0.1 * batch_dur)

    n_created = 0
    best_m: Optional[Dict[str, Any]] = None
    best_snr = -1e9
    tbp_t: List[float] = []
    tbp_v: List[float] = []

    def _process_chunk(chunk: np.ndarray, t0_chunk: float) -> None:
        nonlocal n_created, best_m, best_snr
        if len(chunk) < 64 or info.is_cancelled():
            return

        nperseg = min(512, max(32, 1 << int(np.clip(np.round(np.log2(int(info.fft_size or 256))), 5, 9))))
        while nperseg > 32 and nperseg > len(chunk) // 4:
            nperseg //= 2
        noverlap = nperseg // 2

        win = hann(nperseg, sym=False).astype(np.float64)
        psd_norm_db = 10.0 * np.log10(max(float(fs * np.sum(win ** 2)), 1e-30))
        win_sum_sq = max(float(np.sum(win)) ** 2, 1e-30)

        f_rel_un, t_rel, Z_un = sp_signal.stft(
            chunk,
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=noverlap,
            return_onesided=False,
            boundary=None,
            padded=False,
        )
        if Z_un.shape[1] < 3:
            return

        f_world = fc + np.fft.fftshift(f_rel_un)
        t_world = t0_chunk + t_rel
        df_bin = float(fs / nperseg)
        dt_hop = float(t_rel[1] - t_rel[0]) if len(t_rel) > 1 else float(nperseg / fs)

        Z_mag_sq = np.abs(np.fft.fftshift(Z_un, axes=0)) ** 2
        psd_lin = np.maximum(Z_mag_sq * win_sum_sq, 1e-30) / max(float(fs * np.sum(win ** 2)), 1e-30)

        f_lo_s = float(min(info.f_start, info.f_end))
        f_hi_s = float(max(info.f_start, info.f_end))
        in_f = (f_world >= f_lo_s) & (f_world <= f_hi_s)
        if not np.any(in_f):
            in_f = np.ones_like(f_world, dtype=bool)

        # Exact Exponential (chi2_2) median-to-mean CFAR noise floor + 2D Gaussian logon matched smoothing
        peak_chunk_lin = max(float(np.max(psd_lin[in_f, :])), 1e-30)
        noise_mean_lin = max(
            float(np.median(psd_lin[in_f, :])) / float(np.log(2.0)),
            peak_chunk_lin * 1e-8,
            1e-30,
        )
        noise_db = 10.0 * np.log10(noise_mean_lin)
        psd_smooth_lin = ndimage.gaussian_filter(psd_lin, sigma=0.80, mode="nearest")
        psd_smooth_db = 10.0 * np.log10(np.maximum(psd_smooth_lin, 1e-30))

        active = (psd_smooth_db > (noise_db + float(threshold_db))) & in_f[:, np.newaxis]
        active = ndimage.binary_closing(active, structure=np.ones((3, 3), dtype=bool), iterations=1)

        labeled, num_comp = ndimage.label(active, structure=np.ones((3, 3), dtype=bool))
        if num_comp == 0:
            return

        slices = ndimage.find_objects(labeled)
        for comp_idx, slc in enumerate(slices, start=1):
            if slc is None or info.is_cancelled():
                continue
            if n_created >= 250:
                break

            f_slc, t_slc = slc
            t0_b = float(t_world[t_slc.start]) - 0.5 * dt_hop
            t1_b = float(t_world[t_slc.stop - 1]) + 0.5 * dt_hop
            dur_b = t1_b - t0_b
            if dur_b > max_dur_s:
                continue

            sub_mask = labeled[f_slc, t_slc] == comp_idx
            if int(np.count_nonzero(sub_mask)) < 3:
                continue

            f0_b = float(f_world[f_slc.start]) - df_bin
            f1_b = float(f_world[f_slc.stop - 1]) + df_bin
            ct_init = 0.5 * (t0_b + t1_b)
            cf_init = 0.5 * (f0_b + f1_b)
            rt_init = max(0.65 * dur_b, dt_hop)
            rf_init = max(0.65 * (f1_b - f0_b), 1.5 * df_bin)

            pad_t = max(2.5 * rt_init, 4.0 * dt_hop)
            s0_c = max(0, int(round((ct_init - pad_t - t0_chunk) * fs)))
            s1_c = min(len(chunk), int(round((ct_init + pad_t - t0_chunk) * fs)))
            if s1_c - s0_c < 16:
                continue

            m = _analyze_elliptical_region(
                seg_wb=chunk[s0_c:s1_c],
                seg_t0=t0_chunk + s0_c / fs,
                fs=fs,
                fc_world=fc,
                t_center_init=ct_init,
                f_center_init=cf_init,
                r_t_init=rt_init,
                r_f_init=rf_init,
                containment_pct=containment_pct,
            )
            if m is None or m["peak_snr_db"] < threshold_db:
                continue

            n_created += 1
            tag, hover_md, meta, col_hex = _format_ellipse_annotation(
                n_created, m, containment_pct
            )
            # Ensure visual radii are at least visible on the STFT grid while storing exact Gabor radii in metadata
            vis_rt = max(m["rt_fit"], 0.35 * dt_hop)
            vis_rf = max(m["rf_fit"], 0.5 * df_bin)

            result.add(
                Ellipse(
                    t_center=m["mu_t"],
                    f_center=m["mu_f"],
                    t_radius=vis_rt,
                    f_radius=vis_rf,
                    color=col_hex,
                    alpha=0.22,
                    border_width=2,
                    display_str=tag,
                    hover_str=hover_md,
                    locked=bool(lock_ellipses),
                    z_order=8,
                    metadata=meta,
                    iq=m["iq_bb"],
                    fs=m["fs_bb"],
                )
            )
            tbp_t.append(m["mu_t"])
            tbp_v.append(m["tbp"])
            if m["snr_db"] > best_snr:
                best_snr = m["snr_db"]
                best_m = m

    if (
        samples is not None
        and len(samples) > 0
        and len(samples) <= 2_500_000
        and getattr(info, "_extract_iq_cb", None) is None
    ):
        _process_chunk(np.asarray(samples, dtype=np.complex64), float(info.t_start))
    else:
        for batch_iq, b_t0, _b_t1 in info.iter_batches(duration_s=batch_dur, overlap_s=overlap_dur):
            if info.is_cancelled():
                return result
            _process_chunk(batch_iq, b_t0)

    if best_m is not None:
        result.set_plot_tab_title("Gabor Pulse Ellipses")
        result.add_plot(
            title="Radial Profile vs Gaussian",
            y={
                "Strongest Pulse Radial Energy (dB)": best_m["shell_norm_db"],
                "Ideal Heisenberg-Gabor Logon (dB)": best_m["ideal_gauss_db"],
            },
            x=best_m["rho_centers"],
            x_label="Normalized Elliptical Radius ρ",
            x_units="r/r0",
            y_label="Normalized Power (dB)",
            primary_mode="TIME",
        )
        if len(tbp_t) >= 2:
            order = np.argsort(tbp_t)
            t_sorted = np.asarray(tbp_t)[order]
            v_sorted = np.asarray(tbp_v)[order]
            result.add_plot(
                title="Pulse TBP Timeline",
                y={
                    "Measured TBP (4π·σ_t·σ_f)": v_sorted,
                    "Heisenberg Minimum Limit (1.0)": np.ones_like(v_sorted),
                },
                x=t_sorted,
                x_label="Pulse Center Time",
                x_units="s",
                y_label="Time-Bandwidth Product",
                primary_mode="TIME",
            )

    if n_created == 0:
        result.log(
            "[Ellipse Gabor Analyzer] No localized pulses detected. "
            "Try lowering 'Pulse Detection Threshold (dB)' or increasing 'Max Pulse Duration (ms)'."
        )
    else:
        result.log(
            f"[Ellipse Gabor Analyzer] Fitted {n_created} Gabor Uncertainty Ellipse overlay(s) "
            f"({containment_pct:.0f}% 2D iso-energy contour)."
        )
    return result


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()
    fs = float(info.sample_rate)
    if fs <= 0.0:
        result.error("Invalid sample rate (fs <= 0).")
        return result

    mode = str(info.params.get("mode", MODE_AUTO))
    threshold_db = float(info.params.get("threshold_db", 10.0))
    containment_pct = float(info.params.get("containment_pct", 95.0))
    snap_ellipses = bool(info.params.get("snap_ellipses", True))
    max_duration_ms = float(info.params.get("max_duration_ms", 50.0))
    lock_ellipses = bool(info.params.get("lock_ellipses", False))

    t_lo_s = float(min(info.t_start, info.t_end))
    t_hi_s = float(max(info.t_start, info.t_end))
    ellipses_in_scope = [
        o
        for o in (info.overlays or [])
        if getattr(o, "visible", True)
        and o._shape_name() == "ELLIPSE"
        and getattr(o, "center", None) is not None
        and getattr(o, "radii", None) is not None
        and float(o.t_end) >= t_lo_s
        and float(o.t_start) <= t_hi_s
    ]

    if mode == MODE_AUTO:
        if ellipses_in_scope:
            return _analyze_existing_ellipses(
                ellipses=ellipses_in_scope,
                samples=samples,
                info=info,
                containment_pct=containment_pct,
                snap_ellipses=snap_ellipses,
                result=result,
            )
        return _detect_pulse_ellipses(
            samples=samples,
            info=info,
            threshold_db=threshold_db,
            containment_pct=containment_pct,
            max_duration_ms=max_duration_ms,
            lock_ellipses=lock_ellipses,
            result=result,
        )

    if mode == MODE_ANALYZE:
        if not ellipses_in_scope:
            result.warning(
                "No Ellipse overlays found in the active scope.\n\n"
                "Draw an Ellipse overlay around a pulse/transient on the spectrogram, "
                "or switch Operation Mode to 'Detect Localized Pulses -> Create Ellipses'."
            )
            return result
        return _analyze_existing_ellipses(
            ellipses=ellipses_in_scope,
            samples=samples,
            info=info,
            containment_pct=containment_pct,
            snap_ellipses=snap_ellipses,
            result=result,
        )

    return _detect_pulse_ellipses(
        samples=samples,
        info=info,
        threshold_db=threshold_db,
        containment_pct=containment_pct,
        max_duration_ms=max_duration_ms,
        lock_ellipses=lock_ellipses,
        result=result,
    )

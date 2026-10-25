"""iqview/plugins/builtin/polygon_tf_filter.py

Built-in IQView Plugin: Polygon TF Filter & Sweep Tracker.

Demonstrates why `Polygon` overlays are essential in RF Time-Frequency analysis:
1. Non-Stationary Signal Tracking: Axis-aligned `Rect` boxes fail on chirps,
   FMCW radar sweeps, VCO slews, Doppler-drifting passes, and diagonal jammers,
   enclosing up to 90%+ empty noise and co-channel bursts. Tight `Polygon`
   ribbons follow the exact (t, f) trajectory.
2. Surgical 2D Time-Frequency Filtering: Uses COLA-compliant Short-Time Fourier
   Transform (STFT -> feathered 2D Polygon Gabor mask -> ISTFT) to either
   isolate a non-stationary signal inside a `Polygon` or surgically notch/erase
   diagonal interference colliding with a packet.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy import ndimage, signal as sp_signal
from scipy.signal.windows import hann

from iqview import PluginContext, PluginResult
from iqview.overlays import Polygon


PLUGIN_NAME = "Polygon TF Filter & Sweep Tracker"
PLUGIN_DESCRIPTION = (
    "Surgical 2D STFT time-frequency masking (isolate or notch) inside Polygon "
    "overlays, plus automatic non-stationary sweep/chirp Polygon contour detection."
)
PLUGIN_CATEGORY = "Analysis"
PLUGIN_NEEDS_WIDEBAND_IQ = False
PLUGIN_BATCH_SECONDS = None
PLUGIN_RUN_ON_MAIN_THREAD = False


PLUGIN_DOC = """# Polygon TF Filter & Sweep Tracker

Showcases and utilizes **`Polygon`** overlays for **non-stationary RF signal analysis** and **surgical 2D Time-Frequency (Gabor) filtering** — tasks where standard axis-aligned `Rect` overlays fundamentally fail.

### Why Use a `Polygon` Instead of a `Rect`?

A rectangular `Rect` overlay assumes a signal has constant center frequency $[f_{\\min}, f_{\\max}]$ over its entire duration $[t_{\\text{start}}, t_{\\text{end}}]$. For **swept or drifting signals** (FMCW radar chirps, LoRa/chirpsounder sweeps, VCO slews, LEO satellite Doppler curves, or swept-tone jammers):
- A bounding `Rect` encloses up to **85–98% empty noise** (and colliding co-channel bursts), degrading extracted SNR by **10–20 dB**.
- A 1D bandpass filter cannot separate a diagonal chirp from a stationary packet sharing the same frequency band.
- A **`Polygon` overlay** wraps tightly around the slanted, V-shaped, or irregular $(t, f)$ ridge, enabling true **2D time-varying filtering**.

---

### Dual Operating Modes

1. **Surgical 2D STFT Filtering (When `Polygon` Overlays Exist)**:
   - Draw one or more **Polygon** overlays on the spectrogram (and drag individual vertices to wrap a slanted chirp, curved trajectory, or interference blob).
   - **Isolate Inside Polygons (2D Pass-Band)**: Applies a COLA-compliant 75%-overlap Hann STFT, masks *only* the $(t, f)$ bins inside each `Polygon` (with smooth cosine/spline edge feathering to prevent Gibbs ringing), reconstructs the clean time-domain IQ via `istft`, caches baseband `o.iq` on the overlay, and compares **Surgical Polygon** vs. **Naive Bounding Rect** SNR!
   - **Notch / Erase Inside Polygons (2D Stop-Band)**: Surgically erases interference inside the `Polygon`(s) — e.g., removing a sweeping FMCW radar chirp that cuts straight across a communication packet — while leaving surrounding $(t, f)$ energy untouched.

2. **Auto-Detect Sweeps & Chirps $\\rightarrow$ Create `Polygon` Overlays**:
   - When no `Polygon` overlays exist in scope (or when explicitly selected), scans the spectrogram using 8-connected ridge/contour segmentation and Ramer-Douglas-Peucker vertex simplification.
   - Wraps non-stationary chirps, sweeps, and drifting emissions in tight, vertex-editable **`Polygon` ribbons**, reporting **Sweep Rate** ($\\text{kHz/ms}$), **Instantaneous BW**, **Fill Ratio**, and **SNR Advantage vs. `Rect` (dB)**.

### Parameters
- **Mode**: Auto (filters existing `Polygon`s if present, otherwise detects sweeps), Isolate, Notch/Erase, or Detect Sweeps.
- **Detection Threshold (dB)**: SNR above noise floor for automatic sweep contour tracking.
- **Mask Attenuation (dB)**: Out-of-polygon (Isolate) or in-polygon (Notch) suppression depth in dB.
- **Edge Feathering (bins)**: Soft 2D taper width in STFT bins to suppress time-frequency ringing.
- **Only Non-Stationary Sweeps**: Skip flat constant-frequency bursts during auto-detection so only tilted/drifting/irregular signals receive `Polygon` contours.
- **Open Reconstructed Tab**: Optionally launch a native **Time Domain** or **Frequency Domain** tab with the surgically filtered IQ waveform.
"""


MODE_AUTO = "Auto (Filter Drawn Polygons, or Detect Sweeps)"
MODE_ISOLATE = "Isolate Inside Polygons (2D Pass-Band)"
MODE_NOTCH = "Notch / Erase Inside Polygons (2D Stop-Band)"
MODE_DETECT = "Detect Sweeps & Chirps -> Create Polygons"

TAB_NONE = "None (Plots & Overlay Cache Only)"
TAB_TIME = "Time Domain Tab"
TAB_FREQ = "Frequency Domain Tab"


PLUGIN_PARAMS = {
    "mode": {
        "type": "choice",
        "default": MODE_AUTO,
        "choices": [MODE_AUTO, MODE_ISOLATE, MODE_NOTCH, MODE_DETECT],
        "label": "Operation Mode",
        "tooltip": "Auto filters drawn Polygons if any exist in scope, otherwise auto-detects sweeps into Polygons.",
    },
    "threshold_db": {
        "type": "float",
        "default": 10.0,
        "min": 3.0,
        "max": 60.0,
        "label": "Sweep Detection Threshold (dB)",
        "tooltip": "Minimum bin SNR (dB above noise floor) when auto-detecting sweep contours.",
    },
    "atten_db": {
        "type": "float",
        "default": 60.0,
        "min": 10.0,
        "max": 120.0,
        "label": "Surgical Mask Attenuation (dB)",
        "tooltip": "Suppression depth (dB) applied outside (Isolate) or inside (Notch) the Polygon.",
    },
    "feather_bins": {
        "type": "int",
        "default": 2,
        "min": 0,
        "max": 12,
        "label": "Edge Feathering (STFT bins)",
        "tooltip": "2D Gabor taper width in STFT bins along polygon edges to prevent Gibbs ringing.",
    },
    "only_nonstationary": {
        "type": "bool",
        "default": True,
        "label": "Only Swept / Non-Stationary Signals",
        "tooltip": "In Detect mode, only emit Polygons for signals with frequency drift/tilt or non-rectangular shape.",
    },
    "open_output_tab": {
        "type": "choice",
        "default": TAB_NONE,
        "choices": [TAB_NONE, TAB_TIME, TAB_FREQ],
        "label": "Open Reconstructed IQ In",
        "tooltip": "Optionally open a native Time Domain or Frequency Domain tab with the surgically filtered IQ.",
    },
    "lock_polygons": {
        "type": "bool",
        "default": False,
        "label": "Lock Detected Polygons",
        "tooltip": "If False, auto-detected Polygon vertices can be dragged interactively on the spectrogram.",
    },
}


# ---------------------------------------------------------------------------
# Pure Geometry & DSP Helpers
# ---------------------------------------------------------------------------

def _polygon_shoelace_area(pts: List[Tuple[float, float]]) -> float:
    """Compute exact 2D area (s * Hz) of a polygon via the Shoelace formula."""
    if len(pts) < 3:
        return 0.0
    arr = np.asarray(pts, dtype=np.float64)
    x = arr[:, 0]
    y = arr[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _rdp_simplify(pts: np.ndarray, eps: float) -> np.ndarray:
    """Iterative Ramer-Douglas-Peucker polyline simplification in 2D."""
    n = len(pts)
    if n <= 3 or eps <= 0.0:
        return pts

    keep = np.zeros(n, dtype=bool)
    keep[0] = True
    keep[-1] = True
    stack: List[Tuple[int, int]] = [(0, n - 1)]

    while stack:
        i0, i1 = stack.pop()
        if i1 - i0 <= 1:
            continue
        p0 = pts[i0]
        p1 = pts[i1]
        seg = p1 - p0
        seg_len_sq = float(seg[0] * seg[0] + seg[1] * seg[1])
        sub = pts[i0 + 1 : i1] - p0
        if seg_len_sq <= 1e-24:
            dists = np.hypot(sub[:, 0], sub[:, 1])
        else:
            cross = np.abs(sub[:, 0] * seg[1] - sub[:, 1] * seg[0])
            dists = cross / np.sqrt(seg_len_sq)

        rel_idx = int(np.argmax(dists))
        max_d = float(dists[rel_idx])
        if max_d > eps:
            split = i0 + 1 + rel_idx
            keep[split] = True
            stack.append((i0, split))
            stack.append((split, i1))

    return pts[keep]


def _simplify_closed_polygon(
    vertices: List[Tuple[float, float]],
    rel_tol: float = 0.018,
    max_vertices: int = 20,
) -> List[Tuple[float, float]]:
    """Simplify a closed polygon in normalized (t, f) coordinates while keeping >= 4 vertices."""
    if len(vertices) <= 6:
        return [(float(t), float(f)) for t, f in vertices]

    arr = np.asarray(vertices, dtype=np.float64)
    t_span = max(float(np.ptp(arr[:, 0])), 1e-12)
    f_span = max(float(np.ptp(arr[:, 1])), 1e-12)
    norm = np.column_stack([(arr[:, 0] - arr[0, 0]) / t_span, (arr[:, 1] - arr[0, 1]) / f_span])

    # Split at the temporally farthest vertex from vertex 0 so both halves simplify cleanly
    mid_idx = int(np.argmax(np.hypot(norm[:, 0], norm[:, 1])))
    if mid_idx <= 0 or mid_idx >= len(norm) - 1:
        mid_idx = len(norm) // 2

    tol = float(rel_tol)
    for _ in range(6):
        h1 = _rdp_simplify(norm[: mid_idx + 1], tol)
        h2 = _rdp_simplify(np.vstack([norm[mid_idx:], norm[0:1]]), tol)
        merged_idx_pts = np.vstack([h1[:-1], h2[:-1]])
        if len(merged_idx_pts) <= max_vertices:
            break
        tol *= 1.45

    if len(merged_idx_pts) < 4:
        return [(float(t), float(f)) for t, f in vertices[:max_vertices]]

    out_t = merged_idx_pts[:, 0] * t_span + arr[0, 0]
    out_f = merged_idx_pts[:, 1] * f_span + arr[0, 1]
    return [(float(t), float(f)) for t, f in zip(out_t, out_f)]


def _rasterize_polygon_mask(
    t_world: np.ndarray,
    f_world: np.ndarray,
    vertices: List[Tuple[float, float]],
) -> np.ndarray:
    """
    Vectorized Jordan ray-casting of a closed (t, f) polygon onto a 2D STFT grid
    of shape `(len(f_world), len(t_world))`, with thin-ribbon safeguard so narrow
    polygons never fall between discrete FFT bins.
    """
    n_f = len(f_world)
    n_t = len(t_world)
    mask = np.zeros((n_f, n_t), dtype=bool)
    if len(vertices) < 3 or n_f == 0 or n_t == 0:
        return mask

    pts = np.asarray(vertices, dtype=np.float64)
    t_min, t_max = float(np.min(pts[:, 0])), float(np.max(pts[:, 0]))
    f_min, f_max = float(np.min(pts[:, 1])), float(np.max(pts[:, 1]))

    m0 = max(0, int(np.searchsorted(t_world, t_min, side="left")) - 1)
    m1 = min(n_t, int(np.searchsorted(t_world, t_max, side="right")) + 1)
    k0 = max(0, int(np.searchsorted(f_world, f_min, side="left")) - 1)
    k1 = min(n_f, int(np.searchsorted(f_world, f_max, side="right")) + 1)
    if m1 <= m0 or k1 <= k0:
        return mask

    t_sub = t_world[m0:m1][np.newaxis, :]  # (1, M_sub)
    f_sub = f_world[k0:k1][:, np.newaxis]  # (K_sub, 1)
    inside = np.zeros((k1 - k0, m1 - m0), dtype=bool)

    n_v = len(pts)
    for i in range(n_v):
        t1_v, f1_v = pts[i]
        t2_v, f2_v = pts[(i + 1) % n_v]
        cond = (f1_v > f_sub) != (f2_v > f_sub)
        df = f2_v - f1_v
        if abs(df) > 1e-30:
            t_x = (t2_v - t1_v) * (f_sub - f1_v) / df + t1_v
            inside ^= cond & (t_sub < t_x)

    # Thin-ribbon safeguard: if a vertical time line intersects polygon edges
    # but the ribbon is thinner than 1 FFT bin, ensure the nearest bin is active.
    t_vec = t_world[m0:m1]
    for m_local, tm in enumerate(t_vec):
        if inside[:, m_local].any():
            continue
        f_crossings: List[float] = []
        for i in range(n_v):
            t1_v, f1_v = pts[i]
            t2_v, f2_v = pts[(i + 1) % n_v]
            if (t1_v <= tm <= t2_v) or (t2_v <= tm <= t1_v):
                dt = t2_v - t1_v
                if abs(dt) > 1e-30:
                    alpha = (tm - t1_v) / dt
                    if 0.0 <= alpha <= 1.0:
                        f_crossings.append(float(f1_v + alpha * (f2_v - f1_v)))
        if len(f_crossings) >= 2:
            f_mid = 0.5 * (min(f_crossings) + max(f_crossings))
            k_near = int(np.clip(np.searchsorted(f_world, f_mid), k0, k1 - 1)) - k0
            inside[k_near, m_local] = True

    mask[k0:k1, m0:m1] = inside
    return mask


def _smooth_2d_mask(mask_bool: np.ndarray, feather_bins: int) -> np.ndarray:
    """Apply smooth 2D B-spline Gabor feathering to a binary mask in [0.0, 1.0]."""
    m_float = mask_bool.astype(np.float64)
    if feather_bins <= 0:
        return m_float
    size = 2 * int(feather_bins) + 1
    # Two passes of uniform_filter produce a smooth C1 tent/quadratic B-spline taper
    smoothed = ndimage.uniform_filter(m_float, size=size, mode="nearest")
    smoothed = ndimage.uniform_filter(smoothed, size=max(3, feather_bins + 1), mode="nearest")
    return np.clip(smoothed, 0.0, 1.0)


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


def _choose_nperseg(n_samples: int, fft_hint: int) -> int:
    """Select power-of-2 STFT segment size balancing TF resolution and frame count."""
    base = int(fft_hint) if fft_hint and fft_hint >= 64 else 512
    p2 = 1 << int(np.clip(np.round(np.log2(base)), 6, 12))
    while p2 > 64 and p2 > n_samples // 4:
        p2 //= 2
    return max(32, min(p2, n_samples))


def _welch_psd_db_hz(iq: np.ndarray, fs: float, nfft: int = 1024) -> Tuple[np.ndarray, np.ndarray]:
    """Compute true Power Spectral Density in dB/Hz (`10*log10(fs * sum(w^2))` invariant)."""
    n = len(iq)
    nper = min(nfft, max(32, 1 << int(np.floor(np.log2(max(32, n))))))
    win = hann(nper, sym=False).astype(np.float64)
    win_norm = max(float(fs * np.sum(win ** 2)), 1e-30)
    step = max(1, nper // 2)
    acc = np.zeros(nper, dtype=np.float64)
    cnt = 0
    for s0 in range(0, n - nper + 1, step):
        seg = iq[s0 : s0 + nper] * win
        acc += np.abs(np.fft.fft(seg)) ** 2
        cnt += 1
    if cnt == 0:
        padded = np.zeros(nper, dtype=np.complex128)
        padded[: min(n, nper)] = iq[: min(n, nper)]
        acc = np.abs(np.fft.fft(padded * win)) ** 2
        cnt = 1
    psd_lin = np.fft.fftshift(acc / (cnt * win_norm))
    freqs = np.fft.fftshift(np.fft.fftfreq(nper, d=1.0 / fs))
    psd_db = 10.0 * np.log10(np.maximum(psd_lin, 1e-30))
    return freqs, psd_db


# ---------------------------------------------------------------------------
# Engine 1: Surgical 2D STFT Filtering on Existing Polygon Overlays
# ---------------------------------------------------------------------------

def _run_surgical_filter(
    polys: List[Any],
    samples: Optional[np.ndarray],
    info: PluginContext,
    is_notch: bool,
    atten_db: float,
    feather_bins: int,
    open_output_tab: str,
    result: PluginResult,
) -> PluginResult:
    fs = float(info.sample_rate)
    fc = float(info.center_freq)
    floor_gain = float(10.0 ** (-float(atten_db) / 20.0))

    if is_notch:
        # Notch / Erase mode: clean a contiguous span covering the polygons (or active view)
        t_min_all = min(float(o.t_start) for o in polys)
        t_max_all = max(float(o.t_end) for o in polys)
        pad_s = min(0.05, 0.15 * max(t_max_all - t_min_all, 1e-3))
        t_win_0 = max(float(info.t_start), t_min_all - pad_s)
        t_win_1 = min(float(info.t_end), t_max_all + pad_s)

        # Bound memory to at most 4M samples (~32 MB complex64)
        max_dur = 4_000_000.0 / fs
        if (t_win_1 - t_win_0) > max_dur:
            t_win_1 = t_win_0 + max_dur

        info.progress(15.0, "Extracting IQ for surgical 2D Polygon notch...")
        raw_iq, actual_t0 = _extract_iq_slice(samples, info, t_win_0, t_win_1)
        if len(raw_iq) < 64:
            result.warning("Selected Polygon region contains too few IQ samples (< 64) to filter.")
            return result

        n_orig = len(raw_iq)
        nperseg = _choose_nperseg(n_orig, info.fft_size)
        noverlap = (3 * nperseg) // 4

        info.progress(35.0, "Computing COLA 2D STFT & rasterizing Polygon mask(s)...")
        f_rel_unshifted, t_rel, Z_unshifted = sp_signal.stft(
            raw_iq,
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=noverlap,
            return_onesided=False,
            boundary="zeros",
            padded=True,
        )
        f_world = fc + np.fft.fftshift(f_rel_unshifted)
        t_world = actual_t0 + t_rel
        Z_shifted = np.fft.fftshift(Z_unshifted, axes=0)
        pwr_grid = np.abs(Z_shifted) ** 2

        union_mask = np.zeros(Z_shifted.shape, dtype=bool)
        noise_med = max(float(np.percentile(pwr_grid, 30)), 1e-30)

        for idx, o in enumerate(polys):
            if info.is_cancelled():
                return result
            m_poly = _rasterize_polygon_mask(t_world, f_world, list(o.points))
            union_mask |= m_poly

            in_pwr = float(np.mean(pwr_grid[m_poly])) if np.any(m_poly) else noise_med
            excised_inr_db = float(10.0 * np.log10(max(in_pwr / noise_med, 1e-12)))
            p_area = _polygon_shoelace_area(list(o.points))
            r_area = max(float(o.duration * o.bandwidth), 1e-12)
            fill_pct = float(np.clip(100.0 * p_area / r_area, 0.01, 100.0))

            meta = dict(o.metadata or {})
            meta.update({
                "tf_filter_mode": "notch",
                "excised_inr_db": round(excised_inr_db, 2),
                "atten_db": round(float(atten_db), 1),
                "polygon_fill_pct": round(fill_pct, 1),
                "num_vertices": len(o.points),
            })
            hover_md = (
                f"### Surgical Polygon Notch #{idx + 1}\n"
                f"| Metric | Value |\n"
                f"| :--- | :--- |\n"
                f"| **Mode** | 2D Stop-Band (Interference Erased) |\n"
                f"| **Excised Interference** | {excised_inr_db:+.1f} dB above noise |\n"
                f"| **Notch Depth** | -{atten_db:.1f} dB |\n"
                f"| **TF Area vs. Rect** | {fill_pct:.1f}% ({100.0 - fill_pct:.1f}% spared!) |\n"
                f"| **Vertices** | {len(o.points)} |"
            )
            tag = o.display_str or f"Notched (-{atten_db:.0f} dB)"
            result.update(o.id, display_str=tag, hover_str=hover_md, metadata=meta)

        info.progress(65.0, "Applying feathered 2D Gabor stop-band & inverse STFT...")
        m_smooth = _smooth_2d_mask(union_mask, feather_bins)
        gain_2d = floor_gain + (1.0 - floor_gain) * (1.0 - m_smooth)
        Z_filt_unshifted = np.fft.ifftshift(Z_shifted * gain_2d, axes=0)
        _, rec_iq = sp_signal.istft(
            Z_filt_unshifted,
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=noverlap,
            input_onesided=False,
            boundary=True,
        )
        clean_iq = np.asarray(rec_iq[:n_orig], dtype=np.complex64)

        # Build comparison plots
        info.progress(85.0, "Generating Before vs. After comparison plots...")
        freqs_rel, psd_before = _welch_psd_db_hz(raw_iq, fs)
        _, psd_after = _welch_psd_db_hz(clean_iq, fs)
        result.set_plot_tab_title("Polygon TF Notch")
        result.add_plot(
            title="Spectrum (Before vs Notched)",
            y={"Before Polygon Notch": psd_before, "After Surgical Notch": psd_after},
            x=fc + freqs_rel,
            x_label="Frequency",
            x_units="Hz",
            y_label="PSD (dB/Hz)",
            primary_mode="FREQ",
        )

        dec = max(1, n_orig // 4000)
        t_env = actual_t0 + (np.arange(0, n_orig, dec) / fs)
        env_before = 10.0 * np.log10(np.maximum(np.abs(raw_iq[::dec]) ** 2, 1e-12))
        env_after = 10.0 * np.log10(np.maximum(np.abs(clean_iq[::dec]) ** 2, 1e-12))
        result.add_plot(
            title="Power Envelope",
            y={"Raw Envelope (dB)": env_before, "After Polygon Notch (dB)": env_after},
            x=t_env,
            x_label="Time",
            x_units="s",
            y_label="Power (dB)",
            primary_mode="TIME",
        )

        if open_output_tab == TAB_TIME:
            result.open_time_domain(clean_iq, fs, t_start=actual_t0, title="Polygon Notched IQ")
        elif open_output_tab == TAB_FREQ:
            result.open_freq_domain(clean_iq, fs, fc=fc, title="Polygon Notched Spectrum")

        result.log(
            f"[Polygon TF Filter] Surgically notched {len(polys)} Polygon region(s) "
            f"over [{actual_t0:.4f}s, {actual_t0 + n_orig / fs:.4f}s] (-{atten_db:.0f} dB)."
        )
        return result

    # --- Isolate (Pass-Band) Mode: Surgically extract each Polygon ---
    n_polys = len(polys)
    best_plot_bundle: Optional[Dict[str, Any]] = None
    best_snr = -1e9
    total_gain_db: List[float] = []

    for idx, o in enumerate(polys):
        if info.is_cancelled():
            return result
        info.progress(
            10.0 + 75.0 * (idx / max(1, n_polys)),
            f"Surgically isolating Polygon {idx + 1}/{n_polys}...",
        )

        t0_p, t1_p = float(o.t_start), float(o.t_end)
        f0_p, f1_p = float(o.f_start), float(o.f_end)
        dur_p = t1_p - t0_p
        bw_p = f1_p - f0_p
        if dur_p <= 0.0 or bw_p <= 0.0:
            continue

        # Bound per-polygon extraction to 4M samples max
        if dur_p * fs > 4_000_000:
            t1_p = t0_p + 4_000_000.0 / fs

        pad_s = min(0.01, 0.1 * dur_p)
        raw_pad, pad_t0 = _extract_iq_slice(
            samples, info, max(0.0, t0_p - pad_s), t1_p + pad_s
        )
        if len(raw_pad) < 32:
            continue

        n_pad = len(raw_pad)
        nperseg = _choose_nperseg(n_pad, info.fft_size)
        noverlap = (3 * nperseg) // 4

        f_rel_un, t_rel, Z_un = sp_signal.stft(
            raw_pad,
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=noverlap,
            return_onesided=False,
            boundary="zeros",
            padded=True,
        )
        f_world = fc + np.fft.fftshift(f_rel_un)
        t_world = pad_t0 + t_rel
        Z_sh = np.fft.fftshift(Z_un, axes=0)
        pwr_grid = np.abs(Z_sh) ** 2

        m_poly = _rasterize_polygon_mask(t_world, f_world, list(o.points))
        if not np.any(m_poly):
            continue

        # Also build the naive Bounding-Rect mask [t0_p..t1_p] x [f0_p..f1_p] for comparison!
        m_rect = (
            (t_world[np.newaxis, :] >= t0_p)
            & (t_world[np.newaxis, :] <= t1_p)
            & (f_world[:, np.newaxis] >= f0_p)
            & (f_world[:, np.newaxis] <= f1_p)
        )

        out_mask = ~m_poly
        noise_bin = (
            float(np.median(pwr_grid[out_mask])) / float(np.log(2.0))
            if np.any(out_mask)
            else float(np.percentile(pwr_grid, 20))
        )
        mean_in_pwr = max(float(np.mean(pwr_grid[m_poly])), 1e-30)
        noise_bin = max(noise_bin, float(np.max(pwr_grid[m_poly])) * 1e-8, 1e-30)
        snr_poly_db = float(10.0 * np.log10(max((mean_in_pwr - noise_bin) / noise_bin, 1e-6)))

        # Measure instantaneous frequency ridge & sweep rate inside the polygon
        active_cols = np.where(np.any(m_poly, axis=0))[0]
        ridge_t: List[float] = []
        ridge_f: List[float] = []
        ridge_w: List[float] = []
        for mc in active_cols:
            ks = np.where(m_poly[:, mc])[0]
            w_col = np.maximum(pwr_grid[ks, mc] - noise_bin, 0.0)
            w_sum = float(np.sum(w_col))
            if w_sum > 1e-30:
                fc_col = float(np.sum(f_world[ks] * w_col) / w_sum)
                ridge_t.append(float(t_world[mc]))
                ridge_f.append(fc_col)
                ridge_w.append(w_sum)

        sweep_rate_khz_ms = 0.0
        if len(ridge_t) >= 2:
            rt = np.asarray(ridge_t) - ridge_t[0]
            rf = np.asarray(ridge_f)
            rw = np.asarray(ridge_w)
            w_norm = rw / max(float(np.sum(rw)), 1e-30)
            t_bar = float(np.sum(w_norm * rt))
            f_bar = float(np.sum(w_norm * rf))
            denom_t = float(np.sum(w_norm * (rt - t_bar) ** 2))
            if denom_t > 1e-24:
                slope_hz_s = float(np.sum(w_norm * (rt - t_bar) * (rf - f_bar)) / denom_t)
                sweep_rate_khz_ms = slope_hz_s / 1e6  # 1 MHz/s == 1 kHz/ms

        p_area = _polygon_shoelace_area(list(o.points))
        r_area = max(dur_p * bw_p, 1e-12)
        fill_ratio = float(np.clip(p_area / r_area, 1e-4, 1.0))
        snr_advantage_db = float(-10.0 * np.log10(fill_ratio))
        total_gain_db.append(snr_advantage_db)

        # Reconstruct surgical Polygon-isolated IQ vs naive Rect-isolated IQ
        m_smooth = _smooth_2d_mask(m_poly, feather_bins)
        gain_poly = floor_gain + (1.0 - floor_gain) * m_smooth
        _, rec_poly_pad = sp_signal.istft(
            np.fft.ifftshift(Z_sh * gain_poly, axes=0),
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=noverlap,
            input_onesided=False,
            boundary=True,
        )
        rec_poly_pad = np.asarray(rec_poly_pad[:n_pad], dtype=np.complex64)

        gain_rect = floor_gain + (1.0 - floor_gain) * m_rect.astype(np.float64)
        _, rec_rect_pad = sp_signal.istft(
            np.fft.ifftshift(Z_sh * gain_rect, axes=0),
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=noverlap,
            input_onesided=False,
            boundary=True,
        )
        rec_rect_pad = np.asarray(rec_rect_pad[:n_pad], dtype=np.complex64)

        # Crop back from padded window to exact [t0_p, t1_p]
        c0 = max(0, int(round((t0_p - pad_t0) * fs)))
        c1 = min(n_pad, max(c0 + 2, int(round((t1_p - pad_t0) * fs))))
        iq_poly_wb = rec_poly_pad[c0:c1]
        iq_rect_wb = rec_rect_pad[c0:c1]
        iq_raw_wb = raw_pad[c0:c1]
        crop_t0 = pad_t0 + c0 / fs

        # Mix isolated signal to overlay f_center and decimate to overlay bandwidth for `o.iq`
        f_center_p = float(o.f_center)
        f_off = f_center_p - fc
        t_local = np.arange(len(iq_poly_wb), dtype=np.float64) / fs
        iq_bb = (iq_poly_wb * np.exp(-2j * np.pi * f_off * t_local)).astype(np.complex64)
        out_fs = fs
        if 0.0 < bw_p < fs * 0.95 and len(iq_bb) >= 16:
            target_len = max(8, int(round(len(iq_bb) * (bw_p / fs))))
            iq_bb = np.asarray(sp_signal.resample(iq_bb, target_len), dtype=np.complex64)
            out_fs = float(len(iq_bb)) / max(len(iq_poly_wb) / fs, 1e-12)

        meta = dict(o.metadata or {})
        meta.update({
            "tf_filter_mode": "isolate",
            "in_polygon_snr_db": round(snr_poly_db, 2),
            "snr_gain_vs_rect_db": round(snr_advantage_db, 2),
            "polygon_fill_pct": round(fill_ratio * 100.0, 1),
            "sweep_rate_khz_per_ms": round(sweep_rate_khz_ms, 3),
            "num_vertices": len(o.points),
            "sample_rate_hz": round(out_fs, 2),
        })
        hover_md = (
            f"### Surgical Polygon Isolation #{idx + 1}\n"
            f"| Metric | Value |\n"
            f"| :--- | :--- |\n"
            f"| **In-Polygon SNR** | {snr_poly_db:+.1f} dB |\n"
            f"| **Noise Rejected vs. Rect** | **+{snr_advantage_db:.1f} dB** ({fill_ratio * 100.0:.1f}% fill) |\n"
            f"| **Sweep Slope** | {sweep_rate_khz_ms:+.2f} kHz/ms |\n"
            f"| **Vertices** | {len(o.points)} |\n"
            f"| **Cached Baseband IQ** | {len(iq_bb):,} samples @ {out_fs / 1e3:.1f} kHz |"
        )
        tag = (
            f"Poly SNR {snr_poly_db:.1f}dB (+{snr_advantage_db:.1f}dB vs Rect)"
            if snr_advantage_db >= 0.5
            else f"Poly SNR {snr_poly_db:.1f}dB"
        )
        result.update(
            o.id,
            display_str=tag,
            hover_str=hover_md,
            metadata=meta,
            iq=iq_bb,
            fs=out_fs,
        )

        if snr_poly_db > best_snr:
            best_snr = snr_poly_db
            best_plot_bundle = {
                "raw": iq_raw_wb,
                "rect": iq_rect_wb,
                "poly": iq_poly_wb,
                "t0": crop_t0,
                "ridge_t": np.asarray(ridge_t, dtype=np.float64),
                "ridge_f": np.asarray(ridge_f, dtype=np.float64),
                "snr_gain": snr_advantage_db,
            }

    if best_plot_bundle is not None:
        raw_w = best_plot_bundle["raw"]
        rect_w = best_plot_bundle["rect"]
        poly_w = best_plot_bundle["poly"]
        t0_b = best_plot_bundle["t0"]

        freqs_rel, psd_raw = _welch_psd_db_hz(raw_w, fs)
        _, psd_rect = _welch_psd_db_hz(rect_w, fs)
        _, psd_poly = _welch_psd_db_hz(poly_w, fs)

        result.set_plot_tab_title("Polygon TF Isolate")
        result.add_plot(
            title="Spectrum (Rect vs Polygon)",
            y={
                "Surgical Polygon Isolate": psd_poly,
                "Naive Bounding Rect": psd_rect,
                "Unfiltered Wideband": psd_raw,
            },
            x=fc + freqs_rel,
            x_label="Frequency",
            x_units="Hz",
            y_label="PSD (dB/Hz)",
            primary_mode="FREQ",
        )

        n_w = len(poly_w)
        dec = max(1, n_w // 4000)
        t_ax = t0_b + (np.arange(0, n_w, dec) / fs)
        env_rect = 10.0 * np.log10(np.maximum(np.abs(rect_w[::dec]) ** 2, 1e-12))
        env_poly = 10.0 * np.log10(np.maximum(np.abs(poly_w[::dec]) ** 2, 1e-12))
        result.add_plot(
            title="Envelope (Rect vs Polygon)",
            y={
                "Surgical Polygon (dB)": env_poly,
                "Naive Bounding Rect (dB)": env_rect,
            },
            x=t_ax,
            x_label="Time",
            x_units="s",
            y_label="Power (dB)",
            primary_mode="TIME",
        )

        if len(best_plot_bundle["ridge_t"]) >= 2:
            result.add_plot(
                title="Tracked Ridge f(t)",
                y={"In-Polygon Ridge Frequency": best_plot_bundle["ridge_f"]},
                x=best_plot_bundle["ridge_t"],
                x_label="Time",
                x_units="s",
                y_label="Frequency (Hz)",
                primary_mode="TIME",
            )

        if open_output_tab == TAB_TIME:
            result.open_time_domain(poly_w, fs, t_start=t0_b, title="Polygon Isolated IQ")
        elif open_output_tab == TAB_FREQ:
            result.open_freq_domain(poly_w, fs, fc=fc, title="Polygon Isolated Spectrum")

    avg_gain = float(np.mean(total_gain_db)) if total_gain_db else 0.0
    result.log(
        f"[Polygon TF Filter] Surgically isolated {n_polys} Polygon overlay(s) "
        f"(mean noise rejection advantage vs. Rect: +{avg_gain:.1f} dB)."
    )
    return result


# ---------------------------------------------------------------------------
# Engine 2: Automatic Sweep / Chirp Contour Polygon Detector
# ---------------------------------------------------------------------------

def _detect_sweep_polygons(
    samples: Optional[np.ndarray],
    info: PluginContext,
    threshold_db: float,
    only_nonstationary: bool,
    lock_polygons: bool,
    result: PluginResult,
) -> PluginResult:
    fs = float(info.sample_rate)
    fc = float(info.center_freq)

    # Stream in memory-safe batches (~2M samples max per chunk)
    batch_dur = min(max(0.05, float(info.duration)), max(0.05, 2_000_000.0 / fs))
    overlap_dur = min(0.005, 0.1 * batch_dur)

    detected_tracks_t: Dict[str, np.ndarray] = {}
    detected_tracks_f: Dict[str, np.ndarray] = {}
    n_created = 0

    palette = ["#00E5FF", "#FF9100", "#76FF03", "#EA80FC", "#FFD740", "#FF5252"]

    def _process_chunk(chunk: np.ndarray, t0_chunk: float) -> None:
        nonlocal n_created
        if len(chunk) < 128 or info.is_cancelled():
            return

        nperseg = _choose_nperseg(len(chunk), min(int(info.fft_size or 512), 1024))
        noverlap = nperseg // 2
        win = hann(nperseg, sym=False).astype(np.float64)
        psd_norm_db = 10.0 * np.log10(max(float(fs * np.sum(win ** 2)), 1e-30))

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
        if Z_un.shape[1] < 4:
            return

        f_world = fc + np.fft.fftshift(f_rel_un)
        t_world = t0_chunk + t_rel
        df_bin = float(fs / nperseg)
        dt_hop = float(t_rel[1] - t_rel[0]) if len(t_rel) > 1 else float(nperseg / fs)

        # True PSD in dB/Hz (AGENTS.md invariant: 10*log10(fs * sum(w^2)))
        Z_mag_sq = np.abs(np.fft.fftshift(Z_un, axes=0)) ** 2
        # Note: scipy.signal.stft divides by sum(win), so |Z|^2 * (sum(win)^2) = raw |FFT|^2
        win_sum_sq = max(float(np.sum(win)) ** 2, 1e-30)
        psd_db = 10.0 * np.log10(np.maximum(Z_mag_sq * win_sum_sq, 1e-30)) - psd_norm_db

        # Filter to active scope frequency range if restricted
        f_lo_scope = float(min(info.f_start, info.f_end))
        f_hi_scope = float(max(info.f_start, info.f_end))
        in_f_scope = (f_world >= f_lo_scope) & (f_world <= f_hi_scope)
        if not np.any(in_f_scope):
            in_f_scope = np.ones_like(f_world, dtype=bool)

        peak_psd_db = float(np.max(psd_db[in_f_scope, :]))
        noise_db = max(float(np.median(psd_db[in_f_scope, :])) + 1.592, peak_psd_db - 80.0)
        noise_lin = 10.0 ** (noise_db / 10.0)

        active = (psd_db > (noise_db + float(threshold_db))) & in_f_scope[:, np.newaxis]
        # 8-connected closing bridges diagonal fast-chirp hops; opening drops single-bin noise specks
        struct8 = np.ones((3, 3), dtype=bool)
        active = ndimage.binary_closing(active, structure=struct8, iterations=1)
        active = ndimage.binary_opening(active, structure=np.ones((2, 2), dtype=bool), iterations=1)

        labeled, num_comp = ndimage.label(active, structure=struct8)
        if num_comp == 0:
            return

        slices = ndimage.find_objects(labeled)
        for comp_idx, slc in enumerate(slices, start=1):
            if slc is None or info.is_cancelled():
                continue
            f_slc, t_slc = slc
            if (t_slc.stop - t_slc.start) < 4:
                continue

            sub_mask = labeled[f_slc, t_slc] == comp_idx
            n_pix = int(np.count_nonzero(sub_mask))
            if n_pix < 8:
                continue

            sub_psd_db = psd_db[f_slc, t_slc]
            sub_lin = np.maximum(10.0 ** (sub_psd_db / 10.0) - noise_lin, 0.0)
            f_sub = f_world[f_slc]
            t_sub = t_world[t_slc]

            cols_valid: List[float] = []
            f_lo_env: List[float] = []
            f_hi_env: List[float] = []
            f_cent: List[float] = []
            col_weights: List[float] = []

            comp_peak_db = float(np.max(sub_psd_db[sub_mask]))
            margin_f = 1.25 * df_bin
            for mc in range(sub_mask.shape[1]):
                ks = np.where(sub_mask[:, mc])[0]
                if len(ks) == 0:
                    continue
                col_peak_db = float(np.max(sub_psd_db[ks, mc]))
                # Ignore ultra-weak -28 dB turn-on/turn-off tail columns
                if col_peak_db < comp_peak_db - 28.0:
                    continue
                # Track the -20 dB instantaneous occupied core of each time slice
                ks_core = ks[sub_psd_db[ks, mc] >= (col_peak_db - 20.0)]
                if len(ks_core) == 0:
                    ks_core = ks
                w = sub_lin[ks_core, mc]
                w_sum = float(np.sum(w))
                f_ks = f_sub[ks_core]
                if w_sum > 1e-30:
                    fc_m = float(np.sum(f_ks * w) / w_sum)
                else:
                    fc_m = float(0.5 * (f_ks[0] + f_ks[-1]))
                cols_valid.append(float(t_sub[mc]))
                f_cent.append(fc_m)
                f_lo_env.append(float(f_ks[0]) - margin_f)
                f_hi_env.append(float(f_ks[-1]) + margin_f)
                col_weights.append(max(w_sum, 1e-30))

            if len(cols_valid) < 4:
                continue

            t_arr = np.asarray(cols_valid, dtype=np.float64)
            fc_arr = np.asarray(f_cent, dtype=np.float64)
            flo_arr = np.asarray(f_lo_env, dtype=np.float64)
            fhi_arr = np.asarray(f_hi_env, dtype=np.float64)
            w_arr = np.asarray(col_weights, dtype=np.float64)

            # Suppress 1-frame turn-on/turn-off key-click splatter & smooth ribbon edges
            if len(flo_arr) >= 5:
                flo_arr = ndimage.median_filter(flo_arr, size=3, mode="nearest")
                fhi_arr = ndimage.median_filter(fhi_arr, size=3, mode="nearest")
                fc_clean = ndimage.median_filter(fc_arr, size=3, mode="nearest")
                k3 = np.array([0.25, 0.5, 0.25])
                flo_arr = np.convolve(np.pad(flo_arr, 1, mode="edge"), k3, mode="valid")
                fhi_arr = np.convolve(np.pad(fhi_arr, 1, mode="edge"), k3, mode="valid")
            else:
                fc_clean = fc_arr

            # Expand start and end time by half an STFT hop
            t_arr_pad = t_arr.copy()
            t_arr_pad[0] = max(0.0, t_arr_pad[0] - 0.5 * dt_hop)
            t_arr_pad[-1] = t_arr_pad[-1] + 0.5 * dt_hop

            body_cols = w_arr >= 0.05 * float(np.max(w_arr))
            fc_body = fc_clean[body_cols] if np.count_nonzero(body_cols) >= 2 else fc_clean
            freq_drift_hz = float(np.max(fc_body) - np.min(fc_body))
            mean_inst_bw = max(float(np.mean(fhi_arr - flo_arr)), df_bin)

            # Weighted linear regression for sweep rate (Hz/s)
            t_rel_c = t_arr - t_arr[0]
            wn = w_arr / max(float(np.sum(w_arr)), 1e-30)
            t_bar = float(np.sum(wn * t_rel_c))
            f_bar = float(np.sum(wn * fc_arr))
            denom_t = float(np.sum(wn * (t_rel_c - t_bar) ** 2))
            slope_hz_s = (
                float(np.sum(wn * (t_rel_c - t_bar) * (fc_arr - f_bar)) / denom_t)
                if denom_t > 1e-24
                else 0.0
            )
            sweep_khz_ms = slope_hz_s / 1e6

            # Build closed contour vertices (upper forward + lower reverse)
            raw_verts = [(float(t_arr_pad[i]), float(fhi_arr[i])) for i in range(len(t_arr_pad))] + [
                (float(t_arr_pad[i]), float(flo_arr[i])) for i in range(len(t_arr_pad) - 1, -1, -1)
            ]
            simp_verts = _simplify_closed_polygon(raw_verts, rel_tol=0.018, max_vertices=20)

            p_area = _polygon_shoelace_area(simp_verts)
            dur_tot = max(float(t_arr_pad[-1] - t_arr_pad[0]), 1e-12)
            bw_tot = max(float(np.max(fhi_arr) - np.min(flo_arr)), 1e-12)
            r_area = dur_tot * bw_tot
            fill_ratio = float(np.clip(p_area / r_area, 1e-4, 1.0))

            # Non-stationarity gate: require genuine center-frequency excursion across time
            is_swept = freq_drift_hz >= 1.15 * mean_inst_bw
            if only_nonstationary and not is_swept:
                continue

            snr_adv_db = float(-10.0 * np.log10(fill_ratio))
            mean_snr_db = float(np.mean(sub_psd_db[sub_mask]) - noise_db)
            peak_snr_db = float(np.max(sub_psd_db[sub_mask]) - noise_db)

            n_created += 1
            col = palette[(n_created - 1) % len(palette)]
            label_str = (
                f"Sweep {sweep_khz_ms:+.1f} kHz/ms (+{snr_adv_db:.1f}dB vs Rect)"
                if abs(sweep_khz_ms) >= 0.05
                else f"Contour SNR {mean_snr_db:.1f}dB ({fill_ratio * 100:.0f}% fill)"
            )
            hover_md = (
                f"### Detected Sweep Contour #{n_created}\n"
                f"| Metric | Value |\n"
                f"| :--- | :--- |\n"
                f"| **Sweep Rate** | {sweep_khz_ms:+.3f} kHz/ms ({slope_hz_s / 1e6:+.3f} MHz/s) |\n"
                f"| **Sweep Excursion ($\\Delta f$)** | {freq_drift_hz / 1e3:.2f} kHz |\n"
                f"| **Instantaneous BW** | {mean_inst_bw / 1e3:.2f} kHz |\n"
                f"| **Bounding Rect BW** | {bw_tot / 1e3:.2f} kHz |\n"
                f"| **Polygon vs. Rect Fill** | **{fill_ratio * 100.0:.1f}%** (+{snr_adv_db:.1f} dB noise rejected!) |\n"
                f"| **Mean / Peak SNR** | {mean_snr_db:.1f} dB / {peak_snr_db:.1f} dB |\n"
                f"| **Polygon Vertices** | {len(simp_verts)} |"
            )
            meta = {
                "sweep_rate_khz_per_ms": round(sweep_khz_ms, 4),
                "freq_drift_hz": round(freq_drift_hz, 2),
                "inst_bw_hz": round(mean_inst_bw, 2),
                "rect_bw_hz": round(bw_tot, 2),
                "polygon_fill_pct": round(fill_ratio * 100.0, 2),
                "snr_gain_vs_rect_db": round(snr_adv_db, 2),
                "snr_db": round(mean_snr_db, 2),
                "peak_snr_db": round(peak_snr_db, 2),
                "num_vertices": len(simp_verts),
            }

            result.add(
                Polygon(
                    vertices=simp_verts,
                    color=col,
                    alpha=0.22,
                    border_width=2,
                    display_str=label_str,
                    hover_str=hover_md,
                    locked=bool(lock_polygons),
                    z_order=8,
                    metadata=meta,
                )
            )
            if len(detected_tracks_t) < 8:
                tr_key = f"Sweep #{n_created} ({sweep_khz_ms:+.1f} kHz/ms)"
                detected_tracks_t[tr_key] = t_arr
                detected_tracks_f[tr_key] = fc_arr

    # Use direct buffer if short, otherwise stream via `info.iter_batches`
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

    if detected_tracks_t:
        # Plot the strongest / first track or overlaid tracks on common grid
        first_k = next(iter(detected_tracks_t))
        result.set_plot_tab_title("Detected Sweep Contours")
        result.add_plot(
            title="Primary Sweep Ridge f(t)",
            y={first_k: detected_tracks_f[first_k]},
            x=detected_tracks_t[first_k],
            x_label="Time",
            x_units="s",
            y_label="Frequency (Hz)",
            primary_mode="TIME",
        )

    if n_created == 0:
        hint = (
            " Try lowering 'Sweep Detection Threshold (dB)' or unchecking 'Only Swept / Non-Stationary Signals'."
            if only_nonstationary
            else " Try lowering 'Sweep Detection Threshold (dB)'."
        )
        result.log(f"[Polygon TF Filter] No sweep contours detected in scope.{hint}")
    else:
        result.log(
            f"[Polygon TF Filter] Created {n_created} tight Polygon contour overlay(s). "
            f"Tip: Re-run in 'Isolate' or 'Notch' mode (or drag polygon vertices!) to surgically filter."
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
    atten_db = float(info.params.get("atten_db", 60.0))
    feather_bins = int(info.params.get("feather_bins", 2))
    only_nonstationary = bool(info.params.get("only_nonstationary", True))
    open_output_tab = str(info.params.get("open_output_tab", TAB_NONE))
    lock_polygons = bool(info.params.get("lock_polygons", False))

    # Collect visible Polygon overlays overlapping the active execution scope
    t_lo_s = float(min(info.t_start, info.t_end))
    t_hi_s = float(max(info.t_start, info.t_end))
    polys_in_scope = [
        o
        for o in (info.overlays or [])
        if getattr(o, "visible", True)
        and o._shape_name() == "POLYGON"
        and len(getattr(o, "points", [])) >= 3
        and float(o.t_end) >= t_lo_s
        and float(o.t_start) <= t_hi_s
    ]

    if mode == MODE_AUTO:
        if polys_in_scope:
            return _run_surgical_filter(
                polys=polys_in_scope,
                samples=samples,
                info=info,
                is_notch=False,
                atten_db=atten_db,
                feather_bins=feather_bins,
                open_output_tab=open_output_tab,
                result=result,
            )
        return _detect_sweep_polygons(
            samples=samples,
            info=info,
            threshold_db=threshold_db,
            only_nonstationary=only_nonstationary,
            lock_polygons=lock_polygons,
            result=result,
        )

    if mode in (MODE_ISOLATE, MODE_NOTCH):
        if not polys_in_scope:
            result.warning(
                "No Polygon overlays found in the active scope.\n\n"
                "Draw a Polygon overlay on the spectrogram (select 'Polygon' in the "
                "Overlay toolbar and drag/adjust vertices), or switch Operation Mode "
                "to 'Detect Sweeps & Chirps -> Create Polygons'."
            )
            return result
        return _run_surgical_filter(
            polys=polys_in_scope,
            samples=samples,
            info=info,
            is_notch=(mode == MODE_NOTCH),
            atten_db=atten_db,
            feather_bins=feather_bins,
            open_output_tab=open_output_tab,
            result=result,
        )

    return _detect_sweep_polygons(
        samples=samples,
        info=info,
        threshold_db=threshold_db,
        only_nonstationary=only_nonstationary,
        lock_polygons=lock_polygons,
        result=result,
    )

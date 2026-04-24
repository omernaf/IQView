"""detect_peaks.py — IQView example plugin

Detects spectral peaks in the current view and marks each one with a
horizontal HLINE overlay positioned at the peak frequency.

Usage
-----
In IQView: Plugins → Load Plugin… → select this file → Plugins → ▶ detect_peaks

What it does
------------
1. Takes the FFT of the IQ samples.
2. Computes the power spectrum (dB).
3. Finds up to MAX_PEAKS peaks that are at least THRESHOLD_DB above the median.
4. Returns one HLINE overlay per peak, coloured by relative amplitude.
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Plugin metadata (displayed in the menu tooltip)
# ---------------------------------------------------------------------------

PLUGIN_NAME        = "detect_peaks"
PLUGIN_DESCRIPTION = "Mark spectral peaks in the current view with HLINE overlays"

# ---------------------------------------------------------------------------
# Tuning parameters (edit as needed)
# ---------------------------------------------------------------------------

THRESHOLD_DB = 20.0   # peak must be at least this many dB above the median
MAX_PEAKS    = 20     # maximum number of overlays to add
MIN_SPACING  = 0.02   # minimum spacing between peaks, as fraction of bandwidth


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(samples: np.ndarray, info: dict) -> list[dict]:
    """
    Parameters
    ----------
    samples : np.ndarray  (complex64)
        IQ samples for the currently visible time window.
    info : dict
        {sample_rate, center_freq, t_start, t_end, f_start, f_end, overlays}

    Returns
    -------
    list[dict]
        Overlay dicts (HLINE shapes) at detected peak frequencies.
    """
    if samples is None or len(samples) == 0:
        return []

    sample_rate = info["sample_rate"]
    center_freq = info["center_freq"]

    # ── 1. FFT ────────────────────────────────────────────────────────────────
    nfft   = min(len(samples), 4096)
    window = np.hanning(nfft)
    block  = samples[:nfft]

    spectrum = np.fft.fftshift(np.fft.fft(block * window, n=nfft))
    power_db = 20 * np.log10(np.abs(spectrum) + 1e-12)

    # Frequency axis in absolute Hz
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / sample_rate)) + center_freq

    # ── 2. Peak finding ───────────────────────────────────────────────────────
    median_db = np.median(power_db)
    threshold = median_db + THRESHOLD_DB

    # Minimum bin spacing to avoid closely spaced duplicates
    min_bins = max(1, int(MIN_SPACING * nfft))

    peak_indices = _find_peaks_above(power_db, threshold, min_bins)
    peak_indices = peak_indices[:MAX_PEAKS]

    if len(peak_indices) == 0:
        return []

    # ── 3. Colour map: louder peaks → brighter green ──────────────────────────
    peak_powers = power_db[peak_indices]
    p_min, p_max = peak_powers.min(), peak_powers.max()

    overlays = []
    for idx, db in zip(peak_indices, peak_powers):
        freq = float(freqs[idx])

        # Skip peaks outside the visible frequency range (view clipping)
        if not (info["f_start"] <= freq <= info["f_end"]):
            continue

        # Intensity 0.0 → 1.0
        intensity = float((db - p_min) / (p_max - p_min + 1e-9))
        color     = _intensity_to_hex(intensity)

        overlays.append({
            "shape":        "HLINE",
            "points":       [[0.0, freq]],
            "center":       None,
            "radii":        None,
            "color":        color,
            "alpha":        0.0,
            "border_width": 1,
            "border_color": color,
            "border_style": "dash",
            "display_str":  f"{freq/1e6:.4f} MHz  ({db:.1f} dB)",
            "hover_str":    f"Peak at {freq:.1f} Hz  |  {db:.1f} dB above median",
            "tag_pos":      "center",
            "visible":      True,
            "locked":       False,
            "z_order":      9,
            "source":       "plugin:detect_peaks",
            "metadata":     {"freq_hz": freq, "power_db": float(db)},
        })

    return overlays


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_peaks_above(signal: np.ndarray, threshold: float, min_spacing: int) -> list:
    """Simple local-maximum detector with a minimum-spacing guard."""
    candidates = []
    n = len(signal)
    for i in range(1, n - 1):
        if signal[i] >= threshold and signal[i] >= signal[i - 1] and signal[i] >= signal[i + 1]:
            candidates.append(i)

    # Non-maximum suppression: keep the strongest within min_spacing windows
    filtered = []
    last = -min_spacing
    for i in sorted(candidates, key=lambda x: -signal[x]):
        if abs(i - last) >= min_spacing:
            filtered.append(i)
            last = i

    # Return sorted by frequency bin index
    return sorted(filtered)


def _intensity_to_hex(t: float) -> str:
    """Map 0→1 intensity to a green → yellow colour."""
    t    = max(0.0, min(1.0, t))
    r    = int(t * 255)
    g    = int(100 + t * 155)   # 100 → 255
    b    = 0
    return f"#{r:02x}{g:02x}{b:02x}"

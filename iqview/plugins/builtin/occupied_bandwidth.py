"""iqview/plugins/builtin/occupied_bandwidth.py

Built-in IQView Plugin: Occupied Bandwidth.

Measures occupied bandwidth across the entire sample buffer and the
integrated power inside that bandwidth, then draws a Y-region (frequency
band) annotated with both values.
"""

from __future__ import annotations

import numpy as np
from scipy.signal.windows import hann

from iqview import PluginResult, PluginContext
from iqview.overlays import FreqRegion


PLUGIN_NAME = "Occupied Bandwidth"
PLUGIN_DESCRIPTION = (
    "Measures occupied bandwidth over the whole sample and the integrated "
    "power in that band, and draws a Y-region with both values."
)
PLUGIN_CATEGORY = "Analysis"
PLUGIN_NEEDS_WIDEBAND_IQ = True
# One spectrum of the full scope. Chunked runs would emit a region per chunk.
PLUGIN_BATCH_SECONDS = None

PLUGIN_DOC = """# Occupied Bandwidth

Measures the occupied bandwidth of the **entire sample** in the active execution scope and the integrated power inside that bandwidth. The result is a locked Y-region (a frequency band spanning the full time axis).

The sample buffer is raw wideband IQ. Time coverage is the whole buffer (`info.t_start` through `info.t_end`). Frequency coverage is the active scope `[info.f_start, info.f_end]`.

### Algorithm & Operation

1. **Welch power spectrum**: Averages overlapping periodograms across every sample in the buffer (periodic Hann window, 50% overlap, a final segment anchored on the last sample). Segment length is the largest power of two up to 65536 that fits the buffer. Density scaling matches `scipy.signal.welch(..., scaling="density")`, so integrating the spectrum recovers mean power `|IQ|²`.
2. **Scope mask**: Keeps bins whose absolute RF frequency lies inside `[f_start, f_end]`.
3. **Noise floor**: When **Subtract Noise Floor** is enabled, subtracts 1.5× the median bin of the in-scope spectrum before building the cumulative distribution. Bins below that floor drop out, so a narrow emission is not stretched by low-level noise in the tails. The integrated-power number still uses the unsubtracted spectrum.
4. **Occupied bandwidth**: Finds the bin span that leaves `(100 − percent) / 2` percent of the (optionally noise-subtracted) power below the lower edge and the same amount above the upper edge. This is the usual β/2 definition (99% means 0.5% in each tail).
5. **Integrated power**: Sums the measured PSD over those bins and multiplies by the bin width, then reports `10·log10` of that power in dB. A mean-square power of 1 is 0 dB.
6. **Y-region**: Places one locked `FreqRegion` from the lower edge to the upper edge. Bandwidth (Hz) and power (dB, plus the linear mean-square value) are stored on `metadata`, written into `hover_str`, and shown on the overlay label. Running the plugin again removes the previous Y-region from this plugin before adding the new one.

### Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `obw_percent` | `float` | `99.0` | Percent of power that defines the occupied bandwidth. |
| `subtract_noise` | `bool` | `True` | Subtract the spectral noise floor before locating the bandwidth edges. |

### Output Metadata

The Y-region `metadata` dictionary contains:

* `obw_hz` (`float`): Occupied bandwidth in Hz. Equals the region's `f_end − f_start`.
* `obw_percent` (`float`): Percent setting used for the measurement.
* `integrated_power` (`float`): Power inside the occupied bandwidth, in mean-square units (`mean |IQ|²`).
* `integrated_power_db` (`float`): Integrated power in dB, `10·log10(integrated_power)`.
* `f_low_hz` (`float`): Lower edge of the region, absolute RF Hz.
* `f_high_hz` (`float`): Upper edge of the region, absolute RF Hz.
* `noise_floor_subtracted` (`bool`): Whether the noise floor was removed before locating the edges.
"""


PLUGIN_PARAMS = {
    "obw_percent": {
        "type": "float",
        "default": 99.0,
        "label": "Occupied BW (%)",
        "tooltip": (
            "Percent of in-scope power that defines occupied bandwidth. "
            "99% puts 0.5% of the power in each tail."
        ),
    },
    "subtract_noise": {
        "type": "bool",
        "default": True,
        "label": "Subtract Noise Floor",
        "tooltip": (
            "Subtract the median noise floor before locating the bandwidth "
            "edges. Integrated power is always computed from the measured spectrum."
        ),
    },
}


_MAX_NPERSEG = 65536
_MIN_SAMPLES = 32
_MIN_BINS = 8


def _choose_nperseg(n: int) -> int:
    """Largest power-of-two Welch length that fits `n`, capped at 65536."""
    if n < _MIN_SAMPLES:
        return 0
    limit = min(int(n), _MAX_NPERSEG)
    nperseg = 1 << int(np.floor(np.log2(limit)))
    return int(max(_MIN_SAMPLES, min(nperseg, n)))


def _segment_starts(n: int, nperseg: int, step: int):
    """Yield segment starts that cover the first and last sample."""
    last = n - nperseg
    start = 0
    while start <= last:
        yield start
        if start == last:
            break
        nxt = start + step
        if nxt >= last:
            nxt = last
        if nxt <= start:
            break
        start = nxt


def _segment_count(n: int, nperseg: int, step: int) -> int:
    span = n - nperseg
    count = 1 + span // step
    if span % step != 0:
        count += 1
    return int(count)


def _average_psd(iq: np.ndarray, fs: float, nperseg: int, info: PluginContext | None):
    """
    Two-sided Welch PSD in V²/Hz, frequencies shifted to [-fs/2, fs/2).

    Scale is `|FFT|² / (fs · Σ w²)` with a periodic Hann window, matching
    `scipy.signal.welch(..., window="hann", scaling="density", detrend=False)`.
    """
    noverlap = nperseg // 2
    step = max(1, nperseg - noverlap)
    window = hann(nperseg, sym=False).astype(np.float64)
    win_sum2 = float(np.sum(window * window))
    scale = fs * max(win_sum2, 1e-30)

    acc = np.zeros(nperseg, dtype=np.float64)
    count = 0
    n_seg = _segment_count(len(iq), nperseg, step)
    report_every = max(1, n_seg // 20)

    for start in _segment_starts(len(iq), nperseg, step):
        if info is not None and info.is_cancelled():
            return None
        seg = np.asarray(iq[start : start + nperseg], dtype=np.complex128)
        acc += np.abs(np.fft.fft(seg * window)) ** 2
        count += 1
        if info is not None and (count % report_every == 0 or count == n_seg):
            pct = 5.0 + 75.0 * (count / float(n_seg))
            info.progress(pct, f"Averaging spectrum {count}/{n_seg}…")

    if count < 1:
        return None

    pxx = np.fft.fftshift(acc / (float(count) * scale))
    freqs = np.fft.fftshift(np.fft.fftfreq(nperseg, d=1.0 / fs))
    return freqs, pxx


def _measure_occupied_bandwidth(
    iq: np.ndarray,
    fs: float,
    fc: float,
    f_start: float,
    f_end: float,
    obw_percent: float = 99.0,
    subtract_noise: bool = True,
    info: PluginContext | None = None,
) -> dict | None:
    """
    Occupied bandwidth and integrated power of `iq`.

    Returns absolute-Hz edges plus power, or None when the buffer or the
    in-scope spectrum is too short, or when the user cancels.
    """
    n = int(len(iq))
    nperseg = _choose_nperseg(n)
    if nperseg < _MIN_SAMPLES or fs <= 0.0:
        return None

    averaged = _average_psd(iq, fs, nperseg, info)
    if averaged is None:
        return None
    freqs, pxx = averaged

    f_lo_scope = float(min(f_start, f_end))
    f_hi_scope = float(max(f_start, f_end))
    f_abs = freqs + float(fc)
    scope_bw = f_hi_scope - f_lo_scope
    full_band = scope_bw <= 0.0 or scope_bw >= fs * 0.98

    if full_band:
        band_abs = f_abs
        band_pxx = pxx
    else:
        selected = np.flatnonzero((f_abs >= f_lo_scope) & (f_abs <= f_hi_scope))
        if selected.size < _MIN_BINS:
            return None
        sl = slice(int(selected[0]), int(selected[-1]) + 1)
        band_abs = f_abs[sl]
        band_pxx = pxx[sl]

    n_bins = int(band_pxx.size)
    if n_bins < _MIN_BINS:
        return None

    if n_bins > 1:
        df = float(np.median(np.diff(band_abs)))
    else:
        df = float(fs / nperseg)
    df = max(df, float(fs / nperseg))

    total = float(np.sum(band_pxx))
    if total <= 0.0 or not np.isfinite(total):
        return None

    spec = band_pxx
    if subtract_noise:
        # Median of every in-scope bin. A partial-band emission occupies
        # fewer than half the bins, so the median sits on the noise floor.
        # A full-band emission sits near the median and the span stays wide.
        noise_bin = float(np.median(band_pxx))
        cleaned = np.maximum(0.0, band_pxx - noise_bin * 1.5)
        if float(np.sum(cleaned)) > max(total * 1e-6, 1e-30):
            spec = cleaned

    spec_sum = float(np.sum(spec))
    if spec_sum <= 0.0 or not np.isfinite(spec_sum):
        return None

    cdf = np.cumsum(spec) / spec_sum
    frac = float(np.clip(obw_percent / 100.0, 0.50, 0.999))
    tail = 0.5 * (1.0 - frac)
    idx_lo = int(np.clip(np.searchsorted(cdf, tail), 0, n_bins - 1))
    idx_hi = int(np.clip(np.searchsorted(cdf, 1.0 - tail), idx_lo, n_bins - 1))

    f_lo = float(band_abs[idx_lo] - 0.5 * df)
    f_hi = float(band_abs[idx_hi] + 0.5 * df)
    # Keep the stripe inside a real frequency scope. A zero-width scope
    # means "use the whole Nyquist zone", so there is nothing to clamp to.
    if scope_bw > 0.0:
        f_lo = max(f_lo_scope, f_lo)
        f_hi = min(f_hi_scope, f_hi)
    if f_hi <= f_lo:
        f_lo = float(band_abs[idx_lo])
        f_hi = float(band_abs[idx_hi] if idx_hi != idx_lo else band_abs[idx_lo] + df)
        if f_hi <= f_lo:
            f_hi = f_lo + df

    # Integrated power uses the measured PSD, including the noise still
    # inside the occupied bins. Density (V²/Hz) × bin width = power.
    power = float(np.sum(band_pxx[idx_lo : idx_hi + 1]) * df)
    power = max(power, 0.0)
    power_db = float(10.0 * np.log10(max(power, 1e-30)))
    obw_hz = float(f_hi - f_lo)

    return {
        "obw_hz": obw_hz,
        "obw_percent": float(obw_percent),
        "integrated_power": power,
        "integrated_power_db": power_db,
        "f_low_hz": f_lo,
        "f_high_hz": f_hi,
        "noise_floor_subtracted": bool(subtract_noise),
    }


def _fmt_hz(hz: float) -> str:
    return f"{hz:,.1f} Hz"


def _fmt_db(db: float) -> str:
    return f"{db:.2f} dB"


def _shape_name(overlay) -> str:
    shape = getattr(overlay, "shape", "")
    return shape.value if hasattr(shape, "value") else str(shape)


def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()
    if samples is None or len(samples) < _MIN_SAMPLES:
        result.log("Occupied Bandwidth: need at least 32 samples.")
        return result

    iq = np.asarray(samples)
    if iq.ndim != 1:
        result.log("Occupied Bandwidth: samples must be a 1-D complex array.")
        return result
    if not np.all(np.isfinite(iq)):
        result.log("Occupied Bandwidth: samples contain non-finite values.")
        return result

    fs = float(info.sample_rate)
    fc = float(info.center_freq)
    if fs <= 0.0:
        result.log("Occupied Bandwidth: sample rate must be positive.")
        return result

    obw_percent = float(np.clip(info.params.get("obw_percent", 99.0), 50.0, 99.9))
    subtract_noise = bool(info.params.get("subtract_noise", True))

    if info.is_cancelled():
        return result

    info.progress(5, "Computing power spectrum over the full sample…")
    measured = _measure_occupied_bandwidth(
        iq,
        fs=fs,
        fc=fc,
        f_start=float(info.f_start),
        f_end=float(info.f_end),
        obw_percent=obw_percent,
        subtract_noise=subtract_noise,
        info=info,
    )
    if info.is_cancelled():
        return result
    if measured is None:
        result.log(
            "Occupied Bandwidth: the active frequency span does not contain "
            "enough spectrum bins to measure."
        )
        return result

    plugin_source = f"plugin:{PLUGIN_NAME}"
    for overlay in info.overlays:
        if _shape_name(overlay) != "Y_REGION":
            continue
        if str(getattr(overlay, "source", "") or "") != plugin_source:
            continue
        result.remove(overlay.id)

    metadata = {
        "obw_hz": round(float(measured["obw_hz"]), 2),
        "obw_percent": round(float(measured["obw_percent"]), 2),
        "integrated_power": float(measured["integrated_power"]),
        "integrated_power_db": round(float(measured["integrated_power_db"]), 2),
        "f_low_hz": round(float(measured["f_low_hz"]), 2),
        "f_high_hz": round(float(measured["f_high_hz"]), 2),
        "noise_floor_subtracted": bool(measured["noise_floor_subtracted"]),
    }
    bw_txt = _fmt_hz(metadata["obw_hz"])
    pwr_txt = _fmt_db(metadata["integrated_power_db"])
    percent_txt = f"{metadata['obw_percent']:g}%"
    hover = (
        f"Occupied bandwidth: {bw_txt} ({percent_txt})\n"
        f"Integrated power: {pwr_txt}"
    )

    result.add(
        FreqRegion(
            f_start=float(measured["f_low_hz"]),
            f_end=float(measured["f_high_hz"]),
            color="#ffb020",
            alpha=0.20,
            border_width=2,
            border_color="#ffe08a",
            display_str=f"{bw_txt} | {pwr_txt}",
            hover_str=hover,
            tag_pos="top-left",
            locked=True,
            z_order=4,
            metadata=metadata,
        )
    )
    result.log(f"Occupied bandwidth: {bw_txt} ({percent_txt}), integrated power {pwr_txt}")
    info.progress(100, "Done")
    return result

"""iqview/plugins/builtin/fsk_demodulator.py

Built-in IQView Plugin: FSK Demodulator.

Operates on existing `Rect` overlays in `info.overlays` (using cached `o.iq`
from upstream detectors or lazily extracting from file via `o.get_samples(info)`).
Performs FM discrimination, automatic CFO removal, symbol rate & clock recovery,
and bit slicing, annotating each overlay's `metadata`, `hover_str`, and `display_str`.
"""

from __future__ import annotations

import copy
import numpy as np
from scipy import fft as sp_fft
from scipy import signal as sp_signal

from iqview import PluginResult


PLUGIN_NAME              = "FSK Demodulator"
PLUGIN_DESCRIPTION       = (
    "Demodulates 2-FSK / GFSK bursts inside Rect overlays, recovering CFO, "
    "frequency deviation, baud rate, and bit/hex sequences."
)
PLUGIN_CATEGORY          = "Demodulation"
PLUGIN_NEEDS_WIDEBAND_IQ = False


PLUGIN_PARAMS = {
    "baud_rate": {
        "type": "float",
        "default": 0.0,
        "label": "Baud Rate (sym/s, 0 = Auto)",
        "tooltip": (
            "Symbol rate in baud (symbols/sec). Set to 0 to automatically "
            "estimate baud rate from symbol transitions."
        ),
    },
    "invert_bits": {
        "type": "bool",
        "default": False,
        "label": "Invert Bit Polarity (0 ↔ 1)",
        "tooltip": "When enabled, negative frequency deviation maps to 1 and positive to 0.",
    },
    "trim_edges": {
        "type": "bool",
        "default": True,
        "label": "Trim Noise Edges",
        "tooltip": "Automatically trim low-energy leading/trailing edge samples before bit slicing.",
    },
    "max_hover_bits": {
        "type": "int",
        "default": 64,
        "label": "Max Bits Shown in Tooltip",
        "tooltip": "Maximum number of bits displayed directly in the hover tooltip (full bits stored in metadata).",
    },
    "debug_plots": {
        "type": "bool",
        "default": False,
        "label": "Debug Plots (FM Discriminator & Bits)",
        "tooltip": "Open a plot tab showing the FM discriminator waveform and sliced bit regions for up to 5 bursts.",
    },
}


def _trim_active_span(iq: np.ndarray) -> tuple[np.ndarray, int]:
    """Trim leading/trailing low-energy ramp samples; return (trimmed_iq, start_offset)."""
    n = len(iq)
    if n < 16:
        return iq, 0
    mag2 = (iq.real.astype(np.float64) ** 2) + (iq.imag.astype(np.float64) ** 2)
    win = max(1, min(16, n // 8))
    if win > 1:
        k = np.ones(win, dtype=np.float64) / float(win)
        env = np.convolve(mag2, k, mode="same")
    else:
        env = mag2

    peak_ref = float(np.percentile(env, 75.0))
    if peak_ref <= 1e-20:
        return iq, 0
    active_idx = np.where(env >= 0.20 * peak_ref)[0]
    if len(active_idx) < 8:
        return iq, 0
    s0 = int(active_idx[0])
    s1 = int(active_idx[-1]) + 1
    if (s1 - s0) < 8:
        return iq, 0
    return iq[s0:s1], s0


def _estimate_baud_rate(f_demod: np.ndarray, fs: float) -> float:
    """
    Auto-estimate symbol baud rate from the cyclostationary transition envelope
    |diff(f_demod)| and zero-crossing run lengths.
    """
    n = len(f_demod)
    if n < 12 or fs <= 0:
        return max(100.0, fs / 8.0)

    # 1. Cyclostationary tone of |df/dt|
    df = np.abs(np.diff(f_demod))
    df = df - np.mean(df)
    nfft = max(256, 1 << int(np.ceil(np.log2(min(len(df) * 4, 16384)))))
    win = np.hanning(len(df))
    spec = np.abs(sp_fft.rfft(df * win, n=nfft))
    freqs = sp_fft.rfftfreq(nfft, d=1.0 / fs)

    f_min = max(fs / max(n * 0.5, 4.0), fs / 64.0)
    f_max = fs / 2.1
    valid = (freqs >= f_min) & (freqs <= f_max)
    if np.any(valid):
        sub_spec = spec[valid]
        sub_freqs = freqs[valid]
        peak_idx = int(np.argmax(sub_spec))
        baud_fft = float(sub_freqs[peak_idx])
    else:
        baud_fft = fs / 4.0

    # 2. Zero-crossing interval check to avoid harmonic lock
    signs = f_demod >= 0.0
    zc = np.where( signs[1:] != signs[:-1] )[0]
    if len(zc) >= 3:
        intervals = np.diff(zc).astype(np.float64)
        # Minimum symbol duration is around the 20th-35th percentile of zero-crossing intervals
        t_sym_samples = float(np.percentile(intervals, 25.0))
        if t_sym_samples >= 2.0:
            baud_zc = fs / t_sym_samples
            # If FFT picked 2x harmonic of zero-crossing baud, prefer fundamental
            if 1.75 * baud_zc <= baud_fft <= 2.25 * baud_zc:
                return baud_zc

    return float(np.clip(baud_fft, fs / 100.0, fs / 2.0))


def _demodulate_fsk_burst(
    iq: np.ndarray,
    fs: float,
    target_baud: float = 0.0,
    invert_bits: bool = False,
    trim_edges: bool = True,
):
    """
    Demodulate a single complex baseband FSK burst.

    Returns
    -------
    dict with keys:
      bits: np.ndarray of uint8 (0/1)
      bits_str: str
      hex_str: str
      baud_rate: float
      f_dev_hz: float
      cfo_hz: float
      f_demod: np.ndarray (centered FM discriminator trace in Hz)
      sample_times_s: np.ndarray (symbol sampling instants relative to trimmed start)
      trim_offset: int
    """
    if trim_edges:
        work_iq, trim_offset = _trim_active_span(iq)
    else:
        work_iq, trim_offset = iq, 0

    if len(work_iq) < 6 or fs <= 0:
        return None

    # Instantaneous frequency via phase difference: angle(x[n] * conj(x[n-1])) * fs / (2*pi)
    prod = work_iq[1:] * np.conj(work_iq[:-1])
    dphi = np.angle(prod).astype(np.float64)
    f_inst = dphi * (fs / (2.0 * np.pi))

    # Robust CFO and frequency deviation estimation using inner percentiles
    core = f_inst[max(1, len(f_inst) // 10) : max(2, len(f_inst) - len(f_inst) // 10)]
    if len(core) < 4:
        core = f_inst
    p15, p85 = np.percentile(core, [15.0, 85.0])
    cfo_hz = 0.5 * float(p15 + p85)
    f_dev_hz = max(1.0, 0.5 * float(p85 - p15))

    f_demod = f_inst - cfo_hz
    if invert_bits:
        f_demod = -f_demod

    baud_rate = float(target_baud) if target_baud > 0 else _estimate_baud_rate(f_demod, fs)
    sps = max(1.5, fs / max(baud_rate, 1e-3))

    # Matched / moving-average filter of ~0.75 symbol period
    filt_len = max(1, int(round(0.75 * sps)))
    if filt_len > 1 and filt_len < len(f_demod):
        kernel = np.ones(filt_len, dtype=np.float64) / float(filt_len)
        f_filt = np.convolve(f_demod, kernel, mode="same")
    else:
        f_filt = f_demod

    # Symbol clock recovery: search fractional sampling phase tau in [0, sps)
    # that maximizes the mean absolute eye opening
    idx_grid = np.arange(len(f_filt), dtype=np.float64)
    n_phases = 24
    best_tau = 0.5 * sps
    best_eye = -1.0

    for tau in np.linspace(0.1 * sps, 0.9 * sps, n_phases):
        sample_pos = np.arange(tau, len(f_filt) - 0.1 * sps, sps)
        if len(sample_pos) < 1:
            continue
        vals = np.interp(sample_pos, idx_grid, f_filt)
        score = float(np.mean(np.abs(vals)))
        if score > best_eye:
            best_eye = score
            best_tau = float(tau)

    sample_pos = np.arange(best_tau, len(f_filt), sps)
    if len(sample_pos) == 0:
        sample_pos = np.array([0.5 * len(f_filt)], dtype=np.float64)

    sym_vals = np.interp(sample_pos, idx_grid, f_filt)
    bits = (sym_vals >= 0.0).astype(np.uint8)
    bits_str = "".join("1" if b else "0" for b in bits)

    # Convert bits to padded hex string
    if len(bits) > 0:
        pad = (4 - (len(bits) % 4)) % 4
        padded_bits = bits_str + ("0" * pad)
        hex_digits = [
            f"{int(padded_bits[i : i + 4], 2):X}"
            for i in range(0, len(padded_bits), 4)
        ]
        hex_str = "0x" + "".join(hex_digits)
    else:
        hex_str = "0x0"

    return {
        "bits": bits,
        "bits_str": bits_str,
        "hex_str": hex_str,
        "baud_rate": baud_rate,
        "sps": sps,
        "f_dev_hz": f_dev_hz,
        "cfo_hz": cfo_hz,
        "f_demod": f_filt,
        "sample_pos": sample_pos,
        "trim_offset": trim_offset,
    }


def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()

    params = info.params
    target_baud    = float(params.get("baud_rate", 0.0))
    invert_bits    = bool(params.get("invert_bits", False))
    trim_edges     = bool(params.get("trim_edges", True))
    max_hover_bits = max(8, int(params.get("max_hover_bits", 64)))
    debug_plots    = bool(params.get("debug_plots", False))

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
        result.log("No Rect overlays found in active scope to demodulate.")
        return result

    MAX_DEBUG_PLOTS = 5
    debug_items = []
    n_demod = 0

    for idx, o in enumerate(candidates):
        if info.is_cancelled():
            break

        if idx % max(1, len(candidates) // 10) == 0:
            pct = int((idx / max(1, len(candidates))) * 95)
            info.progress(pct, f"Demodulating FSK burst {idx + 1}/{len(candidates)}…")

        burst_iq, burst_fs = o.get_samples(samples, info)
        if burst_iq is None or len(burst_iq) < 8 or burst_fs <= 0:
            continue

        demod = _demodulate_fsk_burst(
            burst_iq,
            burst_fs,
            target_baud=target_baud,
            invert_bits=invert_bits,
            trim_edges=trim_edges,
        )
        if demod is None:
            continue

        bits_str = demod["bits_str"]
        hex_str  = demod["hex_str"]
        n_bits   = len(bits_str)
        baud_est = demod["baud_rate"]
        f_dev    = demod["f_dev_hz"]
        cfo      = demod["cfo_hz"]

        bits_preview = (
            bits_str if len(bits_str) <= max_hover_bits
            else bits_str[:max_hover_bits] + f"... ({n_bits} bits)"
        )

        new_meta = copy.deepcopy(getattr(o, "metadata", {}) or {})
        new_meta.update({
            "modulation": "2-FSK",
            "baud_rate": round(float(baud_est), 2),
            "f_dev_hz": round(float(f_dev), 2),
            "cfo_hz": round(float(cfo), 2),
            "num_bits": int(n_bits),
            "bits": bits_str,
            "hex": hex_str,
        })

        base_hover = (getattr(o, "hover_str", "") or "").strip()
        # Strip any previous FSK Demod lines so re-running updates cleanly
        kept_lines = [
            ln for ln in base_hover.splitlines()
            if not ln.startswith("FSK:") and not ln.startswith("Bits:") and not ln.startswith("Hex:")
        ]
        kept_lines.append(
            f"FSK: {baud_est:,.1f} Bd | ±{f_dev:,.1f} Hz | CFO: {cfo:+,.1f} Hz | {n_bits} bits"
        )
        kept_lines.append(f"Bits: {bits_preview}")
        kept_lines.append(f"Hex: {hex_str[:42] + ('...' if len(hex_str) > 42 else '')}")
        new_hover = "\n".join(kept_lines)

        base_label = (getattr(o, "display_str", "") or "").split(" [")[0].strip()
        if not base_label:
            base_label = f"Burst #{idx + 1}"
        new_label = f"{base_label} [{n_bits}b @ {baud_est / 1e3:.2f}kBd]"

        result.update(
            o.id,
            display_str=new_label,
            hover_str=new_hover,
            metadata=new_meta,
        )
        n_demod += 1

        if debug_plots and len(debug_items) < MAX_DEBUG_PLOTS:
            debug_items.append((idx + 1, o, burst_fs, demod))

    if debug_plots and debug_items:
        result.set_plot_tab_title("FSK Demod Debug")
        for b_num, o, burst_fs, demod in debug_items:
            f_demod = demod["f_demod"]
            trim_off = demod["trim_offset"]
            sps = demod["sps"]
            sample_pos = demod["sample_pos"]
            bits = demod["bits"]

            t0 = float(o.t_start) + (trim_off / burst_fs)
            t_axis = t0 + np.arange(len(f_demod), dtype=np.float64) / burst_fs
            zero_line = np.zeros_like(f_demod)

            regions = []
            half_sym = 0.5 * sps / burst_fs
            for pos, bit_val in zip(sample_pos, bits):
                tc = t0 + (float(pos) / burst_fs)
                regions.append({
                    "x_start": max(t0, tc - half_sym),
                    "x_end": min(float(t_axis[-1]), tc + half_sym),
                    "color": "#00e676" if bit_val == 1 else "#ff5252",
                    "alpha": 0.16,
                    "label": "Bit 1" if bit_val == 1 else "Bit 0",
                })

            result.add_plot(
                title=f"Burst #{b_num} ({len(bits)}b)",
                y={
                    "FM Discrim (Hz)": f_demod,
                    "Slice Threshold": zero_line,
                },
                x=t_axis,
                fs=burst_fs,
                x_label="Time",
                x_units="s",
                y_label="Frequency Deviation (Hz)",
                regions=regions,
            )

    result.log(f"Demodulated {n_demod}/{len(candidates)} FSK burst(s)")
    info.progress(100, "Done")
    return result

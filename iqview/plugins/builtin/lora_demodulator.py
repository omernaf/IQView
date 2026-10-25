"""iqview/plugins/builtin/lora_demodulator.py

Built-in IQView Plugin: LoRa Demodulator.

Operates on existing `Rect` overlays in `info.overlays` (using cached `o.iq`
from upstream detectors or lazily extracting from file via `o.get_samples(samples, info)`).
Performs LoRa Chirp Spread Spectrum (CSS) physical layer demodulation:
- Automatic Bandwidth detection via Occupied Bandwidth (OBW) measurement snapped to standard LoRa BWs
- Automatic Symbol Time (T_sym) measurement & Spreading Factor calculation via SF = round(log2(BW * T_sym))
- Automatic Chirp Direction detection (Upchirp standard uplink vs Downchirp inverted downlink)
- SOB (Start of Burst) symbol clock synchronization and Carrier Frequency Offset (CFO) recovery
- Extraction of the two Sync Word / NetID symbols preceding the SFD
- Demodulation of all post-SFD payload symbols into raw integer values (0 .. 2^SF - 1)
- Automatic EOB (End of Burst) energy-drop termination bounded by overlay time limits
- Optional debug plot of the burst FM demod with NetID, SFD, and symbol regions
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy import signal as sp_signal
from scipy.signal.windows import hann

from iqview import PluginResult, PluginContext
from iqview.overlays import OverlayShape


PLUGIN_NAME              = "LoRa Demodulator"
PLUGIN_DESCRIPTION       = (
    "Demodulates LoRa CSS bursts inside Rect overlays, extracting SF, BW, "
    "chirp direction, NetID symbols, and raw integer payload symbols."
)
PLUGIN_CATEGORY          = "Demodulation"
PLUGIN_NEEDS_WIDEBAND_IQ = False

PLUGIN_DOC = """# LoRa Demodulator

Demodulates LoRa Chirp Spread Spectrum (CSS) physical-layer transmissions inside `Rect` overlays. Operates directly on the zero-copy baseband IQ cached on each overlay (`o.iq`, `o.fs`) by an upstream energy detector or channelizer, or lazily down-converts on demand via `o.get_samples(samples, info)`.

Demodulation focuses purely on the physical layer: extracting the raw integer values of each symbol ($0 \\dots 2^{SF}-1$) without Gray decoding, header parsing, or CRC checking.

### Algorithm & Operation

1. **Occupied Bandwidth (OBW) & Legal LoRa BW Snapping**: When `bw = 0` (Auto), computes an active-frame Welch Power Spectral Density (PSD) with out-of-band noise-floor subtraction and sub-bin cumulative energy interpolation ($99\\%$ OBW compensated for rectangular CSS occupancy) to measure the true signal bandwidth and center frequency offset, then rounds to the nearest legal LoRa standard bandwidth (`7.8 kHz` to `500 kHz` Sub-GHz and `812.5 kHz` to `1.625 MHz` 2.4 GHz).
2. **Coarse Centering, Zero-Phase Filtering & Chip-Rate Resampling**: Centers off-frequency bursts inside wider overlays, applies a zero-phase 6th-order Butterworth anti-alias filter (`scipy.signal.sosfiltfilt`), and resamples to the exact chip rate ($f_s = BW$), where each symbol spans $N = 2^{SF}$ samples.
3. **Symbol Time ($T_{\\text{sym}}$) & Spreading Factor ($SF$) Calculation**: Isolates the active burst envelope and measures the fundamental preamble chirp repetition period $T_{\\text{sym}}$ via octave-matched normalized autocorrelation with harmonic step-down and parabolic sub-sample refinement, then calculates $SF = \\text{round}(\\log_2(BW \\cdot T_{\\text{sym}})) \\in [5 \\dots 12]$. Chirp polarity (`up` standard or `down` inverted) is determined by matched chirp correlation across the preamble.
4. **SOB & Symbol Boundary Alignment**: Slides the conjugate base chirp across the preamble and SFD to determine the exact sample-aligned symbol clock phase with symmetric CFO shift cancellation.
5. **CFO & SFD Synchronization**: Recovers integer and fractional Carrier Frequency Offset (CFO) from coherent dechirped preamble peaks (combined with any coarse band-centering offset). Detects the 2.25-symbol Start of Frame Delimiter (SFD) via opposite-polarity matched correlation.
6. **NetID Extraction**: Extracts the raw integer values of the two NetID / Sync Word symbols immediately preceding the SFD.
7. **Payload Demodulation**: Beginning exactly after the 2.25 SFD chirps, demodulates each symbol window into its raw integer value $S \\in [0, 2^{SF}-1]$.
8. **EOB Termination**: Halts demodulation when symbol energy drops below the preamble threshold or when the overlay boundary is reached.

### Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **Spreading Factor** (`sf`) | `int` | `0` | LoRa Spreading Factor (5 to 12). Set to `0` for automatic calculation from $BW$ and measured $T_{\\text{sym}}$. |
| **Bandwidth** (`bw`) | `float` | `0.0` | Bandwidth in Hz (e.g. 125000, 250000, 500000, 812500, 1000000). Set to `0` to measure OBW and round to nearest legal LoRa BW. |
| **Trim Noise Edges** (`trim_edges`) | `bool` | `True` | Trim leading/trailing low-energy samples before symbol alignment. |
| **Max Hover Symbols** (`max_hover_symbols`) | `int` | `32` | Maximum number of payload symbols shown in hover tooltip (full list in metadata). |
| **Debug Plots** (`debug_plots`) | `bool` | `False` | Open an interactive plot of the burst FM demod, with shaded regions for the two NetID symbols, the SFD, and each payload symbol. |

### Output Metadata

* `metadata["protocol"]`: `"LoRa"`
* `metadata["sf"]`: Spreading Factor ($5 \\dots 12$)
* `metadata["bw_hz"]`: Legal LoRa bandwidth in Hz
* `metadata["obw_hz"]`: Measured Occupied Bandwidth in Hz
* `metadata["symbol_time_ms"]`: Symbol duration in milliseconds ($2^{SF} / BW \\times 10^3$)
* `metadata["symbol_rate"]`: Symbol rate in symbols/sec ($BW / 2^{SF}$)
* `metadata["chirp_direction"]`: `"up"` (standard uplink) or `"down"` (inverted downlink)
* `metadata["netid"]`: `[netid1, netid2]` (integers $0 \\dots 2^{SF}-1$)
* `metadata["netid_hex"]`: Formatted hex string (e.g. `0x12 0x22`)
* `metadata["cfo_hz"]`: Carrier Frequency Offset in Hz (relative to overlay center)
* `metadata["num_symbols"]`: Number of payload symbols decoded
* `metadata["symbols"]`: List of raw integer symbol values after SFD
"""

# Standard legal LoRa bandwidths (Sub-GHz, standard, and 2.4 GHz band)
LEGAL_LORA_BWS = [
    7812.5,
    10416.7,
    15625.0,
    20833.3,
    31250.0,
    41666.7,
    62500.0,
    125000.0,
    250000.0,
    500000.0,
    812500.0,
    1000000.0,
    1625000.0,
]

PLUGIN_PARAMS = {
    "sf": {
        "type": "choice",
        "default": 0,
        "choices": [0, 5, 6, 7, 8, 9, 10, 11, 12],
        "label": "Spreading Factor (0 = Auto)",
        "tooltip": "LoRa Spreading Factor (5 to 12). Set to 0 to measure symbol time T_sym and compute SF = round(log2(BW * T_sym)).",
    },
    "bw": {
        "type": "choice",
        "default": 0.0,
        "choices": [0.0, 7812.5, 10416.7, 15625.0, 20833.3, 31250.0, 41666.7, 62500.0, 125000.0, 250000.0, 500000.0, 812500.0, 1000000.0, 1625000.0],
        "label": "Bandwidth (Hz, 0 = Auto)",
        "tooltip": "Bandwidth in Hz. Set to 0 to measure Occupied Bandwidth (OBW) and round to the nearest legal LoRa bandwidth.",
    },
    "trim_edges": {
        "type": "bool",
        "default": True,
        "label": "Trim Noise Edges",
        "tooltip": "Trim low-energy leading and trailing guard samples before symbol synchronization.",
    },
    "max_hover_symbols": {
        "type": "int",
        "default": 32,
        "label": "Max Symbols in Tooltip",
        "tooltip": "Maximum number of payload symbols previewed in the hover tooltip (full sequence stored in metadata).",
    },
    "debug_plots": {
        "type": "bool",
        "default": False,
        "label": "Debug Plots (FM Demod)",
        "tooltip": (
            "Open an interactive plot of the burst instantaneous frequency, "
            "with shaded regions marking the NetID symbols, the SFD, and each payload symbol."
        ),
    },
}


def _format_hz(hz: float) -> str:
    """Format frequency cleanly in Hz, kHz, or MHz."""
    abs_hz = abs(hz)
    if abs_hz >= 1e6:
        return f"{hz / 1e6:.3f}".rstrip("0").rstrip(".") + " MHz"
    if abs_hz >= 1e3:
        return f"{hz / 1e3:.1f} kHz"
    return f"{hz:.1f} Hz"


def _measure_lora_obw(iq: np.ndarray, fs: float, obw_percent: float = 99.0) -> Tuple[float, float]:
    """
    Measure Occupied Bandwidth (OBW) and band center offset (Hz) of a LoRa burst inside `iq`.
    Uses active-frame Welch PSD, out-of-band noise-floor subtraction, and sub-bin CDF interpolation.
    Returns (obw_hz, f_center_offset_hz).
    """
    n = len(iq)
    if n < 32 or fs <= 0.0:
        return float(fs), 0.0

    max_seg = min(1024, max(32, n // 2)) if n >= 64 else n
    nperseg = max(32, 1 << int(np.floor(np.log2(max_seg))))
    nperseg = min(nperseg, n)
    step = max(1, nperseg // 2)

    win = hann(nperseg, sym=False).astype(np.float64)
    starts = list(range(0, max(1, n - nperseg + 1), step))
    if n >= nperseg and starts[-1] != n - nperseg:
        starts.append(n - nperseg)

    frames = np.empty((len(starts), nperseg), dtype=np.float64)
    for idx, st in enumerate(starts):
        seg = np.asarray(iq[st : st + nperseg], dtype=np.complex128)
        frames[idx] = np.fft.fftshift(np.abs(np.fft.fft(seg * win)) ** 2)

    # Gate active burst frames using total frame power (invariant to chirp phase & Nyquist wraps)
    frame_pwr = np.mean(frames, axis=1)
    q_max = float(np.max(frame_pwr))
    q_low = float(np.percentile(frame_pwr, 20.0))
    low_cand = frame_pwr[frame_pwr <= float(np.percentile(frame_pwr, 40.0))]
    mu_fp = float(np.median(low_cand)) if len(low_cand) > 0 else q_low
    sigma_fp = 1.4826 * float(np.median(np.abs(low_cand - mu_fp))) if len(low_cand) > 0 else 0.0

    quiet_psd: Optional[np.ndarray] = None
    if len(starts) >= 3 and q_max > mu_fp + max(4.0 * sigma_fp, 0.10 * mu_fp):
        low_frames = frame_pwr <= mu_fp + max(2.5 * sigma_fp, 0.10 * (q_max - mu_fp))
        active_mask = frame_pwr >= mu_fp + max(3.5 * sigma_fp, 0.35 * (q_max - mu_fp))
        if not np.any(active_mask):
            active_mask = frame_pwr >= 0.5 * q_max
        pxx = np.mean(frames[active_mask], axis=0)
        if np.sum(low_frames) >= 1:
            quiet_psd = np.mean(frames[low_frames], axis=0)
    else:
        pxx = np.mean(frames, axis=0)

    df = float(fs / nperseg)
    freqs = np.fft.fftshift(np.fft.fftfreq(nperseg, d=1.0 / fs))

    # Smooth spectral envelope with edge padding (bridges even SF5 preamble comb teeth spaced by BW/32)
    env_w = max(3, nperseg // 16)
    pad_l = env_w // 2
    pad_r = env_w - 1 - pad_l
    pxx_pad = np.pad(pxx, (pad_l, pad_r), mode="edge")
    p_env = np.convolve(pxx_pad, np.ones(env_w, dtype=np.float64) / float(env_w), mode="valid")

    edge_trim = max(2, int(0.05 * nperseg))
    env_int = p_env[edge_trim : nperseg - edge_trim] if nperseg > 2 * edge_trim + 4 else p_env
    env_top = float(np.percentile(env_int, 95.0))
    env_p10 = float(np.percentile(env_int, 10.0))

    oob_mask = np.zeros(nperseg, dtype=bool)
    oob_mask[edge_trim : nperseg - edge_trim] = env_int <= max(env_p10 * 1.15, env_p10 + 1e-30)
    oob_bins = pxx[oob_mask] if np.any(oob_mask) else pxx
    mu_noise = float(np.median(oob_bins))
    mad_noise = float(np.median(np.abs(oob_bins - mu_noise)))
    sigma_bin = 1.4826 * mad_noise
    sigma_env = sigma_bin / np.sqrt(float(env_w))

    n_quiet: Optional[float] = None
    if quiet_psd is not None:
        q_int = quiet_psd[edge_trim : nperseg - edge_trim] if nperseg > 2 * edge_trim + 4 else quiet_psd
        n_quiet = float(np.median(q_int))

    if n_quiet is not None and n_quiet > 1e-30:
        if mu_noise > 1.8 * n_quiet:
            has_oob = False
        else:
            has_oob = env_top > mu_noise + max(4.0 * sigma_env, 0.18 * mu_noise)
    else:
        has_oob = env_top > 2.6 * max(mu_noise, 1e-30)

    if has_oob:
        sig_height = env_top - mu_noise
        env_gate = mu_noise + max(3.5 * sigma_env, 0.15 * sig_height)
        above = p_env >= env_gate
        if np.any(above):
            padded = np.concatenate([[False], above, [False]])
            diffs = np.diff(padded.astype(np.int8))
            c_starts = np.where(diffs == 1)[0]
            c_ends = np.where(diffs == -1)[0]
            best_a, best_b = 0, nperseg
            best_e = -1.0
            for a, b in zip(c_starts, c_ends):
                e = float(np.sum(np.maximum(0.0, pxx[a:b] - mu_noise)))
                if e > best_e:
                    best_e = e
                    best_a, best_b = int(a), int(b)
            guard = max(1, env_w // 6)
            best_a = max(0, best_a - guard)
            best_b = min(nperseg, best_b + guard)
            spec = np.zeros_like(pxx)
            bin_floor = mu_noise + min(2.0 * sigma_bin, 0.20 * sig_height)
            spec[best_a:best_b] = np.maximum(0.0, pxx[best_a:best_b] - bin_floor)
            if float(np.sum(spec)) <= 0.0:
                spec[best_a:best_b] = np.maximum(0.0, pxx[best_a:best_b] - mu_noise)
        else:
            spec = np.maximum(0.0, pxx - mu_noise)
    else:
        if n_quiet is not None and env_top > 1.35 * n_quiet:
            spec = np.maximum(0.0, pxx - n_quiet)
        else:
            spec = pxx.copy()

    spec_sum = float(np.sum(spec))
    if spec_sum <= 0.0 or not np.isfinite(spec_sum):
        return float(fs), 0.0

    frac = float(np.clip(obw_percent / 100.0, 0.50, 0.999))
    tail = 0.5 * (1.0 - frac)

    cdf_edges = np.concatenate([[0.0], np.cumsum(spec) / spec_sum])
    freq_edges = np.concatenate([freqs - 0.5 * df, [freqs[-1] + 0.5 * df]])
    f_lo = float(np.interp(tail, cdf_edges, freq_edges))
    f_hi = float(np.interp(1.0 - tail, cdf_edges, freq_edges))

    obw_hz = max(df, float(f_hi - f_lo) / frac)
    f_center = 0.5 * (f_lo + f_hi)
    return obw_hz, f_center


def _find_active_burst_span(iq_proc: np.ndarray) -> Tuple[int, int]:
    """Locate active burst span [s0, s1] robustly across arbitrary duty cycles and low SNR."""
    n = len(iq_proc)
    if n < 32:
        return 0, max(0, n - 1)

    mag2 = (iq_proc.real.astype(np.float64) ** 2) + (iq_proc.imag.astype(np.float64) ** 2)
    win = max(16, min(256, n // 16))
    env = np.convolve(mag2, np.ones(win, dtype=np.float64) / float(win), mode="same")

    p98 = float(np.percentile(env, 98.0))
    if p98 <= 1e-20:
        return 0, n - 1
    p15 = float(np.percentile(env, 15.0))
    low_vals = env[env <= float(np.percentile(env, 35.0))]
    mu_n = float(np.median(low_vals)) if len(low_vals) > 0 else p15
    sigma_n = 1.4826 * float(np.median(np.abs(low_vals - mu_n))) if len(low_vals) > 0 else 0.0

    if p98 > mu_n + max(4.0 * sigma_n, 0.25 * mu_n):
        thresh = mu_n + max(3.0 * sigma_n, 0.25 * (p98 - mu_n))
    else:
        thresh = 0.20 * p98

    above = env >= thresh
    if not np.any(above):
        return 0, n - 1

    padded = np.concatenate([[False], above, [False]])
    diffs = np.diff(padded.astype(np.int8))
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]

    gap_tol = max(32, win // 2)
    m_starts: List[int] = []
    m_ends: List[int] = []
    for a, b in zip(starts, ends):
        if m_starts and (int(a) - m_ends[-1]) <= gap_tol:
            m_ends[-1] = int(b)
        else:
            m_starts.append(int(a))
            m_ends.append(int(b))

    best_s0, best_s1 = 0, n - 1
    best_e = -1.0
    for a, b in zip(m_starts, m_ends):
        e = float(np.sum(np.maximum(0.0, env[a:b] - mu_n)))
        if e > best_e:
            best_e = e
            best_s0, best_s1 = int(a), int(b) - 1

    return best_s0, max(best_s0 + 1, best_s1)


def _estimate_symbol_time_and_sf(active_span: np.ndarray, bw: float) -> Tuple[int, float]:
    """
    Measure LoRa symbol time T_sym (seconds) via octave-matched normalized preamble
    autocorrelation, then compute SF = round(log2(BW * T_sym)) clamped to [5, 12].
    Returns (sf, t_sym_seconds).
    """
    total_len = len(active_span)
    tau_global_max = min(total_len // 2, int(round(2.0 ** 12.5)))
    if tau_global_max < 24 or bw <= 0.0:
        return 7, (2 ** 7) / max(bw, 1.0)

    rho_full = np.zeros(tau_global_max + 1, dtype=np.float64)
    prom_full = np.zeros(tau_global_max + 1, dtype=np.float64)

    for k in range(5, 13):
        tau_lo = max(22, int(np.floor(2.0 ** (k - 0.5))))
        tau_hi = min(tau_global_max, int(np.floor(2.0 ** (k + 0.5))))
        if tau_lo > tau_hi:
            continue

        win_len = min(total_len, 8 * (1 << k))
        if win_len <= tau_lo + 8:
            continue
        tau_hi_eff = min(tau_hi, win_len - 8)
        if tau_lo > tau_hi_eff:
            continue

        seg = np.asarray(active_span[:win_len], dtype=np.complex128)
        m_fft = 1 << int(np.ceil(np.log2(2 * win_len)))
        x_fft = np.fft.fft(seg, n=m_fft)
        r_raw = np.abs(np.fft.ifft(x_fft * np.conj(x_fft))[: tau_hi_eff + 1])

        pwr = (seg.real ** 2) + (seg.imag ** 2)
        csum = np.concatenate([[0.0], np.cumsum(pwr)])

        taus = np.arange(tau_lo, tau_hi_eff + 1, dtype=np.int64)
        e_left = csum[win_len - taus]
        e_right = csum[win_len] - csum[taus]
        denom = np.sqrt(np.maximum(e_left * e_right, 1e-30))

        rho = r_raw[tau_lo : tau_hi_eff + 1] / denom
        rho_full[tau_lo : tau_hi_eff + 1] = rho
        prom_full[tau_lo : tau_hi_eff + 1] = np.maximum(0.0, rho - float(np.median(rho)))

    best_tau = int(np.argmax(prom_full))
    best_rho = float(rho_full[best_tau])
    if best_tau < 22 or best_rho <= 0.0:
        return 7, (2 ** 7) / bw

    # Step down from harmonics m * tau_0 (for long preambles) to fundamental period tau_0
    chosen_tau = best_tau
    for mult in (8, 7, 6, 5, 4, 3, 2):
        cand = int(round(best_tau / float(mult)))
        if cand < 22:
            continue
        lo_c = max(22, cand - 2)
        hi_c = min(tau_global_max, cand + 2)
        sub_idx = lo_c + int(np.argmax(rho_full[lo_c : hi_c + 1]))
        if rho_full[sub_idx] >= 0.65 * best_rho and prom_full[sub_idx] >= 0.55 * prom_full[best_tau]:
            chosen_tau = sub_idx
            break

    # Parabolic sub-sample refinement of symbol period
    tau_refined = float(chosen_tau)
    if 22 < chosen_tau < tau_global_max:
        y0, y1, y2 = rho_full[chosen_tau - 1], rho_full[chosen_tau], rho_full[chosen_tau + 1]
        denom_p = y0 - 2.0 * y1 + y2
        if abs(denom_p) > 1e-12 and y1 >= y0 and y1 >= y2:
            delta = 0.5 * (y0 - y2) / denom_p
            if abs(delta) <= 0.5:
                tau_refined = float(chosen_tau) + float(delta)

    t_sym = tau_refined / float(bw)
    sf_float = float(np.log2(max(1.0, float(bw) * t_sym)))
    sf = int(np.clip(int(round(sf_float)), 5, 12))
    return sf, t_sym


def _estimate_chirp_direction(active_span: np.ndarray, sf: int) -> str:
    """Determine LoRa preamble chirp polarity ('up' or 'down') for a known SF at fs = BW."""
    N = 1 << int(sf)
    n = np.arange(N, dtype=np.float64)
    c_up = np.exp(1j * 2.0 * np.pi * (-0.5 * n + 0.5 * (n ** 2) / float(N)), dtype=np.complex64)
    c_down = np.conj(c_up)

    pre_region = active_span[: min(len(active_span), 6 * N)]
    if len(pre_region) < N:
        return "up"
    corr_up = np.abs(sp_signal.fftconvolve(pre_region, c_up[::-1].conj(), mode="valid"))
    corr_down = np.abs(sp_signal.fftconvolve(pre_region, c_down[::-1].conj(), mode="valid"))
    k_top = min(6, len(corr_up))
    score_up = float(np.sum(np.sort(corr_up)[-k_top:] ** 2))
    score_down = float(np.sum(np.sort(corr_down)[-k_top:] ** 2))
    return "up" if score_up >= score_down else "down"


def _demodulate_lora_iq(
    iq: np.ndarray,
    fs: float,
    overlay_bw: float = 0.0,
    sf_param: int = 0,
    bw_param: float = 0.0,
    trim_edges: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Core physical-layer LoRa demodulator. Returns dictionary of extracted signal parameters
    and decoded symbols, or None if burst is invalid or preamble/SFD is not detected.
    """
    if len(iq) < 32 or fs <= 0.0:
        return None

    # 1. Measure precise Occupied Bandwidth (OBW) & snap to nearest legal LoRa BW
    obw_hz, f_band_offset = _measure_lora_obw(iq, fs)
    if bw_param > 0:
        bw = min(LEGAL_LORA_BWS, key=lambda b: abs(b - float(bw_param)))
    else:
        bw = min(LEGAL_LORA_BWS, key=lambda b: abs(b - float(obw_hz)))

    # 2. Coarse frequency centering, zero-phase anti-alias filtering, & resampling to fs_chip = bw
    iq_work = np.asarray(iq, dtype=np.complex64)
    f_shift_hz = 0.0
    if fs > 1.08 * bw and abs(f_band_offset) > 0.005 * bw:
        max_shift = max(0.0, 0.5 * (fs - bw))
        f_shift_hz = float(np.clip(f_band_offset, -max_shift, max_shift))
        if abs(f_shift_hz) > 0.0:
            t_vec = np.arange(len(iq_work), dtype=np.float64) / float(fs)
            iq_work = (iq_work * np.exp(-1j * 2.0 * np.pi * f_shift_hz * t_vec)).astype(np.complex64)

    if fs > 1.08 * bw and len(iq_work) >= 64:
        cutoff = min(0.55 * bw, 0.49 * fs)
        sos = sp_signal.butter(6, cutoff / (0.5 * fs), btype="low", output="sos")
        iq_work = sp_signal.sosfiltfilt(sos, iq_work).astype(np.complex64)

    target_len = max(2, int(round(len(iq_work) * (bw / fs))))
    if target_len != len(iq_work):
        iq_proc = np.asarray(sp_signal.resample(iq_work, target_len), dtype=np.complex64)
    else:
        iq_proc = iq_work
    fs_chip = float(bw)

    # 3. Detect active burst core (always used for symbol-time/SF measurement; used for sync if trim_edges)
    det_s0, det_s1 = _find_active_burst_span(iq_proc)
    core_span = iq_proc[det_s0 : det_s1 + 1]
    if len(core_span) < 32:
        return None

    if trim_edges:
        s0 = det_s0
        active_span = core_span
    else:
        s0 = 0
        active_span = iq_proc

    # 4. Measure Symbol Time (T_sym), calculate SF = round(log2(BW * T_sym)), and detect Chirp Direction
    sf_auto, t_sym_measured = _estimate_symbol_time_and_sf(core_span, fs_chip)
    if sf_param in range(5, 13):
        sf = int(sf_param)
    else:
        sf = int(sf_auto)
    direction = _estimate_chirp_direction(core_span, sf)

    N = 2 ** sf
    n = np.arange(N, dtype=np.float64)
    # Discrete base upchirp over [0, N-1]
    c_up = np.exp(1j * 2.0 * np.pi * (-0.5 * n + 0.5 * (n ** 2) / float(N)), dtype=np.complex64)
    c_down = np.conj(c_up)

    pre_chirp = c_up if direction == "up" else c_down
    sfd_chirp = c_down if direction == "up" else c_up
    pre_ref = np.conj(pre_chirp)

    if len(active_span) < 5 * N:
        return None

    # 5. SFD & Preamble Synchronization via FFT correlation
    corr_sfd = np.abs(sp_signal.fftconvolve(active_span, sfd_chirp[::-1].conj(), mode="valid"))
    if len(corr_sfd) == 0:
        return None

    p_sfd = int(np.argmax(corr_sfd))
    # If argmax selected the 2nd SFD chirp, check if 1st chirp (~N samples prior) is strong:
    if p_sfd >= N:
        lo_1 = max(0, p_sfd - N - 2)
        hi_1 = min(len(corr_sfd), p_sfd - N + 3)
        if hi_1 > lo_1:
            p_cand1 = lo_1 + int(np.argmax(corr_sfd[lo_1:hi_1]))
            if corr_sfd[p_cand1] >= 0.68 * corr_sfd[p_sfd]:
                p_sfd = p_cand1

    corr_pre = np.abs(sp_signal.fftconvolve(active_span[: max(0, p_sfd - N)], pre_chirp[::-1].conj(), mode="valid"))
    if len(corr_pre) == 0:
        return None

    # Target the last preamble chirp (nominally 3 symbols prior to SFD start: 2 NetID + 1 Preamble)
    target_idx = p_sfd - 3 * N
    win_start = max(0, target_idx - N // 2)
    win_end = min(len(corr_pre), target_idx + N // 2)
    if win_end <= win_start:
        p_pre = int(np.argmax(corr_pre))
    else:
        p_pre = win_start + int(np.argmax(corr_pre[win_start:win_end]))

    # Symmetric cancellation of CFO timing shift:
    # Upchirp: p_sfd = t + dt, p_pre + 3N = t - dt
    # Downchirp: p_sfd = t - dt, p_pre + 3N = t + dt
    # In both cases: sfd_start = (p_sfd + (p_pre + 3N)) / 2
    sfd_start_rel = int(round((p_sfd + (p_pre + 3 * N)) / 2.0))
    sfd_start = s0 + sfd_start_rel

    if sfd_start - 3 * N < 0 or sfd_start + int(round(2.25 * N)) > len(iq_proc):
        return None

    # 6. Accurate CFO Recovery on aligned dechirped preamble symbols
    pre_seg = iq_proc[sfd_start - 3 * N : sfd_start - 2 * N]
    pre_prev = iq_proc[sfd_start - 4 * N : sfd_start - 3 * N] if sfd_start >= 4 * N else pre_seg

    fft_pre = np.fft.fft(pre_seg * pre_ref)
    fft_prev = np.fft.fft(pre_prev * pre_ref)
    k_bin = int(np.argmax(np.abs(fft_pre) + np.abs(fft_prev)))
    k_cfo = k_bin if k_bin < N // 2 else k_bin - N

    if sfd_start >= 4 * N:
        dot = fft_pre[k_bin] * np.conj(fft_prev[k_bin])
        cfo_frac = float(np.angle(dot) / (2.0 * np.pi * (N / bw)))
    else:
        cfo_frac = 0.0
    cfo_local_hz = float((k_cfo * (bw / N)) + cfo_frac)
    cfo_hz = float(f_shift_hz + cfo_local_hz)

    avg_preamble_power = float(np.mean(np.abs(pre_seg) ** 2))

    # 7. Extract the 2 NetID / Sync Word symbols immediately before SFD
    n1_seg = iq_proc[sfd_start - 2 * N : sfd_start - N]
    n2_seg = iq_proc[sfd_start - N : sfd_start]
    if direction == "up":
        n1 = (int(np.argmax(np.abs(np.fft.fft(n1_seg * pre_ref)))) - k_cfo) % N
        n2 = (int(np.argmax(np.abs(np.fft.fft(n2_seg * pre_ref)))) - k_cfo) % N
    else:
        n1 = (k_cfo - int(np.argmax(np.abs(np.fft.fft(n1_seg * pre_ref))))) % N
        n2 = (k_cfo - int(np.argmax(np.abs(np.fft.fft(n2_seg * pre_ref))))) % N
    netid = [int(n1), int(n2)]

    # 8. Payload Demodulation after SFD (SFD is 2.25 symbols long in standard LoRa)
    payload_start = sfd_start + int(round(2.25 * N))
    payload_symbols: List[int] = []
    curr = payload_start
    min_power_threshold = 0.08 * avg_preamble_power

    while curr + N <= len(iq_proc):
        seg = iq_proc[curr : curr + N]
        pwr = float(np.mean(np.abs(seg) ** 2))
        if pwr < min_power_threshold:
            # End of Burst (EOB) reached via energy drop
            break

        spec = np.abs(np.fft.fft(seg * pre_ref))
        peak_b = int(np.argmax(spec))
        if direction == "up":
            sym_val = (peak_b - k_cfo) % N
        else:
            sym_val = (k_cfo - peak_b) % N

        payload_symbols.append(int(sym_val))
        curr += N

    return {
        "sf": sf,
        "bw": bw,
        "obw_hz": float(obw_hz),
        "t_sym_s": float(N / bw),
        "t_sym_measured_s": float(t_sym_measured),
        "direction": direction,
        "netid": netid,
        "cfo_hz": cfo_hz,
        "symbols": payload_symbols,
        "num_symbols": len(payload_symbols),
        "sfd_start_sample": sfd_start,
        "payload_start_sample": payload_start,
        "best_tau": sfd_start,
        "N": N,
        "fs_chip": float(fs_chip),
        "f_demod": _fm_demod(iq_proc, fs_chip, cfo_local_hz),
    }


def _fm_demod(iq: np.ndarray, fs: float, cfo_hz: float = 0.0) -> np.ndarray:
    """Instantaneous frequency in Hz, with the recovered CFO removed."""
    if iq is None or len(iq) < 2 or fs <= 0.0:
        return np.zeros(0, dtype=np.float64)
    prod = iq[1:] * np.conj(iq[:-1])
    f_inst = np.angle(prod).astype(np.float64) * (float(fs) / (2.0 * np.pi))
    return f_inst - float(cfo_hz)


def _lora_fm_regions(
    t0: float,
    fs: float,
    sfd_start: int,
    payload_start: int,
    n_sym: int,
    netid: List[int],
    symbols: List[int],
) -> List[Dict[str, Any]]:
    """Shaded time spans for the two NetID symbols, the SFD, and each payload symbol."""
    if fs <= 0.0 or n_sym <= 0:
        return []

    def span(start: int, end: int) -> Tuple[float, float]:
        return float(t0 + start / fs), float(t0 + end / fs)

    regions: List[Dict[str, Any]] = []
    for i, value in enumerate(netid[:2]):
        start = int(sfd_start) - (2 - i) * n_sym
        end = start + n_sym
        if end <= start:
            continue
        x0, x1 = span(start, end)
        regions.append({
            "x_start": x0,
            "x_end": x1,
            "color": "#ffb020",
            "alpha": 0.20,
            "label": "NetID",
            "text": str(int(value)),
        })

    if payload_start > sfd_start:
        x0, x1 = span(int(sfd_start), int(payload_start))
        regions.append({
            "x_start": x0,
            "x_end": x1,
            "color": "#29b6f6",
            "alpha": 0.22,
            "label": "SFD",
            "text": "SFD",
        })

    symbol_colors = ("#7e57c2", "#26a69a")
    payload = int(payload_start)
    for i, value in enumerate(symbols):
        start = payload + i * n_sym
        end = start + n_sym
        x0, x1 = span(start, end)
        regions.append({
            "x_start": x0,
            "x_end": x1,
            "color": symbol_colors[i % 2],
            "alpha": 0.16,
            "label": "Symbol",
            "text": str(int(value)),
        })
    return regions


def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    """
    Main plugin execution point. Demodulates all `Rect` overlays in `info.overlays`.
    """
    result = PluginResult()

    target_overlays = [
        o for o in info.overlays
        if o.shape == OverlayShape.RECT or (hasattr(o, "_shape_name") and o._shape_name() == "RECT")
    ]

    if not target_overlays:
        result.log("No Rect overlays found in active scope.")
        result.warning("No Rect overlays found in the active scope to demodulate.", title="LoRa Demodulator")
        return result

    sf_param          = int(float(info.params.get("sf", 0)))
    bw_param          = float(info.params.get("bw", 0.0))
    trim_edges        = bool(info.params.get("trim_edges", True))
    max_hover_symbols = max(4, int(info.params.get("max_hover_symbols", 32)))
    debug_plots       = bool(info.params.get("debug_plots", False))

    total = len(target_overlays)
    demod_count = 0

    for idx, ov in enumerate(target_overlays):
        if info.is_cancelled():
            break

        info.progress(int((idx / total) * 100), f"Demodulating burst {idx + 1}/{total}…")

        burst_iq, burst_fs = ov.get_samples(samples, info)
        if burst_iq is None or len(burst_iq) < 32:
            continue

        res = _demodulate_lora_iq(
            iq=burst_iq,
            fs=float(burst_fs),
            overlay_bw=float(ov.bandwidth),
            sf_param=sf_param,
            bw_param=bw_param,
            trim_edges=trim_edges,
        )

        if res is None:
            continue

        sf           = res["sf"]
        bw           = res["bw"]
        obw_hz       = res["obw_hz"]
        direction    = res["direction"]
        netid        = res["netid"]
        cfo_hz       = res["cfo_hz"]
        symbols      = res["symbols"]
        num_symbols  = res["num_symbols"]
        symbol_rate  = float(bw / (2 ** sf))
        sym_time_ms  = float((2 ** sf) / bw * 1000.0)

        netid_hex_str = f"0x{netid[0]:02X} 0x{netid[1]:02X}"
        bw_str = _format_hz(bw)
        obw_str = _format_hz(obw_hz)
        dir_label = "Upchirp (Standard)" if direction == "up" else "Downchirp (Inverted)"

        # 1. Update metadata
        new_meta = copy.deepcopy(ov.metadata or {})
        new_meta.update({
            "protocol":        "LoRa",
            "sf":              int(sf),
            "bw_hz":           float(bw),
            "obw_hz":          round(float(obw_hz), 1),
            "symbol_time_ms":  round(sym_time_ms, 4),
            "symbol_rate":     round(symbol_rate, 2),
            "chirp_direction": direction,
            "netid":           [int(netid[0]), int(netid[1])],
            "netid_hex":       netid_hex_str,
            "cfo_hz":          round(float(cfo_hz), 1),
            "num_symbols":     int(num_symbols),
            "symbols":         [int(s) for s in symbols],
        })

        # 2. Display label and hover tooltip
        display_label = f"LoRa SF{sf} {bw_str} | NetID: [{netid[0]},{netid[1]}] | {num_symbols} syms"

        preview_syms = symbols[:max_hover_symbols]
        syms_str = ", ".join(str(s) for s in preview_syms)
        if len(symbols) > max_hover_symbols:
            syms_str += f", … (+{len(symbols) - max_hover_symbols} more)"

        hover_lines = [
            f"LoRa Physical Layer ({dir_label})",
            f"SF: {sf} | BW: {bw_str} (OBW: {obw_str}) | T_sym: {sym_time_ms:.3f} ms ({symbol_rate:.1f} sym/s)",
            f"CFO: {cfo_hz:+.1f} Hz | NetID: [{netid[0]}, {netid[1]}] ({netid_hex_str})",
            f"Payload Symbols ({num_symbols}):",
            f"[{syms_str}]",
        ]
        hover_tooltip = "\n".join(hover_lines)

        # 3. Patch overlay
        result.update(
            ov.id,
            display_str=display_label,
            hover_str=hover_tooltip,
            metadata=new_meta,
            locked=True,
        )
        demod_count += 1

        # 4. Optional FM-demod plot with NetID, SFD, and symbol spans
        f_demod = res.get("f_demod")
        if debug_plots and demod_count <= 5 and f_demod is not None and len(f_demod) > 1:
            result.set_plot_tab_title(f"LoRa — SF{sf} {bw_str}")
            fs_chip = float(res["fs_chip"])
            t0 = float(ov.t_start)
            t_axis = t0 + (np.arange(len(f_demod), dtype=np.float64) + 0.5) / fs_chip
            regions = _lora_fm_regions(
                t0=t0,
                fs=fs_chip,
                sfd_start=int(res["sfd_start_sample"]),
                payload_start=int(res["payload_start_sample"]),
                n_sym=int(res["N"]),
                netid=netid,
                symbols=symbols,
            )
            result.add_plot(
                title=f"Burst {idx + 1}: SF{sf} FM ({num_symbols} syms)",
                y={"FM Demod (Hz)": f_demod},
                x=t_axis,
                fs=fs_chip,
                x_label="Time",
                x_units="s",
                y_label="Instantaneous Frequency (Hz)",
                primary_mode="TIME",
                regions=regions,
            )

    result.log(f"Demodulated {demod_count}/{total} LoRa burst(s).")
    if demod_count == 0 and total > 0:
        result.warning(
            f"Could not synchronize or demodulate any LoRa bursts across {total} candidate burst(s).\n\n"
            "Possible causes:\n"
            "• Bursts are not LoRa modulated (e.g. FSK/GFSK or noise).\n"
            "• Selected Spreading Factor (SF) does not match the signal.\n"
            "• Signal-to-noise ratio is too low for chirp preamble synchronization.",
            title="LoRa Demodulator",
        )
    info.progress(100, "Done")
    return result

"""iqview/plugins/builtin/lora_demodulator.py

Built-in IQView Plugin: LoRa Demodulator.

Operates on existing `Rect` overlays in `info.overlays` (using cached `o.iq`
from upstream detectors or lazily extracting from file via `o.get_samples(samples, info)`).
Performs LoRa Chirp Spread Spectrum (CSS) physical layer demodulation:
- Automatic Spreading Factor (SF 5..12) estimation via chirp slope or user override
- Automatic Bandwidth snapping to standard LoRa grid (including 2.4 GHz LoRa)
- Automatic Chirp Direction detection (Upchirp standard uplink vs Downchirp inverted downlink)
- SOB (Start of Burst) symbol clock synchronization and Carrier Frequency Offset (CFO) recovery
- Extraction of the two Sync Word / NetID symbols preceding the SFD
- Demodulation of all post-SFD payload symbols into raw integer values (0 .. 2^SF - 1)
- Automatic EOB (End of Burst) energy-drop termination bounded by overlay time limits
- Optional interactive debug plot tab displaying symbol sequences and dechirped transitions
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy import signal as sp_signal

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

1. **Bandwidth Determination**: When `bw = 0` (Auto), snaps the overlay's frequency bandwidth to the closest legal LoRa standard value (including Sub-GHz 7.8 kHz to 500 kHz and 2.4 GHz 812.5 kHz to 1.625 MHz).
2. **Resampling to Chip Rate**: Resamples the complex baseband signal to the exact chip rate ($f_s = BW$), where each symbol contains exactly $N = 2^{SF}$ samples.
3. **SF & Chirp Direction Estimation**: When `sf = 0` (Auto), computes the instantaneous frequency derivative $\\frac{df}{dt} = \\pm \\frac{BW^2}{2^{SF}}$ on a 2x-oversampled discriminator to determine both the Spreading Factor ($SF \\in [5 \\dots 12]$) and preamble chirp direction (`up` standard or `down` inverted) without ambiguity.
4. **SOB & Symbol Boundary Alignment**: Slices the active burst region and slides the conjugate base chirp across a single symbol window ($N$ samples) to determine the exact sample-aligned symbol clock phase.
5. **CFO & SFD Synchronization**: Scans through preamble unmodulated chirps to estimate integer and fractional Carrier Frequency Offset (CFO). Detects the 2.25-symbol Start of Frame Delimiter (SFD) by measuring the sharp peak in the opposite-polarity dechirped spectrum.
6. **NetID Extraction**: Extracts the raw integer values of the two NetID / Sync Word symbols immediately preceding the SFD.
7. **Payload Demodulation**: Beginning exactly after the 2.25 SFD downchirps, demodulates each symbol window into its raw integer value $S \\in [0, 2^{SF}-1]$.
8. **EOB Termination**: Halts demodulation when symbol energy drops below the preamble threshold or when the overlay boundary is reached.

### Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **Spreading Factor** (`sf`) | `int` | `0` | LoRa Spreading Factor (5 to 12). Set to `0` for automatic detection. |
| **Bandwidth** (`bw`) | `float` | `0.0` | Bandwidth in Hz (e.g. 125000, 250000, 500000, 812500, 1000000). Set to `0` to snap to closest legal LoRa BW. |
| **Trim Noise Edges** (`trim_edges`) | `bool` | `True` | Trim leading/trailing low-energy samples before symbol alignment. |
| **Max Hover Symbols** (`max_hover_symbols`) | `int` | `32` | Maximum number of payload symbols shown in hover tooltip (full list in metadata). |
| **Debug Plots** (`debug_plots`) | `bool` | `False` | Open an interactive plot tab showing payload symbols and dechirped profile. |

### Output Metadata

* `metadata["protocol"]`: `"LoRa"`
* `metadata["sf"]`: Spreading Factor ($5 \\dots 12$)
* `metadata["bw_hz"]`: Bandwidth in Hz
* `metadata["symbol_rate"]`: Symbol rate in symbols/sec ($BW / 2^{SF}$)
* `metadata["chirp_direction"]`: `"up"` (standard uplink) or `"down"` (inverted downlink)
* `metadata["netid"]`: `[netid1, netid2]` (integers $0 \\dots 2^{SF}-1$)
* `metadata["netid_hex"]`: Formatted hex string (e.g. `0x12 0x22`)
* `metadata["cfo_hz"]`: Carrier Frequency Offset in Hz
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
        "type": "int",
        "default": 0,
        "label": "Spreading Factor (0 = Auto)",
        "tooltip": "LoRa Spreading Factor (5 to 12). Set to 0 to automatically detect SF from chirp sweep slope.",
    },
    "bw": {
        "type": "float",
        "default": 0.0,
        "label": "Bandwidth (Hz, 0 = Auto)",
        "tooltip": "Bandwidth in Hz. Set to 0 to automatically snap to the legal LoRa bandwidth matching the overlay.",
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
        "label": "Debug Plots (Symbols & Profile)",
        "tooltip": "Open an interactive 1D plot tab showing demodulated symbol values and dechirped profile.",
    },
}


def _format_hz(hz: float) -> str:
    """Format frequency cleanly in Hz, kHz, or MHz."""
    abs_hz = abs(hz)
    if abs_hz >= 1e6:
        return f"{hz / 1e6:.3f} MHz".rstrip("0").rstrip(".") + " MHz"
    if abs_hz >= 1e3:
        return f"{hz / 1e3:.1f} kHz"
    return f"{hz:.1f} Hz"


def _estimate_sf_and_direction(iq: np.ndarray, fs: float, bw: float) -> Tuple[int, str]:
    """
    Estimate LoRa Spreading Factor (5..12) and chirp direction (up/down) via
    coherent dechirping PAPR across the legal candidate SF hypotheses.
    """
    # Resample to chip rate (fs = bw) so each candidate symbol is 2^SF samples
    target_len = max(2, int(round(len(iq) * (bw / fs))))
    if target_len != len(iq):
        iq_proc = np.asarray(sp_signal.resample(iq, target_len), dtype=np.complex64)
    else:
        iq_proc = np.asarray(iq, dtype=np.complex64)

    best_papr = -1.0
    best_sf = 7
    best_dir = "up"

    for sf_cand in range(5, 13):
        N_cand = 2 ** sf_cand
        if len(iq_proc) < 2 * N_cand:
            continue
        n = np.arange(N_cand, dtype=np.float64)
        c_up = np.exp(1j * 2.0 * np.pi * (-0.5 * n + 0.5 * (n ** 2) / float(N_cand)), dtype=np.complex64)
        c_down = np.conj(c_up)

        # Dechirp test slice inside preamble region
        slice_start = min(len(iq_proc) - N_cand, max(0, N_cand // 2))
        seg = iq_proc[slice_start : slice_start + N_cand]

        spec_up = np.abs(np.fft.fft(seg * np.conj(c_up)))
        papr_up = float(np.max(spec_up) / (np.mean(spec_up) + 1e-12))

        spec_down = np.abs(np.fft.fft(seg * np.conj(c_down)))
        papr_down = float(np.max(spec_down) / (np.mean(spec_down) + 1e-12))

        if papr_up > best_papr:
            best_papr = papr_up
            best_sf = sf_cand
            best_dir = "up"
        if papr_down > best_papr:
            best_papr = papr_down
            best_sf = sf_cand
            best_dir = "down"

    return best_sf, best_dir


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
    if len(iq) < 32:
        return None

    # 1. Bandwidth determination
    if bw_param > 0:
        bw = min(LEGAL_LORA_BWS, key=lambda b: abs(b - float(bw_param)))
    elif overlay_bw > 0:
        bw = min(LEGAL_LORA_BWS, key=lambda b: abs(b - float(overlay_bw)))
    else:
        bw = min(LEGAL_LORA_BWS, key=lambda b: abs(b - float(fs)))

    # 2. Resample to chip rate (fs = bw) so N = 2^SF samples per symbol
    target_len = max(2, int(round(len(iq) * (bw / fs))))
    if target_len != len(iq):
        iq_proc = np.asarray(sp_signal.resample(iq, target_len), dtype=np.complex64)
    else:
        iq_proc = np.asarray(iq, dtype=np.complex64)
    fs_chip = bw

    # 3. Detect active burst span (energy trimming)
    if trim_edges:
        mag2 = (iq_proc.real.astype(np.float64) ** 2) + (iq_proc.imag.astype(np.float64) ** 2)
        win = max(4, min(32, len(iq_proc) // 16))
        env = np.convolve(mag2, np.ones(win, dtype=np.float64) / float(win), mode="same")
        peak_ref = float(np.percentile(env, 75.0))
        if peak_ref <= 1e-20:
            return None
        active = np.where(env >= 0.20 * peak_ref)[0]
        if len(active) < 32:
            return None
        s0 = int(active[0])
        s1 = int(active[-1])
        active_span = iq_proc[s0 : s1 + 1]
    else:
        s0 = 0
        s1 = len(iq_proc) - 1
        active_span = iq_proc

    # 4. Spreading Factor (SF) and Chirp Direction
    if sf_param in range(5, 13):
        sf = int(sf_param)
        _, direction = _estimate_sf_and_direction(active_span, fs_chip, bw)
    else:
        sf, direction = _estimate_sf_and_direction(active_span, fs_chip, bw)

    N = 2 ** sf
    n = np.arange(N, dtype=np.float64)
    # Discrete base upchirp over [0, N-1]
    c_up = np.exp(1j * 2.0 * np.pi * (-0.5 * n + 0.5 * (n ** 2) / float(N)), dtype=np.complex64)
    c_down = np.conj(c_up)

    pre_chirp = c_up if direction == "up" else c_down
    sfd_chirp = c_down if direction == "up" else c_up
    pre_ref = np.conj(pre_chirp)
    sfd_ref = np.conj(sfd_chirp)

    if len(active_span) < 5 * N:
        return None

    # 5. SFD & Preamble Synchronization via FFT correlation
    corr_sfd = np.abs(sp_signal.fftconvolve(active_span, sfd_chirp[::-1].conj(), mode="valid"))
    if len(corr_sfd) == 0:
        return None

    p_sfd = int(np.argmax(corr_sfd))
    # If argmax selected the 2nd SFD downchirp, check if 1st chirp (N samples prior) is strong:
    if p_sfd >= N and corr_sfd[p_sfd - N] >= 0.70 * corr_sfd[p_sfd]:
        p_sfd -= N

    corr_pre = np.abs(sp_signal.fftconvolve(active_span[:max(0, p_sfd - N)], pre_chirp[::-1].conj(), mode="valid"))
    if len(corr_pre) == 0:
        return None

    # Target the last preamble chirp (nominally 3 symbols prior to SFD start: 2 NetID + 1 Preamble)
    target_idx = p_sfd - 3 * N
    win_start = max(0, target_idx - N // 2)
    win_end = min(len(corr_pre), target_idx + N // 2)
    if win_end <= win_start:
        p_pre = int(np.argmax(corr_pre))
    else:
        p_pre = win_start + int(np.argmax(corr_pre[win_start : win_end]))

    # Symmetric cancellation of CFO timing shift:
    # Upchirp: p_sfd = t + dt, p_pre + 3N = t - dt
    # Downchirp: p_sfd = t - dt, p_pre + 3N = t + dt
    # In both cases: sfd_start = (p_sfd + (p_pre + 3N)) / 2
    sfd_start_rel = int(round((p_sfd + (p_pre + 3 * N)) / 2.0))
    sfd_start = s0 + sfd_start_rel

    if sfd_start - 3 * N < 0 or sfd_start + int(round(2.25 * N)) > len(iq_proc):
        return None

    # 6. Accurate CFO Recovery on aligned preamble symbols
    pre_seg = iq_proc[sfd_start - 3 * N : sfd_start - 2 * N]
    spec_pre = np.abs(np.fft.fft(pre_seg * pre_ref))
    k_bin = int(np.argmax(spec_pre))
    k_cfo = k_bin if k_bin < N // 2 else k_bin - N

    pre_prev = iq_proc[sfd_start - 4 * N : sfd_start - 3 * N] if sfd_start >= 4 * N else pre_seg
    t_N = np.arange(N, dtype=np.float64) / bw
    p1_derot = pre_prev * np.exp(-1j * 2.0 * np.pi * (k_cfo * bw / N) * t_N)
    p2_derot = pre_seg * np.exp(-1j * 2.0 * np.pi * (k_cfo * bw / N) * (t_N + N / bw))
    dot = np.sum(p2_derot * np.conj(p1_derot))
    cfo_frac = float(np.angle(dot) / (2.0 * np.pi * (N / bw)))
    cfo_hz = float((k_cfo * (bw / N)) + cfo_frac)

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
        "direction": direction,
        "netid": netid,
        "cfo_hz": cfo_hz,
        "symbols": payload_symbols,
        "num_symbols": len(payload_symbols),
        "sfd_start_sample": sfd_start,
        "payload_start_sample": payload_start,
        "best_tau": sfd_start,
        "N": N,
    }


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
        return result

    sf_param          = int(info.params.get("sf", 0))
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
        direction    = res["direction"]
        netid        = res["netid"]
        cfo_hz       = res["cfo_hz"]
        symbols      = res["symbols"]
        num_symbols  = res["num_symbols"]
        symbol_rate  = float(bw / (2 ** sf))

        netid_hex_str = f"0x{netid[0]:02X} 0x{netid[1]:02X}"
        bw_str = _format_hz(bw)
        dir_label = "Upchirp (Standard)" if direction == "up" else "Downchirp (Inverted)"

        # 1. Update metadata
        new_meta = copy.deepcopy(ov.metadata or {})
        new_meta.update({
            "protocol":        "LoRa",
            "sf":              int(sf),
            "bw_hz":           float(bw),
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
            f"SF: {sf} | BW: {bw_str} | Rate: {symbol_rate:.1f} sym/s",
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

        # 4. Optional interactive debug plot tab
        if debug_plots and demod_count <= 5 and num_symbols > 0:
            result.set_plot_tab_title(f"LoRa — SF{sf} {bw_str}")
            sym_arr = np.asarray(symbols, dtype=np.float64)
            sym_idx = np.arange(len(symbols), dtype=np.float64)

            result.add_plot(
                title=f"Burst {idx + 1}: SF{sf} ({num_symbols} syms)",
                y={"Symbol Value": sym_arr},
                x=sym_idx,
                x_label="Payload Symbol Index",
                x_units="",
                y_label=f"Value (0 .. {2**sf - 1})",
                primary_mode="TIME",
            )

    result.log(f"Demodulated {demod_count}/{total} LoRa burst(s).")
    info.progress(100, "Done")
    return result

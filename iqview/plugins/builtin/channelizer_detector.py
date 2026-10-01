"""iqview/plugins/builtin/channelizer_detector.py

Built-in IQView Plugin: Channelizer + Energy Detector.

Channelizes the wideband IQ signal into uniform (or overlapping) frequency
channels and runs an adaptive two-speed IIR / Moving-Average Energy Detector
with m-out-of-n hysteresis on each channel.
"""

from __future__ import annotations

import numpy as np
from scipy import fft as sp_fft
from scipy import signal as sp_signal

from iqview import PluginResult
from iqview.overlays import Rect


PLUGIN_NAME        = "Channelizer + Energy Detector"
PLUGIN_DESCRIPTION = (
    "Channelizes wideband IQ (with configurable channel spacing, reference "
    "center frequency, and overlap) and detects bursts per channel using a "
    "Moving Average + dual-alpha IIR + m-out-of-n state machine."
)
PLUGIN_CATEGORY    = "Detection"

PLUGIN_DOC = """# Channelizer + Energy Detector

Divides the active frequency span `[f_start, f_end]` into uniform or overlapping narrowband channels anchored at **Reference Channel Fc**, down-converts each channel to baseband using a single-FFT frequency-domain DDC with a 12th-order zero-phase Butterworth filter, and runs a two-speed adaptive IIR + *M*-out-of-*N* hysteresis energy detector on each channel.

### Algorithm & Operation

1. **Channel Grid Deduction**: Channel center frequencies are placed at `f_k = ref_channel_fc + k * channel_spacing * (1 - overlap)` within `[f_start, f_end]`.
2. **Single-FFT Frequency-Domain DDC**: A single multithreaded wideband FFT is computed once. Each channel slices its passband bins, applies a zero-phase Butterworth low-pass response, and executes a narrowband IFFT of rate `ch_fs = channel_spacing`.
3. **FIR Envelope (Moving Average)**: Computes the instantaneous magnitude `|IQ|` and smooths it with an `L`-tap moving average filter (`FIR`).
4. **Dual-Alpha IIR & M-out-of-N State Machine**:
   - **INIT (Gray)**: Runs for `init_chunks * chunk_size` samples using `alpha_low` so the noise-floor IIR converges before detection starts.
   - **IDLE (Red)**: Tracks the noise floor with `y[n] = alpha_low * x[n] + (1 - alpha_low) * y[n-1]`. Each sample where `x[n] > threshold * y[n-1]` counts as a hit. When `M` hits occur within the last `N` samples, the detector transitions to **ACTIVE** (burst start at `i - M + 1`) and resets the IIR state to the current FIR value `y = x[n]`.
   - **ACTIVE (Green)**: Tracks the active burst energy with `alpha_high`. Each sample where `x[n] < y[n-1] / threshold` counts as a hit. When `M` hits occur within `N` samples, the detector transitions back to **IDLE** (burst end at `i - M + 1`) and resets `y = x[n]`.
5. **Safeguard Margin & Zero-Copy IQ**: Each detected burst interval `[s0, s1]` is expanded by `margin` samples on both sides (`[max(0, s0 - margin), min(N, s1 + margin)]`) and stored on the resulting locked `Rect` overlay as `o.iq` and `o.fs`.
"""


PLUGIN_PARAMS = {
    "channel_spacing": {
        "type": "float",
        "default": 500000.0,
        "label": "Channel Spacing / BW (Hz)",
        "tooltip": (
            "Bandwidth of each channel in Hz. When overlap is 0, adjacent "
            "channel centers are separated by this exact spacing."
        ),
    },
    "ref_channel_fc": {
        "type": "float",
        "default": 0.0,
        "label": "Reference Channel Fc (Hz)",
        "tooltip": (
            "Center frequency (Hz) of one known channel. All other channel "
            "centers in the active frequency span are deduced from this anchor."
        ),
    },
    "overlap": {
        "type": "float",
        "default": 0.0,
        "label": "Channel Overlap (0–1)",
        "tooltip": (
            "Fractional overlap between adjacent channels (0.0 = no overlap, "
            "0.5 = 50% overlap -> step = 0.5 * channel_spacing)."
        ),
    },
    "threshold_db": {
        "type": "float",
        "default": 6.0,
        "label": "Threshold (dB)",
        "tooltip": (
            "Threshold in dB above the IIR noise floor to trigger IDLE -> ACTIVE "
            "(e.g. 6 dB corresponds to MA > ~4 * IIR)."
        ),
    },
    "L": {
        "type": "int",
        "default": 8,
        "label": "MA Length (L)",
        "tooltip": "Moving average filter length (samples) applied to |IQ|.",
    },
    "alpha_low": {
        "type": "float",
        "default": 0.001,
        "label": "IIR Alpha Low (IDLE / INIT)",
        "tooltip": (
            "IIR smoothing coefficient during INIT and IDLE noise-floor tracking: "
            "y[n] = alpha_low * x[n] + (1 - alpha_low) * y[n-1]."
        ),
    },
    "alpha_high": {
        "type": "float",
        "default": 0.005,
        "label": "IIR Alpha High (ACTIVE)",
        "tooltip": (
            "IIR smoothing coefficient during ACTIVE burst tracking: "
            "y[n] = alpha_high * x[n] + (1 - alpha_high) * y[n-1]."
        ),
    },
    "m": {
        "type": "int",
        "default": 70,
        "label": "M (Hits Required)",
        "tooltip": "Number of hits out of N tries required to switch state (IDLE <-> ACTIVE).",
    },
    "n": {
        "type": "int",
        "default": 115,
        "label": "N (Window Tries)",
        "tooltip": "Sliding window length (tries) for the M-out-of-N detector.",
    },
    "chunk_size": {
        "type": "int",
        "default": 10000,
        "label": "Chunk Size (samples)",
        "tooltip": "Processing chunk size in channel-rate samples.",
    },
    "init_chunks": {
        "type": "int",
        "default": 3,
        "label": "Init Chunks",
        "tooltip": "Number of initial chunks used to converge the IIR noise floor before entering IDLE.",
    },
    "margin": {
        "type": "int",
        "default": 0,
        "label": "Margin (samples)",
        "tooltip": (
            "Extra safeguard samples taken from each side of every detected burst "
            "([max(0, start - margin), min(N, end + margin)])."
        ),
    },
    "debug": {
        "type": "bool",
        "default": False,
        "label": "Debug Plots (FIR / IIR / State)",
        "tooltip": (
            "When enabled, opens a plot tab showing the FIR (Moving Average), "
            "IIR filter, and State Machine state for up to 5 active channels."
        ),
    },
}


def _run_ed_state_machine(
    ma: np.ndarray,
    alpha_low: float,
    alpha_high: float,
    thresh_mult: float,
    m: int,
    n: int,
    chunk_size: int,
    init_chunks: int,
    record_debug: bool = False,
):
    """
    Chunk-wise IIR + M-out-of-N hysteresis energy detector on moving-average envelope `ma`.
    """
    total_len = len(ma)
    if total_len == 0:
        return [], [], [], None

    iir_trace = np.empty(total_len, dtype=np.float64) if record_debug else None

    one_minus_low = 1.0 - alpha_low
    one_minus_high = 1.0 - alpha_high
    b_low = np.array([alpha_low], dtype=np.float64)
    a_low = np.array([1.0, -one_minus_low], dtype=np.float64)
    b_high = np.array([alpha_high], dtype=np.float64)
    a_high = np.array([1.0, -one_minus_high], dtype=np.float64)

    y = float(ma[0])
    init_samples = init_chunks * chunk_size

    # 1. INIT Phase (fast C lfilter)
    if init_samples >= total_len:
        y_init, _ = sp_signal.lfilter(b_low, a_low, ma, zi=[y * one_minus_low])
        if record_debug:
            iir_trace[:] = y_init
        y = float(y_init[-1])
        start_search_idx = 0
    elif init_samples > 0:
        y_init, _ = sp_signal.lfilter(b_low, a_low, ma[:init_samples], zi=[y * one_minus_low])
        if record_debug:
            iir_trace[:init_samples] = y_init
        y = float(y_init[-1])
        start_search_idx = init_samples
    else:
        start_search_idx = 0

    ring = np.zeros(n, dtype=np.int8)
    ring_idx = 0
    ring_sum = 0

    state = 0  # 0 = IDLE, 1 = ACTIVE
    burst_start = 0
    burst_peak_ratio = 1.0

    starts = []
    ends = []
    peaks = []

    inv_thresh = 1.0 / thresh_mult

    # 2. Chunk-by-chunk IDLE <-> ACTIVE processing
    for c_start in range(start_search_idx, total_len, chunk_size):
        c_end = min(c_start + chunk_size, total_len)
        chunk = ma[c_start:c_end]
        c_len = len(chunk)

        if state == 0:
            y_seq, _ = sp_signal.lfilter(b_low, a_low, chunk, zi=[y * one_minus_low])
            y_prev = np.empty(c_len, dtype=np.float64)
            y_prev[0] = y
            if c_len > 1:
                y_prev[1:] = y_seq[:-1]
            hits = chunk > (thresh_mult * y_prev)
            total_hits = int(np.count_nonzero(hits))

            if ring_sum + total_hits < m:
                if record_debug:
                    iir_trace[c_start:c_end] = y_seq
                y = float(y_seq[-1])
                if c_len >= n:
                    ring[:] = hits[-n:]
                    ring_idx = 0
                    ring_sum = int(np.sum(ring))
                else:
                    for h in hits.astype(np.int8):
                        ring_sum += int(h) - int(ring[ring_idx])
                        ring[ring_idx] = h
                        ring_idx = (ring_idx + 1) % n
                continue
        else:
            y_seq, _ = sp_signal.lfilter(b_high, a_high, chunk, zi=[y * one_minus_high])
            y_prev = np.empty(c_len, dtype=np.float64)
            y_prev[0] = y
            if c_len > 1:
                y_prev[1:] = y_seq[:-1]
            hits = y_prev > (thresh_mult * chunk)
            total_hits = int(np.count_nonzero(hits))

            if ring_sum + total_hits < m:
                if record_debug:
                    iir_trace[c_start:c_end] = y_seq
                max_r = float(np.max(chunk / (y_prev + 1e-30)))
                if max_r > burst_peak_ratio:
                    burst_peak_ratio = max_r
                y = float(y_seq[-1])
                if c_len >= n:
                    ring[:] = hits[-n:]
                    ring_idx = 0
                    ring_sum = int(np.sum(ring))
                else:
                    for h in hits.astype(np.int8):
                        ring_sum += int(h) - int(ring[ring_idx])
                        ring[ring_idx] = h
                        ring_idx = (ring_idx + 1) % n
                continue

        # Slow-path: chunk contains candidate hits that may trigger a state transition
        ring_list = ring.tolist()
        for offset in range(c_len):
            x = float(chunk[offset])
            if state == 0:
                hit = 1 if (x > thresh_mult * y) else 0
                y = alpha_low * x + one_minus_low * y

                ring_sum += hit - ring_list[ring_idx]
                ring_list[ring_idx] = hit
                ring_idx += 1
                if ring_idx == n:
                    ring_idx = 0

                if ring_sum >= m:
                    state = 1
                    i = c_start + offset
                    burst_start = max(start_search_idx, i - m + 1)
                    burst_peak_ratio = x / (y + 1e-30)
                    y = x  # Reset IIR to current FIR value on state switch
                    ring_list = [0] * n
                    ring_sum = 0
                    ring_idx = 0
            else:
                hit = 1 if (x < y * inv_thresh) else 0
                ratio = x / (y + 1e-30)
                if ratio > burst_peak_ratio:
                    burst_peak_ratio = ratio
                y = alpha_high * x + one_minus_high * y

                ring_sum += hit - ring_list[ring_idx]
                ring_list[ring_idx] = hit
                ring_idx += 1
                if ring_idx == n:
                    ring_idx = 0

                if ring_sum >= m:
                    state = 0
                    i = c_start + offset
                    burst_end = i - m + 1
                    if burst_end <= burst_start:
                        burst_end = i
                    starts.append(burst_start)
                    ends.append(burst_end)
                    peaks.append(burst_peak_ratio)
                    y = x  # Reset IIR to current FIR value on state switch
                    ring_list = [0] * n
                    ring_sum = 0
                    ring_idx = 0

            if record_debug:
                iir_trace[c_start + offset] = y

        ring[:] = ring_list

    if state == 1:
        starts.append(burst_start)
        ends.append(total_len - 1)
        peaks.append(burst_peak_ratio)

    return starts, ends, peaks, iir_trace


def _build_state_regions(
    total_len: int,
    init_samples: int,
    starts: list,
    ends: list,
    t_start: float,
    ch_fs: float,
) -> list[dict]:
    """Build shaded X-region dicts for INIT (gray), IDLE (red), and ACTIVE (green)."""
    regions: list[dict] = []
    if total_len <= 1 or ch_fs <= 0:
        return regions

    start_search_idx = min(init_samples, total_len - 1) if init_samples < total_len else 0
    if start_search_idx > 0:
        regions.append({
            "x_start": t_start,
            "x_end": t_start + (start_search_idx / ch_fs),
            "color": "#9e9e9e",
            "alpha": 0.20,
            "label": "INIT",
        })

    curr = start_search_idx
    for s0, s1 in zip(starts, ends):
        s0 = max(curr, int(s0))
        s1 = max(s0, int(s1))
        if s0 > curr:
            regions.append({
                "x_start": t_start + (curr / ch_fs),
                "x_end": t_start + (s0 / ch_fs),
                "color": "#ff5252",
                "alpha": 0.10,
                "label": "IDLE",
            })
        if s1 > s0:
            regions.append({
                "x_start": t_start + (s0 / ch_fs),
                "x_end": t_start + (s1 / ch_fs),
                "color": "#00e676",
                "alpha": 0.20,
                "label": "ACTIVE",
            })
        curr = s1

    if curr < total_len - 1:
        regions.append({
            "x_start": t_start + (curr / ch_fs),
            "x_end": t_start + ((total_len - 1) / ch_fs),
            "color": "#ff5252",
            "alpha": 0.10,
            "label": "IDLE",
        })

    return regions


def _compute_channel_centers(
    f_start: float,
    f_end: float,
    ref_fc: float,
    channel_spacing: float,
    overlap: float,
) -> np.ndarray:
    step = channel_spacing * (1.0 - overlap)
    if step <= 0:
        return np.array([ref_fc], dtype=np.float64)

    k_min = int(np.ceil((f_start - ref_fc) / step))
    k_max = int(np.floor((f_end - ref_fc) / step))
    if k_max < k_min:
        k_closest = int(round(((0.5 * (f_start + f_end)) - ref_fc) / step))
        return np.array([ref_fc + k_closest * step], dtype=np.float64)

    ks = np.arange(k_min, k_max + 1, dtype=np.float64)
    return ref_fc + ks * step


def _channel_color(ch_idx: int) -> str:
    palette = [
        "#00e5ff",
        "#ffab00",
        "#00e676",
        "#ff4081",
        "#7c4dff",
        "#ffd740",
        "#18ffff",
        "#ff6e40",
    ]
    return palette[ch_idx % len(palette)]


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
    channel_spacing = float(params.get("channel_spacing", 25000.0))
    ref_channel_fc  = float(params.get("ref_channel_fc", 0.0))
    overlap         = float(np.clip(params.get("overlap", 0.0), 0.0, 0.95))
    threshold_db    = float(params.get("threshold_db", 6.0))
    L               = max(1, int(params.get("L", 8)))
    alpha_low       = float(np.clip(params.get("alpha_low", 0.001), 1e-6, 1.0))
    alpha_high      = float(np.clip(params.get("alpha_high", 0.005), 1e-6, 1.0))
    m               = max(1, int(params.get("m", 70)))
    n               = max(m, int(params.get("n", 115)))
    chunk_size      = max(64, int(params.get("chunk_size", 10000)))
    init_chunks     = max(0, int(params.get("init_chunks", 3)))
    margin          = max(0, int(params.get("margin", 0)))
    debug           = bool(params.get("debug", False))

    if channel_spacing <= 0 or fs <= 0:
        return result

    thresh_mult = float(10.0 ** (threshold_db / 10.0))

    channel_fcs = _compute_channel_centers(
        f_start, f_end, ref_channel_fc, channel_spacing, overlap
    )
    num_channels = len(channel_fcs)
    if num_channels == 0:
        return result

    work_iq = np.asarray(samples, dtype=np.complex64)
    total_in = len(work_iq)
    duration = total_in / fs
    ch_bw = min(channel_spacing, fs)
    num_ch_samples = max(2, int(round(duration * ch_bw)))
    ch_fs = num_ch_samples / duration if duration > 0 else ch_bw

    info.progress(5, "Computing wideband FFT for channelizer…")

    is_real_only = bool(np.max(np.abs(work_iq.imag)) < 1e-9 * (np.max(np.abs(work_iq.real)) + 1e-30))
    X_full = sp_fft.fft(work_iq, workers=-1)
    if is_real_only and total_in > 2:
        half = total_in // 2
        if total_in % 2 == 0:
            X_full[1:half] *= 2.0
            X_full[half + 1:] = 0.0
        else:
            X_full[1:half + 1] *= 2.0
            X_full[half + 1:] = 0.0

    ch_bin_freqs = sp_fft.fftfreq(num_ch_samples, d=1.0 / ch_fs)
    cutoff = ch_bw * 0.5
    H_lpf = (1.0 / (1.0 + (np.abs(ch_bin_freqs) / max(cutoff, 1e-9)) ** 12)).astype(np.float32)
    scale_factor = np.float32(num_ch_samples / float(total_in))
    H_scaled = H_lpf * scale_factor

    pos_count = (num_ch_samples + 1) // 2
    neg_count = num_ch_samples - pos_count
    rel_bins = np.concatenate([
        np.arange(0, pos_count, dtype=np.int64),
        np.arange(-neg_count, 0, dtype=np.int64),
    ])

    ma_kernel = np.ones(L, dtype=np.float64) / float(L)

    MAX_DEBUG_CHANNELS = 5
    debug_active_channels = []
    init_samples = init_chunks * chunk_size

    for ch_idx, f_ch in enumerate(channel_fcs):
        if info.is_cancelled():
            break

        if ch_idx % max(1, num_channels // 10) == 0:
            pct = 10 + int((ch_idx / max(1, num_channels)) * 88)
            info.progress(pct, f"Channel {ch_idx + 1}/{num_channels} ({f_ch / 1e3:.1f} kHz)…")

        f_offset = f_ch - fc
        center_bin = int(round(f_offset * duration))
        idx_bins = (center_bin + rel_bins) % total_in

        X_ch = X_full[idx_bins] * H_scaled
        ch_iq = sp_fft.ifft(X_ch, overwrite_x=True).astype(np.complex64, copy=False)

        if len(ch_iq) < max(L, n):
            continue

        mag = np.abs(ch_iq).astype(np.float64)
        if L > 1:
            ma = sp_signal.lfilter(ma_kernel, [1.0], mag)
            for k in range(min(L - 1, len(ma))):
                ma[k] = np.mean(mag[: k + 1])
        else:
            ma = mag

        want_debug = debug and (len(debug_active_channels) < MAX_DEBUG_CHANNELS)

        starts, ends, peak_ratios, iir_trace = _run_ed_state_machine(
            ma,
            alpha_low=alpha_low,
            alpha_high=alpha_high,
            thresh_mult=thresh_mult,
            m=m,
            n=n,
            chunk_size=chunk_size,
            init_chunks=init_chunks,
            record_debug=want_debug,
        )

        if not starts:
            continue

        if want_debug and iir_trace is not None:
            regions = _build_state_regions(
                len(ma), init_samples, starts, ends, t_start, ch_fs
            )
            debug_active_channels.append((ch_idx, f_ch, ma, iir_trace, regions))

        ch_color = _channel_color(ch_idx)
        f_lo = f_ch - ch_bw * 0.5
        f_hi = f_ch + ch_bw * 0.5

        for b_idx in range(len(starts)):
            s0 = max(0, int(starts[b_idx]) - margin)
            s1 = min(len(ch_iq), int(ends[b_idx]) + margin)
            if s1 <= s0:
                continue

            b_t0 = t_start + (s0 / ch_fs)
            b_t1 = t_start + (s1 / ch_fs)
            b_dur_ms = (b_t1 - b_t0) * 1e3
            peak_db = float(10.0 * np.log10(max(peak_ratios[b_idx], 1e-12)))

            burst_iq = ch_iq[s0:s1].copy()

            ov_rect = Rect(
                t_start=b_t0,
                f_start=f_lo,
                t_end=b_t1,
                f_end=f_hi,
                color=ch_color,
                alpha=0.18,
                border_width=2,
                border_color=ch_color,
                display_str=f"Ch {ch_idx + 1} ({f_ch / 1e3:.1f} kHz)",
                hover_str=(
                    f"Channel {ch_idx + 1} | Fc: {f_ch:,.1f} Hz | BW: {ch_bw:,.1f} Hz\n"
                    f"Duration: {b_dur_ms:.3f} ms ({len(burst_iq)} samples @ {ch_fs:,.1f} Hz)\n"
                    f"Peak above IIR: +{peak_db:.1f} dB"
                ),
                metadata={
                    "channel_index": int(ch_idx + 1),
                    "channel_fc_hz": round(float(f_ch), 2),
                    "channel_bw_hz": round(float(ch_bw), 2),
                    "overlap": round(float(overlap), 3),
                    "duration_ms": round(float(b_dur_ms), 4),
                    "peak_above_iir_db": round(float(peak_db), 2),
                    "num_samples": int(len(burst_iq)),
                    "sample_rate_hz": round(float(ch_fs), 2),
                },
            )
            ov_rect.iq = burst_iq
            ov_rect.fs = ch_fs
            result.add(ov_rect)

    if debug and debug_active_channels:
        result.set_plot_tab_title("ED Debug (FIR / IIR / State)")
        t_axis = t_start + np.arange(num_ch_samples, dtype=np.float64) / ch_fs
        for ch_idx, f_ch, ma_arr, iir_arr, regions in debug_active_channels[:MAX_DEBUG_CHANNELS]:
            result.add_plot(
                title=f"Ch {ch_idx + 1} ({f_ch / 1e3:.1f} kHz)",
                y={
                    "FIR (MA)": ma_arr,
                    "IIR": iir_arr,
                },
                x=t_axis[: len(ma_arr)],
                fs=ch_fs,
                x_label="Time",
                x_units="s",
                y_label="Amplitude",
                regions=regions,
            )

    info.progress(100, "Done")
    return result

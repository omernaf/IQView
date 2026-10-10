"""iqview/plugins/builtin/signal_comparator.py

Built-in IQView Plugin: Signal Comparator.

Compares the active loaded signal against a 2nd signal file:
- Normalized Complex Cross-Correlation (|ρ_IQ|)
- Differential Cross-Correlation (|ρ_diff|) (CFO/Doppler robust)
- Normalized FM Demodulation Correlation (ρ_FM)
- Subtraction Residual Magnitude (|s1 - s2|)
- Subtraction Residual Phase (wrapped Δθ in radians)
- Occupied Bandwidth (OBW) & Spectral Centroid (fc) Comparison
- Aligned FM Demodulation Overlay (symbol/trajectory tracking)
"""

from __future__ import annotations

import os
import numpy as np
from scipy import signal, fft as sp_fft
from scipy.signal.windows import hann

from iqview import PluginResult, PluginContext
from iqview.overlays import Rect
from iqview.dsp.domain_transforms import compute_instantaneous_frequency
from iqview.utils.helpers import (
    load_mat_file,
    load_audio_file,
    detect_type_from_ext,
    AUDIO_EXTENSIONS,
)


PLUGIN_NAME = "Signal Comparator"
PLUGIN_DESCRIPTION = (
    "Compares the active signal against a 2nd signal: IQ/Diff/FM correlation, "
    "subtraction (abs & phase), OBW, and center frequency."
)
PLUGIN_CATEGORY = "Analysis"
PLUGIN_NEEDS_WIDEBAND_IQ = True
PLUGIN_BATCH_SECONDS = None
PLUGIN_RUN_ON_MAIN_THREAD = False


PLUGIN_DOC = """# Signal Comparator

Performs comprehensive dual-signal comparison between the active workspace signal (Signal 1) and an external recording (Signal 2).

### Analysis Capabilities

1. **Normalized Complex Cross-Correlation ($|\\rho_{\\text{IQ}}|$)**:
   Measures full waveform similarity (phase + envelope coherence). Locates best-match time lag $\\tau^*$ and carrier phase difference $\\Delta\\phi$.
2. **Differential Correlation ($|\\rho_{\\text{diff}}|$)**:
   Correlates conjugate delay products $d[n] = s[n] \\cdot s^*[n-D]$. Highly robust against Carrier Frequency Offset (CFO), oscillator mismatch, and Doppler drift.
3. **Normalized FM Demodulation Correlation ($\\rho_{\\text{FM}}$)**:
   Correlates instantaneous frequency deviation trajectories. Immune to amplitude fluctuations, AGC steps, and RF carrier phase.
4. **Subtraction Residual Magnitude ($|e[n]|$)**:
   Point-by-point envelope residual magnitude $|s_1[n] - s_2[n]|$, reporting EVM (RMS % and dB) and Signal-to-Error Ratio (SER dB).
5. **Subtraction Phase Difference ($\\Delta\\theta$ in Radians)**:
   Instantaneous phase difference $\\text{wrap}_{[-\\pi, \\pi]}(\\arg(s_1) - \\arg(s_2))$ in radians, revealing phase noise and tracking errors.
6. **Spectral Density Comparison (PSD)**:
   Overlaid Welch Power Spectral Density in dB/Hz, reporting Occupied Bandwidth (OBW) and Spectral Centroid ($f_c$) for both signals.
7. **Aligned FM Demodulation Overlay**:
   Overlaid instantaneous frequency tracks showing symbol-level and modulation-level alignment.

### 7 Interactive Sub-Plots ([F1] .. [F7])

The plugin presents an interactive `PluginPlotView` with 7 sub-plot mode buttons:
* **`[F1]` IQ Correlation**: Full waveform normalized cross-correlation profile.
* **`[F2]` Diff Correlation**: Frequency-offset immune differential correlation.
* **`[F3]` FM Correlation**: Frequency modulation trajectory correlation.
* **`[F4]` Subtraction Mag**: Residual error magnitude $|s_1 - s_2|$ with EVM stats.
* **`[F5]` Subtraction Phase**: Phase difference $\\Delta\\theta$ wrapped to $[-\\pi, +\\pi]$ radians.
* **`[F6]` Spectral Comparison**: Overlaid PSDs with shaded OBW bands and centroids.
* **`[F7]` FM Demod Overlay**: Aligned instantaneous frequency trajectories.
"""


PLUGIN_PARAMS = {
    "signal2_path": {
        "type": "file",
        "default": "",
        "label": "Signal 2 File",
        "tooltip": "Path to the 2nd signal file (.32fc, .16tc, .mat, .wav, .bin, etc.)",
    },
    "subtraction_mode": {
        "type": "choice",
        "default": "Aligned (Lag & Phase Corrected)",
        "choices": ["Aligned (Lag & Phase Corrected)", "Raw (Direct Point-by-Point)"],
        "label": "Subtraction Mode",
        "tooltip": "Whether subtraction aligns time lag and carrier phase before calculating residuals",
    },
    "obw_percent": {
        "type": "float",
        "default": 99.0,
        "min": 50.0,
        "max": 99.9,
        "label": "Occupied BW (%)",
        "tooltip": "Percentage of integrated spectral power defining occupied bandwidth",
    },
    "diff_delay": {
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 1000,
        "label": "Diff Delay D (samples)",
        "tooltip": "Conjugate product delay lag: d[n] = s[n] * conj(s[n - D])",
    },
    "max_samples": {
        "type": "int",
        "default": 1000000,
        "min": 1024,
        "label": "Max Samples to Compare",
        "tooltip": "Maximum sample length to analyze from each signal (0 = unlimited)",
    },
    "draw_overlay": {
        "type": "bool",
        "default": True,
        "label": "Draw Match Overlay",
        "tooltip": "Place an overlay on the main spectrogram indicating where Signal 2 matched",
    },
}


def _load_signal2(path: str, default_fs: float, default_fc: float, max_samples: int | None = None) -> tuple[np.ndarray, float, float]:
    """
    Loads samples from the 2nd signal file supporting .mat, audio, and binary IQ formats.
    Returns (samples: complex64 ndarray, fs: float, fc: float).
    """
    norm_path = os.path.normpath(os.path.abspath(path))
    if not os.path.isfile(norm_path):
        raise FileNotFoundError(f"Signal 2 file not found: {path}")

    ext = os.path.splitext(norm_path)[1].lower()
    fs = float(default_fs)
    fc = float(default_fc)

    # 1. Keysight / MATLAB .mat
    if ext == ".mat":
        data_bytes, _t, mat_fs, mat_fc, _is_c = load_mat_file(norm_path)
        samples = np.frombuffer(data_bytes, dtype=np.complex64)
        if mat_fs and mat_fs > 0:
            fs = float(mat_fs)
        if mat_fc is not None:
            fc = float(mat_fc)

    # 2. Audio files
    elif ext in AUDIO_EXTENSIONS:
        data_bytes, type_str, aud_fs, _aud_fc, is_c = load_audio_file(norm_path, complex_iq=True)
        if data_bytes is None:
            raise ValueError(f"Failed to load audio file: {type_str}")
        samples = np.frombuffer(data_bytes, dtype=np.complex64 if is_c else np.float32)
        if not is_c:
            samples = samples.astype(np.complex64)
        if aud_fs and aud_fs > 0:
            fs = float(aud_fs)

    # 3. NumPy arrays
    elif ext == ".npy":
        arr = np.load(norm_path)
        if np.iscomplexobj(arr):
            samples = arr.astype(np.complex64).ravel()
        else:
            samples = arr.astype(np.float32).view(np.complex64).ravel()

    # 4. Raw binary formats (.32fc, .16tc, .32f, etc.)
    else:
        type_str = detect_type_from_ext(norm_path) or "complex64"
        file_size = os.path.getsize(norm_path)

        if type_str in ("int16", "cs16", "16tc"):
            item_size = 2
            read_bytes = file_size if not max_samples else min(file_size, max_samples * item_size * 2)
            valid_bytes = (read_bytes // (item_size * 2)) * (item_size * 2)
            with open(norm_path, "rb") as f:
                raw = np.frombuffer(f.read(valid_bytes), dtype=np.int16).astype(np.float32) / 32768.0
            samples = (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
        elif type_str in ("float32", "32f"):
            item_size = 4
            read_bytes = file_size if not max_samples else min(file_size, max_samples * item_size)
            valid_bytes = (read_bytes // item_size) * item_size
            with open(norm_path, "rb") as f:
                raw = np.frombuffer(f.read(valid_bytes), dtype=np.float32)
            samples = raw.astype(np.complex64)
        else:
            # Default to complex64 (.32fc)
            item_size = 8
            read_bytes = file_size if not max_samples else min(file_size, max_samples * item_size)
            valid_bytes = (read_bytes // item_size) * item_size
            with open(norm_path, "rb") as f:
                samples = np.frombuffer(f.read(valid_bytes), dtype=np.complex64)

    if max_samples and len(samples) > max_samples:
        samples = samples[:max_samples]

    return samples, fs, fc


def _compute_welch_psd(iq: np.ndarray, fs: float, nfft: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    """Compute Welch PSD with Hann window and true power spectral density scaling."""
    n = len(iq)
    nperseg = min(nfft, max(64, 1 << int(np.floor(np.log2(max(64, n))))))
    win = hann(nperseg, sym=False).astype(np.float64)
    win_scale = fs * max(float(np.sum(win ** 2)), 1e-30)

    step = max(1, nperseg // 2)
    acc = np.zeros(nperseg, dtype=np.float64)
    count = 0
    for s0 in range(0, n - nperseg + 1, step):
        seg = iq[s0 : s0 + nperseg] * win
        acc += np.abs(np.fft.fft(seg)) ** 2
        count += 1

    if count < 1:
        seg = np.pad(iq, (0, nperseg - n)) * win
        acc = np.abs(np.fft.fft(seg)) ** 2
        count = 1

    psd = np.fft.fftshift(acc / (count * win_scale))
    freqs = np.fft.fftshift(np.fft.fftfreq(nperseg, d=1.0 / fs))
    return freqs, psd


def _measure_obw_and_centroid(freqs: np.ndarray, psd: np.ndarray, obw_percent: float = 99.0) -> tuple[float, float, float, float]:
    """Calculate Occupied Bandwidth (Hz) and Spectral Centroid fc (Hz)."""
    clean_psd = np.maximum(psd, 0.0)
    total_power = float(np.sum(clean_psd))
    if total_power <= 1e-24:
        return 0.0, 0.0, float(freqs[0]), float(freqs[-1])

    cdf = np.cumsum(clean_psd) / total_power
    tail = 0.5 * (1.0 - np.clip(obw_percent / 100.0, 0.50, 0.999))
    idx_lo = int(np.clip(np.searchsorted(cdf, tail), 0, len(freqs) - 1))
    idx_hi = int(np.clip(np.searchsorted(cdf, 1.0 - tail), idx_lo, len(freqs) - 1))

    f_lo = float(freqs[idx_lo])
    f_hi = float(freqs[idx_hi])
    obw_hz = max(1.0, f_hi - f_lo)

    # Spectral centroid inside OBW
    slice_psd = clean_psd[idx_lo : idx_hi + 1]
    slice_freqs = freqs[idx_lo : idx_hi + 1]
    slice_sum = float(np.sum(slice_psd))
    if slice_sum > 1e-24:
        centroid_hz = float(np.sum(slice_freqs * slice_psd) / slice_sum)
    else:
        centroid_hz = 0.5 * (f_lo + f_hi)

    return obw_hz, centroid_hz, f_lo, f_hi


def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()

    # --- Parameter Validation ---
    s2_path = str(info.params.get("signal2_path", "")).strip()
    if not s2_path:
        result.error("Signal 2 File Path is required. Please specify a file in plugin parameters.")
        result.log("Error: Signal 2 File Path is empty.")
        return result

    if samples is None or len(samples) < 16:
        result.error("Active Signal 1 has too few samples (< 16) for comparison.")
        result.log("Error: Active workspace buffer is too short.")
        return result

    fs = float(info.sample_rate)
    fc = float(info.center_freq)
    if fs <= 0.0:
        result.error("Invalid sample rate (fs <= 0).")
        return result

    obw_percent = float(np.clip(info.params.get("obw_percent", 99.0), 50.0, 99.9))
    diff_delay = max(1, int(info.params.get("diff_delay", 1)))
    sub_mode = str(info.params.get("subtraction_mode", "Aligned (Lag & Phase Corrected)"))
    max_samples_cfg = int(info.params.get("max_samples", 1000000))
    max_samples = max_samples_cfg if max_samples_cfg > 0 else None
    draw_overlay = bool(info.params.get("draw_overlay", True))

    # --- Step 1: Load Signal 2 ---
    info.progress(10.0, "Loading Signal 2 file...")
    try:
        s2, s2_fs, s2_fc = _load_signal2(s2_path, default_fs=fs, default_fc=fc, max_samples=max_samples)
    except Exception as exc:
        result.error(f"Failed to load Signal 2: {exc}")
        result.log(f"Error loading '{s2_path}': {exc}")
        return result

    if len(s2) < 16:
        result.error("Signal 2 contains too few samples (< 16).")
        return result

    # Truncate s1 if needed
    s1 = samples[:max_samples] if max_samples and len(samples) > max_samples else samples
    n1 = len(s1)
    n2 = len(s2)

    if info.is_cancelled():
        return result

    # --- Step 2: Complex IQ Normalized Cross-Correlation ---
    info.progress(25.0, "Computing complex IQ normalized correlation...")
    # Cross-correlation via FFT convolution
    r_iq = signal.fftconvolve(s1, s2[::-1].conj(), mode="full")
    lags = np.arange(-(n2 - 1), n1)
    lags_s = lags / fs

    # Running energy normalization
    e2_total = float(np.sum(np.abs(s2) ** 2))
    e1_sliding = signal.fftconvolve(np.abs(s1) ** 2, np.ones(n2, dtype=np.float64), mode="full")
    denom_iq = np.sqrt(np.maximum(e1_sliding * e2_total, 1e-24))
    rho_iq = np.clip(np.abs(r_iq) / denom_iq, 0.0, 1.0)

    idx_pk_iq = int(np.argmax(rho_iq))
    val_pk_iq = float(rho_iq[idx_pk_iq])
    lag_samples_iq = int(lags[idx_pk_iq])
    lag_s_iq = float(lags_s[idx_pk_iq])
    phase_pk_iq = float(np.angle(r_iq[idx_pk_iq]))  # Carrier phase offset in radians

    if info.is_cancelled():
        return result

    # --- Step 3: Differential Cross-Correlation ---
    info.progress(45.0, "Computing differential correlation...")
    if n1 > diff_delay and n2 > diff_delay:
        d1 = s1[diff_delay:] * np.conj(s1[:-diff_delay])
        d2 = s2[diff_delay:] * np.conj(s2[:-diff_delay])

        r_diff = signal.fftconvolve(d1, d2[::-1].conj(), mode="full")
        lags_diff = np.arange(-(len(d2) - 1), len(d1))
        lags_diff_s = lags_diff / fs

        e2_diff = float(np.sum(np.abs(d2) ** 2))
        e1_diff_sliding = signal.fftconvolve(np.abs(d1) ** 2, np.ones(len(d2), dtype=np.float64), mode="full")
        denom_diff = np.sqrt(np.maximum(e1_diff_sliding * e2_diff, 1e-24))
        rho_diff = np.clip(np.abs(r_diff) / denom_diff, 0.0, 1.0)

        idx_pk_diff = int(np.argmax(rho_diff))
        val_pk_diff = float(rho_diff[idx_pk_diff])
        lag_samples_diff = int(lags_diff[idx_pk_diff])
        lag_s_diff = float(lags_diff_s[idx_pk_diff])
    else:
        lags_diff_s = lags_s
        rho_diff = np.zeros_like(lags_diff_s)
        val_pk_diff = 0.0
        lag_samples_diff = 0
        lag_s_diff = 0.0

    if info.is_cancelled():
        return result

    # --- Step 4: FM Demodulation Correlation ---
    info.progress(60.0, "Computing FM demodulation correlation...")
    f1_inst = compute_instantaneous_frequency(s1, fs, median_filter_len=5)
    f2_inst = compute_instantaneous_frequency(s2, fs, median_filter_len=5)

    f1_zero = f1_inst - float(np.mean(f1_inst))
    f2_zero = f2_inst - float(np.mean(f2_inst))

    r_fm = signal.fftconvolve(f1_zero, f2_zero[::-1], mode="full")
    lags_fm = np.arange(-(len(f2_zero) - 1), len(f1_zero))
    lags_fm_s = lags_fm / fs

    e2_fm = float(np.sum(f2_zero ** 2))
    e1_fm_sliding = signal.fftconvolve(f1_zero ** 2, np.ones(len(f2_zero), dtype=np.float64), mode="full")
    denom_fm = np.sqrt(np.maximum(e1_fm_sliding * e2_fm, 1e-24))
    rho_fm = np.clip(r_fm / denom_fm, -1.0, 1.0)

    idx_pk_fm = int(np.argmax(rho_fm))
    val_pk_fm = float(rho_fm[idx_pk_fm])
    lag_samples_fm = int(lags_fm[idx_pk_fm])
    lag_s_fm = float(lags_fm_s[idx_pk_fm])

    if info.is_cancelled():
        return result

    # --- Step 5: Subtraction Residuals (Magnitude & Phase in Radians) ---
    info.progress(75.0, "Computing subtraction residuals (abs & phase)...")
    t0_scope = float(info.t_start)

    if sub_mode.startswith("Aligned"):
        # Shift Signal 2 by peak lag and align phase/amplitude
        tau = lag_samples_iq
        if tau >= 0:
            s1_sub = s1[tau : tau + n2]
            s2_sub = s2[: len(s1_sub)]
        else:
            s1_sub = s1[: max(0, n2 + tau)]
            s2_sub = s2[-tau : -tau + len(s1_sub)]

        if len(s1_sub) > 0 and len(s2_sub) > 0:
            # Optimal gain scaling & carrier phase rotation
            scale_alpha = float(np.abs(np.sum(s1_sub * np.conj(s2_sub))) / max(float(np.sum(np.abs(s2_sub) ** 2)), 1e-24))
            s2_aligned = s2_sub * (scale_alpha * np.exp(1j * phase_pk_iq))
            err_sig = s1_sub - s2_aligned
            sub_mag = np.abs(err_sig)

            # Phase difference in radians wrapped to [-pi, pi]
            sub_phase = np.angle(s1_sub * np.conj(s2_aligned))
            t_sub = (np.arange(len(err_sig)) + max(0, tau)) / fs + t0_scope
        else:
            sub_mag = np.zeros(16, dtype=np.float64)
            sub_phase = np.zeros(16, dtype=np.float64)
            t_sub = np.arange(16) / fs + t0_scope
            s1_sub = s1[:16]
            err_sig = sub_mag
    else:
        # Raw direct point-by-point subtraction
        min_len = min(n1, n2)
        s1_sub = s1[:min_len]
        s2_sub = s2[:min_len]
        err_sig = s1_sub - s2_sub
        sub_mag = np.abs(err_sig)
        sub_phase = np.angle(s1_sub * np.conj(s2_sub))
        t_sub = np.arange(min_len) / fs + t0_scope

    p_ref = max(float(np.mean(np.abs(s1_sub) ** 2)), 1e-24)
    p_err = max(float(np.mean(sub_mag ** 2)), 1e-24)
    evm_rms_pct = float(np.sqrt(p_err / p_ref) * 100.0)
    evm_db = float(20.0 * np.log10(max(evm_rms_pct / 100.0, 1e-12)))
    ser_db = float(10.0 * np.log10(max(p_ref / p_err, 1e-12)))
    mean_phase_rad = float(np.mean(sub_phase))
    std_phase_rad = float(np.std(sub_phase))

    if info.is_cancelled():
        return result

    # --- Step 6: Spectral Comparison (OBW & Centroid) ---
    info.progress(85.0, "Measuring bandwidth and spectral centroids...")
    freqs_psd, psd1 = _compute_welch_psd(s1, fs)
    _, psd2 = _compute_welch_psd(s2, fs)

    obw1_hz, cfo1_hz, f1_lo, f1_hi = _measure_obw_and_centroid(freqs_psd, psd1, obw_percent)
    obw2_hz, cfo2_hz, f2_lo, f2_hi = _measure_obw_and_centroid(freqs_psd, psd2, obw_percent)

    delta_obw_hz = obw1_hz - obw2_hz
    delta_fc_hz = cfo1_hz - cfo2_hz

    psd1_db = 10.0 * np.log10(np.maximum(psd1, 1e-24))
    psd2_db = 10.0 * np.log10(np.maximum(psd2, 1e-24))

    # --- Step 7: Aligned FM Demodulation Tracks ---
    # Construct overlaid frequency trajectories
    if lag_samples_iq >= 0:
        f1_track = f1_inst[lag_samples_iq : lag_samples_iq + len(f2_inst)]
        f2_track = f2_inst[: len(f1_track)]
        t_track = (np.arange(len(f1_track)) + lag_samples_iq) / fs + t0_scope
    else:
        f1_track = f1_inst[: max(0, len(f2_inst) + lag_samples_iq)]
        f2_track = f2_inst[-lag_samples_iq : -lag_samples_iq + len(f1_track)]
        t_track = np.arange(len(f1_track)) / fs + t0_scope

    if len(f1_track) < 2:
        min_track_len = min(len(f1_inst), len(f2_inst))
        f1_track = f1_inst[:min_track_len]
        f2_track = f2_inst[:min_track_len]
        t_track = np.arange(min_track_len) / fs + t0_scope

    # --- Step 8: Build the 7 Sub-Plots in PluginPlotView ---
    info.progress(92.0, "Generating 7 interactive sub-plots...")
    result.set_plot_tab_title("Signal Comparison")

    # Plot 1: IQ Normalized Correlation
    pk_iq_lbl = f"Peak: {val_pk_iq:.4f} @ {lag_s_iq * 1e3:+.3f} ms (Δφ = {phase_pk_iq:+.3f} rad)"
    result.add_plot(
        title="IQ Correlation",
        y={pk_iq_lbl: rho_iq},
        x=lags_s,
        x_label="Lag Time",
        x_units="s",
        y_label="|Normalized Corr|",
        primary_mode="TIME",
    )

    # Plot 2: Differential Correlation
    pk_diff_lbl = f"Peak: {val_pk_diff:.4f} @ {lag_s_diff * 1e3:+.3f} ms (D = {diff_delay})"
    result.add_plot(
        title="Diff Correlation",
        y={pk_diff_lbl: rho_diff},
        x=lags_diff_s,
        x_label="Lag Time",
        x_units="s",
        y_label="|Diff Corr|",
        primary_mode="TIME",
    )

    # Plot 3: FM Demodulation Correlation
    pk_fm_lbl = f"Peak: {val_pk_fm:.4f} @ {lag_s_fm * 1e3:+.3f} ms"
    result.add_plot(
        title="FM Correlation",
        y={pk_fm_lbl: rho_fm},
        x=lags_fm_s,
        x_label="Lag Time",
        x_units="s",
        y_label="FM Demod Corr",
        primary_mode="TIME",
    )

    # Plot 4: Subtraction Residual Magnitude
    sub_mag_lbl = f"|s1 - s2| (EVM: {evm_rms_pct:.2f}% / {evm_db:.1f} dB | SER: {ser_db:.1f} dB)"
    result.add_plot(
        title="Subtraction Mag",
        y={sub_mag_lbl: sub_mag},
        x=t_sub,
        x_label="Time",
        x_units="s",
        y_label="Residual Magnitude",
        primary_mode="TIME",
    )

    # Plot 5: Subtraction Phase Difference (in Radians)
    sub_phase_lbl = f"Phase Error Δθ (rad) (Mean: {mean_phase_rad:+.3f}, Std: {std_phase_rad:.3f} rad)"
    result.add_plot(
        title="Subtraction Phase",
        y={sub_phase_lbl: sub_phase},
        x=t_sub,
        x_label="Time",
        x_units="s",
        y_label="Phase Difference (rad)",
        primary_mode="TIME",
    )

    # Plot 6: Spectral Density Comparison (PSD)
    psd_label_s1 = f"Signal 1 Ref (OBW: {obw1_hz / 1e3:.1f} kHz, fc: {cfo1_hz / 1e3:+.2f} kHz)"
    psd_label_s2 = f"Signal 2 Target (OBW: {obw2_hz / 1e3:.1f} kHz, fc: {cfo2_hz / 1e3:+.2f} kHz)"
    result.add_plot(
        title="PSD Comparison",
        y={psd_label_s1: psd1_db, psd_label_s2: psd2_db},
        x=freqs_psd,
        x_label="Frequency",
        x_units="Hz",
        y_label="PSD (dB/Hz)",
        primary_mode="FREQ",
    )

    # Plot 7: Aligned FM Demodulation Overlay
    result.add_plot(
        title="FM Demod Overlay",
        y={"Signal 1 Ref (kHz)": f1_track / 1e3, "Signal 2 Aligned (kHz)": f2_track / 1e3},
        x=t_track,
        x_label="Time",
        x_units="s",
        y_label="Frequency (kHz)",
        primary_mode="TIME",
    )

    # --- Step 9: Spectrogram Overlay Annotation ---
    if draw_overlay:
        t_match_start = t0_scope + max(0.0, lag_s_iq)
        t_match_end = t_match_start + (n2 / fs)
        f_span = max(obw1_hz, fs * 0.1)
        f_mid = fc + cfo1_hz

        tag_text = f"Match: IQ={val_pk_iq:.3f} Diff={val_pk_diff:.3f} FM={val_pk_fm:.3f}"
        hover_text = (
            f"Signal Comparison Match:\n"
            f"-----------------------------------------\n"
            f"• Peak IQ Corr:        {val_pk_iq:.4f} @ {lag_s_iq * 1e3:+.3f} ms\n"
            f"• Peak Diff Corr:      {val_pk_diff:.4f} @ {lag_s_diff * 1e3:+.3f} ms\n"
            f"• Peak FM Demod Corr:  {val_pk_fm:.4f} @ {lag_s_fm * 1e3:+.3f} ms\n"
            f"• Carrier Phase Diff:  {phase_pk_iq:+.3f} rad ({np.degrees(phase_pk_iq):+.1f}°)\n"
            f"• Signal 1 OBW:        {obw1_hz / 1e3:.2f} kHz (fc: {cfo1_hz / 1e3:+.2f} kHz)\n"
            f"• Signal 2 OBW:        {obw2_hz / 1e3:.2f} kHz (fc: {cfo2_hz / 1e3:+.2f} kHz)\n"
            f"• ΔOBW:                {delta_obw_hz / 1e3:+.2f} kHz | Δfc: {delta_fc_hz / 1e3:+.2f} kHz\n"
            f"• Residual EVM:        {evm_rms_pct:.2f}% ({evm_db:.1f} dB)\n"
            f"• Signal-to-Error SER: {ser_db:.1f} dB\n"
            f"• Subtraction Mode:    {sub_mode}"
        )

        meta = {
            "val_pk_iq": val_pk_iq,
            "lag_s_iq": lag_s_iq,
            "val_pk_diff": val_pk_diff,
            "val_pk_fm": val_pk_fm,
            "obw1_hz": obw1_hz,
            "obw2_hz": obw2_hz,
            "delta_fc_hz": delta_fc_hz,
            "evm_rms_pct": evm_rms_pct,
        }

        result.add(
            Rect(
                t_start=t_match_start,
                f_start=f_mid - f_span / 2.0,
                t_end=t_match_end,
                f_end=f_mid + f_span / 2.0,
                color="#00E676",
                alpha=0.20,
                border_width=2,
                border_color="#00E676",
                display_str=tag_text,
                hover_str=hover_text,
                locked=True,
                z_order=7,
                metadata=meta,
            )
        )

    # --- Step 10: Result Summary and Logging ---
    result.message = (
        f"Match: IQ={val_pk_iq:.3f}, Diff={val_pk_diff:.3f}, FM={val_pk_fm:.3f} "
        f"@ {lag_s_iq * 1e3:+.3f} ms | EVM: {evm_rms_pct:.1f}%"
    )

    report_lines = [
        "===========================================================",
        "                 SIGNAL COMPARISON REPORT                  ",
        "===========================================================",
        f"Signal 1 (Active Scope) : {n1:,} samples (fs = {fs / 1e6:g} MHz, fc = {fc / 1e6:g} MHz)",
        f"Signal 2 (External File): {n2:,} samples ({os.path.basename(s2_path)})",
        "-----------------------------------------------------------",
        "CORRELATION PEAKS & ALIGNMENT:",
        f"  • IQ Correlation Peak      : {val_pk_iq:.5f}  @  lag = {lag_s_iq * 1e3:+.4f} ms ({lag_samples_iq:+d} samples)",
        f"  • Differential Peak (D={diff_delay})   : {val_pk_diff:.5f}  @  lag = {lag_s_diff * 1e3:+.4f} ms",
        f"  • FM Demod Correlation Peak: {val_pk_fm:.5f}  @  lag = {lag_s_fm * 1e3:+.4f} ms",
        f"  • Carrier Phase at Peak    : {phase_pk_iq:+.4f} rad  ({np.degrees(phase_pk_iq):+.2f}°)",
        "-----------------------------------------------------------",
        "SPECTRAL METRICS (OBW & CENTROID):",
        f"  • Signal 1 Occupied BW     : {obw1_hz / 1e3:.2f} kHz  (Centroid: {cfo1_hz / 1e3:+.2f} kHz)",
        f"  • Signal 2 Occupied BW     : {obw2_hz / 1e3:.2f} kHz  (Centroid: {cfo2_hz / 1e3:+.2f} kHz)",
        f"  • Bandwidth Delta (ΔOBW)   : {delta_obw_hz / 1e3:+.2f} kHz",
        f"  • Carrier Offset Delta (Δfc): {delta_fc_hz / 1e3:+.2f} kHz",
        "-----------------------------------------------------------",
        "SUBTRACTION & RESIDUAL FIDELITY:",
        f"  • Mode                     : {sub_mode}",
        f"  • RMS EVM                  : {evm_rms_pct:.2f}%  ({evm_db:.2f} dB)",
        f"  • Signal-to-Error (SER)    : {ser_db:.2f} dB",
        f"  • Phase Error Std Dev      : {std_phase_rad:.4f} rad  ({np.degrees(std_phase_rad):.2f}°)",
        "===========================================================",
    ]
    for line in report_lines:
        result.log(line)

    info.progress(100.0, "Comparison complete.")
    return result

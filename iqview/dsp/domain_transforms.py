from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
from scipy.signal import hilbert, butter, sosfiltfilt, medfilt


@dataclass
class RegionStatsResult:
    """Structured result of 1D region statistics calculation (Time or Frequency domain)."""
    b1: float
    b2: float
    p_max: float
    p_min: float
    p_mean: float
    p_median: float
    p_10: float
    p_90: float
    p_diff: float
    total_power: Optional[float]
    idx_max: int
    idx_min: int
    x_max: float
    x_min: float
    unit_str: str
    diff_unit_str: str
    int_unit_str: str
    is_psd: bool
    is_db: bool


def compute_instantaneous_frequency(
    samples: np.ndarray,
    sample_rate: float,
    median_filter_len: int = 1,
) -> np.ndarray:
    """Compute instantaneous frequency (Hz) of a complex or real signal segment.

    For real-valued signals (negligible imaginary component), converts to an
    analytic signal via the Hilbert transform and applies a wide DC-blocking
    Butterworth HPF before phase differentiation.
    """
    if samples is None or len(samples) == 0:
        return np.array([], dtype=np.float64)

    is_real_signal = (
        not np.any(np.iscomplex(samples))
        or np.max(np.abs(samples.imag)) < 1e-9 * (np.max(np.abs(samples.real)) + 1e-30)
    )

    if is_real_signal:
        real_part = samples.real.astype(np.float64)
        try:
            analytic = hilbert(real_part)
            sos = butter(2, 0.005, btype='high', output='sos')
            analytic = sosfiltfilt(sos, analytic.real) + 1j * sosfiltfilt(sos, analytic.imag)
            samples = analytic
        except Exception:
            pass

    if len(samples) < 2:
        return np.zeros(len(samples), dtype=np.float64)

    dphi = np.diff(np.angle(samples))
    wrapped_dphi = (dphi + np.pi) % (2 * np.pi) - np.pi
    freq = wrapped_dphi / (2 * np.pi) * sample_rate

    filter_len = int(median_filter_len)
    if filter_len > 1:
        if filter_len % 2 == 0:
            filter_len += 1
        try:
            freq = medfilt(freq, kernel_size=filter_len)
        except Exception:
            pass

    if len(freq) > 0:
        freq = np.concatenate(([freq[0]], freq))
    return freq


def compute_time_domain_trace(
    samples: np.ndarray,
    mode_name: str,
    sample_rate: float = 1.0,
    median_filter_len: int = 7,
) -> Tuple[np.ndarray, str]:
    """Compute a 1D Time Domain trace and its Y-axis label from complex IQ samples."""
    if mode_name == "Real":
        return samples.real, "Real"
    elif mode_name == "Real [dB]":
        data = np.abs(samples.real).copy()
        data[data < 1e-12] = 1e-12
        return 20 * np.log10(data), "Real [dB]"
    elif mode_name == "Imaginary":
        return samples.imag, "Imaginary"
    elif mode_name == "Imaginary [dB]":
        data = np.abs(samples.imag).copy()
        data[data < 1e-12] = 1e-12
        return 20 * np.log10(data), "Imaginary [dB]"
    elif mode_name == "magnitude":
        return np.abs(samples), "magnitude"
    elif mode_name == "magnitude [dB]":
        data = np.abs(samples).copy()
        data[data < 1e-12] = 1e-12
        return 20 * np.log10(data), "magnitude [dB]"
    elif mode_name == "magnitude^2":
        return np.abs(samples) ** 2, "magnitude^2"
    elif mode_name == "magnitude^2 [dB]":
        data = (np.abs(samples) ** 2).copy()
        data[data < 1e-18] = 1e-18
        return 10 * np.log10(data), "magnitude^2 [dB]"
    elif mode_name == "instant frequency":
        freq = compute_instantaneous_frequency(samples, sample_rate, median_filter_len)
        return freq, "instant frequency"
    elif mode_name == "Phase":
        return np.angle(samples), "Phase"
    elif mode_name == "Unwrapped phase":
        return np.unwrap(np.angle(samples)), "Unwrapped phase"
    else:
        return np.abs(samples), "magnitude"


def apply_signal_operator(
    samples: np.ndarray,
    sample_rate: float,
    operator_name: str = "Normal",
    median_filter_len: int = 7,
) -> np.ndarray:
    """Apply a non-linear preprocessing operator to IQ samples for Frequency Domain analysis."""
    if samples is None or len(samples) == 0:
        return np.array([], dtype=np.complex64)

    if operator_name == "2nd Power":
        return samples ** 2
    elif operator_name == "4th Power":
        return samples ** 4
    elif operator_name == "Absolute Value":
        return np.abs(samples)
    elif operator_name in ("FM Demod", "2nd Power FM"):
        freq = compute_instantaneous_frequency(samples, sample_rate, median_filter_len)
        if operator_name == "2nd Power FM":
            return freq ** 2
        return freq
    elif operator_name == "Delay & Multiply":
        if len(samples) > 1:
            res = samples[1:] * np.conj(samples[:-1])
            return np.concatenate(([res[0]], res))
        return np.array([], dtype=np.complex64)
    return samples


def resolve_operator_center_freq(center_freq: float, operator_name: str = "Normal") -> float:
    """Return the effective center frequency after applying `operator_name`."""
    if operator_name in ("Absolute Value", "FM Demod", "2nd Power FM", "Delay & Multiply"):
        return 0.0
    elif operator_name == "2nd Power":
        return 2.0 * center_freq
    elif operator_name == "4th Power":
        return 4.0 * center_freq
    return center_freq


def compute_frequency_domain_fft(
    samples: np.ndarray,
    sample_rate: float,
    center_freq: float = 0.0,
    operator_name: str = "Normal",
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute normalized FFT and shifted frequency axis for a preprocessed sample segment."""
    n = len(samples)
    if n == 0:
        return np.array([], dtype=np.complex64), np.array([], dtype=np.float64)

    window = np.ones(n)
    fft_res = np.fft.fft(samples * window) / n
    fft_data = np.fft.fftshift(fft_res)

    cf = resolve_operator_center_freq(center_freq, operator_name)
    fft_freq_axis = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / sample_rate)) + cf
    return fft_data, fft_freq_axis


def compute_frequency_domain_trace(
    fft_data: np.ndarray,
    mode_name: str,
) -> Tuple[np.ndarray, str]:
    """Compute a 1D Frequency Domain trace and its Y-axis label from complex FFT data."""
    if mode_name == "magnitude":
        return np.abs(fft_data), "magnitude"
    elif mode_name in ("magnitude [dBFS]", "magnitude [dB]"):
        data = np.abs(fft_data).copy()
        data[data < 1e-15] = 1e-15
        return 20 * np.log10(data), "magnitude [dBFS]"
    elif mode_name == "magnitude^2":
        return np.abs(fft_data) ** 2, "magnitude^2"
    elif mode_name == "real":
        return fft_data.real, "real"
    elif mode_name in ("real [dBFS]", "real [dB]"):
        data = np.abs(fft_data.real).copy()
        data[data < 1e-15] = 1e-15
        return 20 * np.log10(data), "real [dBFS]"
    elif mode_name == "imag":
        return fft_data.imag, "imag"
    elif mode_name in ("imag [dBFS]", "imag [dB]"):
        data = np.abs(fft_data.imag).copy()
        data[data < 1e-15] = 1e-15
        return 20 * np.log10(data), "imag [dBFS]"
    elif mode_name == "phase":
        return np.angle(fft_data), "phase"
    elif mode_name == "unwrapped phase":
        return np.unwrap(np.angle(fft_data)), "unwrapped phase"
    else:
        return np.abs(fft_data), "magnitude"


def compute_region_statistics(
    x_axis: np.ndarray,
    y_data: np.ndarray,
    r_min: float,
    r_max: float,
    y_label_text: str,
    is_freq_domain: bool = False,
) -> Optional[RegionStatsResult]:
    """Compute Min, Max, Mean, Median, 10th/90th Percentiles, and Integrated Power over [r_min, r_max]."""
    if len(y_data) == 0 or len(x_axis) == 0:
        return None

    i_min = int(np.searchsorted(x_axis, r_min))
    i_max = int(np.searchsorted(x_axis, r_max))

    if is_freq_domain:
        i_min = max(0, i_min)
        i_max = min(len(x_axis), i_max)
    else:
        i_min = max(0, min(len(x_axis) - 1, i_min))
        i_max = max(0, min(len(x_axis), i_max))

    if i_min >= i_max:
        return None

    slice_data = y_data[i_min:i_max]
    if len(slice_data) == 0:
        return None

    p_max = float(np.max(slice_data))
    p_min = float(np.min(slice_data))
    p_median = float(np.median(slice_data))
    p_10_val, p_90_val = np.percentile(slice_data, [10, 90])
    p_10 = float(p_10_val)
    p_90 = float(p_90_val)
    p_diff = p_90 - p_10

    idx_max = int(i_min + np.argmax(slice_data))
    idx_min = int(i_min + np.argmin(slice_data))
    x_max = float(x_axis[idx_max])
    x_min = float(x_axis[idx_min])

    b1, b2 = sorted([float(r_min), float(r_max)])

    y_lower = y_label_text.lower()
    is_psd = ("psd" in y_lower or "db/hz" in y_lower)
    is_db = ("db" in y_lower)

    unit_str = ""
    if is_freq_domain and "dBFS" in y_label_text:
        unit_str = "dBFS"
    elif is_freq_domain and ("dB/Hz" in y_label_text or "dB / Hz" in y_label_text):
        unit_str = "dB/Hz"
    elif "[dB]" in y_label_text or "dB" in y_label_text:
        unit_str = "dB"
    elif "rad" in y_lower or "phase" in y_lower:
        unit_str = "rad"
    elif not is_freq_domain and "hz" in y_lower:
        unit_str = "Hz"
    elif "magnitude^2" in y_lower:
        unit_str = "Linear²"
    elif "magnitude" in y_lower or "real" in y_lower or "imag" in y_lower:
        unit_str = "Linear"

    int_unit_str = "dB" if (is_db or is_psd) else unit_str
    diff_unit_str = "dB" if (is_db or is_psd) else unit_str

    total_power: Optional[float] = None
    if is_freq_domain:
        if is_psd:
            lin_pow_slice = 10.0 ** (slice_data / 10.0)
            df = float(x_axis[1] - x_axis[0]) if len(x_axis) > 1 else 1.0
            total_p_lin = float(np.sum(lin_pow_slice)) * df
            p_mean_lin = float(np.mean(lin_pow_slice))
            p_mean = float(10.0 * np.log10(p_mean_lin + 1e-20))
            total_power = float(10.0 * np.log10(total_p_lin + 1e-20))
        elif is_db:
            lin_pow_slice = 10.0 ** (slice_data / 10.0)
            p_mean_lin = float(np.mean(lin_pow_slice))
            total_p_lin = float(np.sum(lin_pow_slice))
            p_mean = float(10.0 * np.log10(p_mean_lin + 1e-18))
            total_power = float(10.0 * np.log10(total_p_lin + 1e-15))
        else:
            if "magnitude^2" in y_lower:
                lin_pow_slice = slice_data
            else:
                lin_pow_slice = slice_data ** 2
            p_mean = float(np.mean(lin_pow_slice))
            total_power = float(np.sum(lin_pow_slice))
    else:
        if "[dB]" in y_label_text:
            factor = 10.0 if "magnitude^2" in y_lower else 20.0
            lin_data = 10.0 ** (slice_data / factor)
            lin_mean = float(np.mean(lin_data))
            p_mean = float(factor * np.log10(lin_mean + 1e-15))
        else:
            p_mean = float(np.mean(slice_data))

    return RegionStatsResult(
        b1=b1,
        b2=b2,
        p_max=p_max,
        p_min=p_min,
        p_mean=p_mean,
        p_median=p_median,
        p_10=p_10,
        p_90=p_90,
        p_diff=p_diff,
        total_power=total_power,
        idx_max=idx_max,
        idx_min=idx_min,
        x_max=x_max,
        x_min=x_min,
        unit_str=unit_str,
        diff_unit_str=diff_unit_str,
        int_unit_str=int_unit_str,
        is_psd=is_psd,
        is_db=is_db,
    )

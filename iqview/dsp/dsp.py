import numpy as np

def preprocess_chunk(data_array, window, fft_size):
    """
    De-interleaves I and Q to complex numbers and applies window.
    Vectorized version.
    """
    # De-interleave using slicing: [real, imag, real, imag, ...]
    complex_data = data_array[0::2] + 1j * data_array[1::2]
    
    # Apply window
    return complex_data * window

def postprocess_fft(fft_result, fft_size):
    """
    Applies fftshift and computes log magnitude in dB.
    Vectorized version.
    """
    # Use NumPy's vectorized fftshift and magnitude calculation
    shifted = np.fft.fftshift(fft_result)
    mag = np.abs(shifted)
    
    # Clip to epsilon to avoid log10(0)
    epsilon = np.float32(1e-10)
    mag = np.maximum(mag, epsilon)
    
# Convert to dB
    return 20.0 * np.log10(mag)

from scipy import signal

def design_filter(fs, f_min, f_max, filter_type="Elliptic", order=8, rp=0.1, rs=60.0, filter_taps=101, fir_window="hamming", **kwargs):
    """
    Designs a baseband filter representing the target band.
    Returns (filter_data, f_center, is_fir) where filter_data is either SOS or FIR taps.
    """
    if f_min >= f_max:
        return None, 0.0, False
        
    f_center = (f_min + f_max) / 2.0
    bandwidth = f_max - f_min
    
    nyquist = fs / 2.0
    cutoff = (bandwidth / 2.0) / nyquist
    cutoff = max(0.0001, min(cutoff, 0.9999))
    
    is_fir = (filter_type == "FIR (Windowed)")
    
    if filter_type == "Butterworth":
        filter_data = signal.butter(order, cutoff, btype='low', output='sos')
    elif filter_type == "Chebyshev I":
        filter_data = signal.cheby1(order, rp, cutoff, btype='low', output='sos')
    elif filter_type == "Chebyshev II":
        filter_data = signal.cheby2(order, rs, cutoff, btype='low', output='sos')
    elif filter_type == "Bessel":
        b_norm = kwargs.get('bessel_norm', 'phase')
        filter_data = signal.bessel(order, cutoff, btype='low', output='sos', norm=b_norm)
    elif is_fir:
        numtaps = filter_taps
        fir_win = fir_window.lower()
        # Design a REAL low-pass FIR filter
        filter_data = signal.firwin(numtaps, cutoff, window=fir_win)
    else: # Default: Elliptic
        filter_data = signal.ellip(order, rp, rs, cutoff, btype='low', output='sos')
        
    return filter_data, f_center, is_fir

def apply_filter(data, fs, f_min, f_max, filter_type="Elliptic", order=8, rp=0.1, rs=60.0, filter_taps=101, fir_window="hamming", mode='bpf', **kwargs):
    """
    Applies a sharp COMPLEX (Asymmetric) Band-Pass or Band-Stop filter to IQ data.
    Uses Shift-to-Baseband -> Zero-Phase Low-Pass Filter -> Shift-Back-Up approach.

    Zero-phase filtering (sosfiltfilt / filtfilt) is used so that:
      - There is no group delay: filtered output is perfectly time-aligned with input.
      - There is no phase distortion: every frequency component is preserved in phase.
    This makes BSF = (Original - BPF_result) exact: the target band is cleanly cancelled
    rather than leaving residuals from a misaligned or phase-distorted causal BPF.
    """
    filter_data, f_center, is_fir = design_filter(fs, f_min, f_max, filter_type, order, rp, rs, filter_taps, fir_window, **kwargs)
    if filter_data is None or len(data) == 0:
        return data
        
    # 1. Shift target band to 0 Hz
    t = np.arange(len(data)) / fs
    shift_vector = np.exp(-2j * np.pi * f_center * t)
    data_shifted = data * shift_vector
    
    # 2. Apply zero-phase Low-Pass Filter
    #    filtfilt / sosfiltfilt filter forward then backward: zero net phase, zero group delay.
    try:
        if is_fir:
            data_filtered = signal.filtfilt(filter_data, [1.0], data_shifted)
        else:
            data_filtered = signal.sosfiltfilt(filter_data, data_shifted)
    except ValueError:
        # Data segment shorter than ~3x filter length — fall back to causal (BSF will be approximate).
        if is_fir:
            data_filtered = signal.lfilter(filter_data, [1.0], data_shifted)
        else:
            data_filtered = signal.sosfilt(filter_data, data_shifted)

    # 3. Shift back to original frequency band
    #    Zero-phase filtering has no delay, so a simple conjugate reversal is exact.
    shift_back = np.conj(shift_vector)
    bpf_result = data_filtered * shift_back

    if mode == 'bsf':
        # BSF = Original - BPF  (exact: both signals have identical time alignment and phase)
        return data - bpf_result
    else:
        return bpf_result

def apply_bpf(data, fs, f_min, f_max, filter_type="Elliptic", order=8, rp=0.1, rs=60.0, filter_taps=101, fir_window="hamming", **kwargs):
    """Backwards compatibility wrapper for apply_filter(mode='bpf')."""
    return apply_filter(data, fs, f_min, f_max, filter_type, order, rp, rs, filter_taps, fir_window, mode='bpf', **kwargs)

def compute_psd(samples, fs=1.0, method='Welch', **kwargs):
    """
    Computes the Power Spectrum Density (PSD) of the samples.
    Methods supported: 'Periodogram' and 'Welch'.
    Returns (freqs, psd)
    NOTE: If fs=1.0 (default), returns normalized density.
    """
    if len(samples) == 0:
        return np.array([]), np.array([])

    if method == 'Welch':
        # Welch's method: Overlapping segments and averaging
        # Default nperseg to 1024 or len(samples) if shorter
        nperseg = kwargs.get('nperseg', 1024)
        nperseg = min(nperseg, len(samples))
        
        freqs, psd = signal.welch(
            samples, fs, 
            window=kwargs.get('window_type', 'hann'),
            nperseg=nperseg,
            nfft=kwargs.get('nfft', nperseg),
            scaling='density',
            return_onesided=False
        )
        # Shift to center DC
        freqs = np.fft.fftshift(freqs)
        psd = np.fft.fftshift(psd)
    else:
        # Periodogram method: Basic FFT-based estimate
        freqs, psd = signal.periodogram(
            samples, fs, 
            window=kwargs.get('window_type', 'boxcar'),
            nfft=kwargs.get('nfft', len(samples)),
            scaling='density',
            return_onesided=False
        )
        # Shift to center DC
        freqs = np.fft.fftshift(freqs)
        psd = np.fft.fftshift(psd)
        
    return freqs, psd

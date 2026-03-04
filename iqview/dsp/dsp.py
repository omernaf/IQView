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

def apply_bpf(data, fs, f_min, f_max, order=8, rp=0.1, rs=60):
    """
    Applies a sharp Band-Pass Elliptic filter to complex IQ data using Scipy.
    Elliptic filters provide the sharpest transition for a given order.
    Uses Second-Order Sections (SOS) for numerical stability.
    """
    if f_min >= f_max:
        return data
        
    # Band frequencies normalized to Nyquist
    nyquist = fs / 2.0
    low = f_min / nyquist
    high = f_max / nyquist
    
    # Ensure frequencies are within valid range (0, 1) and have a minimum width
    min_width = 0.001
    if (high - low) < min_width:
        center = (low + high) / 2
        low = max(0.001, center - min_width/2)
        high = min(0.999, center + min_width/2)
    else:
        low = max(0.001, min(low, 0.999))
        high = max(low + 0.0001, min(high, 0.999))
    
    # Design the filter (Elliptic for sharpest roll-off)
    # rp is passband ripple (dB), rs is stopband attenuation (dB)
    sos = signal.ellip(order, rp, rs, [low, high], btype='band', output='sos')
    
    # Apply filter
    return signal.sosfilt(sos, data)

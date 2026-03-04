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
    Applies a sharp COMPLEX (Asymmetric) Band-Pass filter to IQ data.
    Uses Shift-to-Baseband -> Low-Pass Filter -> Shift-Back-Up approach.
    This ensures that ONLY the selected freq range is kept even in complex signals.
    """
    if f_min >= f_max or len(data) == 0:
        return data
        
    f_center = (f_min + f_max) / 2.0
    bandwidth = f_max - f_min
    
    # 1. Shift target band to 0 Hz
    t = np.arange(len(data)) / fs
    shift_vector = np.exp(-2j * np.pi * f_center * t)
    data_shifted = data * shift_vector
    
    # 2. Design Low-Pass Filter at half-bandwidth
    # Normalized frequency (0 to 1.0, where 1.0 is Nyquist)
    nyquist = fs / 2.0
    cutoff = (bandwidth / 2.0) / nyquist
    cutoff = max(0.0001, min(cutoff, 0.9999))
    
    # Use Elliptic Low-Pass Filter for sharpest roll-off
    sos = signal.ellip(order, rp, rs, cutoff, btype='low', output='sos')
    
    # 3. Apply Filter
    data_filtered = signal.sosfilt(sos, data_shifted)
    
    # 4. Shift back to original frequency band
    return data_filtered * np.conj(shift_vector)

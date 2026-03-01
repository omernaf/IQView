import numpy as np
from numba import njit

@njit(fastmath=True)
def preprocess_chunk(data_array, window, fft_size):
    """
    De-interleaves I and Q to complex numbers and applies window.
    """
    complex_data = np.empty(fft_size, dtype=np.complex64)
    for i in range(fft_size):
        complex_data[i] = data_array[2*i] + 1j * data_array[2*i+1]
        
    for i in range(fft_size):
        complex_data[i] = complex_data[i] * window[i]
        
    return complex_data

@njit(fastmath=True)
def postprocess_fft(fft_result, fft_size):
    """
    Applies fftshift and computes log magnitude in dB.
    """
    db_mag = np.empty(fft_size, dtype=np.float32)
    half_n = fft_size // 2
    epsilon = np.float32(1e-10)
    
    for i in range(fft_size):
        if i < half_n:
            shifted_idx = i + half_n
        else:
            shifted_idx = i - half_n
            
        val = np.abs(fft_result[shifted_idx])
        if val < epsilon:
            val = epsilon
        db_mag[i] = 20.0 * np.log10(val)
        
    return db_mag

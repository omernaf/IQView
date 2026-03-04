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

def apply_bpf(data, fs, f_min, f_max, numtaps=65):
    """
    Applies a Band-Pass FIR filter to complex IQ data using NumPy.
    Normalized frequencies are relative to fs.
    """
    if f_min >= f_max:
        return data
        
    # Normalized frequencies (0 to 1.0, where 1.0 is fs)
    # But for sinc design, we need normalization relative to Nyquist (0.5 fs)
    nyquist = fs / 2.0
    w_low = f_min / nyquist
    w_high = f_max / nyquist
    
    # Design FIR impulse response using sinc functions
    n = np.arange(numtaps) - (numtaps - 1) / 2.0
    
    # Ideal BPF is the difference of two Low-Pass filters
    h = (w_high * np.sinc(w_high * n)) - (w_low * np.sinc(w_low * n))
    
    # Apply Hamming window to reduce sidelobes
    h *= np.hamming(numtaps)
    
    # Normalize gain at center frequency (approximate)
    h /= np.sum(h.real) if np.sum(h.real) != 0 else 1.0
    
    # Apply filter using convolution
    # mode='same' keeps the output length identical to input
    return np.convolve(data, h, mode='same')

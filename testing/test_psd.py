import sys
import os
import numpy as np

# Add iqview to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from iqview.dsp.dsp import compute_psd

def test_psd():
    fs = 1e6
    t = np.arange(10000) / fs
    # Signal with 100 kHz tone
    samples = np.exp(2j * np.pi * 100e3 * t) + 0.1 * (np.random.randn(10000) + 1j * np.random.randn(10000))
    
    print("Testing Welch method...")
    freqs_w, psd_w = compute_psd(samples, fs, method='Welch')
    print(f"Welch: freqs shape {freqs_w.shape}, psd shape {psd_w.shape}")
    
    peak_freq_w = freqs_w[np.argmax(psd_w)]
    print(f"Welch peak freq: {peak_freq_w / 1e3:.1f} kHz (Expected ~100 kHz)")
    
    print("\nTesting Periodogram method...")
    freqs_p, psd_p = compute_psd(samples, fs, method='Periodogram')
    print(f"Periodogram: freqs shape {freqs_p.shape}, psd shape {psd_p.shape}")
    
    peak_freq_p = freqs_p[np.argmax(psd_p)]
    print(f"Periodogram peak freq: {peak_freq_p / 1e3:.1f} kHz (Expected ~100 kHz)")
    
    # Simple sanity check
    assert abs(peak_freq_w - 100e3) < 2e3, "Welch peak freq error"
    assert abs(peak_freq_p - 100e3) < 1e2, "Periodogram peak freq error"
    print("\nPSD tests passed!")

if __name__ == "__main__":
    test_psd()

import numpy as np
import subprocess
import sys
import os

def generate_test_file(filename, sample_rate, duration):
    print(f"Generating test file '{filename}'...")
    num_samples = int(sample_rate * duration)
    t = np.arange(num_samples) / sample_rate
    
    # Signal 1: CW at +250 kHz offset
    freq1 = 250e3  
    sig1 = 1.0 * np.exp(1j * 2 * np.pi * freq1 * t)
    
    # Signal 2: CW at -150 kHz offset
    freq2 = -150e3 
    sig2 = 0.5 * np.exp(1j * 2 * np.pi * freq2 * t)
    
    # Signal 3: Linear chirp sweeping across the band
    chirp_freq = np.linspace(-400e3, 400e3, num_samples)
    sig_chirp = 0.3 * np.exp(1j * 2 * np.pi * chirp_freq * t)
    
    # Gaussian White Noise
    noise = (np.random.randn(num_samples) + 1j * np.random.randn(num_samples)) * 0.1
    
    # Combine signals and cast to exactly 32-bit floats for the complex numbers
    combined = sig1 + sig2 + sig_chirp + noise
    complex_data = combined.astype(np.complex64)
    
    # Write interleaved binary out to disk
    with open(filename, 'wb') as f:
        f.write(complex_data.tobytes())
        
    print(f"Created '{filename}' ({len(complex_data) * 8 / 1024 / 1024:.2f} MB).")

def main():
    filename = "temp1.32fc"
    sample_rate = 2e6  # 2 MHz
    duration = 10.0    # 10 seconds of simulated RF recording
    
    # generate_test_file(filename, sample_rate, duration)
    
    print("Launching Antigravity Spectrogram Viewer...")
    cmd = [
        sys.executable, "main.py",
        "-f", filename,
        "-t", "complex64", # Utilizing the explicit complex64 mapping we added previously
        "-r", str(sample_rate),
        "-c", "100000000", # Example: 100 MHz target center
        "-s", "1024"
    ]
    
    try:
        # Run the main Antigravity app natively
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    finally:
        # Optionally clean up testing artifacts
        # if os.path.exists(filename):
        #     os.remove(filename)
        pass

if __name__ == '__main__':
    main()

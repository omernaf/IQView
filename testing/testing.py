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
    # --- CONFIGURATION (Toggle features here for easy IDE 'Run') ---
    PROFILE_ENABLED      = False   # Set to True to always run with the summary profiler
    LINE_PROFILE_ENABLED = False  # Set to True to run the deep line-by-line profiler
    GENERATE_ENABLED     = False  # Set to True to force regenerate the test file
    # -------------------------------------------------------------

    import argparse
    parser = argparse.ArgumentParser(description="IQView Test Runner")
    parser.add_argument('--profile', action='store_true', default=PROFILE_ENABLED, help='Enable summary profiling')
    parser.add_argument('--line-profile', action='store_true', default=LINE_PROFILE_ENABLED, help='Run deep line-profiler')
    parser.add_argument('--generate', action='store_true', default=GENERATE_ENABLED, help='Force regenerate test file')
    args, unknown = parser.parse_known_args()

    filename = "samples/temp_10Msps_433MHz.32fc"
    # filename = "samples/mavic_air_2.16tc"
    # filename = "samples/long_sweep.32fc"
    sample_rate = 50e6  # 2 MHz
    duration = 10.0    # 10 seconds of simulated RF recording
    if args.line_profile:
        print("Running Deep Line-by-Line Profiler...")
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prof_script = os.path.join(root_dir, "profiler", "profile_script.py")
        subprocess.run([sys.executable, prof_script])
        return

    # if args.generate or not os.path.exists(filename):
    #     os.makedirs(os.path.dirname(filename), exist_ok=True)
    #     generate_test_file(filename, sample_rate, duration)
    
    print("Launching IQView Spectrogram Viewer...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_py = os.path.join(root_dir, "iqview", "main.py")
    cmd = [
        sys.executable, main_py,
        "-f", filename,
        "-r", str(sample_rate),
    ]
    
    if args.profile:
        cmd.append("--profile")
    
    try:
        # Run the main IQView app natively
        env = os.environ.copy()
        env["PYTHONPATH"] = root_dir + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    finally:
        # Optionally clean up testing artifacts
        # if os.path.exists(filename):
        #     os.remove(filename)
        pass

if __name__ == '__main__':
    main()

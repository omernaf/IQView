import numpy as np
import subprocess
import sys
import os

def main():
    # --- CONFIGURATION (Toggle features here for easy IDE 'Run') ---
    PROFILE_ENABLED      = False   # Set to True to always run with the summary profiler
    LINE_PROFILE_ENABLED = False  # Set to True to run the deep line-by-line profiler
    # -------------------------------------------------------------

    import argparse
    parser = argparse.ArgumentParser(description="IQView Test Runner")
    parser.add_argument('--profile', action='store_true', default=PROFILE_ENABLED, help='Enable summary profiling')
    parser.add_argument('--line-profile', action='store_true', default=LINE_PROFILE_ENABLED, help='Run deep line-profiler')
    args, unknown = parser.parse_known_args()

    # filename = "samples/temp_10Msps_433MHz.32fc"
    # filename = "samples/mavic_air_2.16tc"
    # filename = "samples/long_sweep.32fc"
    # filename = "samples/very_long_sweep.32fc"
    # filename = "samples/long_cw.32fc"
    filename = "samples/chirp_rate_3MHz.32fc";
    # filename = "samples/noise.32fc"
    # filename = "samples/saved/iq1.mat"
    # filename = "samples/file_example_WAV_5MG.wav"
    # filename = "samples/temp.32fc"
    filename = "samples/mavic_long_50MHz.32fc"
    # filename = "samples/burst_cw.32fc";
    sample_rate = 1e6  # 2 MHz
    duration = 10.0    # 10 seconds of simulated RF recording
    if args.line_profile:
        print("Running Deep Line-by-Line Profiler...")
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prof_script = os.path.join(root_dir, "profiler", "profile_script.py")
        subprocess.run([sys.executable, prof_script])
        return
    
    print("Launching IQView Spectrogram Viewer...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_py = os.path.join(root_dir, "iqview", "main.py")
    cmd = [
        sys.executable, main_py,
        "-f", filename,
        "-r", str(sample_rate),
        "--lazy",
        # "--name", "lazy"
        # "--full",
        # "--name", "full"
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

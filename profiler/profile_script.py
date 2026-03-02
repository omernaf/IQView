import os
import sys

# Disable Numba JIT so line_profiler can see inside the functions
os.environ['NUMBA_DISABLE_JIT'] = '1'

# Add parent directory to path to import dsp and utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from line_profiler import LineProfiler

import dsp
import utils

def profile_dsp():
    print("Profiling DSP functions (JIT disabled)...")
    fft_size = 1024
    window = np.hanning(fft_size).astype(np.float32)
    data_array = np.random.randn(fft_size * 2).astype(np.float32)
    
    lp = LineProfiler()
    lp.add_function(dsp.preprocess_chunk)
    lp.add_function(dsp.postprocess_fft)
    
    # Run a few iterations to get stable results
    lp_wrapper = lp(lambda: [dsp.preprocess_chunk(data_array, window, fft_size) for _ in range(100)])
    lp_wrapper()
    lp_wrapper = lp(lambda: [dsp.postprocess_fft(data_array[:fft_size], fft_size) for _ in range(100)])
    lp_wrapper()
    
    print("\n--- DSP Line Profiling Details ---")
    lp.print_stats()

def profile_file_reader():
    print("Profiling Optimized FileReaderThread.run (JIT disabled, BATCHED)...")
    filename = "temp1.32fc"
    if not os.path.exists(filename):
        filename = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp1.32fc")
        
    if not os.path.exists(filename):
        print(f"Error: {filename} not found. Please run testing.py first to generate it.")
        return
        
    reader = utils.FileReaderThread(filename, np.float32, 1024, 50.0)
    reader.num_rows = 5000 # More rows for batching
    
    lp = LineProfiler()
    lp.add_function(reader.run)
    
    lp_wrapper = lp(reader.run)
    lp_wrapper()
    
    print("\n--- Optimized FileReaderThread.run Line Profiling ---")
    lp.print_stats()

if __name__ == "__main__":
    profile_dsp()
    profile_file_reader()

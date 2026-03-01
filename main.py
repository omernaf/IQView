import sys
import argparse
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication
from ui import SpectrogramWindow

def parse_args():
    parser = argparse.ArgumentParser(description="Antigravity - High-performance Static RF Spectrogram Viewer")
    parser.add_argument('-f', '--file', required=True, help='Path to the binary IQ file')
    parser.add_argument('-t', '--type', required=True, type=str, help='Data type (e.g., np.int16, np.float32, np.complex64)')
    parser.add_argument('-r', '--rate', type=float, default=1e6, help='Sample rate in Hz')
    parser.add_argument('-c', '--fc', type=float, default=0.0, help='Center frequency in Hz')
    parser.add_argument('-s', '--fft', type=int, default=1024, help='FFT bin size')
    return parser.parse_args()

def main():
    args = parse_args()
    
    dtype_map = {
        'np.int8': np.int8, 'np.int16': np.int16, 'np.int32': np.int32,
        'np.float32': np.float32, 'np.float64': np.float64,
        'int8': np.int8, 'int16': np.int16, 'int32': np.int32,
        'float32': np.float32, 'float64': np.float64,
        'np.complex64': np.complex64, 'complex64': np.complex64
    }
    
    if args.type not in dtype_map:
        print(f"Error: Unsupported data type {args.type}.")
        sys.exit(1)
        
    dtype = dtype_map[args.type]
    
    if dtype == np.complex64:
        # Cast to float32 internally to de-interleave properly across numpy logic
        dtype = np.float32
        
    pg.setConfigOptions(useOpenGL=True, enableExperimental=True, imageAxisOrder='row-major')
    
    app = QApplication(sys.argv)
    window = SpectrogramWindow(args.file, dtype, args.rate, args.fc, args.fft)
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

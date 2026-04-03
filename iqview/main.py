# Support running as a script without installation
if __name__ == "__main__" and __package__ is None:
    import os, sys
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    __package__ = "iqview"

import sys
import argparse
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication
from iqview.ui import SpectrogramWindow
from iqview.utils.settings_manager import SettingsManager
from iqview.utils.helpers import DTYPE_MAP, detect_type_from_ext, detect_params_from_filename

# Fix taskbar grouping on Windows (must be done before creating QApplication)
if sys.platform == "win32":
    try:
        import ctypes
        myapp_id = "OmerNaf.IQView.0.1.4" # Unique AppUserModelID
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myapp_id)
    except Exception:
        pass

def load_mat_file(path):
    """
    Loads a .mat file containing Y, XDelta, and InputCenter fields.
    Returns:
        tuple: (data_bytes, type_str, fs, fc, is_complex)
    """
    import scipy.io
    import numpy as np
    
    try:
        data = scipy.io.loadmat(path)
        if 'Y' not in data or 'XDelta' not in data or 'InputCenter' not in data:
            print(f"Error: .mat file {path} is missing required fields (Y, XDelta, InputCenter).")
            return None
            
        y = data['Y'].flatten()
        # Handle potential 1x1 arrays from loadmat
        x_delta = float(data['XDelta'].item()) if hasattr(data['XDelta'], 'item') else float(data['XDelta'])
        input_center = float(data['InputCenter'].item()) if hasattr(data['InputCenter'], 'item') else float(data['InputCenter'])
        
        # Normalization: samples = Y * sqrt(10)
        # Ensure we are using complex64 (32-bit float real/imag)
        samples = (y * np.sqrt(10)).astype(np.complex64)
        
        dtype_str = 'complex64'
        is_complex = True
            
        fs = 1.0 / x_delta
        fc = input_center
        
        print(f"Successfully loaded .mat file: {len(samples):,} samples, Fs={fs/1e6:g} MHz, Fc={fc/1e6:g} MHz")
        return samples.tobytes(), dtype_str, fs, fc, is_complex
        
    except Exception as e:
        print(f"Error loading .mat file {path}: {e}")
        return None

def parse_args():
    sm = SettingsManager()
    parser = argparse.ArgumentParser(description="IQView - High-performance Static RF Spectrogram Viewer")
    
    # Positional path to load a file by dragging and dropping or double clicking
    parser.add_argument('path', nargs='?', default=None, help='Positional path to the binary IQ file')
    
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument('-f', '--file', default=None, help='Path to the binary IQ file (legacy/optional)')
    src.add_argument('--stdin', action='store_true', help='Read IQ data from stdin (binary pipe)')
    
    parser.add_argument('-t', '--type', default=None, type=str, help='Data type (int16, float32, float64, complex64, complex128)')
    parser.add_argument('-r', '--rate', type=float, default=float(sm.get("core/fs", 1e6)), help='Sample rate in Hz')
    parser.add_argument('-c', '--fc', type=float, default=float(sm.get("core/fc", 0.0)), help='Center frequency in Hz')
    parser.add_argument('-s', '--fft', type=int, default=int(sm.get("core/fft_size", 1024)), help='FFT bin size')
    parser.add_argument('--profile', action='store_true', help='Enable cProfile profiling')
    parser.add_argument('-n', '--name', type=str, default=None, help='Custom window name')

    # Desktop integration flags
    parser.add_argument('--install-desktop', action='store_true', help='Install Start Menu shortcut and File associations')
    parser.add_argument('--uninstall-desktop', action='store_true', help='Remove Start Menu shortcut and File associations')
    parser.add_argument('--install-mat', action='store_true', help='Associate .mat files with IQView')
    parser.add_argument('--uninstall-mat', action='store_true', help='Remove .mat file association')

    # Rendering mode (overrides the settings default for this session)
    render_group = parser.add_mutually_exclusive_group()
    render_group.add_argument(
        '--lazy', dest='lazy_rendering', action='store_const', const=True, default=None,
        help='Enable on-demand (lazy) rendering — only process the visible file slice'
    )
    render_group.add_argument(
        '--full', dest='lazy_rendering', action='store_const', const=False,
        help='Disable lazy rendering — process the entire file upfront (classic mode)'
    )

    return parser.parse_args()

def main():
    args = parse_args()
    
    if args.install_desktop:
        from iqview.utils.desktop import install_desktop_integration
        install_desktop_integration()
        sys.exit(0)
        
    if args.uninstall_desktop:
        from iqview.utils.desktop import uninstall_desktop_integration
        uninstall_desktop_integration()
        sys.exit(0)

    if args.install_mat:
        from iqview.utils.desktop import install_mat_integration
        install_mat_integration()
        sys.exit(0)

    if args.uninstall_mat:
        from iqview.utils.desktop import uninstall_mat_integration
        uninstall_mat_integration()
        sys.exit(0)
        
    sm = SettingsManager()
    
    # Priority for file path: 1. Positional argument 'path', 2. Flag '-f'/'--file'
    file_path = args.path or args.file
    
    # Priority: 1. User Input, 2. Auto-detection from filename, 3. App Settings
    type_str = args.type
    fs = args.rate
    fc = args.fc
    
    # We will check if rate or fc are still at their default values by reading the settings
    # because argparse doesn't natively tell us if default was used if we used `default=` parameter
    # A cleaner way is using `sys.argv`, but this is fine.
    
    # Identify if user explicitly set them 
    user_rate = '-r' in sys.argv or '--rate' in sys.argv
    user_fc = '-c' in sys.argv or '--fc' in sys.argv

    if file_path:
        if not type_str:
            auto_type = detect_type_from_ext(file_path)
            if auto_type:
                type_str = auto_type
                print(f"Auto-detected data type from file extension: {type_str}")
        
        # Detect fs and fc
        if not user_rate or not user_fc:
            params = detect_params_from_filename(file_path)
            
            if not user_rate and params.get('fs') is not None:
                fs = params['fs']
                print(f"Auto-detected sample rate from filename: {fs/1e6:g} MHz")
                
            if not user_fc and params.get('fc') is not None:
                fc = params['fc']
                print(f"Auto-detected center frequency from filename: {fc/1e6:g} MHz")
                
    if not type_str:
        type_str = sm.get("core/type", "complex64")

    if type_str not in DTYPE_MAP:
        print(f"Error: Unsupported data type {type_str}.")
        sys.exit(1)
        
    dtype = DTYPE_MAP[type_str]
    is_complex = dtype in [np.complex64, np.complex128, np.int16]
    
    if dtype == np.complex64:
        # Cast to float32 internally to de-interleave properly across numpy logic
        dtype = np.float32
    elif dtype == np.complex128:
        # Cast to float64 internally to de-interleave properly
        dtype = np.float64

    # Resolve the data source: file path (str), in-memory bytes from stdin, or None (open empty)
    if args.stdin:
        print("Reading IQ data from stdin...", flush=True)
        data_source = sys.stdin.buffer.read()
        print(f"Read {len(data_source):,} bytes from stdin.", flush=True)
    elif file_path and file_path.lower().endswith('.mat'):
        mat_data = load_mat_file(file_path)
        if mat_data:
            data_source, type_str, fs, fc, is_complex = mat_data
        else:
            sys.exit(1)
    else:
        data_source = file_path  # may be None if no source given

    pg.setConfigOptions(useOpenGL=True, enableExperimental=True, imageAxisOrder='row-major')
    
    # Resolve rendering mode: CLI flag > settings default.
    # NOTE: do NOT write this back to QSettings — that would affect every other
    # open window since QSettings is shared process-wide. Instead we pass the
    # resolved value directly to SpectrogramWindow as an in-memory override.
    lazy_override = None   # None = use whatever QSettings says
    if args.lazy_rendering is not None:
        lazy_override = args.lazy_rendering
        mode_label = "lazy" if args.lazy_rendering else "full-file"
        print(f"Rendering mode forced by CLI: {mode_label}")
    
    app = QApplication(sys.argv)
    # Fix taskbar/dock grouping on Linux
    app.setDesktopFileName("iqview")
    
    window = SpectrogramWindow(data_source, dtype, fs, fc, args.fft, args.profile,
                               is_complex=is_complex, window_name=args.name,
                               lazy_rendering=lazy_override)
    window.show()
    
    if args.profile:
        import cProfile
        import pstats
        import io
        import os
        
        # Ensure profiler directory exists
        os.makedirs("profiler", exist_ok=True)
        
        print("\n" + "="*40)
        print("PROFILING ENABLED")
        print("="*40 + "\n")
        
        pr = cProfile.Profile()
        pr.enable()
        
        exit_code = app.exec()
        
        pr.disable()
        
        # 1. Print to console (Top 30)
        sortby = 'cumulative'
        ps = pstats.Stats(pr).sort_stats(sortby)
        ps.print_stats(30)
        
        # 2. Save human-readable summary to disk
        summary_path = os.path.join("profiler", "profile_summary.txt")
        with open(summary_path, "w") as f:
            f.write("IQView Execution Profile Summary\n")
            f.write("="*40 + "\n\n")
            ps_file = pstats.Stats(pr, stream=f).sort_stats(sortby)
            ps_file.print_stats() # Save ALL stats to file
            
        # 3. Save binary data to disk
        prof_path = os.path.join("profiler", "profile_results.prof")
        pr.dump_stats(prof_path)
        
        print(f"\nDetailed profile (binary) saved to: {prof_path}")
        print(f"Human-readable summary saved to:    {summary_path}\n")
        
        sys.exit(exit_code)
    else:
        sys.exit(app.exec())

if __name__ == '__main__':
    main()

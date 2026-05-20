import os
import numpy as np

DTYPE_MAP = {
    'int16': np.int16, 
    'float32': np.float32, 
    'float64': np.float64,
    'complex64': np.complex64, 
    'complex128': np.complex128,
    # np. prefixed aliases
    'np.int16': np.int16, 
    'np.float32': np.float32, 
    'np.float64': np.float64,
    'np.complex64': np.complex64, 
    'np.complex128': np.complex128
}

# Audio file extensions supported natively (via scipy.io.wavfile, no extra deps)
AUDIO_EXTENSIONS = {'.wav'}

def detect_type_from_ext(path):
    """
    Detects the data type based on the file extension.
    Returns the string key (e.g. 'float32'), 'audio' for audio files,
    or None if unknown.
    """
    if not path:
        return None
        
    ext = os.path.splitext(path)[1].lower()

    # Audio files are handled by a dedicated loader, not raw binary
    if ext in AUDIO_EXTENSIONS:
        return 'audio'
    
    # Load mapping from settings manager dynamically
    from iqview.utils.settings_manager import SettingsManager
    sm = SettingsManager()
    mapping = sm.get("core/extension_mapping", {})
    
    return mapping.get(ext)


def detect_params_from_filename(filename):
    """
    Auto-detect sample rate (fs) and center frequency (fc) from a filename.
    Returns:
        dict: {'fs': float or None, 'fc': float or None}
    """
    import re
    if not filename:
        return {'fs': None, 'fc': None}
        
    # Helper to parse multipliers
    def parse_value(val_str, multiplier_str):
        val = float(val_str)
        mult = multiplier_str.upper() if multiplier_str else ""
        if 'G' in mult: val *= 1e9
        elif 'M' in mult: val *= 1e6
        elif 'K' in mult: val *= 1e3
        return val

    # Common separators between the keyword and the number
    sep = r'[-_=]*'
    
    # Start and end boundaries to replace \b
    # Numbers should not be preceded by other letters/digits/dots (so _10Msps works, because _ is not in the set)
    sb = r'(?<![a-zA-Z0-9.])'
    # Units should not be immediately followed by another letter (e.g. hzds)
    eb = r'(?![a-zA-Z])'
    
    # Matches: "fs_10M", "rate=500k", "sr-2.4G", "samp2m"
    # We allow the unit (sps/hz) to be optional, but we want to capture the multiplier
    fs_pattern = sb + r'(?:fs|sr|rate|samp)' + sep + r'(\d+(?:\.\d+)?)\s*([kKmMgG]?)(?:sps|hz|Hz)?' + eb
    
    # Matches: "fc_915M", "freq=433k", "center-2.4G"
    fc_pattern = sb + r'(?:fc|freq|center)' + sep + r'(\d+(?:\.\d+)?)\s*([kKmMgG]?)(?:sps|hz|Hz)?' + eb
    
    # Matches: "10Msps", "500ksps"
    sps_pattern = sb + r'(\d+(?:\.\d+)?)\s*([kKmMgG]?)sps' + eb
    
    # Matches: "915MHz", "2.4GHz"
    hz_pattern = sb + r'(\d+(?:\.\d+)?)\s*([kKmMgG]?)hz' + eb
    
    fs = None
    fc = None
    
    basename = os.path.basename(filename)
    
    # Try to find explicit fs
    match_fs = re.search(fs_pattern, basename, re.IGNORECASE)
    if match_fs:
        fs = parse_value(match_fs.group(1), match_fs.group(2))
    else:
        # Try explicit sps units
        match_sps = re.search(sps_pattern, basename, re.IGNORECASE)
        if match_sps:
            fs = parse_value(match_sps.group(1), match_sps.group(2))
            
    # Try to find explicit fc
    match_fc = re.search(fc_pattern, basename, re.IGNORECASE)
    if match_fc:
        fc = parse_value(match_fc.group(1), match_fc.group(2))
    
    # If fc is still not found, try to find a standalone hz value
    # But only if it wasn't already matched as fs (e.g. rate-10MHz)
    if fc is None:
        hz_matches = list(re.finditer(hz_pattern, basename, re.IGNORECASE))
        
        if len(hz_matches) > 0:
            # If we found exactly one Hz value and we DON'T have a sample rate yet, 
            # assume it's the sample rate based on user request.
            if len(hz_matches) == 1 and fs is None:
                fs = parse_value(hz_matches[0].group(1), hz_matches[0].group(2))
            else:
                # If we have fs already, we'll take the first one that doesn't overlap with our fs match.
                taken_hz = False
                for m in hz_matches:
                    val = parse_value(m.group(1), m.group(2))
                    if fs is not None and val == fs and (match_fs and m.start() >= match_fs.start() and m.end() <= match_fs.end()):
                        continue
                    
                    if not taken_hz:
                        fc = val
                        taken_hz = True

    return {'fs': fs, 'fc': fc}


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


def load_audio_file(path):
    """
    Loads a .wav audio file using scipy.io.wavfile (no extra dependencies).
    Multi-channel audio is averaged to a single mono channel.
    Integer samples are normalized to float32 in [-1.0, 1.0].

    Returns:
        tuple: (data_bytes, type_str, fs, fc, is_complex)
               data_bytes — raw bytes of float32 samples
               type_str   — always 'float32'
               fs         — sample rate in Hz (from the file header)
               fc         — always 0.0 (no carrier info in audio files)
               is_complex — always False
        None on error.
    """
    try:
        from scipy.io import wavfile
        fs, data = wavfile.read(path)

        # Convert to float32, normalizing integers to [-1.0, 1.0]
        if data.dtype == np.int16:
            samples = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            samples = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            # uint8 WAV is offset-binary: 0–255, centre at 128
            samples = (data.astype(np.float32) - 128.0) / 128.0
        else:
            # float32 or float64 already — just ensure float32
            samples = data.astype(np.float32)

        # Average multi-channel (stereo, etc.) to mono
        if samples.ndim > 1:
            samples = samples.mean(axis=1).astype(np.float32)

        fc = 0.0
        is_complex = False
        dtype_str = 'float32'

        n_ch = data.shape[1] if data.ndim > 1 else 1
        print(f"Successfully loaded audio file: {len(samples):,} samples, "
              f"Fs={fs/1e3:g} kHz, {n_ch} channel(s) averaged to mono")
        return samples.tobytes(), dtype_str, float(fs), fc, is_complex

    except Exception as e:
        print(f"Error loading audio file {path}: {e}")
        return None

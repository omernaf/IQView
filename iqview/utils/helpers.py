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

def detect_type_from_ext(path):
    """
    Detects the data type based on the file extension.
    Returns the string key (e.g. 'float32') or None if unknown.
    """
    if not path:
        return None
        
    ext = os.path.splitext(path)[1].lower()
    
    # Mapping based on user request
    mapping = {
        '.32f': 'float32',
        '.64f': 'float64',
        '.16tc': 'int16',
        '.16sc': 'int16',
        '.64fc': 'complex128',
        '.32fc': 'complex64',
        '.bin': 'complex64',
        '.iq': 'complex64'
    }
    
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

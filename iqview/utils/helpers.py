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

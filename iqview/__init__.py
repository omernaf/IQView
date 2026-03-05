# IQView package
import numpy as np

def view(data, fs, fc=0.0, fft_size=1024, dtype='complex64'):
    """
    Open the IQView Spectrogram Viewer directly from Python with a numpy array.

    Parameters
    ----------
    data     : array-like — complex IQ samples (any dtype; converted to complex64 internally)
    fs       : float      — sample rate in Hz
    fc       : float      — center frequency in Hz (default 0)
    fft_size : int        — FFT size / number of frequency bins (default 1024)
    dtype    : str        — internal sample type passed to IQView (default 'complex64')

    Example
    -------
    import numpy as np
    import iqview

    fs = 2e6
    t  = np.arange(int(fs * 0.5)) / fs
    x  = np.exp(2j * np.pi * 250e3 * t)   # CW tone at +250 kHz
    iqview.view(x, fs)
    """
    import sys
    import pyqtgraph as pg
    from PyQt6.QtWidgets import QApplication

    # Convert to interleaved float32 bytes (the native IQView wire format)
    samples = np.asarray(data, dtype=np.complex64).ravel()
    interleaved = np.empty(len(samples) * 2, dtype=np.float32)
    interleaved[0::2] = samples.real
    interleaved[1::2] = samples.imag
    raw_bytes = interleaved.tobytes()

    from iqview.ui import SpectrogramWindow
    pg.setConfigOptions(useOpenGL=True, enableExperimental=True, imageAxisOrder='row-major')
    app = QApplication.instance() or QApplication(sys.argv)
    window = SpectrogramWindow(raw_bytes, np.float32, fs, fc, fft_size)
    window.show()
    sys.exit(app.exec())

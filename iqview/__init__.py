# IQView package
import numpy as np
from iqview.plugins.plugin_result import PluginResult
from iqview.plugins.context import PluginContext, PluginParams
from iqview.plugins.chain import PluginChain
from iqview.plugins.format_utils import format_hover_bits

__version__ = "0.7.0"
__all__ = [
    "view",
    "PluginResult",
    "PluginContext",
    "PluginParams",
    "PluginChain",
    "format_hover_bits",
    "__version__",
]


def view(
    source=None,
    fs: float = None,   # effective default: 1e6
    fc: float = None,   # effective default: 0.0
    fft_size: int = 1024,
    dtype: str = "complex64",
    name: str = None,
    lazy: bool = None,
    norm_db: float = 0.0,
):
    """
    Open the IQView Spectrogram Viewer directly from Python.

    This is the primary entry point for plugin debugging: open a file (or pass
    a numpy array), set a breakpoint in your plugin, load it via the Plugins
    menu and step through the code in your IDE.

    Parameters
    ----------
    source : str | np.ndarray | None
        What to display.  Three modes:

        * ``str``           — path to a binary IQ file on disk.  IQView will
                              auto-detect the data type from the file extension
                              (e.g. ``.cf32``, ``.sc16``) and the sample rate /
                              center frequency from the filename when possible.
        * ``np.ndarray``    — complex IQ samples as a NumPy array (any dtype;
                              converted to ``complex64`` internally).
        * ``None`` (default)— open IQView with an empty canvas (no file loaded).

    fs : float, optional
        Sample rate in Hz.  Default ``1e6`` (1 MHz) when not auto-detected
        from the filename.  Pass ``None`` (or omit) to allow filename
        auto-detection; pass an explicit value to always override it.

    fc : float, optional
        Center frequency in Hz.  Default ``0.0`` when not auto-detected
        from the filename.  Pass ``None`` (or omit) to allow filename
        auto-detection; pass an explicit value to always override it.

    fft_size : int, optional
        Number of FFT bins (spectrogram frequency resolution).  Default ``1024``.

    dtype : str, optional
        Data type of the samples when *source* is a file path and the type
        cannot be auto-detected from the extension.
        Accepted values: ``'complex64'`` (default), ``'complex128'``,
        ``'float32'``, ``'float64'``, ``'int16'``.
        Has no effect when *source* is a NumPy array (the array's own dtype is
        used) or ``None``.

    name : str, optional
        Custom window title shown in the title bar.  Defaults to the file path
        or ``"<array>"`` when *source* is a NumPy array.

    lazy : bool | None, optional
        Rendering mode override.

        * ``True``  — lazy/on-demand rendering (only process the visible slice).
        * ``False`` — full-file rendering (process entire file up-front).
        * ``None``  — use whatever is configured in IQView Settings (default).

    Examples
    --------
    **Open a file by path:**

    >>> import iqview
    >>> iqview.view("path/to/recording.cf32", fft_size=2048)

    **Pass a NumPy array (great for synthetic signals):**

    >>> import numpy as np, iqview
    >>> fs = 2e6
    >>> t  = np.arange(int(fs * 0.5)) / fs
    >>> x  = np.exp(2j * np.pi * 250e3 * t)   # CW tone at +250 kHz
    >>> iqview.view(x, fs=fs, fc=2.4e9, name="Test Signal")

    **Open empty (no file):**

    >>> iqview.view()
    """
    import sys
    import pyqtgraph as pg
    from PyQt6.QtWidgets import QApplication
    from iqview.ui import SpectrogramWindow
    from iqview.utils.helpers import DTYPE_MAP, detect_type_from_ext, detect_params_from_filename

    pg.setConfigOptions(useOpenGL=True, enableExperimental=True, imageAxisOrder="row-major")
    app = QApplication.instance() or QApplication(sys.argv)

    # ------------------------------------------------------------------ #
    # Resolve data_source, data_type, is_complex from the `source` arg    #
    # ------------------------------------------------------------------ #
    if source is None:
        # Empty launch
        data_source = None
        data_type   = np.float32
        is_complex  = True
        file_path   = None
        window_name = name

    elif isinstance(source, str):
        # File path — mirror the auto-detection logic from main.py
        import os
        from iqview.utils.helpers import (
            AUDIO_EXTENSIONS, load_mat_file, load_audio_file, load_r3f_file,
            MatFileFormatError, R3FFileFormatError
        )

        file_path = os.path.normpath(os.path.abspath(source))
        startup_error = None
        type_str = None

        if os.path.splitext(file_path)[1].lower() in AUDIO_EXTENSIONS or dtype in ('aud', 'audio', 'caud', 'caudio'):
            is_caudio = dtype in ('caud', 'caudio')
            data_bytes, err_or_type, loaded_fs, loaded_fc, is_complex = load_audio_file(
                file_path, complex_iq=is_caudio
            )
            if data_bytes is not None:
                data_source = data_bytes
                data_type = np.float32
                type_str = err_or_type  # 'float32' on success
                fs = fs if fs is not None else loaded_fs
                fc = fc if fc is not None else loaded_fc
                window_name = name
            else:
                startup_error = {
                    "title": "Unsupported Audio Format",
                    "message": f"<b>Could not load audio file:</b><br>{os.path.basename(file_path)}<br><br>"
                               f"<pre style='font-family:Consolas;'>{err_or_type}</pre><br>"
                               f"Supported formats: WAV, FLAC, OGG, AIFF, AU, W64, CAF, RF64, SD2"
                }
                data_source = None
                data_type = np.float32
                is_complex = True
                file_path = None
                window_name = name
        elif file_path.lower().endswith('.mat'):
            try:
                mat_data = load_mat_file(file_path)
            except MatFileFormatError as exc:
                startup_error = {
                    "title": "Unsupported .mat File Format",
                    "message": f"<b>{exc}</b><br><br><pre style='font-family:Consolas;'>{exc.detail}</pre>"
                }
                data_source = None
                data_type = np.float32
                is_complex = True
                file_path = None
                window_name = name
            else:
                if mat_data:
                    data_source, loaded_type_str, loaded_fs, loaded_fc, is_complex = mat_data
                    type_str = loaded_type_str
                    fs = fs if fs is not None else loaded_fs
                    fc = fc if fc is not None else loaded_fc
                    dtype_resolved = DTYPE_MAP.get(loaded_type_str, np.complex64)
                    data_type = np.float32 if dtype_resolved == np.complex64 else (np.float64 if dtype_resolved == np.complex128 else dtype_resolved)
                    window_name = name
                else:
                    data_source = None
                    data_type = np.float32
                    is_complex = True
                    file_path = None
                    window_name = name
        elif file_path.lower().endswith('.r3f'):
            try:
                r3f_data = load_r3f_file(file_path)
            except R3FFileFormatError as exc:
                startup_error = {
                    "title": "Unsupported .r3f File Format",
                    "message": f"<b>{exc}</b><br><br><pre style='font-family:Consolas;'>{exc.detail}</pre>"
                }
                data_source = None
                data_type = np.float32
                is_complex = True
                file_path = None
                window_name = name
            else:
                if r3f_data:
                    data_source, loaded_type_str, loaded_fs, loaded_fc, is_complex = r3f_data
                    type_str = loaded_type_str
                    fs = fs if fs is not None else loaded_fs
                    fc = fc if fc is not None else loaded_fc
                    data_type = np.float32
                    window_name = name
                else:
                    data_source = None
                    data_type = np.float32
                    is_complex = True
                    file_path = None
                    window_name = name
        else:
            # Auto-detect dtype from extension
            auto_type = detect_type_from_ext(file_path)
            resolved_type = auto_type or dtype
            type_str = resolved_type

            # Auto-detect fs / fc from filename only when the caller did not
            # explicitly supply a value (fs/fc are None when left at default).
            params = detect_params_from_filename(file_path)
            resolved_fs = fs if fs is not None else params.get("fs", 1e6)
            resolved_fc = fc if fc is not None else params.get("fc", 0.0)
            fs = resolved_fs
            fc = resolved_fc

            if resolved_type not in DTYPE_MAP:
                raise ValueError(
                    f"Unsupported dtype {resolved_type!r}. "
                    f"Valid options: {list(DTYPE_MAP)}"
                )

            raw_dtype  = DTYPE_MAP[resolved_type]
            is_complex = raw_dtype in (np.complex64, np.complex128, np.int16)

            # De-alias complex types to their float counterparts (same as main.py)
            if raw_dtype == np.complex64:
                data_type = np.float32
            elif raw_dtype == np.complex128:
                data_type = np.float64
            else:
                data_type = raw_dtype

            data_source = file_path
            window_name = name  # None → SpectrogramWindow uses the file path

    else:
        # NumPy array (or anything array-like)
        arr = np.asarray(source, dtype=np.complex64).ravel()
        interleaved       = np.empty(len(arr) * 2, dtype=np.float32)
        interleaved[0::2] = arr.real
        interleaved[1::2] = arr.imag
        data_source = interleaved.tobytes()
        data_type   = np.float32
        is_complex  = True
        file_path   = None
        type_str    = None
        window_name = name or "<array>"
        startup_error = None

    # ------------------------------------------------------------------ #
    # Launch                                                               #
    # ------------------------------------------------------------------ #
    # Apply final defaults for paths that didn't go through filename detection
    if fs is None:
        fs = 1e6
    if fc is None:
        fc = 0.0

    window = SpectrogramWindow(
        data_source,
        data_type,
        fs,
        fc,
        fft_size,
        is_complex=is_complex,
        window_name=window_name,
        lazy_rendering=lazy,
        file_path=file_path,
        type_str=type_str,
        norm_db=norm_db,
    )
    window.show()

    if startup_error:
        from PyQt6.QtWidgets import QMessageBox
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: QMessageBox.critical(
            window,
            startup_error["title"],
            startup_error["message"]
        ))

    sys.exit(app.exec())


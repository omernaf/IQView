# IQView

**High-Performance GPU-Accelerated RF Spectrogram & Signal Analysis Viewer**

IQView is an advanced, high-performance GUI application designed for deep inspection and analysis of In-phase and Quadrature (IQ) signals. Built with Python, PyQt6, pyqtgraph, and PyOpenGL, it delivers a fluid, hardware-accelerated experience for exploring multi-gigabyte RF recordings across time, frequency, and modulation domains.

---

## 🚀 Key Features

- **Lazy Rendering Engine**: Seamlessly inspect ultra-large recordings (multi-gigabyte or hour+ captures) without memory exhaustion. Computes FFTs on-demand specifically for the visible viewport slice.
- **Multi-Row Spectrogram View**: Fold ultra-long captures into stacked periodic time rows (ideal for radar PRF, burst telemetry, and framing analysis) with synchronous zooming and cursor inspection across all rows.
- **Plugin System 2.0 & Plugin Studio**:
  - **Visual Editor**: Create, tune, and chain complex DSP pipelines using `PluginChain`.
  - **Custom Analysis Tabs**: Direct rendering of 1D/2D views via `PluginPlotView` within the main window or detached popouts.
  - **Quick Run & Favorites**: Instant one-click toolbar execution and MRU history for frequently used analysis plugins.
  - **Built-in Plugins**: Includes Time-Frequency Polygon Mask Filter, Gabor Ellipse Chirp Analyzer, Cross-Correlation Signal Comparator, LoRa Demodulator (automatic OBW and $SF$ detection), and GNSS PRN Detector.
- **Calibrated RF Power Normalization**: Hardware gain calibration via `norm_db` (CLI `--norm`) scaling input samples ($10^{-\text{norm\_db} / 20}$) and decibel normalization with window power compensation ($10 \log_{10}(f_s \sum w^2[n])$).
- **Maximum Overlap Mode (`MAX`)**: Seamless 1-sample step STFT mode for maximum temporal resolution and ultra-fine transient inspection.
- **In-App Application Log Viewer**: Real-time diagnostic viewer (`L` shortcut or sidebar button) displaying background thread activity, file I/O timings, and plugin execution logs with severity filtering and search.
- **Precision DSP & Zero-Phase Filtering**:
  - Real-time frequency-domain BPF/BSF mask preview with zero compute overhead.
  - True zero-phase forward-backward filtering (`scipy.signal.sosfiltfilt`) in time-domain detail views, ensuring zero phase shift and exact mathematical band cancellation ($BSF = \text{Original} - BPF$).
- **Extensive File & Stream Ingestion**:
  - **Binary IQ Formats**: `complex64`, `complex128`, `float32`, `float64`, `int16`, `int8`, etc.
  - **Hardware Captures**: Tektronix RSA `.r3f` files with automated hardware header metadata extraction.
  - **MATLAB / Keysight**: `.mat` files with auto-detected scaling and `.mat.overlays` sidecar support.
  - **Audio Formats**: Multi-format audio (`.wav`, `.flac`, `.ogg`, `.mp3`) with automatic channel downmixing and float32 normalization.
  - **Byte Slicing**: Arbitrary byte range slicing (`--bytes START:STOP`, `--start-byte`, `--stop-byte`) with automatic alignment to complex sample boundaries.
  - **Live Stdin Streaming**: Binary pipe ingestion (`--stdin`) for live pipeline integration (e.g. `rtl_sdr - | iqview --stdin`).
- **Interactive Overlays & Markers**:
  - Point, Delta, and Center-locked markers with adaptive boundary clamping.
  - Multi-geometry Region Overlays (`X-Region`, `Y-Region`, `Rect`, `Polygon`, `Ellipse`) with vertex manipulation and sidecar persistence.
- **Detachable Multi-Monitor Windows**: Pop out any analysis tab (Time Domain, Frequency Domain, Eye Diagram, Constellation, or Plugin Plot) into an independent, synchronized window.
- **Vertically Resizable Controls**: Fully customizable workspace with the top control bar splitter.

---

## 💻 Installation

### Standard Installation (PyPI)
Install the latest release from PyPI:
```bash
pip install iqview
```

*Note for Linux/Debian users: ensure system libraries for Qt rendering are installed (`python3-pip`, `libxcb-cursor0`).*

### Launching IQView
IQView can be launched directly via its CLI entry point or as a Python module:
```bash
# Standard entry point
iqview

# Module execution
python -m iqview

# Silent GUI launcher (Windows - suppresses console window)
pythonw -m iqview
```

### Desktop Integration
Add IQView to your Start Menu and associate it with standard IQ file formats (`.iq`, `.bin`, `.cf32`, `.complex64`, etc.):
```bash
iqview --install-desktop
```
To associate Keysight/MATLAB `.mat` files:
```bash
iqview --install-mat
```
*(To remove associations, pass `--uninstall-desktop` or `--uninstall-mat`)*

### Offline Debian Package (`.deb`)
For secure, air-gapped, or isolated environments, dependencies can be bundled into a standalone Debian package:
```bash
# 1. Download offline wheels and prepare build
python scripts/build_project.py --offline-wheels

# 2. Package into .deb with bundled wheels
python scripts/make_deb.py --offline-wheels

# 3. Install on the target machine
sudo apt install ./dist/iqview_*.deb
```

### Developer Installation
Clone the repository and install in editable mode:
```bash
git clone https://github.com/omernaf/IQView.git
cd IQView
pip install -e .
```

---

## 📖 Quick Start

Open an IQ file from the command line:
```bash
iqview -f signals.iq -r 20e6 -c 2.44e9 -t complex64
```
Or open a hardware capture (`.r3f` or `.mat`):
```bash
iqview -f capture.r3f
iqview -f Keysight_Capture.mat
```
Stream live IQ data from standard input:
```bash
rtl_sdr -f 915M -s 2.4M - | iqview --stdin -r 2.4e6 -c 915e6 -t int16
```
Inspect a specific byte slice of a massive file:
```bash
iqview -f huge_recording.raw --bytes 100MB:500MB -r 50e6 -t complex64
```

### Dynamic Filename Parameter Auto-detection
If `-r` (sample rate) or `-c` (center frequency) are omitted, IQView parses the file name for standard notation. For example, a file named:
`capture_20Msps_2.44GHz.cf32`
will automatically launch with $f_s = 20\text{ MHz}$, $f_c = 2.44\text{ GHz}$, and `complex64` data type.

---

## 🛠️ CLI Reference

| Option | Flag | Description | Default |
| :--- | :--- | :--- | :--- |
| **Path** | `path` or `-f`, `--file` | Path to binary IQ, audio, `.r3f`, or `.mat` file | `None` |
| **Stdin** | `--stdin` | Read binary IQ stream from stdin pipe | `False` |
| **Sample Rate** | `-r`, `--rate` | Sample rate in Hz (e.g. `20e6`, `10M`) | `1 MHz` (or auto) |
| **Center Freq** | `-c`, `--fc` | Center frequency in Hz (e.g. `2.4e9`, `915M`) | `0 Hz` (or auto) |
| **Data Type** | `-t`, `--type` | `complex64`, `complex128`, `int16`, `int8`, `float32`, `float64`, `audio` | Auto / `complex64` |
| **FFT Size** | `-s`, `--fft` | FFT bin size (power of 2: 256 to 65536) | `1024` |
| **Normalization** | `--norm`, `--normalization` | Hardware gain / RF power normalization offset in dB | `0.0 dB` |
| **Byte Range** | `--bytes` | Slicing range as `START:STOP` (e.g. `1024:65536`, `0x1000:0x5000`) | `0:EOF` |
| **Start Byte** | `--start-byte`, `-b` | Starting byte offset (supports decimal, hex `0x..`, scientific `1e6`) | `0` |
| **Stop Byte** | `--stop-byte` | Stopping byte offset (supports decimal, hex `0x..`, scientific `1e6`) | `EOF` |
| **Lazy Engine** | `--lazy` | Force on-demand viewport rendering | From Settings |
| **Full Engine** | `--full` | Force full-file upfront memory buffering | From Settings |
| **Debug Mode** | `--debug` | Enable verbose diagnostic logging | `False` |
| **Profile** | `--profile` | Profile execution with cProfile | `False` |
| **Window Name** | `-n`, `--name` | Custom window title | `None` |
| **Desktop Link** | `--install-desktop` / `--uninstall-desktop` | Manage Start Menu shortcuts and OS file associations | `False` |
| **MAT Link** | `--install-mat` / `--uninstall-mat` | Manage `.mat` file type registration | `False` |

---

## 🐍 Python API & Interactive Debugging

You can invoke IQView directly inside Python scripts, Jupyter notebooks, or IDE sessions via `iqview.view()`. This provides a first-class debugging workflow for DSP algorithms and custom plugins with IDE breakpoints.

```python
import numpy as np
import iqview

# 1. Open an existing recording
iqview.view("recordings/burst_10Msps_433MHz.bin")

# 2. Visualize synthetic NumPy signals
fs = 10e6
t = np.arange(int(fs * 0.05)) / fs
chirp = np.exp(1j * np.pi * (10e6 / 0.05) * t**2)

iqview.view(
    chirp,
    fs=fs,
    fc=433.92e6,
    fft_size=2048,
    name="Synthetic Chirp Analysis",
    norm_db=-12.5,
    lazy=False,
    debug=True,
)
```

### Function Signature:
```python
iqview.view(
    source=None,          # File path (str), NumPy array (ndarray), or None
    fs=1e6,               # Sample rate in Hz
    fc=0.0,               # Center frequency in Hz
    fft_size=1024,        # Number of FFT frequency bins
    dtype="complex64",    # Data type format string
    name=None,            # Custom window title
    lazy=None,            # Override lazy rendering (True / False / None)
    norm_db=0.0,          # RF gain / power calibration offset in dB
    debug=False,          # Enable verbose diagnostic logging
)
```

---

## ⌨️ Controls & Keyboard Shortcuts

| Category | Key | Action |
| :--- | :--- | :--- |
| **General** | **Ctrl + O** | Open file dialog |
| | **I** | Open Settings Dialog |
| | **L** | Open Application Diagnostic Log Viewer |
| | **Middle-Click** | Close active analysis tab |
| **Navigation** | **Ctrl (Hold)** | Box Zoom mode (drag left mouse button) |
| | **Space (Hold)** | Pan / Move mode (or Middle-Click drag) |
| | **Ctrl + Z** | Undo zoom level |
| | **R** | Reset zoom to full file view |
| **Analysis Modes** | **T** | Enter **Time Marker** mode |
| | **E** | Enter **Endless Time Marker** mode |
| | **F** | Enter **Frequency Marker** mode |
| | **G** | Enter **Endless Frequency Marker** mode |
| | **B** | Enter **Filter Marker** mode |
| | **O** | Enter **Overlay** mode |
| | **P** | Enter **Plugins** mode |
| **Markers & Locks** | **1** / **2** | Lock Marker 1 / Marker 2 position |
| | **D** | Toggle **Delta Lock** (lock distance between markers) |
| | **C** | Toggle **Center Lock** (symmetrical span expansion) |
| | **[** / **]** | Toggle BPF / BSF in Filter mode |
| | **Backspace** | Clear active markers or overlays |
| | **Delete** | Delete currently selected overlay |
| | **A** | Add Manual Overlay (in Overlay mode) / Load Plugin (in Plugin mode) |

---

## 🧪 Mathematical Foundations & DSP Invariants

### 1. Spectrogram & True Power Spectral Density (PSD)
Each vertical spectrogram slice is computed via the Short-Time Fourier Transform (STFT):
$$X[k] = \sum_{n=0}^{N-1} x_{\text{cal}}[n] \cdot w[n] e^{-j \frac{2\pi}{N} kn}$$

Input samples are calibrated against the RF power gain offset:
$$x_{\text{cal}}[n] = x[n] \cdot 10^{-\text{norm\_db} / 20}$$

To ensure PSD values in $\text{dB/Hz}$ are invariant to window function $w[n]$, window length, and FFT size $N$, IQView applies the exact window power normalization offset:
$$\text{offset}_{\text{dB}} = 10 \log_{10}\left(f_s \sum_{n=0}^{N-1} w^2[n]\right)$$
$$\text{Level}_{\text{dB/Hz}}[k] = 10 \log_{10}(|X[k]|^2 + \epsilon) - \text{offset}_{\text{dB}}$$
*where $\epsilon = 10^{-12}$ prevents numerical singularities.*

### 2. Time-Frequency Coordinate Alignment
To guarantee that spectrogram pixel coordinates perfectly match the physical sample center, bounding boxes account for the STFT window-center delay:
$$\Delta t_{\text{offset}} = \frac{\text{window\_size} / 2 - \text{step\_size} / 2}{f_s}$$

### 3. Zero-Phase Forward-Backward Filtering
Time-domain filtering in detail views strictly uses zero-phase forward-backward second-order sections (`scipy.signal.sosfiltfilt`). This eliminates group delay and non-linear phase shifts, ensuring mathematical identity between band-pass and band-stop operations:
$$x_{\text{BSF}}[n] = x[n] - x_{\text{BPF}}[n]$$

### 4. Time Domain Transformations
IQView computes analytical metrics for complex samples $x[n] = I[n] + jQ[n]$:
- **Magnitude**: $|x[n]| = \sqrt{I[n]^2 + Q[n]^2}$
- **Magnitude [dB]**: $20 \log_{10}(|x[n]| + \epsilon)$
- **Magnitude² [dB]**: $10 \log_{10}(|x[n]|^2 + \epsilon)$
- **Phase**: $\phi[n] = \text{atan2}(Q[n], I[n])$
- **Instantaneous Frequency**: $f_{\text{inst}}[n] = \frac{\text{unwrap}(\Delta \phi[n])}{2\pi \Delta t}$

---

## 🔌 Plugin Ecosystem & Built-in Algorithms

IQView features an extensible DSP plugin framework with visual chaining (`PluginChain`) and dedicated result tabs:

- **Polygon Time-Frequency Mask Filter** (`polygon_tf_filter`): Interactively isolate complex hopping or chirped signals across arbitrary polygonal boundaries in the spectrogram, masking or band-passing the time-frequency region and reconstructing the filtered baseband IQ.
- **Gabor Ellipse Phase & Chirp Analyzer** (`ellipse_gabor_analyzer`): Fit Gabor time-frequency atoms inside an interactive elliptical overlay to estimate instantaneous chirp rate ($k_{\text{chirp}} = \frac{\Delta f}{\Delta t}$), effective RMS duration ($\sigma_t$), and bandwidth ($\sigma_f$).
- **Signal Comparator** (`signal_comparator`): High-precision cross-correlation engine featuring energy-normalized correlation and differential cross-correlation for comparing signals across time and frequency offsets.
- **LoRa Modem Demodulator** (`lora_demodulator`): Detects LoRa chirps, measures precise occupied bandwidth (OBW), computes Spreading Factor ($SF$) from symbol duration, de-chirps the spectrogram waterfall, and decodes payload symbols.
- **GNSS PRN Acquisition** (`gnss_detector`): Performs parallel code-phase search and Doppler estimation across GPS/Galileo satellite constellations.

For authoring your own plugins, see the comprehensive [🔌 Plugin Developer Guide](https://github.com/omernaf/IQView/blob/master/docs/plugin_guide.md).

---

## 📚 Detailed Documentation

Explore in-depth documentation for each module and view:

- [🌌 **Spectrogram View**](https://github.com/omernaf/IQView/blob/master/docs/spectrogram.md): STFT, windowing functions, colormaps, and OpenGL rendering.
- [⏳ **Time Domain View**](https://github.com/omernaf/IQView/blob/master/docs/time_domain.md): Waveform representations, zero-phase filtering, and statistics.
- [📶 **Frequency Domain View**](https://github.com/omernaf/IQView/blob/master/docs/frequency_domain.md): PSD estimation, peak detection, and integrated channel power.
- [👁️ **Eye Diagram View**](https://github.com/omernaf/IQView/blob/master/docs/eye_diagram.md): Digital symbol transitions, fractional oversampling, and phase alignment.
- [✨ **Scatter / Constellation View**](https://github.com/omernaf/IQView/blob/master/docs/scatter_plot.md): IQ constellation diagrams, phase rotation, and fine frequency offset tuning.
- [🔌 **Plugin Developer Guide**](https://github.com/omernaf/IQView/blob/master/docs/plugin_guide.md): Complete architecture guide for custom DSP plugins and chains.
- [⚙️ **Settings & Preferences**](https://github.com/omernaf/IQView/blob/master/docs/settings.md): Configuration keys, color palettes, and default analysis parameters.
- [📦 **Distribution & Packaging**](https://github.com/omernaf/IQView/blob/master/docs/distribution.md): PyPI wheels, standalone executables, and Debian packaging.

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](https://github.com/omernaf/IQView/blob/master/LICENSE) file for details.  
Original author: **Omer Naftali** ([@omernaf](https://github.com/omernaf)).

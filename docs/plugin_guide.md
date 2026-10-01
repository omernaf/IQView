# IQView Plugin Development & System Guide

IQView features an asynchronous, modular, and extensible Python plugin architecture. Plugins can natively process complex IQ samples, stream large files in bounded-memory batches, create interactive visual overlays on the spectrogram, attach cached baseband IQ data, launch rich 1D plot tabs with markers and shaded regions, open native IQView analysis windows, and chain together into multi-step pipelines.

Plugins run safely on an isolated background worker thread (`QThread`), ensuring that computationally intensive DSP algorithms (such as large FFTs, DDC filter banks, or machine learning models) execute smoothly without blocking or freezing the application UI.

> [!NOTE]
> IQView ships with a built-in library of production-grade plugins for wideband channelization, burst energy detection, bounding box snapping, FSK demodulation, RF metrics (SNR, OBW, CFO, PAPR), and overlay stitching. All built-in plugins include full interactive documentation accessible directly inside the application UI via the **Docs** viewer and **Plugin Studio**.

---

## Table of Contents

1. [Plugin Architecture & Execution Model](#1-plugin-architecture--execution-model)
2. [Plugin Anatomy, Discovery & Lifecycle](#2-plugin-anatomy-discovery--lifecycle)
3. [The `PluginContext` (`info`) Object & Samples Buffer](#3-the-plugincontext-info-object--samples-buffer)
4. [The Object-Oriented Overlay API & Serialization](#4-the-object-oriented-overlay-api--serialization)
5. [Cached Per-Burst Baseband IQ (`o.iq`, `o.fs`) & DDC Extraction](#5-cached-per-burst-baseband-iq-oiq-ofs--ddc-extraction)
6. [The `PluginResult` Return Object & Error Handling](#6-the-pluginresult-return-object--error-handling)
7. [Custom 1D Plot Tabs (`PluginPlotView`)](#7-custom-1d-plot-tabs-pluginplotview)
8. [Native Analysis Tab Launchers](#8-native-analysis-tab-launchers)
9. [Dynamic Parameters & Automatic Session Persistence](#9-dynamic-parameters--automatic-session-persistence)
10. [Plugin Chains (`PluginChain`) & Pipeline Execution](#10-plugin-chains-pluginchain--pipeline-execution)
11. [In-App Documentation Specification (`PLUGIN_DOC`)](#11-in-app-documentation-specification-plugindoc)
12. [IQView Plugin Studio](#12-iqview-plugin-studio)
13. [Complete Code Examples](#13-complete-code-examples)
14. [Best Practices & Performance Guidelines](#14-best-practices--performance-guidelines)

---

## 1. Plugin Architecture & Execution Model

```
+------------------------------------------------------------------------+
|                          IQView Main UI Thread                         |
|  - Spectrogram Display (Waterfall / Multi-Row)                         |
|  - Overlays Layer (Rect, Polygon, Ellipse, Lines)                      |
|  - Plugin Studio & Toolbar (Manage, Chain Builder, Scaffolding)        |
+------------------------------------------------------------------------+
                               |                  ^
       1. Dispatches run()     |                  | 4. Applies PluginResult
          with PluginContext   v                  |    (Atomic UI update)
+------------------------------------------------------------------------+
|                      Background Worker (QThread)                       |
|  - Executes plugin run(samples, info)                                  |
|  - Emits real-time progress: info.progress(pct, "Status...")           |
|  - Checks user cancellation: info.is_cancelled()                       |
|  - Automatically batches large recordings (PLUGIN_BATCH_SECONDS)       |
+------------------------------------------------------------------------+
```

### Execution Scopes & Marker Fallback Semantics
When a plugin runs, it operates over a defined region of the recording. Users select the active **Execution Scope** from the toolbar dropdown or the Plugin Studio:
* **Current View (`"view"`)**: Bounded by the currently visible time $[t_{\text{start}}, t_{\text{end}}]$ and frequency $[f_{\text{start}}, f_{\text{end}}]$ of the spectrogram viewport (multi-row and waterfall aware).
* **Between Markers (`"markers"`)**: Bounded by active time markers ($M_1, M_2$) and frequency markers.
  * **Automatic Fallback**: If fewer than two time markers are active on the spectrogram, the time bounds $[t_{\text{start}}, t_{\text{end}}]$ automatically fall back to the visible viewport time range. Likewise, if fewer than two frequency markers are active, frequency bounds $[f_{\text{start}}, f_{\text{end}}]$ fall back to the visible viewport frequency range.
* **Full File (`"full_file"`)**: Spans the entire recording from $t = 0.0$ to the end of the file across the full Nyquist bandwidth ($f_c \pm f_s/2$).

### Asynchronous Processing & Progress Reporting
Plugins do not freeze the UI. If execution takes more than 250 ms, a modal progress dialog appears with a cancel button. Inside `run()`, plugins report progress and check for cancellation:

```python
def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()
    total_steps = 100

    for i in range(total_steps):
        if info.is_cancelled():
            break  # Exit cooperatively on user cancellation
        
        # Do processing...
        info.progress((i + 1) / total_steps * 100.0, f"Processing step {i + 1}/{total_steps}...")

    return result
```

---

## 2. Plugin Anatomy, Discovery & Lifecycle

An IQView plugin is a standard Python `.py` file that defines a top-level `run` function and optional module-level constants declaring its metadata, parameters, documentation, and resource requirements:

```python
"""
My Custom IQView Plugin
"""
from __future__ import annotations
import numpy as np
from iqview import PluginResult, PluginContext
from iqview.overlays import Rect

# --- Module Metadata ---
PLUGIN_NAME                  = "Fast Energy Detector"
PLUGIN_DESCRIPTION           = "Detects bursts using an adaptive power threshold"
PLUGIN_CATEGORY              = "Detection"   # e.g., Detection, Demodulation, Metrics, Chains, Custom
PLUGIN_NEEDS_WIDEBAND_IQ     = True          # False if plugin only reads overlays or extracts on demand
PLUGIN_BATCH_SECONDS         = 1.0           # Auto-chunks files longer than 1s into 1s batches
PLUGIN_BATCH_OVERLAP_SECONDS = 0.05          # 50 ms overlap between consecutive batches
PLUGIN_RUN_ON_MAIN_THREAD    = False         # Set True ONLY if synchronous UI execution is needed

# --- In-App Markdown Documentation ---
PLUGIN_DOC = """# Fast Energy Detector

Detects RF energy bursts exceeding the background noise floor by a user-defined threshold.

### Algorithm
1. Computes power envelope $|x[n]|^2$.
2. Estimates median noise floor.
3. Detects contiguous sample segments above `threshold_db`.
"""

# --- Parameter Schema ---
PLUGIN_PARAMS = {
    "threshold_db": {
        "type": "float",
        "default": 10.0,
        "label": "Threshold (dB)",
        "tooltip": "Power threshold in dB above the estimated noise floor",
    },
    "margin": {
        "type": "int",
        "default": 16,
        "label": "Margin (samples)",
        "tooltip": "Extra safeguard samples prepended and appended to each burst",
    },
}

# --- Entry Point ---
def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()
    threshold = float(info.params.get("threshold_db", 10.0))
    # DSP logic here...
    return result
```

### Module Metadata Constants

| Constant | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `PLUGIN_NAME` | `str` | Filename stem | Display name shown in menus, toolbars, and the Studio. Does not need to match the filename. |
| `PLUGIN_DESCRIPTION` | `str` | `""` | Brief one-line summary displayed in tooltips and catalogs. |
| `PLUGIN_CATEGORY` | `str` | `"Custom"` | Grouping category (e.g. `Detection`, `Demodulation`, `Metrics`, `Chains`). |
| `PLUGIN_DOC` | `str` | `""` | Full in-app documentation in GitHub-flavored Markdown (`.md`). |
| `PLUGIN_PARAMS` | `dict` | `{}` | Parameter specification schema rendered dynamically in the UI. |
| `PLUGIN_NEEDS_WIDEBAND_IQ` | `bool` | `True` | Set to `False` if your plugin only processes existing overlays or calls `o.get_samples()`. Avoids loading large wideband IQ buffers into memory. |
| `PLUGIN_BATCH_SECONDS` | `float \| None` | `None` | Automatically slices the execution scope into time chunks of this duration, preventing out-of-memory errors on large files. |
| `PLUGIN_BATCH_OVERLAP_SECONDS` | `float` | `0.0` | Overlap duration in seconds between consecutive chunks when batching. |
| `PLUGIN_RUN_ON_MAIN_THREAD` | `bool` | `False` | Forces execution on the Qt main GUI thread. Useful for interactive debugging. |

### Plugin Discovery & File Locations
* **File Paths**: Plugin `.py` files can live **anywhere on the filesystem**.
  * Users can load plugins from any folder via **Plugins $\rightarrow$ Load Plugin(s)...** or through the **Plugin Studio**.
  * IQView records loaded plugin paths in application settings (`plugins/loaded_paths`), automatically reloading them across sessions.
  * Standard built-in plugins are located in `iqview/plugins/builtin/`.
* **Naming Conventions**: The filename on disk does **not** have to match `PLUGIN_NAME`. If `PLUGIN_NAME` is defined in the script, it overrides the filename stem for all menu entries, toolbar items, and result tags.

### Import Environment & Third-Party Library Safety
* **In-Process Architecture**: Plugins execute in the same Python process as IQView. Top-level exports are available for direct import without modifying `sys.path`:
  ```python
  from iqview import PluginResult, PluginContext, PluginParams, PluginChain
  from iqview.overlays import Rect, Polygon, Ellipse, VerticalLine, OverlayShape
  ```
* **Safe Libraries**: Any standard mathematical, scientific, or DSP library installed in the environment is safe to import inside `run()`:
  * `numpy`, `scipy` (`scipy.signal`, `scipy.fft`, `scipy.ndimage`, `scipy.optimize`), `math`, `re`, `json`, `collections`.
  * `matplotlib` in non-interactive / headless mode (e.g. `matplotlib.use("Agg")`).
* **Concurrency Constraint (PyQt Hazards)**: **Never import or instantiate `PyQt6.QtWidgets` widgets inside `run()`**. Because `run()` executes on a worker `QThread`, calling Qt GUI elements directly from this thread violates Qt threading rules and will crash the application. Always request UI operations via `PluginResult`.

### Module Lifecycle, In-Memory State & Automatic Hot-Reloading
* **State Persistence**: When a plugin is executed, IQView retains the loaded module in memory. Module-level caches, lookup tables, and pre-loaded neural network weights persist across repeated runs as long as the file is untouched on disk.
* **Automatic Hot-Reloading**: Before executing a plugin, IQView inspects the file's modification timestamp (`mtime`). If the `.py` file has been modified and saved, IQView automatically **hot-reloads** the module so code changes take effect immediately without requiring an application restart.

---

## 3. The `PluginContext` (`info`) Object & Samples Buffer

When `run(samples, info)` is called, `info` is an instance of `PluginContext`. It provides dual-access syntax: clean Python attributes (`info.sample_rate`) and legacy dictionary subscripting (`info["sample_rate"]`).

### Available Properties

```python
# Signal Parameters
fs = info.sample_rate      # float: Sample rate in Hz (alias: info.fs)
fc = info.center_freq      # float: Center frequency in Hz (alias: info.fc)

# Scope Boundaries (Absolute Units)
t0, t1 = info.t_start, info.t_end    # float: Scope time boundaries in seconds
f0, f1 = info.f_start, info.f_end    # float: Scope frequency boundaries in absolute RF Hz
dur = info.duration                  # float: Scope duration (t_end - t_start) in seconds
bw = info.bandwidth                  # float: Scope bandwidth (f_end - f_start) in Hz

# Context & Spectrogram State
scope_name = info.scope              # str: "view", "markers", or "full_file"
overlays = info.overlays             # list[Overlay]: Snapshot of all overlays currently on screen
fft_size = info.fft_size             # int: Spectrogram FFT size (e.g. 1024)
spec_db = info.spectrogram           # np.ndarray | None: Rendered 2D spectrogram image in dB
file_dur = info.file_duration        # float: Total duration of loaded recording in seconds
path = info.file_path                # str | None: Path to open file on disk

# Active Markers & Filters
t_markers = info.time_markers        # list[float]: Active time marker values [M1, M2] in seconds
f_markers = info.freq_markers        # list[float]: Active frequency marker values in Hz
bpf = info.filter_bounds             # tuple[float, float] | None: Active (f_lo, f_hi) filter bounds
```

### The `samples` Buffer Semantics & Alignment
* **Data Format**: When populated, `samples` is always a 1-D NumPy array of `dtype=np.complex64`.
* **Time Indexing**: Sample index `0` corresponds exactly to `info.t_start`. The timestamp for sample index $n$ is:
  $$t = \text{info.t\_start} + \frac{n}{\text{info.sample\_rate}}$$
* **Wideband Nature**: When `samples` is provided, it is **raw wideband IQ** sampled at the global sample rate (`info.sample_rate`). Even if the execution scope is frequency-bounded (e.g. zoomed in to a 50 kHz channel), `samples` is **not** pre-mixed to the center frequency or decimated to the sub-band bandwidth. The frequency boundaries are passed in `info.f_start` and `info.f_end` to indicate the active sub-band.
* **When `samples` Is Empty or `None`**:
  * If `PLUGIN_NEEDS_WIDEBAND_IQ = False` is set, `samples` is passed as an empty array (`len(samples) == 0`). Downstream plugins obtain burst data via `o.get_samples(samples, info)`.
  * If `PLUGIN_BATCH_SECONDS` chunked streaming is active, wideband pre-extraction is bypassed, and chunks are streamed individually to `run()`.
  * *Always include a safe guard*: `if samples is None or len(samples) == 0: return PluginResult()`.

### Frequency Coordinates & Bandwidth
* **Absolute RF Frequencies**: `info.f_start` and `info.f_end` are expressed in **absolute RF Hz** (centered around `info.center_freq`). For example, if center frequency is 915 MHz with 2 MHz bandwidth, `f_start` might be `914.5e6` and `f_end` `915.5e6`. To convert to a zero-centered baseband offset:
  $$f_{\text{offset}} = f - \text{info.center\_freq}$$
* **Bandwidth Definition**: `info.bandwidth` is strictly:
  $$\text{info.bandwidth} = \text{info.f\_end} - \text{info.f\_start}$$
  It follows the active Execution Scope (the viewport for `"view"`, the markers for `"markers"`, or full Nyquist for `"full_file"`).
* **Filter Bounds Independence**: Active BPF or BSF filter boundaries do **not** override `info.bandwidth` or `info.f_start/f_end`. Instead, filter limits are provided separately as an informative tuple via `info.filter_bounds` (which is `(f_lo, f_hi)` if a filter is active, or `None`).

### Context Methods

#### Parameter Access: `info.params`
Access user-configured parameters using attribute notation or standard dictionary methods:
```python
threshold = info.params.threshold_db
margin = info.params.get("margin", 0)
```

#### On-Demand IQ Extraction: `info.extract_iq(t0, t1)`
Extracts raw complex64 samples for any arbitrary time slice $[t_0, t_1]$ directly from disk or memory:
```python
burst_samples = info.extract_iq(1.200, 1.250)
```

#### Batch Streaming Paradigms: Declarative vs. Programmatic
IQView provides two alternative batching paradigms for handling massive recordings without memory exhaustion:
1. **Declarative Host Batching (`PLUGIN_BATCH_SECONDS`)**:
   * Set `PLUGIN_BATCH_SECONDS = 1.0` (and optional `PLUGIN_BATCH_OVERLAP_SECONDS = 0.05`) at module level.
   * The host background worker automatically slices the active scope and calls your `run(batch_samples, batch_info)` repeatedly—once per chunk.
   * On each invocation, `batch_info.t_start` and `batch_info.t_end` are shifted to bound that specific chunk.
   * Overlays emitted across chunks are concatenated by the host. To avoid duplicate detections across chunk boundaries, set `PLUGIN_BATCH_OVERLAP_SECONDS = 0.0` or pipe into a merge plugin.
2. **Programmatic In-Plugin Batching (`info.iter_batches()`)**:
   * Leave `PLUGIN_BATCH_SECONDS = None`, set `PLUGIN_NEEDS_WIDEBAND_IQ = False`, and iterate directly inside your single `run()` call:
     ```python
     for chunk_samples, chunk_t0, chunk_t1 in info.iter_batches(duration_s=0.5, overlap_s=0.0):
         if info.is_cancelled():
             break
         # Process 500 ms chunk...
     ```
   * *Note: Do not combine both paradigms at the same time.*

---

## 4. The Object-Oriented Overlay API & Serialization

IQView provides strictly typed overlay classes under `iqview.overlays`. Overlays placed by plugins are **locked by default** (`locked=True`) so they cannot be accidentally moved or resized when panning the spectrogram.

### Available Overlay Types

```python
from iqview.overlays import (
    Rect,           # Rect(t_start, f_start, t_end, f_end)
    Polygon,        # Polygon(vertices=[(t, f), ...])
    Ellipse,        # Ellipse(t_center, f_center, t_radius, f_radius)
    VerticalLine,   # VerticalLine(t) or TimeLine(t)
    HorizontalLine, # HorizontalLine(f) or FreqLine(f)
    TimeRegion,     # TimeRegion(t_start, t_end) - spans full frequency axis
    FreqRegion,     # FreqRegion(f_start, f_end) - spans full time axis
    Point,          # Point(t, f) or Dot(t, f)
    OverlayShape,   # Enum: RECT, POLYGON, ELLIPSE, LINE, HLINE, X_REGION, Y_REGION, DOT
)
```

### Shape Checking: `OverlayShape` Enum vs. String Name
To verify the geometric shape of an overlay, compare against the typed enum:
```python
from iqview.overlays import OverlayShape

if o.shape == OverlayShape.RECT:
    # Process rectangular burst...
```
*(The convenience helper `o._shape_name()` returning `"RECT"`, `"POLYGON"`, etc. is also fully supported).*

### Creating Overlays

```python
r = Rect(
    t_start=0.100, f_start=915.0e6,
    t_end=0.150,   f_end=915.2e6,
    color="#00aaff",          # Hex fill and border color
    alpha=0.25,               # Fill opacity (0.0 to 1.0)
    border_width=2,           # Border stroke in pixels
    border_color="#ffffff",   # Optional custom border color
    border_style="solid",     # "solid", "dash", "dot", "dashdot"
    display_str="915.1 MHz",  # Label permanently rendered on overlay
    hover_str="FSK Signal",   # Detailed tooltip shown on mouse hover
    tag_pos="center",         # "center", "top-left", "top-right", "bottom-left", "bottom-right"
    locked=True,              # Locked by default (prevents accidental dragging)
    visible=True,             # Visibility flag
    z_order=8,                # Layer stacking order (higher values draw on top)
    metadata={"snr_db": 22.4} # Arbitrary JSON-serializable dictionary
)
```

### Smart Geometry Properties
All overlay objects provide unified world-space accessors (in seconds and Hz):

| Property | Description |
| :--- | :--- |
| `o.t_start`, `o.t_end` | Left and right time boundaries in seconds. |
| `o.t_center` | Midpoint time $\frac{t_0 + t_1}{2}$ in seconds. |
| `o.duration` | Temporal duration $(t_1 - t_0)$ in seconds. |
| `o.f_start`, `o.f_end` | Lower and upper frequency boundaries in Hz. |
| `o.f_center` | Center frequency $\frac{f_0 + f_1}{2}$ in Hz. |
| `o.bandwidth` | Frequency span $(f_1 - f_0)$ in Hz. |

### Overlay Identity & Lifetime Stability
* **UUID Stability**: Each overlay is assigned a UUID string (`o.id`) upon creation that remains stable throughout the entire application session.
* **Targeting Overlays**: Methods such as `result.update(o.id, ...)` and `result.remove(o.id)` consume this exact string ID (or the `Overlay` instance directly). Deep-copied snapshots passed to `info.overlays` preserve the identical `o.id`.

### Sidecar Serialization & Metadata Rules
* **JSON Sidecar Persistence**: Overlays serialize to disk via `.json` sidecars (`to_dict()`).
* **Supported Metadata Types**: Any standard JSON-serializable Python data type survives a session save (`int`, `float`, `str`, `bool`, `list`, `dict`, `None`).
* **Transient Fields Excluded**: `o.iq` and `o.fs` are **deliberately excluded** from JSON sidecars to keep sidecar files lightweight and avoid storing multi-gigabyte raw sample buffers in text files.
* **Type Conversion Requirement**: Non-JSON data types stored in `o.metadata` (such as NumPy scalar types, complex numbers, NumPy arrays, or Python functions) will raise a serialization error unless converted beforehand (e.g. `float(val)` or `arr.tolist()`).

---

## 5. Cached Per-Burst Baseband IQ (`o.iq`, `o.fs`) & DDC Extraction

A central feature of the plugin system is **Zero-Copy Per-Burst Baseband Hand-Off**.

Detection plugins can slice the narrowband complex baseband signal for a burst, down-convert it, and attach it directly to the overlay's in-memory fields:
* `overlay.iq`: 1D `complex64` NumPy array containing baseband samples.
* `overlay.fs`: Effective sample rate of `overlay.iq` in Hz.

*(Note: `o.iq` and `o.fs` are stored in memory and are excluded from disk `.json` sidecar files to prevent multi-gigabyte sidecars).*

### Consuming Samples: `o.get_samples(samples, info)`
Downstream plugins (such as demodulators, classifiers, or metrics calculators) declare:
```python
PLUGIN_NEEDS_WIDEBAND_IQ = False
```
And retrieve the burst signal via `o.get_samples(samples, info)`:

```python
for o in info.overlays:
    if o.shape != OverlayShape.RECT:
        continue

    # Zero disk I/O if o.iq is already cached!
    burst_iq, burst_fs = o.get_samples(samples, info)
    if burst_iq is None or len(burst_iq) == 0:
        continue

    # Process baseband signal directly
    demodulate(burst_iq, burst_fs)
```

#### How `o.get_samples()` Works Under the Hood:
1. **Cached Path ($O(1)$)**: If `o.iq` is already present on the overlay (e.g. generated by an energy detector or channelizer), it returns `(o.iq, o.fs)` instantly with zero disk reads and zero FFT overhead.
2. **Lazy DDC Fallback**: If the overlay was drawn manually by a user or loaded from a sidecar file (`o.iq is None`), `o.get_samples()` automatically:
   - Slices the time interval $[t_{\text{start}}, t_{\text{end}}]$ from wideband data.
   - Mixes the center frequency $f_{\text{center}}$ down to 0 Hz DC baseband: $e^{-j 2\pi f_c t}$.
   - Applies an anti-aliasing low-pass filter with bandwidth equal to `o.bandwidth`.
   - Resamples and decimates the signal to `o.bandwidth` Hz.

### Attaching Baseband IQ to Non-Owned Overlays
Plugins are fully permitted to attach or update `o.iq` and `o.fs` on overlays created by other plugins or drawn manually by the user. While `result.remove()` is restricted to overlays owned by the calling plugin, **`result.update()` has no ownership restrictions**. Calling `result.update(o.id, iq=burst_iq, fs=burst_fs)` or `result.update(o)` successfully caches and persists the baseband signal on the live overlay in memory.

---

## 6. The `PluginResult` Return Object & Error Handling

Every plugin's `run()` function must return a `PluginResult` object (`run()` cannot return `None`). It provides a fluent builder interface to queue operations:

```python
from iqview import PluginResult

result = PluginResult()
```

### Overlay Operations

```python
# 1. Add a new overlay (assigns a fresh UUID and sets source="plugin:<name>")
result.add(new_rect)

# 2. Update existing overlay fields (supports passing ID or Overlay instance)
result.update(overlay_id, color="#ff0000", display_str="Demodulated")
result.update(o)  # Syncs modified attributes of overlay instance 'o'

# 3. Remove an overlay (Safety restricted: only removes overlays owned by this plugin)
result.remove(overlay_id)

# 4. Atomic Replace (Removes old_id and inserts replacement, preserving provenance)
result.replace(old_id, tightly_fitted_rect)
```

### Return Type Contract
The plugin runner strictly checks the return value of `run()`. If a plugin returns `None` or any type other than `PluginResult`, execution aborts and an error dialog informs the user. To perform no actions or exit early, return an empty result: `return PluginResult()`.

### Exception Handling & Stack Tracebacks
If `run()` raises an unhandled Python exception, the background worker catches it safely without crashing the application. A modal error dialog (`QMessageBox.critical`) is presented to the user displaying the **complete exception type, message, and full stack traceback**.

### Logging & Warning Mechanisms
* **`result.log("message")`**:
  * Prints `[IQView Plugin: <name>] message` to standard output / terminal console.
  * Surfaces the message on the **main application bottom status bar** for 5 seconds upon completion.
* **Alternative Warning Methods**:
  * **Progress Dialog**: Call `info.progress(pct, "Warning: Low SNR detected...")` to update the modal progress status text live.
  * **Overlay Tooltips**: Set `hover_str="Warning: SNR < 6 dB"` or prefix `display_str="⚠ Signal"` to provide visual warning indicators on the spectrogram.

---

## 7. Custom 1D Plot Tabs (`PluginPlotView`)

Plugins can open dedicated, interactive 1D visualization tabs inside the IQView workspace. These tabs support:
* Multi-trace plotting with legends and active-trace selection.
* Background shaded state/phase regions (e.g. Preamble, Header, Payload).
* Interactive marker panel ($M_1$, $M_2$, $\Delta$, Center frequency/time).
* Region Statistics (Mean, Min, Max, RMS, Peak-to-Peak).
* Sub-plot toolbar switching ($F_1 \dots F_{10}$).
* In-place updates: Re-running a plugin updates its existing plot tab in place rather than creating duplicate tabs.

```python
result.set_plot_tab_title("FSK Demodulator — Debug")

# Add a sub-plot
result.add_plot(
    title="Discriminator Output",
    y={
        "Instantaneous Freq": freq_trace,
        "Slicing Threshold": np.zeros_like(freq_trace),
    },
    x=time_axis,
    fs=sample_rate,
    x_label="Time",
    x_units="s",
    y_label="Frequency Deviation",
    primary_mode="TIME",
    regions=[
        {"x_start": 0.000, "x_end": 0.012, "color": "#00ff88", "alpha": 0.20, "label": "PREAMBLE"},
        {"x_start": 0.012, "x_end": 0.045, "color": "#00aaff", "alpha": 0.20, "label": "PAYLOAD"},
    ]
)
```

---

## 8. Native Analysis Tab Launchers

Plugins can launch IQView's built-in deep-dive analysis tools directly populated with processed samples:

```python
# Open Native Time Domain View (I/Q waveforms & envelope)
result.open_time_domain(samples, fs=fs, t_start=t0, title="Burst — Time Domain")

# Open Native Frequency Domain View (FFT spectrum & PSD)
result.open_freq_domain(samples, fs=fs, fc=fc, title="Burst — Spectrum")

# Open Constellation (Scatter Plot) View
result.open_constellation(samples, fs=fs, title="Burst — Constellation")

# Open Eye Diagram View
result.open_eye_diagram(samples, fs=fs, title="Burst — Eye Diagram")
```

---

## 9. Dynamic Parameters & Automatic Session Persistence

### Exposing Parameters in `PLUGIN_PARAMS`
Declare a dictionary where keys are parameter IDs:

```python
PLUGIN_PARAMS = {
    "baud_rate": {
        "type": "float",
        "default": 9600.0,
        "label": "Baud Rate (Bd)",
        "tooltip": "Expected symbol rate in symbols per second (0.0 for auto-estimate)",
    },
    "filter_taps": {
        "type": "int",
        "default": 32,
        "label": "Filter Taps",
        "tooltip": "Number of FIR moving-average filter taps",
    },
    "invert": {
        "type": "bool",
        "default": False,
        "label": "Invert Frequency",
        "tooltip": "Invert sign of frequency deviation",
    },
    "preamble": {
        "type": "str",
        "default": "10101010",
        "label": "Sync Pattern",
        "tooltip": "Binary preamble string for packet alignment",
    },
}
```

### Accessing Parameters Inside `run()`
```python
def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    baud = float(info.params.baud_rate)
    taps = int(info.params.get("filter_taps", 32))
    invert = bool(info.params.invert)
    preamble = str(info.params.get("preamble", "10101010"))
    ...
```

### Automatic Session Persistence
When users modify parameters in the UI (via the **Config** dialog, toolbar, or Plugin Studio), the values are **automatically saved to the application session settings** (`plugins/saved_params`).
* Re-launching IQView automatically restores the exact parameter values you used previously.
* Python source files (`.py`) are never overwritten or modified on disk, preserving code integrity.

---

## 10. Plugin Chains (`PluginChain`) & Pipeline Execution

The `PluginChain` engine allows multiple plugins to run sequentially, piping overlays and in-memory baseband IQ data seamlessly between steps.

### Defining a Chain in Python

Create a `.py` file inside your plugins folder:

```python
"""
Channelize, Snap, and Demodulate Pipeline
"""
from __future__ import annotations
from iqview import PluginChain

PLUGIN_NAME        = "Detect + Snap + Demod"
PLUGIN_DESCRIPTION = "Channelizer burst detector followed by snap-to-burst and 2-FSK demodulation."
PLUGIN_CATEGORY    = "Chains"

CHAIN = (
    PluginChain(name=PLUGIN_NAME, description=PLUGIN_DESCRIPTION)
    .add("Channelizer + Energy Detector", channel_spacing=25000.0, threshold_db=8.0, margin=16)
    .add("Snap to Burst", threshold_db=6.0, obw_percent=99.0)
    .add("FSK Demodulator", baud_rate=0.0, debug_plots=True)
)

# Binds chain execution, combined parameter schemas, and documentation
CHAIN.bind_to_module(globals(), __file__)
```

### In-Memory Pipeline Flow & Visibility Timing
* **Execution Sequence**: Each step executes sequentially and returns its `PluginResult`.
* **Immediate Reconciliation**: Overlay operations (`adds`, `updates`, `replaces`, `removes`) are applied in memory immediately after a step returns.
* **Step Visibility Timing**: Any `o.iq` and `o.fs` slices attached to overlays in Step $k$ become **immediately available** in `info.overlays` to Step $k+1$.
* **Automatic Cleanup**: Re-running a chain automatically removes overlays previously produced by that chain within the active time scope before executing Step 0, preventing duplicate overlay stacking.

### Step-by-Step UI Execution
In the **Plugin Studio** or **Config** panel, each step in a chain has its own control card:
* **▶ Run Step Only**: Executes only that specific step against the current overlays on screen. This lets you tune demodulator settings and re-run demodulation in milliseconds without re-running the detector!
* **⏩ Run From Here**: Executes the pipeline starting from that step forward to the end.

---

## 11. In-App Documentation Specification (`PLUGIN_DOC`)

Every plugin should provide comprehensive documentation in the `PLUGIN_DOC` string formatted in GitHub-flavored Markdown. This documentation renders natively inside the **Plugin Studio** and the **Docs Viewer** dialog with syntax highlighting and theme-aware styling.

### Standard Template

```python
PLUGIN_DOC = """# Plugin Name

One-paragraph executive summary of the plugin's capability and purpose.

### Operation & Algorithm
1. **Stage 1 (Preprocessing)**: Explanation of filtering, FFT, or decimation.
2. **Stage 2 (Detection / Measurement)**: Mathematical principles and threshold criteria.
3. **Stage 3 (Overlay / Plot Output)**: What visual indicators or plot tabs are generated.

### Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `param_one` | `float` | `10.0` | Primary operational threshold in dB. |
| `param_two` | `int` | `32` | Filter tap count or window size. |

### Output Metadata
When applied to an overlay, the following fields are populated in `overlay.metadata`:
* `snr_db` (`float`): Signal-to-noise ratio in dB.
* `cfo_hz` (`float`): Estimated carrier frequency offset in Hz.

### References
* Author Name / Organization
* Standard or Specification (e.g. IEEE 802.15.4, Bluetooth Low Energy)
"""
```

---

## 12. IQView Plugin Studio

The **Plugin Studio** (`Plugins -> Plugin Studio...`) provides a visual control center divided into three tabs:

```
+--------------------------------------------------------------------------------+
|  Manage & Run  |  Chain Builder  |  + Create Plugin (.py)                      |
+--------------------------------------------------------------------------------+
| [Search plugins...]               | Parameters & Step Execution                |
| [ ] Favorites only                | [Threshold (dB) ]: [ 10.0 ]               |
|                                   | [Margin (samples)]: [ 16   ]               |
| * Fast Energy Detector            |                                            |
|   Snap to Burst                   | [ ▶ Run Plugin ]                           |
|   FSK Demodulator                 |--------------------------------------------|
|   Custom Chain                    | Documentation Preview                      |
|                                   | (Live interactive Markdown view)           |
+--------------------------------------------------------------------------------+
```

### Tab 1: Manage & Run
* **Catalog & Favorites**: Search all loaded plugins. Star favorites to display them on the main Spectrogram toolbar.
* **Inline Parameter Configuration**: Edit parameters directly with theme-aware controls (scientific notation enabled).
* **Step Controls**: For chain plugins, inspect and execute individual steps or run sub-chains.
* **In-App Docs**: View full formatted documentation for any plugin.

### Tab 2: Chain Builder
* **Visual Pipeline Assembly**: Add steps from the plugin library, reorder them with Up/Down buttons, and configure baked-in step defaults.
* **Edit Existing Chains**: Select any active chain from the dropdown to modify its steps and update it live in memory.
* **Export**: Save your pipeline as a concise `.py` file or a zero-dependency standalone bundle.

### Tab 3: + Create Plugin (.py)
* **Starter Templates**: Scaffold production-ready plugins from five built-in templates:
  1. *Custom 1D Plot Tab*: Power envelope smoothing and interactive multi-trace plotting.
  2. *Streamed Batch Energy Detector*: Memory-bounded processing with safeguard margins.
  3. *Overlay Baseband Processor*: Inspects `Rect` overlays and reads `o.get_samples()`.
  4. *Native Tab Launcher*: Opens Time Domain and Constellation tabs.
  5. *Blank Custom Plugin*: Minimal clean scaffold.
* **Live Markdown Documentation Preview**: As you edit template fields and parameter tables, the real-time preview renders the exact documentation that will appear in the UI.

---

## 13. Complete Code Examples

### Example 1: Streamed Energy Detector with Margins & `o.iq` Cache

```python
"""
Streamed Energy Detector with Baseband IQ Caching
"""
from __future__ import annotations
import numpy as np
from iqview import PluginResult, PluginContext
from iqview.overlays import Rect, OverlayShape

PLUGIN_NAME                  = "Streamed Energy Detector"
PLUGIN_DESCRIPTION           = "Memory-bounded burst detector caching baseband IQ on overlays"
PLUGIN_CATEGORY              = "Detection"
PLUGIN_NEEDS_WIDEBAND_IQ     = True
PLUGIN_BATCH_SECONDS         = 1.0   # Process in 1.0 second chunks
PLUGIN_BATCH_OVERLAP_SECONDS = 0.05  # 50 ms overlap

PLUGIN_PARAMS = {
    "threshold_db": {
        "type": "float",
        "default": 12.0,
        "label": "Threshold (dB)",
        "tooltip": "Detection threshold above median noise floor",
    },
    "margin": {
        "type": "int",
        "default": 32,
        "label": "Margin (samples)",
        "tooltip": "Extra safeguard samples prepended and appended to each burst",
    },
}

def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()
    if samples is None or len(samples) == 0:
        return result

    thresh_db = float(info.params.get("threshold_db", 12.0))
    margin = max(0, int(info.params.get("margin", 32)))

    # Compute instantaneous power
    pwr = np.abs(samples) ** 2
    noise_floor = float(np.median(pwr)) + 1e-20
    thresh_linear = noise_floor * (10.0 ** (thresh_db / 10.0))

    # Detect contiguous segments above threshold
    above = pwr >= thresh_linear
    diffs = np.diff(np.concatenate([[False], above, [False]]).astype(np.int8))
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]

    for s0, s1 in zip(starts, ends):
        if (s1 - s0) < 16:
            continue  # Ignore transient spikes

        # Apply safeguard margins
        idx_start = max(0, int(s0) - margin)
        idx_end = min(len(samples), int(s1) + margin)

        t_burst_start = info.t_start + (idx_start / info.sample_rate)
        t_burst_end = info.t_start + (idx_end / info.sample_rate)

        # Create locked overlay
        rect = Rect(
            t_start=t_burst_start,
            f_start=info.f_start,
            t_end=t_burst_end,
            f_end=info.f_end,
            color="#00ff88",
            alpha=0.20,
            border_width=2,
            display_str="Burst",
            hover_str=f"SNR: {thresh_db:.1f} dB (Est)",
            locked=True,
            metadata={"snr_db": thresh_db, "margin_samples": margin},
        )

        # Cache baseband IQ directly onto overlay for downstream plugins
        rect.iq = samples[idx_start:idx_end].copy()
        rect.fs = float(info.sample_rate)

        result.add(rect)

    return result
```

---

### Example 2: Zero-Memory Overlay Processor (Peak & RMS Metrics)

```python
"""
Overlay Metrics Analyzer
"""
from __future__ import annotations
import numpy as np
from iqview import PluginResult, PluginContext
from iqview.overlays import OverlayShape

PLUGIN_NAME              = "Overlay Metrics Analyzer"
PLUGIN_DESCRIPTION       = "Calculates Peak and RMS power for all Rect overlays"
PLUGIN_CATEGORY          = "Metrics"
PLUGIN_NEEDS_WIDEBAND_IQ = False  # Zero wideband memory loading!

def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()

    for o in info.overlays:
        if o.shape != OverlayShape.RECT:
            continue

        # Zero disk read if o.iq is cached; automatic DDC if not
        burst_iq, burst_fs = o.get_samples(samples, info)
        if burst_iq is None or len(burst_iq) == 0:
            continue

        pwr = np.abs(burst_iq) ** 2
        peak_dbfs = 10.0 * np.log10(np.max(pwr) + 1e-20)
        rms_dbfs = 10.0 * np.log10(np.mean(pwr) + 1e-20)
        papr_db = peak_dbfs - rms_dbfs

        # Update metadata without overwriting existing keys
        new_meta = dict(o.metadata or {})
        new_meta.update({
            "peak_dbfs": round(float(peak_dbfs), 2),
            "rms_dbfs": round(float(rms_dbfs), 2),
            "papr_db": round(float(papr_db), 2),
        })

        hover = (
            f"{o.display_str or 'Burst'}\n"
            f"Peak: {peak_dbfs:.1f} dBFS | RMS: {rms_dbfs:.1f} dBFS | PAPR: {papr_db:.1f} dB"
        )

        result.update(o.id, metadata=new_meta, hover_str=hover)

    return result
```

---

### Example 3: Interactive 1D Plot Tab with Multi-Trace Legend & Shaded Regions

```python
"""
Filter Bank Power Inspector with 1D Plot Tab
"""
from __future__ import annotations
import numpy as np
from iqview import PluginResult, PluginContext

PLUGIN_NAME        = "Filter Bank Inspector"
PLUGIN_DESCRIPTION = "Displays smoothed power envelope with state regions"
PLUGIN_CATEGORY    = "Analysis"

PLUGIN_PARAMS = {
    "window_size": {
        "type": "int",
        "default": 64,
        "label": "Smoothing Window",
        "tooltip": "Moving-average filter length in samples",
    },
}

def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()
    if samples is None or len(samples) == 0:
        return result

    win = max(1, int(info.params.get("window_size", 64)))
    pwr = np.abs(samples) ** 2
    smoothed = np.convolve(pwr, np.ones(win) / win, mode="same")
    noise = np.full_like(smoothed, np.median(smoothed))

    t_axis = info.t_start + np.arange(len(smoothed)) / info.sample_rate

    result.set_plot_tab_title("Filter Bank — Debug")
    result.add_plot(
        title="Smoothed Power vs Noise",
        y={
            "Moving Avg Power": smoothed,
            "Median Noise Floor": noise,
        },
        x=t_axis,
        fs=info.sample_rate,
        x_label="Time",
        x_units="s",
        y_label="Linear Power",
        primary_mode="TIME",
        regions=[
            {"x_start": info.t_start, "x_end": info.t_start + 0.010, "color": "#888888", "alpha": 0.20, "label": "SYNC"},
            {"x_start": info.t_start + 0.010, "x_end": info.t_end, "color": "#00aaff", "alpha": 0.15, "label": "DATA"},
        ]
    )
    return result
```

---

## 14. Best Practices & Performance Guidelines

1. **Keep `run()` GUI-Free**: Never import `PyQt6.QtWidgets` or manipulate GUI widgets inside `run()`. The function runs on a background thread; manipulating UI elements directly will cause segfaults. Always use `PluginResult` to communicate with the GUI.
2. **Use `PLUGIN_NEEDS_WIDEBAND_IQ = False`**: If your plugin performs demodulation, metrics, or classification on existing overlays, set this flag to `False` and call `o.get_samples(samples, info)`. This eliminates multi-gigabyte memory allocations for wideband recordings.
3. **Stream Large Files with `PLUGIN_BATCH_SECONDS`**: For full-file energy detectors, set `PLUGIN_BATCH_SECONDS = 1.0` or use `info.iter_batches()`. This bounds memory consumption to small constant buffers regardless of file size.
4. **Cooperative Cancellation**: Check `if info.is_cancelled(): break` inside long loops to ensure the application remains immediately responsive when the user clicks Cancel.
5. **Lock Overlays by Default**: Ensure new overlays have `locked=True`. Users can still select, inspect, and delete them, but locking prevents accidental shifts during panning and zooming.
6. **Preserve Metadata**: When updating an overlay, merge into `dict(o.metadata or {})` rather than overwriting the entire dictionary so upstream data from earlier plugins is preserved.
7. **Document with Markdown**: Write complete `PLUGIN_DOC` strings with tables and parameter descriptions. This empowers users to understand your plugin directly within the UI without reading Python source code.

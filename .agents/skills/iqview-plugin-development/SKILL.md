---
name: iqview-plugin-development
description: >-
  ALWAYS load and read this skill before writing, modifying, debugging, or testing any
  plugin code, PluginManagerMixin, Plugin Studio, toolbar Quick Run, PluginChain pipelines,
  PluginContext, PluginResult, parameter schemas (PLUGIN_PARAMS), in-app Markdown (PLUGIN_DOC),
  overlay creation, baseband IQ caching (o.iq), cooperative thread cancellation, or batch iteration.
---

# IQView Plugin Development Skill

This skill guides the design, implementation, debugging, and testing of IQView plugins and `PluginChain` pipelines.

For complete parameter schema definitions and API details:
- [Plugin API & Parameter Schema Reference](./references/plugin_api_reference.md)
- [Starter Plugin Template](./examples/template_energy_detector.py)

---

## 1. Plugin Anatomy & Lifecycle

An IQView plugin is a standard Python `.py` file implementing a top-level `run(samples, info)` function accompanied by module-level declarations:

```python
from __future__ import annotations
import numpy as np
from iqview import PluginResult, PluginContext
from iqview.overlays import Rect

# --- Module Metadata ---
PLUGIN_NAME                  = "Adaptive Energy Detector"
PLUGIN_DESCRIPTION           = "Detects bursts exceeding noise floor by SNR threshold"
PLUGIN_CATEGORY              = "Detection"   # Detection, Demodulation, Metrics, Chains, Custom
PLUGIN_NEEDS_WIDEBAND_IQ     = True          # False if only reading overlays
PLUGIN_BATCH_SECONDS         = 1.0           # Time-chunk duration for large files (or None)
PLUGIN_BATCH_OVERLAP_SECONDS = 0.05          # Overlap between consecutive chunks
PLUGIN_RUN_ON_MAIN_THREAD    = False         # True ONLY for interactive matplotlib.show() debugging

# --- In-App Markdown Documentation ---
PLUGIN_DOC = """# Adaptive Energy Detector

Detects contiguous energy bursts in the active execution scope.

### Parameters
- **threshold_db**: Minimum SNR in dB above median noise floor.
- **min_duration_ms**: Minimum burst width to keep.
"""

# --- Parameter Schema ---
PLUGIN_PARAMS = {
    "threshold_db": {
        "type": "float",
        "default": 12.0,
        "label": "Threshold (dB)",
        "tooltip": "Power threshold above estimated background noise floor",
    },
    "min_duration_ms": {
        "type": "float",
        "default": 1.0,
        "label": "Min Duration (ms)",
        "tooltip": "Discard bursts shorter than this duration",
    },
}

# --- Entry Point ---
def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()
    threshold = float(info.params.get("threshold_db", 12.0))
    fs = info.sample_rate

    # Cooperative cancellation loop
    steps = 100
    for step in range(steps):
        if info.is_cancelled():
            break
        info.progress((step + 1) / steps * 100.0, f"Scanning step {step + 1}/{steps}...")

    return result
```

---

## 2. Cancellation & Threading Rules

> [!CRITICAL]
> 1. `PluginCancelledError` inherits from `BaseException`.
> 2. **Never** catch `BaseException` or use bare `except:` inside a plugin. Catching `BaseException` swallows the cancellation signal and leaves the worker thread permanently hung.
> 3. Periodically poll `info.is_cancelled()` inside heavy computational loops. If `True`, terminate processing promptly and return `result`.

---

## 3. Large File Processing & Memory Safety

1. **Avoid Wideband Buffer Exhaustion**:
   - If the plugin only operates on existing overlays (e.g. measuring occupied bandwidth or demodulating bursts), set `PLUGIN_NEEDS_WIDEBAND_IQ = False`.
2. **Chunking Long Recordings**:
   - Declare `PLUGIN_BATCH_SECONDS = 2.0` (and `PLUGIN_BATCH_OVERLAP_SECONDS`).
   - The plugin runner automatically executes `run()` on consecutive batches, or the plugin can iterate manually using `info.iter_batches()`.

---

## 4. Overlay API & Baseband IQ Attachment

### 4.1 Overlay Classes ([`iqview/overlays/`](file:///d:/Projects/IQView/iqview/overlays/__init__.py))
- `Rect(t_start, t_end, f_min, f_max, label="...", color="#00ff00", locked=True)`
- `Polygon([(t1, f1), (t2, f2), (t3, f3)], label="...")`
- `Ellipse(t_center, f_center, r_t, r_f, label="...")`
- `XRegion(t_start, t_end, label="...")`
- `YRegion(f_min, f_max, label="...")`
- `Line(t1, f1, t2, f2, label="...")`
- `HLine(f, label="...")`

### 4.2 Attaching Per-Burst Baseband IQ (`o.iq`, `o.fs`)
Burst detection plugins can attach zero-overhead baseband IQ slices directly to overlays:
```python
rect = Rect(t_start, t_end, f_min, f_max, label="Burst")
rect.iq = baseband_samples   # Complex numpy array
rect.fs = burst_sample_rate  # Effective sample rate
result.add_overlay(rect)
```
Downstream plugins can read the cached samples via `o.get_samples()` with zero disk I/O. If `o.iq` is absent, `o.get_samples()` automatically performs lazy Digital Down-Conversion (DDC) from the parent capture file.

---

## 5. Custom 1D Plot Tabs & Analysis Launchers

### 5.1 Adding Sub-Plot Tabs ([`PluginPlotView`](file:///d:/Projects/IQView/iqview/ui/plugin_plot_view.py))
Plugins can present rich 1D analysis plots (e.g., correlation profiles, eye curves, bitstreams):
```python
tab = result.add_plot_tab("Correlation Profile", x_label="Time (ms)", y_label="Magnitude")
tab.add_curve(t_ms, corr_mag, label="Matched Filter", color="#0072BD")
tab.add_x_region(t_sync_start, t_sync_end, label="Preamble Sync", color="#3300FF00")
```

### 5.2 Opening Native Tabs
Plugins can programmatically open native IQView tabs for specific bursts:
```python
info.launch_tab("scatter", samples=burst_iq, rate=burst_fs, title="Demod Constellation")
```
Supported types: `"time"`, `"freq"`, `"eye"`, `"scatter"`.

---

## 6. Testing & Debugging Workflow

1. **Python Breakpoint Debugging**:
   Launch IQView with the plugin pre-loaded:
   ```bash
   python -c "import iqview; iqview.view('iqview_testdata/bursts_10Msps_100MHz.32fc')"
   ```
2. **Main Thread Debugging**:
   Set `PLUGIN_RUN_ON_MAIN_THREAD = True` to use `matplotlib.pyplot.show()` or `pdb.set_trace()` directly inside `run()`.
3. **Verify Against Built-in Corpus**:
   - Energy detection: test on `iqview_testdata/bursts_10Msps_100MHz.32fc`.
   - FSK / LoRa: test on `iqview_testdata/fm_1Msps_0Hz.32fc`.
   - Constellation / Scatter: test on `iqview_testdata/qpsk_2Msps_915MHz.32fc`.

# IQView Plugin API & Parameter Schema Reference

This document provides the complete API specification for authoring IQView plugins and plugin chains.

---

## 1. Top-Level Entry Point

Every plugin must expose:
```python
def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    ...
```
- `samples`: A `complex64` NumPy array containing IQ samples of the selected execution scope.
  - If `PLUGIN_NEEDS_WIDEBAND_IQ = False`, `samples` is an empty array (`np.empty(0, dtype=np.complex64)`), saving memory.
  - If `PLUGIN_BATCH_SECONDS` is set, `samples` contains the chunk for each batch iteration.
- `info`: An instance of [`PluginContext`](file:///d:/Projects/IQView/iqview/plugins/context.py).
- Return: An instance of [`PluginResult`](file:///d:/Projects/IQView/iqview/plugins/plugin_result.py).

---

## 2. Module Constants

| Constant | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `PLUGIN_NAME` | `str` | Filename | Display name in menus, toolbars, and Plugin Studio. |
| `PLUGIN_DESCRIPTION` | `str` | `""` | One-line tooltip summary. |
| `PLUGIN_CATEGORY` | `str` | `"Custom"` | Grouping (`"Detection"`, `"Demodulation"`, `"Metrics"`, `"Chains"`). |
| `PLUGIN_DOC` | `str` | `""` | In-app documentation formatted in GitHub-flavored Markdown. |
| `PLUGIN_PARAMS` | `dict` | `{}` | Parameter specification schema. |
| `PLUGIN_NEEDS_WIDEBAND_IQ` | `bool` | `True` | Set `False` if plugin only reads existing overlays or calls `o.get_samples()`. |
| `PLUGIN_BATCH_SECONDS` | `float \| None` | `None` | Automatically chunks long files into batches of this duration. |
| `PLUGIN_BATCH_OVERLAP_SECONDS` | `float` | `0.0` | Overlap duration between consecutive batches. |
| `PLUGIN_RUN_ON_MAIN_THREAD` | `bool` | `False` | Forces execution on the Qt main GUI thread for interactive debugging (`matplotlib.show()`). |

---

## 3. Dynamic Parameter Schema (`PLUGIN_PARAMS`)

Parameters are rendered dynamically in the UI and automatically persisted across sessions:

```python
PLUGIN_PARAMS = {
    "param_key": {
        "type": "float",          # "float", "int", "bool", "str", "choice"
        "default": 10.0,
        "label": "Threshold (dB)",
        "tooltip": "Threshold description",
        # Optional validation bounds:
        "min": 0.0,
        "max": 100.0,
        # For "choice":
        "choices": ["Hanning", "Hamming", "Blackman"],
    }
}
```

---

## 4. `PluginContext` API

- `info.params`: Dictionary of configured parameters (e.g. `info.params.get("threshold_db", 10.0)`).
- `info.sample_rate` / `info.fs`: Sample rate of capture ($f_s$).
- `info.center_frequency` / `info.fc`: Center frequency ($f_c$).
- `info.norm_db`: Calibrated power normalization in dB.
- `info.time_range`: Tuple `(t_start, t_end)` of active execution scope.
- `info.freq_range`: Tuple `(f_min, f_max)` of active execution scope.
- `info.overlays`: List of existing overlays currently on the spectrogram.
- `info.progress(pct: float, message: str)`: Emits progress percentage (0..100) and status string to the modal dialog.
- `info.is_cancelled() -> bool`: Returns `True` if user clicked Cancel.
- `info.iter_batches(duration_s, overlap_s)`: Generator yielding `(batch_samples, batch_t0, batch_t1)` slices.
- `info.extract_iq(t_start, t_end) -> np.ndarray`: Slices calibrated baseband IQ from disk.
- `info.launch_tab(view_type, samples, rate, title)`: Opens native tabs (`"time"`, `"freq"`, `"eye"`, `"scatter"`).

---

## 5. `PluginResult` API

- `result.add_overlay(shape)`: Schedules a newly created overlay for display.
- `result.update_overlay(shape)`: Updates an existing overlay.
- `result.remove_overlay(shape)`: Deletes a plugin-generated overlay.
- `result.add_plot_tab(title, x_label, y_label) -> PluginPlotView`: Spawns a custom 1D subplot tab.
- `result.message = "Summary string"`: Status message shown to user.
- `result.error = "Error string"`: Halts pipeline with an error notification.

---

## 6. Overlays API & Baseband IQ Caching

```python
from iqview.overlays import Rect, Polygon, Ellipse, Line, XRegion, YRegion

rect = Rect(t_start, t_end, f_min, f_max, label="Burst", color="#00ff00", locked=True)

# Attach cached baseband IQ slice:
rect.iq = burst_iq_samples   # Complex numpy array
rect.fs = burst_sample_rate  # Effective sample rate
result.add_overlay(rect)
```

Downstream plugins access cached samples via `o.get_samples()`.
If `o.iq` is present, it returns cached samples immediately without disk I/O.
If `o.iq` is absent, it performs lazy DDC from the parent capture file.

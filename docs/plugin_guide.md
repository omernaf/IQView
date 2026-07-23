# IQView Plugin Development Guide

IQView features a lightweight, robust Python plugin system that allows you to natively process IQ samples and dynamically add, edit, or remove visual overlays on the spectrogram.

Plugins run on an isolated background thread, meaning you can perform computationally expensive DSP operations (like large FFTs or machine learning inference) without freezing the application UI.

---

## 1. The Anatomy of a Plugin

An IQView plugin is a standard `.py` file that exposes a top-level `run` function. When the user clicks the plugin in the IQView UI, the current view's data is extracted and passed to this function.

`run()` must return a **`PluginResult`** object — this is how you tell IQView what to do with overlays. Import it from the top-level `iqview` package:

```python
from iqview import PluginResult
```

### Minimal Example

The simplest possible plugin (`mark_view.py`) draws a green rectangle exactly bounding the current spectrogram view:

```python
import numpy as np
from iqview import PluginResult
from iqview.overlays import Rect

PLUGIN_NAME        = "mark_view"
PLUGIN_DESCRIPTION = "Draw a rectangle around the current view"

def run(samples: np.ndarray, info: dict) -> PluginResult:
    overlay = Rect(
        t_start=info["t_start"],
        f_start=info["f_start"],
        t_end=info["t_end"],
        f_end=info["f_end"],
        color="#004400",
        alpha=0.08,
        border_width=2,
        border_color="#00cc00",
        border_style="dash",
        display_str="View region",
        locked=True
    )
    return PluginResult().add(overlay)
```

---

## 2. The `info` Dictionary

When `run(samples, info)` is invoked, `info` is populated with context about the exact state of the IQView application at that moment.

| Key | Type | Description |
| :--- | :--- | :--- |
| `sample_rate` | `float` | The global sampling rate of the loaded file in Hz. |
| `center_freq` | `float` | The global center frequency of the loaded file in Hz. |
| `t_start` | `float` | The *left* edge of the visible spectrogram (time in seconds). |
| `t_end` | `float` | The *right* edge of the visible spectrogram (time in seconds). |
| `f_start` | `float` | The *bottom* edge of the visible spectrogram (frequency in Hz). |
| `f_end` | `float` | The *top* edge of the visible spectrogram (frequency in Hz). |
| `overlays` | `list[Overlay]` | Deep-copied snapshot of all overlays currently on screen. Read their attributes (`.id`, `.shape`, `.points`, `.color`, …) freely — changes to these copies do not affect the live state. Pass `.id` values to `PluginResult` methods to act on the real overlays. |

> **Note on `samples`:**
> The `samples` array is a `complex64` NumPy array containing *only* the IQ data that falls between `t_start` and `t_end`. If the user is zoomed in to a tiny 1-millisecond window, `samples` will only contain 1 ms worth of data.

> **Note on `info["overlays"]`:**
> These are real `Overlay` objects (not dictionaries), so you access their data as Python attributes — `o.id`, `o.shape`, `o.points`, `o.color`, etc. No import is required to read them. They are deep copies made before the background thread starts, so they are always safe to inspect without locking.

---

## 3. The Object-Oriented Overlay API

IQView provides a dedicated `iqview.overlays` module containing strictly-typed Python classes. You only need to import these when *creating* new overlays to add.

### Available Overlay Types

```python
from iqview.overlays import (
    Rect,           # Rect(t_start, f_start, t_end, f_end)
    Polygon,        # Polygon(vertices=[(t, f), ...])
    Ellipse,        # Ellipse(t_center, f_center, t_radius, f_radius)
    VerticalLine,   # VerticalLine(t)
    HorizontalLine, # HorizontalLine(f)
    TimeRegion,     # TimeRegion(t_start, t_end)
    FreqRegion,     # FreqRegion(f_start, f_end)
    OverlayShape,   # Enum for comparing o.shape
)
```

### Common Style Parameters

Every overlay accepts the same set of keyword arguments:

```python
Rect(
    t_start=1.0, f_start=1000, t_end=2.0, f_end=2000,  # geometry

    # Styling
    color="#ff00aa",        # Base colour (hex RGB/RGBA)
    alpha=0.5,              # Fill opacity (0.0–1.0)
    border_width=2,         # Border line width in pixels
    border_color="#ffffff", # Border colour (defaults to `color` if empty)
    border_style="dash",    # "solid", "dash", "dot", or "dashdot"

    # Annotation
    display_str="Label",    # Text permanently pinned to the shape
    hover_str="Details",    # Tooltip shown on mouse-hover
    tag_pos="top-right",    # "center", "top-left", "bottom-right", …

    # State
    visible=True,           # Whether the shape is drawn
    locked=False,           # If True, the user cannot drag or resize it
    z_order=9,              # Stacking order (higher = on top)

    # Custom data
    metadata={"snr": 15.2}  # Arbitrary dict, preserved in JSON export
)
```

---

## 4. PluginResult — The Return Type

All plugins must return a `PluginResult` object. It supports four operations that can be freely mixed and chained:

```python
from iqview import PluginResult

result = PluginResult()
result.add(new_overlay)                   # add a new overlay
result.update(overlay_id, color="#f00")  # patch fields on an existing overlay
result.remove(overlay_id)                # delete an overlay you own
result.replace(overlay_id, new_overlay)  # atomic swap

# Methods return self, so you can chain:
result = PluginResult().add(r1).add(r2).update(some_id, color="#ff0000")
```

### Import rules at a glance

| What you want to do | Import |
| :--- | :--- |
| Use `PluginResult` | `from iqview import PluginResult` |
| Create a new overlay to add | `from iqview.overlays import Rect, VerticalLine, …` |
| Compare `o.shape` against a type | `from iqview.overlays import OverlayShape` |
| Read `o.id`, `o.points`, `o.color`, … | **No import needed** |

### Operation details

#### `.add(overlay)`
Adds a new overlay. IQView assigns it a fresh UUID and sets `source` to `"plugin:<name>"`.  
Running a plugin twice appends more overlays without collisions.

#### `.update(overlay_id, **fields)`
Patches any fields on an existing overlay found by `overlay_id`.  
Works on overlays of any source (user-drawn, other plugins, etc.).  
Can also change `source` — do this intentionally, since setting `source` away from `"user"` excludes the overlay from sidecar auto-saves.

#### `.remove(overlay_id)`
Removes an existing overlay **only if it is owned by this plugin** (`source == "plugin:<name>"`).  
Attempting to remove a user-drawn or other-plugin-owned overlay is silently skipped with a console message.

#### `.replace(overlay_id, new_overlay)`
Atomically removes the old overlay and inserts `new_overlay`.  
The replacement inherits the original's `source` (provenance is preserved).

---

## 5. Editing Existing Overlays

This is the most powerful feature of `PluginResult`. Because `info["overlays"]` contains live overlay objects (deep-copied), you can loop over them, inspect their geometry, and use their `.id` to request changes.

### Example: Snap to Grid

```python
import numpy as np
from iqview import PluginResult
from iqview.overlays import OverlayShape

PLUGIN_NAME        = "Snap to Grid"
PLUGIN_DESCRIPTION = "Snap all RECT overlay time-edges to the nearest 0.1 s grid"

GRID_STEP_SECONDS = 0.1

def run(samples: np.ndarray, info: dict) -> PluginResult:
    result = PluginResult()

    for o in info["overlays"]:            # o is an Overlay object — no import needed
        if o.shape != OverlayShape.RECT:  # compare using the OverlayShape enum
            continue

        (t0, f0), (t1, f1) = o.points[0], o.points[1]

        t0_snapped = round(t0 / GRID_STEP_SECONDS) * GRID_STEP_SECONDS
        t1_snapped = round(t1 / GRID_STEP_SECONDS) * GRID_STEP_SECONDS

        result.update(o.id, points=[(t0_snapped, f0), (t1_snapped, f1)])

    return result
```

> **Note:** This plugin touches overlays of *any* source — user-drawn, or added by another plugin. `update()` is unrestricted. Only `remove()` is source-restricted.

### Example: Recolour your own plugin's overlays

```python
from iqview import PluginResult

PLUGIN_NAME = "Recolour Bursts"

def run(samples, info):
    result = PluginResult()
    for o in info["overlays"]:
        if o.source == "plugin:mark_bursts":
            result.update(o.id, color="#ffaa00", border_width=3)
    return result
```

### Example: Remove stale detections then re-run

```python
from iqview import PluginResult
from iqview.overlays import VerticalLine

PLUGIN_NAME = "Fresh Bursts"

def run(samples, info):
    result = PluginResult()

    # Remove any old results from THIS plugin before adding fresh ones
    for o in info["overlays"]:
        if o.source == "plugin:Fresh Bursts":
            result.remove(o.id)   # only works because source matches

    # ... detect bursts and add new VerticalLine overlays ...
    result.add(VerticalLine(t=1.23, color="#00ff88", display_str="Burst"))

    return result
```

---

## 6. Workflow Best Practices

### Threading & UI Safety
Your `run` function executes in a background `QThread`.  
**Do not import PyQt or manipulate GUI elements directly from inside your plugin.**  
IQView handles the asynchronous hand-off; just compute and return a `PluginResult`.

### Handling Large Data
If the user runs your plugin while fully zoomed out on a large file, `samples` could be massive. Guard against this at the top:

```python
def run(samples: np.ndarray, info: dict) -> PluginResult:
    if len(samples) > 50_000_000:
        return PluginResult()   # bail out gracefully
```

### Storing Metadata
The `metadata` attribute is preserved in JSON exports:

```python
result.add(Rect(
    t_start=1.0, f_start=1000, t_end=2.0, f_end=2000,
    metadata={
        "confidence": 0.98,
        "classifier": "resnet-50",
        "power_db": 42.1
    }
))
```

---

## 7. Custom Configuration Parameters

IQView supports dynamic configuration parameters for plugins. By defining a module-level `PLUGIN_PARAMS` dictionary, you can expose parameters that the user can configure interactively in the GUI before running the plugin.

### Exposing Parameters

Expose parameters by defining the `PLUGIN_PARAMS` dictionary at the top level of your plugin. Each key in the dictionary is the parameter ID, and its value is a dictionary specifying the parameter's properties:

* `type`: The parameter type, which can be `"float"`, `"int"`, `"bool"`, or `"str"`.
* `default`: The default value for the parameter.
* `label`: The human-readable label displayed in the GUI form.
* `tooltip`: (Optional) Helpful text shown when the user hovers over the input field in the GUI.

#### Example Specification
```python
PLUGIN_PARAMS = {
    "threshold_db": {
        "type": "float",
        "default": 15.0,
        "label": "Threshold SNR (dB)",
        "tooltip": "Power threshold in dB above the background noise floor"
    },
    "nfft": {
        "type": "int",
        "default": 512,
        "label": "FFT Size",
        "tooltip": "FFT size for spectrogram calculation"
    },
    "verbose": {
        "type": "bool",
        "default": True,
        "label": "Verbose Logs"
    }
}
```

### Accessing Parameters in `run()`

When the plugin is executed, the user-configured values are passed inside the `info` context dictionary under the `"params"` key. You should read them with safe fallback defaults (such as your module-level constants) to ensure backward compatibility:

```python
def run(samples: np.ndarray, info: dict) -> PluginResult:
    # Extract user-configured parameters from the GUI context
    params = info.get("params", {})
    threshold_db = params.get("threshold_db", 15.0)
    nfft = int(params.get("nfft", 512))
    
    # ... perform DSP calculations using these parameters ...
```

---

## 8. Advanced Example: Detect Bursts

```python
import numpy as np
from iqview import PluginResult
from iqview.overlays import VerticalLine

PLUGIN_NAME = "mark_bursts"

def run(samples: np.ndarray, info: dict) -> PluginResult:
    if samples is None or len(samples) < 100:
        return PluginResult()

    sample_rate = info["sample_rate"]
    t_start     = info["t_start"]

    block_size = min(100, len(samples) // 10)
    mag        = np.abs(samples)

    num_blocks  = len(mag) // block_size
    mag_blocks  = mag[:num_blocks * block_size].reshape(-1, block_size)
    energy_env  = np.mean(mag_blocks, axis=1)

    threshold = np.median(energy_env) * 1.5
    is_burst  = energy_env > threshold

    edges  = np.diff(is_burst.astype(int))
    starts = np.where(edges == 1)[0]
    ends   = np.where(edges == -1)[0]

    result = PluginResult()

    for idx_start, idx_end in zip(starts, ends):
        burst_t_start = t_start + (idx_start * block_size / sample_rate)
        burst_t_end   = t_start + (idx_end   * block_size / sample_rate)

        result.add(VerticalLine(t=burst_t_start, color="#00ff88", display_str="Start"))
        result.add(VerticalLine(t=burst_t_end,   color="#ff3355", display_str="End"))

    return result
```

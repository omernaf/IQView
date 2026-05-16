# IQView Plugin Development Guide

IQView features a lightweight, robust Python plugin system that allows you to natively process IQ samples and dynamically add custom visual overlays to the spectrogram.

Plugins run on an isolated background thread, meaning you can perform computationally expensive DSP operations (like large FFTs or machine learning inference) without freezing the application UI.

This guide will walk you through the plugin architecture, the `run` API, and the new Object-Oriented Overlay system.

---

## 1. The Anatomy of a Plugin

An IQView plugin is simply a standard `.py` file that exposes a top-level `run` function. When the user clicks the plugin in the IQView UI, the current view's data is extracted and passed to this function.

### Minimal Example

Here is the simplest possible plugin (`mark_view.py`). It simply draws a green rectangle exactly bounding the current spectrogram view:

```python
import numpy as np
from iqview.overlays import Rect

# Optional: These constants define how your plugin appears in the IQView Menu.
PLUGIN_NAME        = "mark_view"
PLUGIN_DESCRIPTION = "Draw a rectangle around the current view"

def run(samples: np.ndarray, info: dict) -> list:
    """
    The entry point for the plugin.
    
    Parameters
    ----------
    samples : np.ndarray (complex64)
        The raw IQ samples corresponding exactly to the visible time window.
    info : dict
        Metadata regarding the current spectrogram view extents and parameters.

    Returns
    -------
    list
        A list of Overlay objects to be rendered onto the spectrogram.
    """
    
    # Create a single Rectangle Overlay object
    overlay = Rect(
        t_start=info["t_start"],
        f_start=info["f_start"],
        t_end=info["t_end"],
        f_end=info["f_end"],
        color="#004400",       # Dark green
        alpha=0.08,            # 8% opacity
        border_width=2,
        border_color="#00cc00",
        border_style="dash",
        display_str="View region",
        locked=True            # Lock it so the user can't accidentally move it
    )

    # Yield the overlays back to IQView
    return [overlay]
```

---

## 2. The `info` Dictionary

When `run(samples, info)` is invoked, `info` is populated with context about the exact state of the IQView application at that exact moment.

| Key | Type | Description |
| :--- | :--- | :--- |
| `sample_rate` | `float` | The global sampling rate of the loaded file in Hz. |
| `center_freq` | `float` | The global center frequency of the loaded file in Hz. |
| `t_start` | `float` | The *left* edge of the visible spectrogram (time in seconds). |
| `t_end` | `float` | The *right* edge of the visible spectrogram (time in seconds). |
| `f_start` | `float` | The *bottom* edge of the visible spectrogram (frequency in Hz). |
| `f_end` | `float` | The *top* edge of the visible spectrogram (frequency in Hz). |
| `overlays` | `list[dict]` | A serialized list of all overlays *currently* on the screen. Useful if your plugin needs to analyze or react to existing user annotations. |

> **Note on `samples`:**
> The `samples` array is a `complex64` NumPy array containing *only* the IQ data that falls between `t_start` and `t_end`. If the user is zoomed in to a tiny 1-millisecond window, `samples` will only contain 1 ms worth of data. This guarantees that your plugin only processes what the user is currently looking at.

---

## 3. The Object-Oriented Overlay API

IQView provides a dedicated `iqview.overlays` module containing strictly-typed Python classes. These classes allow you to easily spawn shapes and annotations on the spectrogram.

### Available Overlay Types

You can import any of the following from `iqview.overlays`:

- `Rect(t_start, f_start, t_end, f_end)`: A standard bounding box.
- `Polygon(vertices=[(t, f), ...])`: A multi-point polygon (requires at least 3 vertices).
- `Ellipse(t_center, f_center, t_radius, f_radius)`: An ellipse or circle.
- `VerticalLine(t)`: An infinite vertical line spanning all frequencies at time `t`.
- `HorizontalLine(f)`: An infinite horizontal line spanning all time at frequency `f`.
- `TimeRegion(t_start, t_end)`: An infinite vertical band.
- `FreqRegion(f_start, f_end)`: An infinite horizontal band.

### Common Parameters

Every overlay object shares a robust set of keyword parameters that allow you to heavily customize its appearance and interaction model:

```python
VerticalLine(
    t=1.52,                    # Geometry (varies by shape)
    
    # Styling
    color="#ff00aa",           # Base color (Hex RGB/RGBA)
    alpha=0.5,                 # Fill opacity (0.0 to 1.0)
    border_width=2,            # Pixel width of the border
    border_color="#ffffff",    # Hex color for the border. Defaults to `color` if empty.
    border_style="dash",       # "solid", "dash", "dot", or "dashdot"
    
    # Annotation
    display_str="Burst",       # Text permanently pinned to the shape
    hover_str="Burst details", # Tooltip shown when the mouse hovers over the shape
    tag_pos="top-right",       # "center", "top-left", "bottom-right", etc.
    
    # State
    visible=True,              # Drawn on the screen
    locked=False,              # If True, the user cannot move/drag it
    z_order=9,                 # Stacking order (higher numbers render on top)
    
    # Metadata
    metadata={"snr": 15.2}     # Arbitrary hidden dictionary for your own use
)
```

---

## 4. Workflow Best Practices

### Threading & UI Safety
Your `run` function executes in a background `QThread`.
**Do not attempt to import PyQt or manipulate GUI elements directly from inside your plugin.**
IQView handles the asynchronous hand-off perfectly; just compute your mathematics and return your Python list of Overlays. IQView will safely map them into the UI thread.

### Non-Destructive Addition
IQView automatically assigns a UUID to every overlay your plugin returns. If a user runs your plugin twice, the new overlays will simply stack on top of the old ones. They will not crash or conflict.

### Handling Large Data
If the user executes your plugin while fully zoomed out on a 50GB file, `samples` could be massive.
Always implement a sanity check at the top of your plugin if you do expensive algorithms:
```python
def run(samples: np.ndarray, info: dict) -> list:
    if len(samples) > 50_000_000:
        # Avoid out-of-memory or freezing the background thread forever
        return []
```

### Storing Meta-Information
The `metadata` attribute in the Overlays is extremely powerful. When a user exports their overlays to a JSON file via the IQView UI, all `metadata` is preserved. You can use this to embed calculation artifacts (like SNR, peak amplitude, classification confidence) right into the visual tags.

```python
overlays.append(Rect(
    t_start=1.0, f_start=1000, t_end=2.0, f_end=2000,
    metadata={
        "confidence": 0.98,
        "classifier": "resnet-50",
        "power_db": 42.1
    }
))
```

---

## 5. Advanced Example: Detect Bursts

Here is a slightly more advanced plugin that computes a rolling amplitude envelope and draws vertical lines around energy bursts:

```python
import numpy as np
from iqview.overlays import VerticalLine

PLUGIN_NAME = "mark_bursts"

def run(samples: np.ndarray, info: dict) -> list:
    if samples is None or len(samples) < 100:
        return []

    sample_rate = info["sample_rate"]
    t_start     = info["t_start"]
    
    # Downsample and compute energy using a fast rolling mean block
    block_size = min(100, len(samples) // 10)
    mag = np.abs(samples)
    
    num_blocks = len(mag) // block_size
    mag_blocks = mag[:num_blocks * block_size].reshape(-1, block_size)
    energy_env = np.mean(mag_blocks, axis=1)

    # Detect regions 50% above the median energy
    threshold = np.median(energy_env) * 1.5
    is_burst = energy_env > threshold
    
    # Find rising (1) and falling (-1) edges
    edges = np.diff(is_burst.astype(int))
    starts = np.where(edges == 1)[0]
    ends   = np.where(edges == -1)[0]
    
    # Match edge pairs to form intervals
    burst_intervals = list(zip(starts, ends))
    
    overlays = []
    
    for (idx_start, idx_end) in burst_intervals:
        # Convert indices back to real-world time (seconds)
        burst_t_start = t_start + (idx_start * block_size / sample_rate)
        burst_t_end   = t_start + (idx_end   * block_size / sample_rate)
        
        # Add a green line for the start
        overlays.append(VerticalLine(
            t=burst_t_start,
            color="#00ff88",
            display_str="Start"
        ))
        
        # Add a red line for the end
        overlays.append(VerticalLine(
            t=burst_t_end,
            color="#ff3355",
            display_str="End"
        ))

    return overlays
```

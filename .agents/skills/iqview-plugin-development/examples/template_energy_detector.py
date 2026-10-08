"""Template Energy Detector Plugin for IQView.

Demonstrates:
- Dynamic PLUGIN_PARAMS schema
- Cooperative cancellation loop
- In-app PLUGIN_DOC Markdown documentation
- Creating Rect overlays with cached baseband IQ (o.iq, o.fs)
"""

from __future__ import annotations
import numpy as np
from iqview import PluginContext, PluginResult
from iqview.overlays import Rect

# --- Module Metadata ---
PLUGIN_NAME                  = "Template Energy Detector"
PLUGIN_DESCRIPTION           = "Detects signal bursts using an adaptive power threshold"
PLUGIN_CATEGORY              = "Detection"
PLUGIN_NEEDS_WIDEBAND_IQ     = True
PLUGIN_BATCH_SECONDS         = 1.0
PLUGIN_BATCH_OVERLAP_SECONDS = 0.05
PLUGIN_RUN_ON_MAIN_THREAD    = False

# --- In-App Documentation ---
PLUGIN_DOC = """# Template Energy Detector

Detects bursts exceeding the background noise floor by a user-defined threshold.

### Algorithm
1. Computes instantaneous power $|x[n]|^2$.
2. Estimates median noise floor power.
3. Groups contiguous samples above `threshold_db` into bursts.
4. Attaches baseband IQ slices to output overlays for zero-cost downstream processing.
"""

# --- Parameter Schema ---
PLUGIN_PARAMS = {
    "threshold_db": {
        "type": "float",
        "default": 10.0,
        "label": "Threshold (dB)",
        "tooltip": "Power threshold in dB above the background noise floor",
        "min": 1.0,
        "max": 60.0,
    },
    "min_duration_ms": {
        "type": "float",
        "default": 1.0,
        "label": "Min Duration (ms)",
        "tooltip": "Ignore bursts shorter than this duration",
        "min": 0.1,
    },
}


def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()
    if samples is None or len(samples) == 0:
        return result

    fs = info.sample_rate
    t_start, t_end = info.time_range
    f_min, f_max = info.freq_range

    threshold_db = float(info.params.get("threshold_db", 10.0))
    min_dur_s = float(info.params.get("min_duration_ms", 1.0)) / 1000.0

    # 1. Compute power and noise floor
    power = np.abs(samples) ** 2
    noise_floor = np.median(power)
    thresh_linear = noise_floor * (10.0 ** (threshold_db / 10.0))

    # 2. Binary mask and contiguous segment detection
    above = power > thresh_linear
    diff = np.diff(above.astype(np.int8))
    starts = np.where(diff == 1)[0] + 1
    ends = np.where(diff == -1)[0] + 1

    if above[0]:
        starts = np.insert(starts, 0, 0)
    if above[-1]:
        ends = np.append(ends, len(samples))

    burst_count = 0
    total = len(starts)

    for i in range(total):
        # Check cooperative cancellation
        if info.is_cancelled():
            break

        s_idx, e_idx = starts[i], ends[i]
        dur = (e_idx - s_idx) / fs
        if dur < min_dur_s:
            continue

        burst_t0 = t_start + s_idx / fs
        burst_t1 = t_start + e_idx / fs

        # Create overlay with attached baseband IQ slice
        rect = Rect(
            burst_t0, burst_t1, f_min, f_max,
            label=f"Burst {burst_count + 1}",
            color="#00ff00",
            locked=True
        )
        rect.iq = samples[s_idx:e_idx].copy()
        rect.fs = fs
        result.add_overlay(rect)
        burst_count += 1

        info.progress((i + 1) / total * 100.0, f"Detected {burst_count} bursts...")

    result.message = f"Found {burst_count} bursts."
    return result

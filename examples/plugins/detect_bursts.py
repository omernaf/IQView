"""detect_bursts.py — IQView example plugin

Detects high-energy bursts in the current time-domain view and highlights
each burst by drawing start and end vertical lines (VLINE).

Usage
-----
In IQView: Plugins → Load Plugin… → select this file → Plugins → ▶ mark_bursts

What it does
------------
1. Calculates the amplitude magnitude of the IQ samples.
2. Applies a rolling average window to find the signal envelope.
3. Identifies continuous regions (bursts) that exceed a median power threshold.
4. Draws two VLINE overlays marking the beginning (green) and end (red) of the burst.
"""

from __future__ import annotations
import numpy as np

# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------
PLUGIN_NAME        = "mark_bursts"
PLUGIN_DESCRIPTION = "Draws vertical lines marking start and end of energy bursts"


# ---------------------------------------------------------------------------
# Tuning parameters
# ---------------------------------------------------------------------------
THRESHOLD_MULTIPLIER = 1.5    # Burst must be 3x the median energy level
MIN_BURST_DURATION   = 0.001  # Minimum burst length in seconds
MAX_OVERLAYS         = 30     # Maximum number of polygons to draw

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(samples: np.ndarray, info: dict) -> list[dict]:
    if samples is None or len(samples) < 100:
        return []

    sample_rate = info["sample_rate"]
    t_start     = info["t_start"]
    f_start     = info["f_start"]
    f_end       = info["f_end"]
    
    # Range of the visible view so we can scale our diamonds appropriately
    view_bw_hz = f_end - f_start

    # 1. Calculate the smoothed amplitude envelope (energy)
    # Using a fast rolling mean block of ~100 samples
    block_size = min(100, len(samples) // 10)
    mag        = np.abs(samples)
    
    # We use reshape trick for a fast rolling average downsample
    # (truncate samples so it divides cleanly by block_size)
    num_blocks = len(mag) // block_size
    mag_blocks = mag[:num_blocks * block_size].reshape(-1, block_size)
    energy_env = np.mean(mag_blocks, axis=1)

    # 2. Find burst regions (consecutive blocks above threshold)
    median_energy = np.median(energy_env)
    threshold     = median_energy * THRESHOLD_MULTIPLIER
    
    # Boolean array where True means we are inside a burst
    is_burst = energy_env > threshold
    
    # Find edges: +1 means rising edge (start), -1 means falling edge (end)
    edges = np.diff(is_burst.astype(int))
    starts = np.where(edges == 1)[0]
    ends   = np.where(edges == -1)[0]
    
    # Handle the boundary cases (burst starts before view or ends after view)
    if is_burst[0]:
        starts = np.insert(starts, 0, 0)
    if is_burst[-1]:
        ends = np.append(ends, len(is_burst) - 1)
        
    # Zip together the block indices
    burst_intervals = list(zip(starts, ends))
    
    overlays = []
    
    # 3. For each burst, create a polygon
    for (idx_start, idx_end) in burst_intervals[:MAX_OVERLAYS]:
        burst_duration = (idx_end - idx_start) * block_size / sample_rate
        if burst_duration < MIN_BURST_DURATION:
            continue
            
        # Calculate time (in seconds world-coordinates relative to the file start)
        burst_t_start = t_start + (idx_start * block_size / sample_rate)
        burst_t_end   = t_start + (idx_end   * block_size / sample_rate)
        burst_t_mid   = (burst_t_start + burst_t_end) / 2.0
        
        # 1. Start Line (Green)
        overlays.append({
            "shape":        "VLINE",
            "points":       [[burst_t_start, 0.0]],
            "center":       None,
            "radii":        None,
            "color":        "#00ff88",    # Bright green
            "alpha":        1.0, 
            "border_width": 2,
            "border_color": "#00ff88",
            "border_style": "dash",
            "display_str":  f"Burst Start",
            "hover_str":    f"Burst START\nDuration: {burst_duration*1000:.1f} ms",
            "tag_pos":      "top",
            "visible":      True,
            "locked":       False,
            "z_order":      10,
            "source":       "plugin:mark_bursts",
            "metadata":     {"burst_duration_sec": burst_duration, "type": "start"},
        })
        
        # 2. End Line (Red)
        overlays.append({
            "shape":        "VLINE",
            "points":       [[burst_t_end, 0.0]],
            "center":       None,
            "radii":        None,
            "color":        "#ff3355",    # Bright red
            "alpha":        1.0, 
            "border_width": 2,
            "border_color": "#ff3355",
            "border_style": "dash",
            "display_str":  f"Burst End",
            "hover_str":    f"Burst END\nDuration: {burst_duration*1000:.1f} ms",
            "tag_pos":      "bottom",
            "visible":      True,
            "locked":       False,
            "z_order":      10,
            "source":       "plugin:mark_bursts",
            "metadata":     {"burst_duration_sec": burst_duration, "type": "end"},
        })

    return overlays

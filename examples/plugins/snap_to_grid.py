"""snap_to_grid.py — IQView example plugin

Demonstrates overlay *editing* using PluginResult.update().

Reads all RECT overlays currently on the spectrogram and snaps their
time-axis edges (t_start and t_end) to the nearest multiple of
GRID_STEP_SECONDS.  Frequency edges are left unchanged.

This plugin does NOT add any new overlays — it only mutates the geometry
of overlays that already exist.

Usage
-----
In IQView: Plugins → Load Plugin… → select this file → Plugins → ▶ Snap to Grid

Tip: draw a few rectangle overlays manually, then run this plugin to see
     their left/right edges snap to the grid.
"""

from __future__ import annotations

import numpy as np

from iqview import PluginResult
from iqview.overlays import OverlayShape

# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

PLUGIN_NAME        = "Snap to Grid"
PLUGIN_DESCRIPTION = "Snap all RECT overlay time-edges to the nearest grid step"

# ---------------------------------------------------------------------------
# Tuning parameters (edit as needed)
# ---------------------------------------------------------------------------

GRID_STEP_SECONDS = 0.1   # time grid resolution in seconds


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(samples: np.ndarray, info: dict) -> PluginResult:
    """
    Parameters
    ----------
    samples : np.ndarray (complex64)
        IQ samples for the current view — not used in this plugin.
    info : dict
        Keys: sample_rate, center_freq, t_start, t_end, f_start, f_end,
              overlays (list[Overlay] — deep-copied, read-only snapshot).

    Returns
    -------
    PluginResult
        Contains .update() calls that snap each RECT overlay's time-axis
        edges to the nearest GRID_STEP_SECONDS boundary.
    """
    result = PluginResult()

    for o in info["overlays"]:
        # Only snap rectangular overlays — skip lines, regions, polygons, etc.
        if o.shape != OverlayShape.RECT:
            continue

        if len(o.points) < 2:
            continue

        (t0, f0), (t1, f1) = o.points[0], o.points[1]

        # Snap only the time (x) axis; leave frequency (y) untouched
        t0_snapped = round(t0 / GRID_STEP_SECONDS) * GRID_STEP_SECONDS
        t1_snapped = round(t1 / GRID_STEP_SECONDS) * GRID_STEP_SECONDS

        # Skip if nothing actually changed (already on the grid)
        if t0_snapped == t0 and t1_snapped == t1:
            continue

        result.update(o.id, points=[(t0_snapped, f0), (t1_snapped, f1)])

    return result

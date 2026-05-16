"""mark_view.py — IQView minimal example plugin

The simplest possible plugin: draws a rectangle overlay that exactly covers
the currently visible time × frequency region.

Use this as a copy-paste starting template.
"""

import numpy as np

PLUGIN_NAME        = "mark_view"
PLUGIN_DESCRIPTION = "Draw a rectangle around the current view"


from iqview.overlays import Rect

def run(samples: np.ndarray, info: dict) -> list:
    """
    Parameters
    ----------
    samples : np.ndarray (complex64)
        IQ samples for the current view — not used in this example.
    info : dict
        sample_rate, center_freq, t_start, t_end, f_start, f_end, overlays

    Returns
    -------
    list  — one Rect overlay covering the current view.
    """
    return [
        Rect(
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
            hover_str=(
                f"t: {info['t_start']:.4f}s – {info['t_end']:.4f}s  \n  "
                f"f: {info['f_start']/1e6:.3f} – {info['f_end']/1e6:.3f} MHz"
            ),
            tag_pos="top-left",
            locked=True,   # lock it so it can't be accidentally moved
            z_order=5
        )
    ]

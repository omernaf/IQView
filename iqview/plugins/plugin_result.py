"""iqview/plugins/plugin_result.py

PluginResult — the return type for all IQView plugin run() functions.

Plugin authors import this from the top-level package:

    from iqview import PluginResult

Operations
----------
.add(overlay)              — queue a new overlay to be added to the spectrogram.
.update(id, **fields)      — patch fields on an existing overlay by its id.
.remove(id)                — remove an existing overlay by its id.
                             Restricted to overlays owned by this plugin
                             (source == "plugin:<name>").  Attempting to remove
                             a user- or other-plugin-owned overlay is silently
                             skipped with a console warning.
.replace(id, new_overlay)  — atomically swap an overlay out; the replacement
                             inherits the original overlay's source.

All four methods return self so calls can be chained:

    result = PluginResult().add(r1).add(r2).update(some_id, color="#ff0000")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from iqview.ui.overlay import Overlay


class PluginResult:
    """
    Encapsulates the set of overlay operations that a plugin wishes to perform.

    Returned by a plugin's ``run(samples, info)`` function.  IQView's plugin
    runner processes each operation list in order:
      1. removes
      2. replaces
      3. updates
      4. adds

    Attributes
    ----------
    _adds           : list[Overlay]
    _updates        : list[tuple[str, dict]]   — (overlay_id, field_kwargs)
    _removes        : list[str]                — overlay IDs
    _replaces       : list[tuple[str, Overlay]]— (old_overlay_id, new_overlay)
    _plots          : list[dict]               — custom 1D sub-plot specifications
    _plot_tab_title : str | None               — optional custom tab title for PluginPlotView
    _native_tabs    : list[dict]               — requests to open native analysis tabs
    _logs           : list[str]                — status/console log messages
    """

    def __init__(self) -> None:
        self._adds:           List[Any]                    = []
        self._updates:        List[Tuple[str, Dict]]       = []
        self._removes:        List[str]                    = []
        self._replaces:       List[Tuple[str, Any]]        = []
        self._plots:          List[Dict[str, Any]]         = []
        self._plot_tab_title: Optional[str]                = None
        self._native_tabs:    List[Dict[str, Any]]         = []
        self._logs:           List[str]                    = []

    # ------------------------------------------------------------------
    # Builder methods (all return self for chaining)
    # ------------------------------------------------------------------

    def add(self, overlay) -> "PluginResult":
        """
        Queue *overlay* to be added as a new overlay on the spectrogram.

        The runner will assign a fresh UUID and set ``source`` to the
        plugin's name before adding, so IDs returned by ``info["overlays"]``
        are never re-used.

        Parameters
        ----------
        overlay : Overlay
            Any overlay object from ``iqview.overlays`` (Rect, VerticalLine, …).
        """
        self._adds.append(overlay)
        return self

    def update(self, overlay_id: Any, **fields) -> "PluginResult":
        """
        Queue a partial update of an existing overlay identified by *overlay_id*
        (or pass an ``Overlay`` instance directly).

        Any keyword argument that matches an ``Overlay`` field name will be
        applied via ``setattr``.  If an ``Overlay`` object is passed as the
        first argument with no keyword arguments, its mutable fields are
        automatically extracted as the update payload.
        """
        if not isinstance(overlay_id, str) and hasattr(overlay_id, "id"):
            ov = overlay_id
            overlay_id = str(ov.id)
            if not fields:
                for attr in (
                    "shape", "points", "center", "radii", "color", "alpha",
                    "border_width", "border_color", "border_style",
                    "display_str", "hover_str", "tag_pos", "visible",
                    "locked", "z_order", "metadata", "iq", "fs",
                ):
                    if hasattr(ov, attr):
                        fields[attr] = getattr(ov, attr)
        self._updates.append((str(overlay_id), fields))
        return self

    def remove(self, overlay_id: Any) -> "PluginResult":
        """
        Queue removal of an overlay by *overlay_id* (or ``Overlay`` instance).
        """
        if not isinstance(overlay_id, str) and hasattr(overlay_id, "id"):
            overlay_id = str(overlay_id.id)
        self._removes.append(str(overlay_id))
        return self

    def replace(self, overlay_id: Any, new_overlay) -> "PluginResult":
        """
        Queue an atomic swap: remove *overlay_id* (or ``Overlay`` instance)
        and add *new_overlay* in its place.
        """
        if not isinstance(overlay_id, str) and hasattr(overlay_id, "id"):
            overlay_id = str(overlay_id.id)
        self._replaces.append((str(overlay_id), new_overlay))
        return self

    # ------------------------------------------------------------------
    # Custom 1D Plot Tab & Native Analysis Tab Launchers (Phase 2)
    # ------------------------------------------------------------------

    def add_plot(
        self,
        title: str,
        y: Any,
        x: Any = None,
        fs: Optional[float] = None,
        x_label: str = "Time",
        x_units: str = "s",
        y_label: str = "Amplitude",
        primary_mode: str = "TIME",
        regions: Optional[List[Dict[str, Any]]] = None,
    ) -> "PluginResult":
        """
        Add a custom 1D sub-plot to this plugin's interactive ``PluginPlotView`` tab.

        All ``add_plot()`` calls in a plugin run are grouped into **a single main tab**
        with ``F1..F10`` sub-tab mode buttons in its toolbar (just like ``TimeDomainView``).

        Parameters
        ----------
        title : str
            Name of the sub-plot (shown on the toolbar mode button).
        y : array-like or dict[str, array-like]
            1D data array/sequence, OR a dictionary mapping trace names to 1D arrays
            (e.g. ``{"Moving Avg": fir, "IIR Floor": iir}``) for multi-trace plotting
            with a legend and active-trace selector.
        x : array-like, optional
            Explicit 1D X-axis coordinates. If omitted, derived automatically from
            ``fs`` (if provided) or sample index ``0..N-1``.
        fs : float, optional
            Sample rate in Hz used to construct the X-axis when ``x`` is omitted,
            and for sample/time conversions and oversampling in the marker panel.
        x_label : str, default "Time"
            Label for the bottom X-axis.
        x_units : str, default "s"
            Units for the bottom X-axis.
        y_label : str, default "Amplitude"
            Label for the left Y-axis.
        primary_mode : str, default "TIME"
            Primary marker mode: ``"TIME"`` or ``"FREQ"``.
        regions : list[dict], optional
            List of background shaded X-region dicts, e.g.
            ``[{"x_start": 0.0, "x_end": 0.1, "color": "#888888", "alpha": 0.18, "label": "INIT"}]``.
        """
        import numpy as np

        if isinstance(y, dict):
            y_clean: Any = {}
            for k, v in y.items():
                arr = np.asarray(v)
                if np.iscomplexobj(arr):
                    arr = np.real(arr)
                y_clean[str(k)] = np.asarray(arr, dtype=np.float64).ravel()
        else:
            arr = np.asarray(y)
            if np.iscomplexobj(arr):
                arr = np.real(arr)
            y_clean = np.asarray(arr, dtype=np.float64).ravel()

        x_clean = np.asarray(x, dtype=np.float64).ravel() if x is not None else None
        mode_norm = "FREQ" if str(primary_mode).upper().startswith("FREQ") else "TIME"

        self._plots.append({
            "title": str(title),
            "y": y_clean,
            "x": x_clean,
            "fs": float(fs) if fs is not None else None,
            "x_label": str(x_label),
            "x_units": str(x_units),
            "y_label": str(y_label),
            "primary_mode": mode_norm,
            "regions": list(regions) if regions else [],
        })
        return self

    def set_plot_tab_title(self, title: str) -> "PluginResult":
        """Set a custom main tab title for the ``PluginPlotView`` created by this run."""
        self._plot_tab_title = str(title) if title else None
        return self

    def open_time_domain(
        self,
        samples: Any,
        fs: float,
        t_start: float = 0.0,
        title: Optional[str] = None,
    ) -> "PluginResult":
        """Queue opening a native ``TimeDomainView`` tab with ``samples`` at rate ``fs``."""
        import numpy as np
        self._native_tabs.append({
            "type": "time_domain",
            "samples": np.asarray(samples).ravel(),
            "fs": float(fs),
            "t_start": float(t_start),
            "title": str(title) if title else None,
        })
        return self

    def open_freq_domain(
        self,
        samples: Any,
        fs: float,
        fc: float = 0.0,
        title: Optional[str] = None,
    ) -> "PluginResult":
        """Queue opening a native ``FrequencyDomainView`` tab with ``samples`` at rate ``fs``."""
        import numpy as np
        self._native_tabs.append({
            "type": "freq_domain",
            "samples": np.asarray(samples).ravel(),
            "fs": float(fs),
            "fc": float(fc),
            "title": str(title) if title else None,
        })
        return self

    open_frequency_domain = open_freq_domain

    def open_constellation(
        self,
        samples: Any,
        fs: float,
        title: Optional[str] = None,
    ) -> "PluginResult":
        """Queue opening a native ``ConstellationView`` (Scatter Plot) tab."""
        import numpy as np
        self._native_tabs.append({
            "type": "constellation",
            "samples": np.asarray(samples).ravel(),
            "fs": float(fs),
            "title": str(title) if title else None,
        })
        return self

    open_scatter = open_constellation

    def open_eye_diagram(
        self,
        samples: Any,
        fs: float,
        title: Optional[str] = None,
    ) -> "PluginResult":
        """Queue opening a native ``EyeDiagramView`` tab."""
        import numpy as np
        self._native_tabs.append({
            "type": "eye_diagram",
            "samples": np.asarray(samples).ravel(),
            "fs": float(fs),
            "title": str(title) if title else None,
        })
        return self

    def log(self, message: str) -> "PluginResult":
        """Queue a status/console log message to be displayed when the plugin finishes."""
        self._logs.append(str(message))
        return self

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"PluginResult("
            f"adds={len(self._adds)}, "
            f"updates={len(self._updates)}, "
            f"removes={len(self._removes)}, "
            f"replaces={len(self._replaces)}, "
            f"plots={len(self._plots)}, "
            f"native_tabs={len(self._native_tabs)}, "
            f"logs={len(self._logs)})"
        )


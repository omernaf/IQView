"""
Public Plugin API for IQView Overlays.

This module provides developer-friendly classes for creating overlays from within plugins.
Each class wraps the internal `Overlay` dataclass, ensuring plugins can yield correctly
formatted overlays without manually managing internal dictionaries or enums.
"""

from typing import List, Tuple, Optional, Dict, Any
from iqview.ui.overlay import Overlay, OverlayShape

__all__ = [
    "Rect",
    "Polygon",
    "Ellipse",
    "VerticalLine",
    "HorizontalLine",
    "TimeRegion",
    "FreqRegion"
]

class Rect(Overlay):
    """
    A rectangular overlay spanning specific time and frequency bounds.
    """
    def __init__(self,
                 t_start: float,
                 f_start: float,
                 t_end: float,
                 f_end: float,
                 color: str = "#00aaff",
                 alpha: float = 0.25,
                 border_width: int = 2,
                 border_color: str = "",
                 border_style: str = "solid",
                 display_str: str = "",
                 hover_str: str = "",
                 tag_pos: str = "center",
                 visible: bool = True,
                 locked: bool = False,
                 z_order: int = 8,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Parameters
        ----------
        t_start : float
            Start time in seconds.
        f_start : float
            Start frequency in Hz.
        t_end : float
            End time in seconds.
        f_end : float
            End frequency in Hz.
        color : str, optional
            Hex colour string for fill and border (default "#00aaff").
        alpha : float, optional
            Fill opacity from 0.0 to 1.0 (default 0.25).
        border_width : int, optional
            Width of the border line in pixels (default 2).
        border_color : str, optional
            Hex colour string for the border. If empty, uses `color` (default "").
        border_style : str, optional
            Line style: "solid", "dash", "dot", "dashdot" (default "solid").
        display_str : str, optional
            Text label permanently drawn on the overlay (default "").
        hover_str : str, optional
            Tooltip text shown when the mouse hovers over the overlay (default "").
        tag_pos : str, optional
            Position of the text label: "center", "top-left", "top-right", "bottom-left", "bottom-right" (default "center").
        visible : bool, optional
            Whether the overlay is drawn (default True).
        locked : bool, optional
            If True, the user cannot move or resize this overlay via the UI (default False).
        z_order : int, optional
            Stacking order for rendering. Higher numbers render on top (default 8).
        metadata : dict, optional
            Arbitrary key-value store for plugin use.
        """
        super().__init__(
            shape=OverlayShape.RECT,
            points=[(t_start, f_start), (t_end, f_end)],
            color=color, alpha=alpha, border_width=border_width,
            border_color=border_color, border_style=border_style,
            display_str=display_str, hover_str=hover_str, tag_pos=tag_pos,
            visible=visible, locked=locked, z_order=z_order,
            source="plugin", metadata=metadata or {}
        )


class Polygon(Overlay):
    """
    A polygonal overlay defined by a series of vertices.
    Requires at least 3 vertices. The shape is automatically closed.
    """
    def __init__(self,
                 vertices: List[Tuple[float, float]],
                 color: str = "#00aaff",
                 alpha: float = 0.25,
                 border_width: int = 2,
                 border_color: str = "",
                 border_style: str = "solid",
                 display_str: str = "",
                 hover_str: str = "",
                 tag_pos: str = "center",
                 visible: bool = True,
                 locked: bool = False,
                 z_order: int = 8,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Parameters
        ----------
        vertices : List[Tuple[float, float]]
            List of (time, frequency) tuples. Must contain at least 3 points.
        """
        super().__init__(
            shape=OverlayShape.POLYGON,
            points=vertices,
            color=color, alpha=alpha, border_width=border_width,
            border_color=border_color, border_style=border_style,
            display_str=display_str, hover_str=hover_str, tag_pos=tag_pos,
            visible=visible, locked=locked, z_order=z_order,
            source="plugin", metadata=metadata or {}
        )


class Ellipse(Overlay):
    """
    An elliptical overlay defined by a center point and radii.
    """
    def __init__(self,
                 t_center: float,
                 f_center: float,
                 t_radius: float,
                 f_radius: float,
                 color: str = "#00aaff",
                 alpha: float = 0.25,
                 border_width: int = 2,
                 border_color: str = "",
                 border_style: str = "solid",
                 display_str: str = "",
                 hover_str: str = "",
                 tag_pos: str = "center",
                 visible: bool = True,
                 locked: bool = False,
                 z_order: int = 8,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Parameters
        ----------
        t_center : float
            Center time in seconds.
        f_center : float
            Center frequency in Hz.
        t_radius : float
            Radius along the time axis in seconds.
        f_radius : float
            Radius along the frequency axis in Hz.
        """
        super().__init__(
            shape=OverlayShape.ELLIPSE,
            center=(t_center, f_center),
            radii=(t_radius, f_radius),
            color=color, alpha=alpha, border_width=border_width,
            border_color=border_color, border_style=border_style,
            display_str=display_str, hover_str=hover_str, tag_pos=tag_pos,
            visible=visible, locked=locked, z_order=z_order,
            source="plugin", metadata=metadata or {}
        )


class VerticalLine(Overlay):
    """
    An infinite vertical line spanning the entire frequency range at a specific time.
    """
    def __init__(self,
                 t: float,
                 color: str = "#ff00aa",
                 alpha: float = 0.0,
                 border_width: int = 2,
                 border_style: str = "solid",
                 display_str: str = "",
                 hover_str: str = "",
                 tag_pos: str = "top-right",
                 visible: bool = True,
                 locked: bool = False,
                 z_order: int = 9,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Parameters
        ----------
        t : float
            Time in seconds.
        """
        super().__init__(
            shape=OverlayShape.LINE,
            points=[(t, 0.0)],
            color=color, alpha=alpha, border_width=border_width,
            border_color=color, border_style=border_style,
            display_str=display_str, hover_str=hover_str, tag_pos=tag_pos,
            visible=visible, locked=locked, z_order=z_order,
            source="plugin", metadata=metadata or {}
        )


class HorizontalLine(Overlay):
    """
    An infinite horizontal line spanning the entire time range at a specific frequency.
    """
    def __init__(self,
                 f: float,
                 color: str = "#ff00aa",
                 alpha: float = 0.0,
                 border_width: int = 2,
                 border_style: str = "solid",
                 display_str: str = "",
                 hover_str: str = "",
                 tag_pos: str = "top-right",
                 visible: bool = True,
                 locked: bool = False,
                 z_order: int = 9,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Parameters
        ----------
        f : float
            Frequency in Hz.
        """
        super().__init__(
            shape=OverlayShape.HLINE,
            points=[(0.0, f)],
            color=color, alpha=alpha, border_width=border_width,
            border_color=color, border_style=border_style,
            display_str=display_str, hover_str=hover_str, tag_pos=tag_pos,
            visible=visible, locked=locked, z_order=z_order,
            source="plugin", metadata=metadata or {}
        )


class TimeRegion(Overlay):
    """
    An infinite vertical band spanning the entire frequency range between two time points.
    """
    def __init__(self,
                 t_start: float,
                 t_end: float,
                 color: str = "#00aaff",
                 alpha: float = 0.25,
                 border_width: int = 2,
                 border_color: str = "",
                 border_style: str = "solid",
                 display_str: str = "",
                 hover_str: str = "",
                 tag_pos: str = "center",
                 visible: bool = True,
                 locked: bool = False,
                 z_order: int = 8,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Parameters
        ----------
        t_start : float
            Start time in seconds.
        t_end : float
            End time in seconds.
        """
        super().__init__(
            shape=OverlayShape.X_REGION,
            points=[(t_start, 0.0), (t_end, 0.0)],
            color=color, alpha=alpha, border_width=border_width,
            border_color=border_color, border_style=border_style,
            display_str=display_str, hover_str=hover_str, tag_pos=tag_pos,
            visible=visible, locked=locked, z_order=z_order,
            source="plugin", metadata=metadata or {}
        )


class FreqRegion(Overlay):
    """
    An infinite horizontal band spanning the entire time range between two frequencies.
    """
    def __init__(self,
                 f_start: float,
                 f_end: float,
                 color: str = "#00aaff",
                 alpha: float = 0.25,
                 border_width: int = 2,
                 border_color: str = "",
                 border_style: str = "solid",
                 display_str: str = "",
                 hover_str: str = "",
                 tag_pos: str = "center",
                 visible: bool = True,
                 locked: bool = False,
                 z_order: int = 8,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Parameters
        ----------
        f_start : float
            Start frequency in Hz.
        f_end : float
            End frequency in Hz.
        """
        super().__init__(
            shape=OverlayShape.Y_REGION,
            points=[(0.0, f_start), (0.0, f_end)],
            color=color, alpha=alpha, border_width=border_width,
            border_color=border_color, border_style=border_style,
            display_str=display_str, hover_str=hover_str, tag_pos=tag_pos,
            visible=visible, locked=locked, z_order=z_order,
            source="plugin", metadata=metadata or {}
        )

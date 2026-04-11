"""iqview/ui/overlay.py

Core data model and custom pyqtgraph GraphicsObject for the Overlay feature.

Overlays are transparent, annotated shapes rendered in world-space (time × freq)
on top of the spectrogram.  LINE / HLINE shapes are handled via pg.InfiniteLine
in the OverlayManagerMixin; this module covers RECT, POLYGON, CIRCLE, ELLIPSE.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import pyqtgraph as pg
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import QGraphicsItem


# ---------------------------------------------------------------------------
# Shape enum
# ---------------------------------------------------------------------------

class OverlayShape(Enum):
    RECT    = "RECT"
    POLYGON = "POLYGON"
    CIRCLE  = "CIRCLE"   # equal radius in data coords (rt == rf by convention)
    ELLIPSE = "ELLIPSE"  # separate time-radius and freq-radius
    LINE    = "LINE"     # vertical infinite line (time axis)
    HLINE   = "HLINE"   # horizontal infinite line (frequency axis)


# Map from border_style string to Qt pen style
_BORDER_STYLE_MAP = {
    "solid":   Qt.PenStyle.SolidLine,
    "dash":    Qt.PenStyle.DashLine,
    "dot":     Qt.PenStyle.DotLine,
    "dashdot": Qt.PenStyle.DashDotLine,
}

# Human-readable labels used in the UI
SHAPE_LABELS: Dict[str, OverlayShape] = {
    "Rectangle":       OverlayShape.RECT,
    "Polygon":         OverlayShape.POLYGON,
    "Circle":          OverlayShape.CIRCLE,
    "Ellipse":         OverlayShape.ELLIPSE,
    "Vertical Line":   OverlayShape.LINE,
    "Horizontal Line": OverlayShape.HLINE,
}

TAG_POSITIONS = ["center", "top-left", "top-right", "bottom-left", "bottom-right"]


# ---------------------------------------------------------------------------
# Overlay dataclass
# ---------------------------------------------------------------------------

@dataclass
class Overlay:
    """
    Single overlay instance.  All geometry is expressed in world-space
    (seconds on the time axis, Hz on the frequency axis).

    Geometry conventions
    --------------------
    RECT    : points = [(t_min, f_min), (t_max, f_max)]
    POLYGON : points = [(t0, f0), (t1, f1), …]  (≥ 3 vertices, auto-closed)
    CIRCLE  : center = (t, f),  radii = (r, r)   r in Hz (appears elliptical when
              time and freq axes have different scales — this is physically correct)
    ELLIPSE : center = (t, f),  radii = (rt, rf)
    LINE    : points = [(t, 0.0)]   only x (time) matters
    HLINE   : points = [(0.0, f)]   only y (freq) matters
    """

    shape: OverlayShape = OverlayShape.RECT

    # --- Geometry ---
    points: List[Tuple[float, float]] = field(default_factory=list)
    center: Optional[Tuple[float, float]] = None
    radii:  Optional[Tuple[float, float]] = None

    # --- Style ---
    color:        str   = "#00aaff"   # fill / border base colour ('#RRGGBB')
    alpha:        float = 0.25         # fill opacity 0.0–1.0
    border_width: int   = 2
    border_color: str   = ""           # empty → uses color
    border_style: str   = "solid"      # solid | dash | dot | dashdot

    # --- Annotation ---
    display_str: str = ""              # tag shown on the overlay at all times
    hover_str:   str = ""              # tooltip text shown on mouse-hover
    tag_pos:     str = "center"        # one of TAG_POSITIONS

    # --- State / meta ---
    visible:  bool = True
    z_order:  int  = 8
    source:   str  = "user"            # 'user' or mod name (for namespacing)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Identity (auto-generated; do not set manually)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "shape":        self.shape.value,
            "points":       self.points,
            "center":       list(self.center) if self.center else None,
            "radii":        list(self.radii)  if self.radii  else None,
            "color":        self.color,
            "alpha":        self.alpha,
            "border_width": self.border_width,
            "border_color": self.border_color,
            "border_style": self.border_style,
            "display_str":  self.display_str,
            "hover_str":    self.hover_str,
            "tag_pos":      self.tag_pos,
            "visible":      self.visible,
            "z_order":      self.z_order,
            "source":       self.source,
            "metadata":     self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Overlay":
        o = cls()
        o.id           = d.get("id", str(uuid.uuid4()))
        o.shape        = OverlayShape(d.get("shape", "RECT"))
        o.points       = [tuple(p) for p in d.get("points", [])]
        raw_center     = d.get("center")
        o.center       = tuple(raw_center) if raw_center else None
        raw_radii      = d.get("radii")
        o.radii        = tuple(raw_radii)  if raw_radii  else None
        o.color        = d.get("color",        "#00aaff")
        o.alpha        = float(d.get("alpha",  0.25))
        o.border_width = int(d.get("border_width", 2))
        o.border_color = d.get("border_color", "")
        o.border_style = d.get("border_style", "solid")
        o.display_str  = d.get("display_str", "")
        o.hover_str    = d.get("hover_str",   "")
        o.tag_pos      = d.get("tag_pos",     "center")
        o.visible      = bool(d.get("visible", True))
        o.z_order      = int(d.get("z_order", 8))
        o.source       = d.get("source",    "user")
        o.metadata     = d.get("metadata",  {})
        return o

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def bounding_rect(self) -> Optional[QRectF]:
        """Bounding box in world-space; None for infinite shapes (LINE/HLINE)."""
        if self.shape == OverlayShape.RECT and len(self.points) >= 2:
            x0, y0 = self.points[0]
            x1, y1 = self.points[1]
            return QRectF(min(x0, x1), min(y0, y1),
                          abs(x1 - x0), abs(y1 - y0))

        if self.shape == OverlayShape.POLYGON and len(self.points) >= 3:
            xs = [p[0] for p in self.points]
            ys = [p[1] for p in self.points]
            return QRectF(min(xs), min(ys),
                          max(xs) - min(xs), max(ys) - min(ys))

        if (self.shape in (OverlayShape.CIRCLE, OverlayShape.ELLIPSE)
                and self.center and self.radii):
            cx, cy = self.center
            rx, ry = self.radii
            return QRectF(cx - rx, cy - ry, 2 * rx, 2 * ry)

        return None

    def tag_anchor(self) -> Optional[QPointF]:
        """World-space anchor for the display_str text (pg.TextItem position)."""
        br = self.bounding_rect()
        if br is None:
            # For LINE/HLINE the manager sets the label position separately
            return None
        cx, cy = br.center().x(), br.center().y()
        pos_map = {
            "center":       (cx, cy),
            "top-left":     (br.left(),  br.top()),
            "top-right":    (br.right(), br.top()),
            "bottom-left":  (br.left(),  br.bottom()),
            "bottom-right": (br.right(), br.bottom()),
        }
        x, y = pos_map.get(self.tag_pos, (cx, cy))
        return QPointF(x, y)


# ---------------------------------------------------------------------------
# OverlayItem — custom pg.GraphicsObject for shape overlays
# ---------------------------------------------------------------------------

class OverlayItem(pg.GraphicsObject):
    """
    Renders a single non-line Overlay (RECT, POLYGON, CIRCLE, ELLIPSE) inside a
    pyqtgraph PlotItem.  The coordinate system used by paint() is the data/world
    coordinate space of the ViewBox, so geometry is expressed in seconds × Hz.

    A companion pg.TextItem is managed externally by the OverlayManagerMixin to
    display the always-visible display_str tag at the correct world position.
    """

    def __init__(self, overlay: Overlay) -> None:
        super().__init__()
        self.overlay = overlay

        # Accept hover events for tooltip but don't eat mouse clicks
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

        if overlay.hover_str:
            self.setToolTip(overlay.hover_str)

        # Companion text label (positioned by attach_to_plot / _update_label_pos)
        self._label: Optional[pg.TextItem] = None
        self._plot_item: Optional[pg.PlotItem] = None
        self._build_label()

    # ------------------------------------------------------------------
    # Label management
    # ------------------------------------------------------------------

    def _build_label(self) -> None:
        if not self.overlay.display_str:
            self._label = None
            return
        color = QColor(self.overlay.border_color or self.overlay.color)
        self._label = pg.TextItem(
            text=self.overlay.display_str,
            color=color,
            anchor=(0.5, 0.5),
        )

    def attach_to_plot(self, plot_item: pg.PlotItem) -> None:
        """Call after adding this item to the PlotItem."""
        self._plot_item = plot_item
        if self._label is not None:
            plot_item.addItem(self._label)
            self._update_label_pos()

    def detach_from_plot(self) -> None:
        """Call before removing this item from the PlotItem."""
        if self._label is not None and self._plot_item is not None:
            try:
                self._plot_item.removeItem(self._label)
            except Exception:
                pass
        self._plot_item = None

    def _update_label_pos(self) -> None:
        if self._label is None:
            return
        anchor = self.overlay.tag_anchor()
        if anchor:
            self._label.setPos(anchor.x(), anchor.y())

    # ------------------------------------------------------------------
    # GraphicsObject interface
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        br = self.overlay.bounding_rect()
        if br is None:
            return QRectF()
        # Tiny epsilon to satisfy Qt's requirements (non-zero area)
        return br.adjusted(-1e-15, -1e-15, 1e-15, 1e-15)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        overlay = self.overlay
        painter.save()

        # --- Border pen (cosmetic → width in screen pixels) ---
        bc = QColor(overlay.border_color or overlay.color)
        pen = QPen(bc, overlay.border_width)
        pen.setCosmetic(True)
        pen.setStyle(_BORDER_STYLE_MAP.get(overlay.border_style,
                                           Qt.PenStyle.SolidLine))
        painter.setPen(pen)

        # --- Fill brush ---
        fc = QColor(overlay.color)
        fc.setAlphaF(max(0.0, min(1.0, overlay.alpha)))
        painter.setBrush(QBrush(fc))

        # --- Dispatch to shape painters ---
        {
            OverlayShape.RECT:    self._paint_rect,
            OverlayShape.POLYGON: self._paint_polygon,
            OverlayShape.CIRCLE:  self._paint_ellipse,
            OverlayShape.ELLIPSE: self._paint_ellipse,
        }.get(overlay.shape, lambda p: None)(painter)

        painter.restore()

        # Keep label in sync (called every frame; very cheap)
        self._update_label_pos()

    def _paint_rect(self, painter: QPainter) -> None:
        br = self.overlay.bounding_rect()
        if br:
            painter.drawRect(br)

    def _paint_polygon(self, painter: QPainter) -> None:
        pts = self.overlay.points
        if len(pts) < 3:
            return
        path = QPainterPath()
        path.moveTo(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)

    def _paint_ellipse(self, painter: QPainter) -> None:
        overlay = self.overlay
        if overlay.center and overlay.radii:
            cx, cy = overlay.center
            rx, ry = overlay.radii
            painter.drawEllipse(QPointF(cx, cy), rx, ry)

    # ------------------------------------------------------------------
    # Visibility
    # ------------------------------------------------------------------

    def setVisible(self, visible: bool) -> None:  # type: ignore[override]
        super().setVisible(visible)
        if self._label is not None:
            self._label.setVisible(visible)

    # ------------------------------------------------------------------
    # Live update after overlay properties change
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-sync visuals after overlay data is mutated in-place."""
        # Tooltip
        self.setToolTip(self.overlay.hover_str)

        # Label
        if self._label is not None:
            lbl_color = QColor(self.overlay.border_color or self.overlay.color)
            self._label.setText(self.overlay.display_str)
            self._label.setColor(lbl_color)
        elif self.overlay.display_str and self._plot_item:
            # Label was absent before but now we have text — build it
            self._build_label()
            if self._label:
                self._plot_item.addItem(self._label)

        self.prepareGeometryChange()
        self.update()
        self._update_label_pos()

"""iqview/ui/overlay.py

Core data model and custom pyqtgraph GraphicsObject for the Overlay feature.

Overlays are transparent, annotated shapes rendered in world-space (time × freq)
on top of the spectrogram.  LINE / HLINE shapes are handled via pg.InfiniteLine
in the OverlayManagerMixin; this module covers RECT, POLYGON, ELLIPSE.
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
    locked:   bool = False             # when True, drag/resize is disabled
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
            "locked":       self.locked,
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
        o.locked       = bool(d.get("locked",  False))
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

        if (self.shape == OverlayShape.ELLIPSE
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
# Interaction constants
# ---------------------------------------------------------------------------

HANDLE_PX = 7   # half-size of handle squares in screen pixels
HIT_PX    = 10  # hit-test radius in screen pixels


# ---------------------------------------------------------------------------
# OverlayItem — custom pg.GraphicsObject for shape overlays
# ---------------------------------------------------------------------------

class OverlayItem(pg.GraphicsObject):
    """
    Renders a single non-line Overlay (RECT, POLYGON, ELLIPSE) inside a
    pyqtgraph PlotItem.  Supports interactive drag-to-move and handle-based resize
    unless overlay.locked is True.

    Geometry is expressed in world-space (seconds × Hz).
    """

    def __init__(self, overlay: Overlay, on_geometry_changed=None) -> None:
        super().__init__()
        self.overlay = overlay
        # Callable(overlay_id, points=…, center=…, radii=…) — fired on mouse release
        self._on_geometry_changed = on_geometry_changed

        # Drag state
        self._drag_mode: Optional[str] = None   # None | 'move' | handle role
        self._drag_last: Optional[QPointF] = None
        self._hover_handle: Optional[str] = None
        self._hovered: bool = False

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self._update_interaction_flags()

        if overlay.hover_str:
            self.setToolTip(overlay.hover_str)

        self._label: Optional[pg.TextItem] = None
        self._plot_item: Optional[pg.PlotItem] = None
        self._build_label()

    # ------------------------------------------------------------------
    # Lock / interaction flags
    # ------------------------------------------------------------------

    def _update_interaction_flags(self) -> None:
        if self.overlay.locked:
            self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.unsetCursor()
        else:
            self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    # ------------------------------------------------------------------
    # View-space scale helper
    # ------------------------------------------------------------------

    def _get_scale(self):
        """Returns (sx, sy) = screen-pixels per world-unit for the current view."""
        scene = self.scene()
        if not scene:
            return 1.0, 1.0
        views = scene.views()
        if not views:
            return 1.0, 1.0
        t = views[0].transform() * self.sceneTransform()
        sx = abs(t.m11()) or 1.0
        sy = abs(t.m22()) or 1.0
        return sx, sy

    # ------------------------------------------------------------------
    # Handle geometry
    # ------------------------------------------------------------------

    def _handle_positions(self) -> list:
        """Returns [(role, QPointF world-pos), …] for all resize handles."""
        o = self.overlay
        if o.shape == OverlayShape.RECT and len(o.points) >= 2:
            x0, y0 = o.points[0]
            x1, y1 = o.points[1]
            t0, t1 = min(x0, x1), max(x0, x1)
            f0, f1 = min(y0, y1), max(y0, y1)
            tm, fm = (t0 + t1) / 2, (f0 + f1) / 2
            return [
                ('tl', QPointF(t0, f1)), ('tm', QPointF(tm, f1)), ('tr', QPointF(t1, f1)),
                ('mr', QPointF(t1, fm)),
                ('br', QPointF(t1, f0)), ('bm', QPointF(tm, f0)), ('bl', QPointF(t0, f0)),
                ('ml', QPointF(t0, fm)),
            ]
        if o.shape == OverlayShape.ELLIPSE and o.center and o.radii:
            cx, cy = o.center
            rx, ry = o.radii
            return [
                ('n', QPointF(cx,      cy + ry)),
                ('s', QPointF(cx,      cy - ry)),
                ('e', QPointF(cx + rx, cy)),
                ('w', QPointF(cx - rx, cy)),
            ]
        return []

    def _hit_handle(self, pos: QPointF) -> Optional[str]:
        """Return handle role if pos (world) is within HIT_PX of a handle."""
        sx, sy = self._get_scale()
        hx = HIT_PX / sx
        hy = HIT_PX / sy
        for role, hp in self._handle_positions():
            if abs(pos.x() - hp.x()) <= hx and abs(pos.y() - hp.y()) <= hy:
                return role
        return None

    def _inside_shape(self, pos: QPointF) -> bool:
        """Return True if pos (world) is inside the overlay shape."""
        o = self.overlay
        if o.shape == OverlayShape.RECT:
            br = o.bounding_rect()
            return br is not None and br.contains(pos)
        if o.shape == OverlayShape.POLYGON:
            pts = o.points
            if len(pts) >= 3:
                path = QPainterPath()
                path.moveTo(*pts[0])
                for p in pts[1:]:
                    path.lineTo(*p)
                path.closeSubpath()
                return path.contains(pos)
        if o.shape == OverlayShape.ELLIPSE:
            if o.center and o.radii:
                cx, cy = o.center
                rx, ry = o.radii
                if rx > 0 and ry > 0:
                    return ((pos.x() - cx) / rx) ** 2 + ((pos.y() - cy) / ry) ** 2 <= 1.0
        return False

    # ------------------------------------------------------------------
    # Geometry mutation helpers (in-place, no item recreation)
    # ------------------------------------------------------------------

    def _apply_handle_drag(self, role: str, delta: QPointF) -> None:
        o = self.overlay
        dx, dy = delta.x(), delta.y()
        if o.shape == OverlayShape.RECT and len(o.points) >= 2:
            t0, f0 = list(o.points[0])
            t1, f1 = list(o.points[1])
            if 'l' in role: t0 += dx
            if 'r' in role: t1 += dx
            if 'b' in role: f0 += dy
            if 't' in role: f1 += dy
            # Normalise to always keep min/max ordering
            o.points = [(min(t0, t1), min(f0, f1)), (max(t0, t1), max(f0, f1))]

        elif o.shape == OverlayShape.ELLIPSE:
            if o.center and o.radii:
                rx, ry = o.radii
                if role == 'n': ry = max(1e-9, ry + dy)
                if role == 's': ry = max(1e-9, ry - dy)
                if role == 'e': rx = max(1e-9, rx + dx)
                if role == 'w': rx = max(1e-9, rx - dx)
                o.radii = (rx, ry)

    def _apply_move_drag(self, delta: QPointF) -> None:
        o = self.overlay
        dx, dy = delta.x(), delta.y()
        if o.points:
            o.points = [(p[0] + dx, p[1] + dy) for p in o.points]
        if o.center:
            o.center = (o.center[0] + dx, o.center[1] + dy)

    # ------------------------------------------------------------------
    # Qt mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if self.overlay.locked:
            event.ignore()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        pos = event.pos()
        handle = self._hit_handle(pos)
        if handle:
            self._drag_mode = handle
        elif self._inside_shape(pos):
            self._drag_mode = 'move'
        else:
            event.ignore()
            return
        self._drag_last = pos
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is None or self._drag_last is None:
            event.ignore()
            return
        pos = event.pos()
        delta = pos - self._drag_last
        self._drag_last = pos
        self.prepareGeometryChange()
        if self._drag_mode == 'move':
            self._apply_move_drag(delta)
        else:
            self._apply_handle_drag(self._drag_mode, delta)
        self.update()
        self._update_label_pos()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_mode is not None and self._on_geometry_changed:
            o = self.overlay
            self._on_geometry_changed(o.id, points=o.points, center=o.center, radii=o.radii)
        self._drag_mode = None
        self._drag_last = None
        event.accept()

    # ------------------------------------------------------------------
    # Hover events — handle highlighting + cursor feedback
    # ------------------------------------------------------------------

    def hoverEnterEvent(self, event) -> None:
        if not self.overlay.locked:
            self._hovered = True
            self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self._hover_handle = None
        self.unsetCursor()
        self.update()

    def hoverMoveEvent(self, event) -> None:
        if self.overlay.locked:
            return
        pos = event.pos()
        old = self._hover_handle
        self._hovered = True
        handle = self._hit_handle(pos)
        self._hover_handle = handle
        if handle:
            diag_fwd = {'tr', 'bl'}
            diag_bwd = {'tl', 'br'}
            horz     = {'ml', 'mr', 'e', 'w'}
            vert     = {'tm', 'bm', 'n', 's'}
            if handle in diag_fwd:
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif handle in diag_bwd:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif handle in horz:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif handle in vert:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif self._inside_shape(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()
        if old != handle:
            self.update()

    # ------------------------------------------------------------------
    # Label management
    # ------------------------------------------------------------------

    def _build_label(self) -> None:
        if not self.overlay.display_str:
            self._label = None
            return
        color = QColor(self.overlay.border_color or self.overlay.color)
        self._label = pg.TextItem(text=self.overlay.display_str, color=color, anchor=(0.5, 0.5))

    def attach_to_plot(self, plot_item: pg.PlotItem) -> None:
        self._plot_item = plot_item
        if self._label is not None:
            plot_item.addItem(self._label)
            self._update_label_pos()

    def detach_from_plot(self) -> None:
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
        return br.adjusted(-1e-15, -1e-15, 1e-15, 1e-15)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        overlay = self.overlay
        painter.save()

        bc = QColor(overlay.border_color or overlay.color)
        pen = QPen(bc, overlay.border_width)
        pen.setCosmetic(True)
        pen.setStyle(_BORDER_STYLE_MAP.get(overlay.border_style, Qt.PenStyle.SolidLine))
        painter.setPen(pen)

        fc = QColor(overlay.color)
        fc.setAlphaF(max(0.0, min(1.0, overlay.alpha)))
        painter.setBrush(QBrush(fc))

        {
            OverlayShape.RECT:    self._paint_rect,
            OverlayShape.POLYGON: self._paint_polygon,
            OverlayShape.ELLIPSE: self._paint_ellipse,
        }.get(overlay.shape, lambda p: None)(painter)

        # Draw resize handles when interactive and (hovered or being dragged)
        if not overlay.locked and (self._hovered or self._drag_mode):
            self._paint_handles(painter, bc)

        painter.restore()
        self._update_label_pos()

    def _paint_handles(self, painter: QPainter, border_color: QColor) -> None:
        sx, sy = self._get_scale()
        hw = HANDLE_PX / sx
        hh = HANDLE_PX / sy
        for role, pos in self._handle_positions():
            if role == self._hover_handle:
                painter.setBrush(QBrush(border_color))
            else:
                fill = QColor(255, 255, 255, 210)
                painter.setBrush(QBrush(fill))
            pen = QPen(border_color, 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(QRectF(pos.x() - hw / 2, pos.y() - hh / 2, hw, hh))

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
        o = self.overlay
        if o.center and o.radii:
            cx, cy = o.center
            rx, ry = o.radii
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
        self.setToolTip(self.overlay.hover_str)
        self._update_interaction_flags()

        if self._label is not None:
            lbl_color = QColor(self.overlay.border_color or self.overlay.color)
            self._label.setText(self.overlay.display_str)
            self._label.setColor(lbl_color)
        elif self.overlay.display_str and self._plot_item:
            self._build_label()
            if self._label:
                self._plot_item.addItem(self._label)

        self.prepareGeometryChange()
        self.update()
        self._update_label_pos()


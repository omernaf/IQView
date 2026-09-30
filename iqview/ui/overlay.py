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
    RECT     = "RECT"
    POLYGON  = "POLYGON"
    ELLIPSE  = "ELLIPSE"  # separate time-radius and freq-radius
    LINE     = "LINE"     # vertical infinite line (time axis)
    HLINE    = "HLINE"   # horizontal infinite line (frequency axis)
    X_REGION = "X_REGION"  # vertical band: full freq extent between two time bounds
    Y_REGION = "Y_REGION"  # horizontal band: full time extent between two freq bounds


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
    "X-Region (time band)":  OverlayShape.X_REGION,
    "Y-Region (freq band)":  OverlayShape.Y_REGION,
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
    X_REGION: points = [(t_start, 0.0), (t_end, 0.0)]  fills full freq range
    Y_REGION: points = [(0.0, f_start), (0.0, f_end)]  fills full time range
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

    # --- Transient per-burst IQ cache (in-memory only, excluded from JSON sidecar) ---
    iq: Optional[Any]   = field(default=None, repr=False, compare=False)
    fs: Optional[float] = field(default=None, repr=False, compare=False)

    # Identity (auto-generated; do not set manually)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Smart Geometry Properties (seconds & Hz)
    # ------------------------------------------------------------------

    @property
    def t_start(self) -> float:
        """Start time in seconds."""
        if self.shape in (OverlayShape.RECT, OverlayShape.POLYGON, OverlayShape.X_REGION) and self.points:
            return float(min(p[0] for p in self.points))
        if self.shape == OverlayShape.ELLIPSE and self.center and self.radii:
            return float(self.center[0] - abs(self.radii[0]))
        if self.shape == OverlayShape.LINE and self.points:
            return float(self.points[0][0])
        return 0.0

    @t_start.setter
    def t_start(self, val: float) -> None:
        if self.shape == OverlayShape.RECT and len(self.points) >= 2:
            self.points = [(float(val), self.f_start), (self.t_end, self.f_end)]
        elif self.shape == OverlayShape.X_REGION and len(self.points) >= 2:
            self.points = [(float(val), 0.0), (self.t_end, 0.0)]
        elif self.shape == OverlayShape.LINE:
            self.points = [(float(val), 0.0)]

    @property
    def t_end(self) -> float:
        """End time in seconds."""
        if self.shape in (OverlayShape.RECT, OverlayShape.POLYGON, OverlayShape.X_REGION) and self.points:
            return float(max(p[0] for p in self.points))
        if self.shape == OverlayShape.ELLIPSE and self.center and self.radii:
            return float(self.center[0] + abs(self.radii[0]))
        if self.shape == OverlayShape.LINE and self.points:
            return float(self.points[0][0])
        return 0.0

    @t_end.setter
    def t_end(self, val: float) -> None:
        if self.shape == OverlayShape.RECT and len(self.points) >= 2:
            self.points = [(self.t_start, self.f_start), (float(val), self.f_end)]
        elif self.shape == OverlayShape.X_REGION and len(self.points) >= 2:
            self.points = [(self.t_start, 0.0), (float(val), 0.0)]

    @property
    def t_center(self) -> float:
        """Center time in seconds."""
        if self.shape == OverlayShape.ELLIPSE and self.center:
            return float(self.center[0])
        return 0.5 * (self.t_start + self.t_end)

    @property
    def duration(self) -> float:
        """Time duration in seconds (`t_end - t_start`)."""
        return max(0.0, self.t_end - self.t_start)

    @property
    def f_start(self) -> float:
        """Lower frequency bound in Hz."""
        if self.shape in (OverlayShape.RECT, OverlayShape.POLYGON, OverlayShape.Y_REGION) and self.points:
            return float(min(p[1] for p in self.points))
        if self.shape == OverlayShape.ELLIPSE and self.center and self.radii:
            return float(self.center[1] - abs(self.radii[1]))
        if self.shape == OverlayShape.HLINE and self.points:
            return float(self.points[0][1])
        return 0.0

    @f_start.setter
    def f_start(self, val: float) -> None:
        if self.shape == OverlayShape.RECT and len(self.points) >= 2:
            self.points = [(self.t_start, float(val)), (self.t_end, self.f_end)]
        elif self.shape == OverlayShape.Y_REGION and len(self.points) >= 2:
            self.points = [(0.0, float(val)), (0.0, self.f_end)]
        elif self.shape == OverlayShape.HLINE:
            self.points = [(0.0, float(val))]

    @property
    def f_end(self) -> float:
        """Upper frequency bound in Hz."""
        if self.shape in (OverlayShape.RECT, OverlayShape.POLYGON, OverlayShape.Y_REGION) and self.points:
            return float(max(p[1] for p in self.points))
        if self.shape == OverlayShape.ELLIPSE and self.center and self.radii:
            return float(self.center[1] + abs(self.radii[1]))
        if self.shape == OverlayShape.HLINE and self.points:
            return float(self.points[0][1])
        return 0.0

    @f_end.setter
    def f_end(self, val: float) -> None:
        if self.shape == OverlayShape.RECT and len(self.points) >= 2:
            self.points = [(self.t_start, self.f_start), (self.t_end, float(val))]
        elif self.shape == OverlayShape.Y_REGION and len(self.points) >= 2:
            self.points = [(0.0, self.f_start), (0.0, float(val))]

    @property
    def f_center(self) -> float:
        """Center frequency in Hz."""
        if self.shape == OverlayShape.ELLIPSE and self.center:
            return float(self.center[1])
        return 0.5 * (self.f_start + self.f_end)

    @property
    def bandwidth(self) -> float:
        """Frequency span in Hz (`f_end - f_start`)."""
        return max(0.0, self.f_end - self.f_start)

    # ------------------------------------------------------------------
    # Per-Burst IQ Extraction & DDC
    # ------------------------------------------------------------------

    def extract_iq(
        self,
        samples: Optional[Any] = None,
        info: Optional[Any] = None,
        baseband: bool = True,
        filter_bw: bool = True,
        decimate: bool = False,
    ) -> Tuple[Any, float]:
        """
        Return ``(burst_iq, sample_rate_hz)`` for this overlay.

        1. **Cached Fast Path**: If ``self.iq`` is already attached in memory
           (e.g., from a channelizer/burst-detector plugin), returns
           ``(self.iq, self.fs)`` immediately without touching the wideband file.
        2. **On-Demand DDC Path**: Otherwise slices ``[self.t_start, self.t_end]``
           from *samples* or ``info.extract_iq()``, mixes ``self.f_center`` to
           baseband (0 Hz), low-pass filters to ``self.bandwidth``, optionally
           decimates, caches ``self.iq`` / ``self.fs``, and returns ``(iq, fs)``.
        """
        import numpy as np

        # 1. Fast path: per-burst IQ already cached on this overlay
        if self.iq is not None and len(self.iq) > 0:
            cached_iq = np.asarray(self.iq, dtype=np.complex64)
            cached_fs = float(
                self.fs
                if self.fs is not None and self.fs > 0
                else (info["sample_rate"] if info is not None and "sample_rate" in info else 1.0)
            )
            if decimate and self.bandwidth > 0 and cached_fs > self.bandwidth * 2.5:
                target_fs = max(self.bandwidth * 1.25, 1.0)
                decim = max(1, int(cached_fs // target_fs))
                if decim > 1 and len(cached_iq) > decim:
                    return cached_iq[::decim].copy(), cached_fs / decim
            return cached_iq, cached_fs

        # 2. On-demand slice & DDC from wideband samples or info.extract_iq
        fs = float(info["sample_rate"]) if (info is not None and "sample_rate" in info) else 1.0
        fc = float(info["center_freq"]) if (info is not None and "center_freq" in info) else 0.0

        t0, t1 = self.t_start, self.t_end
        if t1 <= t0:
            return np.empty(0, dtype=np.complex64), fs

        seg = None
        if samples is not None and len(samples) > 0 and info is not None and "t_start" in info:
            info_t0 = float(info["t_start"])
            s0 = max(0, int(round((t0 - info_t0) * fs)))
            s1 = min(len(samples), int(round((t1 - info_t0) * fs)))
            if s1 > s0:
                seg = np.asarray(samples[s0:s1], dtype=np.complex64).copy()

        if (seg is None or len(seg) == 0) and info is not None and hasattr(info, "extract_iq"):
            extracted = info.extract_iq(t0, t1)
            if extracted is not None and len(extracted) > 0:
                seg = np.asarray(extracted, dtype=np.complex64).copy()

        if seg is None or len(seg) == 0:
            return np.empty(0, dtype=np.complex64), fs

        # Mix f_center to baseband (0 Hz)
        has_freq_bounds = self.shape in (
            OverlayShape.RECT,
            OverlayShape.ELLIPSE,
            OverlayShape.POLYGON,
            OverlayShape.Y_REGION,
        )
        if baseband and has_freq_bounds:
            f_offset = self.f_center - fc
            if abs(f_offset) > 1e-6:
                t_vec = np.arange(len(seg), dtype=np.float64) / fs
                seg = (seg * np.exp(-2j * np.pi * f_offset * t_vec)).astype(np.complex64)

        # Low-pass filter to overlay bandwidth
        bw = self.bandwidth
        if filter_bw and has_freq_bounds and bw > 0 and bw < fs * 0.96 and len(seg) >= 18:
            try:
                from scipy.signal import butter, sosfiltfilt
                cutoff = min(bw * 0.5, fs * 0.48)
                if cutoff > 0:
                    sos = butter(5, cutoff / (0.5 * fs), btype="low", output="sos")
                    seg = sosfiltfilt(sos, seg).astype(np.complex64)
            except Exception:
                pass

        out_fs = fs
        if decimate and has_freq_bounds and bw > 0:
            target_fs = max(bw * 1.25, 1.0)
            decim = max(1, int(fs // target_fs))
            if decim > 1 and len(seg) > decim:
                seg = seg[::decim].copy()
                out_fs = fs / decim

        # Cache on overlay so subsequent uses are instant
        self.iq = seg
        self.fs = out_fs
        return seg, out_fs

    def get_samples(
        self,
        samples: Optional[Any] = None,
        info: Optional[Any] = None,
        baseband: bool = True,
        filter_bw: bool = True,
        decimate: bool = False,
    ) -> Tuple[Any, float]:
        """
        Return ``(burst_iq, sample_rate_hz)`` for this overlay.
        Uses cached ``self.iq`` if available, otherwise extracts and DDC-filters
        from *samples* or *info*. Alias for :meth:`extract_iq`.
        """
        return self.extract_iq(
            samples=samples,
            info=info,
            baseband=baseband,
            filter_bw=filter_bw,
            decimate=decimate,
        )

    # ------------------------------------------------------------------
    # Hover Tooltip Formatting (Truncated Preview)
    # ------------------------------------------------------------------

    def get_truncated_hover(
        self,
        max_line_len: int = 72,
        max_lines: int = 6,
        max_total_chars: int = 260,
    ) -> str:
        """
        Return a compact tooltip string for mouse hover, truncating long lines
        or bitstreams with ``...`` and adding a hint to right-click for the
        visual Overlay Inspector popup.
        """
        raw = (self.hover_str or "").strip()
        if not raw and not self.metadata:
            return ""

        was_truncated = False
        lines: List[str] = []

        if raw:
            raw_lines = raw.splitlines()
            if len(raw_lines) > max_lines:
                raw_lines = raw_lines[:max_lines]
                was_truncated = True
            for ln in raw_lines:
                if len(ln) > max_line_len:
                    lines.append(ln[:max_line_len] + "...")
                    was_truncated = True
                else:
                    lines.append(ln)
        elif self.metadata:
            # Build a compact preview from metadata when hover_str is empty
            items = list(self.metadata.items())
            if len(items) > 4:
                items = items[:4]
                was_truncated = True
            for k, v in items:
                val_str = str(v)
                if len(val_str) > max_line_len - len(str(k)) - 4:
                    val_str = val_str[: max(12, max_line_len - len(str(k)) - 4)] + "..."
                    was_truncated = True
                lines.append(f"{k}: {val_str}")

        preview = "\n".join(lines)
        if len(preview) > max_total_chars:
            preview = preview[:max_total_chars].rstrip() + "..."
            was_truncated = True

        if was_truncated or bool(self.metadata):
            preview += "\n(Right-click → Inspect Overlay)"
        return preview

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
        """Bounding box in world-space; None for infinite shapes (LINE/HLINE/X_REGION/Y_REGION)."""
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

        # X_REGION / Y_REGION: bounding rect cannot be determined without the
        # current view extents, so return None (the manager handles rendering).
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

    def __init__(self, overlay: Overlay, waterfall: bool = False, on_geometry_changed=None) -> None:
        super().__init__()
        self.overlay = overlay
        self.waterfall = waterfall
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

        tip = overlay.get_truncated_hover()
        if tip:
            self.setToolTip(tip)

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
    # View-space scale helper & coordinates
    # ------------------------------------------------------------------

    def _to_view(self, t: float, f: float) -> Tuple[float, float]:
        """Convert logical (time, freq) to view coordinates."""
        return (f, t) if getattr(self, 'waterfall', False) else (t, f)
        
    def _from_view(self, x: float, y: float) -> Tuple[float, float]:
        """Convert view coordinates to logical (time, freq)."""
        return (y, x) if getattr(self, 'waterfall', False) else (x, y)

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
        """Returns [(role, QPointF view-pos), …] for all resize handles."""
        o = self.overlay
        if o.shape == OverlayShape.RECT and len(o.points) >= 2:
            t0, f0 = o.points[0]
            t1, f1 = o.points[1]
            t0, t1 = min(t0, t1), max(t0, t1)
            f0, f1 = min(f0, f1), max(f0, f1)
            
            x0, y0 = self._to_view(t0, f0)
            x1, y1 = self._to_view(t1, f1)
            
            vx_min, vx_max = min(x0, x1), max(x0, x1)
            vy_min, vy_max = min(y0, y1), max(y0, y1)
            
            vx_mid = (vx_min + vx_max) / 2
            vy_mid = (vy_min + vy_max) / 2
            
            return [
                ('tl', QPointF(vx_min, vy_max)), ('tm', QPointF(vx_mid, vy_max)), ('tr', QPointF(vx_max, vy_max)),
                ('mr', QPointF(vx_max, vy_mid)),
                ('br', QPointF(vx_max, vy_min)), ('bm', QPointF(vx_mid, vy_min)), ('bl', QPointF(vx_min, vy_min)),
                ('ml', QPointF(vx_min, vy_mid)),
            ]
        if o.shape == OverlayShape.ELLIPSE and o.center and o.radii:
            ct, cf = o.center
            rt, rf = o.radii
            def pt(t, f):
                x, y = self._to_view(t, f)
                return QPointF(x, y)
            return [
                ('n', pt(ct,      cf + rf)),
                ('s', pt(ct,      cf - rf)),
                ('e', pt(ct + rt, cf)),
                ('w', pt(ct - rt, cf)),
            ]
        if o.shape == OverlayShape.POLYGON and len(o.points) >= 3:
            return [(f'p{i}', QPointF(*self._to_view(t, f))) for i, (t, f) in enumerate(o.points)]
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
        """Return True if pos (view coordinates) is inside the overlay shape."""
        logical_pos = QPointF(*self._from_view(pos.x(), pos.y()))
        
        o = self.overlay
        if o.shape == OverlayShape.RECT:
            br = o.bounding_rect()
            return br is not None and br.contains(logical_pos)
        if o.shape == OverlayShape.POLYGON:
            pts = o.points
            if len(pts) >= 3:
                path = QPainterPath()
                path.moveTo(*pts[0])
                for p in pts[1:]:
                    path.lineTo(*p)
                path.closeSubpath()
                return path.contains(logical_pos)
        if o.shape == OverlayShape.ELLIPSE:
            if o.center and o.radii:
                cx, cy = o.center
                rx, ry = o.radii
                if rx > 0 and ry > 0:
                    return ((logical_pos.x() - cx) / rx) ** 2 + ((logical_pos.y() - cy) / ry) ** 2 <= 1.0
        return False

    # ------------------------------------------------------------------
    # Geometry mutation helpers (in-place, no item recreation)
    # ------------------------------------------------------------------

    def _apply_handle_drag(self, role: str, delta: QPointF) -> None:
        o = self.overlay
        dx, dy = delta.x(), delta.y()
        
        if o.shape == OverlayShape.RECT and len(o.points) >= 2:
            x0, y0 = self._to_view(*o.points[0])
            x1, y1 = self._to_view(*o.points[1])
            if 'l' in role:
                if x0 <= x1: x0 += dx
                else: x1 += dx
            if 'r' in role:
                if x0 > x1: x0 += dx
                else: x1 += dx
            if 'b' in role:
                if y0 <= y1: y0 += dy
                else: y1 += dy
            if 't' in role:
                if y0 > y1: y0 += dy
                else: y1 += dy
            
            t_new_0, f_new_0 = self._from_view(x0, y0)
            t_new_1, f_new_1 = self._from_view(x1, y1)
            o.points = [(min(t_new_0, t_new_1), min(f_new_0, f_new_1)), (max(t_new_0, t_new_1), max(f_new_0, f_new_1))]

        elif o.shape == OverlayShape.ELLIPSE:
            if o.center and o.radii:
                rx, ry = self._to_view(*o.radii)
                rx, ry = abs(rx), abs(ry)
                if role == 'n': ry = max(1e-9, ry + dy)
                if role == 's': ry = max(1e-9, ry - dy)
                if role == 'e': rx = max(1e-9, rx + dx)
                if role == 'w': rx = max(1e-9, rx - dx)
                rt, rf = self._from_view(rx, ry)
                o.radii = (abs(rt), abs(rf))
                
        elif o.shape == OverlayShape.POLYGON and role.startswith('p'):
            try:
                idx = int(role[1:])
                if 0 <= idx < len(o.points):
                    px, py = self._to_view(*o.points[idx])
                    o.points[idx] = self._from_view(px + dx, py + dy)
            except ValueError:
                pass
        o.iq = None
        o.fs = None

    def _apply_move_drag(self, delta: QPointF) -> None:
        o = self.overlay
        dt, df = self._from_view(delta.x(), delta.y())
        if o.points:
            o.points = [(p[0] + dt, p[1] + df) for p in o.points]
        if o.center:
            o.center = (o.center[0] + dt, o.center[1] + df)
        o.iq = None
        o.fs = None

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
            elif handle.startswith('p'):
                self.setCursor(Qt.CursorShape.CrossCursor)
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
            if getattr(self, 'waterfall', False):
                self._label.setPos(anchor.y(), anchor.x())
            else:
                self._label.setPos(anchor.x(), anchor.y())

    # ------------------------------------------------------------------
    # GraphicsObject interface
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        br = self.overlay.bounding_rect()
        if br is None:
            return QRectF()
        if getattr(self, 'waterfall', False):
            return QRectF(br.y(), br.x(), br.height(), br.width()).adjusted(-1e-15, -1e-15, 1e-15, 1e-15)
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
            if getattr(self, 'waterfall', False):
                painter.drawRect(QRectF(br.y(), br.x(), br.height(), br.width()))
            else:
                painter.drawRect(br)

    def _paint_polygon(self, painter: QPainter) -> None:
        pts = self.overlay.points
        if len(pts) < 3:
            return
        path = QPainterPath()
        p0 = self._to_view(*pts[0])
        path.moveTo(p0[0], p0[1])
        for t, f in pts[1:]:
            px, py = self._to_view(t, f)
            path.lineTo(px, py)
        path.closeSubpath()
        painter.drawPath(path)

    def _paint_ellipse(self, painter: QPainter) -> None:
        o = self.overlay
        if o.center and o.radii:
            cx, cy = o.center
            rx, ry = o.radii
            if getattr(self, 'waterfall', False):
                painter.drawEllipse(QPointF(cy, cx), ry, rx)
            else:
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
        self.setToolTip(self.overlay.get_truncated_hover())
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


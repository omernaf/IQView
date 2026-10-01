from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from .themes import get_palette

class DoubleClickButton(QtWidgets.QPushButton):
    doubleClicked = pyqtSignal()
    
    def mouseDoubleClickEvent(self, a0: QtGui.QMouseEvent) -> None:
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(a0)

class FormattedLineEdit(QtWidgets.QLineEdit):
    """
    A QLineEdit that displays 3-digit grouped numbers (e.g. 1 000 000)
    but allows editing and copying the raw number.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._raw_text = super().text()
        self.editingFinished.connect(self._handle_editing_finished)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        if self._raw_text:
            super().setText(self._format_text(self._raw_text))

    def setText(self, text):
        self._raw_text = str(text)
        if not self.hasFocus():
            super().setText(self._format_text(self._raw_text))
        else:
            super().setText(self._raw_text)

    def clear(self):
        self._raw_text = ""
        super().clear()

    def text(self):
        # Return raw text. If focused, strip spaces from current display.
        if self.hasFocus():
            return super().text().replace(" ", "")
        return self._raw_text

    def _format_text(self, text):
        if not text: return ""
        try:
            MAX_CHARS = 16 
            
            # Preserve sign
            is_negative = text.startswith('-')
            abs_text = text.lstrip('-')
            
            if '.' in abs_text:
                parts = abs_text.split('.')
                # Format integer part with spaces
                int_part = "{:,}".format(int(parts[0])).replace(",", " ")
                
                # Start with sign + "int_part."
                result = ("-" if is_negative else "") + f"{int_part}."
                if len(result) >= MAX_CHARS:
                    return result.rstrip('.') 
                
                # Format fractional part with spaces every 3 digits
                frac_part = parts[1]
                for i in range(0, len(frac_part), 3):
                    chunk = frac_part[i:i+3]
                    potential_addition = (" " if i > 0 else "") + chunk
                    if len(result) + len(potential_addition) <= MAX_CHARS:
                        result += potential_addition
                    else:
                        for digit in potential_addition:
                            if len(result) + 1 <= MAX_CHARS:
                                result += digit
                            else:
                                break
                        break
                
                return result.rstrip()
            else:
                # Format integer with spaces
                int_part = "{:,}".format(int(abs_text)).replace(",", " ")
                return ("-" if is_negative else "") + int_part
        except (ValueError, TypeError):
            return text

    def _handle_editing_finished(self):
        # Update raw text when user finishes typing
        self._raw_text = super().text().replace(" ", "")
        if not self.hasFocus():
            super().setText(self._format_text(self._raw_text))

    def focusInEvent(self, event):
        super().setText(self._raw_text)
        super().focusInEvent(event)
        QtCore.QTimer.singleShot(0, self.selectAll)

    def focusOutEvent(self, event):
        # Re-format on focus loss
        self._raw_text = super().text().replace(" ", "")
        super().setText(self._format_text(self._raw_text))
        super().focusOutEvent(event)

def key_event_to_name(event) -> str:
    """Convert a QKeyEvent into a normalized keybind string (e.g. 'Ctrl', 'Space', 'T', 'F1', 'Ctrl+Z')."""
    key = event.key()
    if key in (QtCore.Qt.Key.Key_Control,):
        return "Ctrl"
    if key in (QtCore.Qt.Key.Key_Shift,):
        return "Shift"
    if key in (QtCore.Qt.Key.Key_Alt,):
        return "Alt"
    if key in (QtCore.Qt.Key.Key_Space,):
        return "Space"
    
    mod = event.modifiers()
    parts = []
    if mod & QtCore.Qt.KeyboardModifier.ControlModifier:
        parts.append("Ctrl")
    if mod & QtCore.Qt.KeyboardModifier.AltModifier:
        parts.append("Alt")

    name = QtGui.QKeySequence(key).toString()
    if name == "Control":
        name = "Ctrl"
    if name:
        parts.append(name)
    return "+".join(parts) if parts else ""


def format_tooltip_with_keybind(base_text: str, key_str: str, is_hold: bool = False) -> str:
    """Format a button tooltip with its keybind in brackets at the end, e.g. 'Reset Zoom (Home) [R]' or 'Zoom Mode [Hold Ctrl]'."""
    key_clean = str(key_str or "").strip()
    if not key_clean:
        return base_text
    suffix = f"[Hold {key_clean}]" if is_hold else f"[{key_clean}]"
    return f"{base_text} {suffix}"


def get_theme_icon(name: str, theme: str = "Light") -> QtGui.QIcon:
    """Load a theme-aware icon from iqview/resources/assets."""
    import os
    suffix = "_dark" if theme == "Dark" else ""
    icon_name = f"{name}{suffix}"
    try:
        from importlib.resources import files
        icon_resource = files("iqview.resources.assets").joinpath(f"{icon_name}.png")
        with icon_resource.open("rb") as f:
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(f.read())
            return QtGui.QIcon(pixmap)
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        local_path = os.path.join(base_path, "iqview", "resources", "assets", f"{icon_name}.png")
        if not os.path.exists(local_path) and suffix:
            local_path = os.path.join(base_path, "iqview", "resources", "assets", f"{name}.png")
        return QtGui.QIcon(local_path)


class KeyBindEdit(QtWidgets.QLineEdit):
    """
    A QLineEdit that captures a single key press (including standalone modifiers) 
    and sets its text to that key's name.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click and press a key...")
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.key_name = ""

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key.Key_Escape:
            self.clear()
            self.key_name = ""
            self.clearFocus()
            event.accept()
            return

        name = key_event_to_name(event)
        if name:
            self.setText(name)
            self.key_name = name
            self.clearFocus()
            event.accept()
        else:
            super().keyPressEvent(event)

class CustomViewBox(pg.ViewBox):
    def __init__(self, ui_controller, *args, **kwds):
        super().__init__(*args, **kwds)
        self.ui_controller = ui_controller
        self.zoom_rect = None
        self._overlay_preview = None
        self._overlay_drag_start = None
        self._active_drag_mode = None
        self.setMenuEnabled(False) # Disable default pg menu
        self.setAcceptHoverEvents(True)
        self.refresh_theme()

    def refresh_theme(self):
        s = getattr(self.ui_controller, 'settings_mgr', None) or (getattr(self.ui_controller, 'parent_window', None) and getattr(self.ui_controller.parent_window, 'settings_mgr', None))
        theme = str(s.get("ui/theme", "Dark")).lower() if s else "dark"
        if hasattr(self, 'rbScaleBox') and self.rbScaleBox is not None:
            if theme == "light":
                self.rbScaleBox.setPen(pg.mkPen((0, 0, 0, 255), width=1.5))
                self.rbScaleBox.setBrush(pg.mkBrush((0, 0, 0, 60)))
            else:
                self.rbScaleBox.setPen(pg.mkPen((255, 255, 255, 255), width=1.5))
                self.rbScaleBox.setBrush(pg.mkBrush((255, 255, 255, 100)))

    def updateScaleBox(self, p1, p2):
        self.refresh_theme()
        super().updateScaleBox(p1, p2)

    def hoverEvent(self, ev):
        if ev.isExit():
            self.unsetCursor()
            return

        scene_pos = ev.scenePos()
        mode = getattr(self.ui_controller, 'interaction_mode', None)

        # Only show special cursors in interactive marker modes
        if mode not in ['TIME', 'FREQ', 'MAG', 'Y', 'FILTER', 'STATS',
                        'TIME_ENDLESS', 'FREQ_ENDLESS', 'MAG_ENDLESS']:
            self.unsetCursor()
            return

        HIT = 20  # pixel threshold — matches drag code

        # --- Helpers ---
        def dist_to_vertical(val):
            """Pixel distance from scene_pos to a vertical InfiniteLine at x=val."""
            p = self.mapViewToScene(pg.Point(val, 0))
            return abs(scene_pos.x() - p.x())

        def dist_to_horizontal(val):
            """Pixel distance from scene_pos to a horizontal InfiniteLine at y=val."""
            p = self.mapViewToScene(pg.Point(0, val))
            return abs(scene_pos.y() - p.y())

        def dist_to_line(val, is_vertical):
            return dist_to_vertical(val) if is_vertical else dist_to_horizontal(val)

        mp = getattr(self.ui_controller, 'marker_panel', None)
        def _checked(btn_name):
            btn = getattr(mp, btn_name, None) if mp else None
            return btn.isChecked() if btn else False

        lock_m1    = _checked('btn_lock_m1')
        lock_m2    = _checked('btn_lock_m2')
        lock_delta  = _checked('btn_lock_delta')
        lock_center = _checked('btn_lock_center')
        pair_locked = lock_delta or lock_center

        found_near = False

        # ── 1. FILTER mode: BPF bounds (horizontal freq lines) ──────────────
        if not found_near and mode == 'FILTER':
            filter_bounds = getattr(self.ui_controller, 'filter_bounds', [])
            sorted_fb = sorted(filter_bounds)
            for i, b_val in enumerate(sorted_fb):
                if dist_to_horizontal(b_val) < HIT:
                    individually_locked = (i == 0 and lock_m1) or (i == 1 and lock_m2)
                    if not individually_locked or pair_locked:
                        self.setCursor(Qt.CursorShape.SizeVerCursor)
                        found_near = True
                        break

        # ── 2. Regular markers ───────────────────────────────────────────────
        if not found_near and mode in ['TIME', 'FREQ', 'MAG', 'Y',
                                       'TIME_ENDLESS', 'FREQ_ENDLESS', 'MAG_ENDLESS']:
            # Collect active markers for this mode
            if mode in ['TIME', 'TIME_ENDLESS']:
                if 'ENDLESS' in mode:
                    active_markers = list(getattr(self.ui_controller, 'markers_time_endless', []))
                else:
                    active_markers = list(getattr(self.ui_controller, 'markers_time', []))
            elif mode in ['FREQ', 'FREQ_ENDLESS']:
                if 'ENDLESS' in mode:
                    active_markers = list(getattr(self.ui_controller, 'markers_freq_endless', []))
                else:
                    active_markers = list(getattr(self.ui_controller, 'markers_freq', []))
            else:  # MAG / Y / MAG_ENDLESS
                y_label = getattr(self.ui_controller, 'y_label_text', '')
                if 'ENDLESS' in mode:
                    active_markers = list(getattr(self.ui_controller, 'markers_y_endless_dict', {}).get(y_label, []))
                else:
                    active_markers = list(getattr(self.ui_controller, 'markers_y_dict', {}).get(y_label, []))

            # Sorted by value to map m1 (lower) / m2 (higher) to lock buttons
            sorted_m = sorted(active_markers, key=lambda m: m.value()) if len(active_markers) == 2 else active_markers

            for m in active_markers:
                angle = getattr(m, 'angle', 90)
                is_vert = (angle == 90)
                if dist_to_line(m.value(), is_vert) < HIT:
                    # Skip if this individual marker is locked without a pair-lock
                    if len(active_markers) == 2:
                        idx = sorted_m.index(m) if m in sorted_m else -1
                        individually_locked = (idx == 0 and lock_m1) or (idx == 1 and lock_m2)
                        if individually_locked and not pair_locked:
                            continue
                    self.setCursor(Qt.CursorShape.SizeHorCursor if is_vert else Qt.CursorShape.SizeVerCursor)
                    found_near = True
                    break

        # ── 3. Shadow markers / grid lines ──────────────────────────────────
        # Shadow markers work in all lock states (lock_delta shifts the whole grid;
        # lock_center adjusts the spread — both are handled in update_drag).
        if not found_near and mode in ['TIME', 'FREQ', 'MAG', 'Y']:
            if mode == 'TIME':
                grid_lines = getattr(self.ui_controller, 'grid_lines_time', [])
            elif mode == 'FREQ':
                grid_lines = getattr(self.ui_controller, 'grid_lines_freq', [])
            else:  # MAG / Y
                grid_lines = getattr(self.ui_controller, 'grid_lines_mag', [])

            for gl in grid_lines:
                angle = getattr(gl, 'angle', 90)
                is_vert = (angle == 90)
                if dist_to_line(gl.value(), is_vert) < HIT:
                    self.setCursor(Qt.CursorShape.SizeHorCursor if is_vert else Qt.CursorShape.SizeVerCursor)
                    found_near = True
                    break

        # ── 4. STATS mode: region bounds and single line ─────────────────────
        if not found_near and mode == 'STATS':
            stats_bounds = getattr(self.ui_controller, 'stats_bounds', [])
            stats_region = getattr(self.ui_controller, 'stats_region', None)
            stats_line   = getattr(self.ui_controller, 'stats_line', None)

            if stats_region and stats_region.isVisible():
                for b_val in stats_bounds:
                    if dist_to_vertical(b_val) < HIT:
                        self.setCursor(Qt.CursorShape.SizeHorCursor)
                        found_near = True
                        break

            if not found_near and stats_line and stats_line.isVisible():
                if dist_to_vertical(stats_line.value()) < HIT:
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                    found_near = True

        # ── Fallback: crosshair ───────────────────────────────────────────────
        if not found_near:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseDragEvent(self, ev, axis=None):
        if not hasattr(ev, 'isStart'):
            super().mouseDragEvent(ev, axis=axis)
            return
            
        if ev.button() == Qt.MouseButton.LeftButton:
            s = self.ui_controller.settings_mgr
            zoom_key = s.get('keybinds/zoom_mode', 'Ctrl')
            is_zoom_mod = (zoom_key in ("Ctrl", "Control") and bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier))
            
            if ev.isStart():
                if self.ui_controller.interaction_mode == 'ZOOM' or is_zoom_mod:
                    self._active_drag_mode = 'ZOOM'
                elif self.ui_controller.interaction_mode == 'MOVE':
                    self._active_drag_mode = 'MOVE'
                elif self.ui_controller.interaction_mode == 'OVERLAY':
                    self._active_drag_mode = 'OVERLAY'
                else:
                    self._active_drag_mode = self.ui_controller.interaction_mode

            drag_mode = getattr(self, '_active_drag_mode', None) or self.ui_controller.interaction_mode
            if ev.isFinish():
                self._active_drag_mode = None

            if drag_mode == 'ZOOM':
                # --- Rubberband Zoom Logic ---
                if ev.isStart():
                    if self.zoom_rect: self.removeItem(self.zoom_rect)
                    # We'll use a QGraphicsPathItem for the dynamic 1D/2D visual
                    self.zoom_rect = QtWidgets.QGraphicsPathItem()
                    self.addItem(self.zoom_rect)
                    
                    start_v = self.mapSceneToView(ev.buttonDownScenePos())
                    xr, yr = self.viewRange()
                    if xr is not None and yr is not None:
                        x_min, x_max = min(xr), max(xr)
                        y_min, y_max = min(yr), max(yr)
                        self.zoom_start_v = pg.QtCore.QPointF(
                            max(x_min, min(x_max, start_v.x())),
                            max(y_min, min(y_max, start_v.y()))
                        )
                    else:
                        self.zoom_start_v = start_v
                        
                    self.zoom_type = 'BOTH'
                
                elif ev.isFinish():
                    if self.zoom_rect:
                        rect = self.zoom_rect.path().boundingRect()
                        self.removeItem(self.zoom_rect)
                        self.zoom_rect = None
                        self.ui_controller.handle_zoom_rectangle(rect, self.zoom_type, source_vb=self)
                else:
                    if self.zoom_rect:
                        curr_v = self.mapSceneToView(ev.scenePos())
                        
                        xr, yr = self.viewRange()
                        if xr is not None and yr is not None:
                            x_min, x_max = min(xr), max(xr)
                            y_min, y_max = min(yr), max(yr)
                            curr_v = pg.QtCore.QPointF(
                                max(x_min, min(x_max, curr_v.x())),
                                max(y_min, min(y_max, curr_v.y()))
                            )
                            
                        p1, p2 = self.zoom_start_v, curr_v
                        
                        # Detect Zoom Type
                        dx, dy = abs(p2.x() - p1.x()), abs(p2.y() - p1.y())
                        ndx, ndy = dx / (xr[1]-xr[0]), dy / (yr[1]-yr[0])
                        
                        path = pg.QtGui.QPainterPath()
                        theme = str(s.get("ui/theme", "Dark")).lower()
                        default_box_color = "#000000" if theme == "light" else "#ffffff"
                        box_color = s.get(f"ui/{theme}/zoom_box_color", default_box_color) or default_box_color
                        box_style_name = s.get(f"ui/{theme}/zoom_box_style", "DashLine") or "DashLine"
                        
                        style_map = {
                            "SolidLine": Qt.PenStyle.SolidLine,
                            "DashLine": Qt.PenStyle.DashLine,
                            "DotLine": Qt.PenStyle.DotLine,
                            "DashDotLine": Qt.PenStyle.DashDotLine
                        }
                        box_style = style_map.get(str(box_style_name), Qt.PenStyle.DashLine)

                        pen = pg.mkPen(box_color, width=2) # Standard for 1D zoom
                        if ndx < 0.15 * ndy:
                            self.zoom_type = 'Y_ONLY'
                            # Vertical line with horizontal ticks
                            y_min, y_max = min(p1.y(), p2.y()), max(p1.y(), p2.y())
                            tick = (xr[1] - xr[0]) * 0.02
                            path.moveTo(p1.x(), y_min)
                            path.lineTo(p1.x(), y_max)
                            path.moveTo(p1.x() - tick, y_min)
                            path.lineTo(p1.x() + tick, y_min)
                            path.moveTo(p1.x() - tick, y_max)
                            path.lineTo(p1.x() + tick, y_max)
                        elif ndy < 0.15 * ndx:
                            self.zoom_type = 'X_ONLY'
                            # Horizontal line with vertical ticks
                            x_min, x_max = min(p1.x(), p2.x()), max(p1.x(), p2.x())
                            tick = (yr[1] - yr[0]) * 0.02
                            path.moveTo(x_min, p1.y())
                            path.lineTo(x_max, p1.y())
                            path.moveTo(x_min, p1.y() - tick)
                            path.lineTo(x_min, p1.y() + tick)
                            path.moveTo(x_max, p1.y() - tick)
                            path.lineTo(x_max, p1.y() + tick)
                        else:
                            self.zoom_type = 'BOTH'
                            pen = pg.mkPen(box_color, width=2, style=box_style)
                            # Convert hex to RGBA for brush
                            c = QtGui.QColor(box_color)
                            c.setAlpha(40)
                            self.zoom_rect.setBrush(QtGui.QBrush(c))
                            path.addRect(pg.QtCore.QRectF(p1, p2))
                        
                        self.zoom_rect.setPath(path)
                        self.zoom_rect.setPen(pen)
                ev.accept()
            elif drag_mode == 'MOVE':
                if ev.isStart():
                    self.ui_controller.handle_move_drag(ev.buttonDownScenePos(), is_start=True, source_vb=self)
                elif ev.isFinish():
                    self.ui_controller.handle_move_drag(ev.scenePos(), is_finish=True, source_vb=self)
                else:
                    self.ui_controller.handle_move_drag(ev.scenePos(), source_vb=self)
                ev.accept()
            elif drag_mode == 'OVERLAY':
                # Rubber-band drag to place an overlay
                if ev.isStart():
                    self._overlay_drag_start = self.mapSceneToView(ev.buttonDownScenePos())
                    self._overlay_preview = pg.QtWidgets.QGraphicsPathItem()
                    bc = self.ui_controller.settings_mgr.get(
                        f"ui/{self.ui_controller.settings_mgr.get('ui/theme','Dark').lower()}/time_marker_color",
                        '#008800')
                    self._overlay_preview.setPen(pg.mkPen(bc, width=2, style=Qt.PenStyle.DashLine))
                    c = QtGui.QColor(bc); c.setAlpha(30)
                    self._overlay_preview.setBrush(QtGui.QBrush(c))
                    self.addItem(self._overlay_preview)
                elif ev.isFinish():
                    if self._overlay_preview:
                        self.removeItem(self._overlay_preview)
                        self._overlay_preview = None
                    if hasattr(self, '_overlay_drag_start') and self._overlay_drag_start is not None:
                        end = self.mapSceneToView(ev.scenePos())
                        self.ui_controller.place_overlay_by_drag(
                            self._overlay_drag_start, end)
                        self._overlay_drag_start = None
                else:
                    if self._overlay_preview and hasattr(self, '_overlay_drag_start'):
                        curr = self.mapSceneToView(ev.scenePos())
                        p1, p2 = self._overlay_drag_start, curr
                        
                        shape_val = 'RECT'
                        if hasattr(self.ui_controller, 'marker_panel') and hasattr(self.ui_controller.marker_panel, 'cb_overlay_shape'):
                            os_obj = self.ui_controller.marker_panel.cb_overlay_shape.currentData()
                            if os_obj:
                                shape_val = os_obj.value

                        t0, f0 = p1.x(), p1.y()
                        t1, f1 = p2.x(), p2.y()
                        waterfall = getattr(
                            getattr(self.ui_controller, 'spectrogram_view', None),
                            'is_waterfall', False)
                        
                        path = pg.QtGui.QPainterPath()
                        if shape_val == 'RECT':
                            path.addRect(pg.QtCore.QRectF(p1, p2))
                        elif shape_val == 'ELLIPSE':
                            path.addEllipse(pg.QtCore.QRectF(p1, p2))
                        elif shape_val == 'POLYGON':
                            t_min, t_max = min(t0, t1), max(t0, t1)
                            f_min, f_max = min(f0, f1), max(f0, f1)
                            path.moveTo((t_min + t_max) / 2, f_max)
                            path.lineTo(t_max, f_min)
                            path.lineTo(t_min, f_min)
                            path.closeSubpath()
                        elif shape_val == 'X_REGION':
                            # X_REGION = time band
                            # Standard: drag left-right (x carries time) → vertical stripe
                            # Waterfall: drag up-down  (y carries time) → horizontal stripe
                            xr_v = self.viewRange()[0]
                            yr_v = self.viewRange()[1]
                            if waterfall:
                                # Drag span is in y; fill full x
                                y_lo, y_hi = min(f0, f1), max(f0, f1)
                                path.addRect(pg.QtCore.QRectF(
                                    pg.QtCore.QPointF(xr_v[0], y_lo),
                                    pg.QtCore.QPointF(xr_v[1], y_hi)))
                            else:
                                # Drag span is in x; fill full y
                                yr_v = self.viewRange()[1]
                                path.addRect(pg.QtCore.QRectF(
                                    pg.QtCore.QPointF(t0, yr_v[0]),
                                    pg.QtCore.QPointF(t1, yr_v[1])))
                        elif shape_val == 'Y_REGION':
                            # Y_REGION = freq band
                            # Standard: drag up-down (y carries freq) → horizontal stripe
                            # Waterfall: drag left-right (x carries freq) → vertical stripe
                            xr_v = self.viewRange()[0]
                            yr_v = self.viewRange()[1]
                            if waterfall:
                                # Drag span is in x; fill full y
                                x_lo, x_hi = min(t0, t1), max(t0, t1)
                                path.addRect(pg.QtCore.QRectF(
                                    pg.QtCore.QPointF(x_lo, yr_v[0]),
                                    pg.QtCore.QPointF(x_hi, yr_v[1])))
                            else:
                                # Drag span is in y; fill full x
                                path.addRect(pg.QtCore.QRectF(
                                    pg.QtCore.QPointF(xr_v[0], f0),
                                    pg.QtCore.QPointF(xr_v[1], f1)))
                        elif shape_val == 'LINE':
                            # LINE = time line: vertical in standard, horizontal in waterfall
                            xr_v = self.viewRange()[0]
                            yr_v = self.viewRange()[1]
                            if waterfall:
                                path.moveTo(xr_v[0], t0)
                                path.lineTo(xr_v[1], t0)
                            else:
                                path.moveTo(t0, yr_v[0])
                                path.lineTo(t0, yr_v[1])
                        elif shape_val == 'HLINE':
                            # HLINE = freq line: horizontal in standard, vertical in waterfall
                            xr_v = self.viewRange()[0]
                            yr_v = self.viewRange()[1]
                            if waterfall:
                                path.moveTo(f0, yr_v[0])
                                path.lineTo(f0, yr_v[1])
                            else:
                                path.moveTo(xr_v[0], f0)
                                path.lineTo(xr_v[1], f0)
                            
                        self._overlay_preview.setPath(path)
                ev.accept()
            else:
                # --- Marker Logic ---
                if self.ui_controller.interaction_mode in ['TIME', 'FREQ', 'MAG', 'Y', 'FILTER', 'TIME_ENDLESS', 'FREQ_ENDLESS', 'MAG_ENDLESS', 'STATS']:
                    if ev.isStart():
                        self.ui_controller.place_marker(ev.buttonDownScenePos(), drag_mode=True, source_vb=self)
                    elif ev.isFinish():
                        self.ui_controller.active_drag_marker = None
                        self.ui_controller.active_drag_grid_info = None
                        if getattr(self.ui_controller, 'active_drag_filter_bound_idx', -1) != -1:
                            self.ui_controller.on_filter_region_finished()
                            self.ui_controller.active_drag_filter_bound_idx = -1
                        if getattr(self.ui_controller, 'active_drag_stats_bound_idx', -1) != -1:
                            self.ui_controller.active_drag_stats_bound_idx = -1
                        if hasattr(self.ui_controller, 'update_marker_info'):
                            self.ui_controller.update_marker_info()
                    else:
                        self.ui_controller.update_drag(ev.scenePos(), source_vb=self)
                ev.accept()
        else:
            is_multirow = (
                hasattr(self.ui_controller, 'spectrogram_stack')
                and self.ui_controller.spectrogram_stack.currentIndex() == 1
            )
            if ev.button() == Qt.MouseButton.MiddleButton and is_multirow and axis is None:
                if ev.isStart():
                    if hasattr(self.ui_controller, 'push_multirow_zoom_state'):
                        self.ui_controller.push_multirow_zoom_state()
                    self.ui_controller.handle_move_drag(ev.buttonDownScenePos(), is_start=True, source_vb=self)
                elif ev.isFinish():
                    self.ui_controller.handle_move_drag(ev.scenePos(), is_finish=True, source_vb=self)
                else:
                    self.ui_controller.handle_move_drag(ev.scenePos(), source_vb=self)
                ev.accept()
                return

            if ev.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
                if ev.isStart():
                    if is_multirow:
                        if hasattr(self.ui_controller, 'push_multirow_zoom_state'):
                            self.ui_controller.push_multirow_zoom_state()
                        self.ui_controller._multirow_right_dragging = True
                    elif hasattr(self.ui_controller, 'zoom_history'):
                        self.ui_controller.zoom_history.append(self.viewRect())

            super().mouseDragEvent(ev, axis=axis)

            if ev.button() == Qt.MouseButton.RightButton and ev.isFinish() and is_multirow:
                self.ui_controller._multirow_right_dragging = False
                if hasattr(self.ui_controller, '_schedule_multirow_rerender'):
                    self.ui_controller._schedule_multirow_rerender()

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            mode = self.ui_controller.interaction_mode
            is_spec = getattr(self.ui_controller, 'is_spectrogram', False)

            if is_spec and hasattr(self.ui_controller, 'find_overlays_at_view_pos') and hasattr(self.ui_controller, 'select_overlay'):
                try:
                    pos = self.mapSceneToView(ev.scenePos())
                    hit_overlays = self.ui_controller.find_overlays_at_view_pos(pos, view_box=self)
                    endless_items = (
                        set(getattr(self.ui_controller, 'markers_time_endless', []))
                        | set(getattr(self.ui_controller, 'markers_freq_endless', []))
                    )
                    endless_ids = {
                        oid for oid, gfx in getattr(self.ui_controller, '_overlay_items', {}).items()
                        if gfx in endless_items
                    }
                    hit_overlays = [
                        o for o in hit_overlays
                        if o.id not in endless_ids or mode == 'OVERLAY'
                    ]
                except Exception:
                    hit_overlays = []

                if hit_overlays:
                    self.ui_controller.select_overlay(hit_overlays[0].id, scroll_to_row=True)
                    is_double = getattr(ev, 'double', lambda: False)()
                    if is_double and hasattr(self.ui_controller, 'inspect_overlay'):
                        self.ui_controller.inspect_overlay(hit_overlays[0])
                        ev.accept()
                        return
                    ev.accept()
                    return
                elif getattr(self.ui_controller, 'selected_overlay_id', None) is not None:
                    self.ui_controller.select_overlay(None, scroll_to_row=False)

            if mode in ['TIME', 'FREQ', 'MAG', 'Y', 'FILTER', 'TIME_ENDLESS', 'FREQ_ENDLESS', 'MAG_ENDLESS', 'STATS']:
                self.ui_controller.place_marker(ev.scenePos(), drag_mode=False, source_vb=self)
            elif mode == 'OVERLAY':
                # Single click → place a default overlay shape at this position
                pos = self.mapSceneToView(ev.scenePos())
                self.ui_controller.place_overlay_by_click(pos)
            ev.accept()
        elif ev.button() == Qt.MouseButton.RightButton:
            self.raise_custom_menu(ev)
            ev.accept()
        else:
            super().mouseClickEvent(ev)

    def raise_custom_menu(self, ev):
        menu = QtWidgets.QMenu()
        is_spec = getattr(self.ui_controller, 'is_spectrogram', False)

        # ── Overlay-specific context actions when right-clicking an overlay ──
        if is_spec and hasattr(self.ui_controller, 'find_overlays_at_view_pos'):
            try:
                view_pos = self.mapSceneToView(ev.scenePos())
                hit_overlays = self.ui_controller.find_overlays_at_view_pos(view_pos, view_box=self)
            except Exception:
                hit_overlays = []

            if hit_overlays:
                top_ov = hit_overlays[0]
                tag_preview = f" '{top_ov.display_str}'" if top_ov.display_str else f" ({top_ov.shape.value})"

                inspect_act = menu.addAction(f"Inspect Overlay{tag_preview} & Metadata…")
                inspect_act.triggered.connect(
                    lambda _c=False, o=top_ov: self.ui_controller.inspect_overlay(o)
                )

                if top_ov.duration > 0 and hasattr(self.ui_controller, 'analyze_overlay_in_tab'):
                    an_menu = menu.addMenu(f"Analyze Overlay{tag_preview} in…")
                    for lbl, mode_k in [
                        ("Time Domain (DDC Baseband)", "time"),
                        ("Frequency Domain (DDC Baseband)", "freq"),
                        ("Eye Diagram", "eye"),
                        ("Scatter Plot / Constellation", "constellation"),
                    ]:
                        act_an = an_menu.addAction(lbl)
                        act_an.triggered.connect(
                            lambda _c=False, o=top_ov, m=mode_k: self.ui_controller.analyze_overlay_in_tab(o, m)
                        )

                if top_ov.hover_str or top_ov.metadata:
                    copy_act = menu.addAction("Copy Overlay Text / Bits")
                    def _copy_ov_text(_c=False, o=top_ov):
                        import json
                        cb = QtWidgets.QApplication.clipboard()
                        if cb is not None:
                            if "bits" in o.metadata:
                                cb.setText(str(o.metadata["bits"]))
                            elif o.hover_str:
                                cb.setText(o.hover_str)
                            else:
                                cb.setText(json.dumps(o.metadata, indent=2, default=str))
                    copy_act.triggered.connect(_copy_ov_text)

                if hasattr(self.ui_controller, 'marker_panel') and hasattr(self.ui_controller.marker_panel, '_on_overlay_edit'):
                    edit_act = menu.addAction("Edit Overlay Style / Geometry…")
                    edit_act.triggered.connect(
                        lambda _c=False, oid=top_ov.id: self.ui_controller.marker_panel._on_overlay_edit(oid)
                    )

                del_act = menu.addAction("Delete Overlay")
                del_act.triggered.connect(
                    lambda _c=False, oid=top_ov.id: self.ui_controller.remove_overlay(oid)
                )

                if len(hit_overlays) > 1:
                    other_menu = menu.addMenu(f"Other Overlapping Overlays ({len(hit_overlays) - 1})…")
                    for ov_other in hit_overlays[1:]:
                        other_lbl = ov_other.display_str or f"{ov_other.shape.value} ({ov_other.t_start:.4f}s)"
                        act_o = other_menu.addAction(f"Inspect {other_lbl}")
                        act_o.triggered.connect(
                            lambda _c=False, o=ov_other: self.ui_controller.inspect_overlay(o)
                        )

                menu.addSeparator()
        
        view_all_act = menu.addAction("View All")
        view_all_act.triggered.connect(self.ui_controller.reset_zoom)
        
        if is_spec:
            uz_x = menu.addAction("Unzoom Time")
            uz_y = menu.addAction("Unzoom Freq")
        elif type(self.ui_controller).__name__ == "TimeDomainView":
            uz_x = menu.addAction("Unzoom Time")
            uz_y = menu.addAction("Unzoom Amplitude")
        else:
            uz_x = menu.addAction("Unzoom Freq")
            uz_y = menu.addAction("Unzoom Magnitude")
            
        uz_x.triggered.connect(self.ui_controller.reset_zoom_x)
        uz_y.triggered.connect(self.ui_controller.reset_zoom_y)
        
        clear_markers_act = menu.addAction("Clear All Markers")
        clear_markers_act.triggered.connect(self.ui_controller.clear_all_markers)
        
        menu.addSeparator()
        
        if is_spec:
            td_popup_act = menu.addAction("Time Domain Popup")
            td_popup_act.triggered.connect(self.ui_controller.open_time_domain_tab)
            
            fd_popup_act = menu.addAction("Frequency Domain Popup")
            fd_popup_act.triggered.connect(self.ui_controller.open_frequency_domain_tab)

            ed_popup_act = menu.addAction("Eye Diagram Popup")
            ed_popup_act.triggered.connect(self.ui_controller.open_eye_diagram_tab)

            cd_popup_act = menu.addAction("Scatter Plot Popup")
            cd_popup_act.triggered.connect(self.ui_controller.open_constellation_tab)

        # Add Dock Back if detached
        # To avoid circular imports, check if the window class name is DetachedViewWindow
        if self.ui_controller.window().__class__.__name__ == "DetachedViewWindow":
            menu.addSeparator()
            dock_act = menu.addAction("Dock back")
            dock_act.triggered.connect(self.ui_controller.window().dock_back)

        fit_act = menu.addAction("Fit to Screen")
        # Handle 'Y' mode for TimeDomainView or 'FREQ' for Spectrogram/Frequency Popup
        if is_spec:
            is_freq = (getattr(self.ui_controller, 'interaction_mode', 'TIME') in ['FREQ', 'FREQ_ENDLESS', 'MAG', 'Y'])
            active_markers = getattr(self.ui_controller, 'markers_freq_endless', []) if getattr(self.ui_controller, 'interaction_mode', '') == 'FREQ_ENDLESS' else \
                             getattr(self.ui_controller, 'markers_freq', []) if is_freq else \
                             getattr(self.ui_controller, 'markers_time_endless', []) if getattr(self.ui_controller, 'interaction_mode', '') == 'TIME_ENDLESS' else \
                             getattr(self.ui_controller, 'markers_time', [])
        else:
            # Popup View (Time or Frequency)
            mode = getattr(self.ui_controller, 'interaction_mode', 'TIME')
            if mode in ['MAG', 'Y', 'MAG_ENDLESS']:
                y_label = getattr(self.ui_controller, 'y_label_text', '')
                if 'ENDLESS' in mode:
                    active_markers = getattr(self.ui_controller, 'markers_y_endless_dict', {}).get(y_label, [])
                else:
                    active_markers = getattr(self.ui_controller, 'markers_y_dict', {}).get(y_label, [])
            elif mode in ['FREQ', 'FREQ_ENDLESS']:
                active_markers = getattr(self.ui_controller, 'markers_freq_endless', []) if 'ENDLESS' in mode else \
                                 getattr(self.ui_controller, 'markers_freq', [])
            else:
                active_markers = getattr(self.ui_controller, 'markers_time_endless', []) if 'ENDLESS' in mode else \
                                 getattr(self.ui_controller, 'markers_time', [])
                
        fit_act.setEnabled(len(active_markers) >= 2)
        fit_act.triggered.connect(self.ui_controller.fit_to_markers)
        
        if is_spec:
            menu.addSeparator()
            # Time Grid Submenu
            grid_time_menu = menu.addMenu("Time Grid")
            markers_time = getattr(self.ui_controller, 'markers_time', [])
            grid_time_menu.setEnabled(len(markers_time) == 2)
            
            grid_time_enable_act = grid_time_menu.addAction("Enabled")
            grid_time_enable_act.setCheckable(True)
            grid_time_enable_act.setChecked(getattr(self.ui_controller, 'grid_time_enabled', False))
            grid_time_enable_act.triggered.connect(lambda checked: self.ui_controller.toggle_grid('TIME', checked))
            
            grid_time_track_act = grid_time_menu.addAction("Tracking")
            grid_time_track_act.setCheckable(True)
            grid_time_track_act.setChecked(self.ui_controller.grid_time_tracking)
            grid_time_track_act.triggered.connect(lambda checked: self.ui_controller.toggle_tracking('TIME', checked))
            
            # Freq Grid Submenu
            grid_freq_menu = menu.addMenu("Frequency Grid")
            grid_freq_menu.setEnabled(len(self.ui_controller.markers_freq) == 2)
            
            grid_freq_enable_act = grid_freq_menu.addAction("Enabled")
            grid_freq_enable_act.setCheckable(True)
            grid_freq_enable_act.setChecked(self.ui_controller.grid_freq_enabled)
            grid_freq_enable_act.triggered.connect(lambda checked: self.ui_controller.toggle_grid('FREQ', checked))
            
            grid_freq_track_act = grid_freq_menu.addAction("Tracking")
            grid_freq_track_act.setCheckable(True)
            grid_freq_track_act.setChecked(self.ui_controller.grid_freq_tracking)
            grid_freq_track_act.triggered.connect(lambda checked: self.ui_controller.toggle_tracking('FREQ', checked))
        else:
            menu.addSeparator()
            mode = getattr(self.ui_controller, 'interaction_mode', 'TIME')
            is_freq_popup = ('FREQ' in mode)
            
            # Main Axis Grid Submenu (Time or Frequency)
            main_axis_name = "Frequency" if is_freq_popup else "Time"
            grid_main_menu = menu.addMenu(f"{main_axis_name} Grid")
            main_markers = getattr(self.ui_controller, 'markers_freq', []) if is_freq_popup else \
                           getattr(self.ui_controller, 'markers_time', [])
            grid_main_menu.setEnabled(len(main_markers) == 2)
            
            grid_main_enable_act = grid_main_menu.addAction("Enabled")
            grid_main_enable_act.setCheckable(True)
            main_grid_enabled = getattr(self.ui_controller, 'grid_freq_enabled', False) if is_freq_popup else \
                                getattr(self.ui_controller, 'grid_time_enabled', False)
            grid_main_enable_act.setChecked(main_grid_enabled)
            grid_main_enable_act.triggered.connect(lambda checked: self.ui_controller.toggle_grid('FREQ' if is_freq_popup else 'TIME', checked))
            
            grid_main_track_act = grid_main_menu.addAction("Tracking")
            grid_main_track_act.setCheckable(True)
            main_grid_tracking = getattr(self.ui_controller, 'grid_freq_tracking', False) if is_freq_popup else \
                                 getattr(self.ui_controller, 'grid_time_tracking', False)
            grid_main_track_act.setChecked(main_grid_tracking)
            grid_main_track_act.triggered.connect(lambda checked: self.ui_controller.toggle_tracking('FREQ' if is_freq_popup else 'TIME', checked))
            
            # Magnitude/Y Grid Submenu
            grid_mag_menu = menu.addMenu("Magnitude Grid")
            markers_y_dict = getattr(self.ui_controller, 'markers_y_dict', {})
            y_label = getattr(self.ui_controller, 'y_label_text', '')
            active_y_markers = markers_y_dict.get(y_label, [])
            grid_mag_menu.setEnabled(len(active_y_markers) == 2)
            
            grid_mag_enable_act = grid_mag_menu.addAction("Enabled")
            grid_mag_enable_act.setCheckable(True)
            grid_mag_enable_act.setChecked(getattr(self.ui_controller, 'grid_mag_enabled', False))
            grid_mag_enable_act.triggered.connect(lambda checked: self.ui_controller.toggle_grid('MAG', checked))
            
            grid_mag_track_act = grid_mag_menu.addAction("Tracking")
            grid_mag_track_act.setCheckable(True)
            grid_mag_track_act.setChecked(getattr(self.ui_controller, 'grid_mag_tracking', False))
            grid_mag_track_act.triggered.connect(lambda checked: self.ui_controller.toggle_tracking('MAG', checked))
        
        menu.addSeparator()
        
        export_act = menu.addAction("Export...")
        def open_export():
            try:
                from .export_dialog import ExportDialog
                self.export_dialog = ExportDialog(self.ui_controller)
                self.export_dialog.show()
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self.ui_controller, "Export Unavailable", 
                                  f"The custom Export Dialog could not be loaded.\n\nError: {str(e)}")
        export_act.triggered.connect(open_export)
        
        menu.exec(ev.screenPos().toPoint())

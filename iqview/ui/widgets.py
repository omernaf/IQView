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
        if self._raw_text:
            super().setText(self._format_text(self._raw_text))

    def setText(self, text):
        self._raw_text = str(text)
        if not self.hasFocus():
            super().setText(self._format_text(self._raw_text))
        else:
            super().setText(self._raw_text)

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
        self.selectAll()

    def focusOutEvent(self, event):
        # Re-format on focus loss
        self._raw_text = super().text().replace(" ", "")
        super().setText(self._format_text(self._raw_text))
        super().focusOutEvent(event)

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
            return

        # Use QKeySequence to get a friendly name for the key
        # We use just the key (no modifiers) unless it's a combination.
        # But here we want the user to be able to set just 'Ctrl', 'Alt', etc.
        name = QtGui.QKeySequence(key).toString()
        
        # QKeySequence(Qt.Key_Control).toString() -> "Control"
        # We might want to shorten it to "Ctrl" for UI consistency
        if name == "Control": name = "Ctrl"
        
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
        self.setMenuEnabled(False) # Disable default pg menu
        self.setAcceptHoverEvents(True)

    def hoverEvent(self, ev):
        if ev.isExit():
            return
            
        mode = getattr(self.ui_controller, 'interaction_mode', None)
        if mode in ['TIME', 'FREQ', 'MAG', 'Y', 'FILTER', 'STATS']:
            # Find closest marker
            active_markers = []
            
            if mode == 'TIME':
                active_markers = getattr(self.ui_controller, 'markers_time', [])
            elif mode in ['FREQ', 'FILTER']:
                active_markers = getattr(self.ui_controller, 'markers_freq', [])
            elif mode in ['MAG', 'Y']:
                if hasattr(self.ui_controller, 'markers_y_dict'):
                    y_label = getattr(self.ui_controller, 'y_label_text', "")
                    active_markers = self.ui_controller.markers_y_dict.get(y_label, [])
            
            found_near = False
            scene_pos = ev.scenePos()

            if mode == 'FILTER':
                active_values = getattr(self.ui_controller, 'filter_bounds', [])
                for i, b_val in enumerate(active_values):
                    # In Spectrogram, filter bounds are horizontal frequency lines
                    p_scene = self.mapViewToScene(pg.Point(0, b_val))
                    dist = abs(scene_pos.y() - p_scene.y())
                    if dist < 20:
                        # Check lock status
                        is_b_locked = False
                        if len(active_values) == 2:
                            lock_m1 = getattr(self.ui_controller.marker_panel, 'btn_lock_m1', None)
                            lock_m2 = getattr(self.ui_controller.marker_panel, 'btn_lock_m2', None)
                            lock_delta = getattr(self.ui_controller.marker_panel, 'btn_lock_delta', None)
                            lock_center = getattr(self.ui_controller.marker_panel, 'btn_lock_center', None)
                            
                            b_locked = (i == 0 and lock_m1 and lock_m1.isChecked()) or \
                                       (i == 1 and lock_m2 and lock_m2.isChecked())
                            linked = (lock_delta and lock_delta.isChecked()) or \
                                     (lock_center and lock_center.isChecked())
                            if b_locked and not linked:
                                is_b_locked = True
                        
                        if not is_b_locked:
                            found_near = True
                            self.setCursor(Qt.CursorShape.SizeVerCursor)
                            break
            
            if not found_near:
                for i, m in enumerate(active_markers):
                    # markers are InfiniteLines. angle=90 is vertical, angle=0 is horizontal
                    m_val = m.value()
                    angle = m.angle
                    m_pixel = self.mapViewToScene(pg.Point(m_val, 0) if angle == 90 else pg.Point(0, m_val))
                    dist = abs(scene_pos.x() - m_pixel.x()) if angle == 90 else abs(scene_pos.y() - m_pixel.y())
                    
                    if dist < 20:
                        # Check lock status
                        is_m_locked = False
                        if len(active_markers) == 2:
                            lock_m1 = getattr(self.ui_controller.marker_panel, 'btn_lock_m1', None)
                            lock_m2 = getattr(self.ui_controller.marker_panel, 'btn_lock_m2', None)
                            lock_delta = getattr(self.ui_controller.marker_panel, 'btn_lock_delta', None)
                            lock_center = getattr(self.ui_controller.marker_panel, 'btn_lock_center', None)
                            
                            m_locked = (i == 0 and lock_m1 and lock_m1.isChecked()) or \
                                       (i == 1 and lock_m2 and lock_m2.isChecked())
                            linked = (lock_delta and lock_delta.isChecked()) or \
                                     (lock_center and lock_center.isChecked())
                            
                            if m_locked and not linked:
                                is_m_locked = True
                        
                        if not is_m_locked:
                            found_near = True
                            self.setCursor(Qt.CursorShape.SizeHorCursor if angle == 90 else Qt.CursorShape.SizeVerCursor)
                            break
            
            # 4. Check for Grid Lines (Shadow Markers) - allowable in all lock states!
            if not found_near and mode in ['TIME', 'FREQ', 'MAG', 'Y']:
                if mode == 'TIME':
                    grid_lines = getattr(self.ui_controller, 'grid_lines_time', [])
                elif mode == 'FREQ':
                    grid_lines = getattr(self.ui_controller, 'grid_lines_freq', [])
                else:
                    grid_lines = getattr(self.ui_controller, 'grid_lines_mag', [])
                for gl in grid_lines:
                    gl_val = gl.value()
                    angle = gl.angle
                    gl_pixel = self.mapViewToScene(pg.Point(gl_val, 0) if angle == 90 else pg.Point(0, gl_val))
                    dist = abs(scene_pos.x() - gl_pixel.x()) if angle == 90 else abs(scene_pos.y() - gl_pixel.y())
                    
                    if dist < 20:
                        found_near = True
                        self.setCursor(Qt.CursorShape.SizeHorCursor if angle == 90 else Qt.CursorShape.SizeVerCursor)
                        break
                        
            # 5. Check for STATS Region boundaries
            if not found_near and mode == 'STATS':
                stats_bounds = getattr(self.ui_controller, 'stats_bounds', [])
                for b_val in stats_bounds:
                    pi = self.mapViewToScene(pg.Point(b_val, 0))
                    if abs(scene_pos.x() - pi.x()) < 20:
                        found_near = True
                        self.setCursor(Qt.CursorShape.SizeHorCursor)
                        break
            
            if not found_near:
                self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseDragEvent(self, ev, axis=None):
        if not hasattr(ev, 'isStart'):
            super().mouseDragEvent(ev)
            return
            
        if ev.button() == Qt.MouseButton.LeftButton:
            s = self.ui_controller.settings_mgr
            zoom_key = s.get('keybinds/zoom_mode', 'Control')
            is_zoom_mod = (zoom_key == "Control" and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier))
            
            if self.ui_controller.interaction_mode == 'ZOOM' or is_zoom_mod:
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
                        self.ui_controller.handle_zoom_rectangle(rect, self.zoom_type)
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
                        theme = s.get("ui/theme", "Dark").lower()
                        
                        box_color = s.get(f"ui/{theme}/zoom_box_color")
                        box_style_name = s.get(f"ui/{theme}/zoom_box_style")
                        
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
            elif self.ui_controller.interaction_mode == 'MOVE':
                if ev.isStart():
                    self.ui_controller.handle_move_drag(ev.buttonDownScenePos(), is_start=True)
                elif ev.isFinish():
                    self.ui_controller.handle_move_drag(ev.scenePos(), is_finish=True)
                else:
                    self.ui_controller.handle_move_drag(ev.scenePos())
                ev.accept()
            else:
                # --- Marker Logic ---
                if self.ui_controller.interaction_mode in ['TIME', 'FREQ', 'MAG', 'Y', 'FILTER', 'TIME_ENDLESS', 'FREQ_ENDLESS', 'MAG_ENDLESS', 'STATS']:
                    if ev.isStart():
                        self.ui_controller.place_marker(ev.buttonDownScenePos(), drag_mode=True)
                    elif ev.isFinish():
                        self.ui_controller.active_drag_marker = None
                        self.ui_controller.active_drag_grid_info = None
                        if getattr(self.ui_controller, 'active_drag_filter_bound_idx', -1) != -1:
                            self.ui_controller.on_filter_region_finished()
                            self.ui_controller.active_drag_filter_bound_idx = -1
                        if getattr(self.ui_controller, 'active_drag_stats_bound_idx', -1) != -1:
                            self.ui_controller.active_drag_stats_bound_idx = -1
                    else:
                        self.ui_controller.update_drag(ev.scenePos())
                ev.accept()
        else:
            super().mouseDragEvent(ev)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            if self.ui_controller.interaction_mode in ['TIME', 'FREQ', 'MAG', 'Y', 'FILTER', 'TIME_ENDLESS', 'FREQ_ENDLESS', 'MAG_ENDLESS', 'STATS']:
                self.ui_controller.place_marker(ev.scenePos(), drag_mode=False)
            ev.accept()
        elif ev.button() == Qt.MouseButton.RightButton:
            self.raise_custom_menu(ev)
            ev.accept()
        else:
            super().mouseClickEvent(ev)

    def raise_custom_menu(self, ev):
        menu = QtWidgets.QMenu()
        is_spec = getattr(self.ui_controller, 'is_spectrogram', False)
        
        view_all_act = menu.addAction("View All")
        view_all_act.triggered.connect(self.ui_controller.reset_zoom)
        
        menu.addSeparator()
        
        if is_spec:
            td_popup_act = menu.addAction("Time Domain Popup")
            td_popup_act.triggered.connect(self.ui_controller.open_time_domain_tab)

        fit_act = menu.addAction("Fit to Screen")
        # Handle 'Y' mode for TimeDomainView or 'FREQ' for Spectrogram
        if is_spec:
            is_freq = (self.ui_controller.interaction_mode in ['FREQ', 'FREQ_ENDLESS', 'MAG', 'Y'])
            active_markers = self.ui_controller.markers_freq_endless if self.ui_controller.interaction_mode == 'FREQ_ENDLESS' else \
                             self.ui_controller.markers_freq if is_freq else \
                             self.ui_controller.markers_time_endless if self.ui_controller.interaction_mode == 'TIME_ENDLESS' else \
                             self.ui_controller.markers_time
        else:
            # TimeDomainView
            if self.ui_controller.interaction_mode in ['MAG', 'Y', 'MAG_ENDLESS']:
                active_markers = self.ui_controller.markers_y_endless_dict.get(self.ui_controller.y_label_text, []) if 'ENDLESS' in self.ui_controller.interaction_mode else \
                                 self.ui_controller.markers_y_dict.get(self.ui_controller.y_label_text, [])
            else:
                active_markers = self.ui_controller.markers_time_endless if 'ENDLESS' in self.ui_controller.interaction_mode else \
                                 self.ui_controller.markers_time
                
        fit_act.setEnabled(len(active_markers) >= 2)
        fit_act.triggered.connect(self.ui_controller.fit_to_markers)
        
        if is_spec:
            menu.addSeparator()
            # Time Grid Submenu
            grid_time_menu = menu.addMenu("Time Grid")
            grid_time_menu.setEnabled(len(self.ui_controller.markers_time) == 2)
            
            grid_time_enable_act = grid_time_menu.addAction("Enabled")
            grid_time_enable_act.setCheckable(True)
            grid_time_enable_act.setChecked(self.ui_controller.grid_time_enabled)
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
            # Time Grid Submenu
            grid_time_menu = menu.addMenu("Time Grid")
            grid_time_menu.setEnabled(len(self.ui_controller.markers_time) == 2)
            
            grid_time_enable_act = grid_time_menu.addAction("Enabled")
            grid_time_enable_act.setCheckable(True)
            grid_time_enable_act.setChecked(getattr(self.ui_controller, 'grid_time_enabled', False))
            grid_time_enable_act.triggered.connect(lambda checked: self.ui_controller.toggle_grid('TIME', checked))
            
            grid_time_track_act = grid_time_menu.addAction("Tracking")
            grid_time_track_act.setCheckable(True)
            grid_time_track_act.setChecked(getattr(self.ui_controller, 'grid_time_tracking', False))
            grid_time_track_act.triggered.connect(lambda checked: self.ui_controller.toggle_tracking('TIME', checked))
            
            # Magnitude Grid Submenu
            grid_mag_menu = menu.addMenu("Magnitude Grid")
            active_y_markers = self.ui_controller.markers_y_dict.get(self.ui_controller.y_label_text, [])
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

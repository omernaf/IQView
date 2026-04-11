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
        
        clear_markers_act = menu.addAction("Clear All Markers")
        clear_markers_act.triggered.connect(self.ui_controller.clear_all_markers)
        
        menu.addSeparator()
        
        if is_spec:
            td_popup_act = menu.addAction("Time Domain Popup")
            td_popup_act.triggered.connect(self.ui_controller.open_time_domain_tab)
            
            fd_popup_act = menu.addAction("Frequency Domain Popup")
            fd_popup_act.triggered.connect(self.ui_controller.open_frequency_domain_tab)

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

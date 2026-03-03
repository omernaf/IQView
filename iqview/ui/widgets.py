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
        self._raw_text = ""
        self.editingFinished.connect(self._handle_editing_finished)

    def setText(self, text):
        self._raw_text = str(text)
        if not self.hasFocus():
            super().setText(self._format_text(self._raw_text))
        else:
            super().setText(self._raw_text)

    def text(self):
        # Return raw text even if displayed with spaces
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

class CustomViewBox(pg.ViewBox):
    def __init__(self, ui_controller, *args, **kwds):
        super().__init__(*args, **kwds)
        self.ui_controller = ui_controller
        self.zoom_rect = None
        self.setMenuEnabled(False) # Disable default pg menu

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
                    self.zoom_start_v = self.mapSceneToView(ev.buttonDownScenePos())
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
                        p1, p2 = self.zoom_start_v, curr_v
                        
                        # Detect Zoom Type
                        xr, yr = self.viewRange()
                        dx, dy = abs(p2.x() - p1.x()), abs(p2.y() - p1.y())
                        ndx, ndy = dx / (xr[1]-xr[0]), dy / (yr[1]-yr[0])
                        
                        path = pg.QtGui.QPainterPath()
                        theme = s.get("ui/theme", "Dark")
                        p = get_palette(theme)
                        pen = pg.mkPen(p.text_header, width=2) # Contrast Header Color
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
                            pen = pg.mkPen(p.text_header, width=2, style=Qt.PenStyle.DashLine)
                            # Convert hex to RGBA for brush
                            c = QtGui.QColor(p.text_header)
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
                if self.ui_controller.interaction_mode in ['TIME', 'FREQ', 'MAG', 'Y']:
                    if ev.isStart():
                        self.ui_controller.place_marker(ev.buttonDownScenePos(), drag_mode=True)
                    elif ev.isFinish():
                        self.ui_controller.active_drag_marker = None
                    else:
                        self.ui_controller.update_drag(ev.scenePos())
                ev.accept()
        else:
            super().mouseDragEvent(ev)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            if self.ui_controller.interaction_mode in ['TIME', 'FREQ', 'MAG', 'Y']:
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
            time_markers_count = len(self.ui_controller.markers_time)
            td_popup_act.setEnabled(time_markers_count == 2)
            td_popup_act.triggered.connect(self.ui_controller.open_time_domain_tab)

        fit_act = menu.addAction("Fit to Screen")
        # Handle 'Y' mode for TimeDomainView or 'FREQ' for Spectrogram
        if is_spec:
            active_markers = self.ui_controller.markers_freq if self.ui_controller.interaction_mode == 'FREQ' else self.ui_controller.markers_time
        else:
            # TimeDomainView
            if self.ui_controller.interaction_mode == 'MAG':
                active_markers = self.ui_controller.markers_y_dict.get(self.ui_controller.y_label_text, [])
            else:
                active_markers = self.ui_controller.markers_time
                
        fit_act.setEnabled(len(active_markers) == 2)
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
        
        menu.addSeparator()
        
        export_act = menu.addAction("Export...")
        def open_export():
            try:
                try:
                    from pyqtgraph.exportDialog import ExportDialog
                except ImportError:
                    try:
                        from pyqtgraph.exporters.exportDialog import ExportDialog
                    except ImportError:
                        # Some versions of pyqtgraph moved it here or removed it
                        from pyqtgraph.exporters import ExportDialog
                self.export_dialog = ExportDialog(self.scene())
                self.export_dialog.show()
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self.ui_controller.parent_window, "Export Unavailable", 
                                  f"The pyqtgraph Export Dialog could not be loaded.\n\nError: {str(e)}")
        export_act.triggered.connect(open_export)
        
        menu.exec(ev.screenPos().toPoint())

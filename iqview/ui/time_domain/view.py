import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from ..widgets import CustomViewBox
from .marker_panel import TimeDomainMarkerPanel
from ..themes import get_palette, get_scrollbar_stylesheet

class TimeDomainView(QWidget):
    """
    A detailed view of a signal segment in the time domain with interactive markers.
    """
    def __init__(self, samples, start_time, sample_rate, parent=None, parent_window=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.samples = samples # Complex numpy array
        self.start_time = start_time
        self.rate = sample_rate
        self.parent_window = parent_window
        self.settings_mgr = parent_window.settings_mgr if parent_window else None
        self.is_spectrogram = False
        self.interaction_mode = 'TIME'
        self.zoom_mode = False
        self.active_drag_marker = None
        self.markers_time = []
        self._block_signals = False
        
        # Endless Markers
        self.markers_time_endless = []
        
        # Mode-specific Magnitude markers
        self.markers_y_dict = {
            "Amplitude (Real)": [],
            "Amplitude (Imag)": [],
            "Magnitude": [],
            "Instantaneous Frequency (Hz)": [],
            "Phase (rad)": [],
            "Unwrapped Phase (rad)": []
        }
        self.markers_y_endless_dict = {k: [] for k in self.markers_y_dict.keys()}
        
        # Mode-specific Y-zoom states (yMin, yMax)
        self.zoom_y_dict = {}
        
        self.y_label_text = "Amplitude (Real)"
        self.current_plot_data = samples.real # Cache for marker sampling
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(5)
        
        # --- Marker Panel ---
        self.marker_panel = TimeDomainMarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.main_layout.addWidget(self.marker_panel)
        
        # --- Toolbar ---
        self.toolbar = QFrame()
        self.toolbar.setObjectName("td_toolbar")
        self.update_toolbar_style()
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.toolbar_layout.addWidget(QLabel("Plot Mode:"))
        
        self.mode_group = QButtonGroup(self)
        self.modes = [
            ("Real (I)", self.plot_real),
            ("Imag (Q)", self.plot_imag),
            ("Absolute", self.plot_abs),
            ("Inst. Freq", self.plot_inst_freq),
            ("Phase", self.plot_phase),
            ("Unwrapped Phase", self.plot_unwrapped_phase)
        ]
        
        for i, (name, callback) in enumerate(self.modes):
            btn = QPushButton(name)
            btn.setCheckable(True)
            self.mode_group.addButton(btn, i)
            self.toolbar_layout.addWidget(btn)
            btn.clicked.connect(callback)
            if i == 0: btn.setChecked(True)
            
        self.toolbar_layout.addStretch()
        
        end_time = start_time + len(samples) / sample_rate
        range_label = QLabel(f"Range: {start_time:,.6f} to {end_time:,.6f} s")
        range_label.setStyleSheet("color: #888; font-family: Consolas; font-size: 11px;")
        self.toolbar_layout.addWidget(range_label)
        
        self.main_layout.addWidget(self.toolbar)
        
        # --- Plot & Scrollbars ---
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)
        
        self.view_box = CustomViewBox(self)
        self.plot_widget = pg.PlotWidget(viewBox=self.view_box)
        self.plot_item = self.plot_widget.getPlotItem()
        self.refresh_plot_style()
        self.plot_widget.getAxis('bottom').setLabel('Time', units='s')
        self.plot_widget.getAxis('left').setLabel('Amplitude (Real)')
        
        self.grid_layout.addWidget(self.plot_widget, 0, 1)

        # Scrollbars
        self.x_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.y_scroll = QScrollBar(Qt.Orientation.Vertical)
        
        scrollbar_style = get_scrollbar_stylesheet(get_palette(self.parent_window.settings_mgr.get("ui/theme", "Dark")))
        self.x_scroll.setStyleSheet(scrollbar_style)
        self.y_scroll.setStyleSheet(scrollbar_style)
        
        self.grid_layout.addWidget(self.y_scroll, 0, 0)
        self.grid_layout.addWidget(self.x_scroll, 1, 1)
        
        self.x_scroll.hide()
        self.y_scroll.hide()
        
        self.main_layout.addWidget(self.grid_container)
        
        self.time_axis = np.linspace(start_time, end_time, len(samples))
        # Initial call
        self._update_plot(self.samples.real, "Amplitude (Real)")
        self.set_interaction_mode('TIME')

        # Connect scrollbars
        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        s = self.parent_window.settings_mgr
        key_name = QKeySequence(event.key()).toString()
        if key_name == "Control": key_name = "Ctrl"
        
        time_seq = s.get('keybinds/time_markers', 'T')
        mag_seq = s.get('keybinds/mag_markers', 'F')
        zoom_seq = s.get('keybinds/zoom_mode', 'Ctrl')
        
        if key_name == time_seq:
            self.set_interaction_mode('TIME')
        elif key_name == mag_seq:
            self.set_interaction_mode('MAG')
        elif key_name == zoom_seq:
            self._prev_interaction_mode = getattr(self, 'interaction_mode', 'TIME')
            self.set_interaction_mode('ZOOM')
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        s = self.parent_window.settings_mgr
        key_name = QKeySequence(event.key()).toString()
        if key_name == "Control": key_name = "Ctrl"
        zoom_seq = s.get('keybinds/zoom_mode', 'Ctrl')

        if key_name == zoom_seq:
            prev = getattr(self, '_prev_interaction_mode', 'TIME')
            self.set_interaction_mode(prev)
        elif key_name == s.get('keybinds/endless_time', 'Shift+T'):
            self.set_interaction_mode('TIME_ENDLESS')
        elif key_name == s.get('keybinds/endless_mag', 'Shift+F'):
            self.set_interaction_mode('MAG_ENDLESS')
        super().keyReleaseEvent(event)

    def set_interaction_mode(self, mode):
        if mode == 'Y': mode = 'MAG'
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
        if mode == 'ZOOM': self.plot_widget.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == 'MOVE': self.plot_widget.setCursor(Qt.CursorShape.SizeAllCursor)
        elif 'ENDLESS' in mode: self.plot_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        else: self.plot_widget.setCursor(Qt.CursorShape.ArrowCursor)
        
        self.marker_panel.update_mode_ui(mode)
        self.marker_panel.update_headers(mode, self.y_label_text)
        self.update_marker_info()

    def plot_real(self):
        self._update_plot(self.samples.real, "Amplitude (Real)")

    def plot_imag(self):
        self._update_plot(self.samples.imag, "Amplitude (Imag)")

    def plot_abs(self):
        self._update_plot(np.abs(self.samples), "Magnitude")

    def plot_inst_freq(self):
        phase = np.unwrap(np.angle(self.samples))
        freq = np.diff(phase) / (2 * np.pi) * self.rate
        pad_freq = np.concatenate(([freq[0]], freq))
        self._update_plot(pad_freq, "Instantaneous Frequency (Hz)")

    def plot_phase(self):
        self._update_plot(np.angle(self.samples), "Phase (rad)")

    def plot_unwrapped_phase(self):
        self._update_plot(np.unwrap(np.angle(self.samples)), "Unwrapped Phase (rad)")

    def _update_plot(self, data, y_label):
        # 1. Save current view ranges (if not first run)
        old_x_range = None
        if hasattr(self, 'view_box') and self.view_box.viewRect() is not None:
            old_x_range, old_y_range = self.view_box.viewRange()
            self.zoom_y_dict[self.y_label_text] = old_y_range

        # 2. Update state
        self.current_plot_data = data
        self.y_label_text = y_label
        self.marker_panel.update_headers(self.interaction_mode, y_label)
        
        # 3. Clear and Re-plot
        self.plot_item.clear()
        self.plot_item.getAxis('left').setLabel(y_label)
        
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        pen = pg.mkPen(p.accent, width=1.5)
        self.plot_item.plot(self.time_axis, data, pen=pen)
        
        # 4. Restore markers
        for m in self.markers_time: 
            m.setPen(pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)
            
        active_y = self.markers_y_dict.get(y_label, [])
        for m in active_y:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)
            
        active_y_endless = self.markers_y_endless_dict.get(y_label, [])
        for m in active_y_endless:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)

        for m in self.markers_time_endless:
            m.setPen(pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)
        
        # 5. Constraints
        t_start, t_end = self.time_axis[0], self.time_axis[-1]
        t_total = t_end - t_start
        t_pad = t_total * 0.01
        
        y_min_data, y_max_data = np.min(data), np.max(data)
        y_range_val = y_max_data - y_min_data
        if y_range_val == 0: y_range_val = 1.0 
        y_pad = y_range_val * 0.05
        
        # IMPORTANT: unset limits temporarily to allow restoring old zoom if it was outside data bounds
        self.view_box.setLimits(xMin=None, xMax=None, yMin=None, yMax=None)
        
        # 6. Restore Zooms
        if y_label in self.zoom_y_dict:
            y_r = self.zoom_y_dict[y_label]
            self.plot_item.setYRange(y_r[0], y_r[1], padding=0)
        else:
            # Fit Y to data if no cached zoom
            self.plot_item.setYRange(y_min_data - y_pad, y_max_data + y_pad, padding=0)

        if old_x_range is not None:
            # Always restore X zoom
            self.plot_item.setXRange(old_x_range[0], old_x_range[1], padding=0)
        else:
            # Initial fit X
            self.plot_item.setXRange(t_start, t_end, padding=0)

        # 7. Finalize limits
        self.view_box.setLimits(xMin=t_start - t_pad, xMax=t_end + t_pad,
                                yMin=y_min_data - y_pad, yMax=y_max_data + y_pad)
        
        # Explicitly update scrollbars
        self.update_scrollbars()

    def update_scrollbars(self):
        if self._block_signals: return
        self._block_signals = True
        
        xr, yr = self.view_box.viewRange()
        
        # Time axis (X)
        t_start, t_end = self.time_axis[0], self.time_axis[-1]
        t_total = t_end - t_start
        if t_total > 0:
            visible_ratio_x = (xr[1] - xr[0]) / t_total
            if visible_ratio_x < 0.999:
                self.x_scroll.show()
                page_step = int(visible_ratio_x * 1000)
                self.x_scroll.setRange(0, 1000 - page_step)
                self.x_scroll.setPageStep(page_step)
                pos = (xr[0] - t_start) / t_total * 1000
                self.x_scroll.setValue(int(pos))
            else:
                self.x_scroll.hide()
        
        # Magnitude axis (Y)
        y_min_data, y_max_data = self._get_y_bounds()
        y_range_total = y_max_data - y_min_data
        if y_range_total > 0:
            visible_ratio_y = (yr[1] - yr[0]) / y_range_total
            if visible_ratio_y < 0.999:
                self.y_scroll.show()
                page_step = int(visible_ratio_y * 1000)
                self.y_scroll.setRange(0, 1000 - page_step)
                self.y_scroll.setPageStep(page_step)
                # Value 0 is TOP (y_max), Max is BOTTOM (y_min)
                pos_from_bottom = (yr[0] - y_min_data) / y_range_total * 1000
                inv_pos = 1000 - page_step - int(pos_from_bottom)
                self.y_scroll.setValue(inv_pos)
            else:
                self.y_scroll.hide()
                
        self._block_signals = False

    def scroll_view(self):
        if self._block_signals: return
        self._block_signals = True
        
        val_x = self.x_scroll.value()
        val_y = self.y_scroll.value()
        
        t_start, t_end = self.time_axis[0], self.time_axis[-1]
        t_total = t_end - t_start
        
        y_min_data, y_max_data = self._get_y_bounds()
        y_range_total = y_max_data - y_min_data
        
        xr, yr = self.view_box.viewRange()
        width = xr[1] - xr[0]
        height = yr[1] - yr[0]
        
        new_left = t_start + (val_x / 1000.0) * t_total
        # Flip Y back: top of scrollbar is y_max
        inv_val_y = 1000 - self.y_scroll.pageStep() - val_y
        new_bottom = y_min_data + (inv_val_y / 1000.0) * y_range_total
        
        if self.x_scroll.isVisible():
            self.plot_item.setXRange(new_left, new_left + width, padding=0)
        if self.y_scroll.isVisible():
            self.plot_item.setYRange(new_bottom, new_bottom + height, padding=0)
            
        self._block_signals = False

    # --- Marker Logic ---
    def handle_lock_change(self, lock_type, checked):
        if not checked: 
            self.marker_panel.btn_lock_delta.setText(f"Delta (Δ) 🔓")
            self.marker_panel.btn_lock_center.setText(f"Center 🔓")
            return
            
        if lock_type == 'delta':
            self.marker_panel.btn_lock_center.blockSignals(True)
            self.marker_panel.btn_lock_center.setChecked(False)
            self.marker_panel.btn_lock_center.setText("Center 🔓")
            self.marker_panel.btn_lock_center.blockSignals(False)
            self.marker_panel.btn_lock_delta.setText(f"Delta (Δ) 🔒")
        else:
            self.marker_panel.btn_lock_delta.blockSignals(True)
            self.marker_panel.btn_lock_delta.setChecked(False)
            self.marker_panel.btn_lock_delta.setText("Delta (Δ) 🔓")
            self.marker_panel.btn_lock_delta.blockSignals(False)
            self.marker_panel.btn_lock_center.setText(f"Center 🔒")

    def _get_y_bounds(self):
        y_min = np.min(self.current_plot_data)
        y_max = np.max(self.current_plot_data)
        return y_min, y_max

    def place_marker(self, scene_pos, drag_mode=False):
        v_pos = self.view_box.mapSceneToView(scene_pos)
        is_time = (self.interaction_mode in ['TIME', 'TIME_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        
        # Clamp to bounds
        if is_time:
            t_min, t_max = self.time_axis[0], self.time_axis[-1]
            val = max(t_min, min(t_max, v_pos.x()))
        else:
            y_min, y_max = self._get_y_bounds()
            val = max(y_min, min(y_max, v_pos.y()))
        
        if is_endless:
            active_markers = self.markers_time_endless if is_time else self.markers_y_endless_dict[self.y_label_text]
        else:
            active_markers = self.markers_time if is_time else self.markers_y_dict[self.y_label_text]
        
        # 1. Shift pair if locked (Only for fixed modes)
        if not is_endless and len(active_markers) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
            m1_pos, m2_pos = active_markers[0].value(), active_markers[1].value()
            target = active_markers[0] if abs(val-m1_pos) < abs(val-m2_pos) else active_markers[1]
            other = active_markers[1] if target == active_markers[0] else active_markers[0]
            
            shift = val - target.value()
            if self.marker_panel.btn_lock_delta.isChecked():
                new_t, new_o = val, other.value() + shift
                if is_time:
                    t_min, t_max = self.time_axis[0], self.time_axis[-1]
                    if t_min <= new_t <= t_max and t_min <= new_o <= t_max:
                        target.setValue(new_t); other.setValue(new_o)
                else:
                    y_min, y_max = self._get_y_bounds()
                    if y_min <= new_t <= y_max and y_min <= new_o <= y_max:
                        target.setValue(new_t); other.setValue(new_o)
            elif self.marker_panel.btn_lock_center.isChecked():
                ct = (m1_pos + m2_pos) / 2
                new_o = 2 * ct - val
                if is_time:
                    t_min, t_max = self.time_axis[0], self.time_axis[-1]
                    if t_min <= val <= t_max and t_min <= new_o <= t_max:
                        target.setValue(val); other.setValue(new_o)
                else:
                    y_min, y_max = self._get_y_bounds()
                    if y_min <= val <= y_max and y_min <= new_o <= y_max:
                        target.setValue(val); other.setValue(new_o)
            
            if drag_mode: self.active_drag_marker = target
            self.update_marker_info()
            return

        # 2. Hit test
        found_marker = None
        for m in active_markers:
            # Check if marker is vertical (Time) or horizontal (Magnitude)
            m_is_time = m in self.markers_time or m in self.markers_time_endless
            m_pixel = self.view_box.mapViewToScene(pg.Point(m.value(), 0) if m_is_time else pg.Point(0, m.value()))
            dist = abs(scene_pos.x() - m_pixel.x()) if m_is_time else abs(scene_pos.y() - m_pixel.y())
            if dist < 20: found_marker = m; break
        
        if found_marker:
            found_marker.setValue(val)
            if drag_mode: self.active_drag_marker = found_marker
            self.update_marker_info()
            return

        # 3. Add brand new
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        color = p.marker_time if is_time else p.marker_mag
        orient = 90 if is_time else 0
        
        if is_endless:
            # Endless Mode: Just add more markers
            pass
        elif len(active_markers) >= 2:
            # Fixed Mode: Pop the oldest
            old_m = active_markers.pop(0)
            self.plot_item.removeItem(old_m)

        new_m = pg.InfiniteLine(pos=val, angle=orient, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine), movable=False)
        new_m.setZValue(100)
        
        if is_endless:
            label_text = f"M{len(active_markers)+1}"
            new_m.label = pg.InfLineLabel(new_m, text=label_text, position=0.95, rotateAxis=(1, 0), anchor=(1, 1))
            new_m.label.setColor(color)

        active_markers.append(new_m)
        self.plot_item.addItem(new_m, ignoreBounds=True)
        if drag_mode: self.active_drag_marker = new_m
        self.update_marker_info()

    def update_drag(self, scene_pos):
        if not self.active_drag_marker: return
        v_pos = self.view_box.mapSceneToView(scene_pos)
        is_time = (self.active_drag_marker in self.markers_time or self.active_drag_marker in self.markers_time_endless)
        is_endless = 'ENDLESS' in self.interaction_mode
        
        if is_time:
            t_min, t_max = self.time_axis[0], self.time_axis[-1]
            val = max(t_min, min(t_max, v_pos.x()))
        else:
            y_min, y_max = self._get_y_bounds()
            val = max(y_min, min(y_max, v_pos.y()))
        
        if is_endless:
            active_markers = self.markers_time_endless if is_time else self.markers_y_endless_dict[self.y_label_text]
        else:
            active_markers = self.markers_time if is_time else self.markers_y_dict[self.y_label_text]
        
        if not is_endless and len(active_markers) == 2:
            other = active_markers[0] if active_markers[1] == self.active_drag_marker else active_markers[1]
            shift = val - self.active_drag_marker.value()
            if self.marker_panel.btn_lock_delta.isChecked():
                new_o = other.value() + shift
                if is_time:
                    t_min, t_max = self.time_axis[0], self.time_axis[-1]
                    if t_min <= val <= t_max and t_min <= new_o <= t_max:
                        self.active_drag_marker.setValue(val); other.setValue(new_o)
                else:
                    y_min, y_max = self._get_y_bounds()
                    if y_min <= val <= y_max and y_min <= new_o <= y_max:
                        self.active_drag_marker.setValue(val); other.setValue(new_o)
            elif self.marker_panel.btn_lock_center.isChecked():
                ct = (self.active_drag_marker.value() + other.value()) / 2
                new_o = 2 * ct - val
                if is_time:
                    t_min, t_max = self.time_axis[0], self.time_axis[-1]
                    if t_min <= val <= t_max and t_min <= new_o <= t_max:
                        self.active_drag_marker.setValue(val); other.setValue(new_o)
                else:
                    y_min, y_max = self._get_y_bounds()
                    if y_min <= val <= y_max and y_min <= new_o <= y_max:
                        self.active_drag_marker.setValue(val); other.setValue(new_o)
            else: self.active_drag_marker.setValue(val)
        else: self.active_drag_marker.setValue(val)
        self.update_marker_info()

    def update_marker_info(self):
        is_time = (self.interaction_mode in ['TIME', 'TIME_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        
        if is_endless:
            active_markers = self.markers_time_endless if is_time else self.markers_y_endless_dict[self.y_label_text]
            self.marker_panel.update_endless_list(active_markers, self.interaction_mode)
            # Re-label just in case
            for i, m in enumerate(active_markers):
                if hasattr(m, 'label'): m.label.setFormat(f"M{i+1}")
            return

        active_markers = self.markers_time if is_time else self.markers_y_dict[self.y_label_text]
        sorted_m = sorted(active_markers, key=lambda m: m.value())
        
        self.marker_panel.update_headers(self.interaction_mode, self.y_label_text)
        
        # Clear fields
        for widget in self.marker_panel.m_widgets:
            for k in widget: widget[k].blockSignals(True); widget[k].clear(); widget[k].blockSignals(False)
        for w in [self.marker_panel.delta_v1, self.marker_panel.delta_v2,
                  self.marker_panel.center_v1, self.marker_panel.center_v2]:
            w.blockSignals(True); w.clear(); w.blockSignals(False)

        if not sorted_m: return

        # Update columns
        for i in range(2):
            if i < len(sorted_m):
                m_val = sorted_m[i].value()
                self.marker_panel.m_widgets[i]['v1'].blockSignals(True)
                self.marker_panel.m_widgets[i]['v2'].blockSignals(True)
                
                prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if is_time else int(self.settings_mgr.get("ui/label_precision", 6))
                self.marker_panel.m_widgets[i]['v1'].setText(f"{m_val:.{prec1}f}")
                
                if is_time:
                    abs_s = int(round(m_val * self.rate)) + 1
                    self.marker_panel.m_widgets[i]['v2'].setText(f"{abs_s}")
                
                self.marker_panel.m_widgets[i]['v1'].blockSignals(False)
                self.marker_panel.m_widgets[i]['v2'].blockSignals(False)

        # Update Delta/Center
        if len(sorted_m) == 2:
            v1, v2 = sorted_m[0].value(), sorted_m[1].value()
            prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if is_time else int(self.settings_mgr.get("ui/label_precision", 6))
            
            self.marker_panel.delta_v1.blockSignals(True)
            self.marker_panel.center_v1.blockSignals(True)
            self.marker_panel.delta_v1.setText(f"{abs(v2-v1):.{prec1}f}")
            self.marker_panel.center_v1.setText(f"{(v1+v2)/2:.{prec1}f}")
            self.marker_panel.delta_v1.blockSignals(False)
            self.marker_panel.center_v1.blockSignals(False)
            
            if is_time:
                s1, s2 = int(round(v1 * self.rate)) + 1, int(round(v2 * self.rate)) + 1
                self.marker_panel.delta_v2.blockSignals(True)
                self.marker_panel.center_v2.blockSignals(True)
                self.marker_panel.delta_v2.setText(f"{abs(s2-s1)+1}")
                # Center sample
                cv = (v1+v2)/2
                self.marker_panel.center_v2.setText(f"{int(round(cv*self.rate))+1}")
                self.marker_panel.delta_v2.blockSignals(False)
                self.marker_panel.center_v2.blockSignals(False)

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        is_time = (self.interaction_mode in ['TIME', 'TIME_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        
        try:
            val = float(sender.text())
            if is_time:
                t_min, t_max = self.time_axis[0], self.time_axis[-1]
                curr_min, curr_max = t_min, t_max
            else:
                y_min, y_max = self._get_y_bounds()
                curr_min, curr_max = y_min, y_max

            if name.startswith('em_'):
                # Endless edit
                parts = name.split('_')
                idx = int(parts[1])
                unit = parts[2]
                active_list = self.markers_time_endless if is_time else self.markers_y_endless_dict[self.y_label_text]
                if idx < len(active_list):
                    m = active_list[idx]
                    if is_time:
                        new_p = np.clip(val if unit == 'sec' else val, curr_min, curr_max)
                        if unit == 'sam':
                             new_p = np.clip((val - 1) / self.rate, curr_min, curr_max)
                    else:
                        new_p = np.clip(val, curr_min, curr_max)
                    m.setPos(new_p)
                self.update_marker_info()
                return

            # Fixed marker edit logic...
            active_markers = self.markers_time if is_time else self.markers_y_dict[self.y_label_text]
            sorted_markers = sorted(active_markers, key=lambda m: m.value())

            if name.startswith('m'):
                idx = int(name[1])
                if idx >= len(sorted_markers): return
                
                new_p = val
                if 'v2' in name and is_time:
                    new_p = (val - 1.0) / self.rate
                
                new_p = np.clip(new_p, curr_min, curr_max)

                if len(sorted_markers) == 2:
                    other_idx = 1 - idx
                    shift = new_p - sorted_markers[idx].value()
                    if self.marker_panel.btn_lock_delta.isChecked():
                        new_o = sorted_markers[other_idx].value() + shift
                        if curr_min <= new_o <= curr_max:
                            sorted_markers[idx].setValue(new_p); sorted_markers[other_idx].setValue(new_o)
                    elif self.marker_panel.btn_lock_center.isChecked():
                        ct = (sorted_markers[0].value() + sorted_markers[1].value()) / 2
                        new_o = 2 * ct - new_p
                        if curr_min <= new_o <= curr_max:
                            sorted_markers[idx].setValue(new_p); sorted_markers[other_idx].setValue(new_o)
                    else: sorted_markers[idx].setValue(new_p)
                else: sorted_markers[idx].setValue(new_p)
                
            elif len(sorted_markers) == 2:
                p1, p2 = sorted_markers[0].value(), sorted_markers[1].value()
                if 'delta' in name:
                    dv = val
                    if 'v2' in name and is_time: dv = (val - 1) / self.rate
                    sorted_markers[0].setValue((p1+p2)/2 - dv/2); sorted_markers[1].setValue((p1+p2)/2 + dv/2)
                elif 'center' in name:
                    ct = val
                    if 'v2' in name and is_time: ct = (val - 1) / self.rate
                    dv = abs(p2-p1)
                    sorted_markers[0].setValue(ct - dv/2); sorted_markers[1].setValue(ct + dv/2)
                        
            self.update_marker_info()
        except: pass

    def handle_marker_clear(self, mode):
        if mode == 'TIME':
            for m in self.markers_time: self.plot_item.removeItem(m)
            self.markers_time = []
        elif mode == 'TIME_ENDLESS':
            for m in self.markers_time_endless: self.plot_item.removeItem(m)
            self.markers_time_endless = []
        elif mode == 'MAG_ENDLESS':
            for m in self.markers_y_endless_dict[self.y_label_text]: self.plot_item.removeItem(m)
            self.markers_y_endless_dict[self.y_label_text] = []
        else: # 'Y'
            for m in self.markers_y_dict[self.y_label_text]: self.plot_item.removeItem(m)
            self.markers_y_dict[self.y_label_text] = []
        self.update_marker_info()

    def remove_marker_item(self, marker, mode):
        if marker in self.plot_item.items():
            self.plot_item.removeItem(marker)
        
        is_time = 'TIME' in mode
        active_list = self.markers_time_endless if is_time else self.markers_y_endless_dict[self.y_label_text]
        
        if marker in active_list:
            active_list.remove(marker)
            # Re-label remaining
            for i, m in enumerate(active_list):
                if hasattr(m, 'label'):
                    m.label.setFormat(f"M{i+1}")
        
        self.update_marker_info()

    def reset_zoom(self):
        self.plot_item.autoRange()

    def handle_zoom_rectangle(self, rect, zoom_type):
        if zoom_type == 'X_ONLY': self.plot_item.setXRange(rect.left(), rect.right(), padding=0)
        elif zoom_type == 'Y_ONLY': self.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
        else: self.plot_item.setRange(rect, padding=0)

    def handle_move_drag(self, pos, is_start=False, is_finish=False):
        if is_start: self.last_move_scene_pos = pos; return
        if self.last_move_scene_pos is None: return
        delta = pos - self.last_move_scene_pos
        self.view_box.translateBy(x=-self.view_box.mapSceneToView(delta).x() + self.view_box.mapSceneToView(pg.Point(0,0)).x(),
                                  y=-self.view_box.mapSceneToView(delta).y() + self.view_box.mapSceneToView(pg.Point(0,0)).y())
        self.last_move_scene_pos = pos
        if is_finish: self.last_move_scene_pos = None

    def fit_to_markers(self):
        is_time = (self.interaction_mode in ['TIME', 'TIME_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        if is_endless:
            active_markers = self.markers_time_endless if is_time else self.markers_y_endless_dict[self.y_label_text]
        else:
            active_markers = self.markers_time if is_time else self.markers_y_dict[self.y_label_text]
            
        if len(active_markers) >= 2:
            sorted_m = sorted(active_markers, key=lambda m: m.value())
            v1, v2 = sorted_m[0].value(), sorted_m[-1].value()
            if is_time:
                self.plot_item.setXRange(v1, v2, padding=0.05)
            else:
                self.plot_item.setYRange(v1, v2, padding=0.05)

    def refresh_theme(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        
        self.update_toolbar_style()
        self.refresh_plot_style()
        self.marker_panel.refresh_theme()
        
        # Update scrollbars
        sb_style = get_scrollbar_stylesheet(p)
        self.x_scroll.setStyleSheet(sb_style)
        self.y_scroll.setStyleSheet(sb_style)
        
        # Re-plot to refresh curve and marker colors
        self._update_plot(self.current_plot_data, self.y_label_text)

    def update_toolbar_style(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.toolbar.setStyleSheet(f"""
            QFrame#td_toolbar {{ background-color: {p.bg_sidebar}; border-radius: 6px; border: 1px solid {p.border}; }}
            QPushButton {{ background-color: {p.bg_widget}; padding: 5px 15px; border-radius: 3px; color: {p.text_main}; }}
            QPushButton:hover {{ background-color: {p.border_light}; }}
            QPushButton:checked {{ background-color: {p.accent_dim}; color: {p.accent}; border: 1px solid {p.accent}; }}
        """)

    def refresh_plot_style(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.plot_widget.setBackground(p.plot_bg)
        
        from PyQt6.QtGui import QFont
        font = QFont()
        font.setPointSize(int(self.parent_window.settings_mgr.get("ui/axis_font_size", 10)))
        
        grid_enabled = bool(self.parent_window.settings_mgr.get("ui/grid_enabled", True))
        grid_alpha = int(self.parent_window.settings_mgr.get("ui/grid_alpha", 30)) / 100.0
        
        self.plot_item.getAxis('left').setTickFont(font)
        self.plot_item.getAxis('bottom').setTickFont(font)
        self.plot_widget.showGrid(x=grid_enabled, y=grid_enabled, alpha=grid_alpha)
        
        self.plot_item.getAxis('left').setPen(p.text_dim)
        self.plot_item.getAxis('bottom').setPen(p.text_dim)

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLabel, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal
from .widgets import CustomViewBox
from .time_domain_marker_panel import TimeDomainMarkerPanel

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
        self.is_spectrogram = False
        self.interaction_mode = 'TIME'
        self.zoom_mode = False
        self.active_drag_marker = None
        self.markers_time = []
        self.markers_y = [] # Magnitude markers (Horizontal)
        self.y_label_text = "Amplitude (Real)"
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(5)
        
        # --- Marker Panel ---
        self.marker_panel = TimeDomainMarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.layout.addWidget(self.marker_panel)
        
        # --- Toolbar ---
        self.toolbar = QFrame()
        self.toolbar.setObjectName("td_toolbar")
        self.toolbar.setStyleSheet("""
            QFrame#td_toolbar { background-color: #1a1a1a; border-radius: 6px; border: 1px solid #333; }
            QPushButton { background-color: #252525; padding: 5px 15px; border-radius: 3px; color: #ccc; }
            QPushButton:hover { background-color: #333; }
            QPushButton:checked { background-color: #004488; color: #00aaff; border: 1px solid #00aaff; }
        """)
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.toolbar_layout.addWidget(QLabel("Plot Mode:"))
        
        self.mode_group = QButtonGroup(self)
        self.modes = [
            ("Real (I)", self.plot_real),
            ("Imag (Q)", self.plot_imag),
            ("Absolute", self.plot_abs),
            ("Inst. Freq", self.plot_inst_freq)
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
        
        self.layout.addWidget(self.toolbar)
        
        # --- Plot ---
        self.view_box = CustomViewBox(self)
        self.plot_widget = pg.PlotWidget(viewBox=self.view_box)
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_widget.setBackground('#121212')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.getAxis('bottom').setLabel('Time', units='s')
        self.plot_widget.getAxis('left').setPen('#666')
        self.plot_widget.getAxis('bottom').setPen('#666')
        self.layout.addWidget(self.plot_widget)
        
        self.time_axis = np.linspace(start_time, end_time, len(samples))
        self.plot_real() # Default plot
        self.set_interaction_mode('TIME')

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_T:
            self.set_interaction_mode('TIME')
        elif event.key() == Qt.Key.Key_F or event.key() == Qt.Key.Key_M:
            self.set_interaction_mode('MAG')
        elif event.key() == Qt.Key.Key_Control:
            self.set_interaction_mode('ZOOM')
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Control:
            # Revert to previous non-zoom mode
            self.set_interaction_mode('TIME')
        super().keyReleaseEvent(event)

    def set_interaction_mode(self, mode):
        # Normalize mode string (MAG vs Y)
        if mode == 'MAG': pass
        elif mode == 'Y': mode = 'MAG'
        
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
        if mode == 'ZOOM':
            self.plot_widget.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == 'MOVE':
            self.plot_widget.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.plot_widget.setCursor(Qt.CursorShape.ArrowCursor)
        
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
        self._update_plot(freq, "Instantaneous Frequency (Hz)", use_diff_time=True)

    def _update_plot(self, data, y_label, use_diff_time=False):
        self.y_label_text = y_label
        self.marker_panel.update_headers(self.interaction_mode, y_label)
        self.plot_item.clear()
        self.plot_item.getAxis('left').setLabel(y_label)
        
        # Restore markers
        for m in self.markers_time: self.plot_item.addItem(m)
        for m in self.markers_y: self.plot_item.addItem(m)
        
        x_data = self.time_axis
        if use_diff_time:
            x_data = (self.time_axis[:-1] + self.time_axis[1:]) / 2
            
        pen = pg.mkPen('#00aaff', width=1.5)
        self.plot_item.plot(x_data, data, pen=pen)
        self.plot_item.autoRange()

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

    def place_marker(self, scene_pos, drag_mode=False):
        v_pos = self.view_box.mapSceneToView(scene_pos)
        is_time = (self.interaction_mode == 'TIME')
        val = v_pos.x() if is_time else v_pos.y()
        active_markers = self.markers_time if is_time else self.markers_y
        
        curr_min = 0.0 if is_time else -1e12
        curr_max = getattr(self.parent_window, 'time_duration', 1e9) if is_time else 1e12
        
        # 1. Shift pair if locked
        if len(active_markers) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
            m1_pos, m2_pos = active_markers[0].value(), active_markers[1].value()
            dist1, dist2 = abs(val - m1_pos), abs(val - m2_pos)
            target = active_markers[0] if dist1 < dist2 else active_markers[1]
            other = active_markers[1] if dist1 < dist2 else active_markers[0]
            
            shift = val - target.value()
            if self.marker_panel.btn_lock_delta.isChecked():
                new_t, new_o = val, other.value() + shift
                if curr_min <= new_t <= curr_max and curr_min <= new_o <= curr_max:
                    target.setValue(new_t); other.setValue(new_o)
            elif self.marker_panel.btn_lock_center.isChecked():
                center = (m1_pos + m2_pos) / 2
                new_o = 2 * center - val
                if curr_min <= val <= curr_max and curr_min <= new_o <= curr_max:
                    target.setValue(val); other.setValue(new_o)
            
            if drag_mode: self.active_drag_marker = target
            self.update_marker_info()
            return

        # 2. Hit test for single marker
        pixel_pos = scene_pos
        found_marker = None
        for m in active_markers:
            m_pixel = self.view_box.mapViewToScene(pg.Point(m.value(), 0) if is_time else pg.Point(0, m.value()))
            dist = abs(pixel_pos.x() - m_pixel.x()) if is_time else abs(pixel_pos.y() - m_pixel.y())
            if dist < 20:
                found_marker = m
                break
        
        if found_marker:
            found_marker.setValue(val)
            if drag_mode: self.active_drag_marker = found_marker
            self.update_marker_info()
            return

        # 3. Add brand new
        if len(active_markers) >= 2:
            old = active_markers.pop(0)
            self.plot_item.removeItem(old)
            
        orient = 'vertical' if is_time else 'horizontal'
        color = '#00ff00' if is_time else '#ffaa00'
        new_m = pg.InfiniteLine(pos=val, angle=90 if orient=='vertical' else 0, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine), movable=False)
        active_markers.append(new_m)
        self.plot_item.addItem(new_m, ignoreBounds=True)
        if drag_mode: self.active_drag_marker = new_m
        self.update_marker_info()

    def update_drag(self, scene_pos):
        if not self.active_drag_marker: return
        v_pos = self.view_box.mapSceneToView(scene_pos)
        is_time = self.active_drag_marker in self.markers_time
        val = v_pos.x() if is_time else v_pos.y()
        active_markers = self.markers_time if is_time else self.markers_y
        
        curr_min = 0.0 if is_time else -1e12
        curr_max = getattr(self.parent_window, 'time_duration', 1e9) if is_time else 1e12

        if len(active_markers) == 2:
            other = active_markers[0] if active_markers[1] == self.active_drag_marker else active_markers[1]
            shift = val - self.active_drag_marker.value()
            if self.marker_panel.btn_lock_delta.isChecked():
                new_o = other.value() + shift
                if curr_min <= val <= curr_max and curr_min <= new_o <= curr_max:
                    self.active_drag_marker.setValue(val); other.setValue(new_o)
            elif self.marker_panel.btn_lock_center.isChecked():
                ct = (self.active_drag_marker.value() + other.value()) / 2
                new_o = 2 * ct - val
                if curr_min <= val <= curr_max and curr_min <= new_o <= curr_max:
                    self.active_drag_marker.setValue(val); other.setValue(new_o)
            else: self.active_drag_marker.setValue(val)
        else: self.active_drag_marker.setValue(val)
        self.update_marker_info()

    def update_marker_info(self):
        is_time = (self.interaction_mode == 'TIME')
        active_markers = self.markers_time if is_time else self.markers_y
        sorted_m = sorted(active_markers, key=lambda m: m.value())
        
        # Clear fields
        for widget in self.marker_panel.m_widgets:
            for k in widget: widget[k].blockSignals(True); widget[k].clear(); widget[k].blockSignals(False)
        for w in [self.marker_panel.delta_v1, self.marker_panel.delta_v2,
                  self.marker_panel.center_v1, self.marker_panel.center_v2]:
            w.blockSignals(True); w.clear(); w.blockSignals(False)

        # Update columns
        for i in range(2):
            if i < len(sorted_m):
                m_val = sorted_m[i].value()
                self.marker_panel.m_widgets[i]['v1'].blockSignals(True)
                self.marker_panel.m_widgets[i]['v2'].blockSignals(True)
                
                # Precisions based on mode
                prec1 = 9 if is_time else 6
                self.marker_panel.m_widgets[i]['v1'].setText(f"{m_val:.{prec1}f}")
                
                if is_time:
                    s = int(round(m_val * self.rate)) + 1
                    self.marker_panel.m_widgets[i]['v2'].setText(f"{s}")
                
                self.marker_panel.m_widgets[i]['v1'].blockSignals(False)
                self.marker_panel.m_widgets[i]['v2'].blockSignals(False)

        # Update Delta/Center
        if len(sorted_m) == 2:
            v1, v2 = sorted_m[0].value(), sorted_m[1].value()
            self.marker_panel.delta_v1.blockSignals(True)
            self.marker_panel.center_v1.blockSignals(True)
            
            prec1 = 9 if is_time else 6
            self.marker_panel.delta_v1.setText(f"{abs(v2-v1):.{prec1}f}")
            self.marker_panel.center_v1.setText(f"{(v1+v2)/2:.{prec1}f}")
            
            if is_time:
                s1, s2 = int(round(v1 * self.rate)) + 1, int(round(v2 * self.rate)) + 1
                self.marker_panel.delta_v2.blockSignals(True)
                self.marker_panel.center_v2.blockSignals(True)
                self.marker_panel.delta_v2.setText(f"{abs(s2-s1)+1}")
                self.marker_panel.center_v2.setText(f"{int(round(((v1+v2)/2)*self.rate))+1}")
                self.marker_panel.delta_v2.blockSignals(False)
                self.marker_panel.center_v2.blockSignals(False)

            self.marker_panel.delta_v1.blockSignals(False)
            self.marker_panel.center_v1.blockSignals(False)

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        is_time = (self.interaction_mode == 'TIME')
        active_markers = self.markers_time if is_time else self.markers_y
        sorted_markers = sorted(active_markers, key=lambda m: m.value())
        
        curr_min = 0.0 if is_time else -1e12
        curr_max = getattr(self.parent_window, 'time_duration', 1e9) if is_time else 1e12

        try:
            val = float(sender.text())
            if name.startswith('m'):
                idx = int(name[1])
                if idx >= len(sorted_markers): return
                
                new_p = val
                if 'v2' in name and is_time:
                    new_p = (val - 1.0) / self.rate
                
                if len(sorted_markers) == 2:
                    other_idx = 1 - idx
                    shift = new_p - sorted_markers[idx].value()
                    if self.marker_panel.btn_lock_delta.isChecked():
                        other_new = sorted_markers[other_idx].value() + shift
                        if curr_min <= new_p <= curr_max and curr_min <= other_new <= curr_max:
                            sorted_markers[idx].setValue(new_p); sorted_markers[other_idx].setValue(other_new)
                    elif self.marker_panel.btn_lock_center.isChecked():
                        ct = (sorted_markers[0].value() + sorted_markers[1].value()) / 2
                        other_new = 2 * ct - new_p
                        if curr_min <= new_p <= curr_max and curr_min <= other_new <= curr_max:
                            sorted_markers[idx].setValue(new_p); sorted_markers[other_idx].setValue(other_new)
                    else: sorted_markers[idx].setValue(new_p)
                else: sorted_markers[idx].setValue(new_p)
                
            elif len(sorted_markers) == 2:
                p1, p2 = sorted_markers[0].value(), sorted_markers[1].value()
                if 'delta' in name:
                    dv = val
                    if 'v2' in name and is_time:
                        dv = (val - 1) / self.rate
                    m1_new, m2_new = (p1+p2)/2 - dv/2, (p1+p2)/2 + dv/2
                    if curr_min <= m1_new and m2_new <= curr_max:
                        sorted_markers[0].setValue(m1_new); sorted_markers[1].setValue(m2_new)
                elif 'center' in name:
                    ct = val
                    if 'v2' in name and is_time:
                        ct = (val - 1) / self.rate
                    dv = abs(p2-p1)
                    m1_new, m2_new = ct - dv/2, ct + dv/2
                    if curr_min <= m1_new and m2_new <= curr_max:
                        sorted_markers[0].setValue(m1_new); sorted_markers[1].setValue(m2_new)
                        
            self.update_marker_info()
        except ValueError: self.update_marker_info()

    def handle_marker_clear(self, mode):
        # controller handles 'TIME' and 'Y'
        markers = self.markers_time if mode == 'TIME' else self.markers_y
        for m in markers: self.plot_item.removeItem(m)
        markers.clear()
        self.update_marker_info()

    def reset_zoom(self):
        self.plot_item.autoRange()

    def handle_zoom_rectangle(self, rect, zoom_type):
        if zoom_type == 'X_ONLY':
            self.plot_item.setXRange(rect.left(), rect.right(), padding=0)
        elif zoom_type == 'Y_ONLY':
            self.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
        else:
            self.plot_item.setRange(rect, padding=0)

    def handle_move_drag(self, pos, is_start=False, is_finish=False):
        if is_start:
            self.last_move_scene_pos = pos
            return
        if self.last_move_scene_pos is None: return
        
        delta = pos - self.last_move_scene_pos
        self.view_box.translateBy(x=-self.view_box.mapSceneToView(delta).x() + self.view_box.mapSceneToView(pg.Point(0,0)).x(),
                                  y=-self.view_box.mapSceneToView(delta).y() + self.view_box.mapSceneToView(pg.Point(0,0)).y())
        self.last_move_scene_pos = pos
        if is_finish: self.last_move_scene_pos = None

    def fit_to_markers(self):
        m = self.markers_time if self.interaction_mode == 'TIME' else self.markers_y
        if len(m) == 2:
            v1, v2 = m[0].value(), m[1].value()
            if self.interaction_mode == 'TIME':
                self.plot_item.setXRange(min(v1, v2), max(v1, v2), padding=0)
            else:
                self.plot_item.setYRange(min(v1, v2), max(v1, v2), padding=0)

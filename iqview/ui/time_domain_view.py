import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLabel, QFrame)
from PyQt6.QtCore import Qt

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
    def __init__(self, samples, start_time, sample_rate, parent=None):
        super().__init__(parent)
        self.samples = samples # Complex numpy array
        self.start_time = start_time
        self.rate = sample_rate
        self.is_spectrogram = False
        self.interaction_mode = 'TIME'
        self.zoom_mode = False
        self.active_drag_marker = None
        self.markers_time = []
        self.markers_y = []
        self.y_label = "Amplitude (Real)"
        
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

    def set_interaction_mode(self, mode):
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
        if mode == 'ZOOM':
            self.plot_widget.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == 'MOVE':
            self.plot_widget.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.plot_widget.setCursor(Qt.CursorShape.ArrowCursor)
        self.marker_panel.update_mode_ui(mode)

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
        self.y_label = y_label
        self.marker_panel.set_y_label(y_label)
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
    def place_marker(self, scene_pos, drag_mode=False):
        v_pos = self.view_box.mapSceneToView(scene_pos)
        val = v_pos.x() if self.interaction_mode == 'TIME' else v_pos.y()
        markers = self.markers_time if self.interaction_mode == 'TIME' else self.markers_y
        
        # Hit test (20px threshold)
        pixel_pos = scene_pos
        found_marker = None
        for m in markers:
            m_pixel = self.view_box.mapViewToScene(pg.Point(m.value(), 0) if self.interaction_mode == 'TIME' else pg.Point(0, m.value()))
            dist = abs(pixel_pos.x() - m_pixel.x()) if self.interaction_mode == 'TIME' else abs(pixel_pos.y() - m_pixel.y())
            if dist < 20:
                found_marker = m
                break
        
        if found_marker:
            if drag_mode: self.active_drag_marker = found_marker
            return

        if len(markers) >= 2:
            old = markers.pop(0)
            self.plot_item.removeItem(old)
            
        orient = 'vertical' if self.interaction_mode == 'TIME' else 'horizontal'
        color = '#00ff00' if self.interaction_mode == 'TIME' else '#ffaa00'
        new_m = pg.InfiniteLine(pos=val, angle=90 if orient=='vertical' else 0, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine), movable=False)
        markers.append(new_m)
        self.plot_item.addItem(new_m)
        if drag_mode: self.active_drag_marker = new_m
        self.update_marker_info()

    def update_drag(self, scene_pos):
        if not self.active_drag_marker: return
        v_pos = self.view_box.mapSceneToView(scene_pos)
        val = v_pos.x() if self.interaction_mode == 'TIME' else v_pos.y()
        self.active_drag_marker.setValue(val)
        self.update_marker_info()

    def update_marker_info(self):
        for i in range(2):
            # Time Row
            if i < len(self.markers_time):
                t = self.markers_time[i].value()
                self.marker_panel.time_edits[i].setText(f"{t:.9f}")
            else:
                self.marker_panel.time_edits[i].setText("")
            
            # Y Row
            if i < len(self.markers_y):
                y = self.markers_y[i].value()
                self.marker_panel.y_edits[i].setText(f"{y:.6f}")
            else:
                self.marker_panel.y_edits[i].setText("")

        # Delta/Center
        if len(self.markers_time) == 2:
            t1, t2 = self.markers_time[0].value(), self.markers_time[1].value()
            self.marker_panel.delta_t.setText(f"{abs(t2-t1):.9f}")
            self.marker_panel.center_t.setText(f"{(t1+t2)/2:.9f}")
        else:
            self.marker_panel.delta_t.setText(""); self.marker_panel.center_t.setText("")

        if len(self.markers_y) == 2:
            y1, y2 = self.markers_y[0].value(), self.markers_y[1].value()
            self.marker_panel.delta_y.setText(f"{abs(y2-y1):.6f}")
            self.marker_panel.center_y.setText(f"{(y1+y2)/2:.6f}")
        else:
            self.marker_panel.delta_y.setText(""); self.marker_panel.center_y.setText("")

    def marker_edit_finished(self):
        for i in range(2):
            txt_t = self.marker_panel.time_edits[i].text()
            if txt_t and i < len(self.markers_time):
                self.markers_time[i].setValue(float(txt_t))
            
            txt_y = self.marker_panel.y_edits[i].text()
            if txt_y and i < len(self.markers_y):
                self.markers_y[i].setValue(float(txt_y))
        self.update_marker_info()

    def handle_marker_clear(self, mode):
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

import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QProgressBar
from PyQt6.QtCore import pyqtSlot, Qt, QTimer

from utils import FileReaderThread
from .marker_panel import MarkerPanel
from .spectrogram_view import SpectrogramView
from .side_panel import SidePanel

class SpectrogramWindow(QMainWindow):
    def __init__(self, file_path, data_type, sample_rate, center_freq, fft_size, profile_enabled=False):
        super().__init__()
        self.setWindowTitle("IQView - Spectrogram Viewer")
        self.resize(1280, 800)
        
        self.fc = center_freq
        self.rate = sample_rate
        self.fft_size = fft_size
        self.window_type = "Hanning"
        self.overlap_percent = 99.0
        self.file_path = file_path
        self.data_type = data_type
        self.profile_enabled = profile_enabled
        
        self.markers_time = []
        self.markers_freq = []
        self.time_duration = 1.0 # Default until data loads
        self.interaction_mode = 'TIME' # 'TIME', 'FREQ', or 'ZOOM'
        self.zoom_mode = False
        self.is_first_load = True
        self.zoom_history = []
        
        self.grid_time_enabled = False
        self.grid_freq_enabled = False
        self.grid_lines_time = []
        self.grid_lines_freq = []
        self.grid_time_tracking = True
        self.grid_freq_tracking = True
        
        self.last_move_scene_pos = None
        
        self.setup_ui()
        self.start_processing()

    def setup_ui(self):
        # Global Stylesheet / Design Tokens
        self.setStyleSheet("""
            QMainWindow, QWidget#central {
                background-color: #121212;
                color: #e0e0e0;
                font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
            }
            
            QLabel {
                color: #aaaaaa;
            }
            
            QPushButton {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #353535;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
            }
            QPushButton:checked {
                background-color: #004488;
                border-color: #00aaff;
                color: #00aaff;
            }
            
            QLineEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                padding: 4px 8px;
                selection-background-color: #00aaff;
            }
            QLineEdit:focus {
                border-color: #00aaff;
            }
            QLineEdit[readOnly="true"] {
                color: #777777;
                background-color: #151515;
            }
            
            QComboBox {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox:on {
                border-color: #00aaff;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                selection-background-color: #333333;
                border: 1px solid #3d3d3d;
                outline: none;
            }
        """)

        self.central_widget = QWidget()
        self.central_widget.setObjectName("central")
        self.setCentralWidget(self.central_widget)
        
        # Main Horizontal Layout
        self.main_h_layout = QHBoxLayout(self.central_widget)
        self.main_h_layout.setContentsMargins(0, 0, 0, 0)
        self.main_h_layout.setSpacing(0)
        
        # Sidebar
        self.sidebar = SidePanel(self.rate, self.fc, self.fft_size)
        self.sidebar.parametersChanged.connect(self.on_parameters_changed)
        self.main_h_layout.addWidget(self.sidebar)
        
        self.main_v_container = QWidget()
        self.v_layout = QVBoxLayout(self.main_v_container)
        self.v_layout.setContentsMargins(0, 0, 0, 0)
        self.v_layout.setSpacing(0)
        self.main_h_layout.addWidget(self.main_v_container)
        
        # Progress bar - Stealthy slim line
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: transparent;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #00aaff;
            }
        """)
        self.v_layout.addWidget(self.progress_bar)

        self.marker_panel = MarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.v_layout.addWidget(self.marker_panel)
        
        self.spectrogram_view = SpectrogramView(self)
        self.v_layout.addWidget(self.spectrogram_view)
        
        # 1. Immediate internal sync
        self.set_interaction_mode('TIME')
        
        # 2. Delayed UI sync (Wait for event loop to start and QButtonGroup to stabilize)
        QTimer.singleShot(250, lambda: self.set_interaction_mode('TIME'))

    def start_processing(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: transparent; border: none; } QProgressBar::chunk { background-color: #00aaff; }")
        
        self.worker = FileReaderThread(self.file_path, self.data_type, self.fft_size, self.overlap_percent, self.rate, self.profile_enabled, self.window_type)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished_processing.connect(self.display_spectrogram)
        self.worker.start()

    def on_parameters_changed(self, params):
        # Check if we need a full re-processing (DSP params changed)
        needs_reprocess = (self.fft_size != params['fft_size'] or 
                           self.overlap_percent != params['overlap_percent'] or
                           self.window_type != params['window_type'])
        
        old_rate = self.rate
        old_fc = self.fc
        self.rate = params['fs']
        self.fc = params['fc']
        self.fft_size = params['fft_size']
        self.window_type = params['window_type']
        self.overlap_percent = params['overlap_percent']
        
        if needs_reprocess:
            self.start_processing()
        else:
            # Soft update: refresh labels and markers
            if hasattr(self, 'full_spectrogram_cache'):
                # 1. Store old duration for relative coordinate calculation
                old_duration = self.time_duration
                
                # 2. Re-calculate duration based on new rate
                if hasattr(self, 'total_samples_in_cache'):
                    self.time_duration = self.total_samples_in_cache / self.rate
                else:
                    self.time_duration = (old_duration * old_rate) / self.rate

                # 3. Shift view range to keep relative zoom consistent (avoid "stretching and moving")
                vr = self.spectrogram_view.plot_item.viewRange()
                
                # Relative time range [0, 1]
                rel_t_min = vr[0][0] / old_duration
                rel_t_max = vr[0][1] / old_duration
                
                # Relative frequency range [0, 1]
                old_bottom = old_fc - old_rate / 2
                rel_f_min = (vr[1][0] - old_bottom) / old_rate
                rel_f_max = (vr[1][1] - old_bottom) / old_rate
                
                # New bottom
                new_bottom = self.fc - self.rate / 2
                
                # Update viewport to match relative position in new coordinate system
                self.spectrogram_view.plot_item.setXRange(rel_t_min * self.time_duration, rel_t_max * self.time_duration, padding=0)
                self.spectrogram_view.plot_item.setYRange(new_bottom + rel_f_min * self.rate, new_bottom + rel_f_max * self.rate, padding=0)

                # 4. Update time markers to preserve sample position
                for marker in self.markers_time:
                    samples = marker.getYPos() * old_rate # Time is Y coordinate
                    new_t = samples / self.rate
                    marker.setPos(new_t)

                # 5. Final Spectrogram coordinate update
                self.spectrogram_view.update_spectrogram(
                    self.full_spectrogram_cache, self.fc, self.rate, self.time_duration, auto_range=False
                )
            self.update_marker_info()

    def set_interaction_mode(self, mode):
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
        
        # Update cursor
        if mode == 'ZOOM':
            self.spectrogram_view.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.spectrogram_view.setCursor(Qt.CursorShape.ArrowCursor)
            
        # Update table headers
        self.marker_panel.update_headers(mode)
        self.update_marker_info()

    def reset_zoom(self):
        # Save current range before resetting
        self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
        self.spectrogram_view.plot_item.autoRange()

    def handle_zoom_rectangle(self, rect, zoom_type='BOTH'):
        """
        rect is QRectF in view coordinates.
        zoom_type: 'BOTH', 'X_ONLY', or 'Y_ONLY'
        """
        # Save current range before zooming
        self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
        
        # Avoid zero-size or invalid zoom
        if rect.width() <= 0 and zoom_type != 'Y_ONLY': return
        if rect.height() <= 0 and zoom_type != 'X_ONLY': return
            
        if zoom_type == 'Y_ONLY':
            # Zoom only Y (Frequency)
            self.spectrogram_view.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
        elif zoom_type == 'X_ONLY':
            # Zoom only X (Time)
            self.spectrogram_view.plot_item.setXRange(rect.left(), rect.right(), padding=0)
        else:
            # Zoom both
            self.spectrogram_view.plot_item.setRange(rect, padding=0)

    def fit_to_markers(self):
        is_freq = (self.interaction_mode == 'FREQ')
        active_markers = self.markers_freq if is_freq else self.markers_time
        
        if len(active_markers) == 2:
            # Save current range before zooming
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            
            get_pos = lambda m: m.getXPos() if not is_freq else m.getYPos()
            v1 = get_pos(active_markers[0])
            v2 = get_pos(active_markers[1])
            v_min, v_max = min(v1, v2), max(v1, v2)
            
            if is_freq:
                self.spectrogram_view.plot_item.setYRange(v_min, v_max, padding=0)
            else:
                self.spectrogram_view.plot_item.setXRange(v_min, v_max, padding=0)

    def toggle_grid(self, axis, enabled):
        if axis == 'TIME':
            self.grid_time_enabled = enabled
        else:
            self.grid_freq_enabled = enabled
        self.update_grid(axis, force=True)

    def toggle_tracking(self, axis, enabled):
        if axis == 'TIME':
            self.grid_time_tracking = enabled
        else:
            self.grid_freq_tracking = enabled
        self.update_grid(axis, force=True)

    def update_grid(self, axis, force=False):
        is_freq = (axis == 'FREQ')
        enabled = self.grid_freq_enabled if is_freq else self.grid_time_enabled
        tracking = self.grid_freq_tracking if is_freq else self.grid_time_tracking
        active_markers = self.markers_freq if is_freq else self.markers_time
        grid_lines = self.grid_lines_freq if is_freq else self.grid_lines_time
        
        if not enabled:
            # Clear existing if disabled
            for line in grid_lines:
                self.spectrogram_view.plot_item.removeItem(line)
            grid_lines.clear()
            return

        if not tracking and not force:
            return

        # Clear existing before regeneration
        for line in grid_lines:
            self.spectrogram_view.plot_item.removeItem(line)
        grid_lines.clear()

        if len(active_markers) != 2:
            return

        get_pos = lambda m: m.getXPos() if not is_freq else m.getYPos()
        p1 = get_pos(active_markers[0])
        p2 = get_pos(active_markers[1])
        delta = abs(p2 - p1)
        if delta <= 0: return

        angle = 0 if is_freq else 90 # Freq is horizontal (Y), Time is vertical (X)
        f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
        v_min = f_min if is_freq else 0
        v_max = f_max if is_freq else self.time_duration
        
        pen = pg.mkPen(color=(200, 200, 255, 180), width=2, style=Qt.PenStyle.SolidLine)

        # Draw forward (including start p1)
        curr = p1
        while curr <= v_max + 1e-9:
            line = pg.InfiniteLine(pos=curr, angle=angle, pen=pen, movable=False)
            line.setZValue(5)
            self.spectrogram_view.plot_item.addItem(line, ignoreBounds=True)
            grid_lines.append(line)
            curr += delta

        # Draw backward
        curr = p1 - delta
        while curr >= v_min - 1e-9:
            line = pg.InfiniteLine(pos=curr, angle=angle, pen=pen, movable=False)
            line.setZValue(5)
            self.spectrogram_view.plot_item.addItem(line, ignoreBounds=True)
            grid_lines.append(line)
            curr -= delta

    def place_marker(self, scene_pos, drag_mode=False):
        if self.spectrogram_view.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_v = self.spectrogram_view.plot_item.vb.mapSceneToView(scene_pos)
            
            # Determine active markers and bounds based on mode
            if self.interaction_mode == 'TIME':
                active_markers = self.markers_time
                val = float(np.clip(mouse_v.x(), 0, self.time_duration))
                max_bound = self.time_duration
                angle = 90 # Vertical line for constant Time (X)
            elif self.interaction_mode == 'FREQ':
                active_markers = self.markers_freq
                f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
                val = float(np.clip(mouse_v.y(), f_min, f_max))
                angle = 0 # Horizontal line for constant Frequency (Y)
            else:
                return # Should not happen in place_marker

            if len(active_markers) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                m0_pos = active_markers[0].getXPos() if angle == 90 else active_markers[0].getYPos()
                m1_pos = active_markers[1].getXPos() if angle == 90 else active_markers[1].getYPos()
                
                m0_dist = abs(m0_pos - val)
                m1_dist = abs(m1_pos - val)
                
                target = active_markers[0] if m0_dist < m1_dist else active_markers[1]
                other = active_markers[1] if m0_dist < m1_dist else active_markers[0]
                
                old_p = target.getXPos() if angle == 90 else target.getYPos()
                shift = val - old_p
                
                # Check bounds for BOTH markers
                if self.interaction_mode == 'TIME':
                    new_target_p = val
                    new_other_p = other.getYPos() + shift # Time is Y
                    in_bounds = (0 <= new_target_p <= self.time_duration and 0 <= new_other_p <= self.time_duration)
                else:
                    new_target_p = val
                    new_other_p = other.getXPos() + shift # Freq is X
                    in_bounds = (f_min <= new_target_p <= f_max and f_min <= new_other_p <= f_max)

                if self.marker_panel.btn_lock_delta.isChecked():
                    if in_bounds:
                        target.setPos(new_target_p)
                        other.setPos(new_other_p)
                elif self.marker_panel.btn_lock_center.isChecked():
                    # Handle lock center specifically if needed, but for now simple shift logic suffices for placement
                    pass
                
                if drag_mode:
                    self.active_drag_marker = target
            else:
                if len(active_markers) >= 2:
                    old_marker = active_markers.pop(0)
                    self.spectrogram_view.plot_item.removeItem(old_marker)
                    
                marker = pg.InfiniteLine(
                    pos=val, angle=angle, movable=False,
                    pen=pg.mkPen('r', width=2)
                )
                marker.setZValue(10)
                self.spectrogram_view.plot_item.addItem(marker, ignoreBounds=True)
                active_markers.append(marker)
                
                if drag_mode:
                    self.active_drag_marker = marker
            
            self.update_marker_info()

    def handle_move_drag(self, scene_pos, is_start=False, is_finish=False):
        if is_start:
            self.last_move_scene_pos = scene_pos
            return
            
        if is_finish:
            self.last_move_scene_pos = None
            return

        if self.last_move_scene_pos is None:
            return

        # Check if zoomed in
        xr_curr, yr_curr = self.spectrogram_view.view_box.viewRange()
        t_total = self.time_duration
        f_total = self.rate
        visible_ratio_x = (xr_curr[1] - xr_curr[0]) / t_total
        visible_ratio_y = (yr_curr[1] - yr_curr[0]) / f_total
        
        # Do nothing if zoomed out completely
        if visible_ratio_x > 0.999 and visible_ratio_y > 0.999:
            return

        # Map drag to view coordinates
        p1 = self.spectrogram_view.view_box.mapSceneToView(self.last_move_scene_pos)
        p2 = self.spectrogram_view.view_box.mapSceneToView(scene_pos)
        dt = p2.x() - p1.x()
        df = p2.y() - p1.y()
        
        # Translate the view range
        new_xr = [xr_curr[0] - dt, xr_curr[1] - dt]
        new_yr = [yr_curr[0] - df, yr_curr[1] - df]
        
        # Constraints: preserve width/height while clamping to full data range
        if new_xr[0] < 0:
            diff = 0 - new_xr[0]
            new_xr = [0, new_xr[1] + diff]
        elif new_xr[1] > t_total:
            diff = new_xr[1] - t_total
            new_xr = [new_xr[0] - diff, t_total]
            
        f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
        if new_yr[0] < f_min:
            diff = f_min - new_yr[0]
            new_yr = [f_min, new_yr[1] + diff]
        elif new_yr[1] > f_max:
            diff = new_yr[1] - f_max
            new_yr = [new_yr[0] - diff, f_max]
        
        self.spectrogram_view.plot_item.setXRange(*new_xr, padding=0)
        self.spectrogram_view.plot_item.setYRange(*new_yr, padding=0)
        
        self.last_move_scene_pos = scene_pos

    def update_drag(self, scene_pos):
        if self.active_drag_marker and self.spectrogram_view.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_v = self.spectrogram_view.plot_item.vb.mapSceneToView(scene_pos)
            
            # Determine active list based on whether marker is in markers_time or markers_freq
            is_time = self.active_drag_marker in self.markers_time
            active_markers = self.markers_time if is_time else self.markers_freq
            
            if is_time:
                new_v = float(np.clip(mouse_v.x(), 0, self.time_duration))
                get_pos = lambda m: m.getXPos() # Time is X
                f_min, f_max = 0, self.time_duration
            else:
                f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
                new_v = float(np.clip(mouse_v.y(), f_min, f_max))
                get_pos = lambda m: m.getYPos() # Freq is Y

            if len(active_markers) == 2:
                other_marker = active_markers[0] if active_markers[1] == self.active_drag_marker else active_markers[1]
                old_v = get_pos(self.active_drag_marker)
                shift = new_v - old_v
                
                if self.marker_panel.btn_lock_delta.isChecked():
                    other_new = get_pos(other_marker) + shift
                    if f_min <= other_new <= f_max:
                        self.active_drag_marker.setPos(new_v)
                        other_marker.setPos(other_new)
                elif self.marker_panel.btn_lock_center.isChecked():
                    p1, p2 = get_pos(active_markers[0]), get_pos(active_markers[1])
                    ct = (p1 + p2) / 2
                    other_new = 2 * ct - new_v
                    if f_min <= other_new <= f_max:
                        self.active_drag_marker.setPos(new_v)
                        other_marker.setPos(other_new)
                else:
                    self.active_drag_marker.setPos(new_v)
            else:
                self.active_drag_marker.setPos(new_v)
                
            self.update_marker_info()

    def handle_lock_change(self, lock_type, checked):
        if not checked: return
        if lock_type == 'delta':
            self.marker_panel.btn_lock_center.blockSignals(True)
            self.marker_panel.btn_lock_center.setChecked(False)
            self.marker_panel.btn_lock_center.setText("Center 🔓")
            self.marker_panel.btn_lock_center.blockSignals(False)
        else:
            self.marker_panel.btn_lock_delta.blockSignals(True)
            self.marker_panel.btn_lock_delta.setChecked(False)
            self.marker_panel.btn_lock_delta.setText("Delta (Δ) 🔓")
            self.marker_panel.btn_lock_delta.blockSignals(False)

    def handle_marker_clear(self, mode):
        markers = self.markers_time if mode == 'TIME' else self.markers_freq
        for marker in markers:
            self.spectrogram_view.plot_item.removeItem(marker)
        markers.clear()
        self.update_marker_info()

    def update_marker_info(self):
        # Choose active markers based on mode
        is_freq = (self.interaction_mode == 'FREQ')
        active_markers = self.markers_freq if is_freq else self.markers_time
        get_pos = lambda m: m.getYPos() if is_freq else m.getXPos()
        
        sorted_markers = sorted(active_markers, key=get_pos)
        for widgets in self.marker_panel.widgets:
            widgets['sec'].clear()
            widgets['sam'].clear()
        self.marker_panel.delta_sec.clear()
        self.marker_panel.delta_sam.clear()
        self.marker_panel.center_sec.clear()
        self.marker_panel.center_sam.clear()

        if not sorted_markers: return

        for i, marker in enumerate(sorted_markers):
            val = get_pos(marker)
            self.marker_panel.widgets[i]['sec'].blockSignals(True)
            self.marker_panel.widgets[i]['sam'].blockSignals(True)
            if is_freq:
                # Value is Hz. "Samples" -> FFT Bin
                rbw = self.rate / self.fft_size
                bin_idx = int((val - (self.fc - self.rate/2)) / rbw)
                bin_idx = max(0, min(bin_idx, self.fft_size - 1))
                self.marker_panel.widgets[i]['sec'].setText(f"{val:.2f}")
                self.marker_panel.widgets[i]['sam'].setText(f"{bin_idx}")
            else:
                samples = int(val * self.rate)
                self.marker_panel.widgets[i]['sec'].setText(f"{val:.6f}")
                self.marker_panel.widgets[i]['sam'].setText(f"{samples}")
            self.marker_panel.widgets[i]['sec'].blockSignals(False)
            self.marker_panel.widgets[i]['sam'].blockSignals(False)

        if len(sorted_markers) == 2:
            p1, p2 = get_pos(sorted_markers[0]), get_pos(sorted_markers[1])
            dp, cp = abs(p2 - p1), (p1 + p2) / 2
            
            self.marker_panel.delta_sec.blockSignals(True)
            self.marker_panel.delta_sam.blockSignals(True)
            self.marker_panel.center_sec.blockSignals(True)
            self.marker_panel.center_sam.blockSignals(True)

            if is_freq:
                rbw = self.rate / self.fft_size
                # Clip bin indices to [0, nfft-1]
                ds = max(0, min(int(dp / rbw), self.fft_size - 1))
                cs = max(0, min(int((cp - (self.fc - self.rate/2)) / rbw), self.fft_size - 1))
                self.marker_panel.delta_sec.setText(f"{dp:.2f}")
                self.marker_panel.delta_sam.setText(f"{ds}")
                self.marker_panel.center_sec.setText(f"{cp:.2f}")
                self.marker_panel.center_sam.setText(f"{cs}")
            else:
                ds, cs = int(dp * self.rate), int(cp * self.rate)
                self.marker_panel.delta_sec.setText(f"{dp:.6f}")
                self.marker_panel.delta_sam.setText(f"{ds}")
                self.marker_panel.center_sec.setText(f"{cp:.6f}")
                self.marker_panel.center_sam.setText(f"{cs}")

            self.marker_panel.delta_sec.blockSignals(False)
            self.marker_panel.delta_sam.blockSignals(False)
            self.marker_panel.center_sec.blockSignals(False)
            self.marker_panel.center_sam.blockSignals(False)
        
        # Refresh Grids
        self.update_grid('TIME')
        self.update_grid('FREQ')

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        is_freq = (self.interaction_mode == 'FREQ')
        active_markers = self.markers_freq if is_freq else self.markers_time
        get_pos = lambda m: m.getYPos() if is_freq else m.getXPos()
        
        try:
            val = float(sender.text())
            sorted_markers = sorted(active_markers, key=get_pos)
            
            f_min = self.fc - self.rate/2
            f_max = self.fc + self.rate/2
            rbw = self.rate / self.fft_size
            curr_max = f_max if is_freq else self.time_duration
            curr_min = f_min if is_freq else 0

            if name.startswith('m') and len(sorted_markers) > int(name[1]):
                idx = int(name[1])
                unit = name[3:]
                
                if is_freq:
                    # Clip input bin to [0, nfft-1]
                    bin_val = max(0, min(val, self.fft_size - 1))
                    new_p = np.clip(f_min + bin_val * rbw if unit == 'sam' else val, f_min, f_max)
                else:
                    new_p = np.clip(val / self.rate if unit == 'sam' else val, 0, self.time_duration)
                
                if len(sorted_markers) == 2:
                    other_idx = 1 - idx
                    old_p = get_pos(sorted_markers[idx])
                    shift = new_p - old_p
                    if self.marker_panel.btn_lock_delta.isChecked():
                        other_new = get_pos(sorted_markers[other_idx]) + shift
                        if curr_min <= other_new <= curr_max:
                            sorted_markers[idx].setPos(new_p)
                            sorted_markers[other_idx].setPos(other_new)
                    elif self.marker_panel.btn_lock_center.isChecked():
                        p1, p2 = get_pos(sorted_markers[0]), get_pos(sorted_markers[1])
                        ct = (p1 + p2) / 2
                        other_new = 2 * ct - new_p
                        if curr_min <= other_new <= curr_max:
                            sorted_markers[idx].setPos(new_p)
                            sorted_markers[other_idx].setPos(other_new)
                    else: sorted_markers[idx].setPos(new_p)
                else: sorted_markers[idx].setPos(new_p)
                
            elif len(sorted_markers) == 2:
                p1, p2 = get_pos(sorted_markers[0]), get_pos(sorted_markers[1])
                dt, ct = abs(p2 - p1), (p1 + p2) / 2
                
                if 'delta' in name:
                    if is_freq:
                        new_dt = np.clip(val * rbw if 'sam' in name else val, 0, self.rate)
                    else:
                        new_dt = np.clip(val / self.rate if 'sam' in name else val, 0, self.time_duration)
                    m1_new, m2_new = ct - new_dt/2, ct + new_dt/2
                    if curr_min <= m1_new and m2_new <= curr_max:
                        sorted_markers[0].setPos(m1_new)
                        sorted_markers[1].setPos(m2_new)
                elif 'center' in name:
                    if is_freq:
                        new_ct = np.clip(val * rbw + f_min if 'sam' in name else val, f_min, f_max)
                    else:
                        new_ct = np.clip(val / self.rate if 'sam' in name else val, 0, self.time_duration)
                    m1_new, m2_new = new_ct - dt/2, new_ct + dt/2
                    if curr_min <= m1_new and m2_new <= curr_max:
                        sorted_markers[0].setPos(m1_new)
                        sorted_markers[1].setPos(m2_new)
            
            self.update_marker_info()
        except ValueError: self.update_marker_info()

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(np.ndarray, float)
    def display_spectrogram(self, full_spectrogram, duration):
        # Hide progress bar by making it transparent
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: transparent; border: none; } QProgressBar::chunk { background-color: transparent; }")
        
        self.full_spectrogram_cache = full_spectrogram
        self.time_duration = duration
        self.total_samples_in_cache = duration * self.rate
        
        self.spectrogram_view.update_spectrogram(
            full_spectrogram, self.fc, self.rate, self.time_duration, 
            auto_range=self.is_first_load
        )
        self.is_first_load = False
        self.update_marker_info()

    def closeEvent(self, event):
        if hasattr(self, 'worker'): self.worker.stop()
        event.accept()

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.undo_zoom()
        else:
            super().keyPressEvent(event)

    def undo_zoom(self):
        if self.zoom_history:
            prev_rect = self.zoom_history.pop()
            self.spectrogram_view.plot_item.setRange(rect=prev_rect, padding=0)

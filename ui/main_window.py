import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QProgressBar
from PyQt6.QtCore import pyqtSlot, Qt

from utils import FileReaderThread
from .marker_panel import MarkerPanel
from .spectrogram_view import SpectrogramView
from .side_panel import SidePanel

class SpectrogramWindow(QMainWindow):
    def __init__(self, file_path, data_type, sample_rate, center_freq, fft_size, profile_enabled=False):
        super().__init__()
        self.setWindowTitle("Antigravity Spectrogram Viewer")
        self.resize(1280, 800)
        
        self.fc = center_freq
        self.rate = sample_rate
        self.fft_size = fft_size
        self.overlap_percent = 50.0
        self.file_path = file_path
        self.data_type = data_type
        self.profile_enabled = profile_enabled
        
        self.active_drag_marker = None
        self.markers = []
        self.time_duration = 1.0 # Default until data loads
        self.zoom_mode = False
        
        self.setup_ui()
        self.start_processing()

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # Main Horizontal Layout
        self.main_h_layout = QHBoxLayout(self.central_widget)
        self.main_h_layout.setContentsMargins(0, 0, 0, 0)
        self.main_h_layout.setSpacing(0)
        
        # Sidebar
        self.sidebar = SidePanel(self.rate, self.fc, self.fft_size)
        self.sidebar.parametersChanged.connect(self.on_parameters_changed)
        self.main_h_layout.addWidget(self.sidebar)
        
        # Right Side Vertical Layout
        self.right_container = QWidget()
        self.layout = QVBoxLayout(self.right_container)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.main_h_layout.addWidget(self.right_container)
        
        self.info_layout = QHBoxLayout()
        self.info_layout.setContentsMargins(10, 5, 10, 5)
        help_label = QLabel("<b>Interactive Controls:</b> Left Click/Drag - Place & Move Time Marker")
        self.info_layout.addWidget(help_label)
        self.layout.addLayout(self.info_layout)
        
        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)

        self.marker_panel = MarkerPanel(self)
        self.marker_panel.zoomModeToggled.connect(self.toggle_zoom_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.layout.addWidget(self.marker_panel)
        
        self.spectrogram_view = SpectrogramView(self)
        self.layout.addWidget(self.spectrogram_view)

    def start_processing(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        self.worker = FileReaderThread(self.file_path, self.data_type, self.fft_size, self.overlap_percent, self.rate, self.profile_enabled)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished_processing.connect(self.display_spectrogram)
        self.worker.start()

    def on_parameters_changed(self, params):
        # Check if we need a full re-processing (DSP params changed)
        needs_reprocess = (self.fft_size != params['fft_size'] or 
                           self.overlap_percent != params['overlap_percent'])
        
        old_rate = self.rate
        self.rate = params['fs']
        self.fc = params['fc']
        self.fft_size = params['fft_size']
        self.overlap_percent = params['overlap_percent']
        
        if needs_reprocess:
            self.start_processing()
        else:
            # Soft update: refresh labels and markers
            if hasattr(self, 'full_spectrogram_cache'):
                # Re-calculate duration based on new rate
                # We use the same precise logic: (samples) / rate
                num_time_steps = self.full_spectrogram_cache.shape[1]
                step_size = int(self.fft_size * (1.0 - self.overlap_percent / 100.0))
                step_size = max(1, step_size)
                
                total_samples = (num_time_steps - 1) * step_size + self.fft_size
                self.time_duration = total_samples / self.rate
                
                # Update markers to preserve sample position
                for marker in self.markers:
                    samples = marker.getXPos() * old_rate
                    new_t = samples / self.rate
                    marker.setPos(new_t)

                    self.spectrogram_view.update_spectrogram(
                        self.full_spectrogram_cache, self.fc, self.rate, self.time_duration
                    )
            self.update_marker_info()

    def toggle_zoom_mode(self, enabled):
        self.zoom_mode = enabled
        if enabled:
            # Change cursor to crosshair for precision
            self.spectrogram_view.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.spectrogram_view.setCursor(Qt.CursorShape.ArrowCursor)

    def reset_zoom(self):
        self.spectrogram_view.plot_item.autoRange()

    def handle_zoom_rectangle(self, rect, zoom_type='BOTH'):
        """
        rect is QRectF in view coordinates.
        zoom_type: 'BOTH', 'X_ONLY', or 'Y_ONLY'
        """
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

    def place_marker(self, scene_pos, drag_mode=False):
        if self.spectrogram_view.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_v = self.spectrogram_view.plot_item.vb.mapSceneToView(scene_pos)
            pos_x = float(np.clip(mouse_v.x(), 0, self.time_duration))
            
            if len(self.markers) == 2 and (self.marker_panel.lock_delta_cb.isChecked() or self.marker_panel.lock_center_cb.isChecked()):
                m0_dist = abs(self.markers[0].getXPos() - pos_x)
                m1_dist = abs(self.markers[1].getXPos() - pos_x)
                
                target = self.markers[0] if m0_dist < m1_dist else self.markers[1]
                other = self.markers[1] if m0_dist < m1_dist else self.markers[0]
                
                old_x = target.getXPos()
                shift = pos_x - old_x
                
                if self.marker_panel.lock_delta_cb.isChecked():
                    other_new_x = other.getXPos() + shift
                    if 0 <= other_new_x <= self.time_duration:
                        target.setPos(pos_x)
                        other.setPos(other_new_x)
                elif self.marker_panel.lock_center_cb.isChecked():
                    t1, t2 = self.markers[0].getXPos(), self.markers[1].getXPos()
                    ct = (t1 + t2) / 2
                    other_new_x = 2 * ct - pos_x
                    if 0 <= other_new_x <= self.time_duration:
                        target.setPos(pos_x)
                        other.setPos(other_new_x)
                
                if drag_mode:
                    self.active_drag_marker = target
            else:
                if len(self.markers) >= 2:
                    old_marker = self.markers.pop(0)
                    self.spectrogram_view.plot_item.removeItem(old_marker)
                    
                marker = pg.InfiniteLine(
                    pos=pos_x, angle=90, movable=False,
                    pen=pg.mkPen('r', width=2)
                )
                self.spectrogram_view.plot_item.addItem(marker, ignoreBounds=True)
                self.markers.append(marker)
                
                if drag_mode:
                    self.active_drag_marker = marker
            
            self.update_marker_info()

    def update_drag(self, scene_pos):
        if self.active_drag_marker and self.spectrogram_view.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_v = self.spectrogram_view.plot_item.vb.mapSceneToView(scene_pos)
            new_x = float(np.clip(mouse_v.x(), 0, self.time_duration))
            
            if len(self.markers) == 2:
                other_marker = self.markers[0] if self.markers[1] == self.active_drag_marker else self.markers[1]
                old_x = self.active_drag_marker.getXPos()
                shift = new_x - old_x
                
                if self.marker_panel.lock_delta_cb.isChecked():
                    other_new_x = other_marker.getXPos() + shift
                    if 0 <= other_new_x <= self.time_duration:
                        self.active_drag_marker.setPos(new_x)
                        other_marker.setPos(other_new_x)
                elif self.marker_panel.lock_center_cb.isChecked():
                    t1, t2 = self.markers[0].getXPos(), self.markers[1].getXPos()
                    ct = (t1 + t2) / 2
                    other_new_x = 2 * ct - new_x
                    if 0 <= other_new_x <= self.time_duration:
                        self.active_drag_marker.setPos(new_x)
                        other_marker.setPos(other_new_x)
                else:
                    self.active_drag_marker.setPos(new_x)
            else:
                self.active_drag_marker.setPos(new_x)
                
            self.update_marker_info()

    def handle_lock_change(self, lock_type, checked):
        if not checked: return
        if lock_type == 'delta':
            self.marker_panel.lock_center_cb.blockSignals(True)
            self.marker_panel.lock_center_cb.setChecked(False)
            self.marker_panel.lock_center_cb.blockSignals(False)
        else:
            self.marker_panel.lock_delta_cb.blockSignals(True)
            self.marker_panel.lock_delta_cb.setChecked(False)
            self.marker_panel.lock_delta_cb.blockSignals(False)

    def update_marker_info(self):
        sorted_markers = sorted(self.markers, key=lambda m: m.getXPos())
        for widgets in self.marker_panel.widgets:
            widgets['sec'].clear()
            widgets['sam'].clear()
        self.marker_panel.delta_sec.clear()
        self.marker_panel.delta_sam.clear()
        self.marker_panel.center_sec.clear()
        self.marker_panel.center_sam.clear()

        if not sorted_markers: return

        for i, marker in enumerate(sorted_markers):
            t = marker.getXPos()
            samples = int(t * self.rate)
            self.marker_panel.widgets[i]['sec'].blockSignals(True)
            self.marker_panel.widgets[i]['sam'].blockSignals(True)
            self.marker_panel.widgets[i]['sec'].setText(f"{t:.6f}")
            self.marker_panel.widgets[i]['sam'].setText(f"{samples}")
            self.marker_panel.widgets[i]['sec'].blockSignals(False)
            self.marker_panel.widgets[i]['sam'].blockSignals(False)

        if len(sorted_markers) == 2:
            t1, t2 = sorted_markers[0].getXPos(), sorted_markers[1].getXPos()
            dt, ds = abs(t2 - t1), int(abs(t2 - t1) * self.rate)
            ct, cs = (t1 + t2) / 2, int(((t1 + t2) / 2) * self.rate)
            
            self.marker_panel.delta_sec.blockSignals(True)
            self.marker_panel.delta_sam.blockSignals(True)
            self.marker_panel.center_sec.blockSignals(True)
            self.marker_panel.center_sam.blockSignals(True)
            self.marker_panel.delta_sec.setText(f"{dt:.6f}")
            self.marker_panel.delta_sam.setText(f"{ds}")
            self.marker_panel.center_sec.setText(f"{ct:.6f}")
            self.marker_panel.center_sam.setText(f"{cs}")
            self.marker_panel.delta_sec.blockSignals(False)
            self.marker_panel.delta_sam.blockSignals(False)
            self.marker_panel.center_sec.blockSignals(False)
            self.marker_panel.center_sam.blockSignals(False)

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        try:
            val = float(sender.text())
            sorted_markers = sorted(self.markers, key=lambda m: m.getXPos())
            if name.startswith('m') and len(sorted_markers) > int(name[1]):
                idx = int(name[1])
                unit = name[3:]
                new_t = np.clip(val / self.rate if unit == 'sam' else val, 0, self.time_duration)
                if len(sorted_markers) == 2:
                    other_idx = 1 - idx
                    old_t = sorted_markers[idx].getXPos()
                    shift = new_t - old_t
                    if self.marker_panel.lock_delta_cb.isChecked():
                        other_new_t = sorted_markers[other_idx].getXPos() + shift
                        if 0 <= other_new_t <= self.time_duration:
                            sorted_markers[idx].setPos(new_t)
                            sorted_markers[other_idx].setPos(other_new_t)
                    elif self.marker_panel.lock_center_cb.isChecked():
                        t1, t2 = sorted_markers[0].getXPos(), sorted_markers[1].getXPos()
                        ct = (t1 + t2) / 2
                        other_new_t = 2 * ct - new_t
                        if 0 <= other_new_t <= self.time_duration:
                            sorted_markers[idx].setPos(new_t)
                            sorted_markers[other_idx].setPos(other_new_t)
                    else: sorted_markers[idx].setPos(new_t)
                else: sorted_markers[idx].setPos(new_t)
            elif len(sorted_markers) == 2:
                t1, t2 = sorted_markers[0].getXPos(), sorted_markers[1].getXPos()
                dt, ct = abs(t2 - t1), (t1 + t2) / 2
                if 'delta' in name:
                    new_dt = np.clip(val / self.rate if 'sam' in name else val, 0, self.time_duration)
                    m1_new, m2_new = ct - new_dt/2, ct + new_dt/2
                    sorted_markers[0].setPos(np.clip(m1_new, 0, self.time_duration))
                    sorted_markers[1].setPos(np.clip(m2_new, 0, self.time_duration))
                elif 'center' in name:
                    new_ct = np.clip(val / self.rate if 'sam' in name else val, 0, self.time_duration)
                    sorted_markers[0].setPos(np.clip(new_ct - dt/2, 0, self.time_duration))
                    sorted_markers[1].setPos(np.clip(new_ct + dt/2, 0, self.time_duration))
            self.update_marker_info()
        except ValueError: self.update_marker_info()

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(np.ndarray, float)
    def display_spectrogram(self, full_spectrogram, duration):
        self.progress_bar.hide()
        self.full_spectrogram_cache = full_spectrogram
        self.time_duration = duration
        
        self.spectrogram_view.update_spectrogram(full_spectrogram, self.fc, self.rate, self.time_duration)

    def closeEvent(self, event):
        if hasattr(self, 'worker'): self.worker.stop()
        event.accept()

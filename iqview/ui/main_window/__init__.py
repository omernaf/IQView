from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtCore import Qt

from .component_setup import UIComponentsMixin
from .marker_manager import MarkerManagerMixin
from .view_controller import ViewControllerMixin
from .data_handler import DataHandlerMixin

class SpectrogramWindow(QMainWindow, UIComponentsMixin, MarkerManagerMixin, ViewControllerMixin, DataHandlerMixin):
    def __init__(self, file_path, data_type, sample_rate, center_freq, fft_size, profile_enabled=False):
        super().__init__()
        self.is_spectrogram = True
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
        self.time_duration = 1.0
        self.interaction_mode = 'TIME'
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
        self.active_drag_marker = None
        
        self.setup_ui()
        self.start_processing()

    def closeEvent(self, event):
        if hasattr(self, 'worker'): self.worker.stop()
        event.accept()

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.undo_zoom()
        else:
            super().keyPressEvent(event)

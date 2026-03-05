from PyQt6.QtWidgets import QMainWindow, QMenu
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QAction, QKeySequence

from .component_setup import UIComponentsMixin
from .marker_manager import MarkerManagerMixin
from .view_controller import ViewControllerMixin
from .data_handler import DataHandlerMixin
from ...utils.settings_manager import SettingsManager
from ..themes import get_main_stylesheet

class SpectrogramWindow(QMainWindow, UIComponentsMixin, MarkerManagerMixin, ViewControllerMixin, DataHandlerMixin):
    def __init__(self, file_path, data_type, sample_rate, center_freq, fft_size, profile_enabled=False):
        super().__init__()
        self.settings_mgr = SettingsManager()
        self.apply_current_theme()
        
        self.is_spectrogram = True
        self.setWindowTitle("IQView - Spectrogram Viewer")
        self.resize(1280, 800)
        
        self.fc = center_freq
        self.rate = sample_rate
        self.fft_size = fft_size
        self.window_type = self.settings_mgr.get("core/window_type", "Hamming")
        self.overlap_percent = float(self.settings_mgr.get("core/overlap", 99.0))
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
        
        # Filter State
        self.filter_enabled = False
        self.filter_region = None # LinearRegionItem added in setup_ui or on demand
        self.filter_placed = False
        self.filter_placing = False
        
        self.setup_ui()
        self.start_processing()

    def apply_current_theme(self):
        theme = self.settings_mgr.get("ui/theme", "Light")
        self.setStyleSheet(get_main_stylesheet(theme))
        
        if hasattr(self, 'marker_panel'):
            self.marker_panel.refresh_theme()
        if hasattr(self, 'spectrogram_view'):
            self.spectrogram_view.refresh_theme()
            self.refresh_spectrogram_markers()
        
        # Refresh all Time Domain tabs
        if hasattr(self, 'tabs'):
            for i in range(1, self.tabs.count()):
                widget = self.tabs.widget(i)
                if hasattr(widget, 'refresh_theme'):
                    widget.refresh_theme()

    def eventFilter(self, obj, event):
        """Handle middle-click and right-click on the tab bar."""
        if obj == self.tabs.tabBar() and event.type() == QEvent.Type.MouseButtonPress:
            index = self.tabs.tabBar().tabAt(event.pos())
            if index > 0:  # Ignore Spectrogram tab
                if event.button() == Qt.MouseButton.MiddleButton:
                    self.close_tab(index)
                    return True
                elif event.button() == Qt.MouseButton.RightButton:
                    self.handle_tab_context_menu(index, event.globalPosition().toPoint())
                    return True
        return super().eventFilter(obj, event)

    def handle_tab_context_menu(self, index, pos):
        """Show context menu for a tab."""
        menu = QMenu(self)
        close_action = QAction("Close Tab", self)
        close_action.triggered.connect(lambda: self.close_tab(index))
        menu.addAction(close_action)
        menu.exec(pos)

    def closeEvent(self, event):
        if hasattr(self, 'worker'): self.worker.stop()
        event.accept()

    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        s = self.settings_mgr
        key_name = QKeySequence(event.key()).toString()
        if key_name == "Control": key_name = "Ctrl"
        
        time_seq = s.get('keybinds/time_markers', 'T')
        freq_seq = s.get('keybinds/mag_markers', 'F')
        zoom_seq = s.get('keybinds/zoom_mode', 'Ctrl')

        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.undo_zoom()
        elif key_name == time_seq:
            self.set_interaction_mode('TIME')
        elif key_name == freq_seq:
            self.set_interaction_mode('FREQ')
        elif key_name == zoom_seq:
            self._prev_interaction_mode = getattr(self, 'interaction_mode', 'TIME')
            self.set_interaction_mode('ZOOM')
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        s = self.settings_mgr
        key_name = QKeySequence(event.key()).toString()
        if key_name == "Control": key_name = "Ctrl"
        zoom_seq = s.get('keybinds/zoom_mode', 'Ctrl')

        if key_name == zoom_seq:
            prev = getattr(self, '_prev_interaction_mode', 'TIME')
            self.set_interaction_mode(prev)
        super().keyReleaseEvent(event)

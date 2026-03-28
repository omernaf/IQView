from PyQt6.QtWidgets import QMainWindow, QMenu
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QAction, QKeySequence, QIcon, QPixmap
import os
import sys
import ctypes

from .component_setup import UIComponentsMixin
from .marker_manager import MarkerManagerMixin
from .view_controller import ViewControllerMixin
from .data_handler import DataHandlerMixin
from ...utils.settings_manager import SettingsManager
from ..themes import get_main_stylesheet

class SpectrogramWindow(QMainWindow, UIComponentsMixin, MarkerManagerMixin, ViewControllerMixin, DataHandlerMixin):
    def __init__(self, data_source, data_type, sample_rate, center_freq, fft_size, profile_enabled=False, is_complex=True, window_name=None, lazy_rendering=None):
        super().__init__()
        self.settings_mgr = SettingsManager()
        # Per-instance rendering mode override from CLI (None = use QSettings value).
        # Stored here rather than in QSettings so multiple windows can coexist with
        # different modes without interfering with each other.
        self._lazy_rendering_override = lazy_rendering
        self.apply_current_theme()
        
        # --- Application Icon & Taskbar Fix ---
        try:
            # Set AppUserModelID so Windows taskbar shows the custom icon instead of Python's
            if sys.platform == "win32":
                myappid = 'omernaf.iqview.spectrogram.0.1.2' # arbitrary string
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

        # Load logo from resources
        pixmap = QPixmap()
        try:
            from importlib.resources import files
            logo_resource = files("iqview.resources").joinpath("logo.png")
            with logo_resource.open("rb") as f:
                pixmap.loadFromData(f.read())
        except Exception:
            # Fallback for local dev
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            local_logo = os.path.join(base_path, "iqview", "resources", "logo.png")
            pixmap = QPixmap(local_logo)
            
        if not pixmap.isNull():
            self.setWindowIcon(QIcon(pixmap))
        
        self.is_spectrogram = True

        # data_source is either a str (file path), bytes (piped from stdin), or None (empty launch)
        self.data_source = data_source
        self.custom_window_name = window_name
        
        if self.custom_window_name:
            display_name = self.custom_window_name
        elif data_source is None:
            display_name = "No File Loaded"
        elif isinstance(data_source, (bytes, bytearray)):
            display_name = "<stdin>"
        else:
            display_name = data_source
        self.setWindowTitle(f"IQView - {display_name}")
        self.resize(1280, 800)
        
        self.fc = center_freq
        self.rate = sample_rate
        self.fft_size = fft_size
        self.window_type = self.settings_mgr.get("core/window_type", "Hamming")
        self.overlap_percent = float(self.settings_mgr.get("core/overlap", 99.0))
        self.data_type = data_type
        self.is_complex = is_complex
        self.profile_enabled = profile_enabled
        
        # Keep file_path as an alias for backwards-compat with any mixin that reads it
        self.file_path = data_source

        self.markers_time = []
        self.markers_freq = []
        self.markers_time_endless = []
        self.markers_freq_endless = []
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
        self.filter_mode = None
        self.filter_region = None # LinearRegionItem added in setup_ui or on demand
        self.filter_placed = False
        self.filter_placing = False
        self.filter_bounds = [] # [f1, f2] sorted
        self.filter_marker_order = [] # [v1, v2] in placement order
        self.filter_line = None # pg.InfiniteLine for the first bound
        
        self.setup_ui()
        if data_source is not None:
            self.update_sidebar_file_info(data_source)
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

    def on_settings_applied(self):
        """Handle settings changes: refresh theme and re-process if filter is active."""
        self.apply_current_theme()
        
        # Immediately push setting changes to marker panel layouts
        if hasattr(self, 'marker_panel'):
            self.marker_panel.update_headers(getattr(self, 'interaction_mode', 'TIME'))
        
        # Refresh plot modes for Time Domain tabs
        if hasattr(self, 'tabs'):
            for i in range(1, self.tabs.count()):
                widget = self.tabs.widget(i)
                if hasattr(widget, 'rebuild_plot_buttons'):
                    widget.rebuild_plot_buttons()
                if hasattr(widget, 'marker_panel'):
                    widget.marker_panel.update_headers(getattr(widget, 'interaction_mode', 'TIME'), getattr(widget, 'y_label_text', 'Magnitude'))
                    
        if self.filter_mode:
            self.start_processing()

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
        if hasattr(self, '_stop_all_workers'):
            self._stop_all_workers()
        elif hasattr(self, 'worker'):
            self.worker.stop()
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

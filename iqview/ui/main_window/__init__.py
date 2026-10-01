from PyQt6.QtWidgets import QMainWindow, QMenu
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QAction, QKeySequence, QIcon, QPixmap
import os
import sys

from .component_setup import UIComponentsMixin
from .marker_manager import MarkerManagerMixin
from .overlay_manager import OverlayManagerMixin
from .view_controller import ViewControllerMixin
from .data_handler import DataHandlerMixin
from ...plugins.plugin_manager import PluginManagerMixin
from ...utils.settings_manager import SettingsManager
from ..themes import get_main_stylesheet

class SpectrogramWindow(QMainWindow, UIComponentsMixin, MarkerManagerMixin, OverlayManagerMixin, ViewControllerMixin, DataHandlerMixin, PluginManagerMixin):
    def __init__(self, data_source, data_type, sample_rate, center_freq, fft_size, profile_enabled=False, is_complex=True, window_name=None, lazy_rendering=None, file_path=None, type_str=None, norm_db=0.0):
        super().__init__()
        self.settings_mgr = SettingsManager()
        self.norm_db = float(norm_db)
        # Per-instance rendering mode override from CLI (None = use QSettings value).
        self._lazy_rendering_override = lazy_rendering
        
        # Detached Views Management
        self.detached_views = [] # List of DetachedViewWindow objects
        
        self.apply_current_theme()
        
        # --- Application Icon ---
        # Note: AppUserModelID is set in main.py before QApplication is created (correct place).

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
        raw_fp = file_path or (data_source if isinstance(data_source, str) else None)
        self.file_path = os.path.normpath(os.path.abspath(raw_fp)) if (raw_fp and isinstance(raw_fp, str)) else None
        if isinstance(data_source, str):
            self.data_source = self.file_path
        else:
            self.data_source = data_source
        self.custom_window_name = window_name
        
        if self.custom_window_name:
            display_name = self.custom_window_name
        elif self.file_path:
            display_name = self.file_path
        elif data_source is None:
            display_name = "No File Loaded"
        elif isinstance(data_source, (bytes, bytearray)):
            display_name = "<stdin>"
        else:
            display_name = data_source
        self.setWindowTitle(f"IQView - {display_name}")
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        
        self.fc = center_freq
        self.rate = sample_rate
        self.fft_size = fft_size
        self.window_size = fft_size
        self.window_type = self.settings_mgr.get("core/window_type", "Hamming")
        ov = self.settings_mgr.get("core/overlap", 100.0)
        if str(ov).upper() == "MAX":
            self.overlap_percent = 100.0
        else:
            try:
                self.overlap_percent = float(ov)
            except Exception:
                self.overlap_percent = 100.0
        self.data_type = data_type
        self.is_complex = is_complex
        self.profile_enabled = profile_enabled
        from ...utils.helpers import detect_type_from_ext
        self.current_type_str = type_str or (detect_type_from_ext(self.file_path) if self.file_path else None) or str(self.settings_mgr.get("core/type", "complex64"))
        
        # Keep file_path as an alias for backwards-compat with any mixin that reads it

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
        
        self._init_overlays()
        self._init_plugins()
        self.setup_ui()
        if data_source is not None:
            self.update_sidebar_file_info(self.file_path or data_source, self.current_type_str)
            if self.file_path and os.path.isfile(self.file_path):
                self._add_recent_file(self.file_path, self.current_type_str, self.rate, self.fc)
            self.start_processing()

    def apply_current_theme(self):
        theme = self.settings_mgr.get("ui/theme", "Light")
        self.setStyleSheet(get_main_stylesheet(theme))
        
        if hasattr(self, 'sidebar') and hasattr(self.sidebar, 'update_button_tooltips'):
            self.sidebar.update_button_tooltips()
        if hasattr(self, 'marker_panel'):
            self.marker_panel.refresh_theme()
        if hasattr(self, 'spectrogram_view'):
            self.spectrogram_view.refresh_theme()
            self.refresh_spectrogram_markers()
        if hasattr(self, 'multi_row_view'):
            self.multi_row_view.refresh_theme()
        if hasattr(self, '_overlay_items'):
            self.refresh_overlays_theme()
        
        # Refresh all Time Domain tabs
        if hasattr(self, 'tabs'):
            for i in range(1, self.tabs.count()):
                widget = self.tabs.widget(i)
                if hasattr(widget, 'refresh_theme'):
                    widget.refresh_theme()
                    
        # Refresh all detached views
        if hasattr(self, 'detached_views'):
            for dv in self.detached_views:
                if hasattr(dv, 'refresh_theme'):
                    dv.refresh_theme()

    def on_settings_applied(self):
        """Handle settings changes: refresh theme and re-process if filter is active."""
        self.apply_current_theme()
        
        # Re-render spectrogram in the new orientation (waterfall toggle, etc.)
        if hasattr(self, 'spectrogram_view'):
            self.spectrogram_view._session_waterfall = None
            self.spectrogram_view.apply_waterfall_mode()
            
        if hasattr(self, 'sidebar') and hasattr(self.sidebar, 'update_waterfall_checkbox'):
            self.sidebar.update_waterfall_checkbox()
        
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

        # Force-redraw all active marker grids so style/color/width changes apply immediately
        self.update_grid('TIME', force=True)
        self.update_grid('FREQ', force=True)

        # Also refresh grids in any open Time/Freq Domain tabs and detached views
        all_views = []
        if hasattr(self, 'tabs'):
            all_views += [self.tabs.widget(i) for i in range(1, self.tabs.count())]
        if hasattr(self, 'detached_views'):
            all_views += [dv.view for dv in self.detached_views if hasattr(dv, 'view')]
        for view in all_views:
            if hasattr(view, 'update_grid'):
                for axis in ('TIME', 'MAG', 'FREQ'):
                    view.update_grid(axis, force=True)

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
        
        if index > 0:
            undock_action = QAction("Undock", self)
            undock_action.triggered.connect(lambda: self.undock_tab(index))
            menu.addAction(undock_action)
            menu.addSeparator()
            
        close_action = QAction("Close Tab", self)
        close_action.triggered.connect(lambda: self.close_tab(index))
        menu.addAction(close_action)
        menu.exec(pos)

    def close_detached_view(self, dv_window):
        """Called when a detached window is closed."""
        if dv_window in self.detached_views:
            self.detached_views.remove(dv_window)
        # Widget is already parented to dv_window and will be destroyed with it.

    def closeEvent(self, event):
        # Close all detached windows first
        for dv in list(self.detached_views):
            dv.close()
            
        if hasattr(self, '_stop_all_workers'):
            self._stop_all_workers()
        elif hasattr(self, 'worker'):
            self.worker.stop()
        event.accept()

    def _get_kb(self, key, default):
        return str(self.settings_mgr.get(key, default)) if self.settings_mgr else default

    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        if getattr(event, '_from_subview', False):
            super().keyPressEvent(event)
            return

        from PyQt6.QtWidgets import QApplication, QLineEdit, QDoubleSpinBox, QSpinBox
        if isinstance(QApplication.focusWidget(), (QLineEdit, QDoubleSpinBox, QSpinBox)):
            super().keyPressEvent(event)
            return

        active_tab = self.tabs.currentWidget() if hasattr(self, 'tabs') else None
        if active_tab is not None and active_tab != getattr(self, 'spec_tab_page', None):
            event._from_subview = True
            active_tab.keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Delete:
            sel_id = getattr(self, 'selected_overlay_id', None)
            if sel_id and hasattr(self, 'remove_overlay'):
                self.remove_overlay(sel_id)
                event.accept()
                return

        from ..widgets import key_event_to_name
        key_name = key_event_to_name(event)
        if not key_name:
            super().keyPressEvent(event)
            return

        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.undo_zoom()
            return

        if key_name == self._get_kb('keybinds/zoom_mode', 'Ctrl'):
            if self.interaction_mode not in ('ZOOM', 'MOVE'):
                self._prev_interaction_mode = getattr(self, 'interaction_mode', 'TIME')
            self._zoom_key_held = True
            self.set_interaction_mode('ZOOM')
        elif key_name == self._get_kb('keybinds/move_mode', 'Space'):
            if self.interaction_mode not in ('ZOOM', 'MOVE'):
                self._prev_interaction_mode = getattr(self, 'interaction_mode', 'TIME')
            self._move_key_held = True
            self.set_interaction_mode('MOVE')
        elif key_name == self._get_kb('keybinds/reset_zoom', 'R'):
            self.reset_zoom()
        elif key_name == self._get_kb('keybinds/undo_zoom', 'Ctrl+Z'):
            self.undo_zoom()
        elif key_name == self._get_kb('keybinds/clear_markers', 'Backspace'):
            mode = self.interaction_mode
            if mode in ('ZOOM', 'MOVE'):
                mode = getattr(self.marker_panel, 'last_marker_mode', 'TIME')
            if mode in ('OVERLAY', 'PLUGINS'):
                self.marker_panel.clearOverlaysRequested.emit()
            else:
                self.handle_marker_clear(mode)
        elif key_name == self._get_kb('keybinds/open_settings', 'I'):
            if hasattr(self, 'sidebar'):
                self.sidebar.open_settings()
        elif key_name == self._get_kb('keybinds/time_markers', 'T'):
            self._prev_interaction_mode = 'TIME'
            self.set_interaction_mode('TIME')
        elif key_name == self._get_kb('keybinds/time_endless_markers', 'E'):
            self._prev_interaction_mode = 'TIME_ENDLESS'
            self.set_interaction_mode('TIME_ENDLESS')
        elif key_name == self._get_kb('keybinds/freq_markers', 'F'):
            self._prev_interaction_mode = 'FREQ'
            self.set_interaction_mode('FREQ')
        elif key_name == self._get_kb('keybinds/freq_endless_markers', 'G'):
            self._prev_interaction_mode = 'FREQ_ENDLESS'
            self.set_interaction_mode('FREQ_ENDLESS')
        elif key_name == self._get_kb('keybinds/filter_mode', 'B'):
            self._prev_interaction_mode = 'FILTER'
            self.set_interaction_mode('FILTER')
        elif key_name == self._get_kb('keybinds/overlay_mode', 'O'):
            self._prev_interaction_mode = 'OVERLAY'
            self.set_interaction_mode('OVERLAY')
        elif key_name == self._get_kb('keybinds/plugins_mode', 'P'):
            self._prev_interaction_mode = 'PLUGINS'
            self.set_interaction_mode('PLUGINS')
        elif key_name == self._get_kb('keybinds/lock_m1', '1'):
            if hasattr(self, 'marker_panel') and self.marker_panel.btn_lock_m1.isEnabled():
                self.marker_panel.btn_lock_m1.click()
        elif key_name == self._get_kb('keybinds/lock_m2', '2'):
            if hasattr(self, 'marker_panel') and self.marker_panel.btn_lock_m2.isEnabled():
                self.marker_panel.btn_lock_m2.click()
        elif key_name == self._get_kb('keybinds/lock_delta', 'D'):
            if hasattr(self, 'marker_panel') and self.marker_panel.btn_lock_delta.isEnabled():
                self.marker_panel.btn_lock_delta.click()
        elif key_name == self._get_kb('keybinds/lock_center', 'C'):
            if hasattr(self, 'marker_panel') and self.marker_panel.btn_lock_center.isEnabled():
                self.marker_panel.btn_lock_center.click()
        elif key_name == self._get_kb('keybinds/toggle_bpf', '['):
            if self.interaction_mode == 'FILTER' and hasattr(self, 'marker_panel') and self.marker_panel.cb_bpf.isEnabled():
                self.marker_panel.cb_bpf.click()
        elif key_name == self._get_kb('keybinds/toggle_bsf', ']'):
            if self.interaction_mode == 'FILTER' and hasattr(self, 'marker_panel') and self.marker_panel.cb_bsf.isEnabled():
                self.marker_panel.cb_bsf.click()
        elif key_name == self._get_kb('keybinds/panel_action', 'A'):
            if self.interaction_mode == 'OVERLAY' and hasattr(self, 'marker_panel'):
                self.marker_panel.btn_manual_overlay.click()
            elif self.interaction_mode == 'PLUGINS' and hasattr(self, 'marker_panel'):
                self.marker_panel.btn_load_plugin.click()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        if getattr(event, '_from_subview', False):
            super().keyReleaseEvent(event)
            return

        from PyQt6.QtWidgets import QApplication, QLineEdit, QDoubleSpinBox, QSpinBox
        if isinstance(QApplication.focusWidget(), (QLineEdit, QDoubleSpinBox, QSpinBox)):
            super().keyReleaseEvent(event)
            return

        active_tab = self.tabs.currentWidget() if hasattr(self, 'tabs') else None
        if active_tab is not None and active_tab != getattr(self, 'spec_tab_page', None):
            event._from_subview = True
            active_tab.keyReleaseEvent(event)
            return

        from ..widgets import key_event_to_name
        key_name = key_event_to_name(event)

        if key_name == self._get_kb('keybinds/zoom_mode', 'Ctrl') and getattr(self, '_zoom_key_held', False):
            self._zoom_key_held = False
            if getattr(self, '_move_key_held', False):
                self.set_interaction_mode('MOVE')
            else:
                self.set_interaction_mode(getattr(self, '_prev_interaction_mode', 'TIME'))
            return
        elif key_name == self._get_kb('keybinds/move_mode', 'Space') and getattr(self, '_move_key_held', False):
            self._move_key_held = False
            if getattr(self, '_zoom_key_held', False):
                self.set_interaction_mode('ZOOM')
            else:
                self.set_interaction_mode(getattr(self, '_prev_interaction_mode', 'TIME'))
            return
        super().keyReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                event.acceptProposedAction()
                return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                file_path = urls[0].toLocalFile()
                if os.path.isfile(file_path):
                    self.load_new_file(file_path)
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

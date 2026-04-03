import os
import pyqtgraph as pg
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFileDialog
from iqview.utils.helpers import DTYPE_MAP, detect_type_from_ext
from ..detached_window import DetachedViewWindow

class ViewControllerMixin:
    def on_parameters_changed(self, params):
        needs_reprocess = (self.fft_size != params['fft_size'] or 
                           self.overlap_percent != params['overlap_percent'] or
                           self.window_type != params['window_type'])
        
        old_rate, old_fc = self.rate, self.fc
        self.rate, self.fc = params['fs'], params['fc']
        self.fft_size, self.window_type, self.overlap_percent = params['fft_size'], params['window_type'], params['overlap_percent']
        
        if needs_reprocess:
            self.start_processing()
            
        # Remap current view and markers when fs or fc changed.
        # Works in both full-file and lazy mode (no full_spectrogram_cache required).
        old_duration = self.time_duration
        if old_duration > 0:
            old_bottom = old_fc - old_rate / 2

            # Recompute duration: sample count stays the same, only rate changed
            if hasattr(self, 'total_samples_in_cache'):
                self.time_duration = self.total_samples_in_cache / self.rate
            elif self.rate > 0:
                self.time_duration = (old_duration * old_rate) / self.rate

            # Also update the viewport full-range records used by zoom-out
            self.spectrogram_view.full_t_range = (0.0, self.time_duration)
            self.spectrogram_view.full_f_range = (self.fc - self.rate / 2,
                                                   self.fc + self.rate / 2)

            vr = self.spectrogram_view.plot_item.viewRange()
            rel_t_min, rel_t_max = vr[0][0] / old_duration, vr[0][1] / old_duration
            rel_f_min = (vr[1][0] - old_bottom) / old_rate
            rel_f_max = (vr[1][1] - old_bottom) / old_rate

            new_bottom = self.fc - self.rate / 2
            self.spectrogram_view.plot_item.setXRange(rel_t_min * self.time_duration, rel_t_max * self.time_duration, padding=0)
            self.spectrogram_view.plot_item.setYRange(new_bottom + rel_f_min * self.rate, new_bottom + rel_f_max * self.rate, padding=0)

            for marker in self.markers_time:
                marker.setPos((marker.value() / old_duration) * self.time_duration)
            for marker in self.markers_freq:
                rel_f = (marker.value() - old_bottom) / old_rate
                marker.setPos(new_bottom + rel_f * self.rate)

            if not needs_reprocess and hasattr(self, 'full_spectrogram_cache'):
                self.spectrogram_view.update_spectrogram(
                    self.full_spectrogram_cache, self.fc, self.rate, self.time_duration, auto_range=False
                )
        self.update_marker_info()

    def set_interaction_mode(self, mode):
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
        
        # Delegate to active tab if it's not the spectrogram
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spectrogram_view:
            if hasattr(active_tab, 'set_interaction_mode'):
                active_tab.set_interaction_mode(mode)
        
        self.refresh_cursor()
        self.marker_panel.update_headers(mode)
        self.update_marker_info()
        
        # Handle Filter Region Toggle Visibility
        if hasattr(self.marker_panel, 'filter_container'):
            self.marker_panel.filter_container.setVisible(mode == 'FILTER')

        # Handle Filter Region Visibility & Interaction
        b_len = len(getattr(self, 'filter_bounds', []))
        if self.filter_region:
            if mode == 'FILTER' and (getattr(self, 'filter_placed', False) or b_len == 1):
                self.filter_region.show()
                # Use our custom hit-testing and dragging logic instead of pg regional movement
                self.filter_region.setMovable(False)
            else:
                self.filter_region.hide()
                self.filter_region.setMovable(False)
        
        if hasattr(self, 'filter_line') and self.filter_line:
            if mode == 'FILTER' and b_len == 1 and not self.filter_region.isVisible():
                self.filter_line.show()
            else:
                self.filter_line.hide()

    def on_filter_changed(self, mode):
        self.filter_mode = mode
        if self.filter_region:
            if mode and self.interaction_mode == 'FILTER' and getattr(self, 'filter_placed', False):
                self.filter_region.show()
            elif self.interaction_mode != 'FILTER' or not getattr(self, 'filter_placed', False):
                self.filter_region.hide()
        
        # Trigger reprocessing if we have data
        if self._has_data():
            self.start_processing()

    def on_filter_region_changed(self):
        # Update marker table in real-time when the region is dragged
        self.update_marker_info()

    def on_filter_region_finished(self):
        # Sync bounds if region exists
        if self.filter_region:
            new_bounds = sorted(list(self.filter_region.getRegion()))
            
            # Map old values to new ones in the order list
            if hasattr(self, 'filter_marker_order') and len(self.filter_marker_order) == 2:
                old_sorted = sorted(self.filter_bounds)
                for i in range(2):
                    if i < len(old_sorted) and i < len(new_bounds):
                        old_v = old_sorted[i]
                        new_v = new_bounds[i]
                        if old_v in self.filter_marker_order:
                            oidx = self.filter_marker_order.index(old_v)
                            self.filter_marker_order[oidx] = new_v
            
            self.filter_bounds = new_bounds
            
        # Trigger reprocessing when the user finishes dragging the region
        if getattr(self, 'filter_mode', None) and self._has_data():
            self.start_processing()

    def refresh_cursor(self):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spectrogram_view:
            if hasattr(active_tab, 'refresh_cursor'):
                active_tab.refresh_cursor()
                return # Active tab handles its own cursor
        
        if hasattr(self, 'zoom_mode') and self.zoom_mode:
            self.spectrogram_view.setCursor(Qt.CursorShape.CrossCursor)
        elif self.interaction_mode in ['TIME', 'FREQ', 'FILTER']:
            self.spectrogram_view.setCursor(Qt.CursorShape.CrossCursor)
        elif self.interaction_mode == 'MOVE':
            self.spectrogram_view.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.spectrogram_view.setCursor(Qt.CursorShape.ArrowCursor)

    def open_time_domain_tab(self):
        """Extracts the IQ data between the two time markers (or full range) and opens it in a new tab."""
        # Find time markers in spectrogram
        markers = self.markers_time
        if len(markers) < 2:
            # Fallback to current view range if < 2 markers
            xr, _ = self.spectrogram_view.view_box.viewRange()
            start_t, end_t = xr
        else:
            sorted_m = sorted(markers, key=lambda m: m.value())
            start_t, end_t = sorted_m[0].value(), sorted_m[1].value()
        
        # Extract IQ segment
        segment = self.extract_iq_segment(start_t, end_t)
        if segment is not None:
            from ..time_domain.view import TimeDomainView
            view = TimeDomainView(segment, start_t, self.rate, parent_window=self)
            self.tabs.addTab(view, "Time Domain")
            self.tabs.setCurrentWidget(view)
            self.update_tab_names()

    def open_frequency_domain_tab(self):
        """Extracts IQ data for the selected time range and opens a Frequency Domain analysis tab."""
        markers = self.markers_time
        if len(markers) < 2:
            xr, _ = self.spectrogram_view.view_box.viewRange()
            start_t, end_t = xr
        else:
            sorted_m = sorted(markers, key=lambda m: m.value())
            start_t, end_t = sorted_m[0].value(), sorted_m[1].value()
            
        segment = self.extract_iq_segment(start_t, end_t)
        if segment is not None:
            from ..frequency_domain.view import FrequencyDomainView
            # Use center frequency from current state
            view = FrequencyDomainView(segment, self.fc, self.rate, parent_window=self)
            self.tabs.addTab(view, "Freq Domain")
            self.tabs.setCurrentWidget(view)
            self.update_tab_names()

    def undock_tab(self, index, initial_pos=None):
        """Moves a tab from the QTabWidget to a standalone window.
        
        Args:
            index:       Tab index to undock (must be > 0).
            initial_pos: Optional QPoint for the new window's top-left corner.
                         When provided the window is positioned before show() so
                         it appears exactly where the user released the drag.
        """
        if index <= 0: return  # Don't undock spectrogram

        widget = self.tabs.widget(index)
        if not widget: return

        # Remove from tabs without deleting
        self.tabs.removeTab(index)

        # Create detached window — position is applied inside __init__ before show()
        dv = DetachedViewWindow(widget, self, initial_pos=initial_pos)
        self.detached_views.append(dv)

        self.update_tab_names()

    def dock_view(self, widget):
        """Moves a view from a standalone window back to the QTabWidget."""
        # Find the detached window containing this widget
        target_dv = None
        for dv in self.detached_views:
            if dv.view == widget:
                target_dv = dv
                break

        if not target_dv: return

        # IMPORTANT: reparent the widget away from the detached window BEFORE
        # closing it.  QMainWindow takes ownership of its central widget, so
        # calling close() (or setCentralWidget(None)) would delete the widget.
        # setParent(None) breaks the parent-child link so Qt won't destroy it.
        widget.hide()
        widget.setParent(None)

        # Close the now-empty detached window (closeEvent is a no-op because
        # we already removed it from detached_views before close()).
        self.detached_views.remove(target_dv)
        target_dv.close()

        # Add back to tabs
        from ..time_domain.view import TimeDomainView
        from ..frequency_domain.view import FrequencyDomainView

        label = "Time Domain" if isinstance(widget, TimeDomainView) else "Freq Domain"
        self.tabs.addTab(widget, label)
        self.tabs.setCurrentWidget(widget)
        self.update_tab_names()

    def reset_zoom(self):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spectrogram_view and hasattr(active_tab, 'reset_zoom'):
            active_tab.reset_zoom()
        else:
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            self._zoom_to_full_range()

    def _zoom_to_full_range(self):
        """Zoom to the full file extent using full_t_range / full_f_range.
        Falls back to autoRange() if the ranges aren't set yet."""
        sv = self.spectrogram_view
        t0, t1 = sv.full_t_range
        f0, f1 = sv.full_f_range
        if t1 > t0 and f1 > f0:
            sv.plot_item.setXRange(t0, t1, padding=0)
            sv.plot_item.setYRange(f0, f1, padding=0)
        else:
            sv.plot_item.autoRange()

    def handle_zoom_rectangle(self, rect, zoom_type='BOTH'):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spectrogram_view and hasattr(active_tab, 'handle_zoom_rectangle'):
            active_tab.handle_zoom_rectangle(rect, zoom_type)
        else:
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            if rect.width() <= 0 and zoom_type != 'Y_ONLY': return
            if rect.height() <= 0 and zoom_type != 'X_ONLY': return
            if zoom_type == 'Y_ONLY': self.spectrogram_view.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
            elif zoom_type == 'X_ONLY': self.spectrogram_view.plot_item.setXRange(rect.left(), rect.right(), padding=0)
            else: self.spectrogram_view.plot_item.setRange(rect, padding=0)

    def fit_to_markers(self):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spectrogram_view and hasattr(active_tab, 'fit_to_markers'):
            active_tab.fit_to_markers()
            return

        is_freq = (self.interaction_mode in ['FREQ', 'FREQ_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        if is_endless:
            active_markers = self.markers_freq_endless if is_freq else self.markers_time_endless
        else:
            active_markers = self.markers_freq if is_freq else self.markers_time
        if len(active_markers) == 2:
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            v1, v2 = active_markers[0].value(), active_markers[1].value()
            v_min, v_max = min(v1, v2), max(v1, v2)
            if is_freq: self.spectrogram_view.plot_item.setYRange(v_min, v_max, padding=0)
            else: self.spectrogram_view.plot_item.setXRange(v_min, v_max, padding=0)

    def clear_all_markers(self):
        # Clear time / freq markers (regular and endless)
        all_markers = self.markers_time + self.markers_freq + self.markers_time_endless + self.markers_freq_endless
        for m in all_markers:
            self.spectrogram_view.plot_item.removeItem(m)
        self.markers_time.clear()
        self.markers_freq.clear()
        self.markers_time_endless.clear()
        self.markers_freq_endless.clear()
        
        # Reset filter state
        if self.filter_region:
            self.filter_region.hide()
        if hasattr(self, 'filter_line') and self.filter_line:
            self.filter_line.hide()
            
        self.filter_mode    = None
        self.filter_placed  = False
        self.filter_placing = False
        self.filter_bounds  = []
        self.filter_marker_order = []
        if hasattr(self.marker_panel, 'cb_bpf'):
            self.marker_panel.cb_bpf.setChecked(False)
            self.marker_panel.cb_bsf.setChecked(False)

        # Update displays
        self.marker_panel.update_headers(self.interaction_mode)
        self.update_marker_info()
        self.update_grid('TIME', force=True)
        self.update_grid('FREQ', force=True)
        
        # Refresh processing if filter was removed
        if self._has_data():
            self.start_processing()

    def toggle_grid(self, axis, enabled):
        if axis == 'TIME': self.grid_time_enabled = enabled
        else: self.grid_freq_enabled = enabled
        self.update_grid(axis, force=True)

    def toggle_tracking(self, axis, enabled):
        if axis == 'TIME': self.grid_time_tracking = enabled
        else: self.grid_freq_tracking = enabled
        self.update_grid(axis, force=True)

    def update_grid(self, axis, force=False):
        if not hasattr(self, '_grid_timer'):
            self._grid_timer = QTimer()
            self._grid_timer.setSingleShot(True)
            self._grid_timer.timeout.connect(self._do_update_grid)
            self._grid_pending_axes = set()

        if force:
            self._do_update_grid(axis, force=True)
        else:
            self._grid_pending_axes.add(axis)
            if not self._grid_timer.isActive():
                self._grid_timer.start(50) # 50ms throttle

    def _do_update_grid(self, axis=None, force=False):
        if axis is None:
            axes_to_update = list(self._grid_pending_axes)
            self._grid_pending_axes.clear()
            for a in axes_to_update:
                self._do_update_grid(a, force=force)
            return
        
        is_freq = (axis == 'FREQ')
        enabled = self.grid_freq_enabled if is_freq else self.grid_time_enabled
        tracking = self.grid_freq_tracking if is_freq else self.grid_time_tracking
        active_markers = self.markers_freq if is_freq else self.markers_time
        grid_lines = self.grid_lines_freq if is_freq else self.grid_lines_time
        
        if not enabled:
            for line in grid_lines: self.spectrogram_view.plot_item.removeItem(line)
            grid_lines.clear()
            return
        if not tracking and not force: return
        for line in grid_lines: self.spectrogram_view.plot_item.removeItem(line)
        grid_lines.clear()
        if len(active_markers) != 2: return
        p1, p2 = active_markers[0].value(), active_markers[1].value()
        delta = abs(p2 - p1)
        if delta <= 0: return

        # Optimization: Only plot visible lines
        vr = self.spectrogram_view.plot_item.viewRange()
        v_min_visible, v_max_visible = vr[1] if is_freq else vr[0]
        
        # Guard against too many markers
        if (v_max_visible - v_min_visible) / delta > 500:
            return

        angle = 0 if is_freq else 90
        theme = self.settings_mgr.get("ui/theme", "Dark").lower()
        color = self.settings_mgr.get(f"ui/{theme}/grid_color", "#c8c8ff")
        style_name = self.settings_mgr.get(f"ui/{theme}/grid_style", "SolidLine")
        alpha = int(self.settings_mgr.get("ui/grid_alpha", 30))
        
        style_map = {
            "SolidLine": Qt.PenStyle.SolidLine,
            "DashLine": Qt.PenStyle.DashLine,
            "DotLine": Qt.PenStyle.DotLine,
            "DashDotLine": Qt.PenStyle.DashDotLine
        }
        style = style_map.get(str(style_name), Qt.PenStyle.SolidLine)
        
        # Convert hex color to QColor and set alpha
        from PyQt6.QtGui import QColor
        qcolor = QColor(color)
        qcolor.setAlphaF(alpha / 100.0)
        
        pen = pg.mkPen(qcolor, width=1, style=style)
        
        # Start from first visible multiple of delta relative to p1
        start_count = np.ceil((v_min_visible - p1) / delta)
        curr = p1 + start_count * delta
        
        count = 0
        while curr <= v_max_visible + 1e-9 and count < 500:
            line = pg.InfiniteLine(pos=curr, angle=angle, pen=pen, movable=False)
            line.setZValue(5)
            self.spectrogram_view.plot_item.addItem(line, ignoreBounds=True)
            grid_lines.append(line)
            curr += delta
            count += 1

    def undo_zoom(self):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spectrogram_view and hasattr(active_tab, 'undo_zoom'):
            active_tab.undo_zoom()
        elif self.zoom_history:
            prev_rect = self.zoom_history.pop()
            self.spectrogram_view.plot_item.setRange(rect=prev_rect, padding=0)
        else:
            # No history: zoom to the full file range
            self._zoom_to_full_range()

    def handle_move_drag(self, scene_pos, is_start=False, is_finish=False):
        if is_start:
            self.last_move_scene_pos = scene_pos
            return
        if is_finish:
            self.last_move_scene_pos = None
            return
        if self.last_move_scene_pos is None: return
        xr_curr, yr_curr = self.spectrogram_view.view_box.viewRange()
        visible_ratio_x = (xr_curr[1] - xr_curr[0]) / self.time_duration
        visible_ratio_y = (yr_curr[1] - yr_curr[0]) / self.rate
        if visible_ratio_x > 0.999 and visible_ratio_y > 0.999: return
        p1 = self.spectrogram_view.view_box.mapSceneToView(self.last_move_scene_pos)
        p2 = self.spectrogram_view.view_box.mapSceneToView(scene_pos)
        dt, df = p2.x() - p1.x(), p2.y() - p1.y()
        new_xr, new_yr = [xr_curr[0] - dt, xr_curr[1] - dt], [yr_curr[0] - df, yr_curr[1] - df]
        if new_xr[0] < 0: new_xr = [0, new_xr[1] - new_xr[0]]
        elif new_xr[1] > self.time_duration: new_xr = [new_xr[0] - (new_xr[1] - self.time_duration), self.time_duration]
        f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
        if new_yr[0] < f_min: new_yr = [f_min, new_yr[1] + (f_min - new_yr[0])]
        elif new_yr[1] > f_max: new_yr = [new_yr[0] - (new_yr[1] - f_max), f_max]
        self.spectrogram_view.plot_item.setXRange(*new_xr, padding=0)
        self.spectrogram_view.plot_item.setYRange(*new_yr, padding=0)
        self.last_move_scene_pos = scene_pos

    def open_file_dialog(self):
        """Show a native Open File dialog and load the selected IQ file."""
        mapping = self.settings_mgr.get("core/extension_mapping", {})
        exts = " ".join([f"*{ext}" for ext in mapping.keys()])
        if not exts:
            exts = "*.32f *.64f *.16tc *.16sc *.64fc *.32fc *.bin *.iq *.raw"
            
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open IQ File",
            os.path.dirname(self.file_path) if isinstance(self.file_path, str) else "",
            f"IQ Files ({exts});;All Files (*)"
        )
        if path:
            self.load_new_file(path)

    def update_sidebar_file_info(self, source, type_str=None):
        if not hasattr(self, 'sidebar'): return
        
        # Determine type string if not provided
        if type_str is None:
            if isinstance(source, str):
                auto_type = detect_type_from_ext(source)
                type_str = auto_type if auto_type else str(self.settings_mgr.get("core/type", "complex64"))
            elif isinstance(source, (bytes, bytearray)):
                type_str = "stdin (pipe)"
            else:
                type_str = "N/A"

        # Determine size
        try:
            if isinstance(source, str) and os.path.isfile(source):
                file_size = os.path.getsize(source)
            elif isinstance(source, (bytes, bytearray)):
                file_size = len(source)
            else:
                file_size = None
            self.sidebar.set_file_info(type_str, file_size)
        except Exception:
            self.sidebar.set_file_info(type_str, None)

    def load_new_file(self, path):
        """Swap the data source to a new file and reprocess everything."""
        if not os.path.isfile(path):
            return

        # Update data source
        self.data_source = path
        self.file_path   = path
        if getattr(self, 'custom_window_name', None):
            self.setWindowTitle(f"IQView - {self.custom_window_name}")
        else:
            self.setWindowTitle(f"IQView - {path}")

        # Priority: 1. Auto-detection from filename, 2. App Settings
        auto_type = detect_type_from_ext(path)
        if auto_type:
            type_str = auto_type
        else:
            type_str = str(self.settings_mgr.get("core/type", "complex64"))

        dtype = DTYPE_MAP.get(type_str, np.complex64)
        self.is_complex = dtype in [np.complex64, np.complex128, np.int16]
        
        if dtype == np.complex64:
            self.data_type = np.float32
        elif dtype == np.complex128:
            self.data_type = np.float64
        else:
            self.data_type = dtype

        # Save to recent files list
        self._add_recent_file(path)

        # Clear all markers using refactored method
        self.clear_all_markers()

        # Close all Time Domain tabs (keep index 0 = Spectrogram)

        # Update sidebar file info
        self.update_sidebar_file_info(path, type_str)

        # Reprocess with the new file
        self.start_processing()

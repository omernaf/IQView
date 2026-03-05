import os
import pyqtgraph as pg
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog

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
            
        if hasattr(self, 'full_spectrogram_cache'):
            old_duration = self.time_duration
            old_bottom = old_fc - old_rate / 2
            if hasattr(self, 'total_samples_in_cache'):
                self.time_duration = self.total_samples_in_cache / self.rate
            else:
                self.time_duration = (old_duration * old_rate) / self.rate

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

            if not needs_reprocess:
                self.spectrogram_view.update_spectrogram(
                    self.full_spectrogram_cache, self.fc, self.rate, self.time_duration, auto_range=False
                )
        self.update_marker_info()

    def set_interaction_mode(self, mode):
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
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

    def on_filter_toggled(self, checked):
        self.filter_enabled = checked
        if self.filter_region:
            if checked and self.interaction_mode == 'FILTER' and getattr(self, 'filter_placed', False):
                self.filter_region.show()
            elif self.interaction_mode != 'FILTER' or not getattr(self, 'filter_placed', False):
                self.filter_region.hide()
        
        # Trigger reprocessing if we have data
        if hasattr(self, 'full_spectrogram_cache'):
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
        if getattr(self, 'filter_enabled', False) and hasattr(self, 'full_spectrogram_cache'):
            self.start_processing()

    def refresh_cursor(self):
        if hasattr(self, 'zoom_mode') and self.zoom_mode:
            self.spectrogram_view.setCursor(Qt.CursorShape.CrossCursor)
        elif self.interaction_mode in ['TIME', 'FREQ', 'FILTER']:
            self.spectrogram_view.setCursor(Qt.CursorShape.CrossCursor)
        elif self.interaction_mode == 'MOVE':
            self.spectrogram_view.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.spectrogram_view.setCursor(Qt.CursorShape.ArrowCursor)

    def open_time_domain_tab(self):
        if len(self.markers_time) < 2:
            return
            
        t1 = self.markers_time[0].value()
        t2 = self.markers_time[1].value()
        start_t, end_t = min(t1, t2), max(t1, t2)
        
        samples = self.extract_iq_segment(start_t, end_t)
        if samples is not None:
            from ..time_domain.view import TimeDomainView
            td_view = TimeDomainView(samples, start_t, self.rate, parent_window=self)
            idx = self.tabs.addTab(td_view, "Time Domain")
            self.tabs.setCurrentIndex(idx)
            self.update_tab_names()

    def reset_zoom(self):
        self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
        self.spectrogram_view.plot_item.autoRange()

    def handle_zoom_rectangle(self, rect, zoom_type='BOTH'):
        self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
        if rect.width() <= 0 and zoom_type != 'Y_ONLY': return
        if rect.height() <= 0 and zoom_type != 'X_ONLY': return
        if zoom_type == 'Y_ONLY': self.spectrogram_view.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
        elif zoom_type == 'X_ONLY': self.spectrogram_view.plot_item.setXRange(rect.left(), rect.right(), padding=0)
        else: self.spectrogram_view.plot_item.setRange(rect, padding=0)

    def fit_to_markers(self):
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

    def toggle_grid(self, axis, enabled):
        if axis == 'TIME': self.grid_time_enabled = enabled
        else: self.grid_freq_enabled = enabled
        self.update_grid(axis, force=True)

    def toggle_tracking(self, axis, enabled):
        if axis == 'TIME': self.grid_time_tracking = enabled
        else: self.grid_freq_tracking = enabled
        self.update_grid(axis, force=True)

    def update_grid(self, axis, force=False):
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
        v_min = (self.fc - self.rate/2) if is_freq else 0
        v_max = (self.fc + self.rate/2) if is_freq else self.time_duration
        
        pen = pg.mkPen(qcolor, width=1, style=style)
        
        curr = p1
        while curr <= v_max + 1e-9:
            line = pg.InfiniteLine(pos=curr, angle=angle, pen=pen, movable=False)
            line.setZValue(5)
            self.spectrogram_view.plot_item.addItem(line, ignoreBounds=True)
            grid_lines.append(line)
            curr += delta
        curr = p1 - delta
        while curr >= v_min - 1e-9:
            line = pg.InfiniteLine(pos=curr, angle=angle, pen=pen, movable=False)
            line.setZValue(5)
            self.spectrogram_view.plot_item.addItem(line, ignoreBounds=True)
            grid_lines.append(line)
            curr -= delta

    def undo_zoom(self):
        if self.zoom_history:
            prev_rect = self.zoom_history.pop()
            self.spectrogram_view.plot_item.setRange(rect=prev_rect, padding=0)

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
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open IQ File",
            os.path.dirname(self.file_path) if isinstance(self.file_path, str) else "",
            "IQ Files (*.32fc *.fc32 *.cs8 *.cu8 *.sc16 *.bin *.iq *.raw);;All Files (*)"
        )
        if path:
            self.load_new_file(path)

    def load_new_file(self, path):
        """Swap the data source to a new file and reprocess everything."""
        if not os.path.isfile(path):
            return

        # Update data source
        self.data_source = path
        self.file_path   = path
        self.setWindowTitle(f"IQView - {path}")

        # Re-resolve dtype from settings so we always use the last configured type
        import numpy as np
        dtype_map = {
            'np.int8': np.int8, 'np.int16': np.int16, 'np.int32': np.int32,
            'np.float32': np.float32, 'np.float64': np.float64,
            'int8': np.int8, 'int16': np.int16, 'int32': np.int32,
            'float32': np.float32, 'float64': np.float64,
            'np.complex64': np.complex64, 'complex64': np.complex64
        }
        type_str = str(self.settings_mgr.get("core/type", "complex64"))
        dtype = dtype_map.get(type_str, np.complex64)
        self.data_type = np.float32 if dtype == np.complex64 else dtype

        # Save to recent files list
        self._add_recent_file(path)

        # Clear all markers
        for m in self.markers_time:
            self.spectrogram_view.plot_item.removeItem(m)
        for m in self.markers_freq:
            self.spectrogram_view.plot_item.removeItem(m)
        self.markers_time.clear()
        self.markers_freq.clear()
        if hasattr(self, 'marker_panel'):
            self.marker_panel.update_headers(self.interaction_mode)

        # Close all Time Domain tabs (keep index 0 = Spectrogram)
        while self.tabs.count() > 1:
            widget = self.tabs.widget(1)
            self.tabs.removeTab(1)
            widget.deleteLater()

        # Reset zoom history and first-load flag
        self.zoom_history.clear()
        self.is_first_load = True

        # Reset filter state
        if self.filter_region:
            self.filter_region.hide()
        self.filter_enabled  = False
        self.filter_placed   = False
        self.filter_placing  = False
        self.filter_bounds   = []
        self.filter_marker_order = []
        if hasattr(self.marker_panel, 'filter_on_btn'):
            self.marker_panel.filter_on_btn.setChecked(False)

        # Reprocess with the new file
        self.start_processing()

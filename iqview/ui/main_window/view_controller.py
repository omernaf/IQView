import os
import pyqtgraph as pg
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from iqview.utils.helpers import DTYPE_MAP, AUDIO_EXTENSIONS, detect_type_from_ext, detect_params_from_filename, load_mat_file, load_audio_file, MatFileFormatError
from ..detached_window import DetachedViewWindow

class ViewControllerMixin:
    def on_parameters_changed(self, params):
        needs_reprocess = (self.fft_size != params['fft_size'] or 
                           self.overlap_percent != params['overlap_percent'] or
                           self.window_type != params['window_type'] or
                           getattr(self, 'window_size', None) != params.get('window_size', params['fft_size']))
        
        old_rate, old_fc = self.rate, self.fc
        self.rate, self.fc = params['fs'], params['fc']
        self.fft_size, self.window_type, self.overlap_percent = params['fft_size'], params['window_type'], params['overlap_percent']
        self.window_size = params.get('window_size', params['fft_size'])
        
        if hasattr(self, '_add_recent_file') and getattr(self, 'file_path', None):
            self._add_recent_file(self.file_path, type_str=getattr(self, 'current_type_str', None), fs=self.rate, fc=self.fc)
        
        if needs_reprocess:
            self.start_processing()
            
        # Remap current view and markers when fs or fc changed.
        # Works in both full-file and lazy mode (no full_spectrogram_cache required).
        old_duration = self.time_duration
        waterfall = self.spectrogram_view.is_waterfall
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
            if waterfall:
                # X = freq, Y = time
                rel_f_min = (vr[0][0] - (old_fc - old_rate/2)) / old_rate
                rel_f_max = (vr[0][1] - (old_fc - old_rate/2)) / old_rate
                rel_t_min, rel_t_max = vr[1][0] / old_duration, vr[1][1] / old_duration
            else:
                rel_t_min, rel_t_max = vr[0][0] / old_duration, vr[0][1] / old_duration
                rel_f_min = (vr[1][0] - old_bottom) / old_rate
                rel_f_max = (vr[1][1] - old_bottom) / old_rate

            new_bottom = self.fc - self.rate / 2
            if waterfall:
                self.spectrogram_view.plot_item.setXRange(
                    new_bottom + rel_f_min * self.rate,
                    new_bottom + rel_f_max * self.rate, padding=0)
                self.spectrogram_view.plot_item.setYRange(
                    rel_t_min * self.time_duration,
                    rel_t_max * self.time_duration, padding=0)
            else:
                self.spectrogram_view.plot_item.setXRange(
                    rel_t_min * self.time_duration, rel_t_max * self.time_duration, padding=0)
                self.spectrogram_view.plot_item.setYRange(
                    new_bottom + rel_f_min * self.rate,
                    new_bottom + rel_f_max * self.rate, padding=0)

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

    def on_multirow_changed(self, params):
        """Slot for SidePanel.multirowChanged signal.

        Validates / auto-computes missing values, stores them, and triggers
        reprocessing.  Also switches the QStackedWidget back to the standard
        view when num_rows <= 1.
        """
        num_rows = max(1, params.get('num_rows', 1))

        if num_rows <= 1:
            # Return to single-row / standard mode
            self._multirow_num_rows = 1
            if hasattr(self, 'spectrogram_stack'):
                self.spectrogram_stack.setCurrentIndex(0)
            if self._has_data():
                self.start_processing()
            return

        # --- Multi-row active ---
        start_sample = max(0, params.get('start_sample', 0))
        spr          = max(0, params.get('samples_per_row', 0))
        period       = max(0, params.get('period', 0))

        # Auto-compute missing values from file
        if self._has_data():
            total = self.get_total_samples()
            if spr <= 0:
                spr = max(1, total // num_rows)
            if period <= 0:
                period = spr
            # Update sidebar with computed defaults
            if hasattr(self, 'sidebar'):
                self.sidebar.update_multirow_defaults(spr, period)
        else:
            spr    = max(1, spr)
            period = max(1, period)

        # Clamp/validate frequency boundaries to [fc - fs/2, fc + fs/2]
        f_min_def = self.fc - self.rate / 2.0
        f_max_def = self.fc + self.rate / 2.0

        f_min = params.get('freq_min', f_min_def)
        f_max = params.get('freq_max', f_max_def)

        f_min = float(np.clip(f_min, f_min_def, f_max_def - 1.0))
        f_max = float(np.clip(f_max, f_min + 1.0, f_max_def))

        # Push back validated bounds to sidebar inputs
        if hasattr(self, 'sidebar') and hasattr(self.sidebar, 'freq_min_edit'):
            self.sidebar.freq_min_edit.set_hz(f_min)
            self.sidebar.freq_max_edit.set_hz(f_max)

        # Check if processing parameters changed (only re-process if row segmentation params change)
        prev_num_rows = getattr(self, '_multirow_num_rows', 1)
        prev_start    = getattr(self, '_multirow_start_sample', 0)
        prev_spr      = getattr(self, '_multirow_samples_per_row', 0)
        prev_period   = getattr(self, '_multirow_period', 0)

        needs_reprocess = (
            num_rows != prev_num_rows or
            start_sample != prev_start or
            spr != prev_spr or
            period != prev_period
        )

        self._multirow_num_rows       = num_rows
        self._multirow_start_sample   = start_sample
        self._multirow_samples_per_row = spr
        self._multirow_period         = period

        if hasattr(self, 'multi_row_view'):
            self.multi_row_view.set_freq_range(f_min, f_max)

        if needs_reprocess and self._has_data():
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
        elif self.interaction_mode == 'OVERLAY':
            self.spectrogram_view.setCursor(Qt.CursorShape.CrossCursor)
        elif self.interaction_mode == 'MOVE':
            self.spectrogram_view.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.spectrogram_view.setCursor(Qt.CursorShape.ArrowCursor)

    def _confirm_large_segment(self, start_t, end_t, tab_name) -> bool:
        """
        Warns the user if they are trying to open a large segment in a popup tab.
        Returns True if it's safe/approved to proceed, False otherwise.
        """
        num_samples = int(round(abs(end_t - start_t) * self.rate))
        # Warn if segment is larger than 10 million samples
        WARNING_THRESHOLD = 10_000_000
        if num_samples > WARNING_THRESHOLD:
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "Large Segment Warning",
                f"You are opening a segment with {num_samples:,} samples in the {tab_name} tab.\n\n"
                "Opening segments larger than 10,000,000 samples can cause significant lag or crash the application.\n\n"
                "Do you want to proceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            return reply == QMessageBox.StandardButton.Yes
        return True

    def open_time_domain_tab(self):
        """Extracts the IQ data between the two time markers (or full range) and opens it in a new tab."""
        markers = self.markers_time
        if len(markers) < 2:
            # Fallback to current view range. In waterfall mode, time is on Y.
            xr, yr = self.spectrogram_view.view_box.viewRange()
            time_range = yr if self.spectrogram_view.is_waterfall else xr
            start_t, end_t = time_range
        else:
            sorted_m = sorted(markers, key=lambda m: m.value())
            start_t, end_t = sorted_m[0].value(), sorted_m[1].value()
        
        if not self._confirm_large_segment(start_t, end_t, "Time Domain"):
            return

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
            xr, yr = self.spectrogram_view.view_box.viewRange()
            time_range = yr if self.spectrogram_view.is_waterfall else xr
            start_t, end_t = time_range
        else:
            sorted_m = sorted(markers, key=lambda m: m.value())
            start_t, end_t = sorted_m[0].value(), sorted_m[1].value()
            
        if not self._confirm_large_segment(start_t, end_t, "Frequency Domain"):
            return

        segment = self.extract_iq_segment(start_t, end_t)
        if segment is not None:
            from ..frequency_domain.view import FrequencyDomainView
            view = FrequencyDomainView(segment, self.fc, self.rate, parent_window=self)
            self.tabs.addTab(view, "Freq Domain")
            self.tabs.setCurrentWidget(view)
            self.update_tab_names()

    def open_eye_diagram_tab(self):
        """Extracts IQ data for the selected time range and opens an Eye Diagram tab."""
        markers = self.markers_time
        if len(markers) < 2:
            xr, yr = self.spectrogram_view.view_box.viewRange()
            time_range = yr if self.spectrogram_view.is_waterfall else xr
            start_t, end_t = time_range
        else:
            sorted_m = sorted(markers, key=lambda m: m.value())
            start_t, end_t = sorted_m[0].value(), sorted_m[1].value()

        if not self._confirm_large_segment(start_t, end_t, "Eye Diagram"):
            return

        segment = self.extract_iq_segment(start_t, end_t)
        if segment is not None:
            from ..eye_diagram_dialog import EyeDiagramView
            view = EyeDiagramView(segment, self.rate, parent_window=self)
            self.tabs.addTab(view, "Eye Diagram")
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
        from ..eye_diagram_dialog import EyeDiagramView

        if isinstance(widget, TimeDomainView):
            label = "Time Domain"
        elif isinstance(widget, EyeDiagramView):
            label = "Eye Diagram"
        else:
            label = "Freq Domain"
        self.tabs.addTab(widget, label)
        self.tabs.setCurrentWidget(widget)
        self.update_tab_names()

    def reset_zoom(self):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spec_tab_page and hasattr(active_tab, 'reset_zoom'):
            active_tab.reset_zoom()
        elif hasattr(self, 'spectrogram_stack') and self.spectrogram_stack.currentIndex() == 1:
            self.multi_row_view.reset_zoom()
        else:
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            self._zoom_to_full_range()

    def reset_zoom_x(self):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spec_tab_page and hasattr(active_tab, 'reset_zoom_x'):
            active_tab.reset_zoom_x()
        elif hasattr(self, 'spectrogram_stack') and self.spectrogram_stack.currentIndex() == 1:
            self.multi_row_view.reset_zoom_x()
        else:
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            sv = self.spectrogram_view
            if sv.is_waterfall:
                # In waterfall, X=freq — reset the freq axis
                f0, f1 = sv.full_f_range
                if f1 > f0:
                    sv.plot_item.setXRange(f0, f1, padding=0)
                else:
                    sv.plot_item.enableAutoRange(axis='x')
            else:
                t0, t1 = sv.full_t_range
                if t1 > t0:
                    sv.plot_item.setXRange(t0, t1, padding=0)
                else:
                    sv.plot_item.enableAutoRange(axis='x')

    def reset_zoom_y(self):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spec_tab_page and hasattr(active_tab, 'reset_zoom_y'):
            active_tab.reset_zoom_y()
        elif hasattr(self, 'spectrogram_stack') and self.spectrogram_stack.currentIndex() == 1:
            self.multi_row_view.reset_zoom_y()
        else:
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            sv = self.spectrogram_view
            if sv.is_waterfall:
                # In waterfall, Y=time — reset the time axis
                t0, t1 = sv.full_t_range
                if t1 > t0:
                    sv.plot_item.setYRange(t0, t1, padding=0)
                else:
                    sv.plot_item.enableAutoRange(axis='y')
            else:
                f0, f1 = sv.full_f_range
                if f1 > f0:
                    sv.plot_item.setYRange(f0, f1, padding=0)
                else:
                    sv.plot_item.enableAutoRange(axis='y')

    def _zoom_to_full_range(self):
        """Zoom to the full file extent using full_t_range / full_f_range.
        Falls back to autoRange() if the ranges aren't set yet."""
        sv = self.spectrogram_view
        t0, t1 = sv.full_t_range
        f0, f1 = sv.full_f_range
        if t1 > t0 and f1 > f0:
            if sv.is_waterfall:
                sv.plot_item.setXRange(f0, f1, padding=0)
                sv.plot_item.setYRange(t0, t1, padding=0)
            else:
                sv.plot_item.setXRange(t0, t1, padding=0)
                sv.plot_item.setYRange(f0, f1, padding=0)
        else:
            sv.plot_item.autoRange()

    def handle_zoom_rectangle(self, rect, zoom_type='BOTH', source_vb=None):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spec_tab_page and hasattr(active_tab, 'handle_zoom_rectangle'):
            active_tab.handle_zoom_rectangle(rect, zoom_type)
        elif hasattr(self, 'spectrogram_stack') and self.spectrogram_stack.currentIndex() == 1:
            self.multi_row_view.handle_zoom_rectangle(rect, zoom_type, source_vb=source_vb)
        else:
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            if rect.width() <= 0 and zoom_type != 'Y_ONLY': return
            if rect.height() <= 0 and zoom_type != 'X_ONLY': return
            if zoom_type == 'Y_ONLY': self.spectrogram_view.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
            elif zoom_type == 'X_ONLY': self.spectrogram_view.plot_item.setXRange(rect.left(), rect.right(), padding=0)
            else: self.spectrogram_view.plot_item.setRange(rect, padding=0)

    def fit_to_markers(self):
        active_tab = self.tabs.currentWidget()
        if active_tab and active_tab != self.spec_tab_page and hasattr(active_tab, 'fit_to_markers'):
            active_tab.fit_to_markers()
            return

        is_freq = (self.interaction_mode in ['FREQ', 'FREQ_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        if is_endless:
            active_markers = self.markers_freq_endless if is_freq else self.markers_time_endless
        else:
            active_markers = self.markers_freq if is_freq else self.markers_time

        if hasattr(self, 'spectrogram_stack') and self.spectrogram_stack.currentIndex() == 1:
            self.multi_row_view.fit_to_markers(active_markers)
            return

        if len(active_markers) == 2:
            self.zoom_history.append(self.spectrogram_view.plot_item.viewRect())
            v1, v2 = active_markers[0].value(), active_markers[1].value()
            v_min, v_max = min(v1, v2), max(v1, v2)
            waterfall = self.spectrogram_view.is_waterfall
            if is_freq:
                # freq axis: Y in standard, X in waterfall
                if waterfall:
                    self.spectrogram_view.plot_item.setXRange(v_min, v_max, padding=0)
                else:
                    self.spectrogram_view.plot_item.setYRange(v_min, v_max, padding=0)
            else:
                # time axis: X in standard, Y in waterfall
                if waterfall:
                    self.spectrogram_view.plot_item.setYRange(v_min, v_max, padding=0)
                else:
                    self.spectrogram_view.plot_item.setXRange(v_min, v_max, padding=0)

    def clear_all_markers(self):
        # Clear time / freq markers (regular and endless)
        all_markers = self.markers_time + self.markers_freq + self.markers_time_endless + self.markers_freq_endless
        for m in all_markers:
            self.spectrogram_view.plot_item.removeItem(m)
        self.markers_time.clear()
        self.markers_freq.clear()
        # Endless markers are now overlay-backed; clear_overlays handles list cleanup
        self.markers_time_endless.clear()
        self.markers_freq_endless.clear()

        # Clear user overlays (includes endless markers that were backed by overlays)
        if hasattr(self, 'clear_overlays'):
            self.clear_overlays(source='user')
        
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
        
        waterfall = self.spectrogram_view.is_waterfall
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
        # In standard mode: time on X (vr[0]), freq on Y (vr[1])
        # In waterfall mode: freq on X (vr[0]), time on Y (vr[1])
        if waterfall:
            # freq lines are now vertical (angle=90, on X axis)
            # time lines are now horizontal (angle=0, on Y axis)
            axis_range = vr[0] if is_freq else vr[1]
            line_angle = 90 if is_freq else 0
        else:
            # standard: freq lines horizontal (angle=0), time lines vertical (angle=90)
            axis_range = vr[1] if is_freq else vr[0]
            line_angle = 0 if is_freq else 90
        v_min_visible, v_max_visible = axis_range
        
        # Guard against too many markers
        if (v_max_visible - v_min_visible) / delta > 500:
            return

        theme = self.settings_mgr.get("ui/theme", "Dark").lower()
        color = self.settings_mgr.get(f"ui/{theme}/marker_grid_color", "#c8c8ff")
        style_name = self.settings_mgr.get(f"ui/{theme}/marker_grid_style", "SolidLine")
        alpha = int(self.settings_mgr.get("ui/marker_grid_alpha", 50))
        width = int(self.settings_mgr.get("ui/marker_grid_width", 1))
        
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
        
        pen = pg.mkPen(qcolor, width=width, style=style)
        
        # Start from first visible multiple of delta relative to p1
        start_count = np.ceil((v_min_visible - p1) / delta)
        curr = p1 + start_count * delta
        
        count = 0
        while curr <= v_max_visible + 1e-9 and count < 500:
            line = pg.InfiniteLine(pos=curr, angle=line_angle, pen=pen, movable=False)
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
        waterfall = self.spectrogram_view.is_waterfall
        if waterfall:
            visible_ratio_x = (xr_curr[1] - xr_curr[0]) / self.rate
            visible_ratio_y = (yr_curr[1] - yr_curr[0]) / self.time_duration
        else:
            visible_ratio_x = (xr_curr[1] - xr_curr[0]) / self.time_duration
            visible_ratio_y = (yr_curr[1] - yr_curr[0]) / self.rate
        if visible_ratio_x > 0.999 and visible_ratio_y > 0.999: return
        p1 = self.spectrogram_view.view_box.mapSceneToView(self.last_move_scene_pos)
        p2 = self.spectrogram_view.view_box.mapSceneToView(scene_pos)
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        new_xr = [xr_curr[0] - dx, xr_curr[1] - dx]
        new_yr = [yr_curr[0] - dy, yr_curr[1] - dy]
        if waterfall:
            # X = freq, Y = time
            f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
            if new_xr[0] < f_min: new_xr = [f_min, new_xr[1] - new_xr[0] + f_min]
            elif new_xr[1] > f_max: new_xr = [new_xr[0] - (new_xr[1] - f_max), f_max]
            if new_yr[0] < 0: new_yr = [0, new_yr[1] - new_yr[0]]
            elif new_yr[1] > self.time_duration: new_yr = [new_yr[0] - (new_yr[1] - self.time_duration), self.time_duration]
        else:
            # X = time, Y = freq
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

        audio_exts_str = " ".join([f"*{e}" for e in sorted(AUDIO_EXTENSIONS)])

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open IQ / Audio File",
            os.path.dirname(self.file_path) if isinstance(self.file_path, str) else "",
            f"IQ Files ({exts});;Audio Files ({audio_exts_str});;All Files (*)"
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

    def load_new_file(self, path, type_str=None, fs=None, fc=None):
        """Swap the data source to a new file and reprocess everything."""
        if not os.path.isfile(path):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "File Not Found", f"The file could not be found:\n{path}")
            if hasattr(self, '_remove_recent_file'):
                self._remove_recent_file(path)
            return

        # Save current user overlays before switching
        if hasattr(self, 'save_overlay_sidecar'):
            self.save_overlay_sidecar()

        # Clear previous user overlays (do NOT call clear_all_markers here —
        # it would also wipe markers which the user may want to keep).
        if hasattr(self, 'clear_overlays'):
            self.clear_overlays(source='user')

        # Update window title
        if getattr(self, 'custom_window_name', None):
            self.setWindowTitle(f"IQView - {self.custom_window_name}")
        else:
            self.setWindowTitle(f"IQView - {path}")

        if os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS:
            data_bytes, err_or_type, loaded_fs, loaded_fc, is_complex = load_audio_file(path)
            if data_bytes is not None:
                self.data_source = data_bytes
                self.file_path = path
                self.rate = fs if fs is not None else loaded_fs
                self.fc = fc if fc is not None else loaded_fc
                self.is_complex = is_complex
                self.data_type = np.float32
                type_str = err_or_type  # 'float32' on success

                # Update sidebar parameters
                if hasattr(self, 'sidebar'):
                    self.sidebar.update_params(fs=self.rate, fc=self.fc)
            else:
                QMessageBox.critical(
                    self,
                    "Unsupported Audio Format",
                    f"<b>Could not load audio file:</b><br>{os.path.basename(path)}<br><br>"
                    f"<pre style='font-family:Consolas;'>{err_or_type}</pre>"
                    f"<br>Supported formats: WAV, FLAC, OGG, AIFF, AU, W64, CAF, RF64, SD2"
                )
                return

        # Check if it's a .mat file
        elif path.lower().endswith('.mat'):
            try:
                mat_data = load_mat_file(path)
            except MatFileFormatError as exc:
                QMessageBox.critical(
                    self,
                    "Unsupported .mat File Format",
                    f"<b>{exc}</b><br><br><pre style='font-family:Consolas;'>{exc.detail}</pre>",
                )
                return
            if mat_data:
                data_source, loaded_type_str, loaded_fs, loaded_fc, is_complex = mat_data
                self.data_source = data_source
                self.file_path = path
                self.rate = fs if fs is not None else loaded_fs
                self.fc = fc if fc is not None else loaded_fc
                self.is_complex = is_complex
                type_str = loaded_type_str
                
                # Update sidebar parameters
                if hasattr(self, 'sidebar'):
                    self.sidebar.update_params(fs=fs, fc=fc)
                
                dtype = DTYPE_MAP.get(type_str, np.complex64)
                if dtype == np.complex64:
                    self.data_type = np.float32
                elif dtype == np.complex128:
                    self.data_type = np.float64
                else:
                    self.data_type = dtype
            else:
                # Error loading .mat file, return early
                return
        else:
            # Update data source and file path
            self.data_source = path
            self.file_path   = path
            
            # Detect fs and fc from filename if possible
            params = detect_params_from_filename(path)
            fs_detected = fs if fs is not None else params.get('fs')
            fc_detected = fc if fc is not None else params.get('fc')
            if fs_detected is not None or fc_detected is not None:
                if fs_detected is not None:
                    self.rate = fs_detected
                if fc_detected is not None:
                    self.fc = fc_detected
                if hasattr(self, 'sidebar'):
                    self.sidebar.update_params(fs=fs_detected, fc=fc_detected)

            # Priority: 1. Argument, 2. Auto-detection from filename, 3. App Settings
            if type_str is None:
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

        self.current_type_str = type_str
        
        # Save to recent files list
        if hasattr(self, '_add_recent_file'):
            self._add_recent_file(path, type_str, self.rate, self.fc)

        # Force spectrogram auto_range and scaling to reset
        self.is_first_load = True

        # Clear all markers using refactored method
        self.clear_all_markers()

        # Reset multi-row state for the new file
        self._multirow_num_rows        = 1
        self._multirow_start_sample    = 0
        self._multirow_samples_per_row = 0
        self._multirow_period          = 0
        if hasattr(self, 'sidebar') and hasattr(self.sidebar, 'num_rows_edit'):
            self.sidebar.num_rows_edit.setText('1')
        if hasattr(self, 'spectrogram_stack'):
            self.spectrogram_stack.setCurrentIndex(0)

        # Close all Time Domain tabs (keep index 0 = Spectrogram)

        # Update sidebar file info
        self.update_sidebar_file_info(path, type_str)

        # Reprocess with the new file
        self.start_processing()


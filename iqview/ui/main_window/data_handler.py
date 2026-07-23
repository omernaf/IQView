import io
import os
import numpy as np
from PyQt6.QtCore import pyqtSlot, QTimer
from iqview.dsp import FileReaderThread, ViewportAwareReader, MultiRowProcessor

_ZOOM_RERENDER_THRESHOLD = 0.5   # re-render when viewing <= 50% of the file

class DataHandlerMixin:
    # ------------------------------------------------------------------
    # Full-file processing (stdin / bytes sources, or lazy mode disabled)
    # ------------------------------------------------------------------

    def _has_data(self):
        """True when a data source has been loaded (works in both lazy and full-file modes)."""
        return self.data_source is not None

    @property
    def _lazy_enabled(self):
        """Per-instance lazy mode flag.
        Priority: CLI override stored in self._lazy_rendering_override
                  > QSettings 'core/lazy_rendering'
        Using a property (not a cached value) so Settings-dialog changes take effect
        immediately without restarting, while CLI flags still win."""
        override = getattr(self, '_lazy_rendering_override', None)
        if override is not None:
            return bool(override)
        return bool(self.settings_mgr.get("core/lazy_rendering", True))

    def get_total_samples(self):
        """Return the total IQ sample count for the current data source."""
        try:
            item_size = np.dtype(self.data_type).itemsize
            read_mult = 2 if self.is_complex else 1
            if isinstance(self.data_source, (bytes, bytearray)):
                file_size = len(self.data_source)
            else:
                file_size = os.path.getsize(self.data_source)
            return (file_size // item_size) // read_mult
        except Exception:
            return 0

    def get_active_filter_bounds(self):
        """Return (f_min, f_max) absolute frequency bounds if filter_mode is active, else (None, None)."""
        if not getattr(self, 'filter_mode', None):
            return None, None
        bounds = getattr(self, 'filter_bounds', None)
        if bounds and len(bounds) == 2:
            return float(min(bounds)), float(max(bounds))
        fr = getattr(self, 'filter_region', None)
        if fr:
            try:
                v_lo, v_hi = fr.getRegion()
                return float(min(v_lo, v_hi)), float(max(v_lo, v_hi))
            except Exception:
                pass
        return None, None

    def start_processing(self):
        """Main entry point to start file/data processing and display."""
        if self.data_source is None:
            return  # nothing loaded yet — waiting for user to open a file

        # Stop any running workers
        self._stop_all_workers()

        # ---- Multi-row mode check ----
        num_rows = getattr(self, '_multirow_num_rows', 1)
        if num_rows > 1 and isinstance(self.data_source, str):
            self._start_multirow_processing()
            return

        # Single-row: ensure standard view is shown
        if hasattr(self, 'spectrogram_stack'):
            self.spectrogram_stack.setCurrentIndex(0)
        if hasattr(self, 'restore_1row_filter_ui'):
            self.restore_1row_filter_ui()

        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: #00aaff; }"
        )

        f_min, f_max = self.get_active_filter_bounds()

        # Make frequencies relative to Fc for the baseband DSP filter
        f_min_rel = (f_min - self.fc) if f_min is not None else None
        f_max_rel = (f_max - self.fc) if f_max is not None else None

        lazy_enabled = self._lazy_enabled

        # Lazy mode only applies to file-path sources, not in-memory bytes
        if lazy_enabled and isinstance(self.data_source, str):
            # NOTE: do NOT set is_first_load here — that is only set by
            # load_new_file() / __init__ for genuine new-file loads.
            # Re-processing due to parameter/filter changes must NOT reset the zoom.
            self._schedule_lazy_render()
        else:
            # Fallback: traditional full-file processing
            self.worker = FileReaderThread(
                self.data_source, self.data_type, self.fft_size, self.overlap_percent,
                self.rate, self.profile_enabled, self.window_type,
                filter_mode=self.filter_mode, f_min=f_min_rel, f_max=f_max_rel,
                is_complex=self.is_complex,
                window_size=getattr(self, 'window_size', None),
                filter_type=str(self.settings_mgr.get("core/filter_type", "Elliptic")),
                filter_order=int(self.settings_mgr.get("core/filter_order", 8)),
                filter_ripple=float(self.settings_mgr.get("core/filter_ripple", 0.1)),
                filter_stopband=float(self.settings_mgr.get("core/filter_stopband", 60.0)),
                filter_taps=int(self.settings_mgr.get("core/filter_taps", 101)),
                fir_window=str(self.settings_mgr.get("core/fir_window", "Hamming")),
                filter_bessel_norm=str(self.settings_mgr.get("core/filter_bessel_norm", "phase"))
            )
            self.worker.progress.connect(self.update_progress)
            self.worker.finished_processing.connect(self.display_spectrogram)
            self.worker.start()

    # ------------------------------------------------------------------
    # Lazy / viewport-aware rendering
    # ------------------------------------------------------------------

    def _stop_all_workers(self):
        """Stop any running full-file, lazy, or multi-row workers."""
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
        if hasattr(self, 'lazy_worker') and self.lazy_worker.isRunning():
            self.lazy_worker.stop()
        if hasattr(self, '_multirow_worker') and self._multirow_worker.isRunning():
            self._multirow_worker.stop()
        # Cancel any pending zoom re-render
        if hasattr(self, '_zoom_rerender_timer') and self._zoom_rerender_timer.isActive():
            self._zoom_rerender_timer.stop()

    def _get_lazy_debounce_timer(self):
        """Return (creating if needed) the debounce timer for lazy renders."""
        if not hasattr(self, '_lazy_timer'):
            self._lazy_timer = QTimer()
            self._lazy_timer.setSingleShot(True)
            self._lazy_timer.timeout.connect(self._do_lazy_render)
        return self._lazy_timer

    def _update_sidebar_from_single_view(self):
        """Update sidebar inputs (samples_per_row, start_sample, freq_max, freq_min) in default 1-row mode."""
        sb = getattr(self, 'sidebar', None)
        if not sb or not hasattr(self, 'spectrogram_view'):
            return

        xr, yr = self.spectrogram_view.view_box.viewRange()
        waterfall = self.spectrogram_view.is_waterfall
        freq_range = xr if waterfall else yr
        time_range = yr if waterfall else xr

        f_lo, f_hi = freq_range[0], freq_range[1]
        t_min, t_max = max(0.0, time_range[0]), max(0.0, time_range[1])

        fs = max(getattr(self, 'rate', 1.0), 1.0)
        start_sample = int(round(t_min * fs))
        spr          = int(round((t_max - t_min) * fs))

        if hasattr(sb, 'freq_min_edit') and hasattr(sb, 'freq_max_edit'):
            sb.freq_min_edit.set_hz(f_lo)
            sb.freq_max_edit.set_hz(f_hi)

        if hasattr(sb, 'start_sample_edit') and hasattr(sb, 'samples_per_row_edit'):
            sb.start_sample_edit.blockSignals(True)
            sb.samples_per_row_edit.blockSignals(True)
            sb.start_sample_edit.setText(str(start_sample))
            sb.samples_per_row_edit.setText(str(spr))
            sb.start_sample_edit.blockSignals(False)
            sb.samples_per_row_edit.blockSignals(False)

    def on_viewport_changed(self):
        """Called by SpectrogramView whenever the visible range changes."""
        if self.data_source is None:
            return

        self._update_sidebar_from_single_view()

        if self._lazy_enabled and isinstance(self.data_source, str):
            self._schedule_lazy_render()
            return

        # Full mode: trigger high-res zoom re-render when sufficiently zoomed in
        if getattr(self, 'full_spectrogram_cache', None) is None:
            return   # no full render done yet
        self._schedule_zoom_rerender()

    def _schedule_multirow_rerender(self, delay_ms=250):
        """Debounced high-res re-render for multi-row view when time-zoomed."""
        if not hasattr(self, '_multirow_rerender_timer'):
            self._multirow_rerender_timer = QTimer()
            self._multirow_rerender_timer.setSingleShot(True)
            self._multirow_rerender_timer.timeout.connect(self._do_multirow_rerender)
        if self._multirow_rerender_timer.isActive():
            self._multirow_rerender_timer.stop()
        self._multirow_rerender_timer.start(delay_ms)

    def _do_multirow_rerender(self):
        """Re-run MultiRowProcessor for the active zoomed time window."""
        if self.data_source is None or not hasattr(self, 'multi_row_view'):
            return
        if not hasattr(self, 'spectrogram_stack') or self.spectrogram_stack.currentIndex() != 1:
            return

        num_rows     = getattr(self, '_multirow_num_rows', 1)
        base_start   = getattr(self, '_multirow_start_sample', 0)
        base_spr     = getattr(self, '_multirow_samples_per_row', 0)
        base_period  = getattr(self, '_multirow_period', base_spr)

        if base_spr <= 0:
            total = self.get_total_samples()
            base_spr = max(1, total // max(num_rows, 1))
        if base_period <= 0:
            base_period = base_spr

        # Check relative time bounds from multi_row_view
        rel_start, rel_end = getattr(self.multi_row_view, '_current_rel_time', (0.0, 1.0))

        zoomed_start_sample = base_start + int(round(rel_start * base_spr))
        zoomed_spr          = max(1, int(round((rel_end - rel_start) * base_spr)))

        self._multirow_start_sample   = zoomed_start_sample
        self._multirow_samples_per_row = zoomed_spr

        # 300% buffer (100% left, 100% visible, 100% right) for seamless dragging
        total_samples = self.get_total_samples()
        read_start_sample = max(0, zoomed_start_sample - zoomed_spr)
        read_spr          = min(total_samples - read_start_sample, zoomed_spr * 3)

        # Filter frequencies
        f_min, f_max = self.get_active_filter_bounds()
        f_min_rel = (f_min - self.fc) if f_min is not None else None
        f_max_rel = (f_max - self.fc) if f_max is not None else None

        if hasattr(self, '_multirow_worker') and self._multirow_worker.isRunning():
            self._multirow_worker.stop()

        self._multirow_worker = MultiRowProcessor(
            self.data_source, self.data_type, self.fft_size, self.rate,
            num_rows, read_start_sample, read_spr, base_period,
            is_complex=self.is_complex,
            window_type=self.window_type,
            overlap_percent=self.overlap_percent,
            window_size=getattr(self, 'window_size', None),
            filter_mode=self.filter_mode,
            f_min=f_min_rel,
            f_max=f_max_rel,
            filter_type=str(self.settings_mgr.get("core/filter_type", "Elliptic")),
            filter_order=int(self.settings_mgr.get("core/filter_order", 8)),
            filter_ripple=float(self.settings_mgr.get("core/filter_ripple", 0.1)),
            filter_stopband=float(self.settings_mgr.get("core/filter_stopband", 60.0)),
        )
        self._multirow_worker.progress.connect(self.update_progress)
        self._multirow_worker.finished.connect(self.display_multi_row)
        self._multirow_worker.start()

        self._multirow_display_params = {
            'start_sample':        zoomed_start_sample,
            'samples_per_row':     zoomed_spr,
            'period':              base_period,
            'read_start_sample':   read_start_sample,
            'read_samples_per_row': read_spr,
        }

    def _schedule_lazy_render(self, delay_ms=80):
        """Debounce repeated viewport changes — fire the actual render after a short pause."""
        timer = self._get_lazy_debounce_timer()
        if timer.isActive():
            timer.stop()
        timer.start(delay_ms)

    def _schedule_zoom_rerender(self, delay_ms=80):
        """Debounced zoom-aware re-render for full mode."""
        if not hasattr(self, '_zoom_rerender_timer'):
            self._zoom_rerender_timer = QTimer()
            self._zoom_rerender_timer.setSingleShot(True)
            self._zoom_rerender_timer.timeout.connect(self._do_zoom_rerender)
        if self._zoom_rerender_timer.isActive():
            self._zoom_rerender_timer.stop()
        self._zoom_rerender_timer.start(delay_ms)

    def _do_zoom_rerender(self):
        """In full mode: re-render at high res when zoomed in, restore cache when zoomed out."""
        if getattr(self, 'full_spectrogram_cache', None) is None:
            return

        xr, yr = self.spectrogram_view.view_box.viewRange()
        time_range = yr if self.spectrogram_view.is_waterfall else xr
        visible_duration = max(time_range[1] - time_range[0], 0.0)
        total_duration = getattr(self, 'time_duration', 1.0)

        visible_fraction = visible_duration / total_duration if total_duration > 0 else 1.0

        if visible_fraction >= _ZOOM_RERENDER_THRESHOLD:
            # Zoomed out enough — restore the full cached spectrogram
            if getattr(self, '_zoom_hires_active', False):
                self.spectrogram_view.update_spectrogram(
                    self.full_spectrogram_cache, self.fc, self.rate,
                    self.time_duration, auto_range=False
                )
                self._zoom_hires_active = False
            return

        # Zoomed in past threshold — launch a viewport-aware high-res render
        self._zoom_hires_active = True
        self._do_lazy_render()   # reuses all existing lazy machinery

    def _do_lazy_render(self):
        """Build and launch a ViewportAwareReader for the current viewport."""
        if self.data_source is None:
            return

        # Stop any still-running lazy worker
        if hasattr(self, 'lazy_worker') and self.lazy_worker.isRunning():
            self.lazy_worker.stop()

        # Determine the time range to render
        if self.is_first_load:
            # Before the first render we don't know the duration; use the whole file
            t_start, t_end = 0.0, self._estimate_file_duration()
            pixel_width = self.spectrogram_view.get_pixel_width()
        else:
            xr, yr = self.spectrogram_view.view_box.viewRange()
            # In standard mode: X=time, Y=freq.  In waterfall mode: X=freq, Y=time.
            time_range = yr if self.spectrogram_view.is_waterfall else xr
            view_width = max(time_range[1] - time_range[0], 1.0 / max(self.rate, 1))
            
            # Pre-generate exactly another screen width in each direction (3x total)
            file_duration = getattr(self, 'time_duration', self._estimate_file_duration())
            
            ideal_start = time_range[0] - view_width
            ideal_end = time_range[1] + view_width
            
            t_start = max(0.0, ideal_start)
            t_end = min(file_duration, ideal_end)
            
            # Scale pixel width proportionally so resolution remains constant
            base_pixel_width = self.spectrogram_view.get_pixel_width()
            rendered_width = t_end - t_start
            
            if rendered_width > 0 and view_width > 0:
                pixel_width = int(base_pixel_width * (rendered_width / view_width))
            else:
                pixel_width = base_pixel_width

        f_min, f_max = self.get_active_filter_bounds()
        f_min_rel = (f_min - self.fc) if f_min is not None else None
        f_max_rel = (f_max - self.fc) if f_max is not None else None

        self.lazy_worker = ViewportAwareReader(
            self.data_source, self.data_type, self.fft_size, self.rate,
            t_start, t_end, pixel_width,
            is_complex=self.is_complex,
            window_type=self.window_type,
            overlap_percent=self.overlap_percent,
            filter_mode=self.filter_mode,
            f_min=f_min_rel, f_max=f_max_rel,
            window_size=getattr(self, 'window_size', None),
            filter_type=str(self.settings_mgr.get("core/filter_type", "Elliptic")),
            filter_order=int(self.settings_mgr.get("core/filter_order", 8)),
            filter_ripple=float(self.settings_mgr.get("core/filter_ripple", 0.1)),
            filter_stopband=float(self.settings_mgr.get("core/filter_stopband", 60.0)),
            filter_taps=int(self.settings_mgr.get("core/filter_taps", 101)),
            fir_window=str(self.settings_mgr.get("core/fir_window", "Hamming")),
            filter_bessel_norm=str(self.settings_mgr.get("core/filter_bessel_norm", "phase"))
        )
        self.lazy_worker.progress.connect(self.update_progress)
        self.lazy_worker.finished_processing.connect(self.display_lazy_tile)
        self.lazy_worker.start()

        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: #00aaff; }"
        )

    def _estimate_file_duration(self):
        """Quick, cheap estimate of file duration before any processing is done."""
        try:
            item_size = np.dtype(self.data_type).itemsize
            read_mult = 2 if self.is_complex else 1
            if isinstance(self.data_source, (bytes, bytearray)):
                file_size = len(self.data_source)
            else:
                file_size = os.path.getsize(self.data_source)
            total_samples = (file_size // item_size) // read_mult
            return total_samples / max(self.rate, 1)
        except Exception:
            return 1.0

    # ------------------------------------------------------------------
    # Display slots
    # ------------------------------------------------------------------

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(np.ndarray, float, float)
    def display_spectrogram(self, full_spectrogram, t_start, t_end):
        """Slot for the legacy full-file FileReaderThread."""
        was_first = self.is_first_load
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: transparent; }"
        )
        self.full_spectrogram_cache = full_spectrogram
        total_duration = self._estimate_file_duration()
        self.time_duration = total_duration
        self.total_samples_in_cache = int(round(total_duration * self.rate))
        self.spectrogram_view.update_spectrogram(
            full_spectrogram, self.fc, self.rate, t_start, t_end,
            auto_range=self.is_first_load
        )
        self.is_first_load = False
        self.update_marker_info()
        # Load persisted overlays on first display
        if was_first and hasattr(self, 'load_overlay_sidecar'):
            self.load_overlay_sidecar()

    @pyqtSlot(np.ndarray, float, float)
    def display_lazy_tile(self, spectrogram, t_start, t_end):
        """Slot for ViewportAwareReader — updates only the visible image."""
        was_first = self.is_first_load
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: transparent; }"
        )

        duration = t_end - t_start
        if duration <= 0:
            return

        # On first load: store the full file duration so markers/scrollbars work
        if self.is_first_load:
            total_duration = self._estimate_file_duration()
            self.time_duration = total_duration
            self.total_samples_in_cache = int(round(total_duration * self.rate))
            # Set full ranges on the view but show only the computed tile
            self.spectrogram_view.full_t_range = (0.0, total_duration)
            self.spectrogram_view.full_f_range = (self.fc - self.rate / 2,
                                                   self.fc + self.rate / 2)

        # Update the image for the rendered tile
        self.spectrogram_view.update_lazy_tile(
            spectrogram, self.fc, self.rate, t_start, t_end,
            auto_range=self.is_first_load
        )
        self.is_first_load = False
        self.update_marker_info()
        # Load persisted overlays on first display
        if was_first and hasattr(self, 'load_overlay_sidecar'):
            self.load_overlay_sidecar()

    # ------------------------------------------------------------------
    # Multi-row processing
    # ------------------------------------------------------------------

    def _start_multirow_processing(self):
        """Create and launch a MultiRowProcessor for the current params."""
        # Switch to the multi-row view widget
        if hasattr(self, 'spectrogram_stack'):
            self.spectrogram_stack.setCurrentIndex(1)

        num_rows      = getattr(self, '_multirow_num_rows', 2)
        start_sample  = getattr(self, '_multirow_start_sample', 0)
        spr           = getattr(self, '_multirow_samples_per_row', 0)
        period        = getattr(self, '_multirow_period', 0)

        # Guard: auto-compute missing values
        if spr <= 0:
            total = self.get_total_samples()
            spr   = max(1, total // max(num_rows, 1))
        if period <= 0:
            period = spr

        total_samples = self.get_total_samples()
        read_start_sample = max(0, start_sample - spr)
        read_spr          = min(total_samples - read_start_sample, spr * 3)

        # Filter frequency offsets (relative to fc)
        f_min, f_max = self.get_active_filter_bounds()
        f_min_rel = (f_min - self.fc) if f_min is not None else None
        f_max_rel = (f_max - self.fc) if f_max is not None else None

        self._multirow_worker = MultiRowProcessor(
            self.data_source, self.data_type, self.fft_size, self.rate,
            num_rows, read_start_sample, read_spr, period,
            is_complex=self.is_complex,
            window_type=self.window_type,
            overlap_percent=self.overlap_percent,
            window_size=getattr(self, 'window_size', None),
            filter_mode=self.filter_mode,
            f_min=f_min_rel,
            f_max=f_max_rel,
            filter_type=str(self.settings_mgr.get("core/filter_type", "Elliptic")),
            filter_order=int(self.settings_mgr.get("core/filter_order", 8)),
            filter_ripple=float(self.settings_mgr.get("core/filter_ripple", 0.1)),
            filter_stopband=float(self.settings_mgr.get("core/filter_stopband", 60.0)),
        )
        self._multirow_worker.progress.connect(self.update_progress)
        self._multirow_worker.finished.connect(self.display_multi_row)
        self._multirow_worker.start()

        # Stash params so display_multi_row can build start_samples list
        self._multirow_display_params = {
            'start_sample':        start_sample,
            'samples_per_row':     spr,
            'period':              period,
            'read_start_sample':   read_start_sample,
            'read_samples_per_row': read_spr,
        }

        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: #00aaff; }"
        )

    @pyqtSlot(list)
    def display_multi_row(self, spectra_list):
        """Slot called when MultiRowProcessor finishes. Renders all rows."""
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: transparent; }"
        )

        p = getattr(self, '_multirow_display_params', {})
        vis_start_sample  = p.get('start_sample',    0)
        vis_spr           = max(1, p.get('samples_per_row', 1))
        period            = p.get('period',          0)
        if period <= 0:
            period = vis_spr

        read_start_sample = p.get('read_start_sample', vis_start_sample)
        read_spr          = p.get('read_samples_per_row', vis_spr)

        read_start_samples = [read_start_sample + i * period for i in range(len(spectra_list))]
        vis_start_samples  = [vis_start_sample + i * period for i in range(len(spectra_list))]

        self.multi_row_view.update_spectrograms(
            spectra_list, self.fc, self.rate, read_start_samples, read_spr, vis_start_samples, vis_spr
        )
        self.update_marker_info()

    # ------------------------------------------------------------------
    # IQ extraction (unchanged — reads directly from file)
    # ------------------------------------------------------------------

    def extract_iq_segment(self, start_sec, end_sec):
        """
        Extracts raw complex IQ samples from the data source for a given time range.
        Works with both file paths (on-disk) and in-memory bytes buffers (stdin mode).
        """
        try:
            start_sample = int(round(start_sec * self.rate))
            end_sample = int(round(end_sec * self.rate))
            if start_sample > end_sample: start_sample, end_sample = end_sample, start_sample

            num_samples = end_sample - start_sample
            if num_samples <= 0: return None

            # Safety Check: Warn if selection is exceptionally large (> 500 million samples)
            # 500M complex64 samples ≈ 4GB RAM.
            if num_samples > 500_000_000:
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.question(
                    self, "Large Data Extraction",
                    f"The selected range contains {num_samples:,} samples.\n\n"
                    "Extracting this many samples may consume significant memory and make the UI unresponsive.\n\n"
                    "Do you want to proceed?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return None

            item_size = np.dtype(self.data_type).itemsize
            read_multiplier = 2 if self.is_complex else 1
            offset = start_sample * read_multiplier * item_size

            # Open the source — either an in-memory BytesIO or a real file
            if isinstance(self.data_source, (bytes, bytearray)):
                f = io.BytesIO(self.data_source)
                f.seek(offset)
                raw_data = np.frombuffer(f.read(num_samples * read_multiplier * item_size), dtype=self.data_type).astype(np.float32)
            else:
                with open(self.data_source, 'rb') as f:
                    f.seek(offset)
                    raw_data = np.fromfile(f, dtype=self.data_type, count=num_samples * read_multiplier).astype(np.float32)

            if self.data_type == np.int16:
                raw_data /= 32768.0

            if self.is_complex:
                if self.data_type == np.float64:
                    complex_data = raw_data[0::2] + 1j * raw_data[1::2]
                else:
                    complex_data = raw_data[0::2].astype(np.float32) + 1j * raw_data[1::2].astype(np.float32)
            else:
                complex_data = raw_data.astype(np.complex64)

            # Apply Filter if enabled
            f_min, f_max = self.get_active_filter_bounds()
            if hasattr(self, 'filter_mode') and self.filter_mode and f_min is not None and f_max is not None:
                from iqview.dsp import apply_filter
                f_type = str(self.settings_mgr.get("core/filter_type", "Elliptic"))
                f_order = int(self.settings_mgr.get("core/filter_order", 8))
                f_ripple = float(self.settings_mgr.get("core/filter_ripple", 0.1))
                f_stopband = float(self.settings_mgr.get("core/filter_stopband", 60.0))
                f_bessel_norm = str(self.settings_mgr.get("core/filter_bessel_norm", "phase"))

                complex_data = apply_filter(
                    complex_data, self.rate, f_min - self.fc, f_max - self.fc,
                    filter_type=f_type, order=f_order,
                    rp=f_ripple, rs=f_stopband,
                    filter_taps=int(self.settings_mgr.get("core/filter_taps", 101)),
                    fir_window=str(self.settings_mgr.get("core/fir_window", "Hamming")),
                    mode=self.filter_mode,
                    bessel_norm=f_bessel_norm
                )

            return complex_data
        except Exception as e:
            print(f"Error extracting IQ segment: {e}")
            return None

import io
import os
import numpy as np
from PyQt6.QtCore import pyqtSlot, QTimer
from iqview.dsp import FileReaderThread, ViewportAwareReader

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

    def start_processing(self):
        if self.data_source is None:
            return  # nothing loaded yet — waiting for user to open a file

        # Stop any running workers
        self._stop_all_workers()

        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: #00aaff; }"
        )

        f_min, f_max = None, None
        if self.filter_region:
            v_low, v_high = self.filter_region.getRegion()
            f_min, f_max = min(v_low, v_high), max(v_low, v_high)

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
        """Stop both the full-file worker and the lazy worker if running."""
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
        if hasattr(self, 'lazy_worker') and self.lazy_worker.isRunning():
            self.lazy_worker.stop()

    def _get_lazy_debounce_timer(self):
        """Return (creating if needed) the debounce timer for lazy renders."""
        if not hasattr(self, '_lazy_timer'):
            self._lazy_timer = QTimer()
            self._lazy_timer.setSingleShot(True)
            self._lazy_timer.timeout.connect(self._do_lazy_render)
        return self._lazy_timer

    def on_viewport_changed(self):
        """Called by SpectrogramView whenever the visible range changes."""
        if self.data_source is None:
            return
        lazy_enabled = self._lazy_enabled
        if not lazy_enabled or not isinstance(self.data_source, str):
            return
        self._schedule_lazy_render()

    def _schedule_lazy_render(self, delay_ms=80):
        """Debounce repeated viewport changes — fire the actual render after a short pause."""
        timer = self._get_lazy_debounce_timer()
        if timer.isActive():
            timer.stop()
        timer.start(delay_ms)

    def _do_lazy_render(self):
        """Build and launch a ViewportAwareReader for the current viewport."""
        if self.data_source is None or not isinstance(self.data_source, str):
            return

        # Stop any still-running lazy worker
        if hasattr(self, 'lazy_worker') and self.lazy_worker.isRunning():
            self.lazy_worker.stop()

        # Determine the time range to render
        if self.is_first_load:
            # Before the first render we don't know the duration; use the whole file
            t_start, t_end = 0.0, self._estimate_file_duration()
        else:
            xr, _ = self.spectrogram_view.view_box.viewRange()
            t_start = max(0.0, xr[0])
            t_end   = t_start + max(xr[1] - xr[0], 1.0 / max(self.rate, 1))

        # Number of pixels wide the plot is right now
        pixel_width = self.spectrogram_view.get_pixel_width()

        f_min, f_max = None, None
        if self.filter_region:
            v_low, v_high = self.filter_region.getRegion()
            f_min, f_max = min(v_low, v_high), max(v_low, v_high)
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

    @pyqtSlot(np.ndarray, float)
    def display_spectrogram(self, full_spectrogram, duration):
        """Slot for the legacy full-file FileReaderThread."""
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: transparent; }"
        )
        self.full_spectrogram_cache = full_spectrogram
        self.time_duration = duration
        self.total_samples_in_cache = int(round(duration * self.rate))
        self.spectrogram_view.update_spectrogram(
            full_spectrogram, self.fc, self.rate, self.time_duration,
            auto_range=self.is_first_load
        )
        self.is_first_load = False
        self.update_marker_info()

    @pyqtSlot(np.ndarray, float, float)
    def display_lazy_tile(self, spectrogram, t_start, t_end):
        """Slot for ViewportAwareReader — updates only the visible image."""
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
            if hasattr(self, 'filter_mode') and self.filter_mode and self.filter_region:
                from iqview.dsp import apply_filter
                v_low, v_high = self.filter_region.getRegion()
                f_min, f_max = min(v_low, v_high), max(v_low, v_high)

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

import io
import numpy as np
from PyQt6.QtCore import pyqtSlot
from iqview.dsp import FileReaderThread

class DataHandlerMixin:
    def start_processing(self):
        if self.data_source is None:
            return  # nothing loaded yet — waiting for user to open a file
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: transparent; border: none; } QProgressBar::chunk { background-color: #00aaff; }")
        f_min, f_max = None, None
        if self.filter_region:
            v_low, v_high = self.filter_region.getRegion()
            f_min, f_max = min(v_low, v_high), max(v_low, v_high)

        self.worker = FileReaderThread(
            self.data_source, self.data_type, self.fft_size, self.overlap_percent, self.rate, 
            self.profile_enabled, self.window_type,
            filter_enabled=self.filter_enabled, f_min=f_min, f_max=f_max,
            is_complex=self.is_complex,
            filter_type=str(self.settings_mgr.get("core/filter_type", "Elliptic")),
            filter_order=int(self.settings_mgr.get("core/filter_order", 8)),
            filter_ripple=float(self.settings_mgr.get("core/filter_ripple", 0.1)),
            filter_stopband=float(self.settings_mgr.get("core/filter_stopband", 60.0)),
            filter_bessel_norm=str(self.settings_mgr.get("core/filter_bessel_norm", "phase"))
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.finished_processing.connect(self.display_spectrogram)
        self.worker.start()

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(np.ndarray, float)
    def display_spectrogram(self, full_spectrogram, duration):
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: transparent; border: none; } QProgressBar::chunk { background-color: transparent; }")
        self.full_spectrogram_cache = full_spectrogram
        self.time_duration = duration
        self.total_samples_in_cache = int(round(duration * self.rate))
        self.spectrogram_view.update_spectrogram(full_spectrogram, self.fc, self.rate, self.time_duration, auto_range=self.is_first_load)
        self.is_first_load = False
        self.update_marker_info()

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
            
            # Cap extraction for performance
            MAX_EXTRACT_SAMPLES = 1_000_000
            if num_samples > MAX_EXTRACT_SAMPLES:
                num_samples = MAX_EXTRACT_SAMPLES
                end_sample = start_sample + num_samples

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
                
            if self.is_complex:
                if self.data_type == np.float64:
                    complex_data = raw_data[0::2] + 1j * raw_data[1::2]
                else:
                    complex_data = raw_data[0::2].astype(np.float32) + 1j * raw_data[1::2].astype(np.float32)
            else:
                complex_data = raw_data.astype(np.complex64)
            
            # Apply Filter if enabled
            if hasattr(self, 'filter_enabled') and self.filter_enabled and self.filter_region:
                from iqview.dsp import apply_bpf
                v_low, v_high = self.filter_region.getRegion()
                f_min, f_max = min(v_low, v_high), max(v_low, v_high)
                
                f_type = str(self.settings_mgr.get("core/filter_type", "Elliptic"))
                f_order = int(self.settings_mgr.get("core/filter_order", 8))
                f_ripple = float(self.settings_mgr.get("core/filter_ripple", 0.1))
                f_stopband = float(self.settings_mgr.get("core/filter_stopband", 60.0))
                f_bessel_norm = str(self.settings_mgr.get("core/filter_bessel_norm", "phase"))
                
                complex_data = apply_bpf(
                    complex_data, self.rate, f_min, f_max,
                    filter_type=f_type, order=f_order,
                    rp=f_ripple, rs=f_stopband,
                    bessel_norm=f_bessel_norm
                )
                
            return complex_data
        except Exception as e:
            print(f"Error extracting IQ segment: {e}")
            return None

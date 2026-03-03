import numpy as np
from PyQt6.QtCore import pyqtSlot
from iqview.dsp import FileReaderThread

class DataHandlerMixin:
    def start_processing(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: transparent; border: none; } QProgressBar::chunk { background-color: #00aaff; }")
        self.worker = FileReaderThread(self.file_path, self.data_type, self.fft_size, self.overlap_percent, self.rate, self.profile_enabled, self.window_type)
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

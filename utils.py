import os
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from dsp import preprocess_chunk, postprocess_fft

class FileReaderThread(QThread):
    """
    Worker thread that reads the entire IQ file, processes it via DSP module, and emits the static spectrogram.
    """
    progress = pyqtSignal(int, int)
    finished_processing = pyqtSignal(np.ndarray)
    
    def __init__(self, filename, dtype, fft_size):
        super().__init__()
        self.filename = filename
        self.dtype = dtype
        self.fft_size = fft_size
        self.running = True
        self.window = np.hanning(fft_size).astype(np.float32)
        
        file_size = os.path.getsize(self.filename)
        item_size = np.dtype(self.dtype).itemsize
        num_items = file_size // item_size
        complex_samples = num_items // 2
        self.num_rows = complex_samples // self.fft_size
        
        # Pre-allocate large buffer for the entire spectrogram
        self.spectrogram = np.zeros((self.num_rows, self.fft_size), dtype=np.float32)
        
    def run(self):
        block_len = self.fft_size * 2
        chunk_bytes = block_len * np.dtype(self.dtype).itemsize
        
        try:
            with open(self.filename, 'rb') as f:
                row_idx = 0
                while self.running and row_idx < self.num_rows:
                    data_bytes = f.read(chunk_bytes)
                    if not data_bytes or len(data_bytes) < chunk_bytes:
                        break
                        
                    data_array = np.frombuffer(data_bytes, dtype=self.dtype)
                    complex_data = preprocess_chunk(data_array, self.window, self.fft_size)
                    fft_result = np.fft.fft(complex_data)
                    db_array = postprocess_fft(fft_result, self.fft_size)
                    
                    self.spectrogram[row_idx, :] = db_array
                    row_idx += 1
                    
                    # Periodically yield to UI and emit progress calculation
                    if row_idx % 100 == 0:
                        self.progress.emit(row_idx, self.num_rows)
                        QThread.msleep(1)
                
                if self.running:
                    # Emit transposed spectrogram so Time is X and Freq is Y
                    self.finished_processing.emit(self.spectrogram[:row_idx, :].T)
                    
        except Exception as e:
            print(f"Error reading file {self.filename}: {e}")
            
    def stop(self):
        self.running = False
        self.wait()

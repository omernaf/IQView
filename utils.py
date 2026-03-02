import os
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from dsp import preprocess_chunk, postprocess_fft

class FileReaderThread(QThread):
    """
    Worker thread that reads the entire IQ file, processes it via DSP module, and emits the static spectrogram.
    Now supports overlapping windows.
    """
    progress = pyqtSignal(int, int)
    finished_processing = pyqtSignal(np.ndarray)
    
    def __init__(self, filename, dtype, fft_size, overlap_percent=0.0):
        super().__init__()
        self.filename = filename
        self.dtype = dtype
        self.fft_size = fft_size
        self.running = True
        self.window = np.hanning(fft_size).astype(np.float32)
        
        # Calculate step size
        self.step_size = int(fft_size * (1.0 - overlap_percent / 100.0))
        self.step_size = max(1, self.step_size)
        
        item_size = np.dtype(self.dtype).itemsize
        file_size = os.path.getsize(self.filename)
        num_items = file_size // item_size
        self.complex_samples = num_items // 2
        
        # Calculate how many rows we will have
        # (N - overlap) / step
        if self.complex_samples > self.fft_size:
            self.num_rows = (self.complex_samples - self.fft_size) // self.step_size + 1
        else:
            self.num_rows = 0
            
        # Limit rows for mega-files to avoid memory crash
        max_rows = 100000 
        if self.num_rows > max_rows:
            self.num_rows = max_rows
        
        # Pre-allocate spectrogram
        self.spectrogram = np.zeros((self.num_rows, self.fft_size), dtype=np.float32)
        
    def run(self):
        if self.num_rows == 0:
            self.finished_processing.emit(np.zeros((self.fft_size, 1), dtype=np.float32))
            return

        item_size = np.dtype(self.dtype).itemsize
        chunk_read_size = self.fft_size * 2 # 2 because I/Q
        
        import time
        start_time = time.time()
        dsp_time = 0.0
        read_time = 0.0
        seek_time = 0.0
        overhead_time = 0.0
        
        try:
            with open(self.filename, 'rb') as f:
                row_idx = 0
                while self.running and row_idx < self.num_rows:
                    loop_start = time.time()
                    
                    # Seek Time
                    t_seek_start = time.time()
                    pos = row_idx * self.step_size * 2 * item_size
                    f.seek(pos)
                    seek_time += (time.time() - t_seek_start)
                    
                    # Read Time
                    t_read_start = time.time()
                    data_bytes = f.read(chunk_read_size * item_size)
                    read_time += (time.time() - t_read_start)
                    
                    if not data_bytes or len(data_bytes) < chunk_read_size * item_size:
                        break
                    
                    # DSP Time
                    t_dsp_start = time.time()
                    data_array = np.frombuffer(data_bytes, dtype=self.dtype)
                    complex_data = preprocess_chunk(data_array, self.window, self.fft_size)
                    fft_result = np.fft.fft(complex_data)
                    db_array = postprocess_fft(fft_result, self.fft_size)
                    self.spectrogram[row_idx, :] = db_array
                    dsp_time += (time.time() - t_dsp_start)
                    
                    row_idx += 1
                    
                    # Overhead include progress update and sleep
                    overhead_start = time.time()
                    if row_idx % 200 == 0:
                        self.progress.emit(row_idx, self.num_rows)
                        QThread.msleep(1)
                    overhead_time += (time.time() - overhead_start)
                    
                total_time = time.time() - start_time
                if self.running:
                    io_time = seek_time + read_time
                    other_time = total_time - (io_time + dsp_time + overhead_time)
                    print(f"\n" + "-"*30)
                    print(f"Processing Complete:")
                    print(f" - Total Time:    {total_time:.3f}s (100.0%)")
                    print(f" - DSP Time:      {dsp_time:.3f}s ({(dsp_time/total_time)*100:.1f}%)")
                    print(f" - I/O Time:      {io_time:.3f}s ({((io_time)/total_time)*100:.1f}%)")
                    print(f"   - f.seek:      {seek_time:.3f}s")
                    print(f"   - f.read:      {read_time:.3f}s")
                    print(f" - UI/Overhead:   {overhead_time:.3f}s ({(overhead_time/total_time)*100:.1f}%)")
                    print(f" - Other/Python:  {other_time:.3f}s ({(other_time/total_time)*100:.1f}%)")
                    print("-"*30 + "\n")
                    self.finished_processing.emit(self.spectrogram[:row_idx, :].T)
                    
        except Exception as e:
            print(f"Error reading file {self.filename}: {e}")
            
    def stop(self):
        self.running = False
        self.wait()

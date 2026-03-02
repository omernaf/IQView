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
        
        # Batching parameters
        batch_size = 1000
        
        try:
            with open(self.filename, 'rb') as f:
                row_idx = 0
                while self.running and row_idx < self.num_rows:
                    rows_to_process = min(batch_size, self.num_rows - row_idx)
                    
                    # Seek Time
                    t_seek_start = time.time()
                    pos = row_idx * self.step_size * 2 * item_size
                    f.seek(pos)
                    seek_time += (time.time() - t_seek_start)
                    
                    # Read Time (Batch)
                    # For batches, we read raw bytes for the entire chunk. 
                    # Note: This slightly over-reads if there's overlap, but it's faster than repeated seeks.
                    t_read_start = time.time()
                    total_samples_to_read = (rows_to_process - 1) * self.step_size + self.fft_size
                    data_bytes = f.read(total_samples_to_read * 2 * item_size)
                    read_time += (time.time() - t_read_start)
                    
                    if not data_bytes or len(data_bytes) < (total_samples_to_read * 2 * item_size):
                        # Handle end of file or incomplete read
                        if not data_bytes: break
                    
                    # DSP Time (Batch)
                    t_dsp_start = time.time()
                    # Convert raw bytes to complex array
                    raw_array = np.frombuffer(data_bytes, dtype=self.dtype)
                    # Real/Imag de-interleave
                    full_complex = raw_array[0::2] + 1j * raw_array[1::2]
                    
                    # Extract windows into a 2D array for vectorized processing
                    # We use stride_tricks to avoid copying data where possible
                    from numpy.lib.stride_tricks import as_strided
                    itemsize = full_complex.itemsize
                    complex_batch = as_strided(
                        full_complex,
                        shape=(rows_to_process, self.fft_size),
                        strides=(self.step_size * itemsize, itemsize),
                        writeable=False
                    )
                    
                    # Apply window (vectorized across all rows)
                    windowed_batch = complex_batch * self.window
                    
                    # FFT (vectorized across all rows)
                    fft_batch = np.fft.fft(windowed_batch, axis=1)
                    
                    # Post-process (vectorized)
                    shifted_batch = np.fft.fftshift(fft_batch, axes=1)
                    mag_batch = np.abs(shifted_batch)
                    epsilon = np.float32(1e-10)
                    mag_batch = np.maximum(mag_batch, epsilon)
                    db_batch = 20.0 * np.log10(mag_batch)
                    
                    self.spectrogram[row_idx : row_idx + rows_to_process, :] = db_batch
                    dsp_time += (time.time() - t_dsp_start)
                    
                    row_idx += rows_to_process
                    
                    # Overhead
                    overhead_start = time.time()
                    self.progress.emit(row_idx, self.num_rows)
                    QThread.msleep(1)
                    overhead_time += (time.time() - overhead_start)
                    
                total_time = time.time() - start_time
                if self.running:
                    io_time = seek_time + read_time
                    other_time = total_time - (io_time + dsp_time + overhead_time)
                    print(f"\n" + "-"*30)
                    print(f"Processing Complete (BATCHED):")
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

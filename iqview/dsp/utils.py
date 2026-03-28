import io
import os
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from scipy import signal
from .dsp import preprocess_chunk, postprocess_fft, apply_filter, design_filter

class FileReaderThread(QThread):
    """
    Worker thread that reads the entire IQ data source, processes it via DSP module,
    and emits the static spectrogram.  Supports overlapping windows and Band-Pass filtering.

    `source` can be either:
      - str  : path to a binary IQ file on disk
      - bytes: raw IQ bytes already loaded in memory (e.g. piped from stdin)
    """
    progress = pyqtSignal(int, int)
    finished_processing = pyqtSignal(np.ndarray, float)
    
    def __init__(self, source, dtype, fft_size, overlap_percent, sample_rate, 
                 profile_enabled=False, window_type="Hanning",
                 filter_mode=None, f_min=None, f_max=None, is_complex=True, **kwargs):
        super().__init__()
        self.source = source
        self.dtype = dtype
        self.is_complex = is_complex
        self.fft_size = fft_size
        self.sample_rate = sample_rate
        self.profile_enabled = profile_enabled
        self.running = True
        
        self.filter_bessel_norm = kwargs.get('filter_bessel_norm', 'phase')
        
        # Precompute frequency-domain BPF/BSF response mask
        self.freq_mask = None
        if filter_mode in ['bpf', 'bsf'] and f_min is not None and f_max is not None:
            sos, f_center = design_filter(sample_rate, f_min, f_max, **kwargs)
            if sos is not None:
                bin_freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, 1.0 / sample_rate))
                f_eval = bin_freqs - f_center
                _, h = signal.sosfreqz(sos, f_eval, fs=sample_rate)
                h_abs = np.abs(h).astype(np.float32)
                if filter_mode == 'bsf':
                    self.freq_mask = 1.0 - h_abs
                else:
                    self.freq_mask = h_abs
        
        # Select Window Function
        if window_type == "Hanning":
            self.window = np.hanning(fft_size).astype(np.float32)
        elif window_type == "Hamming":
            self.window = np.hamming(fft_size).astype(np.float32)
        elif window_type == "Blackman":
            self.window = np.blackman(fft_size).astype(np.float32)
        elif window_type == "Bartlett":
            self.window = np.bartlett(fft_size).astype(np.float32)
        else: # Rectangular / None
            self.window = np.ones(fft_size, dtype=np.float32)
        
        # Calculate step size based on requested overlap
        req_step_size = int(fft_size * (1.0 - overlap_percent / 100.0))
        req_step_size = max(1, req_step_size)
        
        item_size = np.dtype(self.dtype).itemsize
        # Determine data size — works for both file paths and in-memory bytes
        if isinstance(source, (bytes, bytearray)):
            file_size = len(source)
        else:
            file_size = os.path.getsize(source)
        num_items = file_size // item_size
        self.total_samples = num_items // 2 if self.is_complex else num_items
        self.complex_samples = self.total_samples # Alias for backwards compatibility in logic
        
        # We want to cover the whole file. 
        # Calculate how many rows would be needed with requested step_size
        if self.complex_samples > self.fft_size:
            requested_rows = (self.complex_samples - self.fft_size) // req_step_size + 1
        else:
            requested_rows = 0
            
        # Memory/Performance Cap: Limit to ~20,000 rows for the "Static" view
        # If requested_rows exceeds this, we must increase step_size to cover the whole file
        max_rows_limit = 20000 
        
        if requested_rows > max_rows_limit and requested_rows > 0:
            self.num_rows = max_rows_limit
            # Ensure the last window (fft_size) ends exactly at or before complex_samples
            # (num_rows - 1) * step_size + fft_size <= complex_samples
            # step_size <= (complex_samples - fft_size) / (num_rows - 1)
            self.step_size = (self.complex_samples - self.fft_size) // (self.num_rows - 1)
            self.step_size = max(req_step_size, self.step_size)
        else:
            self.num_rows = requested_rows
            self.step_size = req_step_size
            
        # Pre-allocate spectrogram
        self.spectrogram = np.zeros((self.num_rows, self.fft_size), dtype=np.float32)
        
    def run(self):
        if self.num_rows <= 0:
            self.finished_processing.emit(np.zeros((self.fft_size, 1), dtype=np.float32), 0.0)
            return

        item_size = np.dtype(self.dtype).itemsize
        # chunk_read_size = self.fft_size * (2 if self.is_complex else 1)
        
        import time
        start_time = time.time()
        dsp_time = 0.0
        read_time = 0.0
        seek_time = 0.0
        overhead_time = 0.0
        
        # Batching parameters
        batch_size = 1000
        
        # Open the data source — both io.BytesIO and a real file support .read() / .seek()
        if isinstance(self.source, (bytes, bytearray)):
            data_file = io.BytesIO(self.source)
        else:
            data_file = open(self.source, 'rb')
        
        try:
            with data_file as f:
                row_idx = 0
                while self.running and row_idx < self.num_rows:
                    rows_to_process = min(batch_size, self.num_rows - row_idx)
                    
                    # Seek Time
                    t_seek_start = time.time()
                    read_multiplier = 2 if self.is_complex else 1
                    pos = row_idx * self.step_size * read_multiplier * item_size
                    f.seek(pos)
                    seek_time += (time.time() - t_seek_start)
                    
                    # Read Time (Batch)
                    t_read_start = time.time()
                    total_samples_to_read = (rows_to_process - 1) * self.step_size + self.fft_size
                    data_bytes = f.read(total_samples_to_read * read_multiplier * item_size)
                    read_time += (time.time() - t_read_start)
                    
                    if not data_bytes or len(data_bytes) < (total_samples_to_read * read_multiplier * item_size):
                        # Handle end of file or incomplete read
                        if not data_bytes: break
                    
                    # DSP Time (Batch)
                    t_dsp_start = time.time()
                    # Convert raw bytes to complex array
                    raw_array = np.frombuffer(data_bytes, dtype=self.dtype).astype(np.float32)
                    
                    if self.dtype == np.int16:
                        raw_array /= 32768.0
                    
                    if self.is_complex:
                        # Real/Imag de-interleave
                        full_complex = raw_array[0::2] + 1j * raw_array[1::2]
                    else:
                        # Already real samples, just treat as complex with 0 imag
                        full_complex = raw_array.astype(np.complex64)
                    
                    # No time-domain filtering — BPF is applied in the frequency domain
                    # below (after fftshift) for maximum performance and visual consistency.

                    # Extract windows into a 2D array for vectorized processing
                    # We use stride_tricks to avoid copying data where possible
                    from numpy.lib.stride_tricks import as_strided
                    itemsize = full_complex.itemsize
                    
                    # SAFETY CHECK: Ensure we don't stride past the end of full_complex
                    # The last element accessed is (rows_to_process - 1) * step_size + (fft_size - 1)
                    required_samples = (rows_to_process - 1) * self.step_size + self.fft_size
                    if len(full_complex) < required_samples:
                        # Pad with zeros if we under-read (should be rare with fixed step_size)
                        padded = np.zeros(required_samples, dtype=full_complex.dtype)
                        padded[:len(full_complex)] = full_complex
                        full_complex = padded

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
                    
                    # Apply frequency-domain BPF response mask
                    if self.freq_mask is not None:
                        shifted_batch *= self.freq_mask # broadcast across batch, zero-cost
                        
                    mag_batch = np.abs(shifted_batch)
                    epsilon = np.float32(1e-10)
                    mag_batch = np.maximum(mag_batch, epsilon)
                    db_batch = 20.0 * np.log10(mag_batch)
                    
                    self.spectrogram[row_idx : row_idx + rows_to_process, :] = db_batch
                    dsp_time += (time.time() - t_dsp_start)
                    
                    row_idx += rows_to_process
                    
                    # Overhead
                    overhead_start = time.time()
                    if row_idx == self.num_rows or row_idx % max(1, self.num_rows // 20) == 0:
                        self.progress.emit(row_idx, self.num_rows)
                    overhead_time += (time.time() - overhead_start)
                    
                total_time = time.time() - start_time
                if self.running:
                    actual_rows = row_idx
                    total_duration = 0.0
                    if actual_rows > 0:
                        total_samples_processed = (actual_rows - 1) * self.step_size + self.fft_size
                        total_duration = total_samples_processed / self.sample_rate
                    
                    io_time = seek_time + read_time
                    other_time = total_time - (io_time + dsp_time + overhead_time)
                    
                    if self.profile_enabled:
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
                    
                    self.finished_processing.emit(self.spectrogram[:actual_rows, :].T, total_duration)
                    
        except Exception as e:
            print(f"Error reading IQ source: {e}")
            
    def stop(self):
        self.running = False
        self.wait()


class ViewportAwareReader(QThread):
    """
    On-demand / lazy spectrogram renderer.

    Instead of processing the entire file, this thread only reads the file
    slice that corresponds to [t_start, t_end] seconds and computes exactly
    `pixel_width` FFT rows — one per horizontal pixel available in the plot.

    This means:
     - Initial load is nearly instant (only the visible portion is computed).
     - Zooming in re-renders at higher resolution automatically.
     - Very large files that cannot fit in RAM work correctly.

    Signals
    -------
    progress(current, total)
    finished_processing(spectrogram_2d, t_start, t_end)
        spectrogram_2d : np.ndarray, shape (fft_size, num_rows)  — same
                         orientation as FileReaderThread so the display code
                         is identical.
        t_start, t_end : float — the time range this render covers in seconds.
    """

    progress = pyqtSignal(int, int)
    finished_processing = pyqtSignal(np.ndarray, float, float)

    # Number of extra samples added on each side of the slice before the BPF
    # is applied.  These samples are processed but the resulting FFT rows
    # that fall entirely within the guard are discarded.  This avoids filter
    # transient artefacts at both edges.
    BPF_GUARD_SAMPLES = 4096

    def __init__(self, source, dtype, fft_size, sample_rate, t_start, t_end,
                 pixel_width, is_complex=True, window_type="Hanning",
                 overlap_percent=0.0,
                 filter_mode=None, f_min=None, f_max=None,
                 **kwargs):
        super().__init__()
        self.source        = source
        self.dtype         = dtype
        self.fft_size      = fft_size
        self.sample_rate   = sample_rate
        self.t_start       = t_start
        self.t_end         = t_end
        self.pixel_width   = max(1, int(pixel_width))
        self.is_complex    = is_complex
        self.running       = True

        # Filter settings
        self.filter_mode      = filter_mode
        self.f_min            = f_min
        self.f_max            = f_max
        self.filter_type      = kwargs.get('filter_type', 'Elliptic')
        self.filter_order     = kwargs.get('filter_order', 8)
        self.filter_ripple    = kwargs.get('filter_ripple', 0.1)
        self.filter_stopband  = kwargs.get('filter_stopband', 60.0)
        self.filter_bessel_norm = kwargs.get('filter_bessel_norm', 'phase')

        # Window function
        if window_type == "Hanning":
            self.window = np.hanning(fft_size).astype(np.float32)
        elif window_type == "Hamming":
            self.window = np.hamming(fft_size).astype(np.float32)
        elif window_type == "Blackman":
            self.window = np.blackman(fft_size).astype(np.float32)
        elif window_type == "Bartlett":
            self.window = np.bartlett(fft_size).astype(np.float32)
        else:
            self.window = np.ones(fft_size, dtype=np.float32)

        # --- Derive sample indices ---
        item_size = np.dtype(dtype).itemsize
        if isinstance(source, (bytes, bytearray)):
            file_size = len(source)
        else:
            file_size = os.path.getsize(source)

        read_multiplier = 2 if is_complex else 1
        num_items = file_size // item_size
        total_samples = num_items // read_multiplier

        # Clamp requested range to file bounds
        self.s_start = max(0, int(round(t_start * sample_rate)))
        self.s_end   = min(total_samples, int(round(t_end   * sample_rate)))

        view_samples = self.s_end - self.s_start
        if view_samples <= 0:
            self.num_rows = 0
            return

        # --- Row count & step size ---
        # Goal: produce multiple rows per pixel width — enough to make the image perceptually
        # richer and detailed via automatic downsampling, but keeping runtime strictly bounded.
        #
        # By targeting ~4x pixel_width rows, we rely on the Qt backend's autoDownsample
        # to compress fine signal components visually, delivering excellent "overlap"
        # appearance while completely dodging the 20,000+ row read bottlenecks.
        target_rows = max(1, self.pixel_width * 4)

        req_step     = max(1, int(fft_size * (1.0 - overlap_percent / 100.0)))
        natural_step = max(1, (view_samples - fft_size) // max(target_rows - 1, 1))
        self.step_size = max(req_step, natural_step)

        max_possible_rows = max(1, (view_samples - fft_size) // self.step_size + 1)
        self.num_rows = min(max_possible_rows, target_rows)

        # Precompute frequency-domain BPF response (much better than binary mask).
        # We use the same filter design as the time-domain path, then evaluate
        # its frequency response (roll-off) at each FFT bin.
        self.freq_mask = None
        if filter_mode in ['bpf', 'bsf'] and f_min is not None and f_max is not None:
            sos, f_center = design_filter(sample_rate, f_min, f_max, **kwargs)
            if sos is not None:
                # Get bins relative to fc (baseband)
                bin_freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, 1.0 / sample_rate))
                # Evaluate at (bin_freq - f_center) because the filter is designed as a low-pass 
                # on a signals that was shifted by -f_center in the time domain.
                f_eval = bin_freqs - f_center
                _, h = signal.sosfreqz(sos, f_eval, fs=sample_rate)
                h_abs = np.abs(h).astype(np.float32)
                if filter_mode == 'bsf':
                    self.freq_mask = 1.0 - h_abs
                else:
                    self.freq_mask = h_abs

        # No guard region needed — we no longer filter in time-domain
        self.s_read_start = self.s_start
        self.s_read_end   = self.s_end

    # ------------------------------------------------------------------
    def run(self):
        if self.num_rows <= 0:
            self.finished_processing.emit(
                np.zeros((self.fft_size, 1), dtype=np.float32),
                self.t_start, self.t_end)
            return

        item_size   = np.dtype(self.dtype).itemsize
        read_mult   = 2 if self.is_complex else 1

        if isinstance(self.source, (bytes, bytearray)):
            data_file = io.BytesIO(self.source)
        else:
            data_file = open(self.source, 'rb')

        try:
            with data_file as f:
                spectrogram = np.zeros((self.num_rows, self.fft_size), dtype=np.float32)
                row_idx = 0
                max_read_samples = 1_000_000  # Cap memory usage per batch to ~8MB (1M complex64)
                
                while self.running and row_idx < self.num_rows:
                    batch_now = self.num_rows - row_idx
                    
                    # Logic: If step_size >= fft_size, we just read one row at a time.
                    if self.step_size >= self.fft_size:
                        batch_now = 1
                    else:
                        # Limit batch size to keep reads under max_read_samples
                        span_samples = (batch_now - 1) * self.step_size + self.fft_size
                        if span_samples > max_read_samples:
                            batch_now = max(1, (max_read_samples - self.fft_size) // self.step_size + 1)
                            
                    samples_to_read = (batch_now - 1) * self.step_size + self.fft_size
                    
                    # Read directly into buffer
                    start_sample = self.s_read_start + row_idx * self.step_size
                    offset_bytes = start_sample * read_mult * item_size
                    
                    f.seek(offset_bytes)
                    raw_bytes = f.read(samples_to_read * read_mult * item_size)
                    
                    if not raw_bytes or len(raw_bytes) < (samples_to_read * read_mult * item_size):
                        if not raw_bytes: break

                    raw_array = np.frombuffer(raw_bytes, dtype=self.dtype).astype(np.float32)
                    if self.dtype == np.int16:
                        raw_array /= 32768.0

                    if self.is_complex:
                        valid_complex = raw_array[0::2] + 1j * raw_array[1::2]
                    else:
                        valid_complex = raw_array.astype(np.complex64)

                    if len(valid_complex) < self.fft_size:
                        padded = np.zeros(self.fft_size, dtype=np.complex64)
                        padded[:len(valid_complex)] = valid_complex
                        valid_complex = padded

                    if batch_now == 1:
                        # Single row
                        windowed  = valid_complex[:self.fft_size] * self.window
                        # Expand dimensions to make it 2D so fft functions behave like batch processing
                        windowed  = windowed[np.newaxis, :]
                        fft_out   = np.fft.fft(windowed, axis=1)
                        shifted   = np.fft.fftshift(fft_out, axes=1)
                        if self.freq_mask is not None:
                            shifted *= self.freq_mask
                        mag       = np.abs(shifted)
                        mag       = np.maximum(mag, np.float32(1e-10))
                        db        = 20.0 * np.log10(mag)
                        spectrogram[row_idx] = db[0]
                    else:
                        # Batch rows using as_strided
                        from numpy.lib.stride_tricks import as_strided
                        itemsize_c = valid_complex.itemsize
                        
                        required = (batch_now - 1) * self.step_size + self.fft_size
                        if len(valid_complex) < required:
                            padded = np.zeros(required, dtype=valid_complex.dtype)
                            padded[:len(valid_complex)] = valid_complex
                            valid_complex = padded
                            
                        batch = as_strided(
                            valid_complex,
                            shape=(batch_now, self.fft_size),
                            strides=(self.step_size * itemsize_c, itemsize_c),
                            writeable=False
                        )
                        
                        windowed  = batch * self.window
                        fft_out   = np.fft.fft(windowed, axis=1)
                        shifted   = np.fft.fftshift(fft_out, axes=1)
                        if self.freq_mask is not None:
                            shifted *= self.freq_mask  # broadcast across rows, zero-cost
                        mag       = np.abs(shifted)
                        mag       = np.maximum(mag, np.float32(1e-10))
                        db        = 20.0 * np.log10(mag)
                        spectrogram[row_idx:row_idx + batch_now] = db

                    row_idx += batch_now
                    if row_idx == self.num_rows or row_idx % max(1, self.num_rows // 20) == 0:
                        self.progress.emit(row_idx, self.num_rows)

            if self.running:
                self.finished_processing.emit(
                    spectrogram[:row_idx].T,  # (fft_size, num_rows)
                    self.t_start,
                    self.t_end
                )

        except Exception as e:
            print(f"[ViewportAwareReader] Error: {e}")

    def stop(self):
        self.running = False
        self.wait()

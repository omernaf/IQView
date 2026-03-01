import sys
import os
import argparse
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QProgressBar
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, Qt, QRectF
from numba import njit
import time

@njit(fastmath=True)
def preprocess_chunk(data_array, window, fft_size):
    """
    De-interleaves I and Q to complex numbers and applies window.
    """
    complex_data = np.empty(fft_size, dtype=np.complex64)
    for i in range(fft_size):
        complex_data[i] = data_array[2*i] + 1j * data_array[2*i+1]
        
    for i in range(fft_size):
        complex_data[i] = complex_data[i] * window[i]
        
    return complex_data

@njit(fastmath=True)
def postprocess_fft(fft_result, fft_size):
    """
    Applies fftshift and computes log magnitude in dB.
    """
    db_mag = np.empty(fft_size, dtype=np.float32)
    half_n = fft_size // 2
    epsilon = np.float32(1e-10)
    
    for i in range(fft_size):
        if i < half_n:
            shifted_idx = i + half_n
        else:
            shifted_idx = i - half_n
            
        val = np.abs(fft_result[shifted_idx])
        if val < epsilon:
            val = epsilon
        db_mag[i] = 20.0 * np.log10(val)
        
    return db_mag

class FileReaderThread(QThread):
    """
    Worker thread that reads the entire IQ file, processes it, and emits the static spectrogram.
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

class SpectrogramWindow(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.setWindowTitle("Antigravity Spectrogram Viewer - Static View")
        self.resize(1024, 768)
        
        self.fc = args.fc
        self.rate = args.rate
        self.fft_size = args.fft
        
        # UI Setup
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Interactive features instructions
        self.info_layout = QHBoxLayout()
        self.info_layout.setContentsMargins(10, 5, 10, 5)
        help_label = QLabel(
            "<b>Interactive Controls:</b> 'M' - Drop Frequency Marker | "
            "'B' - Toggle Bandwidth Selector | Drag - Pan | Scroll - Zoom"
        )
        self.info_layout.addWidget(help_label)
        self.layout.addLayout(self.info_layout)
        
        # Progress bar for parsing large files on launch
        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)
        
        # Setup an integrated GraphicsLayoutWidget to hold both the plot and the histogram easily side-by-side
        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.layout.addWidget(self.graphics_layout)
        
        # Setup pyqtgraph plot containing a ViewBox for native navigation
        self.plot_item = self.graphics_layout.addPlot(title="Static Full-File Spectrogram")
        self.plot_item.setLabel('bottom', "Time", units='s')
        self.plot_item.setLabel('left', "Frequency", units='Hz')
        
        # Disable drag/pan navigation to make the map strictly static
        self.plot_item.setMouseEnabled(x=False, y=False)
        self.plot_item.hideButtons() # Hide the auto-scale 'A' button
        
        # Setup ImageItem for static waterfall
        self.img = pg.ImageItem()
        self.plot_item.addItem(self.img)
        
        # Add the HistogramLUTItem side-panel natively inside the GraphicsLayout
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img)
        self.graphics_layout.addItem(self.hist)

        # Set the default colormap into the Histogram item, which will cascade to the ImageItem
        colormap = pg.colormap.get('plasma')
        self.hist.gradient.setColorMap(colormap)
        
        # Limit to 2 markers max
        self.markers = []
        
        # Bandwidth selector (now representing Time range if used across X, or Freq over Y)
        self.region = pg.LinearRegionItem()
        self.region.setZValue(10)
        self.region.hide()
        self.plot_item.addItem(self.region)
        self.region.sigRegionChanged.connect(self.update_region_text)
        
        self.region_text = pg.TextItem(text="", color='w', fill=(0, 0, 0, 150))
        self.region_text.hide()
        self.plot_item.addItem(self.region_text)
        
        # Connect to mouse click for marker placement
        self.plot_item.scene().sigMouseClicked.connect(self.mouse_clicked)
        
        # Start background processing thread
        self.worker = FileReaderThread(args.file, args.type, args.fft)
        
        # Pre-scale rect mapping (pixels to physical domains: Time on X, Freq on Y)
        # Note: self.spectrogram will be transposed in the thread emit
        self.time_duration = (self.worker.num_rows * self.fft_size) / self.rate
        # For X-Time, Y-Freq:
        # X origin: 0, Width: duration
        # Y origin: fc - rate/2, Height: rate
        self.img.setRect(QRectF(0, self.fc - self.rate/2, self.time_duration, self.rate))
        
        self.worker.progress.connect(self.update_progress)
        self.worker.finished_processing.connect(self.display_spectrogram)
        self.worker.start()

    def mouse_clicked(self, evt):
        # Only respond to Left Click and ensure we are clicking within the actual plot data area
        if evt.button() == Qt.MouseButton.LeftButton:
            pos = evt.scenePos()
            if self.plot_item.sceneBoundingRect().contains(pos):
                mouse_pos = self.plot_item.vb.mapSceneToView(pos)
                
                # Add a marker at the clicked X Time domain
                marker = pg.InfiniteLine(
                    pos=mouse_pos.x(), 
                    angle=90, 
                    movable=True, 
                    pen=pg.mkPen('r', width=2)
                )
                
                # Enforce the maximum two-marker rule by shifting the first placed marker out
                if len(self.markers) >= 2:
                    old_marker = self.markers.pop(0)
                    self.plot_item.removeItem(old_marker)
                    
                self.plot_item.addItem(marker)
                self.markers.append(marker)
                evt.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_B:
            self.toggle_bandwidth_region()
        else:
            super().keyPressEvent(event)

    def toggle_bandwidth_region(self):
        if self.region.isVisible():
            self.region.hide()
            self.region_text.hide()
        else:
            view_range = self.plot_item.viewRange()[0]
            v_center = (view_range[0] + view_range[1]) / 2
            v_span = (view_range[1] - view_range[0]) * 0.1
            self.region.setRegion([v_center - v_span/2, v_center + v_span/2])
            self.region.show()
            self.region_text.show()
            self.update_region_text()

    def update_region_text(self):
        minX, maxX = self.region.getRegion()
        dt = maxX - minX
        center = (maxX + minX) / 2
        
        dt_str = f"{dt*1e3:.2f} ms" if dt < 1 else f"{dt:.2f} s"
        center_str = f"{center:.3f} s"
        
        self.region_text.setText(f"Delta: {dt_str}\nTc: {center_str}")
        
        view_y_max = self.plot_item.viewRange()[1][1]
        self.region_text.setPos(minX, view_y_max * 0.8)

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(np.ndarray)
    def display_spectrogram(self, full_spectrogram):
        self.progress_bar.hide()
        # Find explicit levels since autolevels=False
        min_v = np.min(full_spectrogram)
        max_v = np.max(full_spectrogram)
        self.img.setImage(full_spectrogram, autoLevels=False, levels=[min_v, max_v], autoDownsample=True)

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()

def parse_args():
    parser = argparse.ArgumentParser(description="Antigravity - High-performance Static RF Spectrogram Viewer")
    parser.add_argument('-f', '--file', required=True, help='Path to the binary IQ file')
    parser.add_argument('-t', '--type', required=True, type=str, help='Data type (e.g., np.int16, np.float32, np.complex64)')
    parser.add_argument('-r', '--rate', type=float, default=1e6, help='Sample rate in Hz')
    parser.add_argument('-c', '--fc', type=float, default=0.0, help='Center frequency in Hz')
    parser.add_argument('-s', '--fft', type=int, default=1024, help='FFT bin size')
    return parser.parse_args()

def main():
    args = parse_args()
    
    dtype_map = {
        'np.int8': np.int8, 'np.int16': np.int16, 'np.int32': np.int32,
        'np.float32': np.float32, 'np.float64': np.float64,
        'int8': np.int8, 'int16': np.int16, 'int32': np.int32,
        'float32': np.float32, 'float64': np.float64,
        'np.complex64': np.complex64, 'complex64': np.complex64
    }
    
    if args.type not in dtype_map:
        print(f"Error: Unsupported data type {args.type}.")
        sys.exit(1)
        
    dtype = dtype_map[args.type]
    
    if dtype == np.complex64:
        dtype = np.float32
        
    args.type = dtype
    
    pg.setConfigOptions(useOpenGL=True, enableExperimental=True, imageAxisOrder='row-major')
    
    app = QApplication(sys.argv)
    window = SpectrogramWindow(args)
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

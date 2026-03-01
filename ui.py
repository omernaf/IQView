import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QProgressBar
from PyQt6.QtCore import pyqtSlot, Qt, QRectF
from utils import FileReaderThread

class CustomViewBox(pg.ViewBox):
    def __init__(self, ui_controller, *args, **kwds):
        super().__init__(*args, **kwds)
        self.ui_controller = ui_controller

    def mouseDragEvent(self, ev):
        if not hasattr(ev, 'isStart'):
            super().mouseDragEvent(ev)
            return
            
        if ev.button() == Qt.MouseButton.LeftButton:
            if ev.isStart():
                self.ui_controller.place_marker(ev.buttonDownScenePos(), drag_mode=True)
            elif ev.isFinish():
                self.ui_controller.active_drag_marker = None
            else:
                self.ui_controller.update_drag(ev.scenePos())
            ev.accept()
        else:
            super().mouseDragEvent(ev)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.ui_controller.place_marker(ev.scenePos(), drag_mode=False)
            ev.accept()
        else:
            super().mouseClickEvent(ev)

class SpectrogramWindow(QMainWindow):
    def __init__(self, file_path, data_type, sample_rate, center_freq, fft_size):
        super().__init__()
        self.setWindowTitle("Antigravity Spectrogram Viewer")
        self.resize(1024, 768)
        
        self.fc = center_freq
        self.rate = sample_rate
        self.fft_size = fft_size
        self.file_path = file_path
        self.data_type = data_type
        
        self.active_drag_marker = None
        self.markers = []
        
        self.setup_ui()
        self.start_processing()

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.info_layout = QHBoxLayout()
        self.info_layout.setContentsMargins(10, 5, 10, 5)
        help_label = QLabel(
            "<b>Interactive Controls:</b> Left Click/Drag - Place & Move Time Marker"
        )
        self.info_layout.addWidget(help_label)
        self.layout.addLayout(self.info_layout)
        
        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)
        
        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.layout.addWidget(self.graphics_layout)
        
        # Plot Item with Custom ViewBox
        self.view_box = CustomViewBox(ui_controller=self)
        self.plot_item = self.graphics_layout.addPlot(viewBox=self.view_box, title="Static Full-File Spectrogram")
        self.plot_item.setLabel('bottom', "Time", units='s')
        self.plot_item.setLabel('left', "Frequency", units='Hz')
        
        self.plot_item.setMouseEnabled(x=False, y=False)
        self.plot_item.hideButtons()
        
        self.img = pg.ImageItem()
        self.plot_item.addItem(self.img)
        
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img)
        self.graphics_layout.addItem(self.hist)

        colormap = pg.colormap.get('plasma')
        self.hist.gradient.setColorMap(colormap)
        
        # Disable the default viewbox menu so right-clicking purely opens the Colormap picker
        self.hist.vb.setMenuEnabled(False)
        
        # Override the Gradient editor menu to show native pyqtgraph top-level gradients with icons
        def custom_gradient_menu(ev):
            if ev.button() != Qt.MouseButton.RightButton:
                return
                
            from pyqtgraph.widgets.ColorMapMenu import ColorMapMenu
            from pyqtgraph.graphicsItems.GradientPresets import Gradients
            
            # Feed the legacy preset gradients into the native ColorMapMenu generator
            presets = [(name, 'preset-gradient') for name in Gradients.keys()]
            menu = ColorMapMenu(userList=presets, showColorMapSubMenus=False, showGradientSubMenu=False)
            menu.sigColorMapTriggered.connect(self.hist.gradient.setColorMap)
            
            menu.exec(ev.screenPos().toPoint())
            ev.accept()
            
        self.hist.gradient.mouseClickEvent = custom_gradient_menu
        

    def start_processing(self):
        self.worker = FileReaderThread(self.file_path, self.data_type, self.fft_size)
        
        self.time_duration = (self.worker.num_rows * self.fft_size) / self.rate
        self.img.setRect(QRectF(0, self.fc - self.rate/2, self.time_duration, self.rate))
        
        self.worker.progress.connect(self.update_progress)
        self.worker.finished_processing.connect(self.display_spectrogram)
        self.worker.start()

    def place_marker(self, scene_pos, drag_mode=False):
        if self.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_pos = self.plot_item.vb.mapSceneToView(scene_pos)
            
            # Remove old markers if we reach 2
            if len(self.markers) >= 2:
                old_marker = self.markers.pop(0)
                self.plot_item.removeItem(old_marker)
                
            marker = pg.InfiniteLine(
                pos=mouse_pos.x(), 
                angle=90, 
                movable=False, # We handle movement via CustomViewBox
                pen=pg.mkPen('r', width=2)
            )
            self.plot_item.addItem(marker, ignoreBounds=True)
            self.markers.append(marker)
            
            if drag_mode:
                self.active_drag_marker = marker

    def update_drag(self, scene_pos):
        if self.active_drag_marker and self.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_pos = self.plot_item.vb.mapSceneToView(scene_pos)
            self.active_drag_marker.setPos(mouse_pos.x())

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(np.ndarray)
    def display_spectrogram(self, full_spectrogram):
        self.progress_bar.hide()
        min_v = float(np.min(full_spectrogram))
        max_v = float(np.max(full_spectrogram))
        
        self.img.setImage(full_spectrogram, autoLevels=False, levels=[min_v, max_v], autoDownsample=True)
        
        # Lock histogram view entirely so it stays simple and static
        self.hist.vb.setMouseEnabled(x=False, y=False)
        self.hist.vb.disableAutoRange()
        self.hist.vb.setLimits(yMin=min_v, yMax=max_v)
        self.hist.setLevels(min_v, max_v)
        self.hist.region.setBounds([min_v, max_v])

    def closeEvent(self, event):
        if hasattr(self, 'worker'):
            self.worker.stop()
        event.accept()

import pyqtgraph as pg
import numpy as np
import copy
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QAction
from pyqtgraph.widgets.ColorMapMenu import ColorMapMenu
from pyqtgraph.graphicsItems.GradientPresets import Gradients

class SpectrogramView(pg.GraphicsLayoutWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        
        # Plot Item with Custom ViewBox
        from .widgets import CustomViewBox
        self.view_box = CustomViewBox(ui_controller=parent_window)
        self.plot_item = self.addPlot(viewBox=self.view_box, title="Static Full-File Spectrogram")
        self.plot_item.setLabel('bottom', "Time", units='s')
        self.plot_item.setLabel('left', "Frequency", units='Hz')
        
        self.plot_item.setMouseEnabled(x=False, y=False)
        self.plot_item.hideButtons()
        
        self.img = pg.ImageItem()
        self.plot_item.addItem(self.img)
        
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img)
        self.addItem(self.hist)

        colormap = pg.colormap.get('turbo')
        self.hist.gradient.setColorMap(colormap)
        self._current_cmap = colormap
        self._cmap_reversed = False
        
        self.hist.vb.setMenuEnabled(False)
        self.hist.gradient.mouseClickEvent = self.custom_gradient_menu

    def custom_gradient_menu(self, ev):
        if ev.button() != Qt.MouseButton.RightButton:
            return
            
        presets = [(name, 'preset-gradient') for name in Gradients.keys()]
        menu = ColorMapMenu(userList=presets, showColorMapSubMenus=False, showGradientSubMenu=False)
        
        for action in menu.actions():
            if action.text() == "None":
                menu.removeAction(action)
                break
                
        menu.addSeparator()
        reverse_act = QAction("Reverse Colormap", menu)
        reverse_act.setCheckable(True)
        reverse_act.setChecked(self._cmap_reversed)
        menu.addAction(reverse_act)

        def handle_cmap_triggered(cmap):
            self._current_cmap = cmap
            display_cmap = copy.deepcopy(cmap)
            if self._cmap_reversed:
                display_cmap.reverse()
            self.hist.gradient.setColorMap(display_cmap)
            
        def toggle_reverse(checked):
            self._cmap_reversed = checked
            if hasattr(self, '_current_cmap'):
                handle_cmap_triggered(self._current_cmap)
                
        reverse_act.toggled.connect(toggle_reverse)
        menu.sigColorMapTriggered.connect(handle_cmap_triggered)
        
        menu.exec(ev.screenPos().toPoint())
        ev.accept()
        
    def update_spectrogram(self, full_spectrogram, fc, rate, time_duration):
        min_v = float(np.min(full_spectrogram))
        max_v = float(np.max(full_spectrogram))
        
        self.img.setImage(full_spectrogram, autoLevels=False, levels=[min_v, max_v], autoDownsample=True)
        self.img.setRect(QRectF(0, fc - rate/2, time_duration, rate))
        
        self.plot_item.autoRange()
        
        self.hist.vb.setMouseEnabled(x=False, y=False)
        self.hist.vb.disableAutoRange()
        self.hist.vb.setLimits(yMin=min_v, yMax=max_v)
        self.hist.setLevels(min_v, max_v)
        self.hist.region.setBounds([min_v, max_v])

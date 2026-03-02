from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QWidget, QGridLayout, QScrollBar, QSizePolicy
from pyqtgraph.widgets.ColorMapMenu import ColorMapMenu
from pyqtgraph.graphicsItems.GradientPresets import Gradients
import pyqtgraph as pg
import numpy as np
import copy

class SpectrogramView(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        
        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(0, 0, 10, 0) # Added right padding to avoid clipping at the edge
        self.layout.setSpacing(0)
        self.setStyleSheet("background-color: #121212;")
        
        # Internal Graphics Layout for Plot
        self.glw_plot = pg.GraphicsLayoutWidget()
        self.glw_plot.setBackground('#121212')
        self.layout.addWidget(self.glw_plot, 0, 1)
        
        # Scrollbars
        self.x_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.y_scroll = QScrollBar(Qt.Orientation.Vertical)
        
        scrollbar_style = """
            QScrollBar:horizontal {
                background: #121212;
                height: 8px;
                margin: 0px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background: #3d3d3d;
                min-width: 40px;
                border_radius: 4px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #00aaff;
            }
            
            QScrollBar:vertical {
                background: #121212;
                width: 8px;
                margin: 0px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #3d3d3d;
                min-height: 40px;
                border_radius: 4px;
                margin: 0px;
            }
            QScrollBar::handle:vertical:hover {
                background: #00aaff;
            }
            
            QScrollBar::add-line, QScrollBar::sub-line {
                width: 0px; height: 0px;
            }
            QScrollBar::add-page, QScrollBar::sub-page {
                background: none;
            }
        """
        self.x_scroll.setStyleSheet(scrollbar_style)
        self.y_scroll.setStyleSheet(scrollbar_style)
        
        # Add scrollbars to grid
        self.layout.addWidget(self.y_scroll, 0, 0) # Left side
        self.layout.addWidget(self.x_scroll, 1, 1) # Under the plot
        
        # Internal Graphics Layout for Histogram
        self.glw_hist = pg.GraphicsLayoutWidget()
        self.glw_hist.setBackground('#121212')
        self.glw_hist.setFixedWidth(150) # Increased to 150 for extra buffer for colormap handles
        self.layout.addWidget(self.glw_hist, 0, 2)
        
        # Stretch factors
        self.layout.setColumnStretch(0, 0)
        self.layout.setColumnStretch(1, 1) # Plot takes remaining space
        self.layout.setColumnStretch(2, 0) # Fixed width for histogram
        
        # Initially hide or disable scrollbars if not zoomed
        self.x_scroll.hide()
        self.y_scroll.hide()

        # Plot Item with Custom ViewBox
        from .widgets import CustomViewBox
        self.view_box = CustomViewBox(ui_controller=parent_window)
        self.plot_item = self.glw_plot.addPlot(viewBox=self.view_box)
        
        # Modern Plot Styling
        self.plot_item.showGrid(x=True, y=True, alpha=0.1)
        self.plot_item.setLabel('bottom', "Time", units='s')
        self.plot_item.setLabel('left', "Frequency", units='Hz')
        
        self.plot_item.setMouseEnabled(x=False, y=False)
        self.plot_item.hideButtons()
        
        self.img = pg.ImageItem()
        self.plot_item.addItem(self.img)
        
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img)
        self.glw_hist.addItem(self.hist)

        self.hist.gradient.loadPreset('turbo')
        self._current_cmap = self.hist.gradient.colorMap()
        self._cmap_reversed = False
        
        self.hist.vb.setMenuEnabled(False)
        self.hist.gradient.mouseClickEvent = self.custom_gradient_menu

        # Synchronization State
        self._block_signals = False
        self.full_t_range = (0, 1)
        self.full_f_range = (0, 1)

        # Connect signals
        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

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

    def update_scrollbars(self):
        if self._block_signals: return
        self._block_signals = True
        
        xr, yr = self.view_box.viewRange()
        
        t_total = self.full_t_range[1] - self.full_t_range[0]
        if t_total > 0:
            visible_ratio_x = (xr[1] - xr[0]) / t_total
            if visible_ratio_x < 0.999:
                self.x_scroll.show()
                page_step = int(visible_ratio_x * 1000)
                self.x_scroll.setRange(0, 1000 - page_step)
                self.x_scroll.setPageStep(page_step)
                # Position
                pos = (xr[0] - self.full_t_range[0]) / t_total * 1000
                self.x_scroll.setValue(int(pos))
            else:
                self.x_scroll.hide()
        
        # Freq axis (Y)
        f_total = self.full_f_range[1] - self.full_f_range[0]
        if f_total > 0:
            visible_ratio_y = (yr[1] - yr[0]) / f_total
            if visible_ratio_y < 0.999:
                self.y_scroll.show()
                page_step = int(visible_ratio_y * 1000)
                self.y_scroll.setRange(0, 1000 - page_step)
                self.y_scroll.setPageStep(page_step)
                
                # Value 0 is TOP (f_max), Max is BOTTOM (f_min)
                pos_from_bottom = (yr[0] - self.full_f_range[0]) / f_total * 1000
                inv_pos = 1000 - page_step - int(pos_from_bottom)
                self.y_scroll.setValue(inv_pos)
            else:
                self.y_scroll.hide()
                
        self._block_signals = False

    def scroll_view(self):
        if self._block_signals: return
        self._block_signals = True
        
        val_x = self.x_scroll.value()
        val_y = self.y_scroll.value() # 0 is top
        
        t_total = self.full_t_range[1] - self.full_t_range[0]
        f_total = self.full_f_range[1] - self.full_f_range[0]
        xr, yr = self.view_box.viewRange()
        width = xr[1] - xr[0]
        height = yr[1] - yr[0]
        
        new_left = self.full_t_range[0] + (val_x / 1000.0) * t_total
        
        # Flip Y back: top of scrollbar is f_max - vr.height()
        inv_val_y = 1000 - self.y_scroll.pageStep() - val_y
        new_bottom = self.full_f_range[0] + (inv_val_y / 1000.0) * f_total
        
        if self.x_scroll.isVisible():
            self.plot_item.setXRange(new_left, new_left + width, padding=0)
        if self.y_scroll.isVisible():
            self.plot_item.setYRange(new_bottom, new_bottom + height, padding=0)
            
        self._block_signals = False
        
    def update_spectrogram(self, full_spectrogram, fc, rate, time_duration, auto_range=True):
        min_v = float(np.min(full_spectrogram))
        max_v = float(np.max(full_spectrogram))
        
        # Use existing levels if not auto-ranging to preserve contrast/brightness
        if not auto_range:
            levels = self.hist.getLevels()
        else:
            levels = [min_v, max_v]
        
        self.img.setImage(full_spectrogram, autoLevels=False, levels=levels, autoDownsample=True)
        self.img.setRect(QRectF(0, fc - rate/2, time_duration, rate))
        
        self.full_t_range = (0, time_duration)
        self.full_f_range = (fc - rate/2, fc + rate/2)
        
        if auto_range:
            self.plot_item.autoRange()
            self.hist.setLevels(min_v, max_v)
            self.hist.region.setBounds([min_v, max_v])
        
        self.hist.vb.setMouseEnabled(x=False, y=False)
        self.hist.vb.disableAutoRange()

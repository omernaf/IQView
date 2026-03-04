from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QWidget, QGridLayout, QScrollBar, QSizePolicy
from pyqtgraph.widgets.ColorMapMenu import ColorMapMenu
from pyqtgraph.graphicsItems.GradientPresets import Gradients
import pyqtgraph as pg
import numpy as np
import copy
from .themes import get_palette, get_scrollbar_stylesheet

class SpectrogramView(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        
        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # Internal Graphics Layout for Plot
        self.glw_plot = pg.GraphicsLayoutWidget()
        # Initial theme applied at end of __init__
        self.glw_plot.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.glw_plot, 0, 1)
        
        # Scrollbars
        self.x_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.y_scroll = QScrollBar(Qt.Orientation.Vertical)
        
        scrollbar_style = get_scrollbar_stylesheet(get_palette(self.parent_window.settings_mgr.get("ui/theme", "Dark")))
        self.x_scroll.setStyleSheet(scrollbar_style)
        self.y_scroll.setStyleSheet(scrollbar_style)
        
        # Add scrollbars to grid
        self.layout.addWidget(self.y_scroll, 0, 0) # Left side
        self.layout.addWidget(self.x_scroll, 1, 1) # Under the plot
        
        # Internal Graphics Layout for Histogram -> Now Spectrum Envelope
        self.glw_hist = pg.GraphicsLayoutWidget()
        # Background set in refresh_theme
        self.glw_hist.setFixedWidth(180) # Slightly wider for the new dual-control
        self.layout.addWidget(self.glw_hist, 0, 2)
        
        # 1. Spectrum Plot (Min/Max Envelope)
        self.spectrum_plot = self.glw_hist.addPlot(row=0, col=0)
        self.spectrum_plot.setLabel('left', '')
        self.spectrum_plot.setLabel('bottom', '')
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.1)
        self.spectrum_plot.setMenuEnabled(False)
        self.spectrum_plot.setMouseEnabled(x=False, y=False)
        self.spectrum_plot.getAxis('left').setStyle(showValues=False)
        self.spectrum_plot.getAxis('bottom').setStyle(showValues=False)
        self.spectrum_plot.getAxis('left').setWidth(10) # Reduce width since numbers are gone
        self.spectrum_plot.hideButtons()
        
        self.min_env_curve = pg.PlotDataItem(pen=pg.mkPen('#555', width=1)) # Noise Floor (Gray)
        self.max_env_curve = pg.PlotDataItem(pen=pg.mkPen('#00aaff', width=1.5)) # Signal Peaks (Blue)
        self.spectrum_plot.addItem(self.min_env_curve)
        self.spectrum_plot.addItem(self.max_env_curve)
        
        # 2. Level Region (Clipping Controls) - Now horizontal mapping Signal Level to Y
        self.level_region = pg.LinearRegionItem(orientation='horizontal', brush=pg.mkBrush(0, 170, 255, 30))
        # Style the lines to be dashed
        for line in self.level_region.lines:
            line.setPen(pg.mkPen('#fff', style=Qt.PenStyle.DashLine, width=1.5))
            line.setHoverPen(pg.mkPen('#00aaff', width=2))
        
        self.spectrum_plot.addItem(self.level_region)
        
        # 3. Gradient Editor (Vertical, aligned with Level axis)
        self.gradient = pg.GradientEditorItem(orientation='right')
        self.glw_hist.addItem(self.gradient, row=0, col=1)
        
        # Stretch factors for the GLW
        self.glw_hist.ci.layout.setColumnStretchFactor(0, 1)
        self.glw_hist.ci.layout.setColumnStretchFactor(1, 0)

        # Stretch factors for main layout
        self.layout.setColumnStretch(0, 0)
        self.layout.setColumnStretch(1, 1) # Plot takes remaining space
        self.layout.setColumnStretch(2, 0) # Fixed width for histogram area
        
        # Initially hide or disable scrollbars if not zoomed
        self.x_scroll.hide()
        self.y_scroll.hide()

        # Plot Item with Custom ViewBox
        from .widgets import CustomViewBox
        self.view_box = CustomViewBox(ui_controller=parent_window)
        self.plot_item = self.glw_plot.addPlot(viewBox=self.view_box)
        self.plot_item.setContentsMargins(0, 0, 0, 0)
        self.plot_item.getViewBox().setDefaultPadding(0)
        
        # Modern Plot Styling
        self.plot_item.showGrid(x=False, y=False)
        self.plot_item.setLabel('bottom', "Time", units='s')
        self.plot_item.setLabel('left', "Frequency", units='Hz')
        
        self.plot_item.setMouseEnabled(x=False, y=False)
        self.plot_item.hideButtons()
        
        self.img = pg.ImageItem()
        self.img.setZValue(-100) # Ensure image is always behind markers and grid
        self.plot_item.addItem(self.img)
        
        # Initialize Colormap
        self.apply_colormap(
            self.parent_window.settings_mgr.get("ui/colormap", "turbo"),
            bool(self.parent_window.settings_mgr.get("ui/colormap_reversed", False))
        )
        
        # Connections
        self.level_region.sigRegionChanged.connect(self.on_levels_changed)
        self.gradient.sigGradientChanged.connect(self.on_gradient_changed)
        self.gradient.mouseClickEvent = self.custom_gradient_menu

        # Synchronization State
        self._block_signals = False
        self.full_t_range = (0, 1)
        self.full_f_range = (0, 1)

        # Connect signals
        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

        self.refresh_theme()

    def on_levels_changed(self):
        low, high = self.level_region.getRegion()
        self.img.setLevels([low, high])

    def on_gradient_changed(self):
        # Simply apply the current state of the gradient editor to the image
        self.img.setColorMap(self.gradient.colorMap())

    def apply_colormap(self, cmap_name, reversed_mode):
        """Apply a named colormap to the gradient editor and image."""
        self._cmap_reversed = reversed_mode
        if not cmap_name:
            cmap_name = "turbo"
            
        try:
            self.gradient.loadPreset(cmap_name)
        except Exception:
            self.gradient.loadPreset("turbo")
            
        self._current_cmap = self.gradient.colorMap()
        
        display_cmap = copy.deepcopy(self._current_cmap)
        if self._cmap_reversed:
            display_cmap.reverse()
        self.gradient.setColorMap(display_cmap)
        self.img.setColorMap(display_cmap)

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
            self.gradient.setColorMap(display_cmap)
            
        def toggle_reverse(checked):
            self._cmap_reversed = checked
            if hasattr(self, '_current_cmap'):
                handle_cmap_triggered(self._current_cmap)
                
        reverse_act.toggled.connect(toggle_reverse)
        menu.sigColorMapTriggered.connect(handle_cmap_triggered)
        
        menu.exec(ev.screenPos().toPoint())
        ev.accept()

    def keyPressEvent(self, ev):
        if ev.isAutoRepeat(): return
        s = self.parent_window.settings_mgr
        key_name = QKeySequence(ev.key()).toString()
        if key_name == "Control": key_name = "Ctrl"
        
        time_seq = s.get('keybinds/time_markers', 'T')
        freq_seq = s.get('keybinds/mag_markers', 'F')
        zoom_seq = s.get('keybinds/zoom_mode', 'Ctrl')
        
        if key_name == time_seq:
            self.parent_window.set_interaction_mode('TIME')
        elif key_name == freq_seq:
            self.parent_window.set_interaction_mode('FREQ')
        elif key_name == zoom_seq:
            # Tell parent to enter zoom mode
            self.parent_window._prev_interaction_mode = getattr(self.parent_window, 'interaction_mode', 'TIME')
            self.parent_window.set_interaction_mode('ZOOM')
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.isAutoRepeat(): return
        s = self.parent_window.settings_mgr
        key_name = QKeySequence(ev.key()).toString()
        if key_name == "Control": key_name = "Ctrl"
        zoom_seq = s.get('keybinds/zoom_mode', 'Ctrl')

        if key_name == zoom_seq:
            prev = getattr(self.parent_window, '_prev_interaction_mode', 'TIME')
            self.parent_window.set_interaction_mode(prev)
        super().keyReleaseEvent(ev)

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
        
        # Current levels
        if not auto_range:
            levels = self.img.levels
        else:
            levels = [min_v, max_v]
            self.level_region.setRegion([min_v, max_v])
        
        self.img.setImage(full_spectrogram, autoLevels=False, levels=levels, autoDownsample=True)
        self.img.setRect(QRectF(0, fc - rate/2, time_duration, rate))
        
        self.full_t_range = (0, time_duration)
        self.full_f_range = (fc - rate/2, fc + rate/2)
        
        if auto_range:
            self.plot_item.autoRange()

        # full_spectrogram shape: (Freq, Time)
        # We want statistics across Time (axis 1)
        min_env = np.min(full_spectrogram, axis=1)
        max_env = np.max(full_spectrogram, axis=1)
        
        freqs = np.linspace(fc - rate/2, fc + rate/2, len(min_env))
        
        # Map Frequency to X and Level to Y
        self.min_env_curve.setData(freqs, min_env)
        self.max_env_curve.setData(freqs, max_env)
        
        # Explicitly sync X-axis with main plot's frequency range
        self.spectrum_plot.setXRange(fc - rate/2, fc + rate/2, padding=0)
        
        if auto_range:
            # Only auto-range the Y-axis (Signal Level)
            self.spectrum_plot.setYRange(min_v, max_v, padding=0.1)

    def refresh_theme(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        
        self.setStyleSheet(f"background-color: {p.bg_main};")
        self.glw_plot.setBackground(p.plot_bg)
        self.glw_hist.setBackground(p.plot_bg)
        
        # Update colormap from settings
        self.apply_colormap(
            self.parent_window.settings_mgr.get("ui/colormap", "turbo"),
            bool(self.parent_window.settings_mgr.get("ui/colormap_reversed", False))
        )
        
        # Update spectrum plot lines
        if hasattr(self, 'min_env_curve'):
            self.min_env_curve.setPen(pg.mkPen(p.text_dim, width=1))
            self.max_env_curve.setPen(pg.mkPen(p.accent, width=1.5))
            
            # Update level region
            for line in self.level_region.lines:
                line.setPen(pg.mkPen(p.text_header, style=Qt.PenStyle.DashLine, width=1.5))
                line.setHoverPen(pg.mkPen(p.accent, width=2))
            
            # Update spectrum plot grid and axes
            self.spectrum_plot.getAxis('left').setPen(p.text_dim)
            self.spectrum_plot.getAxis('bottom').setPen(p.text_dim)
            
            # Update main plot axes
            self.plot_item.getAxis('left').setPen(p.text_dim)
            self.plot_item.getAxis('bottom').setPen(p.text_dim)
            
        # Update scrollbars
        sb_style = get_scrollbar_stylesheet(p)
        self.x_scroll.setStyleSheet(sb_style)
        self.y_scroll.setStyleSheet(sb_style)

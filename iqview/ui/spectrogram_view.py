from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QImage, QPainter
from PyQt6.QtWidgets import QWidget, QGridLayout, QScrollBar, QSizePolicy
from pyqtgraph.widgets.ColorMapMenu import ColorMapMenu
from pyqtgraph.graphicsItems.GradientPresets import Gradients
import pyqtgraph as pg
from PyQt6 import QtGui
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
        self.glw_plot.setMouseTracking(True)
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

        # Cache of the last raw spectrogram data so we can re-render on orientation change
        self._last_spectrogram = None
        self._last_fc = None
        self._last_rate = None
        self._last_t_start = None  # for lazy tiles
        self._last_t_end = None    # for lazy tiles
        self._last_auto_range = False

        # Connect signals
        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.view_box.sigRangeChanged.connect(lambda: self.parent_window.update_grid('TIME'))
        self.view_box.sigRangeChanged.connect(lambda: self.parent_window.update_grid('FREQ'))
        self.view_box.sigRangeChanged.connect(self._on_range_changed_lazy)
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

        self.refresh_theme()

    # ---- Waterfall helpers ----

    @property
    def is_waterfall(self):
        """True when waterfall mode is enabled (Freq→X, Time→Y)."""
        return bool(self.parent_window.settings_mgr.get("ui/waterfall", False))

    def _axis_labels_for_mode(self):
        """Return (bottom_label, left_label) appropriate for current mode."""
        if self.is_waterfall:
            return ("Frequency", "Hz"), ("Time", "s")
        else:
            return ("Time", "s"), ("Frequency", "Hz")

    def _apply_axis_labels(self):
        (bl, bu), (ll, lu) = self._axis_labels_for_mode()
        self.plot_item.setLabel('bottom', bl, units=bu)
        self.plot_item.setLabel('left', ll, units=lu)

    def apply_waterfall_mode(self):
        """Re-render the current cached image in the new orientation and update all
        axis labels, scrollbars, and the spectrum envelope sync.
        Called from on_settings_applied() after the user changes the waterfall checkbox."""
        self._apply_axis_labels()

        # In waterfall mode time is on the Y axis; invert it so t=0 is at the top
        # (newest data scrolls down, matching the conventional waterfall direction).
        self.view_box.invertY(self.is_waterfall)

        # Re-render using cached data if available
        if self._last_spectrogram is not None and self._last_fc is not None:
            if self._last_t_start is not None:
                # lazy tile path
                self.update_lazy_tile(
                    self._last_spectrogram,
                    self._last_fc,
                    self._last_rate,
                    self._last_t_start,
                    self._last_t_end,
                    auto_range=True,
                )
            else:
                # full spectrogram path
                self.update_spectrogram(
                    self._last_spectrogram,
                    self._last_fc,
                    self._last_rate,
                    self.full_t_range[1],
                    auto_range=True,
                )
        self.update_scrollbars()
        # Update angles of any already-placed markers
        if hasattr(self.parent_window, 'refresh_spectrogram_markers'):
            self.parent_window.refresh_spectrogram_markers()
        # Update marker button icons/tooltips in the panel
        if hasattr(self.parent_window, 'marker_panel'):
            self.parent_window.marker_panel.refresh_waterfall_ui()

    # ---- Level / Gradient ----

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
            
        if ColorMapMenu is None:
            print("Warning: pyqtgraph.widgets.ColorMapMenu not found. Please upgrade pyqtgraph to >= 0.13.0")
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
        from PyQt6.QtWidgets import QApplication, QLineEdit
        if isinstance(QApplication.focusWidget(), QLineEdit):
            super().keyPressEvent(ev)
            return
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
        from PyQt6.QtWidgets import QApplication, QLineEdit
        if isinstance(QApplication.focusWidget(), QLineEdit):
            super().keyReleaseEvent(ev)
            return
        s = self.parent_window.settings_mgr
        key_name = QKeySequence(ev.key()).toString()
        if key_name == "Control": key_name = "Ctrl"
        zoom_seq = s.get('keybinds/zoom_mode', 'Ctrl')

        if key_name == zoom_seq:
            prev = getattr(self.parent_window, '_prev_interaction_mode', 'TIME')
            self.parent_window.set_interaction_mode(prev)
        super().keyReleaseEvent(ev)

    # ---- Lazy render helpers ----

    def _on_range_changed_lazy(self):
        """Forward viewport changes to the data handler for lazy re-rendering."""
        if hasattr(self.parent_window, 'on_viewport_changed'):
            self.parent_window.on_viewport_changed()

    def get_pixel_width(self):
        """Return the current plot pixel size along the *time* axis (integer).

        In standard mode (X=time) this is the ViewBox width in pixels.
        In waterfall mode (Y=time) this is the ViewBox height in pixels.
        Used by ViewportAwareReader to compute how many FFT rows are needed.
        """
        try:
            rect = self.view_box.screenGeometry()
            if rect:
                if self.is_waterfall:
                    dim = rect.height()
                else:
                    dim = rect.width()
                if dim > 0:
                    return int(dim)
        except Exception:
            pass
        # Fallback
        if self.is_waterfall:
            return max(1, self.glw_plot.height())
        return max(1, self.glw_plot.width())

    # ---- Image display helpers ----

    def _compute_auto_levels(self, spectrogram):
        """Compute sensible (min_v, max_v) from spectrogram data."""
        valid_data = spectrogram[spectrogram > -190.0]
        if len(valid_data) > 0:
            max_v = float(np.max(valid_data))
            p5 = float(np.percentile(valid_data, 5))
            if max_v - p5 < 20.0:
                min_v = max_v - 80.0
            else:
                min_v = p5
            min_v = max(min_v, max_v - 120.0)
        else:
            max_v = 0.0
            min_v = -100.0
        return min_v, max_v

    def _set_image_and_rect(self, spectrogram, fc, rate, t_start, t_end, levels):
        """Place the image on the plot in either standard or waterfall orientation.

        spectrogram shape is always (N_freq, N_time).
        Standard  → image as-is,   rect = (t_start, f_min, duration, bandwidth)
        Waterfall → transposed,     rect = (f_min, t_start, bandwidth, duration)
        """
        f_min = fc - rate / 2
        duration = t_end - t_start

        if self.is_waterfall:
            # Transpose: rows become columns; the image will be (N_time, N_freq)
            display_data = np.ascontiguousarray(spectrogram.T)
            self.img.setImage(display_data, autoLevels=False, levels=levels,
                              autoDownsample=True)
            # rect: (x_left, y_bottom, width_x, height_y) = (f_min, t_start, bw, duration)
            self.img.setRect(QRectF(f_min, t_start, rate, duration))
        else:
            self.img.setImage(spectrogram, autoLevels=False, levels=levels,
                              autoDownsample=True)
            self.img.setRect(QRectF(t_start, f_min, duration, rate))

    def _update_spectrum_envelope(self, spectrogram, fc, rate, min_v, max_v, auto_range):
        """Refresh the right-side spectrum envelope panel.

        The envelope always shows Frequency on its X axis and dB on its Y axis,
        regardless of the main plot orientation.
        """
        # full_spectrogram shape: (Freq, Time) — statistics across Time (axis 1)
        min_env = np.min(spectrogram, axis=1)
        max_env = np.max(spectrogram, axis=1)
        freqs = np.linspace(fc - rate / 2, fc + rate / 2, len(min_env))

        self.min_env_curve.setData(freqs, min_env)
        self.max_env_curve.setData(freqs, max_env)
        self.spectrum_plot.setXRange(fc - rate / 2, fc + rate / 2, padding=0)

        if auto_range:
            pad = (max_v - min_v) * 0.1
            self.spectrum_plot.setYRange(min_v, max_v, padding=0.1)
            self.level_region.setBounds([min_v - pad, max_v + pad])

    # ---- Public update methods ----

    def update_lazy_tile(self, spectrogram, fc, rate, t_start, t_end,
                         auto_range=False):
        """
        Like update_spectrogram() but positions the image at [t_start, t_end]
        instead of always starting at 0.  Used by the lazy renderer.
        """
        duration = t_end - t_start
        if duration <= 0:
            return

        min_v, max_v = self._compute_auto_levels(spectrogram)

        if not auto_range:
            levels = self.img.levels if self.img.levels is not None else [min_v, max_v]
        else:
            levels = [min_v, max_v]
            self.level_region.setRegion([min_v, max_v])

        # Cache for orientation re-renders
        self._last_spectrogram = spectrogram
        self._last_fc = fc
        self._last_rate = rate
        self._last_t_start = t_start
        self._last_t_end = t_end

        self._set_image_and_rect(spectrogram, fc, rate, t_start, t_end, levels)

        if auto_range:
            # Use the full file extent set by display_lazy_tile before calling us
            t0, t1 = self.full_t_range
            f0, f1 = self.full_f_range
            if t1 > t0 and f1 > f0:
                if self.is_waterfall:
                    self.plot_item.setXRange(f0, f1, padding=0)
                    self.plot_item.setYRange(t0, t1, padding=0)
                else:
                    self.plot_item.setXRange(t0, t1, padding=0)
                    self.plot_item.setYRange(f0, f1, padding=0)
            else:
                self.plot_item.autoRange()

        self._update_spectrum_envelope(spectrogram, fc, rate, min_v, max_v, auto_range)

    def update_spectrogram(self, full_spectrogram, fc, rate, t_start, t_end, auto_range=True):
        min_v, max_v = self._compute_auto_levels(full_spectrogram)
        
        # Current levels
        if not auto_range:
            levels = self.img.levels
        else:
            levels = [min_v, max_v]
            self.level_region.setRegion([min_v, max_v])

        # Cache for orientation re-renders
        self._last_spectrogram = full_spectrogram
        self._last_fc = fc
        self._last_rate = rate
        self._last_t_start = t_start
        self._last_t_end = t_end

        self._set_image_and_rect(full_spectrogram, fc, rate, t_start, t_end, levels)
        
        self.full_t_range = (0.0, t_end)
        self.full_f_range = (fc - rate/2, fc + rate/2)
        
        if auto_range:
            self.plot_item.autoRange()

        self._update_spectrum_envelope(full_spectrogram, fc, rate, min_v, max_v, auto_range)

    # ---- Scrollbars ----

    def update_scrollbars(self):
        if self._block_signals: return
        self._block_signals = True
        
        xr, yr = self.view_box.viewRange()
        waterfall = self.is_waterfall

        # In waterfall mode: X = freq, Y = time
        # In standard mode:  X = time, Y = freq
        if waterfall:
            t_visible_range = yr   # time is on Y
            f_visible_range = xr   # freq is on X
        else:
            t_visible_range = xr   # time is on X
            f_visible_range = yr   # freq is on Y

        t_total = self.full_t_range[1] - self.full_t_range[0]
        if t_total > 0:
            visible_ratio_t = (t_visible_range[1] - t_visible_range[0]) / t_total
            if visible_ratio_t < 0.999:
                self.x_scroll.show() if not waterfall else self.y_scroll.show()
                page_step = int(visible_ratio_t * 1000)
                scroll = self.x_scroll if not waterfall else self.y_scroll
                scroll.setRange(0, 1000 - page_step)
                scroll.setPageStep(page_step)
                pos = (t_visible_range[0] - self.full_t_range[0]) / t_total * 1000
                if waterfall:
                    # Y axis is inverted in waterfall: scrollbar 0 = top = t_min
                    scroll.setValue(int(pos))
                else:
                    scroll.setValue(int(pos))
            else:
                if waterfall:
                    self.y_scroll.hide()
                else:
                    self.x_scroll.hide()

        f_total = self.full_f_range[1] - self.full_f_range[0]
        if f_total > 0:
            visible_ratio_f = (f_visible_range[1] - f_visible_range[0]) / f_total
            if visible_ratio_f < 0.999:
                scroll = self.y_scroll if not waterfall else self.x_scroll
                scroll.show()
                page_step = int(visible_ratio_f * 1000)
                scroll.setRange(0, 1000 - page_step)
                scroll.setPageStep(page_step)

                if not waterfall:
                    # Standard: Y scroll, 0 = top = f_max (inverted)
                    pos_from_bottom = (f_visible_range[0] - self.full_f_range[0]) / f_total * 1000
                    inv_pos = 1000 - page_step - int(pos_from_bottom)
                    scroll.setValue(inv_pos)
                else:
                    # Waterfall: X scroll tracks freq which is on X
                    pos = (f_visible_range[0] - self.full_f_range[0]) / f_total * 1000
                    scroll.setValue(int(pos))
            else:
                if waterfall:
                    self.x_scroll.hide()
                else:
                    self.y_scroll.hide()
                    
        self._block_signals = False

    def scroll_view(self):
        if self._block_signals: return
        self._block_signals = True
        
        waterfall = self.is_waterfall
        xr, yr = self.view_box.viewRange()

        if waterfall:
            # X = freq (x_scroll), Y = time (y_scroll)
            # Y axis is inverted so scrollbar 0 = top = t_min
            val_f = self.x_scroll.value()
            val_t = self.y_scroll.value()

            f_total = self.full_f_range[1] - self.full_f_range[0]
            t_total = self.full_t_range[1] - self.full_t_range[0]
            f_width = xr[1] - xr[0]
            t_height = yr[1] - yr[0]

            new_f_left = self.full_f_range[0] + (val_f / 1000.0) * f_total
            new_t_bottom = self.full_t_range[0] + (val_t / 1000.0) * t_total

            if self.x_scroll.isVisible():
                self.plot_item.setXRange(new_f_left, new_f_left + f_width, padding=0)
            if self.y_scroll.isVisible():
                self.plot_item.setYRange(new_t_bottom, new_t_bottom + t_height, padding=0)
        else:
            # X = time (x_scroll), Y = freq (y_scroll, inverted)
            val_x = self.x_scroll.value()
            val_y = self.y_scroll.value()  # 0 = top

            t_total = self.full_t_range[1] - self.full_t_range[0]
            f_total = self.full_f_range[1] - self.full_f_range[0]
            width = xr[1] - xr[0]
            height = yr[1] - yr[0]

            new_left = self.full_t_range[0] + (val_x / 1000.0) * t_total

            inv_val_y = 1000 - self.y_scroll.pageStep() - val_y
            new_bottom = self.full_f_range[0] + (inv_val_y / 1000.0) * f_total

            if self.x_scroll.isVisible():
                self.plot_item.setXRange(new_left, new_left + width, padding=0)
            if self.y_scroll.isVisible():
                self.plot_item.setYRange(new_bottom, new_bottom + height, padding=0)
            
        self._block_signals = False
        
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
        
        # Axis labels and orientation
        self._apply_axis_labels()
        # Ensure Y-axis inversion matches the current mode (important on startup)
        self.view_box.invertY(self.is_waterfall)
        
        # Update spectrum plot lines
        if hasattr(self, 'min_env_curve'):
            self.min_env_curve.setPen(pg.mkPen(p.text_dim, width=1))
            self.max_env_curve.setPen(pg.mkPen(p.accent, width=1.5))
            
            # Update level region
            for line in self.level_region.lines:
                line.setPen(pg.mkPen(p.text_header, style=Qt.PenStyle.DashLine, width=1.5))
                line.setHoverPen(pg.mkPen(p.accent, width=2))
            
            # Update spectrum plot grid and axes
            from PyQt6.QtGui import QFont
            font = QFont()
            font.setPointSize(int(self.parent_window.settings_mgr.get("ui/axis_font_size", 10)))
            
            grid_enabled = bool(self.parent_window.settings_mgr.get("ui/grid_enabled", True))
            grid_alpha = int(self.parent_window.settings_mgr.get("ui/grid_alpha", 30)) / 100.0
            
            self.spectrum_plot.getAxis('left').setTickFont(font)
            self.spectrum_plot.getAxis('bottom').setTickFont(font)
            self.spectrum_plot.showGrid(x=grid_enabled, y=grid_enabled, alpha=grid_alpha)
            
            self.spectrum_plot.getAxis('left').setPen(p.text_dim)
            self.spectrum_plot.getAxis('bottom').setPen(p.text_dim)
            
            # Update main plot axes
            self.plot_item.getAxis('left').setTickFont(font)
            self.plot_item.getAxis('bottom').setTickFont(font)
            self.plot_item.showGrid(x=grid_enabled, y=grid_enabled, alpha=grid_alpha)
            
            self.plot_item.getAxis('left').setPen(p.text_dim)
            self.plot_item.getAxis('bottom').setPen(p.text_dim)
            
        # Update scrollbars
        sb_style = get_scrollbar_stylesheet(p)
        self.x_scroll.setStyleSheet(sb_style)
        sb_style = get_scrollbar_stylesheet(p)
        self.y_scroll.setStyleSheet(sb_style)

    def capture_raw_image(self):
        """Captures only the spectrogram image data as a QImage, scaled to preserve visual aspect ratio."""
        pix = self.img.getPixmap()
        if pix.isNull():
            return QtGui.QImage()
            
        raw_img = pix.toImage()
        
        # Get the visual size of the ViewBox (the actual screen area)
        # This determines the aspect ratio the user sees.
        view_size = self.view_box.size()
        
        # Rescale the raw image to match the visual proportions
        return raw_img.scaled(
            int(view_size.width()), 
            int(view_size.height()), 
            Qt.AspectRatioMode.IgnoreAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )

    def capture_plot_with_axes(self):
        """Captures the entire plot area including axes and markers."""
        # QWidget.grab() returns a blank image for OpenGL-backed GraphicsLayoutWidgets.
        # Use pyqtgraph's ImageExporter which renders via the scene painter instead.
        from pyqtgraph.exporters import ImageExporter
        exporter = ImageExporter(self.glw_plot.scene())
        # export() with no filename returns a QImage directly
        return exporter.export(toBytes=True)

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout,
                             QComboBox)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QKeySequence
from ..widgets import CustomViewBox
from .marker_panel import FrequencyDomainMarkerPanel
from ..themes import get_palette, get_scrollbar_stylesheet
from ...dsp.dsp import compute_psd

class FrequencyDomainView(QWidget):
    """
    A detailed view of a signal segment in the frequency domain with interactive markers.
    """
    def __init__(self, samples, center_freq, sample_rate, parent=None, parent_window=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.samples = samples # Complex numpy array
        self.center_freq = center_freq
        self.rate = sample_rate
        self.parent_window = parent_window
        self.settings_mgr = parent_window.settings_mgr if parent_window else None
        
        self.is_spectrogram = False
        self.interaction_mode = 'FREQ'
        self.zoom_mode = False
        self.active_drag_marker = None
        self.markers_freq = []
        self._block_signals = False
        self._marker_age = {}
        self._marker_age_counter = 0
        self.active_drag_stats_bound_idx = -1
        
        # Endless Markers
        self.markers_freq_endless = []
        self._first_plot = True
        self.last_move_scene_pos = None
        
        # Mode-specific Magnitude markers
        self.markers_y_dict = {
            "magnitude": [], "magnitude [dB]": [], 
            "magnitude^2": [],
            "real": [], "real [dB]": [], 
            "imag": [], "imag [dB]": [],
            "phase": [], "unwrapped phase": []
        }
        self.markers_y_endless_dict = {k: [] for k in self.markers_y_dict.keys()}
        self.zoom_y_dict = {}
        
        # Grid variables
        self.grid_freq_enabled = False
        self.grid_freq_tracking = True
        self.grid_lines_freq = []
        self.grid_mag_enabled = False
        self.grid_mag_tracking = True
        self.grid_lines_mag = []

        self.zoom_history = []
        
        # Spectral Settings
        # Removed spectral_mode toggle per user request
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(5)
        
        # --- Marker Panel ---
        self.marker_panel = FrequencyDomainMarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.main_layout.addWidget(self.marker_panel)
        
        # --- Toolbar ---
        self.toolbar = QFrame()
        self.toolbar.setObjectName("fd_toolbar")
        self.update_toolbar_style()
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.toolbar_layout.addWidget(QLabel("Plot Mode:"))
        self.plot_buttons_layout = QHBoxLayout()
        self.plot_buttons_layout.setSpacing(5)
        self.toolbar_layout.addLayout(self.plot_buttons_layout)
        
        self.mode_group = QButtonGroup(self)
        self.plot_buttons = []
        
        self.toolbar_layout.addStretch()
        
        range_label = QLabel(f"Samples: {len(samples)}")
        range_label.setStyleSheet("color: #888; font-family: Consolas; font-size: 11px;")
        self.toolbar_layout.addWidget(range_label)
        
        self.main_layout.addWidget(self.toolbar)
        
        # --- Plot & Scrollbars ---
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)
        
        self.view_box = CustomViewBox(self)
        self.plot_widget = pg.PlotWidget(viewBox=self.view_box)
        self.plot_item = self.plot_widget.getPlotItem()
        self.refresh_plot_style()
        self.plot_widget.getAxis('bottom').setLabel('Frequency', units='Hz')
        
        self.grid_layout.addWidget(self.plot_widget, 0, 1)

        self.x_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.y_scroll = QScrollBar(Qt.Orientation.Vertical)
        
        scrollbar_style = get_scrollbar_stylesheet(get_palette(self.settings_mgr.get("ui/theme", "Dark")))
        self.x_scroll.setStyleSheet(scrollbar_style)
        self.y_scroll.setStyleSheet(scrollbar_style)
        
        self.grid_layout.addWidget(self.y_scroll, 0, 0)
        self.grid_layout.addWidget(self.x_scroll, 1, 1)
        self.x_scroll.hide()
        self.y_scroll.hide()
        
        self.main_layout.addWidget(self.grid_container)
        
        # --- Stats Region ---
        self.stats_bounds = []
        self.stats_marker_order = []
        self.stats_line = None
        self.stats_region = pg.LinearRegionItem(orientation='vertical')
        self.stats_region.setZValue(9)
        self.stats_region.hide()
        self.plot_item.addItem(self.stats_region)
        self.stats_region.sigRegionChanged.connect(self.update_statistics)
        
        self.stats_markers = pg.ScatterPlotItem(size=10, pen=pg.mkPen(None), brush=pg.mkBrush(255, 0, 0, 200))
        self.stats_markers.setZValue(10)
        self.stats_markers.hide()
        self.plot_item.addItem(self.stats_markers)
        
        # --- Process Data ---
        self.compute_fft()
        
        self.available_modes = {
            "magnitude": self.plot_magnitude,
            "magnitude [dB]": self.plot_magnitude_db,
            "magnitude^2": self.plot_magnitude_squared,
            "power spectrum density (PSD)": self.plot_psd,
            "real": self.plot_real,
            "real [dB]": self.plot_real_db,
            "imag": self.plot_imag,
            "imag [dB]": self.plot_imag_db,
            "phase": self.plot_phase,
            "unwrapped phase": self.plot_unwrapped_phase
        }
        
        self.rebuild_plot_buttons()
        self.set_interaction_mode('FREQ')

        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

    def compute_fft(self):
        """Perform FFT processing on the sample segment using signal length N."""
        n = len(self.samples)
        if n == 0: return

        # Rectangular window (no window at all)
        window = np.ones(n)

        fft_res = np.fft.fft(self.samples * window) / n
        self.fft_data = np.fft.fftshift(fft_res)

        self.fft_freq_axis = np.fft.fftshift(np.fft.fftfreq(n, 1/self.rate)) + self.center_freq
        self.freq_axis = self.fft_freq_axis
        self.current_plot_data = np.nan_to_num(np.abs(self.fft_data), nan=0.0, posinf=1e-15, neginf=0.0)
        self.y_label_text = "magnitude"


    def rebuild_plot_buttons(self):
        for btn in self.plot_buttons:
            self.mode_group.removeButton(btn)
            self.plot_buttons_layout.removeWidget(btn)
            btn.deleteLater()
        self.plot_buttons.clear()
        
        active_plots = []
        if self.settings_mgr:
            active_plots = self.settings_mgr.get("core/frequency_plots", [])
            
        if not active_plots:
            active_plots = ["magnitude", "magnitude [dB]"]
            
        for i, name in enumerate(active_plots):
            if name in self.available_modes:
                btn = QPushButton(name)
                btn.setCheckable(True)
                self.mode_group.addButton(btn, i)
                self.plot_buttons_layout.addWidget(btn)
                btn.clicked.connect(self.available_modes[name])
                self.plot_buttons.append(btn)
                if name == "magnitude": btn.setChecked(True)
        
        if self.plot_buttons and not any(b.isChecked() for b in self.plot_buttons):
            self.plot_buttons[0].setChecked(True)
            self.available_modes[self.plot_buttons[0].text()]()
        elif any(b.isChecked() for b in self.plot_buttons):
            checked_btn = next(b for b in self.plot_buttons if b.isChecked())
            self.available_modes[checked_btn.text()]()

    def set_interaction_mode(self, mode):
        if mode == 'Y': mode = 'MAG'
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
        
        if mode == 'STATS':
            if len(self.stats_bounds) == 2:
                self.stats_region.show()
                self.stats_markers.show()
                if self.stats_line: self.stats_line.hide()
                self.update_statistics()
            elif len(self.stats_bounds) == 1:
                if self.stats_line: self.stats_line.show()
                self.stats_region.hide()
                self.stats_markers.hide()
        else:
            self.stats_region.hide()
            self.stats_markers.hide()
            if self.stats_line: self.stats_line.hide()
            
        self.refresh_cursor()
        
        self.marker_panel.update_mode_ui(mode)
        self.marker_panel.update_headers(mode, self.y_label_text)
        self.update_marker_info()

    def refresh_cursor(self):
        mode = self.interaction_mode
        cursor = Qt.CursorShape.ArrowCursor
        if mode == 'ZOOM': cursor = Qt.CursorShape.CrossCursor
        elif mode == 'MOVE': cursor = Qt.CursorShape.SizeAllCursor
        elif 'ENDLESS' in mode: cursor = Qt.CursorShape.PointingHandCursor
        elif mode in ['FREQ', 'MAG', 'Y', 'FILTER', 'STATS']: cursor = Qt.CursorShape.CrossCursor
        self.plot_widget.setCursor(cursor)

    def undo_zoom(self):
        if self.zoom_history:
            prev_rect = self.zoom_history.pop()
            self.plot_item.setRange(rect=prev_rect, padding=0)

    def reset_zoom(self):
        self.zoom_history.append(self.plot_item.viewRect())
        self.plot_item.autoRange()

    def handle_zoom_rectangle(self, rect, zoom_type='BOTH'):
        self.zoom_history.append(self.plot_item.viewRect())
        if rect.width() <= 0 and zoom_type != 'Y_ONLY': return
        if rect.height() <= 0 and zoom_type != 'X_ONLY': return
        if zoom_type == 'Y_ONLY': self.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
        elif zoom_type == 'X_ONLY': self.plot_item.setXRange(rect.left(), rect.right(), padding=0)
        else: self.plot_item.setRange(rect, padding=0)

    def fit_to_markers(self):
        is_freq = (self.interaction_mode in ['FREQ', 'FREQ_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        if is_endless:
            active_markers = self.markers_freq_endless if is_freq else [] # Y markers not implemented for fit yet
        else:
            active_markers = self.markers_freq if is_freq else []
            
        if not active_markers and self.interaction_mode in ['MAG', 'Y', 'MAG_ENDLESS']:
            label = self.y_label_text
            if is_endless: active_markers = self.markers_y_endless_dict.get(label, [])
            else: active_markers = self.markers_y_dict.get(label, [])

        if len(active_markers) == 2:
            self.zoom_history.append(self.plot_item.viewRect())
            v1, v2 = active_markers[0].value(), active_markers[1].value()
            v_min, v_max = min(v1, v2), max(v1, v2)
            if is_freq: self.plot_item.setXRange(v_min, v_max, padding=0)
            else: self.plot_item.setYRange(v_min, v_max, padding=0)

    def plot_magnitude(self): self._update_plot(np.abs(self.fft_data), "magnitude")
    def plot_magnitude_db(self):
        data = np.abs(self.fft_data)
        data[data < 1e-15] = 1e-15
        self._update_plot(20 * np.log10(data), "magnitude [dB]")
    def plot_magnitude_squared(self): self._update_plot(np.abs(self.fft_data)**2, "magnitude^2")
    def plot_real(self): self._update_plot(self.fft_data.real, "real")
    def plot_real_db(self):
        data = np.abs(self.fft_data.real)
        data[data < 1e-15] = 1e-15
        self._update_plot(20 * np.log10(data), "real [dB]")
    def plot_imag(self): self._update_plot(self.fft_data.imag, "imag")
    def plot_imag_db(self):
        data = np.abs(self.fft_data.imag)
        data[data < 1e-15] = 1e-15
        self._update_plot(20 * np.log10(data), "imag [dB]")
    def plot_phase(self): self._update_plot(np.angle(self.fft_data), "phase")
    def plot_unwrapped_phase(self): self._update_plot(np.unwrap(np.angle(self.fft_data)), "unwrapped phase")

    def plot_psd(self):
        method = "Welch"
        if self.settings_mgr:
            method = self.settings_mgr.get("core/psd_algorithm", "Welch")
        
        # Use a reasonable segment length for Welch based on samples
        # Default to 4096 or segments of ~1/4 size
        nperseg = 4096 if len(self.samples) > 4096 else 1024
        
        # Fix: Use fs=1.0 to get normalized density (independent of actual sample rate)
        freqs, psd = compute_psd(self.samples, fs=1.0, method=method, nperseg=nperseg)
        # Scale frequencies only for display
        freqs = freqs * self.rate + self.center_freq
        
        # PSD is usually viewed in dB/Hz
        # Reference level: 1.0 (density)
        psd_db = 10 * np.log10(psd + 1e-20)
        
        # We need to ensure freqs match self.freq_axis for markers if they are tied to indices
        # but compute_psd might return a different number of points (e.g. nperseg for Welch)
        # So we update current_plot_data and ALSO freq_axis if needed, 
        # but that might break existing markers that rely on length.
        # However, the user wants to VIEW it, so we should update the plot correctly.
        
        self._update_plot_dynamic(freqs, psd_db, "PSD [dB/Hz]")

    def _update_plot_dynamic(self, freqs, data, y_label):
        """Standard update but allows changing frequency axis (used for PSD)."""
        # Save current view range
        old_x_range = None
        if not self._first_plot and self.view_box.viewRect() is not None:
            old_x_range, old_y_range = self.view_box.viewRange()
            self.zoom_y_dict[self.y_label_text] = old_y_range

        self._first_plot = False
        self.current_plot_data = data
        self.y_label_text = y_label
        
        # Temporary override freq_axis for this plot
        orig_freq_axis = self.freq_axis
        self.freq_axis = freqs
        
        self.marker_panel.update_headers(self.interaction_mode, y_label)
        if self.stats_region.isVisible(): self.update_statistics()
        
        self.plot_item.clear()
        self.plot_item.addItem(self.stats_region)
        self.stats_region.setZValue(50)
        self.plot_item.addItem(self.stats_markers)
        self.stats_markers.setZValue(100)
        self.plot_item.getAxis('left').setLabel(y_label)
        
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        pen = pg.mkPen(p.accent, width=1.5)
        curve = self.plot_item.plot(freqs, data, pen=pen)
        curve.setZValue(0)
        
        if hasattr(self, 'stats_line') and self.stats_line:
            if self.stats_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_line)
            self.stats_line.setZValue(100)
            
        for m in self.markers_freq: 
            self.plot_item.addItem(m)
        for m in self.markers_freq_endless: 
            self.plot_item.addItem(m)
            
        active_y = self.markers_y_dict.get(y_label, [])
        for m in active_y:
            self.plot_item.addItem(m)

        # Bounds checks
        valid_data = data[np.isfinite(data)]
        if len(valid_data) > 0:
            y_min, y_max = np.min(valid_data), np.max(valid_data)
        else:
            y_min, y_max = -100.0, 0.0
            
        y_range = y_max - y_min if y_max != y_min else 1.0
        f_start, f_end = float(freqs[0]), float(freqs[-1])
        y_min_lim, y_max_lim = float(y_min - y_range*0.1), float(y_max + y_range*0.1)
        
        self.view_box.setLimits(xMin=f_start, xMax=f_end, yMin=y_min_lim, yMax=y_max_lim)
        
        if y_label in self.zoom_y_dict:
            self.plot_item.setYRange(*self.zoom_y_dict[y_label], padding=0)
        else:
            self.plot_item.setYRange(float(y_min - y_range*0.05), float(y_max + y_range*0.05), padding=0)
            
        if old_x_range: self.plot_item.setXRange(*old_x_range, padding=0)
        else: self.plot_item.setXRange(f_start, f_end, padding=0)
        
        self.update_scrollbars()
        # Restore orig_freq_axis for other plots? 
        # No, if we stay in PSD mode, markers should work with PSD freqs.
        # But wait, markers are placed based on freq_axis. If freq_axis changes, markers might "jump" if they are index-based.
        # In this app, InfiniteLine markers use absolute values (freq), so it should be fine.

    def _update_plot(self, data, y_label):
        old_x_range = None
        if not self._first_plot and self.view_box.viewRect() is not None:
            old_x_range, old_y_range = self.view_box.viewRange()
            self.zoom_y_dict[self.y_label_text] = old_y_range

        self._first_plot = False

        self.current_plot_data = data
        self.y_label_text = y_label
        self.freq_axis = self.fft_freq_axis
        self.marker_panel.update_headers(self.interaction_mode, y_label)
        
        if self.stats_region.isVisible(): self.update_statistics()
        
        self.plot_item.clear()
        self.plot_item.addItem(self.stats_region)
        self.stats_region.setZValue(50)
        self.plot_item.addItem(self.stats_markers)
        self.stats_markers.setZValue(100)
        self.plot_item.getAxis('left').setLabel(y_label)
        
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        pen = pg.mkPen(p.accent, width=1.5)
        curve = self.plot_item.plot(self.fft_freq_axis, data, pen=pen)
        curve.setZValue(0)
        
        if hasattr(self, 'stats_line') and self.stats_line:
            if self.stats_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_line)
            self.stats_line.setZValue(100)
        
        for m in self.markers_freq: 
            m.setPen(pg.mkPen(p.marker_freq if hasattr(p, 'marker_freq') else p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            m.setZValue(20)
            self.plot_item.addItem(m)
        for m in self.markers_freq_endless: 
            m.setPen(pg.mkPen(p.marker_freq if hasattr(p, 'marker_freq') else p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            m.setZValue(20)
            self.plot_item.addItem(m)
        
        active_y = self.markers_y_dict.get(y_label, [])
        for m in active_y:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            m.setZValue(20)
            self.plot_item.addItem(m)

        # Defensive check for y_min, y_max
        valid_data = data[np.isfinite(data)]
        if len(valid_data) > 0:
            y_min, y_max = np.min(valid_data), np.max(valid_data)
        else:
            y_min, y_max = 0.0, 1.0
            
        y_range = y_max - y_min if y_max != y_min else 1.0
        
        f_start, f_end = float(self.freq_axis[0]), float(self.freq_axis[-1])
        y_min_lim, y_max_lim = float(y_min - y_range*0.1), float(y_max + y_range*0.1)
        
        # Ensure values are within safe bounds for pyqtgraph/Qt
        y_min_lim = np.clip(y_min_lim, -1e15, 1e15)
        y_max_lim = np.clip(y_max_lim, -1e15, 1e15)

        self.view_box.setLimits(xMin=f_start, xMax=f_end, yMin=y_min_lim, yMax=y_max_lim)
        
        if y_label in self.zoom_y_dict:
            self.plot_item.setYRange(*self.zoom_y_dict[y_label], padding=0)
        else:
            self.plot_item.setYRange(float(y_min - y_range*0.05), float(y_max + y_range*0.05), padding=0)
            
        if old_x_range: self.plot_item.setXRange(*old_x_range, padding=0)
        else: self.plot_item.setXRange(f_start, f_end, padding=0)
        
        self.update_scrollbars()

    def update_statistics(self):
        if not self.stats_region.isVisible() or len(self.current_plot_data) == 0: return
        r_min, r_max = self.stats_region.getRegion()
        i_min = np.searchsorted(self.freq_axis, r_min)
        i_max = np.searchsorted(self.freq_axis, r_max)
        i_min, i_max = max(0, i_min), min(len(self.freq_axis), i_max)
        if i_min >= i_max: return
        
        slice_data = self.current_plot_data[i_min:i_max]
        p_max, p_min, p_median = np.max(slice_data), np.min(slice_data), np.median(slice_data)
        
        if "[dB]" in self.y_label_text:
            # Use 10log10 for power-related plots (PSD, magnitude^2), 20log10 for amplitude (magnitude, real, imag)
            is_power_plot = any(x in self.y_label_text.lower() for x in ["psd", "magnitude^2"])
            factor = 10 if is_power_plot else 20
            p_mean = factor * np.log10(np.mean(10**(slice_data/factor)) + 1e-18)
        else: p_mean = np.mean(slice_data)
        
        idx_max, idx_min = i_min + np.argmax(slice_data), i_min + np.argmin(slice_data)
        f_max, f_min = self.freq_axis[idx_max], self.freq_axis[idx_min]
        
        panel = self.marker_panel
        panel.stats_max_val.setText(f"{p_max:.4g}"); panel.stats_min_val.setText(f"{p_min:.4g}")
        panel.stats_mean_val.setText(f"{p_mean:.4g}"); panel.stats_median_val.setText(f"{p_median:.4g}")
        
        # Calculate Integrated Power
        if "[dB]" in self.y_label_text:
            # 10log for power regardless of amplitude scaling
            lin_pow_slice = 10**(slice_data / 10.0)
        else:
            if "magnitude^2" in self.y_label_text.lower():
                lin_pow_slice = slice_data
            else:
                lin_pow_slice = slice_data**2
        
        # Compute Total linear power
        total_p_lin = np.sum(lin_pow_slice)
        
        # If PSD, we integrate over normalized frequency (-0.5 to 0.5)
        # This makes the integrated power independent of the physical sample rate.
        if "PSD" in self.y_label_text:
            df_norm = 1.0 / len(self.freq_axis)
            total_p_lin *= df_norm
        
        # Window Incoherent Gain (IG) compensation (S2/N)
        # We always use Rectangular currently (IG=1), but for future-proofing:
        # IG = np.sum(window**2) / n. Since window is forced ones(n), IG = 1.0.
        total_p_lin /= 1.0 # Placeholder for IG compensation if windowing is added back
        
        if "[dB]" in self.y_label_text:
            total_p_db = 10 * np.log10(total_p_lin + 1e-15)
            panel.stats_total_power.setText(f"{total_p_db:.2f} dB")
        else:
            panel.stats_total_power.setText(f"{total_p_lin:.4g}")

        panel.stats_max_freq.setText(f"{f_max:,.0f}"); panel.stats_min_freq.setText(f"{f_min:,.0f}")
        panel.stats_max_idx.setText(f"{idx_max}"); panel.stats_min_idx.setText(f"{idx_min}")
        
        self.stats_markers.setData([
            {'pos': (f_max, p_max), 'brush': pg.mkBrush(255, 50, 50), 'pen': pg.mkPen('#ff3232', width=2), 'symbol': 'o'},
            {'pos': (f_min, p_min), 'brush': pg.mkBrush(50, 255, 50), 'pen': pg.mkPen('#32ff32', width=2), 'symbol': 't'}
        ])

    def freq_to_index(self, freq):
        return np.searchsorted(self.freq_axis, freq)

    def place_marker(self, scene_pos, drag_mode=False):
        v_pos = self.view_box.mapSceneToView(scene_pos)
        is_freq = (self.interaction_mode in ['FREQ', 'FREQ_ENDLESS', 'STATS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        
        # Clamp to bounds
        if is_freq:
            f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
            val = max(f_min, min(f_max, v_pos.x()))
        else:
            y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
            val = max(y_min, min(y_max, v_pos.y()))
            
        if is_endless:
            active_markers = self.markers_freq_endless if is_freq else self.markers_y_endless_dict[self.y_label_text]
        else:
            active_markers = self.markers_freq if is_freq else self.markers_y_dict[self.y_label_text]

        # --- STATS Region Logic ---
        if self.interaction_mode == 'STATS':
            if self.stats_bounds:
                best_idx = -1
                min_dist = 20 # pixels
                for i, b_val in enumerate(self.stats_bounds):
                    pi = self.view_box.mapViewToScene(pg.Point(b_val, 0))
                    dist = abs(scene_pos.x() - pi.x())
                    if dist < min_dist:
                        min_dist = dist; best_idx = i
                
                if best_idx != -1:
                    old_v = self.stats_bounds[best_idx]
                    self.stats_bounds[best_idx] = val
                    if old_v in self.stats_marker_order:
                        oidx = self.stats_marker_order.index(old_v)
                        self.stats_marker_order[oidx] = val
                    self.stats_bounds.sort()
                    if drag_mode:
                        self.active_drag_stats_bound_idx = self.stats_bounds.index(val)
                    
                    if len(self.stats_bounds) == 1:
                        if self.stats_line: self.stats_line.setPos(val)
                    else:
                        self.stats_region.setRegion(self.stats_bounds)
                    self.update_statistics()
                    return

            # No hit - Place new bound or replace oldest
            if len(self.stats_marker_order) >= 2:
                oldest_v = self.stats_marker_order.pop(0)
                if oldest_v in self.stats_bounds: self.stats_bounds.remove(oldest_v)
            
            self.stats_marker_order.append(val)
            self.stats_bounds.append(val)
            self.stats_bounds.sort()
            
            if drag_mode:
                self.active_drag_stats_bound_idx = self.stats_bounds.index(val)
            
            if len(self.stats_bounds) == 1:
                if self.stats_line is None:
                    p = get_palette(self.settings_mgr.get("ui/theme", "Dark"))
                    self.stats_line = pg.InfiniteLine(angle=90, pen=pg.mkPen(p.marker_freq if hasattr(p, 'marker_freq') else p.marker_time, width=2, style=Qt.PenStyle.DashLine), movable=False)
                    self.stats_line.setZValue(100)
                
                if self.stats_line not in self.plot_item.items:
                    self.plot_item.addItem(self.stats_line)
                self.stats_line.setPos(val)
                self.stats_line.show()
                self.stats_region.hide()
                self.stats_markers.hide()
            else:
                if self.stats_line: self.stats_line.hide()
                self.stats_region.setRegion(self.stats_bounds)
                self.stats_region.show()
                self.stats_markers.show()
                
            self.update_statistics()
            return

        if self.interaction_mode in ['ZOOM', 'MOVE']:
            return

        # 1. Hit test EXISTING MARKERS
        found_marker = None
        for i, m in enumerate(active_markers):
            pi = self.view_box.mapViewToScene(pg.Point(m.value(), 0) if is_freq else pg.Point(0, m.value()))
            dist = abs(scene_pos.x() - pi.x()) if is_freq else abs(scene_pos.y() - pi.y())
            if dist < 10:
                found_marker = m
                break
        
        if found_marker:
            self.active_drag_marker = found_marker
            return

        # 2. Add or RE-PLACE Marker
        if not is_endless and len(active_markers) == 2:
            # Teleport/Swap logic (like in Time Domain)
            lock_m1 = self.marker_panel.btn_lock_m1.isChecked()
            lock_m2 = self.marker_panel.btn_lock_m2.isChecked()
            lock_delta = self.marker_panel.btn_lock_delta.isChecked()
            lock_center = self.marker_panel.btn_lock_center.isChecked()

            # Decide which marker to move
            if lock_m1 and not lock_m2:
                target, other = active_markers[1], active_markers[0]
            elif lock_m2 and not lock_m1:
                target, other = active_markers[0], active_markers[1]
            else:
                # Move oldest
                target = min(active_markers, key=lambda m: self._marker_age.get(m, 0))
                other = active_markers[1] if target == active_markers[0] else active_markers[0]
            
            # If target is locked, verify if we can move it via delta/center
            is_m1 = (target == active_markers[0])
            if (is_m1 and lock_m1) or (not is_m1 and lock_m2):
                if not (lock_delta or lock_center): return

            shift = val - target.value()
            if lock_delta:
                new_t, new_o = val, other.value() + shift
                if is_freq:
                    f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                    if f_min <= new_t <= f_max and f_min <= new_o <= f_max:
                        target.setValue(new_t); other.setValue(new_o)
                else:
                    y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                    if y_min <= new_t <= y_max and y_min <= new_o <= y_max:
                        target.setValue(new_t); other.setValue(new_o)
            elif lock_center:
                ct = (active_markers[0].value() + active_markers[1].value()) / 2
                new_o = 2 * ct - val
                if is_freq:
                    f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                    if f_min <= val <= f_max and f_min <= new_o <= f_max:
                        target.setValue(val); other.setValue(new_o)
                else:
                    y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                    if y_min <= val <= y_max and y_min <= new_o <= y_max:
                        target.setValue(val); other.setValue(new_o)
            else:
                target.setValue(val)
                self._marker_age_counter += 1
                self._marker_age[target] = self._marker_age_counter

            if drag_mode:
                self.active_drag_marker = target

            self.update_marker_info()
            return

        # 1.5 Hit test GRID LINES (Shadow Markers)
        if not is_endless and len(active_markers) == 2:
            grid_lines = self.grid_lines_freq if is_freq else self.grid_lines_mag
            best_gl = None
            min_gl_dist = 20 # pixels
            
            for gl in grid_lines:
                gl_pos = gl.value()
                pi = self.view_box.mapViewToScene(pg.Point(gl_pos, 0) if is_freq else pg.Point(0, gl_pos))
                dist = abs(scene_pos.x() - pi.x()) if is_freq else abs(scene_pos.y() - pi.y())
                if dist < min_gl_dist:
                    min_gl_dist = dist; best_gl = gl
            
            if best_gl:
                sorted_m = sorted(active_markers, key=lambda m: m.value())
                p1, p2 = sorted_m[0].value(), sorted_m[1].value()
                delta = p2 - p1
                k = (best_gl.value() - p1) / delta if delta != 0 else 0.5
                
                lock_m1 = self.marker_panel.btn_lock_m1.isChecked()
                lock_m2 = self.marker_panel.btn_lock_m2.isChecked()
                lock_delta = self.marker_panel.btn_lock_delta.isChecked()
                lock_center = self.marker_panel.btn_lock_center.isChecked()
                
                move_p1 = (k < 0.5)
                if lock_m1 and not lock_m2: move_p1 = False
                elif lock_m2 and not lock_m1: move_p1 = True
                
                if drag_mode:
                    self.active_drag_grid_info = {
                        'k': k,
                        'moving_marker': sorted_m[0] if move_p1 else sorted_m[1],
                        'fixed_marker': sorted_m[1] if move_p1 else sorted_m[0],
                        'is_p1': move_p1,
                        'is_freq': is_freq,
                        'lock_delta': lock_delta,
                        'lock_center': lock_center
                    }
                    self.active_drag_marker = None
                return

        # 2. Add NEW Marker
        if len(active_markers) < (100 if is_endless else 2):
            p = get_palette(self.settings_mgr.get("ui/theme", "Dark"))
            color = p.marker_freq if (is_freq and hasattr(p, 'marker_freq')) else \
                    p.marker_mag if not is_freq else p.marker_time
            
            m = pg.InfiniteLine(pos=val, angle=90 if is_freq else 0, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine), movable=False)
            m.setZValue(20)
            if is_endless:
                from PyQt6.QtWidgets import QGraphicsTextItem
                label = pg.InfLineLabel(m, text=f"M{len(active_markers)+1}", position=0.9, color=color)
                m.label = label
            
            self.plot_item.addItem(m)
            active_markers.append(m)
            if drag_mode:
                self.active_drag_marker = m
            self.update_marker_info()

    def handle_lock_change(self, lock_type, checked):
        # View just needs to react if necessary (e.g. for grid sync)
        self.update_marker_info()

    def remove_marker_item(self, marker, mode):
        if marker in self.plot_item.items:
            self.plot_item.removeItem(marker)
        
        is_freq = 'FREQ' in mode
        active_list = self.markers_freq_endless if is_freq else self.markers_y_endless_dict[self.y_label_text]
        
        if marker in active_list:
            active_list.remove(marker)
            # Re-label remaining
            for i, m in enumerate(active_list):
                if hasattr(m, 'label'): m.label.setFormat(f"M{i+1}")
        
        self.update_marker_info()

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        is_freq = (self.interaction_mode in ['FREQ', 'FREQ_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        
        try:
            val = float(sender.text())
            if is_freq:
                curr_min, curr_max = self.freq_axis[0], self.freq_axis[-1]
            else:
                curr_min, curr_max = np.min(self.current_plot_data), np.max(self.current_plot_data)

            if name.startswith('em_'):
                # Endless edit
                parts = name.split('_')
                idx = int(parts[1])
                unit = parts[2]
                active_list = self.markers_freq_endless if is_freq else self.markers_y_endless_dict[self.y_label_text]
                if idx < len(active_list):
                    m = active_list[idx]
                    if is_freq:
                        if unit == 'bin':
                            new_p = np.clip(self.freq_axis[max(0, min(len(self.freq_axis)-1, int(val)))], curr_min, curr_max)
                        else:
                            new_p = np.clip(val, curr_min, curr_max)
                    else:
                        new_p = np.clip(val, curr_min, curr_max)
                    m.setValue(new_p)
                self.update_marker_info()
                return

            active_markers = self.markers_freq if is_freq else self.markers_y_dict[self.y_label_text]
            sorted_markers = sorted(active_markers, key=lambda m: m.value())

            if name.startswith('m'):
                idx = int(name[1])
                if idx >= len(sorted_markers): return
                
                new_p = val
                if 'v2' in name and is_freq:
                    new_p = self.freq_axis[max(0, min(len(self.freq_axis)-1, int(val)))]
                
                new_p = np.clip(new_p, curr_min, curr_max)

                if len(sorted_markers) == 2:
                    other_idx = 1 - idx
                    shift = new_p - sorted_markers[idx].value()
                    if self.marker_panel.btn_lock_delta.isChecked():
                        new_o = sorted_markers[other_idx].value() + shift
                        if curr_min <= new_o <= curr_max:
                            sorted_markers[idx].setValue(new_p); sorted_markers[other_idx].setValue(new_o)
                    elif self.marker_panel.btn_lock_center.isChecked():
                        ct = (sorted_markers[0].value() + sorted_markers[1].value()) / 2
                        new_o = 2 * ct - new_p
                        if curr_min <= new_o <= curr_max:
                            sorted_markers[idx].setValue(new_p); sorted_markers[other_idx].setValue(new_o)
                    else: sorted_markers[idx].setValue(new_p)
                else: sorted_markers[idx].setValue(new_p)
                
            elif len(sorted_markers) == 2:
                p1, p2 = sorted_markers[0].value(), sorted_markers[1].value()
                if 'delta' in name:
                    dv = val
                    sorted_markers[0].setValue((p1+p2)/2 - dv/2); sorted_markers[1].setValue((p1+p2)/2 + dv/2)
                elif 'center' in name:
                    ct = val
                    dv = abs(p2-p1)
                    sorted_markers[0].setValue(ct - dv/2); sorted_markers[1].setValue(ct + dv/2)
                        
            self.update_marker_info()
        except Exception: pass

    def toggle_grid(self, axis, enabled):
        if axis == 'FREQ': self.grid_freq_enabled = enabled
        else: self.grid_mag_enabled = enabled
        self.update_grid(axis)

    def toggle_tracking(self, axis, enabled):
        if axis == 'FREQ': self.grid_freq_tracking = enabled
        else: self.grid_mag_enabled = enabled
        self.update_grid(axis)

    def update_grid(self, axis, force=False):
        if not hasattr(self, '_grid_timer'):
            self._grid_timer = QTimer()
            self._grid_timer.setSingleShot(True)
            self._grid_timer.timeout.connect(self._do_update_grid)
            self._grid_pending_axes = set()

        if force:
            self._do_update_grid(axis, force=True)
        else:
            self._grid_pending_axes.add(axis)
            if not self._grid_timer.isActive():
                self._grid_timer.start(50) # 50ms throttle

    def _do_update_grid(self, axis=None, force=False):
        if axis is None:
            axes_to_update = list(self._grid_pending_axes)
            self._grid_pending_axes.clear()
            for a in axes_to_update:
                self._do_update_grid(a, force=force)
            return
        
        is_freq = (axis == 'FREQ')
        enabled = self.grid_freq_enabled if is_freq else self.grid_mag_enabled
        tracking = self.grid_freq_tracking if is_freq else self.grid_mag_tracking
        active_markers = self.markers_freq if is_freq else self.markers_y_dict.get(self.y_label_text, [])
        grid_lines = self.grid_lines_freq if is_freq else self.grid_lines_mag
        
        if not enabled:
            for line in grid_lines: self.plot_item.removeItem(line)
            grid_lines.clear()
            return
        if not tracking and not force: return
        for line in grid_lines: self.plot_item.removeItem(line)
        grid_lines.clear()
        if len(active_markers) != 2: return
        
        sorted_m = sorted(active_markers, key=lambda m: m.value())
        p1, p2 = sorted_m[0].value(), sorted_m[1].value()
        delta = abs(p2 - p1)
        if delta <= 0: return

        # Optimization: Only plot visible lines
        vr = self.plot_item.viewRange()
        v_min_visible, v_max_visible = vr[0] if is_freq else vr[1]
        
        # Guard against too many markers
        if (v_max_visible - v_min_visible) / delta > 500:
            return
        
        angle = 90 if is_freq else 0
        theme = self.settings_mgr.get("ui/theme", "Dark")
        color = self.settings_mgr.get(f"ui/{theme}/grid_color", "#c8c8ff")
        style_name = self.settings_mgr.get(f"ui/{theme}/grid_style", "SolidLine")
        alpha = int(self.settings_mgr.get("ui/grid_alpha", 30))
        
        style_map = {
            "SolidLine": Qt.PenStyle.SolidLine,
            "DashLine": Qt.PenStyle.DashLine,
            "DotLine": Qt.PenStyle.DotLine,
            "DashDotLine": Qt.PenStyle.DashDotLine
        }
        style = style_map.get(str(style_name), Qt.PenStyle.SolidLine)
        
        from PyQt6.QtGui import QColor
        qcolor = QColor(color)
        qcolor.setAlphaF(alpha / 100.0)
        
        pen = pg.mkPen(qcolor, width=1, style=style)
        
        # Start from first visible multiple of delta relative to p1
        start_count = np.ceil((v_min_visible - p1) / delta)
        curr = p1 + start_count * delta
        
        count = 0
        while curr <= v_max_visible + 1e-9 and count < 500:
            line = pg.InfiniteLine(pos=curr, angle=angle, pen=pen, movable=False)
            line.setHoverPen(pg.mkPen(255, 0, 0, width=2))
            line.setAcceptHoverEvents(True)
            line.setZValue(5)
            self.plot_item.addItem(line, ignoreBounds=True)
            grid_lines.append(line)
            curr += delta
            count += 1


    def update_drag(self, scene_pos):
        v_pos = self.plot_item.vb.mapSceneToView(scene_pos)
        
        # 1. Handle STATS Region dragging (Boundaries)
        if getattr(self, 'active_drag_stats_bound_idx', -1) != -1:
            idx = self.active_drag_stats_bound_idx
            f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
            val = max(f_min, min(f_max, v_pos.x()))
            self.stats_bounds[idx] = val
            
            if len(self.stats_bounds) == 2:
                other_idx = 1 - idx
                other_v = self.stats_bounds[other_idx]
                
                self.stats_bounds.sort()
                self.active_drag_stats_bound_idx = self.stats_bounds.index(val)
                
                # Update order to track which one is 'oldest' for future replacements
                if self.stats_marker_order[0] == self.stats_bounds[1 - self.active_drag_stats_bound_idx]:
                    self.stats_marker_order = [other_v, val]
                else:
                    self.stats_marker_order = [val, other_v]
                
                self.stats_region.setRegion(self.stats_bounds)
            else:
                if self.stats_line: self.stats_line.setPos(val)
                if self.stats_marker_order:
                    self.stats_marker_order[-1] = val
            
            self.update_statistics()
            return

        # 1.5 Handle Shadow Marker (Grid Line) dragging
        if getattr(self, 'active_drag_grid_info', None):
            info = self.active_drag_grid_info
            is_freq = info['is_freq']
            k = info['k']
            m_move = info['moving_marker']
            m_fixed = info['fixed_marker']
            is_p1 = info['is_p1']
            p_fixed = m_fixed.value()
            lock_delta = info.get('lock_delta', False)
            lock_center = info.get('lock_center', False)
            
            if is_freq:
                f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                g_prime = max(f_min, min(f_max, v_pos.x()))
            else:
                y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                g_prime = max(y_min, min(y_max, v_pos.y()))
            
            active_markers = self.markers_freq if is_freq else self.markers_y_dict[self.y_label_text]
            if len(active_markers) == 2:
                try:
                    if lock_delta:
                        sorted_m = sorted(active_markers, key=lambda m: m.value())
                        p1_orig, p2_orig = sorted_m[0].value(), sorted_m[1].value()
                        delta_orig = p2_orig - p1_orig
                        shift = g_prime - (p1_orig + k * delta_orig)
                        new_p1, new_p2 = p1_orig + shift, p2_orig + shift
                        if is_freq:
                            f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                            if f_min <= new_p1 <= f_max and f_min <= new_p2 <= f_max:
                                sorted_m[0].setValue(new_p1); sorted_m[1].setValue(new_p2)
                        else:
                            y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                            if y_min <= new_p1 <= y_max and y_min <= new_p2 <= y_max:
                                sorted_m[0].setValue(new_p1); sorted_m[1].setValue(new_p2)
                    elif lock_center:
                        sorted_m = sorted(active_markers, key=lambda m: m.value())
                        p1_orig, p2_orig = sorted_m[0].value(), sorted_m[1].value()
                        center = (p1_orig + p2_orig) / 2
                        if abs(k - 0.5) > 1e-9:
                            new_delta = (g_prime - center) / (k - 0.5)
                            new_p1 = center - new_delta / 2
                            new_p2 = center + new_delta / 2
                            if is_freq:
                                f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                                if f_min <= new_p1 <= f_max and f_min <= new_p2 <= f_max:
                                    if new_p1 <= new_p2:
                                        sorted_m[0].setValue(new_p1); sorted_m[1].setValue(new_p2)
                            else:
                                y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                                if y_min <= new_p1 <= y_max and y_min <= new_p2 <= y_max:
                                    if new_p1 <= new_p2:
                                        sorted_m[0].setValue(new_p1); sorted_m[1].setValue(new_p2)
                    else:
                        if is_p1:
                            if abs(1 - k) > 1e-9:
                                new_v = (g_prime - k * p_fixed) / (1 - k)
                                if is_freq:
                                    f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                                    if f_min <= new_v <= f_max: m_move.setValue(new_v)
                                else:
                                    y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                                    if y_min <= new_v <= y_max: m_move.setValue(new_v)
                        else:
                            if abs(k) > 1e-9:
                                new_v = p_fixed + (g_prime - p_fixed) / k
                                if is_freq:
                                    f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                                    if f_min <= new_v <= f_max: m_move.setValue(new_v)
                                else:
                                    y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                                    if y_min <= new_v <= y_max: m_move.setValue(new_v)
                    
                    # Crossing detection
                    if (active_markers[0].value() > active_markers[1].value()):
                        active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                        self.marker_panel.flip_m_lock(self.interaction_mode)
                except ZeroDivisionError: pass
            
            self.update_marker_info()
            return
            
        if not getattr(self, 'active_drag_marker', None): return
        
        is_freq = (self.active_drag_marker in self.markers_freq or self.active_drag_marker in self.markers_freq_endless)
        is_endless = 'ENDLESS' in self.interaction_mode
        
        if is_freq:
            f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
            val = max(f_min, min(f_max, v_pos.x()))
        else:
            y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
            val = max(y_min, min(y_max, v_pos.y()))
        
        active_markers = self.markers_freq if is_freq else self.markers_y_dict[self.y_label_text]
        if is_endless: active_markers = self.markers_freq_endless if is_freq else self.markers_y_endless_dict[self.y_label_text]
        
        if not is_endless and len(active_markers) == 2:
            other = active_markers[0] if active_markers[1] == self.active_drag_marker else active_markers[1]
            target_idx = 0 if self.active_drag_marker == active_markers[0] else 1
            
            lock_target = self.marker_panel.btn_lock_m1.isChecked() if target_idx == 0 else self.marker_panel.btn_lock_m2.isChecked()
            lock_delta = self.marker_panel.btn_lock_delta.isChecked()
            lock_center = self.marker_panel.btn_lock_center.isChecked()

            if lock_target: return

            shift = val - self.active_drag_marker.value()
            if lock_delta:
                new_o = other.value() + shift
                if is_freq:
                    f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                    if f_min <= val <= f_max and f_min <= new_o <= f_max:
                        self.active_drag_marker.setValue(val); other.setValue(new_o)
                else:
                    y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                    if y_min <= val <= y_max and y_min <= new_o <= y_max:
                        self.active_drag_marker.setValue(val); other.setValue(new_o)
            elif lock_center:
                ct = (self.active_drag_marker.value() + other.value()) / 2
                new_o = 2 * ct - val
                if is_freq:
                    f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
                    if f_min <= val <= f_max and f_min <= new_o <= f_max:
                        self.active_drag_marker.setValue(val); other.setValue(new_o)
                else:
                    y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
                    if y_min <= val <= y_max and y_min <= new_o <= y_max:
                        self.active_drag_marker.setValue(val); other.setValue(new_o)
            else: 
                self.active_drag_marker.setValue(val)
                # Crossing
                if (val > other.value() and target_idx == 0) or (val < other.value() and target_idx == 1):
                    active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                    self.marker_panel.flip_m_lock(self.interaction_mode)
        else: self.active_drag_marker.setValue(val)
        self.update_marker_info()

    def update_marker_info(self):
        is_freq = 'FREQ' in self.interaction_mode
        active_markers = (self.markers_freq + self.markers_freq_endless) if is_freq else \
                         (self.markers_y_dict.get(self.y_label_text, []) + self.markers_y_endless_dict.get(self.y_label_text, []))
        
        if 'ENDLESS' in self.interaction_mode:
            self.marker_panel.update_endless_list(active_markers, self.interaction_mode)
        else:
            sorted_markers = sorted(active_markers, key=lambda m: m.value())
            for i in range(2):
                if i < len(sorted_markers):
                    val = sorted_markers[i].value()
                    self.marker_panel.m_widgets[i]['v1'].blockSignals(True)
                    self.marker_panel.m_widgets[i]['v1'].setText(f"{val:.3f}" if is_freq else f"{val:.6g}")
                    self.marker_panel.m_widgets[i]['v1'].blockSignals(False)
                    if is_freq:
                        idx = self.freq_to_index(val)
                        self.marker_panel.m_widgets[i]['v2'].blockSignals(True)
                        self.marker_panel.m_widgets[i]['v2'].setText(str(idx))
                        self.marker_panel.m_widgets[i]['v2'].blockSignals(False)
                else:
                    for k in ['v1', 'v2']: 
                        self.marker_panel.m_widgets[i][k].blockSignals(True)
                        self.marker_panel.m_widgets[i][k].setText("")
                        self.marker_panel.m_widgets[i][k].blockSignals(False)

            if len(sorted_markers) == 2:
                v1, v2 = sorted_markers[0].value(), sorted_markers[1].value()
                self.marker_panel.delta_v1.blockSignals(True)
                self.marker_panel.delta_v1.setText(f"{abs(v2-v1):.1f}" if is_freq else f"{abs(v2-v1):.6g}")
                self.marker_panel.delta_v1.blockSignals(False)
                
                self.marker_panel.center_v1.blockSignals(True)
                self.marker_panel.center_v1.setText(f"{(v1+v2)/2:.1f}" if is_freq else f"{(v1+v2)/2:.6g}")
                self.marker_panel.center_v1.blockSignals(False)

                if is_freq:
                    idx1 = self.freq_to_index(v1)
                    idx2 = self.freq_to_index(v2)
                    self.marker_panel.delta_v2.blockSignals(True)
                    self.marker_panel.delta_v2.setText(f"{abs(idx2-idx1)+1}")
                    self.marker_panel.delta_v2.blockSignals(False)
                    
                    cv = (v1+v2)/2
                    self.marker_panel.center_v2.blockSignals(True)
                    self.marker_panel.center_v2.setText(f"{self.freq_to_index(cv)}")
                    self.marker_panel.center_v2.blockSignals(False)
            else:
                self.marker_panel.delta_v1.setText("")
                self.marker_panel.delta_v2.setText("")
                self.marker_panel.center_v1.setText("")
                self.marker_panel.center_v2.setText("")
        
        if not 'ENDLESS' in self.interaction_mode:
            m1_p, m2_p = (len(active_markers) >= 1), (len(active_markers) >= 2)
            self.marker_panel.set_locks_enabled(m1_p, m2_p)
            
        self.update_grid('FREQ')
        self.update_grid('MAG')

    def reset_zoom(self):
        f_start, f_end = float(self.freq_axis[0]), float(self.freq_axis[-1])
        self.plot_item.setXRange(f_start, f_end, padding=0)
        valid_data = self.current_plot_data[np.isfinite(self.current_plot_data)]
        if len(valid_data) > 0:
            y_min, y_max = np.min(valid_data), np.max(valid_data)
        else:
            y_min, y_max = 0.0, 1.0
        yr = y_max - y_min if y_max != y_min else 1.0
        self.plot_item.setYRange(float(y_min - yr * 0.05), float(y_max + yr * 0.05), padding=0)

    def handle_marker_clear(self, mode):
        if mode == 'FREQ':
            for m in self.markers_freq: self.plot_item.removeItem(m)
            self.markers_freq.clear()
        elif mode == 'FREQ_ENDLESS':
            for m in self.markers_freq_endless: self.plot_item.removeItem(m)
            self.markers_freq_endless.clear()
        elif mode == 'Y':
            active_list = self.markers_y_dict.get(self.y_label_text, [])
            for m in active_list: self.plot_item.removeItem(m)
            active_list.clear()
        elif mode == 'MAG_ENDLESS':
            active_list = self.markers_y_endless_dict.get(self.y_label_text, [])
            for m in active_list: self.plot_item.removeItem(m)
            active_list.clear()
        elif mode == 'STATS':
            self.stats_bounds.clear()
            self.stats_marker_order.clear()
            if self.stats_line:
                self.plot_item.removeItem(self.stats_line)
                self.stats_line = None
            self.stats_region.hide()
            self.stats_markers.hide()
        self.update_marker_info()

    def update_scrollbars(self): pass # Simplified for now
    def scroll_view(self): pass
    def update_toolbar_style(self):
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.toolbar.setStyleSheet(f"background: {p.bg_sidebar}; border-bottom: 1px solid {p.border};")
    def refresh_plot_style(self):
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.plot_widget.setBackground(p.bg_widget)
        self.plot_item.getAxis('bottom').setPen(p.text_dim)
        self.plot_item.getAxis('left').setPen(p.text_dim)
        self.plot_item.getAxis('bottom').setTextPen(p.text_dim)
        self.plot_item.getAxis('left').setTextPen(p.text_dim)

    def undo_zoom(self):
        if self.zoom_history:
            prev_rect = self.zoom_history.pop()
            self.plot_item.setRange(rect=prev_rect, padding=0)

    def handle_zoom_rectangle(self, rect, zoom_type):
        self.zoom_history.append(self.plot_item.viewRect())
        if zoom_type == 'X_ONLY': self.plot_item.setXRange(rect.left(), rect.right(), padding=0)
        elif zoom_type == 'Y_ONLY': self.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
        else: self.plot_item.setRange(rect, padding=0)

    def handle_move_drag(self, pos, is_start=False, is_finish=False):
        if is_start: self.last_move_scene_pos = pos; return
        if self.last_move_scene_pos is None: return
        delta = pos - self.last_move_scene_pos
        self.view_box.translateBy(x=-self.view_box.mapSceneToView(delta).x() + self.view_box.mapSceneToView(pg.Point(0,0)).x(),
                                  y=-self.view_box.mapSceneToView(delta).y() + self.view_box.mapSceneToView(pg.Point(0,0)).y())
        self.last_move_scene_pos = pos
        if is_finish: self.last_move_scene_pos = None

    def fit_to_markers(self):
        is_freq = (self.interaction_mode in ['FREQ', 'FREQ_ENDLESS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        if is_endless:
            active_markers = self.markers_freq_endless if is_freq else self.markers_y_endless_dict[self.y_label_text]
        else:
            active_markers = self.markers_freq if is_freq else self.markers_y_dict[self.y_label_text]
            
        if len(active_markers) >= 2:
            self.zoom_history.append(self.plot_item.viewRect())
            sorted_m = sorted(active_markers, key=lambda m: m.value())
            v1, v2 = sorted_m[0].value(), sorted_m[-1].value()
            if is_freq:
                self.plot_item.setXRange(v1, v2, padding=0)
            else:
                self.plot_item.setYRange(v1, v2, padding=0)

    def refresh_theme(self):
        self.update_toolbar_style()
        self.refresh_plot_style()
        if hasattr(self, 'marker_panel'):
            self.marker_panel.refresh_theme()
        # Re-plot to refresh curve and marker colors
        if hasattr(self, 'y_label_text') and self.y_label_text in self.available_modes:
            self.available_modes[self.y_label_text]()


    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        key_name = QKeySequence(event.key()).toString()
        if key_name == "F": self.set_interaction_mode('FREQ')
        elif key_name == "M": self.set_interaction_mode('MAG')
        elif key_name == "Ctrl": 
            self._prev_mode = self.interaction_mode
            self.set_interaction_mode('ZOOM')
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        key_name = QKeySequence(event.key()).toString()
        if key_name == "Ctrl": self.set_interaction_mode(getattr(self, '_prev_mode', 'FREQ'))
        super().keyReleaseEvent(event)

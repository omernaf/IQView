import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout,
                             QComboBox)
from PyQt6.QtCore import Qt
from ..widgets import CustomViewBox
from ..base_1d import Base1DPlotView
from .marker_panel import FrequencyDomainMarkerPanel
from ..themes import get_palette, get_scrollbar_stylesheet
from ...dsp.dsp import compute_psd
from ...dsp.domain_transforms import (
    apply_signal_operator,
    resolve_operator_center_freq,
    compute_frequency_domain_fft,
    compute_frequency_domain_trace,
    compute_region_statistics,
)

class FrequencyDomainView(Base1DPlotView):
    """
    A detailed view of a signal segment in the frequency domain with interactive markers.
    """
    primary_mode = "FREQ"
    primary_endless_mode = "FREQ_ENDLESS"
    primary_kb_key = "keybinds/freq_markers"
    primary_kb_default = "F"
    primary_endless_kb_key = "keybinds/freq_endless_markers"
    primary_endless_kb_default = "G"

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

        # Filter state
        self.filter_bounds = []
        self.filter_marker_order = []
        self.filter_placed = False
        self.filter_mode = None
        self.filter_line = None
        self.active_drag_filter_bound_idx = -1
        self._filtered_samples = None
        
        # Endless Markers
        self.markers_freq_endless = []
        self._first_plot = True
        self.last_move_scene_pos = None
        
        # Mode-specific Magnitude markers
        self.markers_y_dict = {
            "magnitude": [], "magnitude [dBFS]": [], "magnitude [dB]": [], 
            "magnitude^2": [],
            "power spectrum density (PSD)": [], "PSD [dB/Hz]": [], "PSD [dB]": [],
            "real": [], "real [dBFS]": [], "real [dB]": [], 
            "imag": [], "imag [dBFS]": [], "imag [dB]": [],
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
        self.marker_panel.filterModeChanged.connect(self.on_filter_mode_changed)
        self.main_layout.addWidget(self.marker_panel)
        
        # --- Toolbar ---
        self.toolbar = QFrame()
        self.toolbar.setObjectName("fd_toolbar")
        self.update_toolbar_style()
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.toolbar_layout.addWidget(QLabel("Operator:"))
        self.operator_combo = QComboBox()
        self.operator_combo.setObjectName("fd_operator_combo")
        self.operator_combo.addItems([
            "Normal",
            "2nd Power",
            "4th Power",
            "Absolute Value",
            "FM Demod",
            "2nd Power FM",
            "Delay & Multiply"
        ])
        self.operator_combo.currentIndexChanged.connect(self.on_operator_changed)
        self.toolbar_layout.addWidget(self.operator_combo)
        
        self.toolbar_layout.addSpacing(15)
        
        self.toolbar_layout.addWidget(QLabel("Plot Mode:"))
        self.plot_buttons_layout = QHBoxLayout()
        self.plot_buttons_layout.setSpacing(5)
        self.toolbar_layout.addLayout(self.plot_buttons_layout)
        
        self.mode_group = QButtonGroup(self)
        self.plot_buttons = []
        
        self.toolbar_layout.addStretch()
        self.setup_oversample_controls(self.toolbar_layout)
        
        self.range_label = QLabel(f"Samples: {len(samples)}")
        self.range_label.setStyleSheet("color: #888; font-family: Consolas; font-size: 11px;")
        self.toolbar_layout.addWidget(self.range_label)
        
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

        # 10th percentile (dotted green) and 90th percentile (dotted red) horizontal indicator lines (spanning full plot)
        self.stats_p10_line = pg.InfiniteLine(angle=0, pen=pg.mkPen('#00e676', width=1.5, style=Qt.PenStyle.DotLine), movable=False)
        self.stats_p10_line.setZValue(90)
        self.stats_p10_line.hide()
        self.plot_item.addItem(self.stats_p10_line)

        self.stats_p90_line = pg.InfiniteLine(angle=0, pen=pg.mkPen('#ff3232', width=1.5, style=Qt.PenStyle.DotLine), movable=False)
        self.stats_p90_line.setZValue(90)
        self.stats_p90_line.hide()
        self.plot_item.addItem(self.stats_p90_line)

        # --- Filter Region ---
        self.filter_region = pg.LinearRegionItem(
            orientation='vertical',
            brush=pg.mkBrush(255, 165, 0, 30),
            movable=False)
        self.filter_region.setZValue(8)
        self.filter_region.hide()
        self.plot_item.addItem(self.filter_region)
        self.filter_region.sigRegionChangeFinished.connect(self.on_filter_region_finished)
        
        # --- Process Data ---
        self.compute_fft()
        
        raw_modes = {
            "magnitude": self.plot_magnitude,
            "magnitude [dBFS]": self.plot_magnitude_db,
            "magnitude [dB]": self.plot_magnitude_db,
            "magnitude^2": self.plot_magnitude_squared,
            "power spectrum density (PSD)": self.plot_psd,
            "PSD [dB/Hz]": self.plot_psd,
            "PSD [dB]": self.plot_psd,
            "real": self.plot_real,
            "real [dBFS]": self.plot_real_db,
            "real [dB]": self.plot_real_db,
            "imag": self.plot_imag,
            "imag [dBFS]": self.plot_imag_db,
            "imag [dB]": self.plot_imag_db,
            "phase": self.plot_phase,
            "unwrapped phase": self.plot_unwrapped_phase
        }
        
        # Track the actual requested mode key, since y_label_text might change dynamically (e.g., PSD [dB])
        self._current_plot_mode_key = 'magnitude'
        def _track(key, fn):
            def wrapper(*args, **kwargs):
                self._current_plot_mode_key = key
                fn()
            return wrapper
        self.available_modes = {k: _track(k, fn) for k, fn in raw_modes.items()}

        self.rebuild_plot_buttons()
        self.set_interaction_mode('FREQ')

        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.view_box.sigRangeChanged.connect(lambda: self.update_grid('FREQ'))
        self.view_box.sigRangeChanged.connect(lambda: self.update_grid('MAG'))
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

    def get_processed_samples(self):
        """Applies the selected preprocessing operator to the source samples."""
        src = self._filtered_samples if (getattr(self, '_filtered_samples', None) is not None) else self.samples
        operator = self.operator_combo.currentText()
        filter_len = int(self.settings_mgr.get("core/inst_freq_filter_len", 7)) if self.settings_mgr else 1
        return apply_signal_operator(src, self.rate, operator, filter_len)

    def on_operator_changed(self):
        """Called when the user selects a new preprocessing operator."""
        operator = self.operator_combo.currentText()
        if operator != "Normal":
            # Switch back to FREQ interaction mode if in FILTER mode (filter not supported directly in baseband)
            if self.interaction_mode == 'FILTER':
                self.set_interaction_mode('FREQ')
                self.marker_panel.update_mode_ui('FREQ')
                self.marker_panel.update_headers('FREQ')
            # Hide filter region
            if hasattr(self, 'filter_region'):
                self.filter_region.hide()
            if hasattr(self, 'filter_line') and self.filter_line:
                self.filter_line.hide()
                
        # Clear zoom ranges as operators change the frequency/magnitude scaling
        self._first_plot = True
        self.zoom_y_dict.clear()
        
        self.compute_fft()
        
        saved_mode = getattr(self, '_current_plot_mode_key', 'magnitude')
        available = getattr(self, 'available_modes', {})
        target = saved_mode if saved_mode in available else 'magnitude'
        if target in available:
            available[target]()

    def set_samples(self, samples: np.ndarray, sample_rate: float, center_freq: float = None) -> None:
        """Replace the underlying IQ samples and sample rate (e.g. when changing oversampling) and re-render."""
        if samples is None or len(samples) == 0 or sample_rate <= 0:
            return
        self.samples = samples
        self.rate = float(sample_rate)
        if center_freq is not None:
            self.center_freq = float(center_freq)
        self._filtered_samples = None
        if hasattr(self, 'range_label'):
            self.range_label.setText(f"Samples: {len(samples)}  |  Fs: {self.rate:g} Hz")
        self._first_plot = True
        self.zoom_y_dict.clear()
        self.compute_fft()
        saved_mode = getattr(self, '_current_plot_mode_key', 'magnitude')
        available = getattr(self, 'available_modes', {})
        target = saved_mode if saved_mode in available else 'magnitude'
        if target in available:
            available[target]()

    def compute_fft(self):
        """Perform FFT processing on the sample segment using signal length N."""
        src = self.get_processed_samples()
        if len(src) == 0:
            return

        operator = self.operator_combo.currentText()
        self.fft_data, self.fft_freq_axis = compute_frequency_domain_fft(
            src, self.rate, self.center_freq, operator
        )
        self.freq_axis = self.fft_freq_axis
        self.stats_region.setBounds([self.freq_axis[0], self.freq_axis[-1]])
        if hasattr(self, 'filter_region'):
            self.filter_region.setBounds([self.freq_axis[0], self.freq_axis[-1]])

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
            active_plots = ["power spectrum density (PSD)", "magnitude [dBFS]", "magnitude"]
            
        for i, name in enumerate(active_plots):
            resolved_name = name
            if name == "magnitude [dB]": resolved_name = "magnitude [dBFS]"
            elif name in ("power spectrum density (PSD)", "PSD [dB]"): resolved_name = "PSD [dB/Hz]"
            elif name == "real [dB]": resolved_name = "real [dBFS]"
            elif name == "imag [dB]": resolved_name = "imag [dBFS]"
            
            target_fn = self.available_modes.get(name) or self.available_modes.get(resolved_name)
            if target_fn:
                btn = QPushButton(resolved_name)
                btn.setCheckable(True)
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.mode_group.addButton(btn, i)
                self.plot_buttons_layout.addWidget(btn)
                btn.clicked.connect(target_fn)
                self.plot_buttons.append(btn)
                if i == 0: btn.setChecked(True)
        
        self.update_button_tooltips()

        if self.plot_buttons and not any(b.isChecked() for b in self.plot_buttons):
            self.plot_buttons[0].setChecked(True)
            self.available_modes.get(self.plot_buttons[0].text(), self.plot_magnitude)()
        elif any(b.isChecked() for b in self.plot_buttons):
            checked_btn = next(b for b in self.plot_buttons if b.isChecked())
            self.available_modes.get(checked_btn.text(), self.plot_magnitude)()

    def set_interaction_mode(self, mode):
        if mode == 'Y': mode = 'MAG'
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
        if mode not in ('ZOOM', 'MOVE'):
            self._prev_interaction_mode = mode

        # --- Stats region visibility ---
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
                self.update_statistics()
            else:
                self.update_statistics()
        else:
            self.stats_region.hide()
            self.stats_markers.hide()
            if self.stats_line: self.stats_line.hide()
            if getattr(self, 'stats_p10_line', None): self.stats_p10_line.hide()
            if getattr(self, 'stats_p90_line', None): self.stats_p90_line.hide()

        # --- Filter region visibility ---
        if mode == 'FILTER':
            b_len = len(self.filter_bounds)
            if b_len == 2:
                self.filter_region.setRegion(sorted(self.filter_bounds))
                self.filter_region.show()
                if self.filter_line: self.filter_line.hide()
            elif b_len == 1:
                self.filter_region.hide()
                if self.filter_line: self.filter_line.show()
            else:
                self.filter_region.hide()
                if self.filter_line: self.filter_line.hide()
            if hasattr(self.marker_panel, 'set_filter_checkboxes_enabled'):
                self.marker_panel.set_filter_checkboxes_enabled(b_len == 2)
        else:
            self.filter_region.hide()
            if self.filter_line: self.filter_line.hide()

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

    def _plot_mode(self, mode_name: str):
        data, label = compute_frequency_domain_trace(self.fft_data, mode_name)
        self._update_plot(data, label)

    def plot_magnitude(self): self._plot_mode("magnitude")
    def plot_magnitude_db(self): self._plot_mode("magnitude [dBFS]")
    def plot_magnitude_squared(self): self._plot_mode("magnitude^2")
    def plot_real(self): self._plot_mode("real")
    def plot_real_db(self): self._plot_mode("real [dBFS]")
    def plot_imag(self): self._plot_mode("imag")
    def plot_imag_db(self): self._plot_mode("imag [dBFS]")
    def plot_phase(self): self._plot_mode("phase")
    def plot_unwrapped_phase(self): self._plot_mode("unwrapped phase")

    def plot_psd(self):
        method = "Welch"
        if self.settings_mgr:
            method = self.settings_mgr.get("core/psd_algorithm", "Welch")
        
        src = self.get_processed_samples()
        if len(src) == 0:
            return
        
        nperseg = 4096 if len(src) > 4096 else 1024
        freqs, psd = compute_psd(src, fs=self.rate, method=method, nperseg=nperseg)
        
        operator = self.operator_combo.currentText()
        cf = resolve_operator_center_freq(self.center_freq, operator)
        freqs = freqs + cf
        psd_db = 10 * np.log10(psd + 1e-20)
        
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
        if hasattr(self, 'stats_p10_line') and self.stats_p10_line:
            if self.stats_p10_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_p10_line)
            self.stats_p10_line.setZValue(90)
        if hasattr(self, 'stats_p90_line') and self.stats_p90_line:
            if self.stats_p90_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_p90_line)
            self.stats_p90_line.setZValue(90)
        # Always re-add filter overlays — plot_item.clear() removes them from the scene;
        # visibility is controlled by show()/hide(), not scene membership.
        if hasattr(self, 'filter_region'):
            self.plot_item.addItem(self.filter_region)
            self.filter_region.setZValue(8)
        if hasattr(self, 'filter_line') and self.filter_line:
            self.plot_item.addItem(self.filter_line)
            self.filter_line.setZValue(9)
        self.plot_item.getAxis('left').setLabel(y_label)
        
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        pen = pg.mkPen('#0072BD', width=0.5)
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
        if hasattr(self, 'stats_p10_line') and self.stats_p10_line:
            if self.stats_p10_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_p10_line)
            self.stats_p10_line.setZValue(90)
        if hasattr(self, 'stats_p90_line') and self.stats_p90_line:
            if self.stats_p90_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_p90_line)
            self.stats_p90_line.setZValue(90)
        # Always re-add filter overlays — plot_item.clear() removes them from the scene;
        # visibility is controlled by show()/hide(), not scene membership.
        if hasattr(self, 'filter_region'):
            self.plot_item.addItem(self.filter_region)
            self.filter_region.setZValue(8)
        if hasattr(self, 'filter_line') and self.filter_line:
            self.plot_item.addItem(self.filter_line)
            self.filter_line.setZValue(9)
        self.plot_item.getAxis('left').setLabel(y_label)
        
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        pen = pg.mkPen('#0072BD', width=0.5)
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

        active_y_endless = self.markers_y_endless_dict.get(y_label, [])
        for m in active_y_endless:
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
        
        if self.stats_region.isVisible(): self.update_statistics()
        self.update_scrollbars()

    def update_statistics(self):
        if not self.stats_region.isVisible():
            self.marker_panel.clear_stats_fields()
            if len(self.stats_bounds) == 1:
                prec1 = int(self.settings_mgr.get("ui/label_precision", 9))
                self.marker_panel.st_row_v1_lbl.setText("Region (Hz)")
                self.marker_panel.st_row_v2_lbl.setText("Index")
                val = self.stats_bounds[0]
                w = self.marker_panel.st_widgets[0]
                w['v1'].blockSignals(True); w['v1'].setText(f"{val:.{prec1}f}"); w['v1'].blockSignals(False)
                idx = self.freq_to_index(val)
                w['v2'].blockSignals(True); w['v2'].setText(f"{idx}"); w['v2'].blockSignals(False)
            return
        if len(self.current_plot_data) == 0:
            return

        r_min, r_max = self.stats_region.getRegion()
        stats = compute_region_statistics(
            self.freq_axis,
            self.current_plot_data,
            r_min,
            r_max,
            self.y_label_text,
            is_freq_domain=True,
        )
        if stats is None:
            return

        b1, b2 = stats.b1, stats.b2
        f_max, f_min = stats.x_max, stats.x_min
        panel = self.marker_panel

        # --- Update Marker Panel Region Definition ---
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9))
        self.marker_panel.st_row_v1_lbl.setText("Region (Hz)")
        self.marker_panel.st_row_v2_lbl.setText("Index")

        for i, val in enumerate([b1, b2]):
            w = self.marker_panel.st_widgets[i]
            w['v1'].blockSignals(True); w['v1'].setText(f"{val:.{prec1}f}"); w['v1'].blockSignals(False)

            idx = self.freq_to_index(val)
            w['v2'].blockSignals(True); w['v2'].setText(f"{idx}"); w['v2'].blockSignals(False)

        # Delta/Center
        dv = abs(b2 - b1)
        cv = (b1 + b2) / 2

        self.marker_panel.st_delta_v1.blockSignals(True); self.marker_panel.st_delta_v1.setText(f"{dv:.{prec1}f}"); self.marker_panel.st_delta_v1.blockSignals(False)
        self.marker_panel.st_center_v1.blockSignals(True); self.marker_panel.st_center_v1.setText(f"{cv:.{prec1}f}"); self.marker_panel.st_center_v1.blockSignals(False)

        idx1, idx2 = self.freq_to_index(b1), self.freq_to_index(b2)
        self.marker_panel.st_delta_v2.blockSignals(True); self.marker_panel.st_delta_v2.setText(f"{abs(idx2-idx1)+1}"); self.marker_panel.st_delta_v2.blockSignals(False)
        self.marker_panel.st_center_v2.blockSignals(True); self.marker_panel.st_center_v2.setText(f"{self.freq_to_index(cv)}"); self.marker_panel.st_center_v2.blockSignals(False)

        # --- Update Statistics Results ---
        unit_str = stats.unit_str
        int_unit_str = stats.int_unit_str
        diff_unit_str = stats.diff_unit_str

        if hasattr(panel, 'st_res_lbl_val'):
            panel.st_res_lbl_val.setText(f"Value ({unit_str})" if unit_str else "Value")
        if hasattr(panel, 'st_res_lbl_mean'):
            panel.st_res_lbl_mean.setText(f"Mean ({unit_str})" if unit_str else "Mean")
        if hasattr(panel, 'st_res_lbl_median'):
            panel.st_res_lbl_median.setText(f"Median ({unit_str})" if unit_str else "Median")
        if hasattr(panel, 'st_res_lbl_integrated'):
            panel.st_res_lbl_integrated.setText(f"Integrated ({int_unit_str})" if int_unit_str else "Integrated")
        if hasattr(panel, 'st_res_lbl_90th'):
            panel.st_res_lbl_90th.setText(f"90th % ({unit_str})" if unit_str else "90th %")
        if hasattr(panel, 'st_res_lbl_10th'):
            panel.st_res_lbl_10th.setText(f"10th % ({unit_str})" if unit_str else "10th %")
        if hasattr(panel, 'st_res_lbl_diff'):
            panel.st_res_lbl_diff.setText(f"90-10 Diff ({diff_unit_str})" if diff_unit_str else "90-10 Diff")

        if stats.is_psd or stats.is_db:
            panel.stats_mean_val.setText(f"{stats.p_mean:.2f}")
            panel.stats_total_power.setText(f"{stats.total_power:.2f}")
        else:
            panel.stats_mean_val.setText(f"{stats.p_mean:.4g}")
            panel.stats_total_power.setText(f"{stats.total_power:.4g}")

        panel.stats_max_val.setText(f"{stats.p_max:.4g}"); panel.stats_min_val.setText(f"{stats.p_min:.4g}")
        panel.stats_median_val.setText(f"{stats.p_median:.4g}")
        panel.stats_90th_val.setText(f"{stats.p_90:.4g}")
        panel.stats_10th_val.setText(f"{stats.p_10:.4g}")
        panel.stats_diff_val.setText(f"{stats.p_diff:.4g}")

        panel.stats_max_freq.setText(f"{f_max:,.0f}"); panel.stats_min_freq.setText(f"{f_min:,.0f}")
        panel.stats_max_idx.setText(f"{stats.idx_max:,}"); panel.stats_min_idx.setText(f"{stats.idx_min:,}")

        self.stats_markers.setData([
            {'pos': (f_max, stats.p_max), 'brush': pg.mkBrush(255, 50, 50), 'pen': pg.mkPen('#ff3232', width=2), 'symbol': 'o'},
            {'pos': (f_min, stats.p_min), 'brush': pg.mkBrush(50, 255, 50), 'pen': pg.mkPen('#32ff32', width=2), 'symbol': 't'}
        ])

        show_p10 = self.marker_panel.cb_p10.isChecked() if hasattr(self.marker_panel, 'cb_p10') else True
        show_p90 = self.marker_panel.cb_p90.isChecked() if hasattr(self.marker_panel, 'cb_p90') else True
        if hasattr(self, 'stats_p10_line'):
            self.stats_p10_line.setPos(stats.p_10)
            self.stats_p10_line.setVisible(show_p10)
        if hasattr(self, 'stats_p90_line'):
            self.stats_p90_line.setPos(stats.p_90)
            self.stats_p90_line.setVisible(show_p90)

    def freq_to_index(self, freq):
        return np.searchsorted(self.freq_axis, freq)

    def _handle_extra_drag(self, scene_pos, v_pos) -> bool:
        """Handle FILTER bound dragging in FrequencyDomainView."""
        if getattr(self, 'active_drag_filter_bound_idx', -1) == -1:
            return False

        idx = self.active_drag_filter_bound_idx
        f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
        val = max(f_min, min(f_max, v_pos.x()))

        if len(self.filter_bounds) == 2:
            b0, b1 = self.filter_bounds[0], self.filter_bounds[1]
            if self.marker_panel.btn_lock_delta.isChecked():
                delta = b1 - b0
                if idx == 0:
                    new_b0 = val
                    new_b1 = new_b0 + delta
                    if new_b1 > f_max:
                        new_b1 = f_max
                        new_b0 = f_max - delta
                    if new_b0 < f_min:
                        new_b0 = f_min
                        new_b1 = f_min + delta
                    self.active_drag_filter_bound_idx = 0
                else:
                    new_b1 = val
                    new_b0 = new_b1 - delta
                    if new_b0 < f_min:
                        new_b0 = f_min
                        new_b1 = f_min + delta
                    if new_b1 > f_max:
                        new_b1 = f_max
                        new_b0 = f_max - delta
                    self.active_drag_filter_bound_idx = 1
                self.filter_bounds = [new_b0, new_b1]
            elif self.marker_panel.btn_lock_center.isChecked():
                center = (b0 + b1) / 2
                half_delta = abs(val - center)
                max_half_delta = min(center - f_min, f_max - center)
                half_delta = min(half_delta, max_half_delta)
                new_b0 = center - half_delta
                new_b1 = center + half_delta
                self.filter_bounds = [new_b0, new_b1]
                self.active_drag_filter_bound_idx = 0 if val < center else 1
            else:
                self.filter_bounds[idx] = val
                self.filter_bounds.sort()
                try:
                    self.active_drag_filter_bound_idx = self.filter_bounds.index(val)
                except ValueError:
                    pass

            self.filter_marker_order = list(self.filter_bounds)
            if self.filter_region:
                self.filter_region.setRegion(self.filter_bounds)
        elif len(self.filter_bounds) == 1:
            self.filter_bounds[0] = val
            if self.filter_line:
                self.filter_line.setPos(val)
        self.update_marker_info()
        return True

    def update_marker_info(self):
        if self.interaction_mode == 'FILTER':
            # Show filter bounds in the marker table
            prec = int(self.settings_mgr.get("ui/label_precision", 9))
            sorted_bounds = sorted(self.filter_bounds)
            for i in range(2):
                if i < len(sorted_bounds):
                    val = sorted_bounds[i]
                    self.marker_panel.m_widgets[i]['v1'].blockSignals(True)
                    self.marker_panel.m_widgets[i]['v1'].setText(f"{val:.{prec}f}")
                    self.marker_panel.m_widgets[i]['v1'].blockSignals(False)
                    idx = self.freq_to_index(val)
                    self.marker_panel.m_widgets[i]['v2'].blockSignals(True)
                    self.marker_panel.m_widgets[i]['v2'].setText(str(idx))
                    self.marker_panel.m_widgets[i]['v2'].blockSignals(False)
                else:
                    for k in ['v1', 'v2']:
                        self.marker_panel.m_widgets[i][k].blockSignals(True)
                        self.marker_panel.m_widgets[i][k].setText("")
                        self.marker_panel.m_widgets[i][k].blockSignals(False)
            if len(sorted_bounds) == 2:
                v1, v2 = sorted_bounds[0], sorted_bounds[1]
                self.marker_panel.delta_v1.blockSignals(True)
                self.marker_panel.delta_v1.setText(f"{abs(v2-v1):.{prec}f}")
                self.marker_panel.delta_v1.blockSignals(False)
                self.marker_panel.center_v1.blockSignals(True)
                self.marker_panel.center_v1.setText(f"{(v1+v2)/2:.{prec}f}")
                self.marker_panel.center_v1.blockSignals(False)
                idx1, idx2 = self.freq_to_index(v1), self.freq_to_index(v2)
                self.marker_panel.delta_v2.blockSignals(True)
                self.marker_panel.delta_v2.setText(f"{abs(idx2-idx1)+1}")
                self.marker_panel.delta_v2.blockSignals(False)
                cv = (v1 + v2) / 2
                self.marker_panel.center_v2.blockSignals(True)
                self.marker_panel.center_v2.setText(f"{self.freq_to_index(cv)}")
                self.marker_panel.center_v2.blockSignals(False)
            else:
                for w in [self.marker_panel.delta_v1, self.marker_panel.delta_v2,
                          self.marker_panel.center_v1, self.marker_panel.center_v2]:
                    w.setText("")
            self.update_grid('FREQ')
            self.update_grid('MAG')
            return

        is_freq = 'FREQ' in self.interaction_mode
        if 'ENDLESS' in self.interaction_mode:
            active_markers = self.markers_freq_endless if is_freq else self.markers_y_endless_dict.get(self.y_label_text, [])
            self.marker_panel.update_endless_list(active_markers, self.interaction_mode)
        else:
            active_markers = self.markers_freq if is_freq else self.markers_y_dict.get(self.y_label_text, [])
            sorted_markers = sorted(active_markers, key=lambda m: m.value())
            
            prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if is_freq else int(self.settings_mgr.get("ui/label_precision", 6))
            
            for i in range(2):
                if i < len(sorted_markers):
                    val = sorted_markers[i].value()
                    self.marker_panel.m_widgets[i]['v1'].blockSignals(True)
                    self.marker_panel.m_widgets[i]['v1'].setText(f"{val:.{prec1}f}")
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
                self.marker_panel.delta_v1.setText(f"{abs(v2-v1):.{prec1}f}")
                self.marker_panel.delta_v1.blockSignals(False)
                
                self.marker_panel.center_v1.blockSignals(True)
                self.marker_panel.center_v1.setText(f"{(v1+v2)/2:.{prec1}f}")
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
        self.zoom_history.append(self.plot_item.viewRect())
        f_start, f_end = float(self.freq_axis[0]), float(self.freq_axis[-1])
        self.plot_item.setXRange(f_start, f_end, padding=0)
        valid_data = self.current_plot_data[np.isfinite(self.current_plot_data)]
        if len(valid_data) > 0:
            y_min, y_max = np.min(valid_data), np.max(valid_data)
        else:
            y_min, y_max = 0.0, 1.0
        yr = y_max - y_min if y_max != y_min else 1.0
        self.plot_item.setYRange(float(y_min - yr * 0.05), float(y_max + yr * 0.05), padding=0)
        self.update_scrollbars()

    def refresh_plot_style(self):
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.plot_widget.setBackground(p.bg_widget)
        self.plot_item.getAxis('bottom').setPen(p.text_dim)
        self.plot_item.getAxis('left').setPen(p.text_dim)
        self.plot_item.getAxis('bottom').setTextPen(p.text_dim)
        self.plot_item.getAxis('left').setTextPen(p.text_dim)
        if hasattr(self, 'view_box') and hasattr(self.view_box, 'refresh_theme'):
            self.view_box.refresh_theme()

    def refresh_theme(self):
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.update_toolbar_style()
        self.refresh_plot_style()
        if hasattr(self, 'marker_panel'):
            self.marker_panel.refresh_theme()
        self.update_button_tooltips()
        sb_style = get_scrollbar_stylesheet(p)
        self.x_scroll.setStyleSheet(sb_style)
        self.y_scroll.setStyleSheet(sb_style)
        # Re-plot to refresh curve and marker colors
        if hasattr(self, 'y_label_text') and self.y_label_text in self.available_modes:
            self.available_modes[self.y_label_text]()

    # -----------------------------------------------------------------------
    # Filter (BPF / BSF) helpers
    # -----------------------------------------------------------------------

    def _place_filter_bound(self, scene_pos, v_pos, drag_mode):
        """Click-to-place / hit-test logic for filter bounds."""
        f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
        val = max(f_min, min(f_max, v_pos.x()))

        # If 2 bounds exist and Delta or Center is locked:
        # Teleport nearest bound to mouse and keep locked relationship immediately!
        if len(self.filter_bounds) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
            sorted_bounds = sorted(self.filter_bounds)
            b0, b1 = sorted_bounds[0], sorted_bounds[1]
            
            if self.marker_panel.btn_lock_delta.isChecked():
                delta = b1 - b0
                dist0 = abs(val - b0)
                dist1 = abs(val - b1)
                if dist0 <= dist1:
                    new_b0 = val
                    new_b1 = val + delta
                    if new_b1 > f_max:
                        new_b1 = f_max
                        new_b0 = f_max - delta
                    if new_b0 < f_min:
                        new_b0 = f_min
                        new_b1 = f_min + delta
                    self.active_drag_filter_bound_idx = 0
                else:
                    new_b1 = val
                    new_b0 = val - delta
                    if new_b0 < f_min:
                        new_b0 = f_min
                        new_b1 = f_min + delta
                    if new_b1 > f_max:
                        new_b1 = f_max
                        new_b0 = f_max - delta
                    self.active_drag_filter_bound_idx = 1
                self.filter_bounds = [new_b0, new_b1]
            elif self.marker_panel.btn_lock_center.isChecked():
                center = (b0 + b1) / 2
                half_delta = abs(val - center)
                max_half_delta = min(center - f_min, f_max - center)
                half_delta = min(half_delta, max_half_delta)
                new_b0 = center - half_delta
                new_b1 = center + half_delta
                self.filter_bounds = [new_b0, new_b1]
                self.active_drag_filter_bound_idx = 0 if val < center else 1

            self.filter_marker_order = list(self.filter_bounds)
            if self.filter_region:
                self.filter_region.setRegion(self.filter_bounds)
                self.filter_region.show()
            if self.filter_line: self.filter_line.hide()
            self.filter_placed = True
            if hasattr(self.marker_panel, 'set_filter_checkboxes_enabled'):
                self.marker_panel.set_filter_checkboxes_enabled(True)
            self.update_marker_info()
            return

        # Hit-test existing bounds within ~20 screen-pixels
        if self.filter_bounds:
            view_range = self.plot_item.viewRange()[0]
            view_width = self.plot_item.vb.width()
            if view_width > 0:
                px_per_hz = view_width / max(view_range[1] - view_range[0], 1e-20)
                HIT_PX = 20.0
                best_idx, best_dist = -1, float('inf')
                for i, bv in enumerate(self.filter_bounds):
                    dist = abs(val - bv) * px_per_hz
                    if dist < HIT_PX and dist < best_dist:
                        best_dist, best_idx = dist, i
                if best_idx != -1:
                    old_v = self.filter_bounds[best_idx]
                    self.filter_bounds[best_idx] = val
                    if old_v in self.filter_marker_order:
                        oidx = self.filter_marker_order.index(old_v)
                        self.filter_marker_order[oidx] = val
                    self.filter_bounds.sort()
                    try:
                        self.active_drag_filter_bound_idx = self.filter_bounds.index(val)
                    except ValueError:
                        self.active_drag_filter_bound_idx = 0
                    if len(self.filter_bounds) == 1:
                        if self.filter_line: self.filter_line.setPos(val)
                    else:
                        if self.filter_region: self.filter_region.setRegion(self.filter_bounds)
                    self.update_marker_info()
                    return

        # FIFO: remove oldest when both bounds already placed
        if len(self.filter_bounds) >= 2:
            oldest_v = self.filter_marker_order[0]
            if oldest_v in self.filter_bounds:
                self.filter_bounds.remove(oldest_v)
            self.filter_marker_order.pop(0)

        # Add new bound
        self.filter_bounds.append(val)
        self.filter_marker_order.append(val)
        self.filter_bounds.sort()
        try:
            self.active_drag_filter_bound_idx = self.filter_bounds.index(val)
        except ValueError:
            self.active_drag_filter_bound_idx = 0

        # Update visuals
        theme = self.settings_mgr.get("ui/theme", "Dark")
        from ..themes import get_palette as _gp
        p = _gp(theme)

        if len(self.filter_bounds) == 1:
            if self.filter_line is None:
                self.filter_line = pg.InfiniteLine(
                    pos=val, angle=90,
                    pen=pg.mkPen(p.accent, width=2, style=Qt.PenStyle.DashLine),
                    movable=False)
                self.filter_line.setZValue(9)
                self.plot_item.addItem(self.filter_line)
            else:
                self.filter_line.setPos(val)
                self.filter_line.show()
            self.filter_region.hide()
            self.filter_placed = False
        elif len(self.filter_bounds) == 2:
            if self.filter_line: self.filter_line.hide()
            self.filter_region.setRegion(self.filter_bounds)
            self.filter_region.show()
            self.filter_placed = True
            if hasattr(self.marker_panel, 'set_filter_checkboxes_enabled'):
                self.marker_panel.set_filter_checkboxes_enabled(True)

        self.update_marker_info()

    def _clear_filter_state(self, replot=False):
        """Remove all filter state and optionally replot unfiltered data."""
        self.filter_bounds.clear()
        self.filter_marker_order.clear()
        self.filter_placed = False
        self.filter_mode = None
        self._filtered_samples = None
        self.active_drag_filter_bound_idx = -1
        if self.filter_region: self.filter_region.hide()
        if self.filter_line: self.filter_line.hide()
        if hasattr(self.marker_panel, 'set_filter_checkboxes_enabled'):
            self.marker_panel.set_filter_checkboxes_enabled(False)
        if hasattr(self.marker_panel, 'cb_bpf'):
            self.marker_panel.cb_bpf.setChecked(False)
            self.marker_panel.cb_bsf.setChecked(False)
        if replot:
            self._apply_filter_and_replot()

    def on_filter_mode_changed(self, mode):
        """Called when BPF/BSF checkboxes toggle."""
        self.filter_mode = mode if mode else None
        self._apply_filter_and_replot()

    def _apply_filter_and_replot(self):
        """Apply BPF/BSF to samples then recompute and replot the FFT.

        Calls apply_filter() which now uses zero-phase filtering (sosfiltfilt/filtfilt),
        making BSF = (Original - BPF) mathematically exact.
        """
        # Use _current_plot_mode_key (always the available_modes key, unlike y_label_text
        # which may differ, e.g. PSD key='power spectrum density (PSD)' vs label='PSD [dB]')
        saved_mode = getattr(self, '_current_plot_mode_key', 'magnitude')

        if (self.filter_mode in ('bpf', 'bsf')
                and len(self.filter_bounds) == 2
                and hasattr(self, 'samples') and len(self.samples) > 0):
            from iqview.dsp import apply_filter
            sb = sorted(self.filter_bounds)
            f1_rel = sb[0] - self.center_freq
            f2_rel = sb[1] - self.center_freq
            try:
                self._filtered_samples = apply_filter(
                    self.samples.astype(np.complex64),
                    self.rate, f1_rel, f2_rel,
                    filter_type=str(self.settings_mgr.get("core/filter_type", "Elliptic")),
                    order=int(self.settings_mgr.get("core/filter_order", 8)),
                    rp=float(self.settings_mgr.get("core/filter_ripple", 0.1)),
                    rs=float(self.settings_mgr.get("core/filter_stopband", 60.0)),
                    filter_taps=int(self.settings_mgr.get("core/filter_taps", 101)),
                    fir_window=str(self.settings_mgr.get("core/fir_window", "Hamming")),
                    mode=self.filter_mode,
                    bessel_norm=str(self.settings_mgr.get("core/filter_bessel_norm", "phase"))
                )
            except Exception as e:
                print(f"[FD Filter] apply_filter error: {e}")
                self._filtered_samples = None
        else:
            self._filtered_samples = None

        self.compute_fft()

        # Restore the user's chosen display mode (not the 'magnitude' default)
        available = getattr(self, 'available_modes', {})
        target = saved_mode if saved_mode in available else 'magnitude'
        if target in available:
            available[target]()


    def on_filter_region_finished(self):
        """Replot after the user finishes dragging the filter region."""
        if len(self.filter_bounds) == 2:
            new_region = sorted(self.filter_region.getRegion())
            if len(new_region) == 2:
                self.filter_bounds = list(new_region)
        if self.filter_mode:
            self._apply_filter_and_replot()
        self.update_marker_info()

    # -----------------------------------------------------------------------

    def _handle_domain_keypress(self, key_name: str) -> bool:
        if key_name == self._get_kb("keybinds/filter_mode", "B"):
            if self.operator_combo.currentText() == "Normal":
                self._prev_interaction_mode = 'FILTER'
                self.set_interaction_mode('FILTER')
            return True
        if key_name == self._get_kb("keybinds/toggle_bpf", "["):
            if self.interaction_mode == 'FILTER' and self.marker_panel.cb_bpf.isEnabled():
                self.marker_panel.cb_bpf.click()
            return True
        if key_name == self._get_kb("keybinds/toggle_bsf", "]"):
            if self.interaction_mode == 'FILTER' and self.marker_panel.cb_bsf.isEnabled():
                self.marker_panel.cb_bsf.click()
            return True
        return False

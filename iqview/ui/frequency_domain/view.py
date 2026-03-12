import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout,
                             QComboBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from ..widgets import CustomViewBox
from .marker_panel import FrequencyDomainMarkerPanel
from ..themes import get_palette, get_scrollbar_stylesheet

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
        
        # Endless Markers
        self.markers_freq_endless = []
        self._first_plot = True
        self.last_move_scene_pos = None
        
        # Mode-specific Magnitude markers
        self.markers_y_dict = {
            "magnitude": [], "magnitude [dB]": [], 
            "magnitude^2": [], "magnitude^2 [dB]": [],
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
        self.stats_markers.hide()
        self.plot_item.addItem(self.stats_markers)
        
        # --- Process Data ---
        self.compute_fft()
        
        self.available_modes = {
            "magnitude": self.plot_magnitude,
            "magnitude [dB]": self.plot_magnitude_db,
            "magnitude^2": self.plot_magnitude_squared,
            "magnitude^2 [dB]": self.plot_magnitude_squared_db,
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

        # Standard FFT with signal length N
        window = np.hanning(n)
        fft_res = np.fft.fft(self.samples * window) / n
        self.fft_data = np.fft.fftshift(fft_res)

        self.freq_axis = np.fft.fftshift(np.fft.fftfreq(n, 1/self.rate)) + self.center_freq
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
                self.update_statistics()
        else:
            self.stats_region.hide()
            self.stats_markers.hide()
            
        cursor = Qt.CursorShape.ArrowCursor
        if mode == 'ZOOM': cursor = Qt.CursorShape.CrossCursor
        elif mode == 'MOVE': cursor = Qt.CursorShape.SizeAllCursor
        elif 'ENDLESS' in mode: cursor = Qt.CursorShape.PointingHandCursor
        self.plot_widget.setCursor(cursor)
        
        self.marker_panel.update_mode_ui(mode)
        self.marker_panel.update_headers(mode, self.y_label_text)
        self.update_marker_info()

    def plot_magnitude(self): self._update_plot(np.abs(self.fft_data), "magnitude")
    def plot_magnitude_db(self):
        data = np.abs(self.fft_data)
        data[data < 1e-15] = 1e-15
        self._update_plot(20 * np.log10(data), "magnitude [dB]")
    def plot_magnitude_squared(self): self._update_plot(np.abs(self.fft_data)**2, "magnitude^2")
    def plot_magnitude_squared_db(self):
        data = np.abs(self.fft_data)**2
        data[data < 1e-15] = 1e-15
        self._update_plot(10 * np.log10(data), "magnitude^2 [dB]")
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

    def _update_plot(self, data, y_label):
        old_x_range = None
        if not self._first_plot and self.view_box.viewRect() is not None:
            old_x_range, old_y_range = self.view_box.viewRange()
            self.zoom_y_dict[self.y_label_text] = old_y_range

        self._first_plot = False

        self.current_plot_data = data
        self.y_label_text = y_label
        self.marker_panel.update_headers(self.interaction_mode, y_label)
        
        if self.stats_region.isVisible(): self.update_statistics()
        
        self.plot_item.clear()
        self.plot_item.addItem(self.stats_region)
        self.plot_item.addItem(self.stats_markers)
        self.plot_item.getAxis('left').setLabel(y_label)
        
        theme = self.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        pen = pg.mkPen(p.accent, width=1.5)
        self.plot_item.plot(self.freq_axis, data, pen=pen)
        
        for m in self.markers_freq: 
            m.setPen(pg.mkPen(p.marker_freq if hasattr(p, 'marker_freq') else p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
        for m in self.markers_freq_endless: 
            m.setPen(pg.mkPen(p.marker_freq if hasattr(p, 'marker_freq') else p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
        
        active_y = self.markers_y_dict.get(y_label, [])
        for m in active_y:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
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
            factor = 10 if "magnitude^2" in self.y_label_text.lower() else 20
            p_mean = factor * np.log10(np.mean(10**(slice_data/factor)) + 1e-18)
        else: p_mean = np.mean(slice_data)
        
        idx_max, idx_min = i_min + np.argmax(slice_data), i_min + np.argmin(slice_data)
        f_max, f_min = self.freq_axis[idx_max], self.freq_axis[idx_min]
        
        panel = self.marker_panel
        panel.stats_max_val.setText(f"{p_max:.4g}"); panel.stats_min_val.setText(f"{p_min:.4g}")
        panel.stats_max_freq.setText(f"{f_max:,.0f}"); panel.stats_min_freq.setText(f"{f_min:,.0f}")
        panel.stats_max_idx.setText(f"{idx_max}"); panel.stats_min_idx.setText(f"{idx_max}")
        
        self.stats_markers.setData([
            {'pos': (f_max, p_max), 'brush': pg.mkBrush(255, 50, 50), 'pen': pg.mkPen('#ff3232', width=2), 'symbol': 'o'},
            {'pos': (f_min, p_min), 'brush': pg.mkBrush(50, 255, 50), 'pen': pg.mkPen('#32ff32', width=2), 'symbol': 't'}
        ])

    def freq_to_index(self, freq):
        return np.searchsorted(self.freq_axis, freq)

    def handle_lock_change(self, lock_type, checked):
        # View just needs to react if necessary (e.g. for grid sync)
        self.update_marker_info()

    def remove_marker_item(self, marker, mode):
        if marker in self.plot_item.items():
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

    def update_grid(self, axis):
        pass # Grid implementation not strictly requested for spectral view yet but stubbing for compat

    def update_drag(self, scene_pos):
        v_pos = self.view_box.mapSceneToView(scene_pos)
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
            else:
                self.marker_panel.delta_v1.setText(""); self.marker_panel.center_v1.setText("")
        
        if not 'ENDLESS' in self.interaction_mode:
            m1_p, m2_p = (len(active_markers) >= 1), (len(active_markers) >= 2)
            self.marker_panel.set_locks_enabled(m1_p, m2_p)

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

    def place_marker(self, scene_pos, drag_mode=False):
        v_pos = self.view_box.mapSceneToView(scene_pos)
        is_freq = (self.interaction_mode in ['FREQ', 'FREQ_ENDLESS', 'STATS'])
        is_endless = 'ENDLESS' in self.interaction_mode
        
        if is_freq:
            f_min, f_max = self.freq_axis[0], self.freq_axis[-1]
            val = max(f_min, min(f_max, v_pos.x()))
        else:
            y_min, y_max = np.min(self.current_plot_data), np.max(self.current_plot_data)
            val = max(y_min, min(y_max, v_pos.y()))
        
        if self.interaction_mode == 'STATS':
            if len(self.stats_bounds) >= 2: self.stats_bounds.clear()
            self.stats_bounds.append(val)
            self.stats_bounds.sort()
            if len(self.stats_bounds) == 2:
                self.stats_region.setRegion(self.stats_bounds)
                self.stats_region.show()
                self.update_statistics()
            return

        active_markers = self.markers_freq if is_freq else self.markers_y_dict[self.y_label_text]
        if is_endless: active_markers = self.markers_freq_endless if is_freq else self.markers_y_endless_dict[self.y_label_text]
        
        # Hit test
        found_marker = None
        for m in active_markers:
            m_scene = self.view_box.mapViewToScene(pg.Point(m.value(), 0) if is_freq else pg.Point(0, m.value()))
            dist = abs(scene_pos.x() - m_scene.x()) if is_freq else abs(scene_pos.y() - m_scene.y())
            if dist < 15:
                found_marker = m
                break

        if found_marker:
            found_marker.setValue(val)
            if drag_mode: self.active_drag_marker = found_marker
            self.update_marker_info()
            return

        if not is_endless and len(active_markers) >= 2:
            target = min(active_markers, key=lambda mrk: self._marker_age.get(mrk, 0))
            target.setValue(val)
            self._marker_age[target] = self._marker_age_counter
            self._marker_age_counter += 1
            if drag_mode: self.active_drag_marker = target
        else:
            theme = self.settings_mgr.get("ui/theme", "Dark")
            p = get_palette(theme)
            color = p.marker_time if is_freq else p.marker_mag
            new_m = pg.InfiniteLine(pos=val, angle=90 if is_freq else 0, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine))
            new_m.setHoverPen(pg.mkPen(255, 0, 0, width=2))
            new_m.setAcceptHoverEvents(True)
            self.plot_item.addItem(new_m)
            active_markers.append(new_m)
            self._marker_age[new_m] = self._marker_age_counter
            self._marker_age_counter += 1
            if drag_mode: self.active_drag_marker = new_m
        
        self.update_marker_info()

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

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout)
from PyQt6.QtCore import Qt
from ..widgets import CustomViewBox
from ..base_1d import Base1DPlotView
from .marker_panel import TimeDomainMarkerPanel
from ..themes import get_palette, get_scrollbar_stylesheet
from ...dsp.domain_transforms import compute_time_domain_trace, compute_region_statistics

class TimeDomainView(Base1DPlotView):
    """
    A detailed view of a signal segment in the time domain with interactive markers.
    """
    primary_mode = "TIME"
    primary_endless_mode = "TIME_ENDLESS"
    primary_kb_key = "keybinds/time_markers"
    primary_kb_default = "T"
    primary_endless_kb_key = "keybinds/time_endless_markers"
    primary_endless_kb_default = "E"

    def __init__(self, samples, start_time, sample_rate, parent=None, parent_window=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.samples = samples # Complex numpy array
        self.start_time = start_time
        self.rate = sample_rate
        self.parent_window = parent_window
        self.settings_mgr = parent_window.settings_mgr if parent_window else None
        self.is_spectrogram = False
        self.interaction_mode = 'TIME'
        self.zoom_mode = False
        self.active_drag_marker = None
        self.last_move_scene_pos = None
        self.markers_time = []
        self._block_signals = False
        # Age tracking: maps each InfiniteLine → insertion order (lower = older)
        self._marker_age = {}
        self._marker_age_counter = 0
        
        # Endless Markers
        self.markers_time_endless = []
        
        # Mode-specific Magnitude markers
        self.markers_y_dict = {
            "Real": [],
            "Real [dB]": [],
            "Imaginary": [],
            "Imaginary [dB]": [],
            "Phase": [],
            "Unwrapped phase": [],
            "instant frequency": [],
            "magnitude": [],
            "magnitude [dB]": [],
            "magnitude^2": [],
            "magnitude^2 [dB]": []
        }
        self.markers_y_endless_dict = {k: [] for k in self.markers_y_dict.keys()}
        
        # Mode-specific Y-zoom states (yMin, yMax)
        self.zoom_y_dict = {}
        
        # Grid variables (added for Shadow Markers)
        self.grid_time_enabled = False
        self.grid_time_tracking = True
        self.grid_lines_time = []
        
        self.grid_mag_enabled = False
        self.grid_mag_tracking = True
        self.grid_lines_mag = []

        self.zoom_history = []
        
        self.y_label_text = list(self.available_modes.keys())[0] if hasattr(self, 'available_modes') else "Real"
        self.current_plot_data = samples.real # Cache for marker sampling
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(5)
        
        # --- Marker Panel ---
        self.marker_panel = TimeDomainMarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.main_layout.addWidget(self.marker_panel)
        
        # --- Toolbar ---
        self.toolbar = QFrame()
        self.toolbar.setObjectName("td_toolbar")
        self.update_toolbar_style()
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.toolbar_layout.addWidget(QLabel("Plot Mode:"))
        
        # Define all available plot modes and their compute functions
        self.available_modes = {
            "Real": self.plot_real,
            "Real [dB]": self.plot_real_db,
            "Imaginary": self.plot_imaginary,
            "Imaginary [dB]": self.plot_imaginary_db,
            "Phase": self.plot_phase,
            "Unwrapped phase": self.plot_unwrapped_phase,
            "instant frequency": self.plot_inst_freq,
            "magnitude": self.plot_magnitude,
            "magnitude [dB]": self.plot_magnitude_db,
            "magnitude^2": self.plot_magnitude_squared,
            "magnitude^2 [dB]": self.plot_magnitude_squared_db
        }
        
        self.plot_buttons_layout = QHBoxLayout()
        self.plot_buttons_layout.setSpacing(5)
        self.toolbar_layout.addLayout(self.plot_buttons_layout)
        
        self.mode_group = QButtonGroup(self)
        self.plot_buttons = []
        
        self.toolbar_layout.addStretch()
        
        end_time = start_time + len(samples) / sample_rate
        range_label = QLabel(f"Range: {start_time:,.6f} to {end_time:,.6f} s")
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
        self.plot_widget.getAxis('bottom').setLabel('Time', units='s')
        self.plot_widget.getAxis('left').setLabel('Amplitude (Real)')
        
        self.grid_layout.addWidget(self.plot_widget, 0, 1)

        # Scrollbars
        self.x_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.y_scroll = QScrollBar(Qt.Orientation.Vertical)
        
        scrollbar_style = get_scrollbar_stylesheet(get_palette(self.parent_window.settings_mgr.get("ui/theme", "Dark")))
        self.x_scroll.setStyleSheet(scrollbar_style)
        self.y_scroll.setStyleSheet(scrollbar_style)
        
        self.grid_layout.addWidget(self.y_scroll, 0, 0)
        self.grid_layout.addWidget(self.x_scroll, 1, 1)
        
        self.x_scroll.hide()
        self.y_scroll.hide()
        
        self.main_layout.addWidget(self.grid_container)
        
        # --- Stats Region Item ---
        self.stats_bounds = []
        self.stats_marker_order = []
        self.stats_line = None
        
        self.stats_region = pg.LinearRegionItem(orientation='vertical')
        self.stats_region.setZValue(9) # Below markers but above plot
        self.stats_region.hide() # Hidden by default
        self.plot_item.addItem(self.stats_region)
        self.stats_region.sigRegionChanged.connect(self.update_statistics)
        
        # --- Stats Visual Indicators (ScatterPlotItem) ---
        self.stats_markers = pg.ScatterPlotItem(size=10, pen=pg.mkPen(None), brush=pg.mkBrush(255, 0, 0, 200))
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
        
        self.time_axis = np.linspace(start_time, end_time, len(samples))
        self.stats_region.setBounds([self.time_axis[0], self.time_axis[-1]])
        # Add buttons and trigger the first plot
        self.rebuild_plot_buttons()
            
        self.set_interaction_mode('TIME')

        # Connect scrollbars
        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.view_box.sigRangeChanged.connect(lambda: self.update_grid('TIME'))
        self.view_box.sigRangeChanged.connect(lambda: self.update_grid('MAG'))
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

    def rebuild_plot_buttons(self):
        # Clear existing buttons
        for btn in self.plot_buttons:
            self.mode_group.removeButton(btn)
            self.plot_buttons_layout.removeWidget(btn)
            btn.deleteLater()
        self.plot_buttons.clear()
        
        # Load active plots from settings
        active_plots = []
        if self.settings_mgr:
            active_plots = self.settings_mgr.get("core/time_plots", [])
            
        # Fallback to default if empty or missing
        if not active_plots:
            active_plots = ["magnitude [dB]", "Real", "Imaginary", "instant frequency"]
            
        for i, name in enumerate(active_plots):
            if name in self.available_modes:
                btn = QPushButton(name)
                btn.setCheckable(True)
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.mode_group.addButton(btn, i)
                self.plot_buttons_layout.addWidget(btn)
                btn.clicked.connect(self.available_modes[name])
                self.plot_buttons.append(btn)
                if i == 0: btn.setChecked(True)
                
        self.update_button_tooltips()

        # Immediately re-trigger the first selected mode to update the plot view
        if len(self.plot_buttons) > 0:
            first_plot_name = self.plot_buttons[0].text()
            self.available_modes[first_plot_name]()

    def set_interaction_mode(self, mode):
        if mode == 'Y': mode = 'MAG'
        self.interaction_mode = mode
        self.zoom_mode = (mode == 'ZOOM')
        if mode not in ('ZOOM', 'MOVE'):
            self._prev_interaction_mode = mode
        
        # Toggle Region visibility
        if mode == 'STATS':
            if len(self.stats_bounds) == 1:
                if self.stats_line: self.stats_line.show()
                self.update_statistics()
            elif len(self.stats_bounds) == 2:
                self.stats_region.show()
                self.stats_markers.show()
                self.update_statistics()
            else:
                self.update_statistics()
        else:
            self.stats_region.hide()
            self.stats_markers.hide()
            if self.stats_line: self.stats_line.hide()
            if getattr(self, 'stats_p10_line', None): self.stats_p10_line.hide()
            if getattr(self, 'stats_p90_line', None): self.stats_p90_line.hide()
            
        self.refresh_cursor()
        self.marker_panel.update_mode_ui(mode)
        self.marker_panel.update_headers(mode, self.y_label_text)
        self.update_marker_info()

    def refresh_cursor(self):
        mode = self.interaction_mode
        cursor = Qt.CursorShape.ArrowCursor
        if mode == 'ZOOM': cursor = Qt.CursorShape.CrossCursor
        elif mode == 'MOVE': cursor = Qt.CursorShape.SizeAllCursor
        elif mode in ['TIME', 'MAG', 'Y', 'FILTER', 'TIME_ENDLESS', 'MAG_ENDLESS']: cursor = Qt.CursorShape.CrossCursor
        self.plot_widget.setCursor(cursor)


    def _plot_mode(self, mode_name: str):
        filter_len = int(self.settings_mgr.get("core/inst_freq_filter_len", 7)) if self.settings_mgr else 7
        data, label = compute_time_domain_trace(self.samples, mode_name, self.rate, filter_len)
        self._update_plot(data, label)

    def plot_real(self):
        self._plot_mode("Real")

    def plot_real_db(self):
        self._plot_mode("Real [dB]")

    def plot_imaginary(self):
        self._plot_mode("Imaginary")

    def plot_imaginary_db(self):
        self._plot_mode("Imaginary [dB]")

    def plot_magnitude(self):
        self._plot_mode("magnitude")

    def plot_magnitude_db(self):
        self._plot_mode("magnitude [dB]")

    def plot_magnitude_squared(self):
        self._plot_mode("magnitude^2")

    def plot_magnitude_squared_db(self):
        self._plot_mode("magnitude^2 [dB]")

    def plot_inst_freq(self):
        self._plot_mode("instant frequency")

    def plot_phase(self):
        self._plot_mode("Phase")

    def plot_unwrapped_phase(self):
        self._plot_mode("Unwrapped phase")

    def update_statistics(self):
        """Calculates Min, Max, Mean, Median for the active region and updates the marker panel UI."""
        if not self.stats_region.isVisible():
            self.marker_panel.clear_stats_fields()
            if len(self.stats_bounds) == 1:
                prec1 = int(self.settings_mgr.get("ui/label_precision", 9))
                self.marker_panel.st_row_v1_lbl.setText("Samples")
                self.marker_panel.st_row_v2_lbl.setText("Region (s)")
                self.marker_panel.st_row_v3_lbl.setText("1/T (Hz)")
                val = self.stats_bounds[0]
                w = self.marker_panel.st_widgets[0]
                w['v1'].blockSignals(True); w['v1'].setText(f"{val:.{prec1}f}"); w['v1'].blockSignals(False)
                abs_s = int(round(val * self.rate)) + 1
                w['v2'].blockSignals(True); w['v2'].setText(f"{abs_s}"); w['v2'].blockSignals(False)
                inv_val = (1.0 / val) if abs(val) > 1e-12 else float('inf')
                w['v3'].blockSignals(True); w['v3'].setText(f"{inv_val:.{prec1}f}" if inv_val != float('inf') else "∞"); w['v3'].blockSignals(False)
            return
        if len(self.current_plot_data) == 0:
            return

        r_min, r_max = self.stats_region.getRegion()
        stats = compute_region_statistics(
            self.time_axis,
            self.current_plot_data,
            r_min,
            r_max,
            self.y_label_text,
            is_freq_domain=False,
        )
        if stats is None:
            return

        b1, b2 = stats.b1, stats.b2
        t_max, t_min = stats.x_max, stats.x_min

        # --- Update Marker Panel Region Definition ---
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9))
        self.marker_panel.st_row_v1_lbl.setText("Samples")
        self.marker_panel.st_row_v2_lbl.setText("Region (s)")
        self.marker_panel.st_row_v3_lbl.setText("1/T (Hz)")

        for i, val in enumerate([b1, b2]):
            w = self.marker_panel.st_widgets[i]
            w['v1'].blockSignals(True); w['v1'].setText(f"{val:.{prec1}f}"); w['v1'].blockSignals(False)

            abs_s = int(round(val * self.rate)) + 1
            w['v2'].blockSignals(True); w['v2'].setText(f"{abs_s}"); w['v2'].blockSignals(False)

            inv_val = (1.0 / val) if abs(val) > 1e-12 else float('inf')
            w['v3'].blockSignals(True); w['v3'].setText(f"{inv_val:.{prec1}f}" if inv_val != float('inf') else "∞"); w['v3'].blockSignals(False)

        # Delta/Center
        dv = abs(b2 - b1)
        cv = (b1 + b2) / 2

        self.marker_panel.st_delta_v1.blockSignals(True); self.marker_panel.st_delta_v1.setText(f"{dv:.{prec1}f}"); self.marker_panel.st_delta_v1.blockSignals(False)
        self.marker_panel.st_center_v1.blockSignals(True); self.marker_panel.st_center_v1.setText(f"{cv:.{prec1}f}"); self.marker_panel.st_center_v1.blockSignals(False)

        s1, s2 = int(round(b1 * self.rate)) + 1, int(round(b2 * self.rate)) + 1
        self.marker_panel.st_delta_v2.blockSignals(True); self.marker_panel.st_delta_v2.setText(f"{abs(s2-s1)+1}"); self.marker_panel.st_delta_v2.blockSignals(False)
        self.marker_panel.st_center_v2.blockSignals(True); self.marker_panel.st_center_v2.setText(f"{int(round(cv*self.rate))+1}"); self.marker_panel.st_center_v2.blockSignals(False)

        if dv > 1e-12: self.marker_panel.st_delta_v3.setText(f"{1.0/dv:.{prec1}f}")
        else: self.marker_panel.st_delta_v3.setText("∞")
        if abs(cv) > 1e-12: self.marker_panel.st_center_v3.setText(f"{1.0/cv:.{prec1}f}")
        else: self.marker_panel.st_center_v3.setText("∞")

        # --- Update Statistics Results ---
        unit_str = stats.unit_str
        diff_unit_str = stats.diff_unit_str
        panel = self.marker_panel

        if hasattr(panel, 'st_res_lbl_val'):
            panel.st_res_lbl_val.setText(f"Value ({unit_str})" if unit_str else "Value")
        if hasattr(panel, 'st_res_lbl_mean'):
            panel.st_res_lbl_mean.setText(f"Mean ({unit_str})" if unit_str else "Mean")
        if hasattr(panel, 'st_res_lbl_median'):
            panel.st_res_lbl_median.setText(f"Median ({unit_str})" if unit_str else "Median")
        if hasattr(panel, 'st_res_lbl_90th'):
            panel.st_res_lbl_90th.setText(f"90th % ({unit_str})" if unit_str else "90th %")
        if hasattr(panel, 'st_res_lbl_10th'):
            panel.st_res_lbl_10th.setText(f"10th % ({unit_str})" if unit_str else "10th %")
        if hasattr(panel, 'st_res_lbl_diff'):
            panel.st_res_lbl_diff.setText(f"90-10 Diff ({diff_unit_str})" if diff_unit_str else "90-10 Diff")

        self.marker_panel.stats_max_val.setText(f"{stats.p_max:.6g}")
        self.marker_panel.stats_min_val.setText(f"{stats.p_min:.6g}")
        self.marker_panel.stats_mean_val.setText(f"{stats.p_mean:.6g}")
        self.marker_panel.stats_median_val.setText(f"{stats.p_median:.6g}")
        self.marker_panel.stats_90th_val.setText(f"{stats.p_90:.6g}")
        self.marker_panel.stats_10th_val.setText(f"{stats.p_10:.6g}")
        self.marker_panel.stats_diff_val.setText(f"{stats.p_diff:.6g}")

        self.marker_panel.stats_max_time.setText(f"{t_max:.6f}")
        self.marker_panel.stats_min_time.setText(f"{t_min:.6f}")

        self.marker_panel.stats_max_idx.setText(f"{stats.idx_max}")
        self.marker_panel.stats_min_idx.setText(f"{stats.idx_min}")

        # Update graphical indicators
        self.stats_markers.setData([
            {'pos': (t_max, stats.p_max), 'brush': pg.mkBrush(255, 50, 50), 'pen': pg.mkPen('#ff3232', width=2), 'symbol': 'o'},
            {'pos': (t_min, stats.p_min), 'brush': pg.mkBrush(50, 255, 50), 'pen': pg.mkPen('#32ff32', width=2), 'symbol': 't'}
        ])

        # 10th and 90th percentile horizontal dotted lines spanning the full plot
        show_p10 = self.marker_panel.cb_p10.isChecked() if hasattr(self.marker_panel, 'cb_p10') else True
        show_p90 = self.marker_panel.cb_p90.isChecked() if hasattr(self.marker_panel, 'cb_p90') else True
        if hasattr(self, 'stats_p10_line'):
            self.stats_p10_line.setPos(stats.p_10)
            self.stats_p10_line.setVisible(show_p10)
        if hasattr(self, 'stats_p90_line'):
            self.stats_p90_line.setPos(stats.p_90)
            self.stats_p90_line.setVisible(show_p90)

    def _update_plot(self, data, y_label):
        # 1. Save current view ranges (if not first run)
        old_x_range = None
        if hasattr(self, 'view_box') and self.view_box.viewRect() is not None:
            old_x_range, old_y_range = self.view_box.viewRange()
            self.zoom_y_dict[self.y_label_text] = old_y_range

        # 2. Update state
        self.current_plot_data = data
        self.y_label_text = y_label
        self.marker_panel.update_headers(self.interaction_mode, y_label)
        
        # 3. Clear and Re-plot
        self.plot_item.clear()
        self.stats_markers.clear() # clear previous indicators if persisting
        
        # Re-add region and markers back onto the plot
        if getattr(self, 'stats_line', None) is not None:
            self.plot_item.addItem(self.stats_line)
        self.plot_item.addItem(self.stats_region)
        self.plot_item.addItem(self.stats_markers)
        if hasattr(self, 'stats_p10_line') and self.stats_p10_line:
            if self.stats_p10_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_p10_line)
            self.stats_p10_line.setZValue(90)
        if hasattr(self, 'stats_p90_line') and self.stats_p90_line:
            if self.stats_p90_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_p90_line)
            self.stats_p90_line.setZValue(90)
        
        self.plot_item.getAxis('left').setLabel(y_label)
        
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        pen = pg.mkPen('#0072BD', width=0.5)
        self.plot_item.plot(self.time_axis, data, pen=pen)
        
        # 4. Restore markers
        for m in self.markers_time: 
            m.setPen(pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)
            
        active_y = self.markers_y_dict.get(y_label, [])
        for m in active_y:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)
            
        active_y_endless = self.markers_y_endless_dict.get(y_label, [])
        for m in active_y_endless:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)

        for m in self.markers_time_endless:
            m.setPen(pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)
        
        # 5. Constraints
        t_start, t_end = self.time_axis[0], self.time_axis[-1]
        t_total = t_end - t_start
        t_pad = t_total * 0.01
        
        y_min_data, y_max_data = np.min(data), np.max(data)
        y_range_val = y_max_data - y_min_data
        if y_range_val == 0: y_range_val = 1.0 
        y_pad = y_range_val * 0.05
        
        # IMPORTANT: unset limits temporarily to allow restoring old zoom if it was outside data bounds
        self.view_box.setLimits(xMin=None, xMax=None, yMin=None, yMax=None)
        
        # 6. Restore Zooms
        if y_label in self.zoom_y_dict:
            y_r = self.zoom_y_dict[y_label]
            self.plot_item.setYRange(y_r[0], y_r[1], padding=0)
        else:
            # Fit Y to data if no cached zoom
            self.plot_item.setYRange(y_min_data - y_pad, y_max_data + y_pad, padding=0)

        if old_x_range is not None:
            # Always restore X zoom
            self.plot_item.setXRange(old_x_range[0], old_x_range[1], padding=0)
        else:
            # Initial fit X
            self.plot_item.setXRange(t_start, t_end, padding=0)

        # 7. Finalize limits
        self.view_box.setLimits(xMin=t_start - t_pad, xMax=t_end + t_pad,
                                yMin=y_min_data - y_pad, yMax=y_max_data + y_pad)
        
        if hasattr(self, 'stats_region') and self.stats_region.isVisible():
            self.update_statistics()

        # Explicitly update scrollbars
        self.update_scrollbars()

    def update_marker_info(self):
        # Always use the cached marker mode for displaying values in the table
        display_mode = self.interaction_mode
        if display_mode in ['ZOOM', 'MOVE', 'STATS']:
            display_mode = getattr(self.marker_panel, 'last_marker_mode', 'TIME')
            
        is_time = (display_mode in ['TIME', 'TIME_ENDLESS'])
        is_endless = 'ENDLESS' in display_mode
        
        if is_endless:
            active_markers = self.markers_time_endless if is_time else self.markers_y_endless_dict[self.y_label_text]
            self.marker_panel.update_endless_list(active_markers, display_mode)
            # Re-label just in case
            for i, m in enumerate(active_markers):
                if hasattr(m, 'label'): m.label.setFormat(f"M{i+1}")
            if self.interaction_mode not in ['ZOOM', 'MOVE', 'STATS']: return
        else:
            active_markers = self.markers_time if is_time else self.markers_y_dict[self.y_label_text]
        
        sorted_m = sorted(active_markers, key=lambda m: m.value())
        
        self.marker_panel.update_headers(display_mode, self.y_label_text)
        
        # Clear fields
        for widget in self.marker_panel.m_widgets:
            for k in widget: widget[k].blockSignals(True); widget[k].clear(); widget[k].blockSignals(False)
        for w in [self.marker_panel.delta_v1, self.marker_panel.delta_v2, self.marker_panel.delta_v3,
                  self.marker_panel.center_v1, self.marker_panel.center_v2, self.marker_panel.center_v3]:
            w.blockSignals(True); w.clear(); w.blockSignals(False)

        if not sorted_m: return

        # Update columns
        for i in range(2):
            if i < len(sorted_m):
                m_val = sorted_m[i].value()
                self.marker_panel.m_widgets[i]['v1'].blockSignals(True)
                self.marker_panel.m_widgets[i]['v2'].blockSignals(True)
                
                prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if is_time else int(self.settings_mgr.get("ui/label_precision", 6))
                self.marker_panel.m_widgets[i]['v1'].setText(f"{m_val:.{prec1}f}")
                
                if is_time:
                    abs_s = int(round(m_val * self.rate)) + 1
                    self.marker_panel.m_widgets[i]['v2'].setText(f"{abs_s}")
                    inv_val = (1.0 / m_val) if abs(m_val) > 1e-12 else float('inf')
                    if inv_val == float('inf'): self.marker_panel.m_widgets[i]['v3'].setText("∞")
                    else: self.marker_panel.m_widgets[i]['v3'].setText(f"{inv_val:.{prec1}f}")
                
                self.marker_panel.m_widgets[i]['v1'].blockSignals(False)
                self.marker_panel.m_widgets[i]['v2'].blockSignals(False)

        # Update Delta/Center
        if len(sorted_m) == 2:
            v1, v2 = sorted_m[0].value(), sorted_m[1].value()
            prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if is_time else int(self.settings_mgr.get("ui/label_precision", 6))
            
            self.marker_panel.delta_v1.blockSignals(True)
            self.marker_panel.center_v1.blockSignals(True)
            self.marker_panel.delta_v1.setText(f"{abs(v2-v1):.{prec1}f}")
            self.marker_panel.center_v1.setText(f"{(v1+v2)/2:.{prec1}f}")
            self.marker_panel.delta_v1.blockSignals(False)
            self.marker_panel.center_v1.blockSignals(False)
            
            if is_time:
                s1, s2 = int(round(v1 * self.rate)) + 1, int(round(v2 * self.rate)) + 1
                self.marker_panel.delta_v2.blockSignals(True)
                self.marker_panel.delta_v3.blockSignals(True)
                self.marker_panel.center_v2.blockSignals(True)
                self.marker_panel.center_v3.blockSignals(True)
                
                self.marker_panel.delta_v2.setText(f"{abs(s2-s1)+1}")
                dt = abs(v2 - v1)
                if dt > 1e-12: self.marker_panel.delta_v3.setText(f"{1.0/dt:.{prec1}f}")
                else: self.marker_panel.delta_v3.setText("∞")
                
                # Center sample
                cv = (v1+v2)/2
                self.marker_panel.center_v2.setText(f"{int(round(cv*self.rate))+1}")
                if abs(cv) > 1e-12: self.marker_panel.center_v3.setText(f"{1.0/cv:.{prec1}f}")
                else: self.marker_panel.center_v3.setText("∞")
                
                self.marker_panel.delta_v2.blockSignals(False)
                self.marker_panel.delta_v3.blockSignals(False)
                self.marker_panel.center_v2.blockSignals(False)
                self.marker_panel.center_v3.blockSignals(False)

        # Sync lock button availability (Keep locked if we are Zooming or Panning)
        if self.interaction_mode in ['ZOOM', 'MOVE', 'STATS']:
            pass
        elif not is_endless:
            m1_p, m2_p = (len(sorted_m) >= 1), (len(sorted_m) >= 2)
            self.marker_panel.set_locks_enabled(m1_p, m2_p)
            
        self.update_grid('TIME')
        self.update_grid('MAG')

    def refresh_theme(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        
        self.update_toolbar_style()
        self.refresh_plot_style()
        self.marker_panel.refresh_theme()
        self.update_button_tooltips()
        
        # Update scrollbars
        sb_style = get_scrollbar_stylesheet(p)
        self.x_scroll.setStyleSheet(sb_style)
        self.y_scroll.setStyleSheet(sb_style)
        
        # Re-plot to refresh curve and marker colors
        self._update_plot(self.current_plot_data, self.y_label_text)

    def update_toolbar_style(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.toolbar.setStyleSheet(f"""
            QFrame#td_toolbar {{ background-color: {p.bg_sidebar}; border-radius: 6px; border: 1px solid {p.border}; }}
            QPushButton {{ background-color: {p.bg_widget}; padding: 5px 15px; border-radius: 3px; color: {p.text_main}; }}
            QPushButton:hover {{ background-color: {p.border_light}; }}
            QPushButton:checked {{ background-color: {p.accent_dim}; color: {p.accent}; border: 1px solid {p.accent}; }}
        """)

    def refresh_plot_style(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.plot_widget.setBackground(p.plot_bg)
        
        from PyQt6.QtGui import QFont
        font = QFont()
        font.setPointSize(int(self.parent_window.settings_mgr.get("ui/axis_font_size", 10)))
        
        grid_enabled = bool(self.parent_window.settings_mgr.get("ui/grid_enabled", True))
        grid_alpha = int(self.parent_window.settings_mgr.get("ui/grid_alpha", 30)) / 100.0
        
        self.plot_item.getAxis('left').setTickFont(font)
        self.plot_item.getAxis('bottom').setTickFont(font)
        self.plot_widget.showGrid(x=grid_enabled, y=grid_enabled, alpha=grid_alpha)
        
        self.plot_item.getAxis('left').setPen(p.text_dim)
        self.plot_item.getAxis('bottom').setPen(p.text_dim)

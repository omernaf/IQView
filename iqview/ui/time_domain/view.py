import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

from ..analysis_view import BaseAnalysisView, AnalysisMarkerMixin, AnalysisStatsMixin
from .marker_panel import TimeDomainMarkerPanel
from .plots import TimeDomainPlotsMixin


class TimeDomainView(BaseAnalysisView, AnalysisMarkerMixin, AnalysisStatsMixin, TimeDomainPlotsMixin):
    """
    A detailed view of a signal segment in the time domain with interactive markers and statistics.
    """
    toolbar_id = "td_toolbar"
    default_marker_mode = "TIME"

    def __init__(self, samples, start_time, sample_rate, parent=None, parent_window=None):
        self.samples = samples
        self.start_time = start_time
        self.rate = sample_rate
        self.interaction_mode = 'TIME'
        self._first_plot = True

        super().__init__(parent=parent, parent_window=parent_window)

        self.init_markers()
        self.init_statistics()

        n_samples = len(samples)
        self.time_axis = start_time + np.arange(n_samples) / sample_rate
        self.current_plot_data = samples.real

        # Setup Marker Panel
        self.marker_panel = TimeDomainMarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.main_layout.insertWidget(0, self.marker_panel)

        # Setup Toolbar Modes
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
            "magnitude^2 [dB]": self.plot_magnitude_squared_db,
        }

        self.y_label_text = "Real"
        self.toolbar_layout.addWidget(QLabel("Plot Mode:"))
        self.toolbar_layout.addLayout(self.plot_buttons_layout)
        self.toolbar_layout.addStretch()

        self.main_layout.insertWidget(1, self.toolbar)
        self.main_layout.addWidget(self.grid_container)

        self.rebuild_plot_buttons()
        self.set_interaction_mode('TIME')

    # -------------------------------------------------------------------------
    # Mode & Button Management
    # -------------------------------------------------------------------------
    def rebuild_plot_buttons(self):
        for btn in self.plot_buttons:
            self.mode_group.removeButton(btn)
            self.plot_buttons_layout.removeWidget(btn)
            btn.deleteLater()
        self.plot_buttons.clear()

        active_plots = []
        if self.settings_mgr:
            active_plots = self.settings_mgr.get("core/time_plots", [])

        if not active_plots:
            active_plots = ["Real", "Imaginary", "magnitude", "magnitude [dB]"]

        for i, name in enumerate(active_plots):
            if name in self.available_modes:
                btn = QPushButton(name)
                btn.setCheckable(True)
                self.mode_group.addButton(btn, i)
                self.plot_buttons_layout.addWidget(btn)
                btn.clicked.connect(self.available_modes[name])
                self.plot_buttons.append(btn)
                if i == 0: btn.setChecked(True)

        if self.plot_buttons and not any(b.isChecked() for b in self.plot_buttons):
            self.plot_buttons[0].setChecked(True)
            self.available_modes[self.plot_buttons[0].text()]()
        elif any(b.isChecked() for b in self.plot_buttons):
            for b in self.plot_buttons:
                if b.isChecked():
                    self.available_modes[b.text()]()
                    break

    def set_interaction_mode(self, mode):
        self.interaction_mode = mode
        self.marker_panel.update_headers(mode, self.y_label_text)
        self.refresh_cursor()

        if mode == 'STATS':
            if len(self.stats_bounds) == 2:
                self.stats_region.show()
                self.stats_markers.show()
            elif len(self.stats_bounds) == 1 and self.stats_line:
                self.stats_line.show()
            self.update_statistics()
        else:
            if hasattr(self, 'stats_region'): self.stats_region.hide()
            if hasattr(self, 'stats_line') and self.stats_line: self.stats_line.hide()
            if hasattr(self, 'stats_markers'): self.stats_markers.hide()

        self.update_marker_info()

    # -------------------------------------------------------------------------
    # Keyboard Navigation
    # -------------------------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Control and not event.isAutoRepeat():
            self._prev_mode_before_ctrl = self.interaction_mode
            self.interaction_mode = 'ZOOM'
            self.refresh_cursor()
        elif event.key() == Qt.Key.Key_Shift and not event.isAutoRepeat():
            self._prev_mode_before_shift = self.interaction_mode
            self.interaction_mode = 'MOVE'
            self.refresh_cursor()
        elif event.matches(QKeySequence.StandardKey.Undo):
            self.undo_zoom()
        elif event.key() == Qt.Key.Key_R:
            self.reset_zoom()
        elif event.key() == Qt.Key.Key_X:
            self.reset_zoom_x()
        elif event.key() == Qt.Key.Key_Y:
            self.reset_zoom_y()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Control and not event.isAutoRepeat():
            if hasattr(self, '_prev_mode_before_ctrl'):
                self.interaction_mode = self._prev_mode_before_ctrl
                del self._prev_mode_before_ctrl
            else:
                self.interaction_mode = self.marker_panel.current_mode
            self.refresh_cursor()
        elif event.key() == Qt.Key.Key_Shift and not event.isAutoRepeat():
            if hasattr(self, '_prev_mode_before_shift'):
                self.interaction_mode = self._prev_mode_before_shift
                del self._prev_mode_before_shift
            else:
                self.interaction_mode = self.marker_panel.current_mode
            self.refresh_cursor()
        super().keyReleaseEvent(event)

    # -------------------------------------------------------------------------
    # Domain Formatting & Parsing Hooks
    # -------------------------------------------------------------------------
    def is_primary_mode(self, mode):
        return mode in ['TIME', 'TIME_ENDLESS', 'STATS']

    def _get_primary_bounds(self):
        return self.time_axis[0], self.time_axis[-1]

    def _format_marker_row(self, m_val, row_dict, is_primary):
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9 if is_primary else 6)) if self.settings_mgr else (9 if is_primary else 6)
        row_dict['v1'].setText(f"{m_val:.{prec1}f}")
        if is_primary:
            abs_s = int(round(m_val * self.rate)) + 1
            row_dict['v2'].setText(f"{abs_s}")
            inv_val = (1.0 / m_val) if abs(m_val) > 1e-12 else float('inf')
            row_dict['v3'].setText(f"{inv_val:.{prec1}f}" if inv_val != float('inf') else "∞")

    def _format_delta_center(self, v1, v2, is_primary):
        super()._format_delta_center(v1, v2, is_primary)
        if is_primary:
            prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if self.settings_mgr else 9
            s1 = int(round(v1 * self.rate)) + 1
            s2 = int(round(v2 * self.rate)) + 1

            self.marker_panel.delta_v2.blockSignals(True)
            self.marker_panel.delta_v3.blockSignals(True)
            self.marker_panel.center_v2.blockSignals(True)
            self.marker_panel.center_v3.blockSignals(True)

            self.marker_panel.delta_v2.setText(f"{abs(s2 - s1) + 1}")
            dt = abs(v2 - v1)
            self.marker_panel.delta_v3.setText(f"{1.0/dt:.{prec1}f}" if dt > 1e-12 else "∞")

            cv = (v1 + v2) / 2
            self.marker_panel.center_v2.setText(f"{int(round(cv * self.rate)) + 1}")
            self.marker_panel.center_v3.setText(f"{1.0/cv:.{prec1}f}" if abs(cv) > 1e-12 else "∞")

            self.marker_panel.delta_v2.blockSignals(False)
            self.marker_panel.delta_v3.blockSignals(False)
            self.marker_panel.center_v2.blockSignals(False)
            self.marker_panel.center_v3.blockSignals(False)

    def _format_stats_region_readouts(self, b1, b2):
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if self.settings_mgr else 9
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

        dv = abs(b2 - b1)
        cv = (b1 + b2) / 2
        self.marker_panel.st_delta_v1.blockSignals(True); self.marker_panel.st_delta_v1.setText(f"{dv:.{prec1}f}"); self.marker_panel.st_delta_v1.blockSignals(False)
        self.marker_panel.st_center_v1.blockSignals(True); self.marker_panel.st_center_v1.setText(f"{cv:.{prec1}f}"); self.marker_panel.st_center_v1.blockSignals(False)

        s1, s2 = int(round(b1 * self.rate)) + 1, int(round(b2 * self.rate)) + 1
        self.marker_panel.st_delta_v2.blockSignals(True); self.marker_panel.st_delta_v2.setText(f"{abs(s2 - s1) + 1}"); self.marker_panel.st_delta_v2.blockSignals(False)
        self.marker_panel.st_center_v2.blockSignals(True); self.marker_panel.st_center_v2.setText(f"{int(round(cv * self.rate)) + 1}"); self.marker_panel.st_center_v2.blockSignals(False)

        self.marker_panel.st_delta_v3.setText(f"{1.0/dv:.{prec1}f}" if dv > 1e-12 else "∞")
        self.marker_panel.st_center_v3.setText(f"{1.0/cv:.{prec1}f}" if abs(cv) > 1e-12 else "∞")

    def _parse_marker_value_by_unit(self, val, unit, is_primary, curr_min, curr_max):
        if is_primary:
            if unit in ('v2', 'sam'):
                return np.clip((val - 1.0) / self.rate, curr_min, curr_max)
            return np.clip(val, curr_min, curr_max)
        return np.clip(val, curr_min, curr_max)

    def _parse_delta_value_by_unit(self, val, unit, is_primary):
        if is_primary and unit in ('v2', 'sam'):
            return (val - 1.0) / self.rate
        return val

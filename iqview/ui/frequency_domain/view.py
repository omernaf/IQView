import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout, QComboBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

from ..analysis_view import BaseAnalysisView, AnalysisMarkerMixin, AnalysisStatsMixin
from .marker_panel import FrequencyDomainMarkerPanel
from .plots import FrequencyDomainPlotsMixin
from .filter_manager import FrequencyDomainFilterMixin


class FrequencyDomainView(BaseAnalysisView, AnalysisMarkerMixin, AnalysisStatsMixin, FrequencyDomainPlotsMixin, FrequencyDomainFilterMixin):
    """
    A detailed view of a signal segment in the frequency domain with interactive markers,
    pre-processing operators, Welch PSD, and BPF/BSF filter regions.
    """
    toolbar_id = "fd_toolbar"
    default_marker_mode = "FREQ"

    OPERATORS = [
        "Normal",
        "2nd Power",
        "4th Power",
        "Absolute Value",
        "FM Demod",
        "2nd Power FM",
        "Delay & Multiply",
    ]

    def __init__(self, samples, center_freq, sample_rate, parent=None, parent_window=None):
        self.samples = samples
        self.center_freq = center_freq
        self.rate = sample_rate
        self.interaction_mode = 'FREQ'
        self._current_plot_mode_key = 'magnitude'
        self._first_plot = True
        self.y_label_text = "magnitude"
        self.current_plot_data = np.array([])
        self.freq_axis = np.array([])

        super().__init__(parent=parent, parent_window=parent_window)

        self.init_markers()
        self.init_statistics()
        self.init_filter()

        # Marker panel
        self.marker_panel = FrequencyDomainMarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.marker_panel.filterModeChanged.connect(self.on_filter_mode_changed)
        self.main_layout.insertWidget(0, self.marker_panel)

        # Toolbar & Operator setup
        self.operator_combo = QComboBox()
        self.operator_combo.addItems(self.OPERATORS)
        self.operator_combo.setCurrentText("Normal")
        self.operator_combo.currentTextChanged.connect(self.on_operator_changed)

        raw_modes = {
            "magnitude": self.plot_magnitude,
            "magnitude [dB]": self.plot_magnitude_db,
            "magnitude^2": self.plot_magnitude_squared,
            "real": self.plot_real,
            "real [dB]": self.plot_real_db,
            "imag": self.plot_imag,
            "imag [dB]": self.plot_imag_db,
            "phase": self.plot_phase,
            "unwrapped phase": self.plot_unwrapped_phase,
            "power spectrum density (PSD)": self.plot_psd
        }

        def _track(key, fn):
            def wrapper(*args, **kwargs):
                self._current_plot_mode_key = key
                fn()
            return wrapper

        self.available_modes = {k: _track(k, fn) for k, fn in raw_modes.items()}

        self.toolbar_layout.addWidget(QLabel("Preprocessing:"))
        self.toolbar_layout.addWidget(self.operator_combo)
        self.toolbar_layout.addSpacing(10)
        self.toolbar_layout.addWidget(QLabel("Plot Mode:"))
        self.toolbar_layout.addLayout(self.plot_buttons_layout)
        self.toolbar_layout.addStretch()

        self.main_layout.insertWidget(1, self.toolbar)
        self.main_layout.addWidget(self.grid_container)

        self.compute_fft()
        self.rebuild_plot_buttons()
        self.set_interaction_mode('FREQ')

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
            if hasattr(self, 'filter_region'): self.filter_region.hide()
            if hasattr(self, 'filter_line') and self.filter_line: self.filter_line.hide()
            self.update_statistics()
        elif mode == 'FILTER':
            if len(self.filter_bounds) == 2:
                self.filter_region.show()
            elif len(self.filter_bounds) == 1 and self.filter_line:
                self.filter_line.show()
            if hasattr(self, 'stats_region'): self.stats_region.hide()
            if hasattr(self, 'stats_line') and self.stats_line: self.stats_line.hide()
            if hasattr(self, 'stats_markers'): self.stats_markers.hide()
        else:
            if hasattr(self, 'stats_region'): self.stats_region.hide()
            if hasattr(self, 'stats_line') and self.stats_line: self.stats_line.hide()
            if hasattr(self, 'stats_markers'): self.stats_markers.hide()
            if hasattr(self, 'filter_region'): self.filter_region.hide()
            if hasattr(self, 'filter_line') and self.filter_line: self.filter_line.hide()

        self.update_marker_info()

    # -------------------------------------------------------------------------
    # Frequency Index Conversion & Domain Hooks
    # -------------------------------------------------------------------------
    def freq_to_index(self, freq):
        if not hasattr(self, 'freq_axis') or len(self.freq_axis) == 0:
            return 0
        idx = int(np.argmin(np.abs(self.freq_axis - freq)))
        return idx + 1

    def is_primary_mode(self, mode):
        return mode in ['FREQ', 'FREQ_ENDLESS', 'FILTER', 'STATS']

    def _get_primary_bounds(self):
        return self.freq_axis[0], self.freq_axis[-1]

    def _format_marker_row(self, m_val, row_dict, is_primary):
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9 if is_primary else 6)) if self.settings_mgr else (9 if is_primary else 6)
        if 'v1' in row_dict:
            row_dict['v1'].setText(f"{m_val:.{prec1}f}")
        if is_primary and 'v2' in row_dict:
            bin_idx = self.freq_to_index(m_val)
            row_dict['v2'].setText(f"{bin_idx}")
        if is_primary and 'v3' in row_dict:
            rel_freq = m_val - self.center_freq
            row_dict['v3'].setText(f"{rel_freq:+.{prec1}f}")

    def _format_delta_center(self, v1, v2, is_primary):
        super()._format_delta_center(v1, v2, is_primary)
        if is_primary:
            prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if self.settings_mgr else 9
            b1 = self.freq_to_index(v1)
            b2 = self.freq_to_index(v2)

            if hasattr(self.marker_panel, 'delta_v2'):
                self.marker_panel.delta_v2.blockSignals(True)
                self.marker_panel.delta_v2.setText(f"{abs(b2 - b1) + 1}")
                self.marker_panel.delta_v2.blockSignals(False)

            if hasattr(self.marker_panel, 'delta_v3'):
                self.marker_panel.delta_v3.blockSignals(True)
                self.marker_panel.delta_v3.setText(f"{abs(v2 - v1):.{prec1}f}")
                self.marker_panel.delta_v3.blockSignals(False)

            cv = (v1 + v2) / 2
            if hasattr(self.marker_panel, 'center_v2'):
                self.marker_panel.center_v2.blockSignals(True)
                self.marker_panel.center_v2.setText(f"{self.freq_to_index(cv)}")
                self.marker_panel.center_v2.blockSignals(False)

            if hasattr(self.marker_panel, 'center_v3'):
                self.marker_panel.center_v3.blockSignals(True)
                self.marker_panel.center_v3.setText(f"{cv - self.center_freq:+.{prec1}f}")
                self.marker_panel.center_v3.blockSignals(False)

    def _format_stats_region_readouts(self, b1, b2):
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if self.settings_mgr else 9
        if hasattr(self.marker_panel, 'st_row_v1_lbl'):
            self.marker_panel.st_row_v1_lbl.setText("Region (Hz)")
        if hasattr(self.marker_panel, 'st_row_v2_lbl'):
            self.marker_panel.st_row_v2_lbl.setText("Index")
        if hasattr(self.marker_panel, 'st_row_v3_lbl'):
            self.marker_panel.st_row_v3_lbl.setText("Rel Freq (Hz)")

        for i, val in enumerate([b1, b2]):
            w = self.marker_panel.st_widgets[i]
            if 'v1' in w:
                w['v1'].blockSignals(True)
                w['v1'].setText(f"{val:.{prec1}f}")
                w['v1'].blockSignals(False)
            if 'v2' in w:
                bin_idx = self.freq_to_index(val)
                w['v2'].blockSignals(True)
                w['v2'].setText(f"{bin_idx}")
                w['v2'].blockSignals(False)
            if 'v3' in w:
                rel_f = val - self.center_freq
                w['v3'].blockSignals(True)
                w['v3'].setText(f"{rel_f:+.{prec1}f}")
                w['v3'].blockSignals(False)

        dv = abs(b2 - b1)
        cv = (b1 + b2) / 2
        if hasattr(self.marker_panel, 'st_delta_v1'):
            self.marker_panel.st_delta_v1.blockSignals(True)
            self.marker_panel.st_delta_v1.setText(f"{dv:.{prec1}f}")
            self.marker_panel.st_delta_v1.blockSignals(False)

        if hasattr(self.marker_panel, 'st_center_v1'):
            self.marker_panel.st_center_v1.blockSignals(True)
            self.marker_panel.st_center_v1.setText(f"{cv:.{prec1}f}")
            self.marker_panel.st_center_v1.blockSignals(False)

        bin1, bin2 = self.freq_to_index(b1), self.freq_to_index(b2)
        if hasattr(self.marker_panel, 'st_delta_v2'):
            self.marker_panel.st_delta_v2.blockSignals(True)
            self.marker_panel.st_delta_v2.setText(f"{abs(bin2 - bin1) + 1}")
            self.marker_panel.st_delta_v2.blockSignals(False)

        if hasattr(self.marker_panel, 'st_center_v2'):
            self.marker_panel.st_center_v2.blockSignals(True)
            self.marker_panel.st_center_v2.setText(f"{self.freq_to_index(cv)}")
            self.marker_panel.st_center_v2.blockSignals(False)

        if hasattr(self.marker_panel, 'st_delta_v3'):
            self.marker_panel.st_delta_v3.setText(f"{dv:.{prec1}f}")
        if hasattr(self.marker_panel, 'st_center_v3'):
            self.marker_panel.st_center_v3.setText(f"{cv - self.center_freq:+.{prec1}f}")

    def _parse_marker_value_by_unit(self, val, unit, is_primary, curr_min, curr_max):
        if is_primary:
            if unit in ('v2', 'bin') and hasattr(self, 'freq_axis') and len(self.freq_axis) > 0:
                bin_idx = int(np.clip(round(val) - 1, 0, len(self.freq_axis) - 1))
                return self.freq_axis[bin_idx]
            return np.clip(val, curr_min, curr_max)
        return np.clip(val, curr_min, curr_max)

    def _parse_delta_value_by_unit(self, val, unit, is_primary):
        if is_primary and unit in ('v2', 'bin') and hasattr(self, 'freq_axis') and len(self.freq_axis) > 1:
            rbw = abs(self.freq_axis[1] - self.freq_axis[0])
            return val * rbw
        return val

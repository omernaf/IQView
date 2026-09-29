from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QButtonGroup, QLabel, QStackedWidget, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from ..widgets import FormattedLineEdit


class RegionStatsWidget(QWidget):
    """
    Reusable Region Statistics widget containing the 'Definition' and 'Results'
    sub-tabs used in both Time Domain and Frequency Domain marker panels.
    """
    percentileToggled = pyqtSignal(bool)

    def __init__(
        self,
        controller,
        header_font: QFont = None,
        has_inv_row: bool = False,
        has_integrated: bool = False,
        is_freq: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.controller = controller
        self.has_inv_row = has_inv_row
        self.has_integrated = has_integrated
        self.is_freq = is_freq
        self.header_font = header_font or QFont("Segoe UI", 9, QFont.Weight.Bold)

        self.stats_main_layout = QVBoxLayout(self)
        self.stats_main_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_main_layout.setSpacing(4)

        # --- Statistics Tab Bar ---
        self.stats_tab_layout = QHBoxLayout()
        self.stats_tab_layout.setSpacing(10)
        self.stats_main_layout.addLayout(self.stats_tab_layout)

        self.btn_stats_def = QPushButton("Definition")
        self.btn_stats_res = QPushButton("Results")
        for btn in [self.btn_stats_def, self.btn_stats_res]:
            btn.setCheckable(True)
            btn.setObjectName("stats_tab_btn")
            btn.setFixedHeight(22)
            self.stats_tab_layout.addWidget(btn)

        self.stats_tab_group = QButtonGroup(self)
        self.stats_tab_group.addButton(self.btn_stats_def)
        self.stats_tab_group.addButton(self.btn_stats_res)
        self.stats_tab_group.setExclusive(True)
        self.btn_stats_res.setChecked(True)
        self.stats_tab_layout.addStretch()

        # --- Sub-Stacked Widget ---
        self.stats_sub_stack = QStackedWidget()
        self.stats_main_layout.addWidget(self.stats_sub_stack)

        # Sub-Page 1: Region Definition
        self.st_def_widget = QWidget()
        self.stats_sub_stack.addWidget(self.st_def_widget)
        self.st_layout = QGridLayout(self.st_def_widget)
        self.st_layout.setContentsMargins(0, 0, 0, 0)
        self.st_layout.setHorizontalSpacing(10)
        self.st_layout.setVerticalSpacing(4)

        # Region Definition Column Titles
        lbl_st_m1 = QLabel("Marker 1"); lbl_st_m1.setFont(self.header_font); lbl_st_m1.setAlignment(Qt.AlignmentFlag.AlignCenter); lbl_st_m1.setObjectName("header_label")
        lbl_st_m2 = QLabel("Marker 2"); lbl_st_m2.setFont(self.header_font); lbl_st_m2.setAlignment(Qt.AlignmentFlag.AlignCenter); lbl_st_m2.setObjectName("header_label")
        lbl_st_delta = QLabel("Delta (Δ)"); lbl_st_delta.setFont(self.header_font); lbl_st_delta.setAlignment(Qt.AlignmentFlag.AlignCenter); lbl_st_delta.setObjectName("header_label")
        lbl_st_center = QLabel("Center"); lbl_st_center.setFont(self.header_font); lbl_st_center.setAlignment(Qt.AlignmentFlag.AlignCenter); lbl_st_center.setObjectName("header_label")

        self.st_layout.addWidget(lbl_st_m1, 0, 1)
        self.st_layout.addWidget(lbl_st_m2, 0, 2)
        self.st_layout.addWidget(lbl_st_delta, 0, 3)
        self.st_layout.addWidget(lbl_st_center, 0, 4)

        self.st_widgets = []
        for i in range(2):
            v2 = FormattedLineEdit(); v2.setFixedWidth(110); v2.setAlignment(Qt.AlignmentFlag.AlignCenter); v2.setObjectName(f"st_m{i}_v2")
            v1 = FormattedLineEdit(); v1.setFixedWidth(110); v1.setAlignment(Qt.AlignmentFlag.AlignCenter); v1.setObjectName(f"st_m{i}_v1")
            for w in [v1, v2]:
                w.returnPressed.connect(self.controller.marker_edit_finished)
            if self.is_freq:
                self.st_layout.addWidget(v1, 1, i + 1)
                self.st_layout.addWidget(v2, 2, i + 1)
                self.st_widgets.append({'v1': v1, 'v2': v2})
            else:
                v3 = FormattedLineEdit(); v3.setFixedWidth(110); v3.setAlignment(Qt.AlignmentFlag.AlignCenter); v3.setObjectName(f"st_m{i}_v3"); v3.setReadOnly(True)
                self.st_layout.addWidget(v2, 1, i + 1)
                self.st_layout.addWidget(v1, 2, i + 1)
                self.st_layout.addWidget(v3, 3, i + 1)
                self.st_widgets.append({'v1': v1, 'v2': v2, 'v3': v3})

        self.st_delta_v2 = FormattedLineEdit(); self.st_delta_v2.setFixedWidth(110); self.st_delta_v2.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_delta_v2.setObjectName("st_delta_v2")
        self.st_delta_v1 = FormattedLineEdit(); self.st_delta_v1.setFixedWidth(110); self.st_delta_v1.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_delta_v1.setObjectName("st_delta_v1")
        self.st_center_v2 = FormattedLineEdit(); self.st_center_v2.setFixedWidth(110); self.st_center_v2.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_center_v2.setObjectName("st_center_v2")
        self.st_center_v1 = FormattedLineEdit(); self.st_center_v1.setFixedWidth(110); self.st_center_v1.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_center_v1.setObjectName("st_center_v1")

        if self.is_freq:
            self.st_delta_v2.setReadOnly(True)
            self.st_center_v2.setReadOnly(True)
            for w in [self.st_delta_v1, self.st_center_v1]:
                w.returnPressed.connect(self.controller.marker_edit_finished)
            self.st_layout.addWidget(self.st_delta_v1, 1, 3); self.st_layout.addWidget(self.st_delta_v2, 2, 3)
            self.st_layout.addWidget(self.st_center_v1, 1, 4); self.st_layout.addWidget(self.st_center_v2, 2, 4)

            self.st_row_v1_lbl = QLabel("Index"); self.st_row_v1_lbl.setObjectName("header_label")
            self.st_row_v2_lbl = QLabel("Region (Hz)"); self.st_row_v2_lbl.setObjectName("header_label")
            self.st_layout.addWidget(self.st_row_v1_lbl, 1, 0, Qt.AlignmentFlag.AlignRight)
            self.st_layout.addWidget(self.st_row_v2_lbl, 2, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.st_delta_v3 = FormattedLineEdit(); self.st_delta_v3.setFixedWidth(110); self.st_delta_v3.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_delta_v3.setObjectName("st_delta_v3"); self.st_delta_v3.setReadOnly(True)
            self.st_center_v3 = FormattedLineEdit(); self.st_center_v3.setFixedWidth(110); self.st_center_v3.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_center_v3.setObjectName("st_center_v3"); self.st_center_v3.setReadOnly(True)
            for w in [self.st_delta_v1, self.st_delta_v2, self.st_center_v1, self.st_center_v2]:
                w.returnPressed.connect(self.controller.marker_edit_finished)
            self.st_layout.addWidget(self.st_delta_v2, 1, 3); self.st_layout.addWidget(self.st_delta_v1, 2, 3); self.st_layout.addWidget(self.st_delta_v3, 3, 3)
            self.st_layout.addWidget(self.st_center_v2, 1, 4); self.st_layout.addWidget(self.st_center_v1, 2, 4); self.st_layout.addWidget(self.st_center_v3, 3, 4)

            self.st_row_v1_lbl = QLabel("Samples"); self.st_row_v1_lbl.setObjectName("header_label")
            self.st_row_v2_lbl = QLabel("Region (s)"); self.st_row_v2_lbl.setObjectName("header_label")
            self.st_row_v3_lbl = QLabel("1/T (Hz)"); self.st_row_v3_lbl.setObjectName("header_label")
            self.st_layout.addWidget(self.st_row_v1_lbl, 1, 0, Qt.AlignmentFlag.AlignRight)
            self.st_layout.addWidget(self.st_row_v2_lbl, 2, 0, Qt.AlignmentFlag.AlignRight)
            self.st_layout.addWidget(self.st_row_v3_lbl, 3, 0, Qt.AlignmentFlag.AlignRight)

        # Sub-Page 2: Measurement Results
        self.st_res_widget = QWidget()
        self.stats_sub_stack.addWidget(self.st_res_widget)
        self.res_layout = QGridLayout(self.st_res_widget)
        self.res_layout.setContentsMargins(0, 0, 0, 0)
        self.res_layout.setHorizontalSpacing(10)
        self.res_layout.setVerticalSpacing(4)

        lbl_max = QLabel("Maximum"); lbl_max.setFont(self.header_font); lbl_max.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_max.setStyleSheet("color: #888; text-transform: uppercase; font-size: 10px;")
        lbl_min = QLabel("Minimum"); lbl_min.setFont(self.header_font); lbl_min.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_min.setStyleSheet("color: #888; text-transform: uppercase; font-size: 10px;")
        self.res_layout.addWidget(lbl_max, 0, 1)
        self.res_layout.addWidget(lbl_min, 0, 2)

        default_unit = "dBFS" if self.is_freq else "dB"

        # Min / Max Table (Cols 0-2)
        self.st_res_lbl_val = QLabel(f"Value ({default_unit})"); self.st_res_lbl_val.setObjectName("header_label")
        self.st_res_lbl_idx = QLabel("Index"); self.st_res_lbl_idx.setObjectName("header_label")
        self.res_layout.addWidget(self.st_res_lbl_val, 1, 0, Qt.AlignmentFlag.AlignRight)
        self.res_layout.addWidget(self.st_res_lbl_idx, 2, 0, Qt.AlignmentFlag.AlignRight)

        self.stats_max_val = FormattedLineEdit(); self.stats_max_val.setFixedWidth(110); self.stats_max_val.setReadOnly(True); self.stats_max_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_min_val = FormattedLineEdit(); self.stats_min_val.setFixedWidth(110); self.stats_min_val.setReadOnly(True); self.stats_min_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_max_idx = FormattedLineEdit(); self.stats_max_idx.setFixedWidth(110); self.stats_max_idx.setReadOnly(True); self.stats_max_idx.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_min_idx = FormattedLineEdit(); self.stats_min_idx.setFixedWidth(110); self.stats_min_idx.setReadOnly(True); self.stats_min_idx.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.res_layout.addWidget(self.stats_max_val, 1, 1); self.res_layout.addWidget(self.stats_min_val, 1, 2)
        self.res_layout.addWidget(self.stats_max_idx, 2, 1); self.res_layout.addWidget(self.stats_min_idx, 2, 2)

        if self.is_freq:
            self.st_res_lbl_freq = QLabel("Freq (Hz)"); self.st_res_lbl_freq.setObjectName("header_label")
            self.res_layout.addWidget(self.st_res_lbl_freq, 3, 0, Qt.AlignmentFlag.AlignRight)
            self.stats_max_freq = FormattedLineEdit(); self.stats_max_freq.setFixedWidth(110); self.stats_max_freq.setReadOnly(True); self.stats_max_freq.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stats_min_freq = FormattedLineEdit(); self.stats_min_freq.setFixedWidth(110); self.stats_min_freq.setReadOnly(True); self.stats_min_freq.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.res_layout.addWidget(self.stats_max_freq, 3, 1); self.res_layout.addWidget(self.stats_min_freq, 3, 2)
        else:
            self.st_res_lbl_time = QLabel("Time (sec)"); self.st_res_lbl_time.setObjectName("header_label")
            self.res_layout.addWidget(self.st_res_lbl_time, 3, 0, Qt.AlignmentFlag.AlignRight)
            self.stats_max_time = FormattedLineEdit(); self.stats_max_time.setFixedWidth(110); self.stats_max_time.setReadOnly(True); self.stats_max_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stats_min_time = FormattedLineEdit(); self.stats_min_time.setFixedWidth(110); self.stats_min_time.setReadOnly(True); self.stats_min_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.res_layout.addWidget(self.stats_max_time, 3, 1); self.res_layout.addWidget(self.stats_min_time, 3, 2)

        # Mean / Median / Optional Integrated (Cols 3-4)
        self.st_res_lbl_mean = QLabel(f"Mean ({default_unit})"); self.st_res_lbl_mean.setObjectName("header_label")
        self.st_res_lbl_median = QLabel(f"Median ({default_unit})"); self.st_res_lbl_median.setObjectName("header_label")
        self.res_layout.addWidget(self.st_res_lbl_mean, 1, 3, Qt.AlignmentFlag.AlignRight)
        self.res_layout.addWidget(self.st_res_lbl_median, 2, 3, Qt.AlignmentFlag.AlignRight)

        self.stats_mean_val = FormattedLineEdit(); self.stats_mean_val.setFixedWidth(110); self.stats_mean_val.setReadOnly(True); self.stats_mean_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_median_val = FormattedLineEdit(); self.stats_median_val.setFixedWidth(110); self.stats_median_val.setReadOnly(True); self.stats_median_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.res_layout.addWidget(self.stats_mean_val, 1, 4)
        self.res_layout.addWidget(self.stats_median_val, 2, 4)

        if self.has_integrated:
            self.st_res_lbl_integrated = QLabel("Integrated (dB)"); self.st_res_lbl_integrated.setObjectName("header_label")
            self.res_layout.addWidget(self.st_res_lbl_integrated, 3, 3, Qt.AlignmentFlag.AlignRight)
            self.stats_total_power = FormattedLineEdit(); self.stats_total_power.setFixedWidth(110); self.stats_total_power.setReadOnly(True); self.stats_total_power.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.res_layout.addWidget(self.stats_total_power, 3, 4)

        # Percentiles (Cols 5-6)
        w_90 = QWidget()
        l_90 = QHBoxLayout(w_90)
        l_90.setContentsMargins(0, 0, 0, 0)
        l_90.setSpacing(4)
        l_90.addStretch()
        self.cb_p90 = QCheckBox()
        self.cb_p90.setChecked(True)
        self.cb_p90.setToolTip("Toggle 90th percentile indicator line (red)")
        self.st_res_lbl_90th = QLabel(f"90th % ({default_unit})"); self.st_res_lbl_90th.setObjectName("header_label")
        l_90.addWidget(self.cb_p90)
        l_90.addWidget(self.st_res_lbl_90th)

        w_10 = QWidget()
        l_10 = QHBoxLayout(w_10)
        l_10.setContentsMargins(0, 0, 0, 0)
        l_10.setSpacing(4)
        l_10.addStretch()
        self.cb_p10 = QCheckBox()
        self.cb_p10.setChecked(True)
        self.cb_p10.setToolTip("Toggle 10th percentile indicator line (green)")
        self.st_res_lbl_10th = QLabel(f"10th % ({default_unit})"); self.st_res_lbl_10th.setObjectName("header_label")
        l_10.addWidget(self.cb_p10)
        l_10.addWidget(self.st_res_lbl_10th)

        self.cb_p90.toggled.connect(self._on_percentile_toggled)
        self.cb_p10.toggled.connect(self._on_percentile_toggled)

        self.st_res_lbl_diff = QLabel("90-10 Diff (dB)"); self.st_res_lbl_diff.setObjectName("header_label")
        self.res_layout.addWidget(w_90, 1, 5, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.res_layout.addWidget(w_10, 2, 5, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.res_layout.addWidget(self.st_res_lbl_diff, 3, 5, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.stats_90th_val = FormattedLineEdit(); self.stats_90th_val.setFixedWidth(110); self.stats_90th_val.setReadOnly(True); self.stats_90th_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_10th_val = FormattedLineEdit(); self.stats_10th_val.setFixedWidth(110); self.stats_10th_val.setReadOnly(True); self.stats_10th_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_diff_val = FormattedLineEdit(); self.stats_diff_val.setFixedWidth(110); self.stats_diff_val.setReadOnly(True); self.stats_diff_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.res_layout.addWidget(self.stats_90th_val, 1, 6)
        self.res_layout.addWidget(self.stats_10th_val, 2, 6)
        self.res_layout.addWidget(self.stats_diff_val, 3, 6)

        self.stats_sub_stack.setCurrentIndex(1)

        # Connect internal tab switching
        self.btn_stats_def.clicked.connect(lambda: self.stats_sub_stack.setCurrentIndex(0))
        self.btn_stats_res.clicked.connect(lambda: self.stats_sub_stack.setCurrentIndex(1))

        for w in [self.btn_stats_def, self.btn_stats_res, self.cb_p90, self.cb_p10]:
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _on_percentile_toggled(self, checked=False):
        self.percentileToggled.emit(checked)
        if hasattr(self.controller, 'update_statistics'):
            self.controller.update_statistics()

    def clear(self):
        """Clear all text fields in the Definition and Results sub-tabs."""
        for widget in self.st_widgets:
            for k in widget:
                widget[k].blockSignals(True)
                widget[k].clear()
                widget[k].blockSignals(False)

        fields = [
            self.st_delta_v1, self.st_delta_v2,
            self.st_center_v1, self.st_center_v2,
            self.stats_max_val, self.stats_min_val,
            self.stats_max_idx, self.stats_min_idx,
            self.stats_mean_val, self.stats_median_val,
            self.stats_90th_val, self.stats_10th_val, self.stats_diff_val,
        ]
        if hasattr(self, 'st_delta_v3'):
            fields.extend([self.st_delta_v3, self.st_center_v3])
        if hasattr(self, 'stats_max_time'):
            fields.extend([self.stats_max_time, self.stats_min_time])
        if hasattr(self, 'stats_max_freq'):
            fields.extend([self.stats_max_freq, self.stats_min_freq])
        if hasattr(self, 'stats_total_power'):
            fields.append(self.stats_total_power)

        for w in fields:
            w.blockSignals(True)
            w.clear()
            w.blockSignals(False)

    def bind_aliases_to_panel(self, panel):
        """
        Bind all child widget attributes onto `panel` for 100% backward compatibility
        with existing view code that accesses `panel.stats_max_val`, `panel.st_widgets`, etc.
        """
        attrs = [
            'stats_main_layout', 'stats_tab_layout', 'btn_stats_def', 'btn_stats_res',
            'stats_tab_group', 'stats_sub_stack', 'st_def_widget', 'st_layout',
            'st_widgets', 'st_delta_v1', 'st_delta_v2', 'st_center_v1', 'st_center_v2',
            'st_row_v1_lbl', 'st_row_v2_lbl', 'st_res_widget', 'res_layout',
            'st_res_lbl_val', 'st_res_lbl_idx', 'stats_max_val', 'stats_min_val',
            'stats_max_idx', 'stats_min_idx', 'st_res_lbl_mean', 'st_res_lbl_median',
            'stats_mean_val', 'stats_median_val', 'cb_p90', 'cb_p10',
            'st_res_lbl_90th', 'st_res_lbl_10th', 'st_res_lbl_diff',
            'stats_90th_val', 'stats_10th_val', 'stats_diff_val'
        ]
        for optional_attr in [
            'st_delta_v3', 'st_center_v3', 'st_row_v3_lbl',
            'st_res_lbl_time', 'stats_max_time', 'stats_min_time',
            'st_res_lbl_freq', 'stats_max_freq', 'stats_min_freq',
            'st_res_lbl_integrated', 'stats_total_power'
        ]:
            if hasattr(self, optional_attr):
                attrs.append(optional_attr)

        for attr in attrs:
            setattr(panel, attr, getattr(self, attr))

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QCheckBox
from PyQt6.QtCore import Qt, pyqtSignal
from ..widgets import format_tooltip_with_keybind
from ..base_1d import Base1DMarkerPanel


class FrequencyDomainMarkerPanel(Base1DMarkerPanel):
    filterModeChanged = pyqtSignal(str)  # 'bpf', 'bsf', or '' (disabled)

    def __init__(self, controller):
        super().__init__(
            controller,
            primary_mode='FREQ',
            fixed_height=140,
            row_v1_default="Index",
            row_v2_default="Frequency (Hz)",
            row_v3_default=None,
            delta_v2_readonly=True,
            has_filter_mode=True,
            stats_has_inv_row=False,
            stats_has_integrated=True,
            stats_is_freq=True,
        )

    def _setup_extra_fixed_grid(self):
        # --- Filter BPF/BSF checkboxes (shown only in FILTER mode) ---
        self.filter_container = QWidget()
        _fl = QVBoxLayout(self.filter_container)
        _fl.setContentsMargins(0, 0, 0, 0)
        _fl.setSpacing(2)
        self.cb_bpf = QCheckBox("BPF")
        self.cb_bsf = QCheckBox("BSF")
        self.cb_bpf.setToolTip("Enable Band-Pass Filter")
        self.cb_bsf.setToolTip("Enable Band-Stop Filter")
        for cb in [self.cb_bpf, self.cb_bsf]:
            cb.setEnabled(False)
            cb.clicked.connect(self._on_filter_clicked)
            _fl.addWidget(cb)
        self.filter_container.setFixedWidth(80)
        self.filter_container.setVisible(False)
        self.grid.addWidget(self.filter_container, 1, 5, 2, 1)

    def _get_extra_nofocus_widgets(self):
        return [self.cb_bpf, self.cb_bsf]

    def update_headers(self, mode, y_axis_label="Magnitude"):
        self.row_v1_label.blockSignals(True)
        self.row_v2_label.blockSignals(True)

        display_mode = self._switch_stacked_page(
            mode, ['FREQ', 'MAG', 'FREQ_ENDLESS', 'MAG_ENDLESS', 'STATS', 'FILTER']
        )

        if display_mode in ['FREQ', 'FREQ_ENDLESS', 'FILTER']:
            self.row_v1_label.setText("Index")
            self.row_v2_label.setText("Frequency (Hz)")
            self.row_v1_label.show()
            self.row_v2_label.show()

            # Reset grid positions
            self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row_v2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.m_widgets[i]['v2'], 1, i + 1)
                self.grid.addWidget(self.m_widgets[i]['v1'], 2, i + 1)
                self.m_widgets[i]['v1'].show()
                self.m_widgets[i]['v2'].show()
            self.grid.addWidget(self.delta_v2, 1, 3); self.delta_v2.show()
            self.grid.addWidget(self.delta_v1, 2, 3); self.delta_v1.show()
            self.grid.addWidget(self.center_v2, 1, 4); self.center_v2.show()
            self.grid.addWidget(self.center_v1, 2, 4); self.center_v1.show()
        else:  # MAG
            display_label = y_axis_label
            if "[" in y_axis_label and "]" in y_axis_label:
                display_label = y_axis_label.replace("[", "(").replace("]", ")")
            if not display_label.startswith("PSD"):
                display_label = display_label.capitalize()
            self.row_v1_label.setText(display_label)
            self.row_v1_label.show()
            self.row_v2_label.hide()
            self.filter_container.hide()

            # Move Magnitude widgets to Row 1
            self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.m_widgets[i]['v1'], 1, i + 1)
                self.m_widgets[i]['v1'].show()
                self.m_widgets[i]['v2'].hide()
            self.grid.addWidget(self.delta_v1, 1, 3); self.delta_v1.show()
            self.grid.addWidget(self.center_v1, 1, 4); self.center_v1.show()
            self.delta_v2.hide()
            self.center_v2.hide()

        self.row_v1_label.blockSignals(False)
        self.row_v2_label.blockSignals(False)

        self._sync_lock_buttons_for_mode(display_mode)

    def update_endless_list(self, markers, mode):
        is_freq = 'FREQ' in mode
        unit_main = "Hz" if is_freq else self.controller.y_label_text
        if not is_freq:
            if "[" in unit_main and "]" in unit_main:
                unit_main = unit_main.split("[")[-1].rstrip("]")
            elif not unit_main.startswith("PSD"):
                unit_main = unit_main.capitalize()
        unit_sub = "Bin" if is_freq else ""
        self.endless_widget.update_markers(
            markers=markers,
            mode=mode,
            is_primary_axis=is_freq,
            unit_main=unit_main,
            unit_sub=unit_sub,
            pos_suffix="hz",
            sub_suffix="bin",
            prec=(3 if is_freq else 6),
            sub_val_fn=lambda val: self.controller.freq_to_index(val),
            on_header_created=self.refresh_theme,
        )

    def _on_filter_clicked(self):
        """Enforce BPF/BSF mutual exclusion and emit filterModeChanged."""
        sender = self.sender()
        if sender == self.cb_bpf and self.cb_bpf.isChecked():
            self.cb_bsf.setChecked(False)
        elif sender == self.cb_bsf and self.cb_bsf.isChecked():
            self.cb_bpf.setChecked(False)
        mode = ''
        if self.cb_bpf.isChecked():
            mode = 'bpf'
        elif self.cb_bsf.isChecked():
            mode = 'bsf'
        self.filterModeChanged.emit(mode)

    def set_filter_checkboxes_enabled(self, enabled):
        """Enable/disable BPF/BSF checkboxes (enabled only when both bounds placed)."""
        self.cb_bpf.setEnabled(enabled)
        self.cb_bsf.setEnabled(enabled)
        if not enabled:
            self.cb_bpf.setChecked(False)
            self.cb_bsf.setChecked(False)

    def _update_domain_tooltips(self, s):
        self.btn_marker_freq.setToolTip(format_tooltip_with_keybind(
            "Frequency Markers (Double-click to clear)", s.get("keybinds/freq_markers", "F")
        ))
        self.btn_marker_freq_endless.setToolTip(format_tooltip_with_keybind(
            "Endless Frequency Markers (Double-click to clear)", s.get("keybinds/freq_endless_markers", "G")
        ))
        self.btn_bpf.setToolTip(format_tooltip_with_keybind(
            "BPF / BSF Filter Mode (Double-click to clear)", s.get("keybinds/filter_mode", "B")
        ))
        self.cb_bpf.setToolTip(format_tooltip_with_keybind(
            "Enable Band-Pass Filter", s.get("keybinds/toggle_bpf", "[")
        ))
        self.cb_bsf.setToolTip(format_tooltip_with_keybind(
            "Enable Band-Stop Filter", s.get("keybinds/toggle_bsf", "]")
        ))

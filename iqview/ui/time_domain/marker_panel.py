from PyQt6.QtCore import Qt
from ..widgets import format_tooltip_with_keybind
from ..base_1d import Base1DMarkerPanel


class TimeDomainMarkerPanel(Base1DMarkerPanel):
    def __init__(self, controller):
        super().__init__(
            controller,
            primary_mode='TIME',
            fixed_height=160,
            row_v1_default="Samples",
            row_v2_default="Time (sec)",
            row_v3_default="1/T (Hz)",
            delta_v2_readonly=False,
            has_filter_mode=False,
            stats_has_inv_row=True,
            stats_has_integrated=False,
            stats_is_freq=False,
        )

    def update_headers(self, mode, y_axis_label="Magnitude"):
        self.row_v1_label.blockSignals(True)
        self.row_v2_label.blockSignals(True)

        display_mode = self._switch_stacked_page(
            mode, ['TIME', 'MAG', 'TIME_ENDLESS', 'MAG_ENDLESS', 'STATS']
        )

        if display_mode in ['TIME', 'TIME_ENDLESS']:
            show_inv = self.controller.settings_mgr.get("ui/show_inv_time", False)
            self.row_v1_label.setText("Samples")
            self.row_v2_label.setText("Time (sec)")
            self.row_v3_label.setText("1/T (Hz)")
            self.row_v1_label.show()
            self.row_v2_label.show()
            self.row_v3_label.setVisible(show_inv)

            # Row mapping: v2 (Samples) on top, v1 (Time) on Row 2
            self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row_v2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row_v3_label, 3, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.m_widgets[i]['v2'], 1, i + 1)
                self.grid.addWidget(self.m_widgets[i]['v1'], 2, i + 1)
                self.grid.addWidget(self.m_widgets[i]['v3'], 3, i + 1)
                self.m_widgets[i]['v1'].show()
                self.m_widgets[i]['v2'].show()
                self.m_widgets[i]['v3'].setVisible(show_inv)
            self.grid.addWidget(self.delta_v2, 1, 3); self.delta_v2.show()
            self.grid.addWidget(self.delta_v1, 2, 3); self.delta_v1.show()
            self.grid.addWidget(self.delta_v3, 3, 3); self.delta_v3.setVisible(show_inv)
            self.grid.addWidget(self.center_v2, 1, 4); self.center_v2.show()
            self.grid.addWidget(self.center_v1, 2, 4); self.center_v1.show()
            self.grid.addWidget(self.center_v3, 3, 4); self.center_v3.setVisible(show_inv)
        else:  # MAG
            self.row_v1_label.setText(y_axis_label)
            self.row_v1_label.show()
            self.row_v2_label.hide()
            self.row_v3_label.hide()

            # Move Magnitude widgets (v1) to Row 1
            self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.m_widgets[i]['v1'], 1, i + 1)  # v1 is Mag
                self.m_widgets[i]['v1'].show()
                self.m_widgets[i]['v2'].hide()
                self.m_widgets[i]['v3'].hide()
            self.grid.addWidget(self.delta_v1, 1, 3); self.delta_v1.show()
            self.grid.addWidget(self.center_v1, 1, 4); self.center_v1.show()
            self.delta_v2.hide(); self.delta_v3.hide()
            self.center_v2.hide(); self.center_v3.hide()

        self.row_v1_label.blockSignals(False)
        self.row_v2_label.blockSignals(False)

        self._sync_lock_buttons_for_mode(display_mode)

    def update_endless_list(self, markers, mode):
        """Update the scroll area with rows for each endless marker, reusing widgets where possible."""
        is_time = 'TIME' in mode
        unit_main = "sec" if is_time else self.controller.y_label_text
        unit_sub = "Sam" if is_time else ""
        self.endless_widget.update_markers(
            markers=markers,
            mode=mode,
            is_primary_axis=is_time,
            unit_main=unit_main,
            unit_sub=unit_sub,
            pos_suffix="sec",
            sub_suffix="sam",
            prec=(9 if is_time else 6),
            sub_val_fn=lambda val: int(round(val * self.controller.rate)) + 1,
            on_header_created=self.refresh_theme,
        )

    def _update_domain_tooltips(self, s):
        self.btn_marker_time.setToolTip(format_tooltip_with_keybind(
            "Time Markers (Double-click to clear)", s.get("keybinds/time_markers", "T")
        ))
        self.btn_marker_time_endless.setToolTip(format_tooltip_with_keybind(
            "Endless Time Markers (Double-click to clear)", s.get("keybinds/time_endless_markers", "E")
        ))

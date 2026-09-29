from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QPushButton
)
from ..widgets import FormattedLineEdit


class EndlessMarkerListWidget(QWidget):
    """
    Reusable scrollable Endless Marker table widget with row recycling,
    used in both Time Domain and Frequency Domain marker panels.
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._endless_rows = []
        self._header_widget = None

        self.endless_layout = QVBoxLayout(self)
        self.endless_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(2)
        self.scroll_layout.addStretch()
        self.scroll.setWidget(self.scroll_content)
        self.endless_layout.addWidget(self.scroll)

    def bind_aliases_to_panel(self, panel):
        """Bind scroll attributes onto `panel` for backward compatibility."""
        panel.endless_layout = self.endless_layout
        panel.scroll = self.scroll
        panel.scroll_content = self.scroll_content
        panel.scroll_layout = self.scroll_layout

    def update_markers(
        self,
        markers,
        mode: str,
        is_primary_axis: bool,
        unit_main: str,
        unit_sub: str,
        pos_suffix: str,
        sub_suffix: str,
        prec: int,
        sub_val_fn,
        on_header_created=None,
    ):
        """Update the scroll area with rows for each endless marker, reusing widgets."""
        # 1. Initialize header widget if needed
        if self._header_widget is None:
            self._header_widget = QWidget()
            h_layout = QHBoxLayout(self._header_widget)
            h_layout.setContentsMargins(5, 2, 5, 2)
            h_layout.setSpacing(10)

            l_id = QLabel("ID"); l_id.setFixedWidth(30); l_id.setObjectName("header_label")
            l_sub = QLabel(unit_sub); l_sub.setObjectName("header_label")
            l_sub.setProperty("role", "sub_header")
            l_main = QLabel(f"Pos ({unit_main})"); l_main.setObjectName("header_label")
            l_main.setProperty("role", "pos_header")
            l_del = QLabel(""); l_del.setFixedWidth(24)

            h_layout.addWidget(l_id)
            h_layout.addWidget(l_sub, 1)
            h_layout.addWidget(l_main, 1)
            h_layout.addWidget(l_del)
            self.scroll_layout.insertWidget(0, self._header_widget)
            if on_header_created is not None:
                on_header_created()

        # 2. Update header labels & sub-header visibility
        for lbl in self._header_widget.findChildren(QLabel, "header_label"):
            if lbl.property("role") == "pos_header":
                lbl.setText(f"Pos ({unit_main})")
            elif lbl.property("role") == "sub_header":
                lbl.setText(unit_sub)
                lbl.setVisible(is_primary_axis)

        # 3. Synchronize row count
        while len(self._endless_rows) > len(markers):
            row_data = self._endless_rows.pop()
            row_data['widget'].deleteLater()

        while len(self._endless_rows) < len(markers):
            i = len(self._endless_rows)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 0, 5, 0)
            row_layout.setSpacing(10)

            lbl_id = QLabel(f"M{i+1}")
            lbl_id.setFixedWidth(30)
            lbl_id.setStyleSheet("color: #ff6400; font-weight: bold;")

            edit_pos = FormattedLineEdit()
            edit_pos.setFixedHeight(24)
            edit_pos.returnPressed.connect(self.controller.marker_edit_finished)

            edit_sub = FormattedLineEdit()
            edit_sub.setFixedHeight(24)
            edit_sub.returnPressed.connect(self.controller.marker_edit_finished)

            btn_del = QPushButton("×")
            btn_del.setFixedWidth(24); btn_del.setFixedHeight(24)
            btn_del.setToolTip("Remove marker")
            btn_del.setStyleSheet("""
                QPushButton { background: none; color: #ff4444; font-weight: bold; font-size: 16px; border-radius: 12px; }
                QPushButton:hover { background: rgba(255, 68, 68, 0.2); }
            """)

            row_layout.addWidget(lbl_id)
            row_layout.addWidget(edit_sub, 1)
            row_layout.addWidget(edit_pos, 1)
            row_layout.addWidget(btn_del)

            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, row)

            self._endless_rows.append({
                'widget': row,
                'lbl_id': lbl_id,
                'edit_pos': edit_pos,
                'edit_sub': edit_sub,
                'btn_del': btn_del
            })

        # 4. Populate row data
        for i, m in enumerate(markers):
            row_data = self._endless_rows[i]
            val = m.value()

            row_data['lbl_id'].setText(f"M{i+1}")

            row_data['edit_pos'].blockSignals(True)
            row_data['edit_pos'].setObjectName(f"em_{i}_{pos_suffix}")
            row_data['edit_pos'].setText(f"{val:.{prec}f}")
            row_data['edit_pos'].blockSignals(False)

            if is_primary_axis:
                sub_val = sub_val_fn(val)
                row_data['edit_sub'].show()
                row_data['edit_sub'].blockSignals(True)
                row_data['edit_sub'].setObjectName(f"em_{i}_{sub_suffix}")
                row_data['edit_sub'].setText(f"{sub_val}")
                row_data['edit_sub'].blockSignals(False)
            else:
                row_data['edit_sub'].hide()

            try:
                row_data['btn_del'].clicked.disconnect()
            except Exception:
                pass
            row_data['btn_del'].clicked.connect(lambda _, m=m: self.controller.remove_marker_item(m, mode))

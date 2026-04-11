"""iqview/ui/overlay_panel.py

Collapsible panel that lists all current overlays.
It sits below the MarkerPanel in the spectrogram layout.

Columns:  Shape | Display tag | Source | 👁 | ✎ | 🗑
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .overlay import Overlay, OverlayShape

if TYPE_CHECKING:
    from .main_window import SpectrogramWindow  # noqa: F401

# Shape → compact symbol for the table
_SHAPE_SYMBOL = {
    OverlayShape.RECT:    "■",
    OverlayShape.POLYGON: "⬠",
    OverlayShape.CIRCLE:  "●",
    OverlayShape.ELLIPSE: "⬤",
    OverlayShape.LINE:    "│",
    OverlayShape.HLINE:   "─",
}


class OverlayPanel(QWidget):
    """
    Compact, collapsible overlay list aligned with the rest of the IQView
    control strip.

    Usage
    -----
    panel = OverlayPanel(parent_window)
    spec_v_layout.addWidget(panel)

    Call panel.refresh() whenever the overlay list changes.
    """

    def __init__(self, parent_window: "SpectrogramWindow") -> None:
        super().__init__()
        self.parent_window = parent_window
        self._expanded = False

        self.setObjectName("overlayPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Minimum)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 2)
        root.setSpacing(2)

        # ── Header row ──────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        self.btn_toggle = QPushButton("▶  Overlays (0)")
        self.btn_toggle.setFlat(True)
        self.btn_toggle.setStyleSheet(
            "QPushButton { text-align: left; font-weight: bold; "
            "padding: 2px 4px; border: none; }"
        )
        self.btn_toggle.clicked.connect(self._toggle)
        header.addWidget(self.btn_toggle, 1)

        self.btn_add = QPushButton("＋ Add")
        self.btn_add.setFixedHeight(22)
        self.btn_add.setToolTip("Add a new overlay")
        self.btn_add.clicked.connect(self._on_add)
        header.addWidget(self.btn_add)

        self.btn_clear = QPushButton("Clear all")
        self.btn_clear.setFixedHeight(22)
        self.btn_clear.setToolTip("Remove all user-created overlays")
        self.btn_clear.clicked.connect(self._on_clear_all)
        header.addWidget(self.btn_clear)

        root.addLayout(header)

        # ── Table (hidden by default) ────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Shape", "Display", "Source", "👁", "✎", "🗑"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)

        # Column sizing
        hdr = self.table.horizontalHeader()
        from PyQt6.QtWidgets import QHeaderView
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setFixedHeight(120)
        self.table.hide()
        root.addWidget(self.table)

        self.refresh()

    # ------------------------------------------------------------------
    # Toggle expand/collapse
    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self.table.setVisible(self._expanded)
        self._update_header_text()
        # Let the layout recompute
        self.updateGeometry()
        if self.parentWidget():
            self.parentWidget().updateGeometry()

    def _update_header_text(self) -> None:
        n = len(getattr(self.parent_window, 'overlays', []))
        arrow = "▼" if self._expanded else "▶"
        self.btn_toggle.setText(f"{arrow}  Overlays ({n})")

    # ------------------------------------------------------------------
    # Public refresh — call whenever the overlay list changes
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-populate the table from the current overlay list."""
        self._update_header_text()

        overlays = getattr(self.parent_window, 'overlays', [])

        self.table.setRowCount(0)  # clear without triggering signals
        self.table.setRowCount(len(overlays))

        for row, overlay in enumerate(overlays):
            self._populate_row(row, overlay)

        self.table.resizeRowsToContents()

    def _populate_row(self, row: int, overlay: Overlay) -> None:
        # ── Col 0: Shape symbol + colour swatch ────────────────────────
        symbol = _SHAPE_SYMBOL.get(overlay.shape, "?")
        shape_item = QTableWidgetItem(f"{symbol} {overlay.shape.value}")
        shape_item.setForeground(QColor(overlay.border_color or overlay.color))
        shape_item.setFlags(shape_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, shape_item)

        # ── Col 1: Display string ───────────────────────────────────────
        tag_item = QTableWidgetItem(overlay.display_str or "(no tag)")
        tag_item.setFlags(tag_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        tag_item.setToolTip(overlay.hover_str or "")
        self.table.setItem(row, 1, tag_item)

        # ── Col 2: Source ───────────────────────────────────────────────
        src_item = QTableWidgetItem(overlay.source)
        src_item.setFlags(src_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 2, src_item)

        # ── Col 3: Visibility toggle ────────────────────────────────────
        btn_vis = QPushButton("👁" if overlay.visible else "○")
        btn_vis.setFixedSize(28, 22)
        btn_vis.setToolTip("Toggle visibility")
        oid = overlay.id
        btn_vis.clicked.connect(lambda _=False, o=oid: self._on_toggle_vis(o))
        self.table.setCellWidget(row, 3, btn_vis)

        # ── Col 4: Edit ─────────────────────────────────────────────────
        btn_edit = QPushButton("✎")
        btn_edit.setFixedSize(28, 22)
        btn_edit.setToolTip("Edit overlay")
        btn_edit.clicked.connect(lambda _=False, o=oid: self._on_edit(o))
        self.table.setCellWidget(row, 4, btn_edit)

        # ── Col 5: Delete ───────────────────────────────────────────────
        btn_del = QPushButton("🗑")
        btn_del.setFixedSize(28, 22)
        btn_del.setToolTip("Delete overlay")
        btn_del.clicked.connect(lambda _=False, o=oid: self._on_delete(o))
        self.table.setCellWidget(row, 5, btn_del)

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        from .overlay_dialog import OverlayDialog
        dlg = OverlayDialog(parent=self, parent_window=self.parent_window)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_overlay = dlg.get_overlay()
            self.parent_window.add_overlay(new_overlay)

    def _on_toggle_vis(self, overlay_id: str) -> None:
        overlay = self.parent_window._get_overlay_by_id(overlay_id)
        if overlay is None:
            return
        self.parent_window.update_overlay(overlay_id, visible=not overlay.visible)
        self.refresh()

    def _on_edit(self, overlay_id: str) -> None:
        overlay = self.parent_window._get_overlay_by_id(overlay_id)
        if overlay is None:
            return

        from .overlay_dialog import OverlayDialog
        dlg = OverlayDialog(
            parent=self,
            parent_window=self.parent_window,
            overlay=overlay,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_overlay()
            # Push every field into the live overlay and re-sync
            self.parent_window.update_overlay(
                overlay_id,
                shape=updated.shape,
                points=updated.points,
                center=updated.center,
                radii=updated.radii,
                color=updated.color,
                alpha=updated.alpha,
                border_width=updated.border_width,
                border_color=updated.border_color,
                border_style=updated.border_style,
                display_str=updated.display_str,
                hover_str=updated.hover_str,
                tag_pos=updated.tag_pos,
                visible=updated.visible,
                z_order=updated.z_order,
                source=updated.source,
            )

    def _on_delete(self, overlay_id: str) -> None:
        self.parent_window.remove_overlay(overlay_id)
        self.refresh()

    def _on_clear_all(self) -> None:
        # Only clear user overlays from this panel
        self.parent_window.clear_overlays(source='user')
        self.refresh()

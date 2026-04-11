"""iqview/ui/overlay_dialog.py

Dialog for creating or editing a single Overlay.

Sections
--------
1. Shape selector (QComboBox)
2. Geometry editor   — stacked widget, one pane per shape
3. Style editor      — fill colour, alpha, border
4. Annotation editor — display_str, hover_str, tag_pos
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .overlay import Overlay, OverlayShape, SHAPE_LABELS, TAG_POSITIONS


# Reverse map: OverlayShape → human label
_SHAPE_TO_LABEL = {v: k for k, v in SHAPE_LABELS.items()}

_BIG = 1e15   # "infinite" spinbox limit


class OverlayDialog(QDialog):
    """
    Modal dialog for creating / editing an Overlay.

    Parameters
    ----------
    parent_window : SpectrogramWindow
        Used to read current view range for sensible geometry defaults.
    overlay       : Overlay | None
        If provided, the dialog opens pre-filled (edit mode).
        If None, a fresh overlay is initialised with view-range defaults.
    """

    def __init__(self, parent=None, parent_window=None, overlay: Optional[Overlay] = None):
        super().__init__(parent)
        self.parent_window = parent_window
        self._editing = overlay is not None
        self._overlay = overlay if overlay is not None else Overlay()

        self.setWindowTitle("Edit Overlay" if self._editing else "Add Overlay")
        self.setMinimumWidth(420)
        self.setModal(True)

        self._build_ui()
        self._populate_from_overlay(self._overlay)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── 1. Shape selector ──────────────────────────────────────────
        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel("Shape:"))
        self.cb_shape = QComboBox()
        for label in SHAPE_LABELS:
            self.cb_shape.addItem(label)
        shape_row.addWidget(self.cb_shape, 1)
        root.addLayout(shape_row)

        # ── 2. Geometry ────────────────────────────────────────────────
        geo_grp = QGroupBox("Geometry")
        geo_lay = QVBoxLayout(geo_grp)
        self._geo_stack = QStackedWidget()

        # One pane per shape (order must match SHAPE_LABELS insertion order)
        self._panes: dict[str, QWidget] = {}
        self._panes["rect"]    = self._make_rect_pane()
        self._panes["polygon"] = self._make_polygon_pane()
        self._panes["circle"]  = self._make_circle_pane()
        self._panes["ellipse"] = self._make_ellipse_pane()
        self._panes["line"]    = self._make_line_pane()
        self._panes["hline"]   = self._make_hline_pane()

        for pane in self._panes.values():
            self._geo_stack.addWidget(pane)

        geo_lay.addWidget(self._geo_stack)
        root.addWidget(geo_grp)

        # Connect shape selector → switch pane
        self.cb_shape.currentIndexChanged.connect(self._on_shape_changed)

        # ── 3. Style ───────────────────────────────────────────────────
        style_grp = QGroupBox("Style")
        style_form = QFormLayout(style_grp)
        style_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)

        # Fill colour
        self._fill_color = "#00aaff"
        self.btn_color = QPushButton()
        self.btn_color.setFixedHeight(24)
        self._update_color_btn(self.btn_color, self._fill_color)
        self.btn_color.clicked.connect(lambda: self._pick_color('fill'))
        style_form.addRow("Fill Colour:", self.btn_color)

        # Alpha
        alpha_row = QHBoxLayout()
        self.sld_alpha = QSlider(Qt.Orientation.Horizontal)
        self.sld_alpha.setRange(0, 100)
        self.sld_alpha.setValue(25)
        self.lbl_alpha = QLabel("25%")
        self.sld_alpha.valueChanged.connect(
            lambda v: self.lbl_alpha.setText(f"{v}%"))
        alpha_row.addWidget(self.sld_alpha)
        alpha_row.addWidget(self.lbl_alpha)
        style_form.addRow("Fill Opacity:", alpha_row)

        # Border width
        self.sp_border_w = QSpinBox()
        self.sp_border_w.setRange(0, 20)
        self.sp_border_w.setValue(2)
        style_form.addRow("Border Width (px):", self.sp_border_w)

        # Border colour  (with "use fill colour" checkbox)
        border_color_row = QHBoxLayout()
        self._border_color = ""
        self.btn_border_color = QPushButton()
        self.btn_border_color.setFixedHeight(24)
        self._update_color_btn(self.btn_border_color, self._fill_color)
        self.btn_border_color.clicked.connect(lambda: self._pick_color('border'))
        self.chk_border_auto = QCheckBox("Same as fill")
        self.chk_border_auto.setChecked(True)
        self.chk_border_auto.toggled.connect(self._on_border_auto_toggled)
        self.btn_border_color.setEnabled(False)
        border_color_row.addWidget(self.btn_border_color)
        border_color_row.addWidget(self.chk_border_auto)
        style_form.addRow("Border Colour:", border_color_row)

        # Border style
        self.cb_border_style = QComboBox()
        for s in ("solid", "dash", "dot", "dashdot"):
            self.cb_border_style.addItem(s.capitalize(), s)
        style_form.addRow("Border Style:", self.cb_border_style)

        root.addWidget(style_grp)

        # ── 4. Annotation ──────────────────────────────────────────────
        ann_grp = QGroupBox("Annotation")
        ann_form = QFormLayout(ann_grp)

        self.le_display = QLineEdit()
        self.le_display.setPlaceholderText("Short tag shown on overlay…")
        ann_form.addRow("Display tag:", self.le_display)

        self.te_hover = QPlainTextEdit()
        self.te_hover.setFixedHeight(60)
        self.te_hover.setPlaceholderText("Longer text shown on mouse hover…")
        ann_form.addRow("Hover text:", self.te_hover)

        self.cb_tag_pos = QComboBox()
        for pos in TAG_POSITIONS:
            self.cb_tag_pos.addItem(pos.replace("-", " ").title(), pos)
        ann_form.addRow("Tag position:", self.cb_tag_pos)

        root.addWidget(ann_grp)

        # ── 5. Advanced ────────────────────────────────────────────────
        adv_grp = QGroupBox("Advanced")
        adv_form = QFormLayout(adv_grp)

        self.sp_z_order = QSpinBox()
        self.sp_z_order.setRange(0, 100)
        self.sp_z_order.setValue(8)
        adv_form.addRow("Z Order:", self.sp_z_order)

        self.le_source = QLineEdit()
        self.le_source.setPlaceholderText("user")
        self.le_source.setText("user")
        adv_form.addRow("Source:", self.le_source)

        root.addWidget(adv_grp)

        # ── Dialog buttons ─────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ── Geometry panes ─────────────────────────────────────────────────

    def _make_rect_pane(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        t_min, t_max, f_lo, f_hi = self._default_view_range()

        self.rect_t_min = self._dspin(t_min, -_BIG, _BIG, "s")
        self.rect_t_max = self._dspin(t_max, -_BIG, _BIG, "s")
        self.rect_f_min = self._dspin(f_lo,  -_BIG, _BIG, "Hz")
        self.rect_f_max = self._dspin(f_hi,  -_BIG, _BIG, "Hz")
        f.addRow("Time Start:", self.rect_t_min)
        f.addRow("Time End:",   self.rect_t_max)
        f.addRow("Freq Start:", self.rect_f_min)
        f.addRow("Freq End:",   self.rect_f_max)
        return w

    def _make_polygon_pane(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.poly_table = QTableWidget(0, 2)
        self.poly_table.setHorizontalHeaderLabels(["Time (s)", "Freq (Hz)"])
        self.poly_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.poly_table.setFixedHeight(130)
        lay.addWidget(self.poly_table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add point")
        btn_add.clicked.connect(self._poly_add_row)
        btn_del = QPushButton("– Remove")
        btn_del.clicked.connect(self._poly_del_row)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        lay.addLayout(btn_row)
        return w

    def _make_circle_pane(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        t_c, f_c = self._default_center()
        _, _, f_lo, f_hi = self._default_view_range()
        default_r = abs(f_hi - f_lo) / 8

        self.circ_ct = self._dspin(t_c, -_BIG, _BIG, "s")
        self.circ_cf = self._dspin(f_c, -_BIG, _BIG, "Hz")
        self.circ_r  = self._dspin(default_r, 0, _BIG, "Hz")
        f.addRow("Center Time:", self.circ_ct)
        f.addRow("Center Freq:", self.circ_cf)
        f.addRow("Radius:",      self.circ_r)
        return w

    def _make_ellipse_pane(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        t_c, f_c = self._default_center()
        t_min, t_max, f_lo, f_hi = self._default_view_range()
        rt = abs(t_max - t_min) / 8
        rf = abs(f_hi - f_lo) / 8

        self.ell_ct = self._dspin(t_c, -_BIG, _BIG, "s")
        self.ell_cf = self._dspin(f_c, -_BIG, _BIG, "Hz")
        self.ell_rt = self._dspin(rt,  0, _BIG, "s")
        self.ell_rf = self._dspin(rf,  0, _BIG, "Hz")
        f.addRow("Center Time:",   self.ell_ct)
        f.addRow("Center Freq:",   self.ell_cf)
        f.addRow("Time Radius:",   self.ell_rt)
        f.addRow("Freq Radius:",   self.ell_rf)
        return w

    def _make_line_pane(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        t_min, t_max, _, _ = self._default_view_range()
        self.line_t = self._dspin((t_min + t_max) / 2, -_BIG, _BIG, "s")
        f.addRow("Time Position:", self.line_t)
        return w

    def _make_hline_pane(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        _, _, f_lo, f_hi = self._default_view_range()
        self.hline_f = self._dspin((f_lo + f_hi) / 2, -_BIG, _BIG, "Hz")
        f.addRow("Freq Position:", self.hline_f)
        return w

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _dspin(value: float, lo: float, hi: float, suffix: str = "") -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(6)
        sb.setValue(value)
        if suffix:
            sb.setSuffix(f" {suffix}")
        sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return sb

    def _default_view_range(self):
        try:
            xr, yr = self.parent_window.spectrogram_view.plot_item.viewRange()
            return xr[0], xr[1], yr[0], yr[1]
        except Exception:
            return 0.0, 1.0, -5e6, 5e6

    def _default_center(self):
        t_min, t_max, f_lo, f_hi = self._default_view_range()
        return (t_min + t_max) / 2, (f_lo + f_hi) / 2

    def _update_color_btn(self, btn: QPushButton, hex_color: str) -> None:
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {hex_color}; "
            f"border: 1px solid #888; border-radius: 3px; }}"
        )
        btn.setText(hex_color)

    def _pick_color(self, target: str) -> None:
        current = self._fill_color if target == 'fill' else (
            self._border_color or self._fill_color)
        color = QColorDialog.getColor(QColor(current), self, "Choose colour")
        if not color.isValid():
            return
        hex_color = color.name()
        if target == 'fill':
            self._fill_color = hex_color
            self._update_color_btn(self.btn_color, hex_color)
            if self.chk_border_auto.isChecked():
                self._update_color_btn(self.btn_border_color, hex_color)
        else:
            self._border_color = hex_color
            self._update_color_btn(self.btn_border_color, hex_color)

    def _on_border_auto_toggled(self, checked: bool) -> None:
        self.btn_border_color.setEnabled(not checked)
        if checked:
            self._border_color = ""
            self._update_color_btn(self.btn_border_color, self._fill_color)

    def _on_shape_changed(self, index: int) -> None:
        self._geo_stack.setCurrentIndex(index)

    def _poly_add_row(self) -> None:
        r = self.poly_table.rowCount()
        self.poly_table.setRowCount(r + 1)
        t_c, f_c = self._default_center()
        self.poly_table.setItem(r, 0, QTableWidgetItem(str(t_c)))
        self.poly_table.setItem(r, 1, QTableWidgetItem(str(f_c)))

    def _poly_del_row(self) -> None:
        rows = sorted({i.row() for i in self.poly_table.selectedItems()}, reverse=True)
        for r in rows:
            self.poly_table.removeRow(r)

    # ------------------------------------------------------------------
    # Populate from existing overlay (edit mode)
    # ------------------------------------------------------------------

    def _populate_from_overlay(self, overlay: Overlay) -> None:
        # Shape
        label = _SHAPE_TO_LABEL.get(overlay.shape, "Rectangle")
        idx = self.cb_shape.findText(label)
        if idx >= 0:
            self.cb_shape.setCurrentIndex(idx)
            self._geo_stack.setCurrentIndex(idx)

        # Geometry
        shape = overlay.shape
        if shape == OverlayShape.RECT and len(overlay.points) >= 2:
            self.rect_t_min.setValue(overlay.points[0][0])
            self.rect_f_min.setValue(overlay.points[0][1])
            self.rect_t_max.setValue(overlay.points[1][0])
            self.rect_f_max.setValue(overlay.points[1][1])

        elif shape == OverlayShape.POLYGON:
            self.poly_table.setRowCount(len(overlay.points))
            for r, (tx, fy) in enumerate(overlay.points):
                self.poly_table.setItem(r, 0, QTableWidgetItem(str(tx)))
                self.poly_table.setItem(r, 1, QTableWidgetItem(str(fy)))

        elif shape == OverlayShape.CIRCLE and overlay.center and overlay.radii:
            self.circ_ct.setValue(overlay.center[0])
            self.circ_cf.setValue(overlay.center[1])
            self.circ_r.setValue(overlay.radii[0])

        elif shape == OverlayShape.ELLIPSE and overlay.center and overlay.radii:
            self.ell_ct.setValue(overlay.center[0])
            self.ell_cf.setValue(overlay.center[1])
            self.ell_rt.setValue(overlay.radii[0])
            self.ell_rf.setValue(overlay.radii[1])

        elif shape == OverlayShape.LINE and overlay.points:
            self.line_t.setValue(overlay.points[0][0])

        elif shape == OverlayShape.HLINE and overlay.points:
            self.hline_f.setValue(overlay.points[0][1])

        # Style
        self._fill_color = overlay.color
        self._update_color_btn(self.btn_color, overlay.color)
        self.sld_alpha.setValue(int(overlay.alpha * 100))
        self.sp_border_w.setValue(overlay.border_width)

        if overlay.border_color:
            self._border_color = overlay.border_color
            self.chk_border_auto.setChecked(False)
            self.btn_border_color.setEnabled(True)
            self._update_color_btn(self.btn_border_color, overlay.border_color)
        else:
            self.chk_border_auto.setChecked(True)
            self._update_color_btn(self.btn_border_color, overlay.color)

        bi = self.cb_border_style.findData(overlay.border_style)
        if bi >= 0:
            self.cb_border_style.setCurrentIndex(bi)

        # Annotation
        self.le_display.setText(overlay.display_str)
        self.te_hover.setPlainText(overlay.hover_str)
        ti = self.cb_tag_pos.findData(overlay.tag_pos)
        if ti >= 0:
            self.cb_tag_pos.setCurrentIndex(ti)

        # Advanced
        self.sp_z_order.setValue(overlay.z_order)
        self.le_source.setText(overlay.source)

    # ------------------------------------------------------------------
    # Build an Overlay from the dialog values
    # ------------------------------------------------------------------

    def get_overlay(self) -> Overlay:
        """Return an Overlay populated from the current dialog state."""
        o = self._overlay if self._editing else Overlay()

        # Shape
        shape_label = self.cb_shape.currentText()
        o.shape = SHAPE_LABELS.get(shape_label, OverlayShape.RECT)

        # Geometry
        if o.shape == OverlayShape.RECT:
            o.points = [
                (self.rect_t_min.value(), self.rect_f_min.value()),
                (self.rect_t_max.value(), self.rect_f_max.value()),
            ]
            o.center = o.radii = None

        elif o.shape == OverlayShape.POLYGON:
            pts = []
            for r in range(self.poly_table.rowCount()):
                try:
                    tx = float(self.poly_table.item(r, 0).text())
                    fy = float(self.poly_table.item(r, 1).text())
                    pts.append((tx, fy))
                except (AttributeError, ValueError):
                    pass
            o.points = pts
            o.center = o.radii = None

        elif o.shape == OverlayShape.CIRCLE:
            o.center = (self.circ_ct.value(), self.circ_cf.value())
            r = self.circ_r.value()
            o.radii  = (r, r)
            o.points = []

        elif o.shape == OverlayShape.ELLIPSE:
            o.center = (self.ell_ct.value(), self.ell_cf.value())
            o.radii  = (self.ell_rt.value(), self.ell_rf.value())
            o.points = []

        elif o.shape == OverlayShape.LINE:
            o.points = [(self.line_t.value(), 0.0)]
            o.center = o.radii = None

        elif o.shape == OverlayShape.HLINE:
            o.points = [(0.0, self.hline_f.value())]
            o.center = o.radii = None

        # Style
        o.color        = self._fill_color
        o.alpha        = self.sld_alpha.value() / 100.0
        o.border_width = self.sp_border_w.value()
        o.border_color = "" if self.chk_border_auto.isChecked() else self._border_color
        o.border_style = self.cb_border_style.currentData() or "solid"

        # Annotation
        o.display_str = self.le_display.text().strip()
        o.hover_str   = self.te_hover.toPlainText().strip()
        o.tag_pos     = self.cb_tag_pos.currentData() or "center"

        # Advanced
        o.z_order = self.sp_z_order.value()
        o.source  = self.le_source.text().strip() or "user"

        return o

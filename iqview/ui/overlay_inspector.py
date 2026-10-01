"""iqview/ui/overlay_inspector.py

Visual Overlay & Metadata Inspector Dialog (`OverlayInspectorDialog`).

Opened by right-clicking an overlay on the spectrogram (or clicking 'Inspect'
in the Overlays panel). Displays:
  - Shape, label, source provenance, and in-memory cached IQ status (`o.iq`)
  - Formatted geometry bounds (t_start, t_end, duration, f_start, f_end, bandwidth)
  - Full untruncated `hover_str` with 1-click Copy
  - Visual key-value table of `o.metadata` (e.g. extracted bits, hex, baud rate, SNR)
    with individual 1-click Copy buttons for every field
  - Quick-action buttons to analyze the overlay's narrowband DDC'd IQ in
    Time Domain, Freq Domain, Eye Diagram, or Scatter Plot tabs
"""

from __future__ import annotations

import json
from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .overlay import Overlay, OverlayShape
from .themes import get_palette


def _fmt_time(sec: float) -> str:
    """Format seconds with both SI unit and raw seconds."""
    abs_s = abs(sec)
    if abs_s == 0:
        return "0.000000 s"
    if abs_s < 1e-3:
        return f"{sec * 1e6:.3f} µs  ({sec:.9f} s)"
    if abs_s < 1.0:
        return f"{sec * 1e3:.4f} ms  ({sec:.6f} s)"
    return f"{sec:.6f} s"


def _fmt_freq(hz: float) -> str:
    """Format frequency in Hz with human-readable kHz/MHz/GHz."""
    abs_f = abs(hz)
    if abs_f >= 1e9:
        return f"{hz / 1e9:.6f} GHz  ({hz:,.1f} Hz)"
    if abs_f >= 1e6:
        return f"{hz / 1e6:.6f} MHz  ({hz:,.1f} Hz)"
    if abs_f >= 1e3:
        return f"{hz / 1e3:.3f} kHz  ({hz:,.1f} Hz)"
    return f"{hz:.2f} Hz"


class OverlayInspectorDialog(QDialog):
    """
    Visual popup for inspecting an Overlay's geometry, full hover text,
    and structured metadata dictionary with ready-to-copy fields.
    """

    def __init__(
        self,
        overlay: Overlay,
        parent_window=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent or parent_window)
        self.overlay = overlay
        self.parent_window = parent_window

        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        title_tag = f" — {overlay.display_str}" if overlay.display_str else ""
        self.setWindowTitle(f"Overlay Inspector ({overlay.shape.value}){title_tag}")
        self.setMinimumSize(680, 560)
        self.resize(760, 660)

        self._setup_ui()

    def changeEvent(self, event) -> None:
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        super().changeEvent(event)

    def _get_theme_palette(self):
        theme = "Dark"
        if self.parent_window and hasattr(self.parent_window, "settings_mgr"):
            theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        return get_palette(theme)

    @staticmethod
    def _detect_markup(text: str) -> str:
        """Return 'html', 'markdown', or 'plain'."""
        raw = (text or "").strip()
        if not raw:
            return "plain"
        raw_lower = raw.lower()
        if (
            "<html" in raw_lower
            or "<table" in raw_lower
            or "<br" in raw_lower
            or "<p" in raw_lower
            or "<div" in raw_lower
            or "<pre" in raw_lower
        ):
            return "html"
        if (
            ("\n|" in raw or raw.startswith("|"))
            or ("\n#" in raw or raw.startswith("#"))
            or ("**" in raw or "```" in raw)
            or ("\n- " in raw or raw.startswith("- "))
            or ("\n* " in raw or raw.startswith("* "))
        ):
            return "markdown"
        return "plain"

    def _copy_with_feedback(self, text: str, btn: QPushButton, orig_label: str = "Copy") -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(str(text))
        btn.setText("✓ Copied")
        QTimer.singleShot(1200, lambda: btn.setText(orig_label) if btn else None)

    def _setup_ui(self) -> None:
        p = self._get_theme_palette()
        o = self.overlay

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {p.bg_main};
                color: {p.text_main};
            }}
            QFrame#card {{
                background-color: {p.bg_widget};
                border: 1px solid {p.border};
                border-radius: 6px;
            }}
            QLabel#section_title {{
                color: {p.text_header};
                font-weight: bold;
                font-size: 11px;
                text-transform: uppercase;
            }}
            QLabel#field_label {{
                color: {p.text_dim};
                font-size: 11px;
                font-weight: bold;
            }}
            QLineEdit, QPlainTextEdit {{
                background-color: {p.bg_input};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 4px;
                padding: 4px 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }}
            QTextBrowser#hover_browser {{
                background-color: {p.bg_input};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 4px;
                padding: 6px 8px;
            }}
            QPushButton {{
                background-color: {p.bg_input};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {p.accent};
                color: {p.accent};
                background-color: {p.accent_dim};
            }}
            QPushButton#accent_btn {{
                border: 1px solid {p.accent};
                color: {p.accent};
            }}
            QPushButton#accent_btn:hover {{
                background-color: {p.accent_dim};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # ── 1. Header Banner ─────────────────────────────────────────────
        header_card = QFrame()
        header_card.setObjectName("card")
        hl = QHBoxLayout(header_card)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(10)

        swatch = QLabel()
        swatch.setFixedSize(18, 18)
        swatch_col = o.border_color or o.color or "#00aaff"
        swatch.setStyleSheet(
            f"background-color: {swatch_col}; border: 1px solid #ffffff; border-radius: 4px;"
        )
        hl.addWidget(swatch)

        shape_badge = QLabel(o.shape.value)
        shape_badge.setStyleSheet(
            f"background-color: {p.accent_dim}; color: {p.accent}; "
            f"padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        hl.addWidget(shape_badge)

        title_lbl = QLabel(o.display_str if o.display_str else "(No Display Tag)")
        title_font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        title_lbl.setFont(title_font)
        hl.addWidget(title_lbl, 1)

        if o.iq is not None and hasattr(o.iq, "__len__") and len(o.iq) > 0:
            iq_fs_str = f" @ {o.fs / 1e3:.1f} kHz" if o.fs else ""
            iq_badge = QLabel(f"⚡ Cached IQ: {len(o.iq):,} samples{iq_fs_str}")
            iq_badge.setToolTip(
                "This overlay has its narrowband baseband IQ cached in memory.\n"
                "Downstream plugins (like FSK Demodulator) can re-run on it instantaneously."
            )
            iq_badge.setStyleSheet(
                "background-color: rgba(0, 204, 102, 0.15); color: #00cc66; "
                "border: 1px solid #00cc66; padding: 2px 8px; border-radius: 4px; "
                "font-size: 11px; font-weight: bold;"
            )
            hl.addWidget(iq_badge)

        src_badge = QLabel(f"Source: {o.source}")
        src_badge.setStyleSheet(
            f"color: {p.text_dim}; font-size: 11px; padding: 2px 6px; "
            f"border: 1px solid {p.border}; border-radius: 4px;"
        )
        hl.addWidget(src_badge)

        root.addWidget(header_card)

        # ── 2. Geometry Section ──────────────────────────────────────────
        geom_card = QFrame()
        geom_card.setObjectName("card")
        gl_outer = QVBoxLayout(geom_card)
        gl_outer.setContentsMargins(12, 8, 12, 10)
        gl_outer.setSpacing(6)

        geom_hdr = QHBoxLayout()
        lbl_g = QLabel("Geometry & Bounds")
        lbl_g.setObjectName("section_title")
        geom_hdr.addWidget(lbl_g)
        geom_hdr.addStretch()

        btn_copy_geom = QPushButton("Copy Geometry JSON")
        btn_copy_geom.setFixedHeight(24)
        geom_dict = {
            "shape": o.shape.value,
            "t_start": o.t_start,
            "t_end": o.t_end,
            "t_center": o.t_center,
            "duration": o.duration,
            "f_start": o.f_start,
            "f_end": o.f_end,
            "f_center": o.f_center,
            "bandwidth": o.bandwidth,
        }
        btn_copy_geom.clicked.connect(
            lambda: self._copy_with_feedback(
                json.dumps(geom_dict, indent=2), btn_copy_geom, "Copy Geometry JSON"
            )
        )
        geom_hdr.addWidget(btn_copy_geom)
        gl_outer.addLayout(geom_hdr)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        geom_fields = [
            ("t_start", _fmt_time(o.t_start), "f_start", _fmt_freq(o.f_start)),
            ("t_end", _fmt_time(o.t_end), "f_end", _fmt_freq(o.f_end)),
            ("t_center", _fmt_time(o.t_center), "f_center", _fmt_freq(o.f_center)),
            ("Duration (Δt)", _fmt_time(o.duration), "Bandwidth (Δf)", _fmt_freq(o.bandwidth)),
        ]
        for r_idx, (l1, v1, l2, v2) in enumerate(geom_fields):
            k1 = QLabel(l1)
            k1.setObjectName("field_label")
            e1 = QLineEdit(v1)
            e1.setReadOnly(True)
            k2 = QLabel(l2)
            k2.setObjectName("field_label")
            e2 = QLineEdit(v2)
            e2.setReadOnly(True)
            grid.addWidget(k1, r_idx, 0)
            grid.addWidget(e1, r_idx, 1)
            grid.addWidget(k2, r_idx, 2)
            grid.addWidget(e2, r_idx, 3)

        gl_outer.addLayout(grid)
        root.addWidget(geom_card)

        # ── 3. Full Hover Text (`hover_str`) ─────────────────────────────
        if o.hover_str:
            hover_card = QFrame()
            hover_card.setObjectName("card")
            hl_vbox = QVBoxLayout(hover_card)
            hl_vbox.setContentsMargins(12, 8, 12, 10)
            hl_vbox.setSpacing(6)

            h_hdr = QHBoxLayout()
            lbl_h = QLabel("Hover Summary / Decoded Text")
            lbl_h.setObjectName("section_title")
            h_hdr.addWidget(lbl_h)
            h_hdr.addStretch()

            markup_type = self._detect_markup(o.hover_str)

            if markup_type in ("markdown", "html"):
                btn_toggle_raw = QPushButton("Show Raw")
                btn_toggle_raw.setFixedHeight(24)
                h_hdr.addWidget(btn_toggle_raw)
            else:
                btn_toggle_raw = None

            btn_copy_hover = QPushButton("Copy Text")
            btn_copy_hover.setFixedHeight(24)
            btn_copy_hover.clicked.connect(
                lambda: self._copy_with_feedback(o.hover_str, btn_copy_hover, "Copy Text")
            )
            h_hdr.addWidget(btn_copy_hover)
            hl_vbox.addLayout(h_hdr)

            hover_edit = QTextBrowser()
            hover_edit.setObjectName("hover_browser")
            hover_edit.setReadOnly(True)
            hover_edit.setOpenExternalLinks(True)
            hover_edit.setMinimumHeight(140)
            hover_edit.setMaximumHeight(280)

            showing_raw = False

            def _render_hover_content():
                if showing_raw:
                    hover_edit.setPlainText(o.hover_str)
                    hover_edit.setFont(QFont("Consolas", 10))
                    if btn_toggle_raw:
                        btn_toggle_raw.setText("Show Formatted")
                else:
                    if markup_type == "markdown":
                        from PyQt6.QtGui import QTextDocument
                        doc = QTextDocument()
                        doc.setMarkdown(o.hover_str)
                        html = doc.toHtml()
                        style_block = (
                            f"<style type='text/css'>"
                            f"body {{ color: {p.text_main}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 12px; }}"
                            f"table {{ border: 1px solid {p.border}; border-collapse: collapse; margin-top: 6px; margin-bottom: 6px; }}"
                            f"th, td {{ padding: 4px 8px; border: 1px solid {p.border}; font-size: 11px; }}"
                            f"th {{ background-color: {p.bg_widget}; color: {p.accent}; font-weight: bold; }}"
                            f"h3, h4 {{ margin-top: 2px; margin-bottom: 6px; color: {p.accent}; }}"
                            f"p {{ margin-top: 2px; margin-bottom: 4px; }}"
                            f"ul {{ margin-top: 2px; margin-bottom: 4px; padding-left: 18px; }}"
                            f"li {{ margin-top: 1px; margin-bottom: 1px; }}"
                            f"hr {{ height: 1px; background-color: {p.border}; border: none; margin: 6px 0; }}"
                            f"code {{ font-family: 'Consolas', 'Courier New', monospace; background-color: {p.bg_widget}; padding: 1px 3px; border-radius: 3px; }}"
                            f"</style>"
                        )
                        if "</head>" in html:
                            html = html.replace("</head>", style_block + "</head>")
                        hover_edit.setHtml(html)
                    elif markup_type == "html":
                        hover_edit.setHtml(o.hover_str)
                    else:
                        hover_edit.setPlainText(o.hover_str)
                        hover_edit.setFont(QFont("Consolas", 10))
                    if btn_toggle_raw:
                        btn_toggle_raw.setText("Show Raw")

            def _toggle_raw():
                nonlocal showing_raw
                showing_raw = not showing_raw
                _render_hover_content()

            if btn_toggle_raw:
                btn_toggle_raw.clicked.connect(_toggle_raw)

            _render_hover_content()
            hl_vbox.addWidget(hover_edit)
            root.addWidget(hover_card)

        # ── 4. Visual Metadata Inspector (`o.metadata`) ──────────────────
        meta_card = QFrame()
        meta_card.setObjectName("card")
        ml_vbox = QVBoxLayout(meta_card)
        ml_vbox.setContentsMargins(12, 8, 12, 10)
        ml_vbox.setSpacing(6)

        m_hdr = QHBoxLayout()
        lbl_m = QLabel(f"Metadata Fields ({len(o.metadata)})")
        lbl_m.setObjectName("section_title")
        m_hdr.addWidget(lbl_m)
        m_hdr.addStretch()

        if o.metadata:
            btn_copy_all_meta = QPushButton("Copy All Metadata (JSON)")
            btn_copy_all_meta.setFixedHeight(24)
            btn_copy_all_meta.clicked.connect(
                lambda: self._copy_with_feedback(
                    self._serialize_metadata(), btn_copy_all_meta, "Copy All Metadata (JSON)"
                )
            )
            m_hdr.addWidget(btn_copy_all_meta)

        ml_vbox.addLayout(m_hdr)

        if not o.metadata:
            empty_lbl = QLabel("No metadata dictionary entries attached to this overlay.")
            empty_lbl.setStyleSheet(f"color: {p.text_dim}; font-style: italic; padding: 8px 0;")
            ml_vbox.addWidget(empty_lbl)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet("background: transparent;")

            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 4, 0)
            content_layout.setSpacing(6)

            for key, val in o.metadata.items():
                row_w = QWidget()
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(0, 0, 0, 0)
                row_l.setSpacing(8)

                key_lbl = QLabel(str(key))
                key_lbl.setFixedWidth(130)
                key_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                key_lbl.setStyleSheet(
                    f"color: {p.accent}; font-family: 'Consolas', monospace; "
                    f"font-weight: bold; font-size: 12px; padding-top: 4px;"
                )
                row_l.addWidget(key_lbl)

                val_str = self._format_meta_val(val)
                if len(val_str) > 80 or "\n" in val_str:
                    val_widget = QPlainTextEdit()
                    val_widget.setReadOnly(True)
                    val_widget.setPlainText(val_str)
                    val_widget.setFixedHeight(min(95, max(48, 22 * (1 + len(val_str) // 70))))
                    row_l.addWidget(val_widget, 1)
                else:
                    val_widget = QLineEdit(val_str)
                    val_widget.setReadOnly(True)
                    row_l.addWidget(val_widget, 1)

                btn_cp = QPushButton("Copy")
                btn_cp.setFixedWidth(72)
                btn_cp.setFixedHeight(26)
                btn_cp.clicked.connect(
                    lambda _checked=False, s=val_str, b=btn_cp: self._copy_with_feedback(
                        s, b, "Copy"
                    )
                )
                row_l.addWidget(btn_cp, 0, Qt.AlignmentFlag.AlignTop)

                content_layout.addWidget(row_w)

            content_layout.addStretch()
            scroll.setWidget(content)
            ml_vbox.addWidget(scroll, 1)

        root.addWidget(meta_card, 1)

        # ── 5. Footer: Analyze in Native Tabs & Close ────────────────────
        footer = QHBoxLayout()
        footer.setSpacing(8)

        can_analyze = (
            self.parent_window is not None
            and hasattr(self.parent_window, "analyze_overlay_in_tab")
            and o.duration > 0
        )
        if can_analyze:
            lbl_an = QLabel("Analyze Burst in:")
            lbl_an.setObjectName("field_label")
            footer.addWidget(lbl_an)

            for label, mode_key in [
                ("Time Domain", "time"),
                ("Freq Domain", "freq"),
                ("Eye Diagram", "eye"),
                ("Scatter Plot", "constellation"),
            ]:
                btn_an = QPushButton(label)
                btn_an.setObjectName("accent_btn")
                btn_an.setFixedHeight(28)
                btn_an.clicked.connect(
                    lambda _c=False, m=mode_key: self._on_analyze_clicked(m)
                )
                footer.addWidget(btn_an)

        footer.addStretch()

        if self.parent_window is not None and hasattr(self.parent_window, "marker_panel"):
            btn_edit = QPushButton("Edit Style / Geometry…")
            btn_edit.setFixedHeight(28)
            btn_edit.clicked.connect(self._on_edit_overlay)
            footer.addWidget(btn_edit)

        btn_close = QPushButton("Close")
        btn_close.setFixedHeight(28)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)

        root.addLayout(footer)

    def _format_meta_val(self, val: Any) -> str:
        if isinstance(val, float):
            return f"{val:.6g}"
        if isinstance(val, (dict, list, tuple)):
            try:
                return json.dumps(val, ensure_ascii=False)
            except Exception:
                return str(val)
        return str(val)

    def _serialize_metadata(self) -> str:
        def _default(obj):
            if hasattr(obj, "tolist"):
                return obj.tolist()
            return str(obj)

        try:
            return json.dumps(self.overlay.metadata, indent=2, default=_default)
        except Exception:
            return str(self.overlay.metadata)

    def _on_analyze_clicked(self, tab_type: str) -> None:
        if self.parent_window and hasattr(self.parent_window, "analyze_overlay_in_tab"):
            self.parent_window.analyze_overlay_in_tab(self.overlay, tab_type)

    def _on_edit_overlay(self) -> None:
        if self.parent_window and hasattr(self.parent_window, "marker_panel"):
            mp = self.parent_window.marker_panel
            if hasattr(mp, "_on_overlay_edit"):
                self.accept()
                mp._on_overlay_edit(self.overlay.id)

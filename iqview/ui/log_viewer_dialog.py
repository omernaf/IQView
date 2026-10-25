"""iqview/ui/log_viewer_dialog.py

In-App Application Log Viewer for IQView.

Provides a dedicated, theme-adaptive viewer to inspect, search, filter,
copy, and export all terminal messages, debug prints, and plugin outputs.
Accessible via the sidebar Logs button or the global keybind (default: 'L').
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QKeySequence,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..utils.log_manager import LogEntry, LogManager
from .themes import get_main_stylesheet, get_palette


class LogHighlighter(QSyntaxHighlighter):
    """Fast syntax highlighter for log levels and timestamps."""

    def __init__(self, document: QtGui.QTextDocument, theme_name: str = "Dark"):
        super().__init__(document)
        self.theme_name = theme_name
        self._update_colors()

    def set_theme(self, theme_name: str) -> None:
        self.theme_name = theme_name
        self._update_colors()
        self.rehighlight()

    def _update_colors(self) -> None:
        is_dark = self.theme_name != "Light"

        # Timestamp format: [HH:MM:SS]
        self.time_fmt = QTextCharFormat()
        self.time_fmt.setForeground(QColor("#00aaff" if is_dark else "#0077cc"))

        # Level formats
        self.info_fmt = QTextCharFormat()
        self.info_fmt.setForeground(QColor("#66bb6a" if is_dark else "#2e7d32"))
        self.info_fmt.setFontWeight(QFont.Weight.Bold)

        self.warn_fmt = QTextCharFormat()
        self.warn_fmt.setForeground(QColor("#ffa726" if is_dark else "#e65100"))
        self.warn_fmt.setFontWeight(QFont.Weight.Bold)

        self.error_fmt = QTextCharFormat()
        self.error_fmt.setForeground(QColor("#ef5350" if is_dark else "#c62828"))
        self.error_fmt.setFontWeight(QFont.Weight.Bold)

        self.debug_fmt = QTextCharFormat()
        self.debug_fmt.setForeground(QColor("#80cbc4" if is_dark else "#00796b"))

        self.dim_fmt = QTextCharFormat()
        self.dim_fmt.setForeground(QColor("#888888" if is_dark else "#666666"))

    def highlightBlock(self, text: str) -> None:
        if not text:
            return

        # Highlight timestamp [HH:MM:SS]
        if text.startswith("[") and len(text) >= 10 and text[9] == "]":
            self.setFormat(0, 10, self.time_fmt)

        # Highlight log level [LEVEL]
        if "[ERROR" in text:
            idx = text.find("[ERROR")
            self.setFormat(idx, 7, self.error_fmt)
        elif "[WARN" in text:
            idx = text.find("[WARN")
            self.setFormat(idx, 6, self.warn_fmt)
        elif "[DEBUG" in text:
            idx = text.find("[DEBUG")
            self.setFormat(idx, 7, self.debug_fmt)
        elif "[INFO " in text:
            idx = text.find("[INFO ")
            self.setFormat(idx, 6, self.info_fmt)


class LogViewerDialog(QDialog):
    """
    Application Log Viewer dialog window.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.parent_window = parent
        self.log_manager = LogManager.get_instance()
        self._filtered_entries: List[LogEntry] = []

        self.setWindowTitle("Application Logs — IQView")
        self.setMinimumSize(600, 400)
        self.resize(850, 550)

        # Allow minimizing and maximizing like a standard tool window
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        self._build_ui()
        self.apply_theme()
        self._populate_logs()

        # Connect live log streaming
        self.log_manager.emitter.entry_added.connect(self._on_entry_added)
        self.log_manager.emitter.cleared.connect(self._on_logs_cleared)

    def _build_ui(self) -> None:
        root_lyt = QVBoxLayout(self)
        root_lyt.setContentsMargins(12, 12, 12, 12)
        root_lyt.setSpacing(8)

        # --- Top Filter & Control Bar ---
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        # Search filter
        top_bar.addWidget(QLabel("Filter:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search or regex filter (Ctrl+F)...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_filter_changed)
        top_bar.addWidget(self.search_edit, stretch=2)

        # Level dropdown
        self.level_combo = QComboBox()
        self.level_combo.addItems([
            "All Levels",
            "Info & Above",
            "Warnings & Errors",
            "Errors Only",
            "Debug Only",
        ])
        self.level_combo.currentIndexChanged.connect(self._on_filter_changed)
        top_bar.addWidget(self.level_combo)

        # Stream dropdown
        self.stream_combo = QComboBox()
        self.stream_combo.addItems([
            "All Streams",
            "stdout",
            "stderr",
            "debug",
        ])
        self.stream_combo.currentIndexChanged.connect(self._on_filter_changed)
        top_bar.addWidget(self.stream_combo)

        # Auto-scroll checkbox
        self.auto_scroll_chk = QCheckBox("Auto-scroll")
        self.auto_scroll_chk.setChecked(True)
        top_bar.addWidget(self.auto_scroll_chk)

        top_bar.addSpacing(6)

        # Action buttons
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Clear the in-memory log buffer")
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        top_bar.addWidget(self.clear_btn)

        self.copy_btn = QPushButton("Copy All")
        self.copy_btn.setToolTip("Copy visible logs to clipboard")
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        top_bar.addWidget(self.copy_btn)

        self.save_btn = QPushButton("Save...")
        self.save_btn.setToolTip("Save visible logs to a text file")
        self.save_btn.clicked.connect(self._on_save_clicked)
        top_bar.addWidget(self.save_btn)

        root_lyt.addLayout(top_bar)

        # --- Central Text Area ---
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        # Monospace font
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed_font.setPointSize(10)
        self.text_edit.setFont(fixed_font)

        # Syntax highlighter
        theme_name = self._get_active_theme()
        self.highlighter = LogHighlighter(self.text_edit.document(), theme_name)

        root_lyt.addWidget(self.text_edit, stretch=1)

        # --- Bottom Status Bar ---
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)

        self.status_lbl = QLabel("0 log entries")
        bottom_bar.addWidget(self.status_lbl)

        bottom_bar.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        bottom_bar.addWidget(self.close_btn)

        root_lyt.addLayout(bottom_bar)

    def _get_active_theme(self) -> str:
        s = getattr(self.parent_window, "settings_mgr", None) if self.parent_window else None
        return s.get("ui/theme", "Light") if s else "Light"

    def apply_theme(self, theme_name: Optional[str] = None) -> None:
        if theme_name is None:
            theme_name = self._get_active_theme()

        self.setStyleSheet(get_main_stylesheet(theme_name))
        p = get_palette(theme_name)

        self.text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {p.bg_input};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 4px;
                padding: 4px;
            }}
        """)

        if hasattr(self, "highlighter"):
            self.highlighter.set_theme(theme_name)

    def _matches_filter(self, entry: LogEntry, query: str, level_choice: str, stream_choice: str) -> bool:
        """Check if an entry passes the active filter criteria."""
        # 1. Stream filter
        if stream_choice != "All Streams" and entry.stream != stream_choice:
            return False

        # 2. Level filter
        lvl = entry.level
        if level_choice == "Info & Above":
            if lvl not in ("INFO", "WARNING", "ERROR"):
                return False
        elif level_choice == "Warnings & Errors":
            if lvl not in ("WARNING", "ERROR"):
                return False
        elif level_choice == "Errors Only":
            if lvl != "ERROR":
                return False
        elif level_choice == "Debug Only":
            if lvl != "DEBUG":
                return False

        # 3. Text query
        if query:
            if query.lower() not in entry.message.lower() and query.lower() not in entry.format_line().lower():
                return False

        return True

    def _populate_logs(self) -> None:
        """Reload all logs matching the active filter into the editor."""
        query = self.search_edit.text().strip()
        level_choice = self.level_combo.currentText()
        stream_choice = self.stream_combo.currentText()

        all_entries = self.log_manager.get_entries()
        self._filtered_entries = [
            e for e in all_entries
            if self._matches_filter(e, query, level_choice, stream_choice)
        ]

        text = "\n".join(e.format_line() for e in self._filtered_entries)

        self.text_edit.setUpdatesEnabled(False)
        self.text_edit.setPlainText(text)
        self.text_edit.setUpdatesEnabled(True)

        if self.auto_scroll_chk.isChecked():
            v_bar = self.text_edit.verticalScrollBar()
            v_bar.setValue(v_bar.maximum())

        self._update_status()

    def _update_status(self) -> None:
        total = len(self.log_manager.get_entries())
        showing = len(self._filtered_entries)
        if total == showing:
            self.status_lbl.setText(f"{total:,} log entries")
        else:
            self.status_lbl.setText(f"Showing {showing:,} of {total:,} entries")

    @QtCore.pyqtSlot(object)
    def _on_entry_added(self, entry: LogEntry) -> None:
        """Live slot called when a new log entry is produced."""
        if not self.isVisible():
            return

        query = self.search_edit.text().strip()
        level_choice = self.level_combo.currentText()
        stream_choice = self.stream_combo.currentText()

        if self._matches_filter(entry, query, level_choice, stream_choice):
            self._filtered_entries.append(entry)
            self.text_edit.appendPlainText(entry.format_line())

            if self.auto_scroll_chk.isChecked():
                v_bar = self.text_edit.verticalScrollBar()
                v_bar.setValue(v_bar.maximum())

        self._update_status()

    @QtCore.pyqtSlot()
    def _on_logs_cleared(self) -> None:
        self._filtered_entries.clear()
        self.text_edit.clear()
        self._update_status()

    def _on_filter_changed(self) -> None:
        self._populate_logs()

    def _on_clear_clicked(self) -> None:
        self.log_manager.clear()

    def _on_copy_clicked(self) -> None:
        text = self.text_edit.toPlainText()
        if text:
            clipboard = QtWidgets.QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
                prev_text = self.copy_btn.text()
                self.copy_btn.setText("Copied!")
                QtCore.QTimer.singleShot(1500, lambda: self.copy_btn.setText(prev_text))

    def _on_save_clicked(self) -> None:
        text = self.text_edit.toPlainText()
        if not text:
            return

        default_name = f"iqview_log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Application Logs",
            default_name,
            "Text Files (*.txt);;Log Files (*.log);;All Files (*)",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.status_lbl.setText(f"Logs saved to {os.path.basename(path)}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Save Error", f"Could not save logs:\n{e}")

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self.apply_theme()
        self._populate_logs()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return

        # Ctrl+F to focus search input
        if event.matches(QKeySequence.StandardKey.Find):
            self.search_edit.setFocus()
            self.search_edit.selectAll()
            event.accept()
            return

        # Check if the global keybind for open_logs was pressed (default 'L')
        s = getattr(self.parent_window, "settings_mgr", None) if self.parent_window else None
        kb_logs = s.get("keybinds/open_logs", "L") if s else "L"
        key_name = QKeySequence(event.key()).toString()
        if key_name and key_name.upper() == kb_logs.upper():
            # If user is not typing in the search box, close the dialog
            if not self.search_edit.hasFocus():
                self.close()
                event.accept()
                return

        super().keyPressEvent(event)

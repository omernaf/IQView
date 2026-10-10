"""iqview/ui/plugin_studio.py

PluginStudioDialog — Visual environment for managing, running, chaining,
documenting, and scaffolding IQView plugins (Phase 4).

Tabs
----
1. Manage & Run      — Search/filter plugins, pin favorites, load and unload, edit parameters
                       inline (with per-step chain execution), read rich
                       plugin documentation, and edit the plugin `.py` file.
                       The selected plugin's path is shown above the editor.
                       Parameters are auto-saved to the session so they persist
                       across restarts.
2. Chain Builder     — Visually assemble multi-step PluginChain pipelines,
                       configure per-step default parameters, register in-session,
                       test-run, or export as a reference or standalone .py file.
3. + Create Plugin   — Scaffold new .py plugins from 5 starter templates with a
                       visual parameter table and live Python code preview.
"""

from __future__ import annotations

import copy
import html as _html
import os
import re
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QEvent
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from iqview.plugins.chain import PluginChain
from .marker_panel import PluginDocDialog, ScientificNumberEdit, setup_preset_overrides
from .themes import get_palette, get_scrollbar_stylesheet


class PluginStudioDialog(QDialog):
    """Comprehensive 3-tab Plugin Studio dialog."""

    def __init__(
        self,
        parent_window,
        initial_tab: int = 0,
        select_plugin: Optional[str] = None,
        edit_source: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent or parent_window)
        self.parent_window = parent_window
        self.setWindowTitle("IQView — Plugin Studio")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(1120, 720)

        theme = "Dark"
        if hasattr(self.parent_window, "settings_mgr"):
            theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        self.palette_obj = get_palette(theme)

        self._selected_manage_plugin: Optional[str] = None
        self._manage_param_widgets: Dict[str, QWidget] = {}

        # Chain builder state: list of {"target": str, "params": dict}
        self._chain_steps: List[Dict[str, Any]] = []
        self._active_chain_step_idx: int = -1
        self._chain_step_widgets: Dict[str, QWidget] = {}
        self._editing_chain_orig_name: Optional[str] = None
        self._editing_chain_path: Optional[str] = None
        self._source_plugin_name: Optional[str] = None
        self._source_path: Optional[str] = None
        self._source_newline: str = "\n"
        self._source_trailing_newline: bool = True
        self._source_dirty: bool = False
        self._source_loading: bool = False

        self._build_ui()
        self.refresh_all(select_plugin=select_plugin)
        if 0 <= int(initial_tab) < self.tabs.count():
            self.tabs.setCurrentIndex(int(initial_tab))
        if edit_source:
            self.manage_subtabs.setCurrentWidget(self.source_page)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
            event.ignore()
            return
        super().changeEvent(event)

    # ------------------------------------------------------------------
    # Top-Level UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        p = self.palette_obj
        self.setStyleSheet(
            f"QDialog, QWidget {{ background-color: {p.bg_main}; color: {p.text_main}; }}"
            f"QScrollArea {{ background-color: {p.bg_main}; border: none; }}"
            f"QLabel, QCheckBox {{ background-color: transparent; color: {p.text_main}; }}"
            f"QTabWidget::pane {{ border: 1px solid {p.border}; background-color: {p.bg_main}; border-radius: 4px; }}"
            f"QTabBar::tab {{ background-color: {p.bg_widget}; color: {p.text_dim}; border: 1px solid {p.border}; padding: 6px 14px; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }}"
            f"QTabBar::tab:selected {{ background-color: {p.bg_main}; color: {p.accent}; font-weight: bold; border-bottom-color: {p.bg_main}; }}"
            f"QGroupBox {{ background-color: {p.bg_main}; border: 1px solid {p.border}; border-radius: 6px; margin-top: 8px; padding-top: 10px; font-weight: bold; color: {p.text_header}; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; background-color: {p.bg_main}; color: {p.text_header}; }}"
            f"QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget, QTableWidget {{ background-color: {p.bg_input}; color: {p.text_main}; border: 1px solid {p.border}; border-radius: 4px; padding: 4px; }}"
            f"QHeaderView::section {{ background-color: {p.bg_widget}; color: {p.text_header}; border: 1px solid {p.border}; padding: 4px; }}"
            f"QPushButton {{ background-color: {p.bg_widget}; color: {p.text_main}; border: 1px solid {p.border}; border-radius: 4px; padding: 5px 10px; }}"
            f"QPushButton:hover {{ border-color: {p.accent}; background-color: {p.border_light}; }}"
            f"QPushButton:disabled {{ color: {p.text_dim}; }}"
            + get_scrollbar_stylesheet(p)
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        self.tabs = QTabWidget(self)
        self.tab_manage = QWidget()
        self.tab_chain = QWidget()
        self.tab_create = QWidget()

        self.tabs.addTab(self.tab_manage, "Manage && Run")
        self.tabs.addTab(self.tab_chain, "Chain Builder")
        self.tabs.addTab(self.tab_create, "+ Create Plugin (.py)")

        self._build_manage_tab()
        self._build_chain_tab()
        self._build_create_tab()

        root_layout.addWidget(self.tabs, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        btn_box.accepted.connect(self.accept)
        root_layout.addWidget(btn_box)

    # ==================================================================
    # TAB 1: Manage & Run
    # ==================================================================

    def _build_manage_tab(self) -> None:
        p = self.palette_obj
        layout = QVBoxLayout(self.tab_manage)
        layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Orientation.Horizontal, self.tab_manage)

        # --- Left Pane: Filter + Plugin List ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(6)

        filter_row = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Search plugins…")
        self.ed_search.textChanged.connect(lambda _: self._populate_manage_list())

        self.cb_filter_type = QComboBox()
        self.cb_filter_type.addItem("All Types", userData="all")
        self.cb_filter_type.addItem("Built-In", userData="builtin")
        self.cb_filter_type.addItem("Chains", userData="chain")
        self.cb_filter_type.addItem("Custom (.py)", userData="custom")
        self.cb_filter_type.addItem("Favorites (★)", userData="pinned")
        self.cb_filter_type.currentIndexChanged.connect(lambda _: self._populate_manage_list())

        filter_row.addWidget(self.ed_search, 1)
        filter_row.addWidget(self.cb_filter_type)
        left_layout.addLayout(filter_row)

        self.list_manage_plugins = QListWidget()
        self.list_manage_plugins.currentItemChanged.connect(self._on_manage_selection_changed)
        left_layout.addWidget(self.list_manage_plugins, 1)

        left_btns = QHBoxLayout()
        btn_load = QPushButton("Load .py…")
        btn_load.setToolTip("Load one or more Python plugin files (.py)")
        btn_load.clicked.connect(self._on_studio_load_plugin)

        self.btn_unload_plugin = QPushButton("Unload")
        self.btn_unload_plugin.setToolTip("Unload the selected plugin. Built-in plugins stay loaded.")
        self.btn_unload_plugin.setEnabled(False)
        self.btn_unload_plugin.clicked.connect(self._on_studio_unload_plugin)

        btn_new_chain = QPushButton("New Chain…")
        btn_new_chain.setToolTip("Switch to the Chain Builder tab")
        btn_new_chain.clicked.connect(lambda: self.tabs.setCurrentIndex(1))

        left_btns.addWidget(btn_load)
        left_btns.addWidget(self.btn_unload_plugin)
        left_btns.addWidget(btn_new_chain)
        left_layout.addLayout(left_btns)

        splitter.addWidget(left_widget)

        # --- Right Pane: Selected Plugin Details, Inline Params & Docs ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(8)

        # Header Card
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet(
            f"QFrame {{ background-color: {p.bg_widget}; border: 1px solid {p.border}; border-radius: 6px; padding: 6px; }}"
        )
        hdr_layout = QVBoxLayout(hdr_frame)
        hdr_layout.setContentsMargins(8, 6, 8, 6)
        hdr_layout.setSpacing(4)

        title_row = QHBoxLayout()
        self.lbl_manage_title = QLabel("Select a plugin")
        self.lbl_manage_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {p.text_header}; border: none;")
        title_row.addWidget(self.lbl_manage_title, 1)

        self.btn_pin_plugin = QPushButton("☆ Favorite")
        self.btn_pin_plugin.setFixedWidth(95)
        self.btn_pin_plugin.setToolTip("Mark/unmark this plugin as a Favorite on the main Plugins tab")
        self.btn_pin_plugin.clicked.connect(self._on_toggle_pin_selected)
        title_row.addWidget(self.btn_pin_plugin)

        self.btn_open_doc_popup = QPushButton("Popup Docs")
        self.btn_open_doc_popup.setToolTip("Open documentation in a standalone dialog")
        self.btn_open_doc_popup.clicked.connect(self._on_open_selected_doc_dialog)
        title_row.addWidget(self.btn_open_doc_popup)

        self.btn_edit_py = QPushButton("Edit .py")
        self.btn_edit_py.setToolTip("Open this plugin's .py file in the source editor")
        self.btn_edit_py.clicked.connect(self._on_edit_selected_py)
        title_row.addWidget(self.btn_edit_py)

        self.btn_edit_in_chain_builder = QPushButton("Edit Chain")
        self.btn_edit_in_chain_builder.setToolTip("Load this chain into the Chain Builder tab for editing")
        self.btn_edit_in_chain_builder.clicked.connect(self._on_edit_selected_chain)
        self.btn_edit_in_chain_builder.setVisible(False)
        title_row.addWidget(self.btn_edit_in_chain_builder)

        hdr_layout.addLayout(title_row)

        self.lbl_manage_meta = QLabel("")
        self.lbl_manage_meta.setStyleSheet(f"color: {p.text_dim}; font-size: 11px; border: none;")
        self.lbl_manage_meta.setWordWrap(True)
        hdr_layout.addWidget(self.lbl_manage_meta)

        self.ed_manage_path = QLineEdit()
        self.ed_manage_path.setReadOnly(True)
        self.ed_manage_path.setPlaceholderText("No .py file for this plugin")
        self.ed_manage_path.setToolTip("Path of the selected plugin's .py file")
        hdr_layout.addWidget(self.ed_manage_path)

        # Execution Row inside Header
        exec_row = QHBoxLayout()
        exec_row.addWidget(QLabel("Scope:"))
        self.cb_studio_scope = QComboBox()
        self.cb_studio_scope.addItem("Current View", userData="view")
        self.cb_studio_scope.addItem("Between Markers", userData="markers")
        self.cb_studio_scope.addItem("Full File", userData="full_file")
        # Sync with MarkerPanel scope combo if available
        if hasattr(self.parent_window, "marker_panel") and hasattr(self.parent_window.marker_panel, "cb_plugin_scope"):
            curr_scope = self.parent_window.marker_panel.cb_plugin_scope.currentData()
            idx_s = self.cb_studio_scope.findData(curr_scope)
            if idx_s >= 0:
                self.cb_studio_scope.setCurrentIndex(idx_s)
        self.cb_studio_scope.currentIndexChanged.connect(self._sync_scope_to_panel)
        exec_row.addWidget(self.cb_studio_scope)

        self.btn_studio_run = QPushButton("Run Plugin")
        self.btn_studio_run.setStyleSheet(
            f"QPushButton {{ background-color: {p.accent_dim}; color: {p.text_header}; font-weight: bold; padding: 6px 14px; }}"
            f"QPushButton:hover {{ border-color: {p.accent}; }}"
        )
        self.btn_studio_run.clicked.connect(self._on_studio_run_selected)
        exec_row.addWidget(self.btn_studio_run)

        exec_row.addStretch(1)

        self.btn_toggle_plugin_ov = QPushButton("Show/Hide Overlays")
        self.btn_toggle_plugin_ov.clicked.connect(self._on_toggle_selected_plugin_overlays)
        exec_row.addWidget(self.btn_toggle_plugin_ov)

        self.btn_clear_plugin_ov = QPushButton("Clear Overlays")
        self.btn_clear_plugin_ov.clicked.connect(self._on_clear_selected_plugin_overlays)
        exec_row.addWidget(self.btn_clear_plugin_ov)

        hdr_layout.addLayout(exec_row)
        right_layout.addWidget(hdr_frame)

        # Sub-tabs for Parameters vs Documentation
        self.manage_subtabs = QTabWidget()

        # Sub-tab A: Parameters
        self.params_page = QWidget()
        params_page_layout = QVBoxLayout(self.params_page)
        params_page_layout.setContentsMargins(4, 4, 4, 4)

        self.params_scroll = QScrollArea()
        self.params_scroll.setWidgetResizable(True)
        self.params_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.params_container = QWidget()
        self.params_form_layout = QVBoxLayout(self.params_container)
        self.params_form_layout.setContentsMargins(4, 4, 4, 4)
        self.params_form_layout.setSpacing(8)
        self.params_scroll.setWidget(self.params_container)
        params_page_layout.addWidget(self.params_scroll, 1)

        param_actions_row = QHBoxLayout()
        self.btn_apply_params = QPushButton("Apply Parameters")
        self.btn_apply_params.clicked.connect(self._on_apply_manage_params)

        self.btn_reset_params = QPushButton("Reset to Defaults")
        self.btn_reset_params.clicked.connect(self._on_reset_manage_params)

        param_actions_row.addWidget(self.btn_apply_params)
        param_actions_row.addWidget(self.btn_reset_params)
        param_actions_row.addStretch(1)
        params_page_layout.addLayout(param_actions_row)

        # Sub-tab B: Inline Documentation
        self.doc_browser = QTextBrowser()
        self.doc_browser.setOpenExternalLinks(True)
        self.doc_browser.setStyleSheet(
            f"QTextBrowser {{ background-color: {p.bg_input}; color: {p.text_main}; border: 1px solid {p.border}; border-radius: 4px; padding: 10px; }}"
        )

        self.manage_subtabs.addTab(self.params_page, "Parameters && Step Execution")
        self.manage_subtabs.addTab(self.doc_browser, "Documentation && Reference")

        self.source_page = QWidget()
        source_layout = QVBoxLayout(self.source_page)
        source_layout.setContentsMargins(4, 4, 4, 4)
        source_layout.setSpacing(6)
        self.ed_source = QPlainTextEdit()
        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.ed_source.setFont(mono)
        self.ed_source.setPlaceholderText("Select a plugin that has a .py file on disk.")
        self.ed_source.textChanged.connect(self._on_source_text_changed)
        source_layout.addWidget(self.ed_source, 1)

        source_btns = QHBoxLayout()
        self.btn_reload_source = QPushButton("Reload from Disk")
        self.btn_reload_source.setToolTip("Discard editor changes and read the .py file again")
        self.btn_reload_source.clicked.connect(self._on_reload_source_clicked)
        self.btn_open_external = QPushButton("Open in Editor")
        self.btn_open_external.setToolTip(
            "Open this .py file in the application registered for Python files. "
            "If none is registered, or the registered application is the Python interpreter, "
            "the system Open With dialog is shown."
        )
        self.btn_open_external.clicked.connect(self._on_open_source_external)
        self.btn_save_source = QPushButton("Save .py")
        self.btn_save_source.setToolTip("Write the editor contents back to the plugin file and reload it")
        self.btn_save_source.setStyleSheet(
            f"QPushButton {{ background-color: {p.accent_dim}; color: {p.text_header}; font-weight: bold; padding: 6px 14px; }}"
            f"QPushButton:hover {{ border-color: {p.accent}; }}"
        )
        self.btn_save_source.clicked.connect(self._on_save_source_clicked)
        source_btns.addWidget(self.btn_reload_source)
        source_btns.addWidget(self.btn_open_external)
        source_btns.addStretch(1)
        source_btns.addWidget(self.btn_save_source)
        source_layout.addLayout(source_btns)

        self.manage_subtabs.addTab(self.source_page, "Source (.py)")
        right_layout.addWidget(self.manage_subtabs, 1)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        layout.addWidget(splitter, 1)

    # ==================================================================
    # TAB 2: Chain Builder
    # ==================================================================

    def _build_chain_tab(self) -> None:
        p = self.palette_obj
        layout = QVBoxLayout(self.tab_chain)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Top Metadata & Pipeline Editing Bar
        meta_group = QGroupBox("Chain Pipeline Metadata & Editing")
        meta_vbox = QVBoxLayout(meta_group)
        meta_vbox.setContentsMargins(8, 8, 8, 8)
        meta_vbox.setSpacing(6)

        # Status & Load controls row
        status_row = QHBoxLayout()
        self.lbl_editing_chain_status = QLabel("Mode: <b>New Chain</b>")
        self.lbl_editing_chain_status.setStyleSheet(
            f"background-color: {p.bg_widget}; color: {p.text_main}; border: 1px solid {p.border}; "
            f"border-radius: 4px; padding: 4px 8px; font-size: 11px;"
        )
        status_row.addWidget(self.lbl_editing_chain_status)

        btn_new_blank = QPushButton("New Blank Chain")
        btn_new_blank.setToolTip("Reset the pipeline builder to create a fresh new chain")
        btn_new_blank.clicked.connect(self._on_new_blank_chain_clicked)
        status_row.addWidget(btn_new_blank)

        btn_open_chain_file = QPushButton("Open Chain .py…")
        btn_open_chain_file.setToolTip("Browse and load an existing chain .py file into the builder")
        btn_open_chain_file.clicked.connect(self._on_open_chain_py_file)
        status_row.addWidget(btn_open_chain_file)

        status_row.addStretch(1)

        status_row.addWidget(QLabel("Load Preexisting Chain:"))
        self.cb_load_existing_chain = QComboBox()
        self.cb_load_existing_chain.setMinimumWidth(180)
        self.cb_load_existing_chain.currentIndexChanged.connect(self._on_select_existing_chain_to_edit)
        status_row.addWidget(self.cb_load_existing_chain)
        meta_vbox.addLayout(status_row)

        # Name, Category, Description row
        fields_row = QHBoxLayout()
        fields_row.addWidget(QLabel("Name:"))
        self.ed_chain_name = QLineEdit("Custom Detection & Demod Chain")
        self.ed_chain_name.setMinimumWidth(200)
        fields_row.addWidget(self.ed_chain_name, 2)

        fields_row.addWidget(QLabel("Category:"))
        self.ed_chain_category = QLineEdit("Chains")
        self.ed_chain_category.setFixedWidth(110)
        fields_row.addWidget(self.ed_chain_category)

        fields_row.addWidget(QLabel("Description:"))
        self.ed_chain_desc = QLineEdit("Multi-step RF detection and analysis pipeline.")
        fields_row.addWidget(self.ed_chain_desc, 3)
        meta_vbox.addLayout(fields_row)

        layout.addWidget(meta_group)

        # 3-Column Splitter: Available Plugins | Pipeline Steps | Step Default Parameters
        chain_splitter = QSplitter(Qt.Orientation.Horizontal, self.tab_chain)

        # Col 1: Available Plugins
        col1 = QGroupBox("1. Available Plugins (Double-click to add)")
        col1_layout = QVBoxLayout(col1)
        self.list_available_for_chain = QListWidget()
        self.list_available_for_chain.itemDoubleClicked.connect(lambda _: self._on_add_step_to_chain())
        col1_layout.addWidget(self.list_available_for_chain, 1)

        btn_add_step = QPushButton("Add Selected Plugin to Pipeline")
        btn_add_step.clicked.connect(self._on_add_step_to_chain)
        col1_layout.addWidget(btn_add_step)
        chain_splitter.addWidget(col1)

        # Col 2: Ordered Pipeline Steps
        col2 = QGroupBox("2. Ordered Pipeline Steps")
        col2_layout = QVBoxLayout(col2)
        self.list_chain_steps = QListWidget()
        self.list_chain_steps.currentRowChanged.connect(self._on_chain_step_selected)
        col2_layout.addWidget(self.list_chain_steps, 1)

        step_btns = QHBoxLayout()
        btn_up = QPushButton("Move Up")
        btn_up.clicked.connect(self._on_move_chain_step_up)
        btn_down = QPushButton("Move Down")
        btn_down.clicked.connect(self._on_move_chain_step_down)
        btn_rm = QPushButton("Remove")
        btn_rm.clicked.connect(self._on_remove_chain_step)
        btn_clr = QPushButton("Clear")
        btn_clr.clicked.connect(self._on_clear_chain_steps)

        step_btns.addWidget(btn_up)
        step_btns.addWidget(btn_down)
        step_btns.addWidget(btn_rm)
        step_btns.addWidget(btn_clr)
        col2_layout.addLayout(step_btns)
        chain_splitter.addWidget(col2)

        # Col 3: Selected Step Default Parameters
        col3 = QGroupBox("3. Selected Step Default Parameters")
        col3_layout = QVBoxLayout(col3)

        step_hdr_row = QHBoxLayout()
        self.lbl_chain_step_title = QLabel("Select a pipeline step to configure its default parameters.")
        self.lbl_chain_step_title.setWordWrap(True)
        step_hdr_row.addWidget(self.lbl_chain_step_title, 1)

        self.btn_chain_step_docs = QPushButton("Step Docs")
        self.btn_chain_step_docs.setEnabled(False)
        self.btn_chain_step_docs.clicked.connect(self._on_open_chain_step_docs)
        step_hdr_row.addWidget(self.btn_chain_step_docs)
        col3_layout.addLayout(step_hdr_row)

        self.chain_step_scroll = QScrollArea()
        self.chain_step_scroll.setWidgetResizable(True)
        self.chain_step_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chain_step_form_host = QWidget()
        self.chain_step_form_layout = QFormLayout(self.chain_step_form_host)
        self.chain_step_scroll.setWidget(self.chain_step_form_host)
        col3_layout.addWidget(self.chain_step_scroll, 1)

        chain_splitter.addWidget(col3)
        chain_splitter.setStretchFactor(0, 3)
        chain_splitter.setStretchFactor(1, 3)
        chain_splitter.setStretchFactor(2, 4)
        layout.addWidget(chain_splitter, 1)

        # Bottom Action Bar
        bottom_bar = QHBoxLayout()
        self.chk_chain_standalone = QCheckBox("Bundle as standalone self-contained .py (embeds step functions)")
        self.chk_chain_standalone.setToolTip(
            "When checked, Saving as .py embeds the full source code of each step into a single portable .py file."
        )
        bottom_bar.addWidget(self.chk_chain_standalone)
        bottom_bar.addStretch(1)

        self.btn_save_or_update_chain = QPushButton("Save / Update Chain")
        self.btn_save_or_update_chain.setStyleSheet(
            f"QPushButton {{ background-color: {p.accent_dim}; color: {p.text_header}; font-weight: bold; padding: 6px 14px; }}"
            f"QPushButton:hover {{ border-color: {p.accent}; }}"
        )
        self.btn_save_or_update_chain.setToolTip(
            "Update this chain in-place in IQView and overwrite its .py file if backed by one on disk"
        )
        self.btn_save_or_update_chain.clicked.connect(self._on_save_or_update_existing_chain)
        bottom_bar.addWidget(self.btn_save_or_update_chain)

        btn_reg_session = QPushButton("Register Chain in Session")
        btn_reg_session.setToolTip("Register or update this chain immediately in IQView without requiring a .py file")
        btn_reg_session.clicked.connect(self._on_register_chain_in_session)
        bottom_bar.addWidget(btn_reg_session)

        btn_run_chain_now = QPushButton("Register && Run Chain Now")
        btn_run_chain_now.clicked.connect(self._on_register_and_run_chain)
        bottom_bar.addWidget(btn_run_chain_now)

        btn_save_chain_py = QPushButton("Save Chain as .py…")
        btn_save_chain_py.setToolTip("Export this chain into a new or chosen .py file")
        btn_save_chain_py.clicked.connect(self._on_save_chain_as_py)
        bottom_bar.addWidget(btn_save_chain_py)

        layout.addLayout(bottom_bar)

    # ==================================================================
    # TAB 3: + Create Plugin (Template Generator & Live Doc Preview)
    # ==================================================================

    def _build_create_tab(self) -> None:
        p = self.palette_obj
        layout = QVBoxLayout(self.tab_create)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        top_group = QGroupBox("Plugin Scaffold Settings")
        top_form = QHBoxLayout(top_group)

        top_form.addWidget(QLabel("Template:"))
        self.cb_template_type = QComboBox()
        self.cb_template_type.addItem("1. Custom Plot (Base1DPlotView + Regions)", userData="plot_1d")
        self.cb_template_type.addItem("2. Batch Wideband Detector (Rect + o.iq)", userData="batch_detector")
        self.cb_template_type.addItem("3. Overlay Processor / Demodulator", userData="overlay_processor")
        self.cb_template_type.addItem("4. Native Analysis Tab Launcher", userData="native_tabs")
        self.cb_template_type.addItem("5. Blank Plugin Skeleton", userData="blank")
        self.cb_template_type.currentIndexChanged.connect(self._on_template_preset_changed)
        top_form.addWidget(self.cb_template_type, 2)

        top_form.addWidget(QLabel("Name:"))
        self.ed_tpl_name = QLineEdit("My Custom Plugin")
        self.ed_tpl_name.textChanged.connect(self._update_template_code_preview)
        top_form.addWidget(self.ed_tpl_name, 2)

        top_form.addWidget(QLabel("Category:"))
        self.ed_tpl_category = QLineEdit("Custom")
        self.ed_tpl_category.setFixedWidth(110)
        self.ed_tpl_category.textChanged.connect(self._update_template_code_preview)
        top_form.addWidget(self.ed_tpl_category)

        top_form.addWidget(QLabel("Description:"))
        self.ed_tpl_desc = QLineEdit("Custom IQView signal processing plugin.")
        self.ed_tpl_desc.textChanged.connect(self._update_template_code_preview)
        top_form.addWidget(self.ed_tpl_desc, 3)

        layout.addWidget(top_group)

        # 3-Pane Splitter: Parameters Table | Python Code Preview (Editable) | Live Doc Preview
        mid_splitter = QSplitter(Qt.Orientation.Horizontal, self.tab_create)

        # Left: Visual Parameter Table
        param_group = QGroupBox("1. Parameters (PLUGIN_PARAMS)")
        param_layout = QVBoxLayout(param_group)

        self.tbl_tpl_params = QTableWidget(0, 5)
        self.tbl_tpl_params.setHorizontalHeaderLabels(["Key", "Type", "Default", "Label", "Tooltip"])
        self.tbl_tpl_params.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_tpl_params.itemChanged.connect(lambda _: self._update_template_code_preview())
        param_layout.addWidget(self.tbl_tpl_params, 1)

        p_btn_row = QHBoxLayout()
        btn_add_p = QPushButton("Add Parameter")
        btn_add_p.clicked.connect(self._on_add_template_param_row)
        btn_del_p = QPushButton("Remove Selected")
        btn_del_p.clicked.connect(self._on_remove_template_param_row)
        p_btn_row.addWidget(btn_add_p)
        p_btn_row.addWidget(btn_del_p)
        p_btn_row.addStretch(1)
        param_layout.addLayout(p_btn_row)

        mid_splitter.addWidget(param_group)

        # Middle: Live Python Code Preview (Editable)
        code_group = QGroupBox("2. Python Code Preview (Editable)")
        code_layout = QVBoxLayout(code_group)
        self.ed_tpl_code = QPlainTextEdit()
        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.ed_tpl_code.setFont(mono)
        self.ed_tpl_code.textChanged.connect(self._update_template_doc_live_preview)
        code_layout.addWidget(self.ed_tpl_code, 1)

        code_btn_row = QHBoxLayout()
        btn_regen = QPushButton("Regenerate Preview from Form")
        btn_regen.clicked.connect(self._update_template_code_preview)
        btn_save_load = QPushButton("Save && Load .py Plugin…")
        btn_save_load.setStyleSheet(
            f"QPushButton {{ background-color: {p.accent_dim}; color: {p.text_header}; font-weight: bold; padding: 6px 14px; }}"
            f"QPushButton:hover {{ border-color: {p.accent}; }}"
        )
        btn_save_load.clicked.connect(self._on_save_and_load_template)
        code_btn_row.addWidget(btn_regen)
        code_btn_row.addStretch(1)
        code_btn_row.addWidget(btn_save_load)
        code_layout.addLayout(code_btn_row)

        mid_splitter.addWidget(code_group)

        # Right: Live Documentation Preview
        doc_group = QGroupBox("3. Live Documentation Preview")
        doc_layout = QVBoxLayout(doc_group)
        self.tpl_doc_preview = QTextBrowser()
        self.tpl_doc_preview.setOpenExternalLinks(True)
        self.tpl_doc_preview.setStyleSheet(
            f"QTextBrowser {{ background-color: {p.bg_input}; color: {p.text_main}; border: 1px solid {p.border}; border-radius: 4px; padding: 10px; font-size: 13px; }}"
        )
        doc_layout.addWidget(self.tpl_doc_preview, 1)

        doc_hint = QLabel("Live preview updates in real time as you edit parameters, scaffold settings, or Python code.")
        doc_hint.setStyleSheet(f"color: {p.text_dim}; font-size: 11px;")
        doc_hint.setWordWrap(True)
        doc_layout.addWidget(doc_hint)

        mid_splitter.addWidget(doc_group)
        mid_splitter.setStretchFactor(0, 2)
        mid_splitter.setStretchFactor(1, 3)
        mid_splitter.setStretchFactor(2, 3)
        layout.addWidget(mid_splitter, 1)

        # Initialize default template preset
        self._on_template_preset_changed()

    # ==================================================================
    # Data Refresh & Helpers
    # ==================================================================

    def _get_pinned_set(self) -> set:
        if hasattr(self.parent_window, "get_pinned_plugins"):
            return set(self.parent_window.get_pinned_plugins())
        return set()

    def refresh_all(self, select_plugin: Optional[str] = None) -> None:
        self._populate_manage_list(select_plugin=select_plugin)
        self._populate_chain_available_list()

    def _populate_manage_list(self, select_plugin: Optional[str] = None) -> None:
        target_sel = select_plugin or self._selected_manage_plugin
        search_q = self.ed_search.text().strip().lower()
        ftype = self.cb_filter_type.currentData() or "all"
        pinned = self._get_pinned_set()

        # Count overlays per plugin
        ov_counts: Dict[str, int] = {}
        for o in getattr(self.parent_window, "overlays", []):
            src = str(getattr(o, "source", "") or "")
            if src.startswith("plugin:"):
                pname = src[len("plugin:"):]
                ov_counts[pname] = ov_counts.get(pname, 0) + 1

        self.list_manage_plugins.blockSignals(True)
        self.list_manage_plugins.clear()

        loaded = getattr(self.parent_window, "_loaded_plugins", {})
        # Sort: Favorites on top (alphabetical), followed by remaining plugins (alphabetical)
        sorted_plugins = sorted(
            loaded.items(),
            key=lambda item: (0 if item[0] in pinned else 1, item[0].lower()),
        )
        selected_row = 0
        row_idx = 0

        for name, info in sorted_plugins:
            is_builtin = bool(info.get("builtin", False))
            is_chain = info.get("chain") is not None
            is_pin = name in pinned

            if ftype == "builtin" and not is_builtin:
                continue
            if ftype == "chain" and not is_chain:
                continue
            if ftype == "custom" and (is_builtin or is_chain):
                continue
            if ftype == "pinned" and not is_pin:
                continue

            desc = str(info.get("description", "") or "")
            cat = str(info.get("category", "") or "")
            if search_q and (
                search_q not in name.lower()
                and search_q not in desc.lower()
                and search_q not in cat.lower()
            ):
                continue

            badge = "Chain" if is_chain else ("Built-In" if is_builtin else "Custom")
            pin_prefix = "★ " if is_pin else ""
            cnt = ov_counts.get(name, 0)
            cnt_suffix = f"  ({cnt} overlays)" if cnt > 0 else ""

            item = QListWidgetItem(f"{pin_prefix}{name}  [{badge}]{cnt_suffix}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            tip_parts = [part for part in (desc, str(info.get("path") or "")) if part]
            if tip_parts:
                item.setToolTip("\n".join(tip_parts))
            self.list_manage_plugins.addItem(item)

            if target_sel and name == target_sel:
                selected_row = row_idx
            row_idx += 1

        if self.list_manage_plugins.count() > 0:
            self.list_manage_plugins.setCurrentRow(selected_row)
            self.list_manage_plugins.blockSignals(False)
            self._on_manage_selection_changed(self.list_manage_plugins.currentItem(), None)
        else:
            self.list_manage_plugins.blockSignals(False)
            if self._source_dirty and not self._confirm_discard_source():
                self.lbl_manage_title.setText("No matching plugins")
                return
            self._selected_manage_plugin = None
            self.lbl_manage_title.setText("No matching plugins")
            self.lbl_manage_meta.setText("")
            self.ed_manage_path.clear()
            self.btn_edit_py.setEnabled(False)
            self._update_unload_button()
            self._show_plugin_source("", "")
            self._rebuild_manage_params_form("", {})
            self._rebuild_manage_doc_html("", {})

    def _on_manage_selection_changed(self, current: Optional[QListWidgetItem], _prev) -> None:
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if not name:
            return
        info = self.parent_window._loaded_plugins.get(name, {})
        file_path = self._plugin_file_path(info)
        if name != self._source_plugin_name or file_path != (self._source_path or ""):
            if not self._confirm_discard_source():
                self._revert_manage_selection()
                return
            self._show_plugin_source(name, file_path)

        self._selected_manage_plugin = name

        is_builtin = bool(info.get("builtin", False))
        is_chain = info.get("chain") is not None
        needs_wb = bool(info.get("needs_wideband_iq", True))
        cat = str(info.get("category", "General"))
        desc = str(info.get("description", ""))

        pinned = name in self._get_pinned_set()
        self.btn_pin_plugin.setText("★ Favorite" if pinned else "☆ Favorite")

        self.lbl_manage_title.setText(name)
        t_label = "PluginChain" if is_chain else ("Built-In Plugin" if is_builtin else "Custom .py Plugin")
        iq_label = "Wideband IQ" if needs_wb else "Overlay Baseband IQ (o.iq)"
        self.lbl_manage_meta.setText(f"Category: {cat}  |  Type: {t_label}  |  IQ Mode: {iq_label}\n{desc}")

        self.ed_manage_path.setText(file_path)
        self.ed_manage_path.setToolTip(file_path or "This plugin has no .py file on disk")
        self.btn_edit_py.setEnabled(bool(file_path))
        self.btn_edit_py.setToolTip(
            f"Open {file_path} in the source editor" if file_path
            else "This plugin has no .py file on disk"
        )
        self.btn_edit_in_chain_builder.setVisible(is_chain)
        self._update_unload_button()

        self._rebuild_manage_params_form(name, info)
        self._rebuild_manage_doc_html(name, info)

    def _plugin_file_path(self, info: dict) -> str:
        """Return the plugin `.py` path when that file exists, otherwise `""`."""
        raw = str((info or {}).get("path") or "").strip()
        if not raw or not os.path.isfile(raw):
            return ""
        return os.path.normpath(os.path.abspath(raw))

    def _on_edit_selected_py(self) -> None:
        """Show the selected plugin's source in the studio."""
        self.tabs.setCurrentIndex(0)
        self.manage_subtabs.setCurrentWidget(self.source_page)
        self.ed_source.setFocus()

    def _on_source_text_changed(self) -> None:
        if self._source_loading:
            return
        self._source_dirty = True
        self.btn_save_source.setText("Save .py *")

    def _set_source_clean(self) -> None:
        self._source_dirty = False
        self.btn_save_source.setText("Save .py")

    def _confirm_discard_source(self) -> bool:
        """Ask before throwing away unsaved source edits. True means it is safe to switch."""
        if not self._source_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved Plugin Source",
            f"Save changes to:\n{self._source_path}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self._save_plugin_source()
        self._set_source_clean()
        return True

    def _revert_manage_selection(self) -> None:
        prev = self._source_plugin_name
        self.list_manage_plugins.blockSignals(True)
        restored = False
        for i in range(self.list_manage_plugins.count()):
            item = self.list_manage_plugins.item(i)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == prev:
                self.list_manage_plugins.setCurrentRow(i)
                restored = True
                break
        self.list_manage_plugins.blockSignals(False)
        if restored:
            self._selected_manage_plugin = prev

    def _show_plugin_source(self, name: str, file_path: str) -> None:
        """Load *file_path* into the source editor, or clear it when there is no file."""
        self._source_plugin_name = name
        self._source_path = file_path or None
        self._source_loading = True
        try:
            if not file_path:
                self.ed_source.setPlainText("")
                self.ed_source.setPlaceholderText("This plugin has no .py file on disk.")
                self.ed_source.setReadOnly(True)
                self._set_source_file_actions(False)
            else:
                with open(file_path, "rb") as fh:
                    raw = fh.read()
                self._source_newline = "\r\n" if b"\r\n" in raw else "\n"
                self._source_trailing_newline = raw.endswith(b"\n")
                text = raw.decode("utf-8")
                self.ed_source.setPlaceholderText("")
                self.ed_source.setPlainText(text)
                self.ed_source.setReadOnly(False)
                self._set_source_file_actions(True)
        except (OSError, UnicodeError) as exc:
            self.ed_source.setPlainText("")
            self.ed_source.setPlaceholderText(f"Could not read file:\n{exc}")
            self.ed_source.setReadOnly(True)
            self._set_source_file_actions(False)
            self._source_path = None
        finally:
            self._set_source_clean()
            self._source_loading = False

    def _set_source_file_actions(self, enabled: bool) -> None:
        self.btn_save_source.setEnabled(enabled)
        self.btn_reload_source.setEnabled(enabled)
        self.btn_open_external.setEnabled(enabled)

    def _on_open_source_external(self) -> None:
        """Open the plugin file in the user's editor, or the system Open With dialog."""
        path = self._source_path
        if not path:
            return
        if self._source_dirty:
            answer = QMessageBox.question(
                self,
                "Unsaved Plugin Source",
                "Save the editor changes before opening the file?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not self._save_plugin_source():
                return
            path = self._source_path or path
        hwnd = 0
        if os.name == "nt":
            try:
                hwnd = int(self.winId())
            except (TypeError, ValueError):
                hwnd = 0
        from iqview.utils.open_py_file import open_py_file
        result = open_py_file(path, parent_hwnd=hwnd)
        if result.message and not result.cancelled:
            QMessageBox.warning(self, "Open in Editor", result.message)

    def _on_reload_source_clicked(self) -> None:
        if not self._source_path:
            return
        if self._source_dirty:
            answer = QMessageBox.question(
                self,
                "Reload Plugin Source",
                "Discard unsaved edits and reload the file from disk?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        name = self._source_plugin_name or ""
        self._set_source_clean()
        self._show_plugin_source(name, self._source_path or "")

    def _on_save_source_clicked(self) -> None:
        if self._save_plugin_source():
            name = self._source_plugin_name
            self.refresh_all(select_plugin=name)

    def _save_plugin_source(self) -> bool:
        """Write the source editor to disk and reload that plugin. Returns True on success."""
        path = self._source_path
        name = self._source_plugin_name
        if not path or not name:
            return False
        text = self.ed_source.toPlainText().replace("\r\n", "\n").replace("\n", self._source_newline)
        if self._source_trailing_newline and text and not text.endswith(self._source_newline):
            text += self._source_newline
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Could not write:\n{path}\n\n{exc}",
            )
            return False

        info = {}
        if hasattr(self.parent_window, "_loaded_plugins"):
            info = self.parent_window._loaded_plugins.get(name, {}) or {}
        is_builtin = bool(info.get("builtin", False))
        loaded_name = None
        if hasattr(self.parent_window, "_load_plugin_from_path"):
            loaded_name = self.parent_window._load_plugin_from_path(
                path,
                _persist=not is_builtin,
                _silent=False,
                _preserve_params=info.get("params"),
                _builtin=is_builtin,
            )
        if loaded_name:
            self._set_source_clean()
            self._source_plugin_name = loaded_name
            return True
        elif hasattr(self.parent_window, "_load_plugin_from_path"):
            return False
        self._set_source_clean()
        return True

    def _create_param_editor_widget(self, key: str, spec: Any, val: Any) -> QWidget:
        if not isinstance(spec, dict):
            spec = {"type": type(spec).__name__, "default": spec, "label": key}
        ptype = spec.get("type", "str")
        if val is None:
            val = spec.get("default")
        tooltip = spec.get("tooltip", "")

        if ptype == "int":
            w = ScientificNumberEdit(
                value=int(val or 0),
                is_int=True,
                min_val=spec.get("min"),
                max_val=spec.get("max"),
            )
        elif ptype == "float":
            w = ScientificNumberEdit(
                value=float(val or 0.0),
                is_int=False,
                min_val=spec.get("min"),
                max_val=spec.get("max"),
            )
        elif ptype == "bool":
            w = QCheckBox()
            w.setChecked(bool(val))
        elif ptype in ("choice", "dropdown", "select", "enum") or ("choices" in spec) or ("options" in spec):
            w = QComboBox()
            raw_choices = spec.get("choices") if "choices" in spec else spec.get("options", [])
            choices = [str(c) for c in raw_choices]
            w.addItems(choices)
            if val is not None and str(val) in choices:
                w.setCurrentText(str(val))
            elif choices:
                w.setCurrentIndex(0)
        elif ptype in ("file", "filepath", "path"):
            container = QWidget()
            h_lay = QHBoxLayout(container)
            h_lay.setContentsMargins(0, 0, 0, 0)
            h_lay.setSpacing(4)
            line_edit = QLineEdit()
            line_edit.setText(str(val if val is not None else ""))
            btn_browse = QPushButton("Browse...")
            btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
            def _on_browse(_=False, le=line_edit, label=spec.get("label", "File")):
                from PyQt6.QtWidgets import QFileDialog
                fn, _ = QFileDialog.getOpenFileName(self, f"Select {label}")
                if fn:
                    le.setText(fn)
            btn_browse.clicked.connect(_on_browse)
            h_lay.addWidget(line_edit, 1)
            h_lay.addWidget(btn_browse)
            container._inner_line_edit = line_edit
            w = container
        else:
            w = QLineEdit()
            w.setText(str(val if val is not None else ""))

        if tooltip:
            w.setToolTip(str(tooltip))
        return w

    def _read_param_widget_value(self, w: QWidget) -> Any:
        if hasattr(w, "_inner_line_edit"):
            return w._inner_line_edit.text()
        if isinstance(w, ScientificNumberEdit):
            return w.value()
        if isinstance(w, QSpinBox):
            return w.value()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QLineEdit):
            return w.text()
        return None

    def _set_param_widget_value(self, w: QWidget, val: Any) -> None:
        if val is None:
            return
        if hasattr(w, "_inner_line_edit"):
            w._inner_line_edit.setText(str(val))
        elif isinstance(w, ScientificNumberEdit):
            w.setValue(val)
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(val))
        elif isinstance(w, QComboBox):
            w.setCurrentText(str(val))
        elif isinstance(w, QLineEdit):
            w.setText(str(val))

    def _rebuild_manage_params_form(self, name: str, info: dict) -> None:
        old_container = self.params_scroll.takeWidget()
        if old_container is not None:
            old_container.hide()
            old_container.setParent(None)
            old_container.deleteLater()

        self.params_container = QWidget()
        self.params_form_layout = QVBoxLayout(self.params_container)
        self.params_form_layout.setContentsMargins(4, 4, 4, 4)
        self.params_form_layout.setSpacing(8)
        self._manage_param_widgets.clear()

        # Banner for chains leading to Chain Builder
        if info.get("chain") is not None:
            p = self.palette_obj
            chain_banner = QFrame()
            chain_banner.setStyleSheet(
                f"QFrame {{ background-color: {p.bg_widget}; border: 1px solid {p.accent}; "
                f"border-radius: 6px; padding: 4px; margin-bottom: 4px; }}"
            )
            banner_lay = QHBoxLayout(chain_banner)
            banner_lay.setContentsMargins(8, 4, 8, 4)
            lbl_banner = QLabel("<b>Pipeline Chain:</b> You can tune step parameters below, or modify pipeline steps & order in Chain Builder.")
            lbl_banner.setStyleSheet(f"color: {p.text_main}; border: none;")
            btn_banner = QPushButton("Edit Pipeline in Chain Builder…")
            btn_banner.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_banner.clicked.connect(self._on_edit_selected_chain)
            banner_lay.addWidget(lbl_banner, 1)
            banner_lay.addWidget(btn_banner)
            self.params_form_layout.addWidget(chain_banner)

        params_spec = info.get("params_spec", {}) or {}
        current_params = info.get("params", {}) or {}

        if not params_spec:
            lbl = QLabel("This plugin has no configurable parameters.")
            lbl.setStyleSheet(f"color: {self.palette_obj.text_dim}; font-style: italic;")
            self.params_form_layout.addWidget(lbl)
            self.params_form_layout.addStretch(1)
            self.params_scroll.setWidget(self.params_container)
            return

        has_steps = any(
            isinstance(spec, dict) and "step_index" in spec
            for spec in params_spec.values()
        )

        if has_steps:
            step_groups: Dict[int, Dict[str, Any]] = {}
            for key, spec in params_spec.items():
                s_idx = int(spec.get("step_index", 0)) if isinstance(spec, dict) else 0
                s_title = (
                    spec.get("step_title", f"Step {s_idx + 1}")
                    if isinstance(spec, dict)
                    else f"Step {s_idx + 1}"
                )
                step_groups.setdefault(s_idx, {"title": s_title, "items": []})["items"].append((key, spec))

            for s_idx in sorted(step_groups.keys()):
                grp_info = step_groups[s_idx]
                box = QGroupBox(grp_info["title"])
                box_vbox = QVBoxLayout(box)

                hdr = QHBoxLayout()
                hdr.addStretch(1)
                btn_step_only = QPushButton("Run Step Only")
                btn_step_only.setToolTip(f"Apply parameters and run only {grp_info['title']}")
                btn_step_only.clicked.connect(lambda _, idx=s_idx: self._on_run_chain_step_from_manage(idx, True))

                btn_from_here = QPushButton("Run From Here")
                btn_from_here.setToolTip(f"Apply parameters and run from {grp_info['title']} onward")
                btn_from_here.clicked.connect(lambda _, idx=s_idx: self._on_run_chain_step_from_manage(idx, False))

                hdr.addWidget(btn_step_only)
                hdr.addWidget(btn_from_here)
                box_vbox.addLayout(hdr)

                form = QFormLayout()
                for key, spec in grp_info["items"]:
                    val = current_params.get(key, spec.get("default") if isinstance(spec, dict) else spec)
                    w = self._create_param_editor_widget(key, spec, val)
                    lbl_txt = spec.get("label", key) if isinstance(spec, dict) else key
                    lbl_w = QLabel(str(lbl_txt) + ":")
                    if isinstance(spec, dict) and spec.get("tooltip"):
                        lbl_w.setToolTip(str(spec["tooltip"]))
                    form.addRow(lbl_w, w)
                    self._manage_param_widgets[key] = w
                box_vbox.addLayout(form)
                self.params_form_layout.addWidget(box)
        else:
            form_box = QGroupBox("Plugin Parameters")
            form = QFormLayout(form_box)
            for key, spec in params_spec.items():
                val = current_params.get(key, spec.get("default") if isinstance(spec, dict) else spec)
                w = self._create_param_editor_widget(key, spec, val)
                lbl_txt = spec.get("label", key) if isinstance(spec, dict) else key
                lbl_w = QLabel(str(lbl_txt) + ":")
                if isinstance(spec, dict) and spec.get("tooltip"):
                    lbl_w.setToolTip(str(spec["tooltip"]))
                form.addRow(lbl_w, w)
                self._manage_param_widgets[key] = w
            self.params_form_layout.addWidget(form_box)

        setup_preset_overrides(params_spec, self._manage_param_widgets, self._set_param_widget_value)

        self.params_form_layout.addStretch(1)
        self.params_scroll.setWidget(self.params_container)

    def _rebuild_manage_doc_html(self, name: str, info: dict) -> None:
        p = self.palette_obj
        raw_doc = str(info.get("doc", "") or "").strip()
        desc = str(info.get("description", ""))
        params_spec = info.get("params_spec", {}) or {}

        is_html = bool(re.search(r"<(?:h[1-6]|p|div|table|ol|ul|br)\b", raw_doc, re.IGNORECASE))

        if not is_html:
            rows_md = []
            for key, spec in params_spec.items():
                if not isinstance(spec, dict):
                    spec = {"type": type(spec).__name__, "default": spec, "label": key}
                lbl = str(spec.get("label", key))
                ptype = str(spec.get("type", "str"))
                def_val = str(spec.get("default", ""))
                tip = str(spec.get("tooltip", "") or "—")
                rows_md.append(f"| **{lbl}** (`{key}`) | `{ptype}` | `{def_val}` | {tip} |")

            table_md = (
                "### Parameters Reference\n\n"
                "| Parameter | Type | Default | Description |\n"
                "| :--- | :--- | :--- | :--- |\n"
                + "\n".join(rows_md)
                if rows_md
                else "*No configurable parameters.*"
            )

            body = raw_doc if raw_doc else f"# {name}\n\n{desc}"
            has_inline_table = ("<table" in raw_doc.lower()) or ("| ---" in raw_doc or "|:---" in raw_doc or "| :---" in raw_doc)
            extra_table = "" if has_inline_table else f"\n\n---\n\n{table_md}"
            self.doc_browser.setMarkdown(f"{body}{extra_table}")
        else:
            rows_html = []
            for key, spec in params_spec.items():
                if not isinstance(spec, dict):
                    spec = {"type": type(spec).__name__, "default": spec, "label": key}
                lbl = _html.escape(str(spec.get("label", key)))
                ptype = _html.escape(str(spec.get("type", "str")))
                def_val = _html.escape(str(spec.get("default", "")))
                tip = _html.escape(str(spec.get("tooltip", "") or "—"))
                rows_html.append(
                    f"<tr>"
                    f"<td style='padding:5px 8px; border-bottom:1px solid {p.border};'><b>{lbl}</b><br/><code style='color:{p.text_dim};'>{_html.escape(str(key))}</code></td>"
                    f"<td style='padding:5px 8px; border-bottom:1px solid {p.border};'><code>{ptype}</code></td>"
                    f"<td style='padding:5px 8px; border-bottom:1px solid {p.border};'><code>{def_val}</code></td>"
                    f"<td style='padding:5px 8px; border-bottom:1px solid {p.border};'>{tip}</td>"
                    f"</tr>"
                )

            table_html = (
                f"<h4>Parameters Reference</h4>"
                f"<table width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse;'>"
                f"<thead><tr style='background-color:{p.bg_widget};'>"
                f"<th align='left' style='padding:6px 8px; border-bottom:2px solid {p.border};'>Parameter</th>"
                f"<th align='left' style='padding:6px 8px; border-bottom:2px solid {p.border};'>Type</th>"
                f"<th align='left' style='padding:6px 8px; border-bottom:2px solid {p.border};'>Default</th>"
                f"<th align='left' style='padding:6px 8px; border-bottom:2px solid {p.border};'>Description</th>"
                f"</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"
                if rows_html
                else "<p><i>No configurable parameters.</i></p>"
            )

            body = raw_doc if raw_doc else f"<h3>{_html.escape(name)}</h3><p>{_html.escape(desc)}</p>"
            has_inline_table = "<table" in raw_doc.lower()
            extra_table = "" if has_inline_table else f"<hr/>{table_html}"
            self.doc_browser.setHtml(
                f"<div style=\"font-family:'Segoe UI',sans-serif; line-height:1.45;\">{body}{extra_table}</div>"
            )

    def _collect_manage_params(self) -> Dict[str, Any]:
        return {k: self._read_param_widget_value(w) for k, w in self._manage_param_widgets.items()}

    def _on_apply_manage_params(self) -> None:
        if not self._selected_manage_plugin:
            return
        info = self.parent_window._loaded_plugins.get(self._selected_manage_plugin)
        if not info:
            return
        params = self._collect_manage_params()
        info["params"] = params
        if hasattr(self.parent_window, "save_plugin_params"):
            self.parent_window.save_plugin_params(self._selected_manage_plugin, params)
        if hasattr(self.parent_window, "statusBar"):
            self.parent_window.statusBar().showMessage(
                f"Applied parameters for '{self._selected_manage_plugin}'", 3000
            )

    def _on_reset_manage_params(self) -> None:
        if not self._selected_manage_plugin:
            return
        info = self.parent_window._loaded_plugins.get(self._selected_manage_plugin)
        if not info:
            return
        params_spec = info.get("params_spec", {}) or {}
        for k, w in self._manage_param_widgets.items():
            spec = params_spec.get(k, {})
            default_val = spec.get("default") if isinstance(spec, dict) else spec
            self._set_param_widget_value(w, default_val)
        self._on_apply_manage_params()

    def _sync_scope_to_panel(self) -> None:
        scope = self.cb_studio_scope.currentData()
        if hasattr(self.parent_window, "marker_panel") and hasattr(self.parent_window.marker_panel, "cb_plugin_scope"):
            cb = self.parent_window.marker_panel.cb_plugin_scope
            idx = cb.findData(scope)
            if idx >= 0 and cb.currentIndex() != idx:
                cb.setCurrentIndex(idx)

    def _on_studio_run_selected(self) -> None:
        if not self._selected_manage_plugin:
            return
        self._on_apply_manage_params()
        scope = self.cb_studio_scope.currentData() or "view"
        self.parent_window.run_plugin(self._selected_manage_plugin, scope=scope)
        self._populate_manage_list(select_plugin=self._selected_manage_plugin)

    def _on_run_chain_step_from_manage(self, step_index: int, single_step_only: bool) -> None:
        if not self._selected_manage_plugin:
            return
        self._on_apply_manage_params()
        scope = self.cb_studio_scope.currentData() or "view"
        self.parent_window.run_plugin_step(
            self._selected_manage_plugin,
            step_index=step_index,
            single_step_only=single_step_only,
            scope=scope,
        )
        self._populate_manage_list(select_plugin=self._selected_manage_plugin)

    def _on_toggle_pin_selected(self) -> None:
        if not self._selected_manage_plugin:
            return
        if hasattr(self.parent_window, "toggle_pinned_plugin"):
            self.parent_window.toggle_pinned_plugin(self._selected_manage_plugin)
        self._populate_manage_list(select_plugin=self._selected_manage_plugin)

    def _on_open_selected_doc_dialog(self) -> None:
        if not self._selected_manage_plugin:
            return
        info = self.parent_window._loaded_plugins.get(self._selected_manage_plugin)
        if not info:
            return
        dlg = PluginDocDialog(self._selected_manage_plugin, info, parent=self)
        dlg.exec()

    def _on_toggle_selected_plugin_overlays(self) -> None:
        if not self._selected_manage_plugin:
            return
        src = f"plugin:{self._selected_manage_plugin}"
        if hasattr(self.parent_window, "toggle_source_overlays_visible"):
            self.parent_window.toggle_source_overlays_visible(src)

    def _on_clear_selected_plugin_overlays(self) -> None:
        if not self._selected_manage_plugin:
            return
        src = f"plugin:{self._selected_manage_plugin}"
        self.parent_window.clear_overlays(source=src)
        self._populate_manage_list(select_plugin=self._selected_manage_plugin)

    def _update_unload_button(self) -> None:
        if not hasattr(self, "btn_unload_plugin"):
            return
        name = self._selected_manage_plugin
        loaded = getattr(self.parent_window, "_loaded_plugins", {})
        info = loaded.get(name) if name else None
        is_builtin = bool((info or {}).get("builtin", False))
        can_unload = bool(info) and not is_builtin
        self.btn_unload_plugin.setEnabled(can_unload)
        if not name:
            tip = "Select a plugin to unload"
        elif is_builtin:
            tip = "Built-in plugins stay loaded"
        else:
            tip = f"Unload '{name}'"
        self.btn_unload_plugin.setToolTip(tip)

    def _on_studio_unload_plugin(self) -> None:
        name = self._selected_manage_plugin
        if not name or not hasattr(self.parent_window, "unload_plugin"):
            return
        info = self.parent_window._loaded_plugins.get(name) or {}
        if info.get("builtin"):
            return
        if not self._confirm_discard_source():
            return
        self.parent_window.unload_plugin(name)
        self._selected_manage_plugin = None
        self._set_source_clean()
        self._show_plugin_source("", "")
        self.refresh_all()

    def _on_studio_load_plugin(self) -> None:
        self.parent_window.load_plugin()
        self.refresh_all()

    def _on_edit_selected_chain(self) -> None:
        if not self._selected_manage_plugin:
            return
        self._load_chain_into_builder(self._selected_manage_plugin)
        self.tabs.setCurrentIndex(1)

    # ==================================================================
    # Chain Builder Logic (Tab 2)
    # ==================================================================

    def _populate_chain_available_list(self) -> None:
        self.list_available_for_chain.clear()
        self.cb_load_existing_chain.blockSignals(True)
        self.cb_load_existing_chain.clear()
        self.cb_load_existing_chain.addItem("— New Blank Chain —", userData="")

        loaded = getattr(self.parent_window, "_loaded_plugins", {})
        pinned = self._get_pinned_set()

        # Sort: Favorites on top (alphabetical), followed by remaining plugins (alphabetical)
        sorted_plugins = sorted(
            loaded.items(),
            key=lambda item: (0 if item[0] in pinned else 1, item[0].lower()),
        )

        selected_idx = 0
        c_idx = 1
        for name, info in sorted_plugins:
            if info.get("chain") is not None:
                self.cb_load_existing_chain.addItem(f"{name} [Chain]", userData=name)
                if self._editing_chain_orig_name and name == self._editing_chain_orig_name:
                    selected_idx = c_idx
                c_idx += 1
                continue
            cat = info.get("category", "General")
            pin_prefix = "★ " if name in pinned else ""
            item = QListWidgetItem(f"{pin_prefix}{name}  [{cat}]")
            item.setData(Qt.ItemDataRole.UserRole, name)
            if info.get("description"):
                item.setToolTip(str(info["description"]))
            self.list_available_for_chain.addItem(item)

        self.cb_load_existing_chain.setCurrentIndex(selected_idx)
        self.cb_load_existing_chain.blockSignals(False)

    def _update_editing_chain_status(self) -> None:
        p = self.palette_obj
        if self._editing_chain_orig_name:
            if self._editing_chain_path:
                path_str = (
                    f"<br><span style='font-weight:normal'>{_html.escape(self._editing_chain_path)}</span>"
                )
            else:
                path_str = " [In-Session]"
            self.lbl_editing_chain_status.setWordWrap(True)
            self.lbl_editing_chain_status.setText(
                f"Editing: <b>{_html.escape(self._editing_chain_orig_name)}</b>{path_str}"
            )
            self.lbl_editing_chain_status.setStyleSheet(
                f"background-color: {p.accent_dim}; color: {p.text_header}; border: 1px solid {p.accent}; "
                f"border-radius: 4px; padding: 4px 8px; font-size: 11px;"
            )
            self.btn_save_or_update_chain.setText("Update Chain")
        else:
            self.lbl_editing_chain_status.setText("Mode: <b>New Chain</b>")
            self.lbl_editing_chain_status.setStyleSheet(
                f"background-color: {p.bg_widget}; color: {p.text_main}; border: 1px solid {p.border}; "
                f"border-radius: 4px; padding: 4px 8px; font-size: 11px;"
            )
            self.btn_save_or_update_chain.setText("Save / Update Chain")

    def _load_chain_into_builder(self, chain_name: str) -> None:
        info = self.parent_window._loaded_plugins.get(chain_name)
        if not info or info.get("chain") is None:
            return
        self._editing_chain_orig_name = chain_name
        self._editing_chain_path = info.get("path")
        chain_obj: PluginChain = info["chain"]
        self.ed_chain_name.setText(chain_obj.name or chain_name)
        self.ed_chain_category.setText(chain_obj.category or "Chains")
        self.ed_chain_desc.setText(chain_obj.description or "")

        self._chain_steps = []
        for s in chain_obj.steps:
            t = s["target"]
            t_name = t if isinstance(t, str) else getattr(t, "PLUGIN_NAME", str(t))
            self._chain_steps.append({
                "target": str(t_name),
                "params": copy.deepcopy(s.get("params", {})),
            })
        self._refresh_chain_steps_list(select_row=0 if self._chain_steps else -1)
        self._update_editing_chain_status()

        idx = self.cb_load_existing_chain.findData(chain_name)
        if idx >= 0:
            self.cb_load_existing_chain.blockSignals(True)
            self.cb_load_existing_chain.setCurrentIndex(idx)
            self.cb_load_existing_chain.blockSignals(False)

    def _on_new_blank_chain_clicked(self) -> None:
        self._editing_chain_orig_name = None
        self._editing_chain_path = None
        self.ed_chain_name.setText("Custom Detection & Demod Chain")
        self.ed_chain_category.setText("Chains")
        self.ed_chain_desc.setText("Multi-step RF detection and analysis pipeline.")
        self._active_chain_step_idx = -1
        self._chain_steps.clear()
        self._refresh_chain_steps_list(select_row=-1)
        self._update_editing_chain_status()
        self.cb_load_existing_chain.blockSignals(True)
        self.cb_load_existing_chain.setCurrentIndex(0)
        self.cb_load_existing_chain.blockSignals(False)

    def _on_open_chain_py_file(self) -> None:
        default_dir = os.path.join(os.getcwd(), "examples", "plugins")
        if not os.path.isdir(default_dir):
            default_dir = os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Chain Plugin (.py)", default_dir, "Python Files (*.py)"
        )
        if not path:
            return
        loaded_name = self.parent_window._load_plugin_from_path(path)
        if not loaded_name:
            QMessageBox.warning(self, "Load Failed", f"Could not load plugin from:\n{path}")
            return
        info = self.parent_window._loaded_plugins.get(loaded_name)
        if not info or info.get("chain") is None:
            QMessageBox.information(
                self,
                "Loaded Standalone Plugin",
                f"Loaded '{loaded_name}', which is a standalone plugin rather than a PluginChain.\n"
                f"Opening '{loaded_name}' in Manage & Run tab.",
            )
            self.refresh_all(select_plugin=loaded_name)
            self.tabs.setCurrentIndex(0)
            return

        self._editing_chain_path = path
        self.refresh_all(select_plugin=loaded_name)
        self._load_chain_into_builder(loaded_name)
        self.tabs.setCurrentIndex(1)

    def _on_select_existing_chain_to_edit(self) -> None:
        chain_name = self.cb_load_existing_chain.currentData()
        if not chain_name:
            self._on_new_blank_chain_clicked()
            return
        self._load_chain_into_builder(chain_name)

    def _save_active_chain_step_edits(self) -> None:
        if 0 <= self._active_chain_step_idx < len(self._chain_steps) and self._chain_step_widgets:
            step_entry = self._chain_steps[self._active_chain_step_idx]
            for k, w in self._chain_step_widgets.items():
                step_entry["params"][k] = self._read_param_widget_value(w)

    def _refresh_chain_steps_list(self, select_row: int = -1) -> None:
        self._save_active_chain_step_edits()
        self.list_chain_steps.blockSignals(True)
        self.list_chain_steps.clear()
        for idx, s in enumerate(self._chain_steps):
            self.list_chain_steps.addItem(f"Step {idx + 1}: {s['target']}")
        self.list_chain_steps.blockSignals(False)

        if 0 <= select_row < len(self._chain_steps):
            self.list_chain_steps.blockSignals(True)
            self.list_chain_steps.setCurrentRow(select_row)
            self.list_chain_steps.blockSignals(False)
            self._on_chain_step_selected(select_row)
        elif self._chain_steps:
            last_idx = len(self._chain_steps) - 1
            self.list_chain_steps.blockSignals(True)
            self.list_chain_steps.setCurrentRow(last_idx)
            self.list_chain_steps.blockSignals(False)
            self._on_chain_step_selected(last_idx)
        else:
            self._active_chain_step_idx = -1
            self._on_chain_step_selected(-1)

    def _on_add_step_to_chain(self) -> None:
        item = self.list_available_for_chain.currentItem()
        if item is None:
            return
        target_name = item.data(Qt.ItemDataRole.UserRole)
        if not target_name:
            return

        info = self.parent_window._loaded_plugins.get(target_name, {})
        params_spec = info.get("params_spec", {}) or {}
        defaults = {}
        for k, spec in params_spec.items():
            defaults[k] = spec.get("default") if isinstance(spec, dict) else spec

        self._save_active_chain_step_edits()
        self._chain_steps.append({
            "target": target_name,
            "params": defaults,
        })
        self._refresh_chain_steps_list(select_row=len(self._chain_steps) - 1)

    def _on_move_chain_step_up(self) -> None:
        row = self.list_chain_steps.currentRow()
        if row <= 0 or row >= len(self._chain_steps):
            return
        self._save_active_chain_step_edits()
        self._chain_steps[row - 1], self._chain_steps[row] = (
            self._chain_steps[row],
            self._chain_steps[row - 1],
        )
        self._active_chain_step_idx = -1
        self._refresh_chain_steps_list(select_row=row - 1)

    def _on_move_chain_step_down(self) -> None:
        row = self.list_chain_steps.currentRow()
        if row < 0 or row >= len(self._chain_steps) - 1:
            return
        self._save_active_chain_step_edits()
        self._chain_steps[row + 1], self._chain_steps[row] = (
            self._chain_steps[row],
            self._chain_steps[row + 1],
        )
        self._active_chain_step_idx = -1
        self._refresh_chain_steps_list(select_row=row + 1)

    def _on_remove_chain_step(self) -> None:
        row = self.list_chain_steps.currentRow()
        if row < 0 or row >= len(self._chain_steps):
            return
        self._active_chain_step_idx = -1
        self._chain_steps.pop(row)
        self._refresh_chain_steps_list(select_row=min(row, len(self._chain_steps) - 1))

    def _on_clear_chain_steps(self) -> None:
        self._active_chain_step_idx = -1
        self._chain_steps.clear()
        self._refresh_chain_steps_list(select_row=-1)

    def _on_chain_step_selected(self, row: int) -> None:
        if self._active_chain_step_idx != row:
            self._save_active_chain_step_edits()
        self._active_chain_step_idx = row

        old_host = self.chain_step_scroll.takeWidget()
        if old_host is not None:
            old_host.hide()
            old_host.setParent(None)
            old_host.deleteLater()

        self.chain_step_form_host = QWidget()
        self.chain_step_form_layout = QFormLayout(self.chain_step_form_host)
        self._chain_step_widgets.clear()

        if row < 0 or row >= len(self._chain_steps):
            self.lbl_chain_step_title.setText("Select a pipeline step to configure its default parameters.")
            self.btn_chain_step_docs.setEnabled(False)
            self.chain_step_scroll.setWidget(self.chain_step_form_host)
            return

        step_entry = self._chain_steps[row]
        target_name = step_entry["target"]
        info = self.parent_window._loaded_plugins.get(target_name, {})
        self.lbl_chain_step_title.setText(f"Step {row + 1}: {target_name}")
        self.btn_chain_step_docs.setEnabled(bool(info))

        params_spec = info.get("params_spec", {}) or {}
        step_params = step_entry.get("params", {})

        if not params_spec:
            self.chain_step_form_layout.addRow(QLabel("No configurable parameters for this step."))
            self.chain_step_scroll.setWidget(self.chain_step_form_host)
            return

        for key, spec in params_spec.items():
            val = step_params.get(key, spec.get("default") if isinstance(spec, dict) else spec)
            w = self._create_param_editor_widget(key, spec, val)
            lbl_txt = spec.get("label", key) if isinstance(spec, dict) else key
            lbl_w = QLabel(str(lbl_txt) + ":")
            if isinstance(spec, dict) and spec.get("tooltip"):
                lbl_w.setToolTip(str(spec["tooltip"]))
            self.chain_step_form_layout.addRow(lbl_w, w)
            self._chain_step_widgets[key] = w

        setup_preset_overrides(params_spec, self._chain_step_widgets, self._set_param_widget_value)

        self.chain_step_scroll.setWidget(self.chain_step_form_host)

    def _on_open_chain_step_docs(self) -> None:
        if 0 <= self._active_chain_step_idx < len(self._chain_steps):
            t_name = self._chain_steps[self._active_chain_step_idx]["target"]
            info = self.parent_window._loaded_plugins.get(t_name)
            if info:
                dlg = PluginDocDialog(t_name, info, parent=self)
                dlg.exec()

    def build_chain_object(self) -> Optional[PluginChain]:
        self._save_active_chain_step_edits()
        if not self._chain_steps:
            QMessageBox.warning(self, "Empty Chain", "Please add at least one plugin step to the chain.")
            return None
        name = self.ed_chain_name.text().strip() or "Custom Plugin Chain"
        cat = self.ed_chain_category.text().strip() or "Chains"
        desc = self.ed_chain_desc.text().strip()

        chain = PluginChain(name=name, description=desc, category=cat)
        for s in self._chain_steps:
            chain.add(s["target"], **copy.deepcopy(s.get("params", {})))
        return chain

    def _on_save_or_update_existing_chain(self) -> None:
        chain = self.build_chain_object()
        if chain is None:
            return
        orig_name = self._editing_chain_orig_name
        py_path = self._editing_chain_path

        # If this chain is not backed by a .py file yet, prompt user to save as .py
        if not py_path or not os.path.isfile(py_path):
            self._on_save_chain_as_py()
            return

        reg_name = self.parent_window.register_chain_plugin(
            chain,
            path=py_path,
            replace_name=orig_name,
        )
        self._editing_chain_orig_name = reg_name

        file_saved = False
        if py_path and os.path.isfile(py_path):
            try:
                chain.set_resolver(self.parent_window._resolve_plugin_target)
                code = chain.to_python_code(standalone=self.chk_chain_standalone.isChecked())
                with open(py_path, "w", encoding="utf-8") as f:
                    f.write(code)
                file_saved = True
                if reg_name in self.parent_window._loaded_plugins:
                    self.parent_window._loaded_plugins[reg_name]["mtime"] = os.path.getmtime(py_path)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "File Save Warning",
                    f"Updated chain in IQView, but could not write to .py file:\n{exc}",
                )

        self.refresh_all(select_plugin=reg_name)
        self._update_editing_chain_status()

        save_msg = f"\nand saved updated code directly to:\n{py_path}" if file_saved else ""
        QMessageBox.information(
            self,
            "Chain Updated",
            f"Chain '{reg_name}' updated successfully in IQView{save_msg}.",
        )

    def _on_register_chain_in_session(self) -> Optional[str]:
        chain = self.build_chain_object()
        if chain is None:
            return None
        reg_name = self.parent_window.register_chain_plugin(
            chain,
            path=self._editing_chain_path,
            replace_name=self._editing_chain_orig_name,
        )
        self._editing_chain_orig_name = reg_name
        self.refresh_all(select_plugin=reg_name)
        self._update_editing_chain_status()
        return reg_name

    def _on_register_and_run_chain(self) -> None:
        reg_name = self._on_register_chain_in_session()
        if not reg_name:
            return
        scope = self.cb_studio_scope.currentData() or "view"
        self.parent_window.run_plugin(reg_name, scope=scope)
        self.refresh_all(select_plugin=reg_name)

    def _on_save_chain_as_py(self) -> None:
        chain = self.build_chain_object()
        if chain is None:
            return
        chain.set_resolver(self.parent_window._resolve_plugin_target)
        standalone = self.chk_chain_standalone.isChecked()
        code = chain.to_python_code(standalone=standalone)

        if self._editing_chain_path and os.path.isfile(self._editing_chain_path):
            default_path = self._editing_chain_path
        else:
            safe_slug = "".join(c if c.isalnum() else "_" for c in chain.name.lower()).strip("_") or "custom_chain"
            default_dir = os.path.join(os.getcwd(), "examples", "plugins")
            if not os.path.isdir(default_dir):
                default_dir = os.getcwd()
            default_path = os.path.join(default_dir, f"{safe_slug}.py")

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Chain as Python Plugin (.py)", default_path, "Python Files (*.py)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)

        # Update saved session parameters so stale params from old saves don't resurrect
        params_spec = chain.get_combined_params_spec()
        active_params = {
            k: (spec.get("default") if isinstance(spec, dict) else spec)
            for k, spec in params_spec.items()
        }
        if hasattr(self.parent_window, "save_plugin_params"):
            self.parent_window.save_plugin_params(chain.name, active_params)

        loaded_name = self.parent_window._load_plugin_from_path(path)
        if loaded_name:
            self._editing_chain_orig_name = loaded_name
            self._editing_chain_path = path
            self.refresh_all(select_plugin=loaded_name)
            self._update_editing_chain_status()
            QMessageBox.information(
                self, "Chain Saved & Loaded",
                f"Saved chain to:\n{path}\n\nand loaded '{loaded_name}' into IQView."
            )

    # ==================================================================
    # Template Generator Logic (Tab 3)
    # ==================================================================

    def _on_template_preset_changed(self) -> None:
        tpl_id = self.cb_template_type.currentData() or "plot_1d"
        self.tbl_tpl_params.blockSignals(True)
        self.tbl_tpl_params.setRowCount(0)

        presets = {
            "plot_1d": (
                "Custom Envelope & State Plotter",
                "Analysis",
                "Computes smoothed envelope and plots 1D trace with shaded state regions.",
                [
                    ("smooth_samples", "int", "32", "Smoothing Window (samples)", "Moving average window length."),
                    ("threshold_db", "float", "6.0", "Threshold (dB)", "Detection threshold above median floor."),
                ],
            ),
            "batch_detector": (
                "Custom Batch Burst Detector",
                "Detection",
                "Scans wideband IQ in batches, places Rect overlays, and attaches o.iq.",
                [
                    ("threshold_db", "float", "10.0", "Threshold (dB)", "SNR threshold above noise floor."),
                    ("margin", "int", "0", "Margin (samples)", "Extra safeguard samples on each side of burst."),
                ],
            ),
            "overlay_processor": (
                "Custom Burst Overlay Analyzer",
                "Demodulation",
                "Processes every Rect overlay in scope using o.get_samples() and annotates metadata.",
                [
                    ("normalize", "bool", "True", "Normalize Burst", "Normalize burst amplitude before processing."),
                    ("open_plots", "bool", "False", "Open Debug Plots", "Plot processed burst waveforms."),
                ],
            ),
            "native_tabs": (
                "Custom Native Tab Launcher",
                "Analysis",
                "Extracts burst IQ and opens native Time Domain and Constellation tabs.",
                [
                    ("open_constellation", "bool", "True", "Open Constellation", "Open Constellation tab."),
                ],
            ),
            "blank": (
                "My Custom Plugin",
                "Custom",
                "Minimal custom IQView plugin.",
                [
                    ("gain_db", "float", "0.0", "Gain (dB)", "Example float parameter."),
                ],
            ),
        }

        name, cat, desc, rows = presets.get(tpl_id, presets["blank"])
        self.ed_tpl_name.setText(name)
        self.ed_tpl_category.setText(cat)
        self.ed_tpl_desc.setText(desc)

        for r_vals in rows:
            self._append_template_param_row(*r_vals)

        self.tbl_tpl_params.blockSignals(False)
        self._update_template_code_preview()

    def _append_template_param_row(
        self, key: str, ptype: str, default: str, label: str, tooltip: str
    ) -> None:
        r = self.tbl_tpl_params.rowCount()
        self.tbl_tpl_params.insertRow(r)
        for c, val in enumerate([key, ptype, default, label, tooltip]):
            self.tbl_tpl_params.setItem(r, c, QTableWidgetItem(str(val)))

    def _on_add_template_param_row(self) -> None:
        idx = self.tbl_tpl_params.rowCount() + 1
        self._append_template_param_row(
            f"param_{idx}", "float", "1.0", f"Parameter {idx}", "Parameter description."
        )
        self._update_template_code_preview()

    def _on_remove_template_param_row(self) -> None:
        row = self.tbl_tpl_params.currentRow()
        if row >= 0:
            self.tbl_tpl_params.removeRow(row)
            self._update_template_code_preview()

    def _update_template_code_preview(self) -> None:
        tpl_id = self.cb_template_type.currentData() or "blank"
        name = self.ed_tpl_name.text().strip() or "My Custom Plugin"
        cat = self.ed_tpl_category.text().strip() or "Custom"
        desc = self.ed_tpl_desc.text().strip() or ""

        params_dict_lines = ["PLUGIN_PARAMS = {"]
        param_reads = []
        doc_table_rows = []
        for r in range(self.tbl_tpl_params.rowCount()):
            key = (self.tbl_tpl_params.item(r, 0).text() if self.tbl_tpl_params.item(r, 0) else f"p{r}").strip()
            ptype = (self.tbl_tpl_params.item(r, 1).text() if self.tbl_tpl_params.item(r, 1) else "float").strip()
            def_raw = (self.tbl_tpl_params.item(r, 2).text() if self.tbl_tpl_params.item(r, 2) else "0").strip()
            label = (self.tbl_tpl_params.item(r, 3).text() if self.tbl_tpl_params.item(r, 3) else key).strip()
            tip = (self.tbl_tpl_params.item(r, 4).text() if self.tbl_tpl_params.item(r, 4) else "").strip()

            if ptype == "int":
                try:
                    def_repr = repr(int(float(def_raw)))
                except ValueError:
                    def_repr = "0"
                cast_fn = "int"
            elif ptype == "float":
                try:
                    def_repr = repr(float(def_raw))
                except ValueError:
                    def_repr = "0.0"
                cast_fn = "float"
            elif ptype == "bool":
                def_repr = "True" if def_raw.lower() in ("true", "1", "yes") else "False"
                cast_fn = "bool"
            else:
                def_repr = repr(def_raw)
                cast_fn = "str"

            params_dict_lines.append(
                f"    {key!r}: {{\"type\": {ptype!r}, \"default\": {def_repr}, \"label\": {label!r}, \"tooltip\": {tip!r}}},"
            )
            param_reads.append(f"    {key} = {cast_fn}(info.params.get({key!r}, {def_repr}))")
            doc_table_rows.append(
                f"| **{label}** (`{key}`) | `{ptype}` | `{def_repr}` | {tip or '—'} |"
            )
        params_dict_lines.append("}")
        params_block = "\n".join(params_dict_lines)
        reads_block = "\n".join(param_reads) if param_reads else "    pass"

        if doc_table_rows:
            doc_params_section = (
                "### Parameters\n\n"
                "| Parameter | Type | Default | Description |\n"
                "| :--- | :--- | :--- | :--- |\n"
                + "\n".join(doc_table_rows)
            )
        else:
            doc_params_section = "### Parameters\n\n*This plugin has no configurable parameters.*"

        if tpl_id == "plot_1d":
            extra_flags = "PLUGIN_NEEDS_WIDEBAND_IQ = True"
            doc_op_section = (
                "### Operation & Algorithm\n\n"
                "1. **Power Envelope**: Computes instantaneous power `|x[n]|²` over the active scope.\n"
                "2. **Moving-Average Smoothing**: Convolves the instantaneous power with a rectangular window.\n"
                "3. **Threshold Comparison & Plotting**: Estimates the median noise floor and opens an interactive 1D plot tab."
            )
            body = f"""def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()
{reads_block}
    if samples is None or len(samples) == 0:
        return result

    pwr = np.abs(samples) ** 2
    win = max(1, int(locals().get("smooth_samples", 32)))
    env = np.convolve(pwr, np.ones(win) / win, mode="same")
    noise_floor = float(np.median(env)) + 1e-20
    thresh = noise_floor * (10.0 ** (float(locals().get("threshold_db", 6.0)) / 10.0))

    t_axis = info.t_start + np.arange(len(env)) / info.sample_rate
    result.set_plot_tab_title(PLUGIN_NAME)
    result.add_plot(
        title="Envelope vs Threshold",
        y={{"Envelope": env, "Threshold": np.full_like(env, thresh)}},
        x=t_axis,
        fs=info.sample_rate,
        x_label="Time",
        x_units="s",
        y_label="Power (linear)",
    )
    return result
"""
        elif tpl_id == "batch_detector":
            extra_flags = "PLUGIN_NEEDS_WIDEBAND_IQ = True\nPLUGIN_BATCH_SECONDS = 1.0"
            doc_op_section = (
                "### Operation & Algorithm\n\n"
                "1. **Batch Streaming**: Processes long recordings in `PLUGIN_BATCH_SECONDS` chunks to bound memory usage.\n"
                "2. **Adaptive Thresholding**: Estimates noise floor from the 25th percentile power and detects contiguous regions above threshold.\n"
                "3. **Overlay Creation & Zero-Copy IQ**: Emits locked `Rect` overlays and attaches `r.iq` and `r.fs` for downstream plugins."
            )
            body = f"""def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()
{reads_block}
    if samples is None or len(samples) == 0:
        return result

    pwr = np.abs(samples) ** 2
    noise_floor = float(np.percentile(pwr, 25.0)) + 1e-20
    thresh = noise_floor * (10.0 ** (float(locals().get("threshold_db", 10.0)) / 10.0))
    margin_samp = max(0, int(locals().get("margin", 0)))

    above = pwr >= thresh
    padded = np.concatenate([[False], above, [False]])
    diffs = np.diff(padded.astype(np.int8))
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]

    for s0, s1 in zip(starts, ends):
        if s1 - s0 < 16:
            continue
        a = max(0, int(s0) - margin_samp)
        b = min(len(samples), int(s1) + margin_samp)
        t0 = info.t_start + a / info.sample_rate
        t1 = info.t_start + b / info.sample_rate
        r = Rect(t0, info.f_start, t1, info.f_end, display_str="Burst")
        r.iq = samples[a:b].copy()
        r.fs = float(info.sample_rate)
        result.add(r)
    return result
"""
        elif tpl_id == "overlay_processor":
            extra_flags = "PLUGIN_NEEDS_WIDEBAND_IQ = False"
            doc_op_section = (
                "### Operation & Algorithm\n\n"
                "1. **Overlay Iteration**: Iterates over all `Rect` overlays in `info.overlays`.\n"
                "2. **Baseband Extraction**: Calls `o.get_samples(samples, info)` to reuse cached `o.iq` or perform lazy DDC.\n"
                "3. **In-Place Annotation**: Updates each overlay's `metadata` and `hover_str` via `result.update(o.id, ...)`."
            )
            body = f"""def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()
{reads_block}
    for idx, o in enumerate(info.overlays):
        if o._shape_name() != "RECT":
            continue
        burst_iq, burst_fs = o.get_samples(samples, info)
        if burst_iq is None or len(burst_iq) == 0:
            continue
        peak_db = float(10.0 * np.log10(np.max(np.abs(burst_iq) ** 2) + 1e-20))
        new_meta = dict(o.metadata or {{}})
        new_meta["peak_db"] = round(peak_db, 2)
        result.update(o.id, metadata=new_meta, hover_str=f"Peak: {{peak_db:.1f}} dB")
    return result
"""
        elif tpl_id == "native_tabs":
            extra_flags = "PLUGIN_NEEDS_WIDEBAND_IQ = True"
            doc_op_section = (
                "### Operation & Algorithm\n\n"
                "1. **Signal Extraction**: Reads complex IQ samples from the selected scope.\n"
                "2. **Native Tab Launch**: Opens IQView's built-in Time Domain and Constellation analysis tabs via `PluginResult`."
            )
            body = f"""def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()
{reads_block}
    if samples is not None and len(samples) > 0:
        result.open_time_domain(samples, fs=info.sample_rate, t_start=info.t_start, title=f"{{PLUGIN_NAME}} — Time")
        if bool(locals().get("open_constellation", True)):
            result.open_constellation(samples, fs=info.sample_rate, title=f"{{PLUGIN_NAME}} — Constellation")
    return result
"""
        else:
            extra_flags = "PLUGIN_NEEDS_WIDEBAND_IQ = True"
            doc_op_section = (
                "### Operation & Algorithm\n\n"
                "Describe the signal processing stages, inputs, and outputs of this plugin here."
            )
            body = f"""def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()
{reads_block}
    result.log(f"Ran {{PLUGIN_NAME}} on {{len(samples) if samples is not None else 0}} samples")
    return result
"""

        code = f'''"""Custom IQView Plugin: {name}"""

import numpy as np
from iqview import PluginResult
from iqview.overlays import Rect

PLUGIN_NAME = {name!r}
PLUGIN_DESCRIPTION = {desc!r}
PLUGIN_CATEGORY = {cat!r}
{extra_flags}

PLUGIN_DOC = """# {name}

{desc}

{doc_op_section}

{doc_params_section}
"""

{params_block}


{body}'''
        self.ed_tpl_code.setPlainText(code)
        self._update_template_doc_live_preview()

    def _extract_plugin_doc_from_code(self, code_text: str) -> str:
        m = re.search(
            r'PLUGIN_DOC\s*=\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')',
            code_text,
            re.DOTALL,
        )
        if m:
            content = m.group(1) if m.group(1) is not None else m.group(2)
            return content.strip()
        return ""

    def _update_template_doc_live_preview(self) -> None:
        if not hasattr(self, "tpl_doc_preview"):
            return
        p = self.palette_obj
        code_text = self.ed_tpl_code.toPlainText()
        doc_body = self._extract_plugin_doc_from_code(code_text)

        m_name = re.search(r'PLUGIN_NAME\s*=\s*["\']([^"\']+)["\']', code_text)
        m_cat = re.search(r'PLUGIN_CATEGORY\s*=\s*["\']([^"\']+)["\']', code_text)
        m_wb = re.search(r'PLUGIN_NEEDS_WIDEBAND_IQ\s*=\s*(True|False)', code_text)

        name = m_name.group(1) if m_name else (self.ed_tpl_name.text().strip() or "Custom Plugin")
        cat = m_cat.group(1) if m_cat else (self.ed_tpl_category.text().strip() or "Custom")
        iq_mode = (
            "Wideband IQ"
            if (not m_wb or m_wb.group(1) == "True")
            else "Overlay Baseband IQ (o.iq)"
        )

        if not doc_body:
            m_desc = re.search(r'PLUGIN_DESCRIPTION\s*=\s*["\']([^"\']+)["\']', code_text)
            desc = m_desc.group(1) if m_desc else self.ed_tpl_desc.text().strip()
            doc_body = (
                f"# {name}\n\n"
                f"{desc}\n\n"
                f"*Define `PLUGIN_DOC = \"\"\"...\"\"\"` in the code editor to customize this live documentation preview.*"
            )

        is_html = bool(re.search(r"<(?:h[1-6]|p|div|table|ol|ul|br)\b", doc_body, re.IGNORECASE))
        if not is_html:
            full_md = (
                f"**Category:** {cat} | **Type:** Custom Plugin (.py) | **IQ Mode:** {iq_mode}\n\n"
                f"---\n\n"
                f"{doc_body}"
            )
            self.tpl_doc_preview.setMarkdown(full_md)
        else:
            full_html = f"""
            <div style="font-family: 'Segoe UI', sans-serif; line-height: 1.45; color: {p.text_main};">
                <div style="margin-bottom: 10px; color: {p.text_dim}; font-size: 11px;">
                    <b>Category:</b> {_html.escape(cat)} &nbsp;|&nbsp;
                    <b>Type:</b> Custom Plugin (.py) &nbsp;|&nbsp;
                    <b>IQ Mode:</b> {_html.escape(iq_mode)}
                </div>
                {doc_body}
            </div>
            """
            self.tpl_doc_preview.setHtml(full_html)

    def _on_save_and_load_template(self) -> None:
        code = self.ed_tpl_code.toPlainText()
        name = self.ed_tpl_name.text().strip() or "custom_plugin"
        safe_slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_") or "custom_plugin"
        default_dir = os.path.join(os.getcwd(), "examples", "plugins")
        if not os.path.isdir(default_dir):
            default_dir = os.getcwd()
        default_path = os.path.join(default_dir, f"{safe_slug}.py")

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Custom Plugin (.py)", default_path, "Python Files (*.py)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)

        loaded_name = self.parent_window._load_plugin_from_path(path)
        if loaded_name:
            self.refresh_all(select_plugin=loaded_name)
            self.tabs.setCurrentIndex(0)
            QMessageBox.information(
                self, "Plugin Created & Loaded",
                f"Saved plugin to:\n{path}\n\nand loaded '{loaded_name}' into IQView."
            )


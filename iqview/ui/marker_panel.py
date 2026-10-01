from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap
import importlib.resources
import os
import re
from .widgets import FormattedLineEdit, DoubleClickButton, format_tooltip_with_keybind, get_theme_icon
from .themes import get_palette

class MarkerPanel(QFrame):
    interactionModeChanged = pyqtSignal(str) # 'TIME', 'FREQ', 'ZOOM', 'OVERLAY', …
    resetZoomRequested = pyqtSignal()
    markerClearRequested = pyqtSignal(str)
    clearOverlaysRequested = pyqtSignal()

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(140)
        self.header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self.mono_font = QFont("Consolas", 10)
        
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 8, 15, 8)
        self.main_layout.setSpacing(15)

        # State
        self.current_mode = 'TIME'
        self.last_marker_mode = 'TIME'
        self.lock_states = {
            'TIME':   {'delta': False, 'center': False, 'm1': False, 'm2': False},
            'FREQ':   {'delta': False, 'center': False, 'm1': False, 'm2': False},
            'FILTER': {'delta': False, 'center': False, 'm1': False, 'm2': False}
        }

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(6)
        self.main_layout.addLayout(self.mode_btn_layout, 0)

        # 1. Time (Top-Left)
        self.btn_marker_time = DoubleClickButton("")
        self.btn_marker_time.setObjectName("mode_btn")
        self.btn_marker_time.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)
        
        # 1b. Time Endless
        self.btn_marker_time_endless = DoubleClickButton("")
        self.btn_marker_time_endless.setObjectName("mode_btn")
        self.btn_marker_time_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time_endless, 0, 1)

        # 2. Zoom
        self.btn_zoom = QPushButton("")
        self.btn_zoom.setIcon(self._get_icon("zoom_mode"))
        self.btn_zoom.setIconSize(QSize(32, 32))
        self.btn_zoom.setObjectName("mode_btn")
        self.btn_zoom.setToolTip("Zoom Mode (Rubberband)")
        self.btn_zoom.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_zoom, 0, 2)
        
        # 3. Home
        self.btn_home = QPushButton("")
        self.btn_home.setIcon(self._get_icon("reset_zoom"))
        self.btn_home.setIconSize(QSize(32, 32))
        self.btn_home.setObjectName("mode_btn")
        self.btn_home.setToolTip("Reset Zoom (Home)")
        self.mode_btn_layout.addWidget(self.btn_home, 0, 3)

        # --- Row 2 ---
        
        # 4. Freq
        self.btn_marker_freq = DoubleClickButton("")
        self.btn_marker_freq.setObjectName("mode_btn")
        self.btn_marker_freq.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq, 1, 0)
        
        # 4b. Freq Endless
        self.btn_marker_freq_endless = DoubleClickButton("")
        self.btn_marker_freq_endless.setObjectName("mode_btn")
        self.btn_marker_freq_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq_endless, 1, 1)

        # 5. Move
        self.btn_move = QPushButton("")
        self.btn_move.setIcon(self._get_icon("free_move_mode"))
        self.btn_move.setIconSize(QSize(32, 32))
        self.btn_move.setObjectName("mode_btn")
        self.btn_move.setToolTip("Free Move Mode (Pan)")
        self.btn_move.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_move, 1, 2)
        
        # 6. BPF Mode
        self.btn_bpf = DoubleClickButton("")
        self.btn_bpf.setIcon(self._get_icon("bpf_selection_mode"))
        self.btn_bpf.setIconSize(QSize(32, 32))
        self.btn_bpf.setObjectName("mode_btn")
        self.btn_bpf.setToolTip("BPF Selection Mode (Double-click to clear)")
        self.btn_bpf.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_bpf, 1, 3)

        # 7. Overlay Mode
        self.btn_overlay = QPushButton("")
        self.btn_overlay.setIcon(self._get_icon("overlays"))
        self.btn_overlay.setIconSize(QSize(32, 32))
        self.btn_overlay.setObjectName("mode_btn")
        self.btn_overlay.setToolTip("Overlay Mode — click or drag to place a shape")
        self.btn_overlay.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_overlay, 0, 4)

        # 8. Plugins Mode
        self.btn_plugins = QPushButton("")
        self.btn_plugins.setIcon(self._get_icon("plugins"))
        self.btn_plugins.setIconSize(QSize(32, 32))
        self.btn_plugins.setObjectName("mode_btn")
        self.btn_plugins.setToolTip("Plugins Panel — manage and run plugins")
        self.btn_plugins.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_plugins, 1, 4)

        # Re-assign BPF to row 1, col 3 (push it down) — already done above

        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        
        # Mutual Exclusion Group
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_freq)
        self.mode_group.addButton(self.btn_marker_time_endless)
        self.mode_group.addButton(self.btn_marker_freq_endless)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.addButton(self.btn_bpf)
        self.mode_group.addButton(self.btn_overlay)
        self.mode_group.addButton(self.btn_plugins)
        self.mode_group.setExclusive(True)

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_freq.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ'))
        self.btn_marker_time_endless.clicked.connect(lambda: self.interactionModeChanged.emit('TIME_ENDLESS'))
        self.btn_marker_freq_endless.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ_ENDLESS'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        self.btn_bpf.clicked.connect(lambda: self.interactionModeChanged.emit('FILTER'))
        self.btn_overlay.clicked.connect(lambda: self.interactionModeChanged.emit('OVERLAY'))
        self.btn_plugins.clicked.connect(lambda: self.interactionModeChanged.emit('PLUGINS'))
        
        self.btn_marker_time.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME'))
        self.btn_marker_freq.doubleClicked.connect(lambda: self.markerClearRequested.emit('FREQ'))
        self.btn_marker_time_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME_ENDLESS'))
        self.btn_marker_freq_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit('FREQ_ENDLESS'))
        self.btn_bpf.doubleClicked.connect(lambda: self.markerClearRequested.emit('FILTER'))

        # --- Data Display Stack ---
        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack, 1)

        # Page 0: Fixed 2-marker layout
        self.fixed_widget = QWidget()
        self.stack.addWidget(self.fixed_widget)
        self.grid = QGridLayout(self.fixed_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)

        # Table Headers — Marker 1 and Marker 2 are clickable lock toggles,
        # same style as the Delta and Center buttons.
        self.grid.addWidget(QLabel(""), 0, 0) # Top-left empty

        self.btn_lock_m1 = QPushButton("Marker 1")
        self.btn_lock_m1.setFont(self.header_font)
        self.btn_lock_m1.setCheckable(True)
        self.grid.addWidget(self.btn_lock_m1, 0, 1, Qt.AlignmentFlag.AlignCenter)

        self.btn_lock_m2 = QPushButton("Marker 2")
        self.btn_lock_m2.setFont(self.header_font)
        self.btn_lock_m2.setCheckable(True)
        self.grid.addWidget(self.btn_lock_m2, 0, 2, Qt.AlignmentFlag.AlignCenter)

        # Delta Header (Combined with Lock)
        self.btn_lock_delta = QPushButton("Delta (Δ)")
        self.btn_lock_delta.setFont(self.header_font)
        self.btn_lock_delta.setCheckable(True)
        self.grid.addWidget(self.btn_lock_delta, 0, 3)

        # Center Header (Combined with Lock)
        self.btn_lock_center = QPushButton("Center")
        self.btn_lock_center.setFont(self.header_font)
        self.btn_lock_center.setCheckable(True)
        self.grid.addWidget(self.btn_lock_center, 0, 4)

        # Side labels (Row names)
        self.row1_label = QLabel("Samples")
        self.row2_label = QLabel("Time (sec)")
        self.row3_label = QLabel("1/T (Hz)")
        self.row1_label.setObjectName("header_label")
        self.row2_label.setObjectName("header_label")
        self.row3_label.setObjectName("header_label")
        self.grid.addWidget(self.row1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row3_label, 3, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Edit Widgets
        self.widgets = []
        for i in range(2):
            sam_edit = FormattedLineEdit(); sam_edit.setFixedWidth(130); sam_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_edit = FormattedLineEdit(); sec_edit.setFixedWidth(130); sec_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inv_edit = FormattedLineEdit(); inv_edit.setFixedWidth(130); inv_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            sam_edit.setObjectName(f"m{i}_sam")
            sec_edit.setObjectName(f"m{i}_sec")
            inv_edit.setObjectName(f"m{i}_inv")
            
            sam_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            sec_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            inv_edit.setReadOnly(True)  
            
            self.grid.addWidget(sam_edit, 1, i + 1)
            self.grid.addWidget(sec_edit, 2, i + 1)
            self.grid.addWidget(inv_edit, 3, i + 1)
            self.widgets.append({'sam': sam_edit, 'sec': sec_edit, 'inv': inv_edit})

        # Delta/Center Edits
        self.delta_sam = FormattedLineEdit(); self.delta_sam.setFixedWidth(130); self.delta_sam.setObjectName("delta_sam"); self.delta_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sec = FormattedLineEdit(); self.delta_sec.setFixedWidth(130); self.delta_sec.setObjectName("delta_sec"); self.delta_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_inv = FormattedLineEdit(); self.delta_inv.setFixedWidth(130); self.delta_inv.setObjectName("delta_inv"); self.delta_inv.setAlignment(Qt.AlignmentFlag.AlignCenter); self.delta_inv.setReadOnly(True)
        
        self.center_sam = FormattedLineEdit(); self.center_sam.setFixedWidth(130); self.center_sam.setObjectName("center_sam"); self.center_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sec = FormattedLineEdit(); self.center_sec.setFixedWidth(130); self.center_sec.setObjectName("center_sec"); self.center_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_inv = FormattedLineEdit(); self.center_inv.setFixedWidth(130); self.center_inv.setObjectName("center_inv"); self.center_inv.setAlignment(Qt.AlignmentFlag.AlignCenter); self.center_inv.setReadOnly(True)
        
        for w in [self.delta_sam, self.delta_sec, self.center_sam, self.center_sec]:
            w.returnPressed.connect(self.parent_window.marker_edit_finished)
            
        self.grid.addWidget(self.delta_sam, 1, 3); self.grid.addWidget(self.delta_sec, 2, 3); self.grid.addWidget(self.delta_inv, 3, 3)
        self.grid.addWidget(self.center_sam, 1, 4); self.grid.addWidget(self.center_sec, 2, 4); self.grid.addWidget(self.center_inv, 3, 4)

        # Connect locks to parent
        self.btn_lock_m1.toggled.connect(self.on_lock_m1_toggled)
        self.btn_lock_m2.toggled.connect(self.on_lock_m2_toggled)
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)

        # Filter Activation Checkboxes (BPF / BSF)
        self.filter_container = QWidget()
        self.filter_layout = QVBoxLayout(self.filter_container)
        self.filter_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_layout.setSpacing(2)
        
        self.cb_bpf = QCheckBox("BPF")
        self.cb_bsf = QCheckBox("BSF")
        self.cb_bpf.setToolTip("Enable Band-Pass Filter")
        self.cb_bsf.setToolTip("Enable Band-Stop Filter")
        
        for cb in [self.cb_bpf, self.cb_bsf]:
            cb.setEnabled(False)
            cb.clicked.connect(self.on_filter_clicked)
            self.filter_layout.addWidget(cb)
            
        self.filter_container.setFixedWidth(80)
        self.filter_container.setVisible(False)
        self.grid.addWidget(self.filter_container, 1, 5, 2, 1)
        
        # Page 1: Endless Marker List
        self.endless_widget = QWidget()
        self.stack.addWidget(self.endless_widget)
        self.endless_layout = QVBoxLayout(self.endless_widget)
        self.endless_layout.setContentsMargins(0, 0, 0, 0)
        self.endless_layout.setSpacing(2)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 10, 0)
        self.scroll_layout.setSpacing(4)
        self.scroll_layout.addStretch()
        
        self.scroll.setWidget(self.scroll_content)
        self.endless_layout.addWidget(self.scroll)

        # Page 2: Overlay Mode
        self.overlay_widget = QWidget()
        self.stack.addWidget(self.overlay_widget)
        self.overlay_layout = QVBoxLayout(self.overlay_widget)
        self.overlay_layout.setContentsMargins(0, 0, 0, 0)
        self.overlay_layout.setSpacing(2)
        
        # --- Overlay Control Header ---
        self.overlay_control_widget = QWidget()
        self.overlay_control_layout = QHBoxLayout(self.overlay_control_widget)
        self.overlay_control_layout.setContentsMargins(5, 2, 5, 2)
        self.overlay_control_layout.setSpacing(10)
        
        from PyQt6.QtWidgets import QComboBox
        from .overlay import SHAPE_LABELS
        self.cb_overlay_shape = QComboBox()
        for label, shape in SHAPE_LABELS.items():
            self.cb_overlay_shape.addItem(label, userData=shape)
            
        self.btn_manual_overlay = QPushButton("+ Manual Add")
        self.btn_manual_overlay.setFixedHeight(28)
        self.btn_manual_overlay.setMinimumWidth(110)
        self.btn_manual_overlay.setStyleSheet("QPushButton { padding: 3px 8px; }")
        self.btn_manual_overlay.clicked.connect(self._on_manual_overlay_add)
        
        self.btn_clear_overlays_overlay = QPushButton("Clear All")
        self.btn_clear_overlays_overlay.setFixedHeight(28)
        self.btn_clear_overlays_overlay.setMinimumWidth(90)
        self.btn_clear_overlays_overlay.setStyleSheet("QPushButton { padding: 3px 8px; }")
        self.btn_clear_overlays_overlay.clicked.connect(lambda: self.parent_window.clear_overlays())
        
        self.overlay_control_layout.addWidget(QLabel("Place Shape:"))
        self.overlay_control_layout.addWidget(self.cb_overlay_shape, 1)
        self.overlay_control_layout.addWidget(self.btn_manual_overlay)
        self.overlay_control_layout.addWidget(self.btn_clear_overlays_overlay)
        
        self.overlay_layout.addWidget(self.overlay_control_widget)
        
        # --- Overlay Scroll Area ---
        self.overlay_scroll = QScrollArea()
        self.overlay_scroll.setWidgetResizable(True)
        self.overlay_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.overlay_scroll.setStyleSheet("background: transparent;")
        
        self.overlay_scroll_content = QWidget()
        self.overlay_scroll_layout = QVBoxLayout(self.overlay_scroll_content)
        self.overlay_scroll_layout.setContentsMargins(0, 0, 10, 0)
        self.overlay_scroll_layout.setSpacing(4)
        self.overlay_scroll_layout.addStretch()
        
        self.overlay_scroll.setWidget(self.overlay_scroll_content)
        self.overlay_layout.addWidget(self.overlay_scroll)

        # Page 3: Plugins Mode
        self.plugins_widget = QWidget()
        self.stack.addWidget(self.plugins_widget)
        self.plugins_layout = QVBoxLayout(self.plugins_widget)
        self.plugins_layout.setContentsMargins(0, 0, 0, 0)
        self.plugins_layout.setSpacing(2)
        
        # --- Plugins Control Header (Quick-Run Bar + Studio + Scope) ---
        self.plugins_control_widget = QWidget()
        self.plugins_control_layout = QHBoxLayout(self.plugins_control_widget)
        self.plugins_control_layout.setContentsMargins(5, 2, 5, 2)
        self.plugins_control_layout.setSpacing(6)

        self.cb_quick_plugin = QComboBox()
        self.cb_quick_plugin.setFixedHeight(28)
        self.cb_quick_plugin.setMinimumWidth(180)
        self.cb_quick_plugin.setToolTip("Quick-select a plugin or chain to run/configure")

        self.btn_quick_run = QPushButton("▶ Run")
        self.btn_quick_run.setFixedHeight(28)
        self.btn_quick_run.setToolTip("Run the selected plugin in the active scope")
        self.btn_quick_run.setStyleSheet(
            "QPushButton { color: #00cc66; font-weight: bold; border: 1px solid #00cc66; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: rgba(0,204,102,0.2); }"
        )
        self.btn_quick_run.clicked.connect(self._on_quick_run_clicked)

        self.btn_quick_config = QPushButton("⚙")
        self.btn_quick_config.setFixedSize(30, 28)
        self.btn_quick_config.setStyleSheet("QPushButton { padding: 0px; font-size: 15px; font-weight: bold; }")
        self.btn_quick_config.setToolTip("Configure selected plugin parameters")
        self.btn_quick_config.clicked.connect(self._on_quick_config_clicked)
        
        self.cb_plugin_scope = QComboBox()
        self.cb_plugin_scope.setFixedHeight(28)
        self.cb_plugin_scope.addItem("Scope: Current View", userData="view")
        self.cb_plugin_scope.addItem("Scope: Between Markers", userData="markers")
        self.cb_plugin_scope.addItem("Scope: Full File", userData="full_file")
        self.cb_plugin_scope.setToolTip(
            "Choose time/frequency range passed to plugins:\n"
            "• Current View: visible spectrogram viewport\n"
            "• Between Markers: M1..M2 time/frequency markers (falls back to view)\n"
            "• Full File: entire recording from 0s to end"
        )

        self.btn_plugin_studio = QPushButton("Plugin Studio…")
        self.btn_plugin_studio.setFixedHeight(28)
        self.btn_plugin_studio.setStyleSheet("QPushButton { padding: 3px 8px; font-weight: bold; }")
        self.btn_plugin_studio.setToolTip("Open Plugin Studio (Manage & Run, Chain Builder, Template Generator)")
        self.btn_plugin_studio.clicked.connect(lambda: self.parent_window.open_plugin_studio(initial_tab=0))

        self.btn_load_plugin = QPushButton("Load .py...")
        self.btn_load_plugin.setFixedHeight(28)
        self.btn_load_plugin.setMinimumWidth(85)
        self.btn_load_plugin.setStyleSheet("QPushButton { padding: 3px 8px; }")
        self.btn_load_plugin.clicked.connect(self.parent_window.load_plugin)
        
        self.btn_clear_overlays_plugins = QPushButton("Clear All")
        self.btn_clear_overlays_plugins.setFixedHeight(28)
        self.btn_clear_overlays_plugins.setMinimumWidth(75)
        self.btn_clear_overlays_plugins.setStyleSheet("QPushButton { padding: 3px 8px; }")
        self.btn_clear_overlays_plugins.clicked.connect(lambda: self.parent_window.clear_overlays())
        
        self.plugins_control_layout.addWidget(QLabel("Quick Run:"))
        self.plugins_control_layout.addWidget(self.cb_quick_plugin)
        self.plugins_control_layout.addWidget(self.btn_quick_run)
        self.plugins_control_layout.addWidget(self.btn_quick_config)
        self.plugins_control_layout.addStretch()
        self.plugins_control_layout.addWidget(self.cb_plugin_scope)
        self.plugins_control_layout.addWidget(self.btn_plugin_studio)
        self.plugins_control_layout.addWidget(self.btn_load_plugin)
        self.plugins_control_layout.addWidget(self.btn_clear_overlays_plugins)
        
        self.plugins_layout.addWidget(self.plugins_control_widget)

        # --- Active Plugin Overlays Pills Bar ---
        self.plugin_pills_widget = QWidget()
        self.plugin_pills_layout = QHBoxLayout(self.plugin_pills_widget)
        self.plugin_pills_layout.setContentsMargins(6, 1, 6, 1)
        self.plugin_pills_layout.setSpacing(6)
        self.plugin_pills_widget.setVisible(False)
        self.plugins_layout.addWidget(self.plugin_pills_widget)
        
        # --- Plugins Scroll Area ---
        self.plugins_scroll = QScrollArea()
        self.plugins_scroll.setWidgetResizable(True)
        self.plugins_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.plugins_scroll.setStyleSheet("background: transparent;")
        
        self.plugins_scroll_content = QWidget()
        self.plugins_scroll_layout = QVBoxLayout(self.plugins_scroll_content)
        self.plugins_scroll_layout.setContentsMargins(0, 0, 10, 0)
        self.plugins_scroll_layout.setSpacing(4)
        self.plugins_scroll_layout.addStretch()
        
        self.plugins_scroll.setWidget(self.plugins_scroll_content)
        self.plugins_layout.addWidget(self.plugins_scroll)

        # Explicit Default Force
        self.btn_marker_time.setChecked(True)
        self.interactionModeChanged.emit('TIME')

        for btn in [
            self.btn_marker_time, self.btn_marker_time_endless,
            self.btn_marker_freq, self.btn_marker_freq_endless,
            self.btn_zoom, self.btn_move, self.btn_home,
            self.btn_bpf, self.btn_overlay, self.btn_plugins,
            self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center,
            self.cb_bpf, self.cb_bsf,
            self.btn_manual_overlay, self.btn_clear_overlays_overlay,
            self.btn_quick_run, self.btn_quick_config,
            self.btn_plugin_studio,
            self.btn_load_plugin, self.btn_clear_overlays_plugins,
        ]:
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Apply icons for initial (standard) mode
        self._apply_marker_button_icons(waterfall=False)

        # Apply theme (must be done AFTER buttons are initialized)
        self.refresh_theme()

    def _apply_marker_button_icons(self, waterfall):
        """Set button icons, tooltips according to orientation mode."""
        if waterfall:
            self.btn_marker_time.setIcon(self._get_icon("horizontal_markers"))
            self.btn_marker_time_endless.setIcon(self._get_icon("endless_horizontal_markers"))
            self.btn_marker_freq.setIcon(self._get_icon("vertical_markers"))
            self.btn_marker_freq_endless.setIcon(self._get_icon("endless_vertical_markers"))
        else:
            self.btn_marker_time.setIcon(self._get_icon("vertical_markers"))
            self.btn_marker_time_endless.setIcon(self._get_icon("endless_vertical_markers"))
            self.btn_marker_freq.setIcon(self._get_icon("horizontal_markers"))
            self.btn_marker_freq_endless.setIcon(self._get_icon("endless_horizontal_markers"))
        for btn in (self.btn_marker_time, self.btn_marker_time_endless,
                    self.btn_marker_freq, self.btn_marker_freq_endless):
            btn.setIconSize(QSize(32, 32))
        self.update_button_tooltips(waterfall=waterfall)

    def update_button_tooltips(self, waterfall=None):
        """Refresh all button hover tooltips with current keybinds in brackets."""
        if waterfall is None:
            waterfall = self.parent_window.spectrogram_view.is_waterfall if (hasattr(self, 'parent_window') and hasattr(self.parent_window, 'spectrogram_view')) else False
        s = getattr(self.parent_window, 'settings_mgr', None)
        def _kb(key, default):
            return s.get(key, default) if s else default

        time_ori = "horizontal lines" if waterfall else "vertical lines"
        freq_ori = "vertical lines" if waterfall else "horizontal lines"

        self.btn_marker_time.setToolTip(format_tooltip_with_keybind(
            f"Time Markers — {time_ori} (Double-click to clear)", _kb("keybinds/time_markers", "T")))
        self.btn_marker_time_endless.setToolTip(format_tooltip_with_keybind(
            f"Endless Time Markers — {time_ori} (Double-click to clear)", _kb("keybinds/time_endless_markers", "E")))
        self.btn_marker_freq.setToolTip(format_tooltip_with_keybind(
            f"Frequency Markers — {freq_ori} (Double-click to clear)", _kb("keybinds/freq_markers", "F")))
        self.btn_marker_freq_endless.setToolTip(format_tooltip_with_keybind(
            f"Endless Frequency Markers — {freq_ori} (Double-click to clear)", _kb("keybinds/freq_endless_markers", "G")))
        self.btn_zoom.setToolTip(format_tooltip_with_keybind(
            "Zoom Mode (Rubberband)", _kb("keybinds/zoom_mode", "Ctrl"), is_hold=True))
        self.btn_move.setToolTip(format_tooltip_with_keybind(
            "Free Move Mode (Pan)", _kb("keybinds/move_mode", "Space"), is_hold=True))
        self.btn_home.setToolTip(format_tooltip_with_keybind(
            "Reset Zoom (Home)", _kb("keybinds/reset_zoom", "R")))
        self.btn_bpf.setToolTip(format_tooltip_with_keybind(
            "BPF / BSF Selection Mode (Double-click to clear)", _kb("keybinds/filter_mode", "B")))
        self.btn_overlay.setToolTip(format_tooltip_with_keybind(
            "Overlay Mode — click or drag to place a shape", _kb("keybinds/overlay_mode", "O")))
        self.btn_plugins.setToolTip(format_tooltip_with_keybind(
            "Plugins Panel — manage and run plugins", _kb("keybinds/plugins_mode", "P")))

        if hasattr(self, 'btn_lock_m1'):
            self.btn_lock_m1.setToolTip(format_tooltip_with_keybind("Lock Marker 1", _kb("keybinds/lock_m1", "1")))
            self.btn_lock_m2.setToolTip(format_tooltip_with_keybind("Lock Marker 2", _kb("keybinds/lock_m2", "2")))
            self.btn_lock_delta.setToolTip(format_tooltip_with_keybind("Lock Delta (Δ)", _kb("keybinds/lock_delta", "D")))
            self.btn_lock_center.setToolTip(format_tooltip_with_keybind("Lock Center", _kb("keybinds/lock_center", "C")))

        if hasattr(self, 'cb_bpf'):
            self.cb_bpf.setToolTip(format_tooltip_with_keybind("Enable Band-Pass Filter", _kb("keybinds/toggle_bpf", "[")))
            self.cb_bsf.setToolTip(format_tooltip_with_keybind("Enable Band-Stop Filter", _kb("keybinds/toggle_bsf", "]")))

        if hasattr(self, 'btn_manual_overlay'):
            self.btn_manual_overlay.setToolTip(format_tooltip_with_keybind("Manually add an overlay", _kb("keybinds/panel_action", "A")))
            self.btn_clear_overlays_overlay.setToolTip(format_tooltip_with_keybind("Clear all placed overlays", _kb("keybinds/clear_markers", "Backspace")))

        if hasattr(self, 'btn_load_plugin'):
            self.btn_load_plugin.setToolTip(format_tooltip_with_keybind("Load a plugin from file", _kb("keybinds/panel_action", "A")))
            self.btn_clear_overlays_plugins.setToolTip(format_tooltip_with_keybind("Clear all placed overlays", _kb("keybinds/clear_markers", "Backspace")))

    def refresh_waterfall_ui(self):
        """Called from apply_waterfall_mode() when the user toggles the Waterfall setting.
        Swaps button icons and refreshes the current table headers."""
        waterfall = self.parent_window.spectrogram_view.is_waterfall if (hasattr(self, 'parent_window') and hasattr(self.parent_window, 'spectrogram_view')) else False
        self._apply_marker_button_icons(waterfall)
        # Re-apply current mode so row labels also refresh
        self.update_headers(self.current_mode)

    def _get_icon(self, name):
        """Load icon using the current app theme (Light or Dark)."""
        theme = self.parent_window.settings_mgr.get("ui/theme", "Light") if hasattr(self, 'parent_window') else "Light"
        return get_theme_icon(name, theme)

    def _clear_marker_locks(self, mode=None, keep=None):
        """Uncheck all marker-position locks except the one named in `keep`."""
        target_mode = mode if mode else self.current_mode
        if target_mode not in self.lock_states: return

        for key, btn in [
            ('m1',     self.btn_lock_m1),
            ('m2',     self.btn_lock_m2),
            ('delta',  self.btn_lock_delta),
            ('center', self.btn_lock_center),
        ]:
            if key == keep:
                continue
            btn.blockSignals(True)
            btn.setChecked(False)
            self.lock_states[target_mode][key] = False
            btn.blockSignals(False)

    def set_locks_enabled(self, m1_placed, m2_placed):
        """Enable/disable lock buttons based on marker presence."""
        self.btn_lock_m1.setEnabled(m1_placed)
        self.btn_lock_m2.setEnabled(m2_placed)
        
        can_pair_lock = m1_placed and m2_placed
        self.btn_lock_delta.setEnabled(can_pair_lock)
        self.btn_lock_center.setEnabled(can_pair_lock)
        
        # If a marker was removed, ensure its lock is released
        if not m1_placed and self.btn_lock_m1.isChecked(): self.on_lock_m1_toggled(False)
        if not m2_placed and self.btn_lock_m2.isChecked(): self.on_lock_m2_toggled(False)
        if not can_pair_lock:
            if self.btn_lock_delta.isChecked(): self.on_lock_delta_toggled(False)
            if self.btn_lock_center.isChecked(): self.on_lock_center_toggled(False)

    def on_lock_delta_toggled(self, checked):
        self.lock_states[self.current_mode]['delta'] = checked
        if checked:
            self._clear_marker_locks(keep='delta')
        self.parent_window.handle_lock_change('delta', checked)

    def on_lock_center_toggled(self, checked):
        self.lock_states[self.current_mode]['center'] = checked
        if checked:
            self._clear_marker_locks(keep='center')
        self.parent_window.handle_lock_change('center', checked)

    def on_lock_m1_toggled(self, checked):
        self.lock_states[self.current_mode]['m1'] = checked
        if checked:
            self._clear_marker_locks(keep='m1')
        self.parent_window.handle_lock_change('m1', checked)

    def on_lock_m2_toggled(self, checked):
        self.lock_states[self.current_mode]['m2'] = checked
        if checked:
            self._clear_marker_locks(keep='m2')
        self.parent_window.handle_lock_change('m2', checked)

    def on_filter_clicked(self):
        """Handle BPF/BSF exclusivity and notify parent."""
        sender = self.sender()
        if sender == self.cb_bpf and self.cb_bpf.isChecked():
            self.cb_bsf.setChecked(False)
        elif sender == self.cb_bsf and self.cb_bsf.isChecked():
            self.cb_bpf.setChecked(False)
            
        # Determine mode
        mode = None
        if self.cb_bpf.isChecked(): mode = 'bpf'
        elif self.cb_bsf.isChecked(): mode = 'bsf'
        
        self.parent_window.on_filter_changed(mode)

    def flip_m_lock(self):
        """Silently swap the m1/m2 lock buttons when markers cross each other."""
        m1 = self.btn_lock_m1.isChecked()
        m2 = self.btn_lock_m2.isChecked()
        if not m1 and not m2:
            return  # neither locked — nothing to flip
        self.btn_lock_m1.blockSignals(True)
        self.btn_lock_m2.blockSignals(True)
        self.btn_lock_m1.setChecked(m2)
        self.btn_lock_m2.setChecked(m1)
        self.lock_states[self.current_mode]['m1'] = m2
        self.lock_states[self.current_mode]['m2'] = m1
        self.btn_lock_m1.blockSignals(False)
        self.btn_lock_m2.blockSignals(False)

    def update_headers(self, mode):
        # Force exclusion sync
        self.btn_marker_time.blockSignals(True)
        self.btn_marker_freq.blockSignals(True)
        self.btn_marker_time_endless.blockSignals(True)
        self.btn_marker_freq_endless.blockSignals(True)
        self.btn_zoom.blockSignals(True)
        self.btn_move.blockSignals(True)
        self.btn_bpf.blockSignals(True)
        self.btn_overlay.blockSignals(True)
        if hasattr(self, 'btn_plugins'): self.btn_plugins.blockSignals(True)
        
        self.btn_marker_time.setChecked(mode == 'TIME')
        self.btn_marker_freq.setChecked(mode == 'FREQ')
        self.btn_marker_time_endless.setChecked(mode == 'TIME_ENDLESS')
        self.btn_marker_freq_endless.setChecked(mode == 'FREQ_ENDLESS')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        self.btn_bpf.setChecked(mode == 'FILTER')
        self.btn_overlay.setChecked(mode == 'OVERLAY')
        if hasattr(self, 'btn_plugins'): self.btn_plugins.setChecked(mode == 'PLUGINS')
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_freq.blockSignals(False)
        self.btn_marker_time_endless.blockSignals(False)
        self.btn_marker_freq_endless.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)
        self.btn_bpf.blockSignals(False)
        self.btn_overlay.blockSignals(False)
        if hasattr(self, 'btn_plugins'): self.btn_plugins.blockSignals(False)

        self.current_mode = mode
        
        # Keep marker button icons in sync with the current waterfall setting
        waterfall = self.parent_window.spectrogram_view.is_waterfall if (hasattr(self, 'parent_window') and hasattr(self.parent_window, 'spectrogram_view')) else False
        self._apply_marker_button_icons(waterfall)
        
        # Track the last valid marker mode to display in the table
        if mode in ['TIME', 'FREQ', 'TIME_ENDLESS', 'FREQ_ENDLESS', 'FILTER', 'OVERLAY', 'PLUGINS']:
            self.last_marker_mode = mode
            
        display_mode = self.last_marker_mode if mode in ['ZOOM', 'MOVE'] else mode

        if display_mode == 'OVERLAY':
            self.stack.setCurrentIndex(2)
        elif display_mode == 'PLUGINS':
            self.stack.setCurrentIndex(3)
        elif display_mode in ['TIME_ENDLESS', 'FREQ_ENDLESS']:
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)

        if display_mode in ['FREQ', 'FREQ_ENDLESS', 'FILTER']:
            self.row1_label.setText("Bin")
            self.row2_label.setText("Freq (Hz)")
            self.row1_label.show()
            self.row2_label.show()
            
            # Move Frequency widgets back to Row 2
            self.grid.addWidget(self.row1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.widgets[i]['sam'], 1, i + 1)
                self.grid.addWidget(self.widgets[i]['sec'], 2, i + 1)
                self.widgets[i]['sam'].show()
                self.widgets[i]['sec'].show()
            self.grid.addWidget(self.delta_sam, 1, 3); self.delta_sam.show()
            self.grid.addWidget(self.delta_sec, 2, 3); self.delta_sec.show()
            self.grid.addWidget(self.center_sam, 1, 4); self.center_sam.show()
            self.grid.addWidget(self.center_sec, 2, 4); self.center_sec.show()

            if display_mode == 'FILTER':
                # Enable checkboxes only if 2 bounds are placed
                has_bounds = getattr(self.parent_window, 'filter_placed', False)
                self.cb_bpf.setEnabled(has_bounds)
                self.cb_bsf.setEnabled(has_bounds)
        elif display_mode in ['TIME', 'TIME_ENDLESS']:
            self.row1_label.setText("Samples")
            self.row2_label.setText("Time (sec)")
            self.row1_label.show()
            self.row2_label.show()
            
            # Move Time widgets back to Row 2
            self.grid.addWidget(self.row1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.widgets[i]['sam'], 1, i + 1)
                self.grid.addWidget(self.widgets[i]['sec'], 2, i + 1)
                self.widgets[i]['sam'].show()
                self.widgets[i]['sec'].show()
            self.grid.addWidget(self.delta_sam, 1, 3); self.delta_sam.show()
            self.grid.addWidget(self.delta_sec, 2, 3); self.delta_sec.show()
            self.grid.addWidget(self.center_sam, 1, 4); self.center_sam.show()
            self.grid.addWidget(self.center_sec, 2, 4); self.center_sec.show()
            
        show_inv = self.parent_window.settings_mgr.get("ui/show_inv_time", False)
        is_time_mode = display_mode in ['TIME', 'TIME_ENDLESS']
        should_show = show_inv and is_time_mode
        self.row3_label.setVisible(should_show)
        for i in range(2): self.widgets[i]['inv'].setVisible(should_show)
        self.delta_inv.setVisible(should_show)
        self.center_inv.setVisible(should_show)
            
        # Sync lock UI with saved state for this display mode
        if display_mode in self.lock_states:
            for key, btn in [
                ('m1',     self.btn_lock_m1),
                ('m2',     self.btn_lock_m2),
                ('delta',  self.btn_lock_delta),
                ('center', self.btn_lock_center),
            ]:
                locked = self.lock_states[display_mode].get(key, False)
                btn.blockSignals(True)
                btn.setChecked(locked)
                btn.setEnabled(True)
                btn.blockSignals(False)
        else:
            for btn in [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]:
                btn.setEnabled(False)

    def update_overlay_list(self, overlays):
        """
        Populate the shared scroll area with overlay rows.
        Each row: index-label | shape | display-tag | Edit btn | Del btn
        No dialog is shown on Add — the overlay was already placed via click/drag.
        Edit opens the full OverlayDialog.
        """
        if not hasattr(self, '_overlay_rows'):
            self._overlay_rows = []

        # Build / rebuild header once
        if not hasattr(self, '_overlay_header_widget'):
            hw = QWidget()
            hl = QHBoxLayout(hw)
            hl.setContentsMargins(5, 2, 5, 2)
            hl.setSpacing(8)
            l_id   = QLabel("#");          l_id.setFixedWidth(22);  l_id.setObjectName("header_label")
            l_sh   = QLabel("Shape");      l_sh.setObjectName("header_label"); l_sh.setFixedWidth(40)
            l_tag  = QLabel("Tag");        l_tag.setObjectName("header_label")
            hl.addWidget(l_id)
            hl.addWidget(l_sh)
            hl.addWidget(l_tag, 1)
            self._overlay_header_widget = hw
            self.overlay_scroll_layout.insertWidget(0, hw)

        # Sync row count
        while len(self._overlay_rows) > len(overlays):
            rd = self._overlay_rows.pop()
            rd['widget'].deleteLater()
        while len(self._overlay_rows) < len(overlays):
            from PyQt6.QtWidgets import QLineEdit
            i   = len(self._overlay_rows)
            row = QWidget()
            rl  = QHBoxLayout(row)
            rl.setContentsMargins(5, 0, 5, 0)
            rl.setSpacing(8)

            lbl_id  = QLabel(f"{i+1}")
            lbl_id.setFixedWidth(22)
            lbl_id.setStyleSheet("color: #008800; font-weight: bold;")

            lbl_shape = QLabel("RECT")
            lbl_shape.setFixedWidth(40)

            edit_tag = QLineEdit()
            edit_tag.setFixedHeight(24)
            edit_tag.setPlaceholderText("...")

            btn_inspect = QPushButton("Inspect")
            btn_inspect.setFixedHeight(28)
            btn_inspect.setToolTip("Inspect overlay metadata, full text/bits, and narrowband IQ")

            btn_vis = QPushButton("Hide")
            btn_vis.setFixedHeight(28)
            btn_vis.setToolTip("Toggle Visibility")

            btn_lock = QPushButton("Lock")
            btn_lock.setFixedHeight(28)
            btn_lock.setToolTip("Lock overlay (prevent move/resize)")

            btn_edit = QPushButton("Edit")
            btn_edit.setFixedHeight(28)
            btn_edit.setToolTip("Edit overlay properties")

            btn_del = QPushButton("Del")
            btn_del.setFixedHeight(28)
            btn_del.setToolTip("Delete overlay")
            btn_del.setStyleSheet("""
                QPushButton { background: none; color: #ff4444; font-weight: bold;
                              font-size: 13px; border-radius: 4px; border: 1px solid #ff4444; }
                QPushButton:hover { background: rgba(255,68,68,0.2); }
            """)

            rl.addWidget(lbl_id)
            rl.addWidget(lbl_shape)
            rl.addWidget(edit_tag, 1)
            rl.addWidget(btn_inspect)
            rl.addWidget(btn_vis)
            rl.addWidget(btn_lock)
            rl.addWidget(btn_edit)
            rl.addWidget(btn_del)

            self.overlay_scroll_layout.insertWidget(self.overlay_scroll_layout.count()-1, row)
            rd_entry = {
                'widget': row, 'lbl_id': lbl_id,
                'lbl_shape': lbl_shape, 'edit_tag': edit_tag,
                'btn_inspect': btn_inspect,
                'btn_vis': btn_vis, 'btn_lock': btn_lock,
                'btn_edit': btn_edit, 'btn_del': btn_del,
                'overlay_id': None,
            }
            def _make_row_press(r=rd_entry):
                def _on_press(ev):
                    if ev.button() == Qt.MouseButton.LeftButton and r.get('overlay_id'):
                        if hasattr(self.parent_window, 'select_overlay'):
                            self.parent_window.select_overlay(r['overlay_id'], scroll_to_row=False)
                    QWidget.mousePressEvent(r['widget'], ev)
                return _on_press
            row.mousePressEvent = _make_row_press(rd_entry)
            self._overlay_rows.append(rd_entry)

        # Update data
        for i, overlay in enumerate(overlays):
            rd = self._overlay_rows[i]
            rd['overlay_id'] = overlay.id
            rd['widget'].setVisible(True)
            rd['lbl_id'].setText(str(i + 1))
            rd['lbl_id'].setStyleSheet(
                f"color: {overlay.border_color or overlay.color or '#008800'}; font-weight: bold;"
            )
            shape_str = overlay.shape.value if hasattr(overlay.shape, 'value') else str(overlay.shape)
            rd['lbl_shape'].setText(shape_str)
            rd['edit_tag'].blockSignals(True)
            rd['edit_tag'].setText(overlay.display_str or "")
            hover_tip = (
                overlay.get_truncated_hover()
                if hasattr(overlay, 'get_truncated_hover')
                else (overlay.hover_str or "")
            )
            rd['edit_tag'].setToolTip(hover_tip)
            rd['lbl_shape'].setToolTip(f"Source: {getattr(overlay, 'source', 'user')}")
            rd['edit_tag'].blockSignals(False)

            has_meta_or_iq = bool(getattr(overlay, 'metadata', None)) or (getattr(overlay, 'iq', None) is not None)
            rd['btn_inspect'].setStyleSheet(
                "QPushButton { border: 1px solid #00aaff; color: #00aaff; border-radius: 4px; padding: 2px 6px; }"
                "QPushButton:hover { background: rgba(0,170,255,0.15); }"
                if has_meta_or_iq else ""
            )

            rd['btn_vis'].setText("Hide" if overlay.visible else "Show")

            # Lock button — highlight when locked
            is_locked = getattr(overlay, 'locked', False)
            rd['btn_lock'].setText("Unlk" if is_locked else "Lock")
            rd['btn_lock'].setStyleSheet(
                "QPushButton { border: 1px solid #ffaa00; color: #ffaa00; border-radius:4px; }"
                "QPushButton:hover { background: rgba(255,170,0,0.15); }"
                if is_locked else ""
            )

            oid = overlay.id
            try: rd['edit_tag'].editingFinished.disconnect()
            except: pass
            try: rd['btn_inspect'].clicked.disconnect()
            except: pass
            try: rd['btn_vis'].clicked.disconnect()
            except: pass
            try: rd['btn_lock'].clicked.disconnect()
            except: pass
            try: rd['btn_edit'].clicked.disconnect()
            except: pass
            try: rd['btn_del'].clicked.disconnect()
            except: pass
            
            rd['edit_tag'].editingFinished.connect(lambda r=rd, o=oid: self.parent_window.update_overlay(o, display_str=r['edit_tag'].text()))
            rd['btn_inspect'].clicked.connect(lambda _, o=oid: self.parent_window.inspect_overlay(o))
            rd['btn_vis'].clicked.connect(lambda _, o=oid: self.parent_window.update_overlay(
                o, visible=not self.parent_window._get_overlay_by_id(o).visible))
            rd['btn_lock'].clicked.connect(lambda _, o=oid: self.parent_window.update_overlay(
                o, locked=not getattr(self.parent_window._get_overlay_by_id(o), 'locked', False)))
            rd['btn_edit'].clicked.connect(lambda _, o=oid: self._on_overlay_edit(o))
            rd['btn_del'].clicked.connect(lambda _, o=oid: self.parent_window.remove_overlay(o))

        # Hide extra overlay rows that don't correspond to any overlay
        for rd in self._overlay_rows[len(overlays):]:
            rd['overlay_id'] = None
            rd['widget'].setVisible(False)

        sel_id = getattr(self.parent_window, 'selected_overlay_id', None)
        self.set_selected_overlay(sel_id, scroll_to_row=False)

    def set_selected_overlay(self, overlay_id, scroll_to_row: bool = True):
        """Highlight the row matching *overlay_id* and optionally scroll it into view."""
        if not hasattr(self, '_overlay_rows'):
            return
        target_widget = None
        for rd in self._overlay_rows:
            oid = rd.get('overlay_id')
            is_sel = (oid is not None and oid == overlay_id)
            if is_sel:
                rd['widget'].setStyleSheet(
                    "background: rgba(0, 170, 255, 0.18); border-radius: 4px;"
                )
                target_widget = rd['widget']
            else:
                rd['widget'].setStyleSheet("")

        if scroll_to_row and target_widget is not None and hasattr(self, 'overlay_scroll'):
            self.overlay_scroll.ensureWidgetVisible(target_widget, 0, 24)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(
                0,
                lambda w=target_widget: self.overlay_scroll.ensureWidgetVisible(w, 0, 24)
                if w is not None else None,
            )

    def _show_endless_rows(self):
        """Switch the scroll area back to showing endless-marker rows."""
        # Now handled by QStackedWidget, no-op
        pass

    def _on_manual_overlay_add(self):
        from PyQt6.QtWidgets import QDialog
        from .overlay_dialog import OverlayDialog
        from .overlay import Overlay
        
        # Pre-select the combo box shape by creating a dummy overlay
        dummy = Overlay()
        dummy.shape = self.cb_overlay_shape.currentData() or dummy.shape
        
        dlg = OverlayDialog(
            parent=self,
            parent_window=self.parent_window,
            overlay=dummy,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_overlay = dlg.get_overlay()
            self.parent_window.add_overlay(new_overlay)


    def _on_overlay_edit(self, overlay_id):
        overlay = self.parent_window._get_overlay_by_id(overlay_id)
        if overlay is None:
            return
        from PyQt6.QtWidgets import QDialog
        from .overlay_dialog import OverlayDialog
        dlg = OverlayDialog(
            parent=self,
            parent_window=self.parent_window,
            overlay=overlay,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_overlay()
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

    def update_endless_list(self, markers, mode):
        """Update the scroll area with rows for each endless marker, reusing widgets where possible."""
        # Switch header/rows to endless view
        self._show_endless_rows()
        is_freq = 'FREQ' in mode
        unit_main = "Hz" if is_freq else "sec"
        unit_sub = "Bin" if is_freq else "Sam"

        
        # 1. Initialize or find internal row storage
        if not hasattr(self, '_endless_rows'):
            self._endless_rows = []
        if not hasattr(self, '_header_widget'):
            self._header_widget = QWidget()
            h_layout = QHBoxLayout(self._header_widget)
            h_layout.setContentsMargins(5, 2, 5, 2)
            h_layout.setSpacing(10)
            
            l_id = QLabel("ID"); l_id.setFixedWidth(30); l_id.setObjectName("header_label")
            l_sub = QLabel(unit_sub)
            l_sub.setObjectName("header_label")
            l_sub.setProperty("role", "sub_header")
            l_main = QLabel(f"Pos ({unit_main})")
            l_main.setObjectName("header_label")
            l_main.setProperty("role", "pos_header")
            l_del = QLabel("")
            l_del.setFixedWidth(28)
            
            h_layout.addWidget(l_id)
            h_layout.addWidget(l_sub, 1)
            h_layout.addWidget(l_main, 1)
            h_layout.addWidget(l_del)
            self.scroll_layout.insertWidget(0, self._header_widget)

        # 2. Update header labels
        for lbl in self._header_widget.findChildren(QLabel, "header_label"):
            if lbl.property("role") == "pos_header":
                lbl.setText(f"Pos ({unit_main})")
            elif lbl.property("role") == "sub_header":
                lbl.setText(unit_sub)

        # 3. Synchronize row count
        # Remove excess rows
        while len(self._endless_rows) > len(markers):
            row_data = self._endless_rows.pop()
            row_data['widget'].deleteLater()

        # Add missing rows
        while len(self._endless_rows) < len(markers):
            i = len(self._endless_rows)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 0, 5, 0)
            row_layout.setSpacing(10)
            
            lbl_id = QLabel(f"M{i+1}")
            lbl_id.setFixedWidth(30)
            lbl_id.setStyleSheet("color: #ff6400; font-weight: bold;")
            
            edit_sub = FormattedLineEdit()
            edit_sub.setFixedHeight(24)
            edit_sub.returnPressed.connect(self.parent_window.marker_edit_finished)

            edit_pos = FormattedLineEdit()
            edit_pos.setFixedHeight(24)
            edit_pos.returnPressed.connect(self.parent_window.marker_edit_finished)
            
            btn_del = QPushButton("Del")
            btn_del.setFixedHeight(28)
            btn_del.setToolTip("Remove marker")
            btn_del.setStyleSheet("""
                QPushButton { background: none; color: #ff4444; font-weight: bold; font-size: 13px; border-radius: 4px; border: 1px solid #ff4444; }
                QPushButton:hover { background: rgba(255, 68, 68, 0.2); }
            """)
            
            row_layout.addWidget(lbl_id)
            row_layout.addWidget(edit_sub, 1)
            row_layout.addWidget(edit_pos, 1)
            row_layout.addWidget(btn_del)
            
            # Insert into layout (before the stretch)
            # Find index of header row or offset
            self.scroll_layout.insertWidget(self.scroll_layout.count()-1, row)
            
            self._endless_rows.append({
                'widget': row,
                'lbl_id': lbl_id,
                'edit_pos': edit_pos,
                'edit_sub': edit_sub,
                'btn_del': btn_del
            })

        # 4. Update data for all rows
        for i, m in enumerate(markers):
            row_data = self._endless_rows[i]
            val = m.value()
            prec = int(self.parent_window.settings_mgr.get("ui/label_precision", 6 if is_freq else 9))
            
            row_data['lbl_id'].setText(f"M{i+1}")
            
            # Update position
            row_data['edit_pos'].blockSignals(True)
            row_data['edit_pos'].setObjectName(f"em_{i}_hz" if is_freq else f"em_{i}_sec")
            row_data['edit_pos'].setText(f"{val:.{prec}f}")
            row_data['edit_pos'].blockSignals(False)
            
            # Update sub-unit
            if is_freq:
                rbw = self.parent_window.rate / self.parent_window.fft_size
                sub_val = int(round((val - (self.parent_window.fc - self.parent_window.rate/2)) / rbw)) + 1
            else:
                sub_val = int(round(val * self.parent_window.rate)) + 1
            
            row_data['edit_sub'].blockSignals(True)
            row_data['edit_sub'].setObjectName(f"em_{i}_bin" if is_freq else f"em_{i}_sam")
            row_data['edit_sub'].setText(f"{sub_val}")
            row_data['edit_sub'].blockSignals(False)
            
            # Update delete button connection
            try: row_data['btn_del'].clicked.disconnect()
            except: pass
            row_data['btn_del'].clicked.connect(lambda _, m=m: self.parent_window.remove_marker_item(m, mode))

    def refresh_theme(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        
        # Update non-marker-type icons (always the same regardless of waterfall)
        self.btn_zoom.setIcon(self._get_icon("zoom_mode"))
        self.btn_move.setIcon(self._get_icon("free_move_mode"))
        self.btn_home.setIcon(self._get_icon("reset_zoom"))
        self.btn_bpf.setIcon(self._get_icon("bpf_selection_mode"))
        self.btn_overlay.setIcon(self._get_icon("overlays"))
        
        # TIME/FREQ marker icons depend on waterfall state — delegate
        waterfall = self.parent_window.spectrogram_view.is_waterfall if (hasattr(self, 'parent_window') and hasattr(self.parent_window, 'spectrogram_view')) else False
        self._apply_marker_button_icons(waterfall)
        
        self.setStyleSheet(f"""
            MarkerPanel {{ 
                background-color: {p.bg_widget}; 
                border-bottom: 2px solid {p.bg_main};
            }}
            QPushButton#mode_btn {{
                background-color: transparent; 
                border: 2px solid transparent;
                border-radius: 4px;
                min-width: 34px;
                min-height: 34px;
                font-size: 16px;
                padding: 0;
            }}
            QPushButton#mode_btn:hover {{ background-color: {p.border_light}; }}
            QPushButton#mode_btn:checked {{ 
                background-color: {p.accent_dim}; 
                border-color: {p.accent};
                color: {p.accent};
            }}
            QLineEdit {{
                background-color: {p.bg_input};
                font-family: 'Consolas', 'Courier New';
                font-size: 13px;
                border: 1px solid {p.border};
                border-radius: 3px;
                padding: 2px 4px;
                color: {p.text_main};
            }}
            QLineEdit:focus {{ border-color: {p.accent}; }}
            QLabel#header_label {{
                color: {p.text_dim};
                font-size: 10px;
                text-transform: uppercase;
                font-weight: bold;
            }}
        """)
        
        lock_style = f"""
            QPushButton {{ 
                background: none; 
                border: 1px solid transparent; 
                border-radius: 4px;
                color: {p.text_dim}; 
                padding: 1px 4px; 
                text-transform: uppercase; 
                font-size: 10px; 
            }}
            QPushButton:hover {{ color: {p.text_header}; background-color: {p.border}; }}
            QPushButton:checked {{ 
                color: {p.accent}; 
                border: 1px solid {p.accent};
                background-color: {p.accent_dim};
            }}
        """
        if hasattr(self, 'btn_lock_delta'):
            for btn in [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]:
                btn.setStyleSheet(lock_style)

        if hasattr(self, 'btn_plugins'):
            self.btn_plugins.setIcon(self._get_icon("plugins"))

    def update_plugins_list(self, loaded_plugins):
        """
        Populate the shared scroll area with plugin rows and sync the Quick-Run dropdown.
        Each row: Pin btn | Name + Badge | Docs btn | Config btn | Run btn | Del btn
        """
        if not hasattr(self, '_plugin_rows'):
            self._plugin_rows = []

        pinned_set = set(
            self.parent_window.get_pinned_plugins()
            if hasattr(self.parent_window, 'get_pinned_plugins')
            else []
        )

        # Show only favorite (pinned) plugins on the main Plugins tab
        all_items = list(loaded_plugins.items())
        plugins_data = [(n, inf) for n, inf in all_items if n in pinned_set]

        # Sync Quick-Run dropdown with favorite plugins
        if hasattr(self, 'cb_quick_plugin'):
            prev_sel = self.cb_quick_plugin.currentData()
            self.cb_quick_plugin.blockSignals(True)
            self.cb_quick_plugin.clear()
            for name, info in plugins_data:
                self.cb_quick_plugin.addItem(f"★ {name}", userData=name)
            if prev_sel:
                idx = self.cb_quick_plugin.findData(prev_sel)
                if idx >= 0:
                    self.cb_quick_plugin.setCurrentIndex(idx)
            self.cb_quick_plugin.blockSignals(False)
            has_favs = len(plugins_data) > 0
            self.cb_quick_plugin.setEnabled(has_favs)
            if hasattr(self, 'btn_quick_run'):
                self.btn_quick_run.setEnabled(has_favs)
            if hasattr(self, 'btn_quick_config'):
                self.btn_quick_config.setEnabled(has_favs)
            if hasattr(self, 'btn_quick_docs'):
                self.btn_quick_docs.setEnabled(has_favs)

        # Build / rebuild header once
        if not hasattr(self, '_plugin_header_widget'):
            hw = QWidget()
            hl = QHBoxLayout(hw)
            hl.setContentsMargins(5, 2, 5, 2)
            hl.setSpacing(8)
            l_name = QLabel("Favorite Plugins"); l_name.setObjectName("header_label")
            hl.addWidget(l_name, 1)
            self._plugin_header_widget = hw
            self.plugins_scroll_layout.insertWidget(0, hw)

        if not hasattr(self, '_lbl_no_favorites'):
            self._lbl_no_favorites = QLabel(
                "No favorite plugins marked yet. Open 'Plugin Studio…' to browse all plugins, "
                "run them, or mark favorites (★) to pin them here."
            )
            self._lbl_no_favorites.setStyleSheet("color: #888888; font-style: italic; padding: 6px 8px;")
            self._lbl_no_favorites.setWordWrap(True)
            self.plugins_scroll_layout.insertWidget(1, self._lbl_no_favorites)

        self._plugin_header_widget.setVisible(len(plugins_data) > 0)
        self._lbl_no_favorites.setVisible(len(plugins_data) == 0)

        # Sync row count
        while len(self._plugin_rows) > len(plugins_data):
            rd = self._plugin_rows.pop()
            rd['widget'].deleteLater()
        while len(self._plugin_rows) < len(plugins_data):
            row = QWidget()
            rl  = QHBoxLayout(row)
            rl.setContentsMargins(5, 0, 5, 0)
            rl.setSpacing(8)

            btn_pin = QPushButton("★")
            btn_pin.setFixedSize(28, 28)
            btn_pin.setToolTip("Remove from favorite plugins")
            btn_pin.setStyleSheet("QPushButton { padding: 2px; font-size: 13px; }")

            lbl_name = QLabel()
            lbl_name.setStyleSheet("font-weight: bold; color: #00aaff;")
            
            btn_docs = QPushButton("Docs")
            btn_docs.setFixedHeight(28)
            btn_docs.setMinimumWidth(60)
            btn_docs.setStyleSheet("QPushButton { padding: 3px 8px; }")
            btn_docs.setToolTip("View detailed plugin documentation, operation, and parameters")

            btn_config = QPushButton("Config")
            btn_config.setFixedHeight(28)
            btn_config.setMinimumWidth(75)
            btn_config.setStyleSheet("QPushButton { padding: 3px 8px; }")
            btn_config.setToolTip("Configure plugin parameters")
            
            btn_run = QPushButton("▶ Run")
            btn_run.setFixedHeight(28)
            btn_run.setMinimumWidth(75)
            btn_run.setToolTip("Run this plugin")
            btn_run.setStyleSheet("""
                QPushButton { background: none; color: #00cc66; font-weight: bold;
                              border-radius: 4px; border: 1px solid #00cc66; padding: 3px 8px; }
                QPushButton:hover { background: rgba(0,204,102,0.2); }
            """)

            btn_del = QPushButton("Del")
            btn_del.setFixedHeight(28)
            btn_del.setMinimumWidth(60)
            btn_del.setToolTip("Unload this plugin")
            btn_del.setStyleSheet("""
                QPushButton { background: none; color: #ff4444; font-weight: bold;
                              border-radius: 4px; border: 1px solid #ff4444; padding: 3px 8px; }
                QPushButton:hover { background: rgba(255,68,68,0.2); }
                QPushButton:disabled { color: #666666; border-color: #444444; }
            """)

            rl.addWidget(btn_pin)
            rl.addWidget(lbl_name, 1)
            rl.addWidget(btn_docs)
            rl.addWidget(btn_config)
            rl.addWidget(btn_run)
            rl.addWidget(btn_del)

            self.plugins_scroll_layout.insertWidget(self.plugins_scroll_layout.count()-1, row)
            self._plugin_rows.append({
                'widget': row, 'btn_pin': btn_pin, 'lbl_name': lbl_name,
                'btn_docs': btn_docs,
                'btn_config': btn_config, 'btn_run': btn_run, 'btn_del': btn_del,
            })

        # Update data
        for i, (name, info) in enumerate(plugins_data):
            rd = self._plugin_rows[i]
            rd['widget'].setVisible(True)
            is_pin = name in pinned_set
            is_chain = info.get("chain") is not None
            is_builtin = bool(info.get("builtin", False))
            badge = " [Chain]" if is_chain else (" [Built-In]" if is_builtin else " [Custom]")

            rd['btn_pin'].setText("★" if is_pin else "☆")
            rd['lbl_name'].setText(f"{name}{badge}")
            
            desc = info.get("description", "")
            if desc:
                rd['lbl_name'].setToolTip(desc)
            else:
                rd['lbl_name'].setToolTip("No description provided.")

            has_params = bool(info.get("params_spec"))
            rd['btn_config'].setEnabled(has_params)
            rd['btn_del'].setEnabled(not is_builtin)
            rd['btn_del'].setToolTip(
                "Built-in plugins are always available" if is_builtin else "Unload this plugin"
            )

            try: rd['btn_pin'].clicked.disconnect()
            except: pass
            try: rd['btn_docs'].clicked.disconnect()
            except: pass
            try: rd['btn_config'].clicked.disconnect()
            except: pass
            try: rd['btn_run'].clicked.disconnect()
            except: pass
            try: rd['btn_del'].clicked.disconnect()
            except: pass

            rd['btn_pin'].clicked.connect(lambda _, n=name: self.parent_window.toggle_pinned_plugin(n))
            rd['btn_docs'].clicked.connect(lambda _, n=name: self._on_plugin_docs(n))
            rd['btn_config'].clicked.connect(lambda _, n=name: self._on_plugin_config(n))
            rd['btn_run'].clicked.connect(lambda _, n=name: self.parent_window.run_plugin(n))
            rd['btn_del'].clicked.connect(lambda _, n=name: self._on_plugin_unload(n))

        for rd in self._plugin_rows[len(plugins_data):]:
            rd['widget'].setVisible(False)

        if hasattr(self.parent_window, 'overlays'):
            self.update_plugin_overlay_pills(self.parent_window.overlays)

    def _on_quick_run_clicked(self):
        if not hasattr(self, 'cb_quick_plugin'):
            return
        name = self.cb_quick_plugin.currentData()
        if name:
            self.parent_window.run_plugin(name)

    def _on_quick_config_clicked(self):
        if not hasattr(self, 'cb_quick_plugin'):
            return
        name = self.cb_quick_plugin.currentData()
        if name:
            self._on_plugin_config(name)

    def _on_quick_docs_clicked(self):
        if not hasattr(self, 'cb_quick_plugin'):
            return
        name = self.cb_quick_plugin.currentData()
        if name:
            self._on_plugin_docs(name)

    def update_plugin_overlay_pills(self, overlays):
        """Render compact pills for each plugin that currently has overlays on the spectrogram."""
        if not hasattr(self, 'plugin_pills_widget') or not hasattr(self, 'plugin_pills_layout'):
            return

        while self.plugin_pills_layout.count():
            item = self.plugin_pills_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        counts = {}
        vis_map = {}
        for o in overlays or []:
            src = str(getattr(o, 'source', '') or '')
            if src.startswith('plugin:'):
                counts[src] = counts.get(src, 0) + 1
                if getattr(o, 'visible', True):
                    vis_map[src] = True
                elif src not in vis_map:
                    vis_map[src] = False

        if not counts:
            self.plugin_pills_widget.setVisible(False)
            return

        self.plugin_pills_widget.setVisible(True)
        lbl_hdr = QLabel("Active Overlays:")
        lbl_hdr.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.plugin_pills_layout.addWidget(lbl_hdr)

        for src, cnt in counts.items():
            pname = src[len('plugin:'):]
            is_vis = vis_map.get(src, True)

            pill = QFrame()
            pill.setStyleSheet(
                "QFrame { border: 1px solid #444444; border-radius: 4px; padding: 1px 4px; }"
            )
            pl = QHBoxLayout(pill)
            pl.setContentsMargins(4, 1, 4, 1)
            pl.setSpacing(4)

            lbl = QLabel(f"{pname} ({cnt})")
            lbl.setStyleSheet("border: none; font-size: 11px;")
            pl.addWidget(lbl)

            btn_vis = QPushButton("👁" if is_vis else "🚫")
            btn_vis.setFixedSize(22, 22)
            btn_vis.setToolTip(f"Show/Hide overlays from '{pname}'")
            btn_vis.setStyleSheet("QPushButton { padding: 0px; font-size: 11px; }")
            btn_vis.clicked.connect(lambda _, s=src: self.parent_window.toggle_source_overlays_visible(s))
            pl.addWidget(btn_vis)

            btn_clr = QPushButton("🧹")
            btn_clr.setFixedSize(22, 22)
            btn_clr.setToolTip(f"Clear overlays created by '{pname}'")
            btn_clr.setStyleSheet("QPushButton { padding: 0px; font-size: 11px; }")
            btn_clr.clicked.connect(lambda _, s=src: self.parent_window.clear_overlays(source=s))
            pl.addWidget(btn_clr)

            self.plugin_pills_layout.addWidget(pill)

        self.plugin_pills_layout.addStretch(1)

    def _on_plugin_docs(self, name):
        info = self.parent_window._loaded_plugins.get(name)
        if not info:
            return
        dlg = PluginDocDialog(name, info, parent=self)
        dlg.exec()

    def _on_plugin_config(self, name):
        info = self.parent_window._loaded_plugins.get(name)
        if not info:
            return
            
        params_spec = info.get("params_spec", {})
        current_params = info.get("params", {})
        
        from PyQt6.QtWidgets import QDialog
        dlg = PluginConfigDialog(name, params_spec, current_params, self, plugin_info=info)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_values = dlg.get_values()
            info["params"] = new_values
            if hasattr(self.parent_window, "save_plugin_params"):
                self.parent_window.save_plugin_params(name, new_values)
            self.parent_window.statusBar().showMessage(f"Updated parameters for {name}", 3000)
            if dlg.requested_step_run is not None:
                step_idx = int(dlg.requested_step_run)
                if hasattr(self.parent_window, "run_plugin_step"):
                    self.parent_window.run_plugin_step(name, step_idx, single_step_only=True)

    def _on_plugin_unload(self, name):
        self.parent_window.unload_plugin(name)


class ScientificNumberEdit(QLineEdit):
    """Numeric line edit for plugin parameters that accepts scientific notation (e.g. 500e3, 1e-4)."""

    def __init__(self, value=0.0, is_int: bool = False, min_val=None, max_val=None, parent=None):
        super().__init__(parent)
        self._is_int = is_int
        self._min_val = min_val
        self._max_val = max_val
        self._fallback = int(value or 0) if is_int else float(value or 0.0)
        self.setValue(self._fallback)
        self.editingFinished.connect(self._normalize_display)

    def setValue(self, val):
        if val is None:
            return
        if self._is_int:
            v = int(round(float(val)))
            self._fallback = v
            self.setText(str(v))
        else:
            v = float(val)
            self._fallback = v
            self.setText(f"{v:g}")

    def value(self):
        raw = self.text().strip().replace(" ", "").replace("_", "")
        if not raw:
            return self._fallback
        try:
            # Support optional SI suffixes if typed, plus standard scientific notation (e.g. 500e3)
            mult = 1.0
            if len(raw) > 1 and raw[-1] in ("k", "K", "M", "G", "m", "u", "n"):
                sfx = raw[-1]
                raw = raw[:-1]
                mult = {
                    "k": 1e3, "K": 1e3,
                    "M": 1e6, "G": 1e9,
                    "m": 1e-3, "u": 1e-6, "n": 1e-9,
                }[sfx]
            parsed = float(raw) * mult
            if self._min_val is not None:
                parsed = max(float(self._min_val), parsed)
            if self._max_val is not None:
                parsed = min(float(self._max_val), parsed)
            if self._is_int:
                res = int(round(parsed))
            else:
                res = float(parsed)
            self._fallback = res
            return res
        except ValueError:
            return self._fallback

    def _normalize_display(self):
        self.setValue(self.value())


class PluginDocDialog(QDialog):
    """Rich documentation dialog displaying a plugin's operation, algorithm, and parameter reference."""

    def __init__(self, plugin_name: str, plugin_info: dict, parent=None):
        super().__init__(parent)
        self.plugin_name = plugin_name
        self.plugin_info = plugin_info or {}
        self.setWindowTitle(f"Plugin Documentation — {plugin_name}")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(720, 600)
        self._build_ui()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
            event.ignore()
            return
        super().changeEvent(event)

    def _build_ui(self):
        from PyQt6.QtWidgets import QTextBrowser
        import html as _html

        layout = QVBoxLayout(self)

        theme = "Dark"
        if self.parent() and hasattr(self.parent(), "parent_window"):
            theme = self.parent().parent_window.settings_mgr.get("ui/theme", "Dark")
        from .themes import get_palette
        p = get_palette(theme)

        self.setStyleSheet(
            f"QDialog, QWidget {{ background-color: {p.bg_main}; color: {p.text_main}; }}"
        )

        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(
            f"QTextBrowser {{ background-color: {p.bg_input}; color: {p.text_main}; "
            f"border: 1px solid {p.border}; border-radius: 6px; padding: 12px; font-size: 13px; }}"
        )

        cat = _html.escape(str(self.plugin_info.get("category", "General")))
        is_builtin = bool(self.plugin_info.get("builtin", False))
        needs_wb = bool(self.plugin_info.get("needs_wideband_iq", True))
        desc = _html.escape(str(self.plugin_info.get("description", "")))
        raw_doc = str(self.plugin_info.get("doc", "") or "").strip()
        params_spec = self.plugin_info.get("params_spec", {}) or {}

        badge_type = "Built-In Plugin" if is_builtin else "Custom / Chain Plugin"
        iq_mode = "Wideband IQ (extracts scope IQ)" if needs_wb else "Overlay Baseband IQ (zero-copy o.iq / lazy DDC)"

        is_html = bool(re.search(r"<(?:h[1-6]|p|div|table|ol|ul|br)\b", raw_doc, re.IGNORECASE))

        if not is_html:
            # Markdown rendering mode
            rows_md = []
            for key, spec in params_spec.items():
                if not isinstance(spec, dict):
                    spec = {"type": type(spec).__name__, "default": spec, "label": key}
                lbl = str(spec.get("label", key))
                ptype = str(spec.get("type", "str"))
                def_val = str(spec.get("default", ""))
                tip = str(spec.get("tooltip", "") or "—")
                step_title = spec.get("step_title")
                if step_title:
                    lbl = f"[{step_title}] {lbl}"
                rows_md.append(f"| **{lbl}** (`{key}`) | `{ptype}` | `{def_val}` | {tip} |")

            params_table_md = (
                "### Parameters Reference\n\n"
                "| Parameter | Type | Default | Description |\n"
                "| :--- | :--- | :--- | :--- |\n"
                + "\n".join(rows_md)
                if rows_md
                else "*This plugin has no configurable parameters.*"
            )

            body_doc = raw_doc if raw_doc else f"# {self.plugin_name}\n\n{desc}"
            has_inline_table = ("<table" in raw_doc.lower()) or ("| ---" in raw_doc or "|:---" in raw_doc or "| :---" in raw_doc)
            extra_params_block = "" if has_inline_table else f"\n\n---\n\n{params_table_md}"

            full_md = (
                f"**Category:** {cat} | **Type:** {badge_type} | **IQ Mode:** {iq_mode}\n\n"
                f"---\n\n"
                f"{body_doc}"
                f"{extra_params_block}"
            )
            browser.setMarkdown(full_md)
        else:
            # Legacy HTML rendering mode
            rows_html = []
            for key, spec in params_spec.items():
                if not isinstance(spec, dict):
                    spec = {"type": type(spec).__name__, "default": spec, "label": key}
                lbl = _html.escape(str(spec.get("label", key)))
                ptype = _html.escape(str(spec.get("type", "str")))
                def_val = _html.escape(str(spec.get("default", "")))
                tip = _html.escape(str(spec.get("tooltip", "") or "—"))
                step_title = spec.get("step_title")
                if step_title:
                    lbl = f"[{_html.escape(str(step_title))}] {lbl}"
                rows_html.append(
                    f"<tr>"
                    f"<td style='padding:6px 8px; border-bottom:1px solid {p.border};'><b>{lbl}</b><br/>"
                    f"<code style='color:{p.text_dim};'>{_html.escape(str(key))}</code></td>"
                    f"<td style='padding:6px 8px; border-bottom:1px solid {p.border};'><code>{ptype}</code></td>"
                    f"<td style='padding:6px 8px; border-bottom:1px solid {p.border};'><code>{def_val}</code></td>"
                    f"<td style='padding:6px 8px; border-bottom:1px solid {p.border};'>{tip}</td>"
                    f"</tr>"
                )

            params_table_html = (
                f"<h4>Parameters Reference</h4>"
                f"<table width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse;'>"
                f"<thead><tr style='background-color:{p.bg_widget};'>"
                f"<th align='left' style='padding:6px 8px; border-bottom:2px solid {p.border};'>Parameter</th>"
                f"<th align='left' style='padding:6px 8px; border-bottom:2px solid {p.border};'>Type</th>"
                f"<th align='left' style='padding:6px 8px; border-bottom:2px solid {p.border};'>Default</th>"
                f"<th align='left' style='padding:6px 8px; border-bottom:2px solid {p.border};'>Description</th>"
                f"</tr></thead>"
                f"<tbody>{''.join(rows_html)}</tbody></table>"
                if rows_html
                else "<p><i>This plugin has no configurable parameters.</i></p>"
            )

            body_doc = raw_doc if raw_doc else f"<h3>{_html.escape(self.plugin_name)}</h3><p>{desc}</p>"
            has_inline_table = "<table" in raw_doc.lower()
            extra_params_block = (
                ""
                if has_inline_table
                else f'<hr style="border: 0; border-top: 1px solid {p.border}; margin: 14px 0;" />{params_table_html}'
            )

            full_html = f"""
            <div style="font-family: 'Segoe UI', sans-serif; line-height: 1.45;">
                <div style="margin-bottom: 10px; color: {p.text_dim}; font-size: 12px;">
                    <b>Category:</b> {cat} &nbsp;|&nbsp;
                    <b>Type:</b> {badge_type} &nbsp;|&nbsp;
                    <b>IQ Mode:</b> {iq_mode}
                </div>
                {body_doc}
                {extra_params_block}
            </div>
            """
            browser.setHtml(full_html)
        layout.addWidget(browser, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)


class PluginConfigDialog(QDialog):
    def __init__(self, plugin_name, params_spec, current_params, parent=None, plugin_info=None):
        super().__init__(parent)
        self.plugin_name = plugin_name
        self.plugin_info = plugin_info or {}
        self.requested_step_run = None
        self.setWindowTitle(f"Configure {plugin_name}")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumWidth(420)
        self.setup_ui(params_spec, current_params)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
            event.ignore()
            return
        super().changeEvent(event)
        
    def setup_ui(self, params_spec, current_params):
        layout = QVBoxLayout(self)
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        
        theme = "Dark"
        if self.parent() and hasattr(self.parent(), 'parent_window'):
            theme = self.parent().parent_window.settings_mgr.get("ui/theme", "Dark")
        from .themes import get_palette
        p = get_palette(theme)
        
        self.setStyleSheet(f"""
            QDialog, QWidget {{
                background-color: {p.bg_main};
                color: {p.text_main};
            }}
            QScrollArea {{
                background-color: {p.bg_main};
                border: none;
            }}
            QLabel, QCheckBox {{
                color: {p.text_main};
            }}
            QDoubleSpinBox, QSpinBox, QLineEdit {{
                background-color: {p.bg_input};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{
                border-color: {p.accent};
            }}
            QPushButton {{
                background-color: {p.bg_widget};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                border-color: {p.accent};
                background-color: {p.border_light};
            }}
        """)
        
        self.widgets = {}
        last_step_index = None
        
        for key, spec in params_spec.items():
            if not isinstance(spec, dict):
                spec = {"type": "str", "default": spec, "label": key}

            step_idx = spec.get("step_index")
            step_title = spec.get("step_title")
            if step_idx is not None and step_idx != last_step_index:
                last_step_index = step_idx
                hdr_row = QWidget()
                hdr_lay = QHBoxLayout(hdr_row)
                hdr_lay.setContentsMargins(0, 8 if step_idx > 0 else 0, 0, 2)
                lbl_hdr = QLabel(f"<b>{step_title or f'Step {step_idx + 1}'}</b>")
                hdr_lay.addWidget(lbl_hdr)
                hdr_lay.addStretch()
                btn_step = QPushButton("▶ Run Step Only")
                btn_step.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_step.setToolTip(
                    f"Apply parameters and run only {step_title or f'Step {step_idx + 1}'} "
                    "on existing overlays / cached IQ"
                )
                btn_step.clicked.connect(lambda _c, idx=step_idx: self._on_run_step_clicked(idx))
                hdr_lay.addWidget(btn_step)
                form_layout.addRow(hdr_row)
                
            label_text = spec.get("label", key)
            param_type = spec.get("type", "str")
            tooltip = spec.get("tooltip", "")
            default_val = spec.get("default")
            curr_val = current_params.get(key, default_val)
            
            if param_type == "float":
                widget = ScientificNumberEdit(
                    value=curr_val if curr_val is not None else 0.0,
                    is_int=False,
                    min_val=spec.get("min", -1e15),
                    max_val=spec.get("max", 1e15),
                )
            elif param_type == "int":
                widget = ScientificNumberEdit(
                    value=curr_val if curr_val is not None else 0,
                    is_int=True,
                    min_val=spec.get("min", -2147483648),
                    max_val=spec.get("max", 2147483647),
                )
            elif param_type == "bool":
                widget = QCheckBox()
                if curr_val is not None:
                    widget.setChecked(bool(curr_val))
            elif param_type in ("choice", "dropdown", "select", "enum") or ("choices" in spec) or ("options" in spec):
                widget = QComboBox()
                raw_choices = spec.get("choices") if "choices" in spec else spec.get("options", [])
                choices = [str(c) for c in raw_choices]
                widget.addItems(choices)
                if curr_val is not None and str(curr_val) in choices:
                    widget.setCurrentText(str(curr_val))
                elif choices:
                    widget.setCurrentIndex(0)
            else:
                widget = QLineEdit()
                if curr_val is not None:
                    widget.setText(str(curr_val))
                    
            if tooltip:
                widget.setToolTip(tooltip)
                
            form_layout.addRow(QLabel(label_text), widget)
            self.widgets[key] = (widget, param_type)
            
        if len(params_spec) > 10:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(form_container)
            scroll.setMinimumHeight(420)
            layout.addWidget(scroll)
        else:
            layout.addWidget(form_container)

        bottom_row = QHBoxLayout()
        btn_docs = QPushButton("Docs")
        btn_docs.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_docs.setToolTip("Open detailed plugin documentation and parameter reference")
        btn_docs.clicked.connect(self._on_docs_clicked)
        bottom_row.addWidget(btn_docs)

        bottom_row.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom_row.addWidget(buttons)
        layout.addLayout(bottom_row)

    def _on_docs_clicked(self):
        dlg = PluginDocDialog(self.plugin_name, self.plugin_info, parent=self)
        dlg.exec()

    def _on_run_step_clicked(self, step_idx: int):
        self.requested_step_run = step_idx
        self.accept()
        
    def get_values(self):
        values = {}
        for key, (widget, param_type) in self.widgets.items():
            if param_type in ("float", "int"):
                values[key] = widget.value()
            elif param_type == "bool":
                values[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentText()
            else:
                values[key] = widget.text()
        return values

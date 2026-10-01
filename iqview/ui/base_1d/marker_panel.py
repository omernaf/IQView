from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QPushButton, QHBoxLayout,
    QButtonGroup, QStackedWidget, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont
from ..widgets import FormattedLineEdit, DoubleClickButton, format_tooltip_with_keybind, get_theme_icon
from ..themes import get_palette
from .region_stats_widget import RegionStatsWidget
from .endless_marker_list import EndlessMarkerListWidget


class Base1DMarkerPanel(QFrame):
    """Shared base class for 1D marker panels (TimeDomainMarkerPanel and FrequencyDomainMarkerPanel).

    Encapsulates the common mode button grid, fixed marker table (M1, M2, Delta, Center),
    marker lock state machine, EndlessMarkerListWidget integration, RegionStatsWidget integration,
    keybind-aware tooltips, and theme styling.
    """
    interactionModeChanged = pyqtSignal(str)
    resetZoomRequested = pyqtSignal()
    markerClearRequested = pyqtSignal(str)

    def __init__(
        self,
        controller,
        *,
        primary_mode="TIME",
        fixed_height=160,
        row_v1_default="Samples",
        row_v2_default="Time (sec)",
        row_v3_default=None,
        delta_v2_readonly=False,
        has_filter_mode=False,
        stats_has_inv_row=False,
        stats_has_integrated=False,
        stats_is_freq=False,
    ):
        super().__init__()
        self.controller = controller
        self.primary_mode = primary_mode
        self.primary_endless_mode = f"{primary_mode}_ENDLESS"
        self.fixed_height = fixed_height
        self.row_v1_default = row_v1_default
        self.row_v2_default = row_v2_default
        self.row_v3_default = row_v3_default
        self.has_v3_row = row_v3_default is not None
        self.delta_v2_readonly = delta_v2_readonly
        self.has_filter_mode = has_filter_mode
        self.stats_has_inv_row = stats_has_inv_row
        self.stats_has_integrated = stats_has_integrated
        self.stats_is_freq = stats_is_freq

        self.lock_states = {
            primary_mode: {'delta': False, 'center': False, 'm1': False, 'm2': False},
            'MAG':        {'delta': False, 'center': False, 'm1': False, 'm2': False},
        }
        self.last_marker_mode = primary_mode
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(self.fixed_height)
        self.header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 6, 15, 6)
        self.main_layout.setSpacing(15)

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(6)
        self.main_layout.addLayout(self.mode_btn_layout)

        # 1. Primary Axis Marker (Top-Left)
        self.btn_marker_primary = DoubleClickButton("")
        self.btn_marker_primary.setIcon(self._get_icon("vertical_markers"))
        self.btn_marker_primary.setIconSize(QSize(32, 32))
        self.btn_marker_primary.setObjectName("mode_btn")
        self.btn_marker_primary.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_primary, 0, 0)

        # 1b. Endless Primary Axis Marker
        self.btn_marker_primary_endless = DoubleClickButton("")
        self.btn_marker_primary_endless.setIcon(self._get_icon("endless_vertical_markers"))
        self.btn_marker_primary_endless.setIconSize(QSize(32, 32))
        self.btn_marker_primary_endless.setObjectName("mode_btn")
        self.btn_marker_primary_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_primary_endless, 0, 1)

        if self.primary_mode == 'TIME':
            self.btn_marker_time = self.btn_marker_primary
            self.btn_marker_time_endless = self.btn_marker_primary_endless
        elif self.primary_mode == 'FREQ':
            self.btn_marker_freq = self.btn_marker_primary
            self.btn_marker_freq_endless = self.btn_marker_primary_endless

        # 3. Zoom
        self.btn_zoom = QPushButton("")
        self.btn_zoom.setIcon(self._get_icon("zoom_mode"))
        self.btn_zoom.setIconSize(QSize(32, 32))
        self.btn_zoom.setObjectName("mode_btn")
        self.btn_zoom.setToolTip("Zoom Mode (Rubberband)")
        self.btn_zoom.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_zoom, 0, 2)

        # 4. Home
        self.btn_home = QPushButton("")
        self.btn_home.setIcon(self._get_icon("reset_zoom"))
        self.btn_home.setIconSize(QSize(32, 32))
        self.btn_home.setObjectName("mode_btn")
        self.btn_home.setToolTip("Reset Zoom (Home)")
        self.mode_btn_layout.addWidget(self.btn_home, 0, 3)

        # --- Row 2 ---

        # 2. Magnitude
        self.btn_marker_mag = DoubleClickButton("")
        self.btn_marker_mag.setIcon(self._get_icon("horizontal_markers"))
        self.btn_marker_mag.setIconSize(QSize(32, 32))
        self.btn_marker_mag.setObjectName("mode_btn")
        self.btn_marker_mag.setToolTip("Magnitude Markers (Double-click to clear)")
        self.btn_marker_mag.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_mag, 1, 0)

        # 2b. Endless Magnitude
        self.btn_marker_mag_endless = DoubleClickButton("")
        self.btn_marker_mag_endless.setIcon(self._get_icon("endless_horizontal_markers"))
        self.btn_marker_mag_endless.setIconSize(QSize(32, 32))
        self.btn_marker_mag_endless.setObjectName("mode_btn")
        self.btn_marker_mag_endless.setToolTip("Endless Magnitude Markers")
        self.btn_marker_mag_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_mag_endless, 1, 1)

        # 5. Move
        self.btn_move = QPushButton("")
        self.btn_move.setIcon(self._get_icon("free_move_mode"))
        self.btn_move.setIconSize(QSize(32, 32))
        self.btn_move.setObjectName("mode_btn")
        self.btn_move.setToolTip("Free Move Mode (Pan)")
        self.btn_move.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_move, 1, 2)

        stats_col = 3
        if self.has_filter_mode:
            # 6. BPF / Filter Mode
            self.btn_bpf = DoubleClickButton("")
            self.btn_bpf.setIcon(self._get_icon("bpf_selection_mode"))
            self.btn_bpf.setIconSize(QSize(32, 32))
            self.btn_bpf.setObjectName("mode_btn")
            self.btn_bpf.setToolTip("BPF / BSF Filter Mode (Double-click to clear)")
            self.btn_bpf.setCheckable(True)
            self.mode_btn_layout.addWidget(self.btn_bpf, 1, 3)
            stats_col = 4

        # Stats
        self.btn_stats = DoubleClickButton("")
        self.btn_stats.setIcon(self._get_icon("region_statistics"))
        self.btn_stats.setIconSize(QSize(32, 32))
        self.btn_stats.setObjectName("mode_btn")
        self.btn_stats.setToolTip("Region Statistics (Double-click to clear)")
        self.btn_stats.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_stats, 1, stats_col)
        self.btn_home.clicked.connect(self.resetZoomRequested.emit)

        # Mutual Exclusion Group
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_primary)
        self.mode_group.addButton(self.btn_marker_primary_endless)
        self.mode_group.addButton(self.btn_marker_mag)
        self.mode_group.addButton(self.btn_marker_mag_endless)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        if self.has_filter_mode:
            self.mode_group.addButton(self.btn_bpf)
        self.mode_group.addButton(self.btn_stats)
        self.mode_group.setExclusive(True)

        # Connections
        pm = self.primary_mode
        pme = self.primary_endless_mode
        self.btn_marker_primary.clicked.connect(lambda: self.interactionModeChanged.emit(pm))
        self.btn_marker_primary_endless.clicked.connect(lambda: self.interactionModeChanged.emit(pme))
        self.btn_marker_mag.clicked.connect(lambda: self.interactionModeChanged.emit('MAG'))
        self.btn_marker_mag_endless.clicked.connect(lambda: self.interactionModeChanged.emit('MAG_ENDLESS'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        if self.has_filter_mode:
            self.btn_bpf.clicked.connect(lambda: self.interactionModeChanged.emit('FILTER'))
        self.btn_stats.clicked.connect(lambda: self.interactionModeChanged.emit('STATS'))

        self.btn_marker_primary.doubleClicked.connect(lambda: self.markerClearRequested.emit(pm))
        self.btn_marker_primary_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit(pme))
        self.btn_marker_mag.doubleClicked.connect(lambda: self.markerClearRequested.emit('Y'))
        self.btn_marker_mag_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit('MAG_ENDLESS'))
        if self.has_filter_mode:
            self.btn_bpf.doubleClicked.connect(lambda: self.markerClearRequested.emit('FILTER'))
        self.btn_stats.doubleClicked.connect(lambda: self.markerClearRequested.emit('STATS'))

        # --- Stacked Widget for Marker Data ---
        self.stacked = QStackedWidget()
        self.main_layout.addWidget(self.stacked, 1)

        # Page 1: Fixed Grid (Marker 1, 2, Delta, Center)
        self.fixed_widget = QWidget()
        self.stacked.addWidget(self.fixed_widget)
        self.grid = QGridLayout(self.fixed_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)

        # Table Headers
        self.grid.addWidget(QLabel(""), 0, 0)

        self.btn_lock_m1 = QPushButton("Marker 1")
        self.btn_lock_m1.setFont(self.header_font)
        self.btn_lock_m1.setCheckable(True)
        self.grid.addWidget(self.btn_lock_m1, 0, 1, Qt.AlignmentFlag.AlignCenter)

        self.btn_lock_m2 = QPushButton("Marker 2")
        self.btn_lock_m2.setFont(self.header_font)
        self.btn_lock_m2.setCheckable(True)
        self.grid.addWidget(self.btn_lock_m2, 0, 2, Qt.AlignmentFlag.AlignCenter)

        self.btn_lock_delta = QPushButton("Delta (Δ)")
        self.btn_lock_delta.setFont(self.header_font)
        self.btn_lock_delta.setCheckable(True)
        self.grid.addWidget(self.btn_lock_delta, 0, 3)

        self.btn_lock_center = QPushButton("Center")
        self.btn_lock_center.setFont(self.header_font)
        self.btn_lock_center.setCheckable(True)
        self.grid.addWidget(self.btn_lock_center, 0, 4)

        self._setup_extra_fixed_grid()

        # Side labels (Row names)
        self.row_v1_label = QLabel(self.row_v1_default)
        self.row_v2_label = QLabel(self.row_v2_default)
        self.row_v1_label.setObjectName("header_label")
        self.row_v2_label.setObjectName("header_label")
        self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row_v2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if self.has_v3_row:
            self.row_v3_label = QLabel(self.row_v3_default)
            self.row_v3_label.setObjectName("header_label")
            self.grid.addWidget(self.row_v3_label, 3, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Edit Widgets
        self.m_widgets = []
        for i in range(2):
            v2_edit = FormattedLineEdit(); v2_edit.setFixedWidth(130); v2_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v1_edit = FormattedLineEdit(); v1_edit.setFixedWidth(130); v1_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)

            v1_edit.setObjectName(f"m{i}_v1")
            v2_edit.setObjectName(f"m{i}_v2")

            for w in [v1_edit, v2_edit]:
                w.returnPressed.connect(self.controller.marker_edit_finished)

            self.grid.addWidget(v2_edit, 1, i + 1)
            self.grid.addWidget(v1_edit, 2, i + 1)

            entry = {'v1': v1_edit, 'v2': v2_edit}
            if self.has_v3_row:
                v3_edit = FormattedLineEdit(); v3_edit.setFixedWidth(130); v3_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
                v3_edit.setObjectName(f"m{i}_v3")
                v3_edit.setReadOnly(True)
                self.grid.addWidget(v3_edit, 3, i + 1)
                entry['v3'] = v3_edit

            self.m_widgets.append(entry)

        # Delta/Center Edits
        self.delta_v2 = FormattedLineEdit(); self.delta_v2.setFixedWidth(130); self.delta_v2.setObjectName("delta_v2"); self.delta_v2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_v1 = FormattedLineEdit(); self.delta_v1.setFixedWidth(130); self.delta_v1.setObjectName("delta_v1"); self.delta_v1.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.center_v2 = FormattedLineEdit(); self.center_v2.setFixedWidth(130); self.center_v2.setObjectName("center_v2"); self.center_v2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_v1 = FormattedLineEdit(); self.center_v1.setFixedWidth(130); self.center_v1.setObjectName("center_v1"); self.center_v1.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self.delta_v2_readonly:
            self.delta_v2.setReadOnly(True)
            self.center_v2.setReadOnly(True)
            editable_dc = [self.delta_v1, self.center_v1]
        else:
            editable_dc = [self.delta_v1, self.delta_v2, self.center_v1, self.center_v2]

        for w in editable_dc:
            w.returnPressed.connect(self.controller.marker_edit_finished)

        self.grid.addWidget(self.delta_v2, 1, 3)
        self.grid.addWidget(self.delta_v1, 2, 3)
        self.grid.addWidget(self.center_v2, 1, 4)
        self.grid.addWidget(self.center_v1, 2, 4)

        if self.has_v3_row:
            self.delta_v3 = FormattedLineEdit(); self.delta_v3.setFixedWidth(130); self.delta_v3.setObjectName("delta_v3"); self.delta_v3.setAlignment(Qt.AlignmentFlag.AlignCenter); self.delta_v3.setReadOnly(True)
            self.center_v3 = FormattedLineEdit(); self.center_v3.setFixedWidth(130); self.center_v3.setObjectName("center_v3"); self.center_v3.setAlignment(Qt.AlignmentFlag.AlignCenter); self.center_v3.setReadOnly(True)
            self.grid.addWidget(self.delta_v3, 3, 3)
            self.grid.addWidget(self.center_v3, 3, 4)

        # Connect locks
        self.btn_lock_m1.toggled.connect(self.on_lock_m1_toggled)
        self.btn_lock_m2.toggled.connect(self.on_lock_m2_toggled)
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)

        self.btn_marker_primary.setChecked(True)

        # Page 2: Endless Table
        self.endless_widget = EndlessMarkerListWidget(self.controller)
        self.endless_widget.bind_aliases_to_panel(self)
        self.stacked.addWidget(self.endless_widget)

        # Page 3: Statistics Layout
        self.stats_widget = RegionStatsWidget(
            self.controller,
            header_font=self.header_font,
            has_inv_row=self.stats_has_inv_row,
            has_integrated=self.stats_has_integrated,
            is_freq=self.stats_is_freq,
        )
        self.stats_widget.bind_aliases_to_panel(self)
        self.stacked.addWidget(self.stats_widget)

        focus_less = [
            self.btn_marker_primary, self.btn_marker_primary_endless,
            self.btn_marker_mag, self.btn_marker_mag_endless,
            self.btn_zoom, self.btn_move, self.btn_home, self.btn_stats,
            self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center,
        ]
        if self.has_filter_mode:
            focus_less.append(self.btn_bpf)
        focus_less.extend(self._get_extra_nofocus_widgets())
        for w in focus_less:
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Apply theme (must be done AFTER buttons are initialized)
        self.refresh_theme()

    def _setup_extra_fixed_grid(self):
        """Hook for subclasses to add extra widgets to self.grid during setup_ui."""
        pass

    def _get_extra_nofocus_widgets(self):
        """Hook for subclasses to return extra widgets that should have NoFocus."""
        return []

    def _on_percentile_toggled(self, checked=False):
        if hasattr(self.controller, 'update_statistics'):
            self.controller.update_statistics()

    def clear_stats_fields(self):
        """Clear all text fields in the Statistics Definition and Results tabs."""
        self.stats_widget.clear()

    def _get_icon(self, name, theme="Light"):
        """Helper to load icons from resources/assets."""
        return get_theme_icon(name, theme)

    def set_y_label(self, label):
        pass

    def _resolve_base_mode(self, mode):
        if mode in [self.primary_endless_mode, 'MAG_ENDLESS']:
            return self.primary_mode if self.primary_mode in mode else 'MAG'
        return mode

    def _switch_stacked_page(self, mode, valid_modes):
        """Track last marker mode, switch stacked widget page, and return display_mode."""
        if mode in valid_modes:
            self.last_marker_mode = mode

        display_mode = self.last_marker_mode if mode in ['ZOOM', 'MOVE'] else mode
        actual_ui_mode = display_mode

        if actual_ui_mode == 'STATS':
            if self.stacked.currentIndex() != 2:
                self.btn_stats_res.setChecked(True)
                self.stats_sub_stack.setCurrentIndex(1)
            self.stacked.setCurrentIndex(2)
        elif 'ENDLESS' in actual_ui_mode:
            self.stacked.setCurrentIndex(1)
        else:
            self.stacked.setCurrentIndex(0)

        return display_mode

    def _sync_lock_buttons_for_mode(self, display_mode):
        base_mode = self._resolve_base_mode(display_mode)
        if base_mode in self.lock_states:
            for key, btn_list in [
                ('m1',     [self.btn_lock_m1,     getattr(self, 'st_btn_lock_m1',     None)]),
                ('m2',     [self.btn_lock_m2,     getattr(self, 'st_btn_lock_m2',     None)]),
                ('delta',  [self.btn_lock_delta,  getattr(self, 'st_btn_lock_delta',  None)]),
                ('center', [self.btn_lock_center, getattr(self, 'st_btn_lock_center', None)]),
            ]:
                locked = self.lock_states[base_mode].get(key, False)
                for btn in btn_list:
                    if btn:
                        btn.blockSignals(True)
                        btn.setChecked(locked)
                        btn.setEnabled('ENDLESS' not in display_mode)
                        btn.blockSignals(False)

    def update_mode_ui(self, mode):
        btns = [
            self.btn_marker_primary, self.btn_marker_primary_endless,
            self.btn_marker_mag, self.btn_marker_mag_endless,
            self.btn_zoom, self.btn_move, self.btn_stats,
        ]
        if self.has_filter_mode:
            btns.append(self.btn_bpf)

        for btn in btns:
            btn.blockSignals(True)

        self.btn_marker_primary.setChecked(mode == self.primary_mode)
        self.btn_marker_primary_endless.setChecked(mode == self.primary_endless_mode)
        self.btn_marker_mag.setChecked(mode == 'MAG')
        self.btn_marker_mag_endless.setChecked(mode == 'MAG_ENDLESS')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        if self.has_filter_mode:
            self.btn_bpf.setChecked(mode == 'FILTER')
        self.btn_stats.setChecked(mode == 'STATS')

        for btn in btns:
            btn.blockSignals(False)

        self.btn_lock_delta.setEnabled(mode in [self.primary_mode, 'MAG'])
        self.btn_lock_center.setEnabled(mode in [self.primary_mode, 'MAG'])
        if hasattr(self, 'st_btn_lock_delta'):
            self.st_btn_lock_delta.setEnabled(mode == 'STATS')
            self.st_btn_lock_center.setEnabled(mode == 'STATS')

        if hasattr(self, 'filter_container'):
            self.filter_container.setVisible(mode == 'FILTER')

    def _clear_marker_locks(self, mode, keep=None):
        """Uncheck all marker-position locks except the one named in `keep`."""
        base_mode = self._resolve_base_mode(mode)
        if base_mode not in self.lock_states:
            return

        for key, btns in [
            ('m1',     [self.btn_lock_m1,     getattr(self, 'st_btn_lock_m1',     None)]),
            ('m2',     [self.btn_lock_m2,     getattr(self, 'st_btn_lock_m2',     None)]),
            ('delta',  [self.btn_lock_delta,  getattr(self, 'st_btn_lock_delta',  None)]),
            ('center', [self.btn_lock_center, getattr(self, 'st_btn_lock_center', None)]),
        ]:
            if key == keep:
                continue
            for btn in btns:
                if btn:
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
            self.lock_states[base_mode][key] = False

    def set_locks_enabled(self, m1_placed, m2_placed):
        """Enable/disable lock buttons based on marker presence."""
        self.btn_lock_m1.setEnabled(m1_placed)
        self.btn_lock_m2.setEnabled(m2_placed)

        can_pair_lock = m1_placed and m2_placed
        self.btn_lock_delta.setEnabled(can_pair_lock)
        self.btn_lock_center.setEnabled(can_pair_lock)

        if not m1_placed and self.btn_lock_m1.isChecked():
            self.btn_lock_m1.setChecked(False)
        if not m2_placed and self.btn_lock_m2.isChecked():
            self.btn_lock_m2.setChecked(False)
        if not can_pair_lock:
            if self.btn_lock_delta.isChecked():
                self.btn_lock_delta.setChecked(False)
            if self.btn_lock_center.isChecked():
                self.btn_lock_center.setChecked(False)

    def _on_lock_toggled(self, lock_key, checked):
        mode = self.controller.interaction_mode
        base_mode = self.primary_mode if self.primary_mode in mode else 'MAG'
        if base_mode not in self.lock_states:
            return
        self.lock_states[base_mode][lock_key] = checked
        if checked:
            self._clear_marker_locks(mode, keep=lock_key)
        self.controller.handle_lock_change(lock_key, checked)

    def on_lock_delta_toggled(self, checked):
        self._on_lock_toggled('delta', checked)

    def on_lock_center_toggled(self, checked):
        self._on_lock_toggled('center', checked)

    def on_lock_m1_toggled(self, checked):
        self._on_lock_toggled('m1', checked)

    def on_lock_m2_toggled(self, checked):
        self._on_lock_toggled('m2', checked)

    def flip_m_lock(self, mode):
        """Silently swap the m1/m2 lock buttons when markers cross each other."""
        base_mode = self._resolve_base_mode(mode)

        m1 = self.lock_states[base_mode]['m1']
        m2 = self.lock_states[base_mode]['m2']
        if not m1 and not m2:
            return

        self.lock_states[base_mode]['m1'] = m2
        self.lock_states[base_mode]['m2'] = m1

        self.btn_lock_m1.blockSignals(True)
        self.btn_lock_m2.blockSignals(True)
        self.btn_lock_m1.setChecked(m2)
        self.btn_lock_m2.setChecked(m1)
        self.btn_lock_m1.blockSignals(False)
        self.btn_lock_m2.blockSignals(False)

    def _get_settings_mgr(self):
        pw = getattr(self.controller, "parent_window", None)
        if pw and getattr(pw, "settings_mgr", None):
            return pw.settings_mgr
        return getattr(self.controller, "settings_mgr", None)

    def update_button_tooltips(self):
        s = self._get_settings_mgr()
        if s is None:
            return
        self._update_domain_tooltips(s)
        self.btn_marker_mag.setToolTip(format_tooltip_with_keybind(
            "Magnitude Markers (Double-click to clear)", s.get("keybinds/mag_markers", "M")
        ))
        self.btn_marker_mag_endless.setToolTip(format_tooltip_with_keybind(
            "Endless Magnitude Markers (Double-click to clear)", s.get("keybinds/mag_endless_markers", "N")
        ))
        self.btn_zoom.setToolTip(format_tooltip_with_keybind(
            "Zoom Mode (Rubberband)", s.get("keybinds/zoom_mode", "Ctrl"), is_hold=True
        ))
        self.btn_move.setToolTip(format_tooltip_with_keybind(
            "Free Move Mode (Pan)", s.get("keybinds/move_mode", "Space"), is_hold=True
        ))
        self.btn_home.setToolTip(format_tooltip_with_keybind(
            "Reset Zoom (Home)", s.get("keybinds/reset_zoom", "R")
        ))
        self.btn_stats.setToolTip(format_tooltip_with_keybind(
            "Region Statistics (Double-click to clear)", s.get("keybinds/stats_mode", "S")
        ))
        self.btn_lock_m1.setToolTip(format_tooltip_with_keybind(
            "Lock Marker 1", s.get("keybinds/lock_m1", "1")
        ))
        self.btn_lock_m2.setToolTip(format_tooltip_with_keybind(
            "Lock Marker 2", s.get("keybinds/lock_m2", "2")
        ))
        self.btn_lock_delta.setToolTip(format_tooltip_with_keybind(
            "Lock Delta (Δ)", s.get("keybinds/lock_delta", "D")
        ))
        self.btn_lock_center.setToolTip(format_tooltip_with_keybind(
            "Lock Center", s.get("keybinds/lock_center", "C")
        ))
        self.btn_stats_def.setToolTip(format_tooltip_with_keybind(
            "Stats Region Definition", s.get("keybinds/stats_def", "Q")
        ))
        self.btn_stats_res.setToolTip(format_tooltip_with_keybind(
            "Stats Measurement Results", s.get("keybinds/stats_res", "W")
        ))

    def _update_domain_tooltips(self, settings_mgr):
        """Hook for subclasses to update domain-specific button tooltips."""
        pass

    def refresh_theme(self):
        s = self._get_settings_mgr()
        theme = s.get("ui/theme", "Dark") if s else "Dark"
        p = get_palette(theme)
        self.update_button_tooltips()

        self.btn_marker_primary.setIcon(self._get_icon("vertical_markers", theme))
        self.btn_marker_primary_endless.setIcon(self._get_icon("endless_vertical_markers", theme))
        self.btn_marker_mag.setIcon(self._get_icon("horizontal_markers", theme))
        self.btn_marker_mag_endless.setIcon(self._get_icon("endless_horizontal_markers", theme))
        self.btn_zoom.setIcon(self._get_icon("zoom_mode", theme))
        self.btn_move.setIcon(self._get_icon("free_move_mode", theme))
        if self.has_filter_mode:
            self.btn_bpf.setIcon(self._get_icon("bpf_selection_mode", theme))
        self.btn_stats.setIcon(self._get_icon("region_statistics", theme))
        self.btn_home.setIcon(self._get_icon("reset_zoom", theme))

        cls_name = self.__class__.__name__
        self.setStyleSheet(f"""
            {cls_name} {{ 
                background-color: {p.bg_widget}; 
                border-radius: 6px;
                border: 1px solid {p.border};
            }}
            QPushButton#mode_btn {{
                background-color: transparent; 
                border: 2px solid transparent;
                border-radius: 4px;
                min-width: 32px;
                min-height: 32px;
                font-size: 16px;
                padding: 0;
            }}
            QPushButton#mode_btn:hover {{ background-color: {p.border}; }}
            QPushButton#mode_btn:checked {{ 
                background-color: {p.accent_dim}; 
                border: 2px solid {p.accent};
                color: {p.accent};
            }}
            QPushButton#stats_tab_btn {{
                background-color: transparent; 
                border: 1px solid {p.border};
                border-radius: 4px;
                color: {p.text_dim};
                font-weight: bold;
                padding: 2px 10px;
                font-size: 10px;
                text-transform: uppercase;
            }}
            QPushButton#stats_tab_btn:hover {{
                border-color: {p.accent_dim};
                color: {p.text_main};
            }}
            QPushButton#stats_tab_btn:checked {{
                background-color: {p.accent};
                color: {p.bg_widget};
                border-color: {p.accent};
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
                if btn:
                    btn.setStyleSheet(lock_style)

        if hasattr(self, 'st_btn_lock_m1'):
            for btn in [self.st_btn_lock_m1, self.st_btn_lock_m2, self.st_btn_lock_delta, self.st_btn_lock_center]:
                if btn:
                    btn.setStyleSheet(lock_style)

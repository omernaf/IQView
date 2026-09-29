from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QHBoxLayout, QButtonGroup, QStackedWidget, QWidget, QVBoxLayout, QScrollArea, QCheckBox
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap
import importlib.resources
import os
from ..widgets import FormattedLineEdit, DoubleClickButton, format_tooltip_with_keybind, get_theme_icon
from ..themes import get_palette
from ..base_1d import RegionStatsWidget, EndlessMarkerListWidget

class TimeDomainMarkerPanel(QFrame):
    interactionModeChanged = pyqtSignal(str) # 'TIME', 'MAG', 'ZOOM', 'MOVE'
    resetZoomRequested = pyqtSignal()
    markerClearRequested = pyqtSignal(str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.lock_states = {
            'TIME': {'delta': False, 'center': False, 'm1': False, 'm2': False},
            'MAG':  {'delta': False, 'center': False, 'm1': False, 'm2': False}
        }
        self.last_marker_mode = 'TIME'
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(160) 
        self.header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 6, 15, 6)
        self.main_layout.setSpacing(15)

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(6)
        self.main_layout.addLayout(self.mode_btn_layout)

        # 1. Time (Top-Left)
        self.btn_marker_time = DoubleClickButton("")
        self.btn_marker_time.setIcon(self._get_icon("vertical_markers"))
        self.btn_marker_time.setIconSize(QSize(32, 32))
        self.btn_marker_time.setObjectName("mode_btn")
        self.btn_marker_time.setToolTip("Time Markers (Double-click to clear)")
        self.btn_marker_time.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)
        
        # 1b. Endless Time
        self.btn_marker_time_endless = DoubleClickButton("")
        self.btn_marker_time_endless.setIcon(self._get_icon("endless_vertical_markers"))
        self.btn_marker_time_endless.setIconSize(QSize(32, 32))
        self.btn_marker_time_endless.setObjectName("mode_btn")
        self.btn_marker_time_endless.setToolTip("Endless Time Markers")
        self.btn_marker_time_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time_endless, 0, 1)

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
        
        # 6. Stats
        self.btn_stats = DoubleClickButton("")
        self.btn_stats.setIcon(self._get_icon("region_statistics"))
        self.btn_stats.setIconSize(QSize(32, 32))
        self.btn_stats.setObjectName("mode_btn")
        self.btn_stats.setToolTip("Region Statistics (Double-click to clear)")
        self.btn_stats.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_stats, 1, 3)
        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        
        # Mutual Exclusion Group
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_time_endless)
        self.mode_group.addButton(self.btn_marker_mag)
        self.mode_group.addButton(self.btn_marker_mag_endless)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.addButton(self.btn_stats)
        self.mode_group.setExclusive(True)

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_time_endless.clicked.connect(lambda: self.interactionModeChanged.emit('TIME_ENDLESS'))
        self.btn_marker_mag.clicked.connect(lambda: self.interactionModeChanged.emit('MAG'))
        self.btn_marker_mag_endless.clicked.connect(lambda: self.interactionModeChanged.emit('MAG_ENDLESS'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        self.btn_stats.clicked.connect(lambda: self.interactionModeChanged.emit('STATS'))
        
        self.btn_marker_time.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME'))
        self.btn_marker_time_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME_ENDLESS'))
        self.btn_marker_mag.doubleClicked.connect(lambda: self.markerClearRequested.emit('Y')) 
        self.btn_marker_mag_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit('MAG_ENDLESS'))
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
        self.row_v1_label = QLabel("Samples")
        self.row_v2_label = QLabel("Time (sec)")
        self.row_v3_label = QLabel("1/T (Hz)")
        self.row_v1_label.setObjectName("header_label")
        self.row_v2_label.setObjectName("header_label")
        self.row_v3_label.setObjectName("header_label")
        self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row_v2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row_v3_label, 3, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Edit Widgets (3 Rows)
        self.m_widgets = []
        for i in range(2):
            v2_edit = FormattedLineEdit(); v2_edit.setFixedWidth(130); v2_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v1_edit = FormattedLineEdit(); v1_edit.setFixedWidth(130); v1_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v3_edit = FormattedLineEdit(); v3_edit.setFixedWidth(130); v3_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            v1_edit.setObjectName(f"m{i}_v1")
            v2_edit.setObjectName(f"m{i}_v2")
            v3_edit.setObjectName(f"m{i}_v3")
            
            for w in [v1_edit, v2_edit]:
                w.returnPressed.connect(self.controller.marker_edit_finished)
            v3_edit.setReadOnly(True)
                
            self.grid.addWidget(v2_edit, 1, i + 1)
            self.grid.addWidget(v1_edit, 2, i + 1)
            self.grid.addWidget(v3_edit, 3, i + 1)
            self.m_widgets.append({'v1': v1_edit, 'v2': v2_edit, 'v3': v3_edit})

        # Delta/Center Edits
        self.delta_v2 = FormattedLineEdit(); self.delta_v2.setFixedWidth(130); self.delta_v2.setObjectName("delta_v2"); self.delta_v2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_v1 = FormattedLineEdit(); self.delta_v1.setFixedWidth(130); self.delta_v1.setObjectName("delta_v1"); self.delta_v1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_v3 = FormattedLineEdit(); self.delta_v3.setFixedWidth(130); self.delta_v3.setObjectName("delta_v3"); self.delta_v3.setAlignment(Qt.AlignmentFlag.AlignCenter); self.delta_v3.setReadOnly(True)
        
        self.center_v2 = FormattedLineEdit(); self.center_v2.setFixedWidth(130); self.center_v2.setObjectName("center_v2"); self.center_v2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_v1 = FormattedLineEdit(); self.center_v1.setFixedWidth(130); self.center_v1.setObjectName("center_v1"); self.center_v1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_v3 = FormattedLineEdit(); self.center_v3.setFixedWidth(130); self.center_v3.setObjectName("center_v3"); self.center_v3.setAlignment(Qt.AlignmentFlag.AlignCenter); self.center_v3.setReadOnly(True)
        
        for w in [self.delta_v1, self.delta_v2, self.center_v1, self.center_v2]:
            w.returnPressed.connect(self.controller.marker_edit_finished)
            
        self.grid.addWidget(self.delta_v2, 1, 3); self.grid.addWidget(self.delta_v1, 2, 3); self.grid.addWidget(self.delta_v3, 3, 3)
        self.grid.addWidget(self.center_v2, 1, 4); self.grid.addWidget(self.center_v1, 2, 4); self.grid.addWidget(self.center_v3, 3, 4)
        
        # Connect locks
        self.btn_lock_m1.toggled.connect(self.on_lock_m1_toggled)
        self.btn_lock_m2.toggled.connect(self.on_lock_m2_toggled)
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)
        
        self.btn_marker_time.setChecked(True)

        # Page 2: Endless Table
        self.endless_widget = EndlessMarkerListWidget(self.controller)
        self.endless_widget.bind_aliases_to_panel(self)
        self.stacked.addWidget(self.endless_widget)

        # Page 3: Statistics Layout
        self.stats_widget = RegionStatsWidget(
            self.controller,
            header_font=self.header_font,
            has_inv_row=True,
            has_integrated=False,
            is_freq=False,
        )
        self.stats_widget.bind_aliases_to_panel(self)
        self.stacked.addWidget(self.stats_widget)

        for w in [
            self.btn_marker_time, self.btn_marker_time_endless,
            self.btn_marker_mag, self.btn_marker_mag_endless,
            self.btn_zoom, self.btn_move, self.btn_home, self.btn_stats,
            self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center,
        ]:
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Apply theme (must be done AFTER buttons are initialized)
        self.refresh_theme()

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
        # We handle this via update_headers now
        pass

    def update_headers(self, mode, y_axis_label="Magnitude"):
        self.row_v1_label.blockSignals(True)
        self.row_v2_label.blockSignals(True)
        
        # Track the last valid marker mode OR stats mode so we can return to it when zooming
        if mode in ['TIME', 'MAG', 'TIME_ENDLESS', 'MAG_ENDLESS', 'STATS']:
            self.last_marker_mode = mode
            
        display_mode = self.last_marker_mode if mode in ['ZOOM', 'MOVE'] else mode
        
        # Handle Page Switching
        # We must use the cached last_marker_mode if we are currently panning/zooming, 
        # because we want to preserve the UI of the last thing the user was doing.
        actual_ui_mode = self.last_marker_mode if mode in ['ZOOM', 'MOVE'] else mode
        
        if actual_ui_mode == 'STATS':
            if self.stacked.currentIndex() != 2:
                self.btn_stats_res.setChecked(True)
                self.stats_sub_stack.setCurrentIndex(1)
            self.stacked.setCurrentIndex(2)
        elif 'ENDLESS' in actual_ui_mode:
            self.stacked.setCurrentIndex(1)
        else:
            self.stacked.setCurrentIndex(0)

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
        else: # MAG
            self.row_v1_label.setText(y_axis_label)
            self.row_v1_label.show()
            self.row_v2_label.hide()
            self.row_v3_label.hide()
            
            # Move Magnitude widgets (v1) to Row 1
            self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2): 
                self.grid.addWidget(self.m_widgets[i]['v1'], 1, i + 1) # v1 is Mag
                self.m_widgets[i]['v1'].show()
                self.m_widgets[i]['v2'].hide()
                self.m_widgets[i]['v3'].hide()
            self.grid.addWidget(self.delta_v1, 1, 3); self.delta_v1.show()
            self.grid.addWidget(self.center_v1, 1, 4); self.center_v1.show()
            self.delta_v2.hide(); self.delta_v3.hide()
            self.center_v2.hide(); self.center_v3.hide()
            
        self.row_v1_label.blockSignals(False)
        self.row_v2_label.blockSignals(False)

        # Sync lock UI with saved state for this display mode
        base_mode = display_mode
        if display_mode in ['TIME_ENDLESS', 'MAG_ENDLESS']: 
             base_mode = 'TIME' if 'TIME' in display_mode else 'MAG'
        
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
        self.btn_marker_time.blockSignals(True)
        self.btn_marker_time_endless.blockSignals(True)
        self.btn_marker_mag.blockSignals(True)
        self.btn_marker_mag_endless.blockSignals(True)
        self.btn_zoom.blockSignals(True)
        self.btn_move.blockSignals(True)
        self.btn_stats.blockSignals(True)
        
        self.btn_marker_time.setChecked(mode == 'TIME')
        self.btn_marker_time_endless.setChecked(mode == 'TIME_ENDLESS')
        self.btn_marker_mag.setChecked(mode == 'MAG')
        self.btn_marker_mag_endless.setChecked(mode == 'MAG_ENDLESS')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        self.btn_stats.setChecked(mode == 'STATS')
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_time_endless.blockSignals(False)
        self.btn_marker_mag.blockSignals(False)
        self.btn_marker_mag_endless.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)
        self.btn_stats.blockSignals(False)
        
        self.btn_lock_delta.setEnabled(mode in ['TIME', 'MAG'])
        self.btn_lock_center.setEnabled(mode in ['TIME', 'MAG'])
        if hasattr(self, 'st_btn_lock_delta'):
            self.st_btn_lock_delta.setEnabled(mode == 'STATS')
            self.st_btn_lock_center.setEnabled(mode == 'STATS')

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

    def _clear_marker_locks(self, mode, keep=None):
        """Uncheck all marker-position locks except the one named in `keep`."""
        base_mode = mode
        if base_mode in ['TIME_ENDLESS', 'MAG_ENDLESS']: 
             base_mode = 'TIME' if 'TIME' in base_mode else 'MAG'
             
        if base_mode not in self.lock_states: return

        for key, btns in [
            ('m1',     [self.btn_lock_m1,     getattr(self, 'st_btn_lock_m1',     None)]),
            ('m2',     [self.btn_lock_m2,     getattr(self, 'st_btn_lock_m2',     None)]),
            ('delta',  [self.btn_lock_delta,  getattr(self, 'st_btn_lock_delta',  None)]),
            ('center', [self.btn_lock_center, getattr(self, 'st_btn_lock_center', None)]),
        ]:
            if key == keep: continue
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
        
        # If a marker was removed, ensure its lock is released
        if not m1_placed and self.btn_lock_m1.isChecked(): self.on_lock_m1_toggled(False)
        if not m2_placed and self.btn_lock_m2.isChecked(): self.on_lock_m2_toggled(False)
        if not can_pair_lock:
            if self.btn_lock_delta.isChecked(): self.on_lock_delta_toggled(False)
            if self.btn_lock_center.isChecked(): self.on_lock_center_toggled(False)

    def on_lock_delta_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        if base_mode not in self.lock_states: return
        self.lock_states[base_mode]['delta'] = checked
        if checked: self._clear_marker_locks(mode, keep='delta')
        self.controller.handle_lock_change('delta', checked)

    def on_lock_center_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        if base_mode not in self.lock_states: return
        self.lock_states[base_mode]['center'] = checked
        if checked: self._clear_marker_locks(mode, keep='center')
        self.controller.handle_lock_change('center', checked)

    def on_lock_m1_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        if base_mode not in self.lock_states: return
        self.lock_states[base_mode]['m1'] = checked
        if checked: self._clear_marker_locks(mode, keep='m1')
        self.controller.handle_lock_change('m1', checked)

    def on_lock_m2_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        if base_mode not in self.lock_states: return
        self.lock_states[base_mode]['m2'] = checked
        if checked: self._clear_marker_locks(mode, keep='m2')
        self.controller.handle_lock_change('m2', checked)

    def flip_m_lock(self, mode):
        """Silently swap the m1/m2 lock buttons when markers cross each other."""
        base_mode = mode
        if base_mode in ['TIME_ENDLESS', 'MAG_ENDLESS']: 
             base_mode = 'TIME' if 'TIME' in base_mode else 'MAG'

        m1 = self.lock_states[base_mode]['m1']
        m2 = self.lock_states[base_mode]['m2']
        if not m1 and not m2: return
        
        self.lock_states[base_mode]['m1'] = m2
        self.lock_states[base_mode]['m2'] = m1
        
        # Update buttons
        self.btn_lock_m1.blockSignals(True); self.btn_lock_m2.blockSignals(True)
        self.btn_lock_m1.setChecked(m2);     self.btn_lock_m2.setChecked(m1)
        self.btn_lock_m1.blockSignals(False); self.btn_lock_m2.blockSignals(False)

    def update_button_tooltips(self):
        s = self.controller.parent_window.settings_mgr
        self.btn_marker_time.setToolTip(format_tooltip_with_keybind(
            "Time Markers (Double-click to clear)", s.get("keybinds/time_markers", "T")
        ))
        self.btn_marker_time_endless.setToolTip(format_tooltip_with_keybind(
            "Endless Time Markers (Double-click to clear)", s.get("keybinds/time_endless_markers", "E")
        ))
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

    def refresh_theme(self):
        theme = self.controller.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.update_button_tooltips()
        
        # Update Icons based on theme
        self.btn_marker_time.setIcon(self._get_icon("vertical_markers", theme))
        self.btn_marker_time_endless.setIcon(self._get_icon("endless_vertical_markers", theme))
        self.btn_marker_mag.setIcon(self._get_icon("horizontal_markers", theme))
        self.btn_marker_mag_endless.setIcon(self._get_icon("endless_horizontal_markers", theme))
        self.btn_zoom.setIcon(self._get_icon("zoom_mode", theme))
        self.btn_move.setIcon(self._get_icon("free_move_mode", theme))
        self.btn_stats.setIcon(self._get_icon("region_statistics", theme))
        self.btn_home.setIcon(self._get_icon("reset_zoom", theme))
        
        self.setStyleSheet(f"""
            TimeDomainMarkerPanel {{ 
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
        for btn in [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]:
            btn.setStyleSheet(lock_style)
        
        if hasattr(self, 'st_btn_lock_m1'):
            for btn in [self.st_btn_lock_m1, self.st_btn_lock_m2, self.st_btn_lock_delta, self.st_btn_lock_center]:
                if btn: btn.setStyleSheet(lock_style)

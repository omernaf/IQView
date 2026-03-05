from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QHBoxLayout, QButtonGroup, QStackedWidget, QWidget, QVBoxLayout, QScrollArea
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from ..widgets import FormattedLineEdit, DoubleClickButton
from ..themes import get_palette

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
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(95) # Reduced height for 2 rows
        self.header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self.refresh_theme()
        
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 6, 15, 6)
        self.main_layout.setSpacing(15)

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(6)
        self.main_layout.addLayout(self.mode_btn_layout)

        # 1. Time (Top-Left)
        self.btn_marker_time = DoubleClickButton("║")
        self.btn_marker_time.setObjectName("mode_btn")
        self.btn_marker_time.setToolTip("Time Markers (Double-click to clear) [T]")
        self.btn_marker_time.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)
        
        # 1b. Endless Time
        self.btn_marker_time_endless = DoubleClickButton("⫼")
        self.btn_marker_time_endless.setObjectName("mode_btn")
        self.btn_marker_time_endless.setToolTip("Endless Time Markers")
        self.btn_marker_time_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time_endless, 0, 1)

        # 2. Magnitude (Bottom-Left)
        self.btn_marker_mag = DoubleClickButton("〓")
        self.btn_marker_mag.setObjectName("mode_btn")
        self.btn_marker_mag.setToolTip("Magnitude Markers (Double-click to clear) [F/M]")
        self.btn_marker_mag.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_mag, 1, 0)

        # 2b. Endless Magnitude
        self.btn_marker_mag_endless = DoubleClickButton("≡")
        self.btn_marker_mag_endless.setObjectName("mode_btn")
        self.btn_marker_mag_endless.setToolTip("Endless Magnitude Markers")
        self.btn_marker_mag_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_mag_endless, 1, 1)
        
        # 3. Zoom
        self.btn_zoom = QPushButton("🔍")
        self.btn_zoom.setObjectName("mode_btn")
        self.btn_zoom.setToolTip("Zoom Mode [Hold Ctrl]")
        self.btn_zoom.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_zoom, 0, 2)
        
        # 4. Move
        self.btn_move = QPushButton("✥")
        self.btn_move.setObjectName("mode_btn")
        self.btn_move.setToolTip("Free Move Mode")
        self.btn_move.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_move, 1, 2)
        
        # 5. Home
        self.btn_home = QPushButton("🏠")
        self.btn_home.setObjectName("mode_btn")
        self.btn_home.setToolTip("Reset Zoom")
        self.mode_btn_layout.addWidget(self.btn_home, 0, 3)
        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        
        # Mutual Exclusion Group
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_time_endless)
        self.mode_group.addButton(self.btn_marker_mag)
        self.mode_group.addButton(self.btn_marker_mag_endless)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.setExclusive(True)

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_time_endless.clicked.connect(lambda: self.interactionModeChanged.emit('TIME_ENDLESS'))
        self.btn_marker_mag.clicked.connect(lambda: self.interactionModeChanged.emit('MAG'))
        self.btn_marker_mag_endless.clicked.connect(lambda: self.interactionModeChanged.emit('MAG_ENDLESS'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        
        self.btn_marker_time.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME'))
        self.btn_marker_time_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME_ENDLESS'))
        self.btn_marker_mag.doubleClicked.connect(lambda: self.markerClearRequested.emit('Y')) 
        self.btn_marker_mag_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit('MAG_ENDLESS'))

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
        
        self.btn_lock_m1 = QPushButton("Marker 1 🔓")
        self.btn_lock_m1.setFont(self.header_font)
        self.btn_lock_m1.setCheckable(True)
        self.grid.addWidget(self.btn_lock_m1, 0, 1, Qt.AlignmentFlag.AlignCenter)

        self.btn_lock_m2 = QPushButton("Marker 2 🔓")
        self.btn_lock_m2.setFont(self.header_font)
        self.btn_lock_m2.setCheckable(True)
        self.grid.addWidget(self.btn_lock_m2, 0, 2, Qt.AlignmentFlag.AlignCenter)

        # Delta Header (Combined with Lock)
        self.btn_lock_delta = QPushButton("Delta (Δ) 🔓")
        self.btn_lock_delta.setFont(self.header_font)
        self.btn_lock_delta.setCheckable(True)
        self.btn_lock_delta.setCheckable(True)
        # Style moved to refresh_theme
        self.grid.addWidget(self.btn_lock_delta, 0, 3)

        # Center Header (Combined with Lock)
        self.btn_lock_center = QPushButton("Center 🔓")
        self.btn_lock_center.setFont(self.header_font)
        self.btn_lock_center.setCheckable(True)
        self.btn_lock_center.setCheckable(True)
        # Style moved to refresh_theme
        self.grid.addWidget(self.btn_lock_center, 0, 4)

        # Side labels (Row names)
        self.row_v1_label = QLabel("Time (sec)")
        self.row_v2_label = QLabel("Samples")
        self.row_v1_label.setObjectName("header_label")
        self.row_v2_label.setObjectName("header_label")
        self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row_v2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Edit Widgets (2 Rows)
        self.m_widgets = []
        for i in range(2):
            v1_edit = FormattedLineEdit(); v1_edit.setFixedWidth(130); v1_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v2_edit = FormattedLineEdit(); v2_edit.setFixedWidth(130); v2_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            v1_edit.setObjectName(f"m{i}_v1")
            v2_edit.setObjectName(f"m{i}_v2")
            
            for w in [v1_edit, v2_edit]:
                w.returnPressed.connect(self.controller.marker_edit_finished)
                
            self.grid.addWidget(v1_edit, 1, i + 1)
            self.grid.addWidget(v2_edit, 2, i + 1)
            self.m_widgets.append({'v1': v1_edit, 'v2': v2_edit})

        # Delta/Center Edits
        self.delta_v1 = FormattedLineEdit(); self.delta_v1.setFixedWidth(130); self.delta_v1.setObjectName("delta_v1"); self.delta_v1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_v2 = FormattedLineEdit(); self.delta_v2.setFixedWidth(130); self.delta_v2.setObjectName("delta_v2"); self.delta_v2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.center_v1 = FormattedLineEdit(); self.center_v1.setFixedWidth(130); self.center_v1.setObjectName("center_v1"); self.center_v1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_v2 = FormattedLineEdit(); self.center_v2.setFixedWidth(130); self.center_v2.setObjectName("center_v2"); self.center_v2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        for w in [self.delta_v1, self.delta_v2, self.center_v1, self.center_v2]:
            w.returnPressed.connect(self.controller.marker_edit_finished)
            
        self.grid.addWidget(self.delta_v1, 1, 3); self.grid.addWidget(self.delta_v2, 2, 3)
        self.grid.addWidget(self.center_v1, 1, 4); self.grid.addWidget(self.center_v2, 2, 4)
        
        # Connect locks
        self.btn_lock_m1.toggled.connect(self.on_lock_m1_toggled)
        self.btn_lock_m2.toggled.connect(self.on_lock_m2_toggled)
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)
        
        self.btn_marker_time.setChecked(True)

        # Page 2: Endless Table
        self.endless_widget = QWidget()
        self.stacked.addWidget(self.endless_widget)
        self.endless_layout = QVBoxLayout(self.endless_widget)
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

    def set_y_label(self, label):
        # We handle this via update_headers now
        pass

    def update_headers(self, mode, y_axis_label="Magnitude"):
        self.row_v1_label.blockSignals(True)
        self.row_v2_label.blockSignals(True)
        
        # Handle Page Switching
        if 'ENDLESS' in mode:
            self.stacked.setCurrentIndex(1)
        else:
            self.stacked.setCurrentIndex(0)

        if mode in ['TIME', 'TIME_ENDLESS']:
            self.row_v1_label.setText("Time (sec)")
            self.row_v2_label.setText("Samples")
            self.row_v2_label.show()
            for i in range(2): self.m_widgets[i]['v2'].show()
            self.delta_v2.show()
            self.center_v2.show()
        else: # MAG
            self.row_v1_label.setText(y_axis_label)
            self.row_v2_label.setText("")
            self.row_v2_label.hide()
            for i in range(2): self.m_widgets[i]['v2'].hide()
            self.delta_v2.hide()
            self.center_v2.hide()
            
        self.row_v1_label.blockSignals(False)
        self.row_v2_label.blockSignals(False)

        # Sync lock UI with saved state for this mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        if base_mode in self.lock_states:
            for key, btn, label_fn in [
                ('m1',     self.btn_lock_m1,     lambda c: f"Marker 1 {'🔒' if c else '🔓'}"),
                ('m2',     self.btn_lock_m2,     lambda c: f"Marker 2 {'🔒' if c else '🔓'}"),
                ('delta',  self.btn_lock_delta,  lambda c: f"Delta (Δ) {'🔒' if c else '🔓'}"),
                ('center', self.btn_lock_center, lambda c: f"Center {'🔒' if c else '🔓'}"),
            ]:
                locked = self.lock_states[base_mode].get(key, False)
                btn.blockSignals(True)
                btn.setChecked(locked)
                btn.setText(label_fn(locked))
                btn.setEnabled('ENDLESS' not in mode)
                btn.blockSignals(False)

    def update_mode_ui(self, mode):
        self.btn_marker_time.blockSignals(True)
        self.btn_marker_time_endless.blockSignals(True)
        self.btn_marker_mag.blockSignals(True)
        self.btn_marker_mag_endless.blockSignals(True)
        self.btn_zoom.blockSignals(True)
        self.btn_move.blockSignals(True)
        
        self.btn_marker_time.setChecked(mode == 'TIME')
        self.btn_marker_time_endless.setChecked(mode == 'TIME_ENDLESS')
        self.btn_marker_mag.setChecked(mode == 'MAG')
        self.btn_marker_mag_endless.setChecked(mode == 'MAG_ENDLESS')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_time_endless.blockSignals(False)
        self.btn_marker_mag.blockSignals(False)
        self.btn_marker_mag_endless.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)
        
        self.btn_lock_delta.setEnabled(mode in ['TIME', 'MAG'])
        self.btn_lock_center.setEnabled(mode in ['TIME', 'MAG'])

    def update_endless_list(self, markers, mode):
        """Update the scroll area with rows for each endless marker, reusing widgets where possible."""
        is_time = 'TIME' in mode
        unit_main = "sec" if is_time else self.controller.y_label_text
        unit_sub = "Sam" if is_time else ""
        
        # 1. Initialize or find internal row storage
        if not hasattr(self, '_endless_rows'):
            self._endless_rows = []
        if not hasattr(self, '_header_widget'):
            self._header_widget = QWidget()
            h_layout = QHBoxLayout(self._header_widget)
            h_layout.setContentsMargins(5, 2, 5, 2)
            h_layout.setSpacing(10)
            
            l_id = QLabel("ID"); l_id.setFixedWidth(30); l_id.setObjectName("header_label")
            l_main = QLabel(f"Pos ({unit_main})"); l_main.setObjectName("header_label")
            l_main.setProperty("role", "pos_header")
            l_sub = QLabel(unit_sub); l_sub.setObjectName("header_label")
            l_sub.setProperty("role", "sub_header")
            l_del = QLabel(""); l_del.setFixedWidth(24)
            
            h_layout.addWidget(l_id)
            h_layout.addWidget(l_main, 1)
            h_layout.addWidget(l_sub, 1)
            h_layout.addWidget(l_del)
            self.scroll_layout.insertWidget(0, self._header_widget)
            self.refresh_theme() # Apply theme to new header

        # 2. Update header labels
        for lbl in self._header_widget.findChildren(QLabel, "header_label"):
            if lbl.property("role") == "pos_header":
                lbl.setText(f"Pos ({unit_main})")
            elif lbl.property("role") == "sub_header":
                lbl.setText(unit_sub)
        
        if not is_time:
            # Hide sub-header if in MAG mode
            for lbl in self._header_widget.findChildren(QLabel, "header_label"):
                if lbl.property("role") == "sub_header": lbl.hide()
        else:
            for lbl in self._header_widget.findChildren(QLabel, "header_label"):
                if lbl.property("role") == "sub_header": lbl.show()

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
            row_layout.addWidget(edit_pos, 1)
            row_layout.addWidget(edit_sub, 1)
            row_layout.addWidget(btn_del)
            
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
            prec = 9 if is_time else 6
            
            row_data['lbl_id'].setText(f"M{i+1}")
            
            row_data['edit_pos'].blockSignals(True)
            row_data['edit_pos'].setObjectName(f"em_{i}_sec")
            row_data['edit_pos'].setText(f"{val:.{prec}f}")
            row_data['edit_pos'].blockSignals(False)
            
            if is_time:
                sub_val = int(round(val * self.controller.rate)) + 1
                row_data['edit_sub'].show()
                row_data['edit_sub'].blockSignals(True)
                row_data['edit_sub'].setObjectName(f"em_{i}_sam")
                row_data['edit_sub'].setText(f"{sub_val}")
                row_data['edit_sub'].blockSignals(False)
            else:
                row_data['edit_sub'].hide()
            
            try: row_data['btn_del'].clicked.disconnect()
            except: pass
            row_data['btn_del'].clicked.connect(lambda _, m=m: self.controller.remove_marker_item(m, mode))

    def _clear_marker_locks(self, mode, keep=None):
        """Uncheck all marker-position locks except the one named in `keep`."""
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        for key, btn, label in [
            ('m1',     self.btn_lock_m1,     lambda c: f"Marker 1 {'🔒' if c else '🔓'}"),
            ('m2',     self.btn_lock_m2,     lambda c: f"Marker 2 {'🔒' if c else '🔓'}"),
            ('delta',  self.btn_lock_delta,  lambda c: f"Delta (Δ) {'🔒' if c else '🔓'}"),
            ('center', self.btn_lock_center, lambda c: f"Center {'🔒' if c else '🔓'}"),
        ]:
            if key == keep: continue
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.setText(label(False))
            self.lock_states[base_mode][key] = False
            btn.blockSignals(False)

    def on_lock_delta_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        self.lock_states[base_mode]['delta'] = checked
        if checked: self._clear_marker_locks(mode, keep='delta')
        self.btn_lock_delta.setText(f"Delta (Δ) {'🔒' if checked else '🔓'}")
        self.controller.handle_lock_change('delta', checked)

    def on_lock_center_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        self.lock_states[base_mode]['center'] = checked
        if checked: self._clear_marker_locks(mode, keep='center')
        self.btn_lock_center.setText(f"Center {'🔒' if checked else '🔓'}")
        self.controller.handle_lock_change('center', checked)

    def on_lock_m1_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        self.lock_states[base_mode]['m1'] = checked
        if checked: self._clear_marker_locks(mode, keep='m1')
        self.btn_lock_m1.setText(f"Marker 1 {'🔒' if checked else '🔓'}")
        self.controller.handle_lock_change('m1', checked)

    def on_lock_m2_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        self.lock_states[base_mode]['m2'] = checked
        if checked: self._clear_marker_locks(mode, keep='m2')
        self.btn_lock_m2.setText(f"Marker 2 {'🔒' if checked else '🔓'}")
        self.controller.handle_lock_change('m2', checked)

    def flip_m_lock(self, mode):
        """Silently swap the m1/m2 lock buttons when markers cross each other."""
        base_mode = 'TIME' if 'TIME' in mode else 'MAG'
        m1 = self.btn_lock_m1.isChecked()
        m2 = self.btn_lock_m2.isChecked()
        if not m1 and not m2: return
        self.btn_lock_m1.blockSignals(True); self.btn_lock_m2.blockSignals(True)
        self.btn_lock_m1.setChecked(m2); self.btn_lock_m2.setChecked(m1)
        self.btn_lock_m1.setText(f"Marker 1 {'🔒' if m2 else '🔓'}")
        self.btn_lock_m2.setText(f"Marker 2 {'🔒' if m1 else '🔓'}")
        self.lock_states[base_mode]['m1'] = m2
        self.lock_states[base_mode]['m2'] = m1
        self.btn_lock_m1.blockSignals(False); self.btn_lock_m2.blockSignals(False)

    def refresh_theme(self):
        theme = self.controller.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        self.setStyleSheet(f"""
            TimeDomainMarkerPanel {{ 
                background-color: {p.bg_widget}; 
                border-radius: 6px;
                border: 1px solid {p.border};
            }}
            QPushButton#mode_btn {{
                background-color: {p.bg_sidebar};
                border: 1px solid {p.border};
                border-radius: 4px;
                min-width: 32px;
                min-height: 32px;
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
            QPushButton {{ background: none; border: none; color: {p.text_dim}; padding: 0; text-transform: uppercase; font-size: 10px; }}
            QPushButton:hover {{ color: {p.text_header}; }}
            QPushButton:checked {{ color: {p.accent}; }}
        """
        if hasattr(self, 'btn_lock_delta'):
            for btn in [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]:
                btn.setStyleSheet(lock_style)

from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QCheckBox, QPushButton, QHBoxLayout, QStackedWidget, QWidget, QScrollArea, QVBoxLayout, QButtonGroup
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from .widgets import FormattedLineEdit, DoubleClickButton
from .themes import get_palette

class MarkerPanel(QFrame):
    interactionModeChanged = pyqtSignal(str) # 'TIME', 'FREQ', 'ZOOM'
    resetZoomRequested = pyqtSignal()
    markerClearRequested = pyqtSignal(str)

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(115)
        self.header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self.mono_font = QFont("Consolas", 10)
        self.refresh_theme()
        
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 8, 15, 8)
        self.main_layout.setSpacing(15)

        # State
        self.current_mode = 'TIME'
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
        self.btn_marker_time = DoubleClickButton("║")
        self.btn_marker_time.setObjectName("mode_btn")
        self.btn_marker_time.setToolTip("Time Markers (Double-click to clear)")
        self.btn_marker_time.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)
        
        # 2. Freq (Bottom-Left)
        self.btn_marker_freq = DoubleClickButton("〓")
        self.btn_marker_freq.setObjectName("mode_btn")
        self.btn_marker_freq.setToolTip("Frequency Markers (Double-click to clear)")
        self.btn_marker_freq.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq, 1, 0)
        
        # 3. Zoom
        self.btn_zoom = QPushButton("🔍")
        self.btn_zoom.setObjectName("mode_btn")
        self.btn_zoom.setToolTip("Zoom Mode (Rubberband)")
        self.btn_zoom.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_zoom, 0, 1)
        
        # 4. Move
        self.btn_move = QPushButton("✥")
        self.btn_move.setObjectName("mode_btn")
        self.btn_move.setToolTip("Free Move Mode (Pan)")
        self.btn_move.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_move, 1, 1)
        
        # 5. Home
        self.btn_home = QPushButton("🏠")
        self.btn_home.setObjectName("mode_btn")
        self.btn_home.setToolTip("Reset Zoom (Home)")
        self.mode_btn_layout.addWidget(self.btn_home, 0, 2)

        # 6. BPF Mode
        self.btn_bpf = DoubleClickButton("📊")
        self.btn_bpf.setObjectName("mode_btn")
        self.btn_bpf.setToolTip("BPF Selection Mode (Double-click to clear)")
        self.btn_bpf.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_bpf, 1, 2)

        # 7. Time Endless
        self.btn_marker_time_endless = DoubleClickButton("⫼")
        self.btn_marker_time_endless.setObjectName("mode_btn")
        self.btn_marker_time_endless.setToolTip("Endless Time Markers")
        self.btn_marker_time_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time_endless, 0, 3)

        # 8. Freq Endless
        self.btn_marker_freq_endless = DoubleClickButton("≡")
        self.btn_marker_freq_endless.setObjectName("mode_btn")
        self.btn_marker_freq_endless.setToolTip("Endless Frequency Markers")
        self.btn_marker_freq_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq_endless, 1, 3)

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
        self.mode_group.setExclusive(True)

        # Connections

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_freq.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ'))
        self.btn_marker_time_endless.clicked.connect(lambda: self.interactionModeChanged.emit('TIME_ENDLESS'))
        self.btn_marker_freq_endless.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ_ENDLESS'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        self.btn_bpf.clicked.connect(lambda: self.interactionModeChanged.emit('FILTER'))
        
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
        self.grid.addWidget(self.btn_lock_delta, 0, 3)

        # Center Header (Combined with Lock)
        self.btn_lock_center = QPushButton("Center 🔓")
        self.btn_lock_center.setFont(self.header_font)
        self.btn_lock_center.setCheckable(True)
        self.grid.addWidget(self.btn_lock_center, 0, 4)

        # Side labels (Row names)
        self.row1_label = QLabel("Time (sec)")
        self.row2_label = QLabel("Samples")
        self.row1_label.setObjectName("header_label")
        self.row2_label.setObjectName("header_label")
        self.grid.addWidget(self.row1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Edit Widgets
        self.widgets = []
        for i in range(2):
            sec_edit = FormattedLineEdit(); sec_edit.setFixedWidth(130); sec_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sam_edit = FormattedLineEdit(); sam_edit.setFixedWidth(130); sam_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_edit.setObjectName(f"m{i}_sec")
            sam_edit.setObjectName(f"m{i}_sam")
            sec_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            sam_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            self.grid.addWidget(sec_edit, 1, i + 1)
            self.grid.addWidget(sam_edit, 2, i + 1)
            self.widgets.append({'sec': sec_edit, 'sam': sam_edit})

        # Delta/Center Edits
        self.delta_sec = FormattedLineEdit(); self.delta_sec.setFixedWidth(130); self.delta_sec.setObjectName("delta_sec"); self.delta_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sam = FormattedLineEdit(); self.delta_sam.setFixedWidth(130); self.delta_sam.setObjectName("delta_sam"); self.delta_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sec = FormattedLineEdit(); self.center_sec.setFixedWidth(130); self.center_sec.setObjectName("center_sec"); self.center_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sam = FormattedLineEdit(); self.center_sam.setFixedWidth(130); self.center_sam.setObjectName("center_sam"); self.center_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        for w in [self.delta_sec, self.delta_sam, self.center_sec, self.center_sam]:
            w.returnPressed.connect(self.parent_window.marker_edit_finished)
            
        self.grid.addWidget(self.delta_sec, 1, 3); self.grid.addWidget(self.delta_sam, 2, 3)
        self.grid.addWidget(self.center_sec, 1, 4); self.grid.addWidget(self.center_sam, 2, 4)

        # Connect locks to parent
        self.btn_lock_m1.toggled.connect(self.on_lock_m1_toggled)
        self.btn_lock_m2.toggled.connect(self.on_lock_m2_toggled)
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)

        # Filter Activation Checkbox (Moved next to table)
        self.filter_container = QWidget()
        self.filter_layout = QVBoxLayout(self.filter_container)
        self.filter_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_layout.setSpacing(0)
        
        self.filter_enable_cb = QCheckBox("Filter On")
        self.filter_enable_cb.setToolTip("Enable Band-Pass Filter")
        self.filter_layout.addStretch()
        self.filter_layout.addWidget(self.filter_enable_cb)
        self.filter_layout.addStretch()
        
        self.filter_container.setFixedWidth(80)
        self.filter_enable_cb.setEnabled(False)
        self.filter_container.setVisible(False)
        self.grid.addWidget(self.filter_container, 1, 5, 2, 1)
        self.filter_enable_cb.toggled.connect(self.parent_window.on_filter_toggled)
        
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

        # Explicit Default Force
        self.btn_marker_time.setChecked(True)
        self.interactionModeChanged.emit('TIME')

    def _clear_marker_locks(self, mode=None, keep=None):
        """Uncheck all marker-position locks except the one named in `keep`."""
        target_mode = mode if mode else self.current_mode
        if target_mode not in self.lock_states: return

        for key, btn, label in [
            ('m1',     self.btn_lock_m1,     lambda c: f"Marker 1 {'🔒' if c else '🔓'}"),
            ('m2',     self.btn_lock_m2,     lambda c: f"Marker 2 {'🔒' if c else '🔓'}"),
            ('delta',  self.btn_lock_delta,  lambda c: f"Delta (Δ) {'🔒' if c else '🔓'}"),
            ('center', self.btn_lock_center, lambda c: f"Center {'🔒' if c else '🔓'}"),
        ]:
            if key == keep:
                continue
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.setText(label(False))
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
        self.btn_lock_delta.setText(f"Delta (Δ) {'🔒' if checked else '🔓'}")
        self.parent_window.handle_lock_change('delta', checked)

    def on_lock_center_toggled(self, checked):
        self.lock_states[self.current_mode]['center'] = checked
        if checked:
            self._clear_marker_locks(keep='center')
        self.btn_lock_center.setText(f"Center {'🔒' if checked else '🔓'}")
        self.parent_window.handle_lock_change('center', checked)

    def on_lock_m1_toggled(self, checked):
        self.lock_states[self.current_mode]['m1'] = checked
        if checked:
            self._clear_marker_locks(keep='m1')
        self.btn_lock_m1.setText(f"Marker 1 {'🔒' if checked else '🔓'}")
        self.parent_window.handle_lock_change('m1', checked)

    def on_lock_m2_toggled(self, checked):
        self.lock_states[self.current_mode]['m2'] = checked
        if checked:
            self._clear_marker_locks(keep='m2')
        self.btn_lock_m2.setText(f"Marker 2 {'🔒' if checked else '🔓'}")
        self.parent_window.handle_lock_change('m2', checked)

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
        self.btn_lock_m1.setText(f"Marker 1 {'🔒' if m2 else '🔓'}")
        self.btn_lock_m2.setText(f"Marker 2 {'🔒' if m1 else '🔓'}")
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
        
        self.btn_marker_time.setChecked(mode == 'TIME')
        self.btn_marker_freq.setChecked(mode == 'FREQ')
        self.btn_marker_time_endless.setChecked(mode == 'TIME_ENDLESS')
        self.btn_marker_freq_endless.setChecked(mode == 'FREQ_ENDLESS')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        self.btn_bpf.setChecked(mode == 'FILTER')
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_freq.blockSignals(False)
        self.btn_marker_time_endless.blockSignals(False)
        self.btn_marker_freq_endless.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)
        self.btn_bpf.blockSignals(False)

        self.current_mode = mode
        
        if mode in ['TIME_ENDLESS', 'FREQ_ENDLESS']:
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)

        if mode in ['FREQ', 'FREQ_ENDLESS']:
            self.row1_label.setText("Freq (Hz)")
            self.row2_label.setText("Bin")
        elif mode in ['TIME', 'TIME_ENDLESS']:
            self.row1_label.setText("Time (sec)")
            self.row2_label.setText("Samples")
            # Enable checkbox only if 2 bounds are placed
            has_bounds = getattr(self.parent_window, 'filter_placed', False)
            self.filter_enable_cb.setEnabled(has_bounds)
            
        # Sync lock UI with saved state for this mode (if applicable)
        if mode in self.lock_states:
            for key, btn, label_fn in [
                ('m1',     self.btn_lock_m1,     lambda c: f"Marker 1 {'🔒' if c else '🔓'}"),
                ('m2',     self.btn_lock_m2,     lambda c: f"Marker 2 {'🔒' if c else '🔓'}"),
                ('delta',  self.btn_lock_delta,  lambda c: f"Delta (Δ) {'🔒' if c else '🔓'}"),
                ('center', self.btn_lock_center, lambda c: f"Center {'🔒' if c else '🔓'}"),
            ]:
                locked = self.lock_states[mode].get(key, False)
                btn.blockSignals(True)
                btn.setChecked(locked)
                btn.setText(label_fn(locked))
                btn.setEnabled(True)
                btn.blockSignals(False)
        else:
            for btn in [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]:
                btn.setEnabled(False)

    def update_endless_list(self, markers, mode):
        """Update the scroll area with rows for each endless marker, reusing widgets where possible."""
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
            l_main = QLabel(f"Pos ({unit_main})")
            l_main.setObjectName("header_label")
            l_main.setProperty("role", "pos_header")
            l_sub = QLabel(unit_sub)
            l_sub.setObjectName("header_label")
            l_sub.setProperty("role", "sub_header")
            l_del = QLabel(""); l_del.setFixedWidth(24)
            
            h_layout.addWidget(l_id)
            h_layout.addWidget(l_main, 1)
            h_layout.addWidget(l_sub, 1)
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
            
            edit_pos = FormattedLineEdit()
            edit_pos.setFixedHeight(24)
            edit_pos.returnPressed.connect(self.parent_window.marker_edit_finished)
            
            edit_sub = FormattedLineEdit()
            edit_sub.setFixedHeight(24)
            edit_sub.returnPressed.connect(self.parent_window.marker_edit_finished)
            
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

        # 3. Update header widget if units changed
        # (Assuming the header is the first item in scroll_layout)
        header_widget = self.scroll_layout.itemAt(0).widget()
        if header_widget and header_widget.findChild(QLabel, "header_label"):
            # Update labels to Hz/sec etc if needed
            labels = header_widget.findChildren(QLabel, "header_label")
            if len(labels) >= 2:
                labels[1].setText(f"Pos ({unit_main})")
                labels[2].setText(unit_sub)

        # 4. Update data for all rows
        for i, m in enumerate(markers):
            row_data = self._endless_rows[i]
            val = m.value()
            prec = int(self.parent_window.settings_mgr.get("ui/label_precision", 6 if is_freq else 9))
            
            row_data['lbl_id'].setText(f"M{i+1}")
            
            # Update position
            row_data['edit_pos'].blockSignals(True)
            row_data['edit_pos'].setObjectName(f"em_{i}_sec")
            row_data['edit_pos'].setText(f"{val:.{prec}f}")
            row_data['edit_pos'].blockSignals(False)
            
            # Update sub-unit
            if is_freq:
                rbw = self.parent_window.rate / self.parent_window.fft_size
                sub_val = int(round((val - (self.parent_window.fc - self.parent_window.rate/2)) / rbw)) + 1
            else:
                sub_val = int(round(val * self.parent_window.rate)) + 1
            
            row_data['edit_sub'].blockSignals(True)
            row_data['edit_sub'].setObjectName(f"em_{i}_sam")
            row_data['edit_sub'].setText(f"{sub_val}")
            row_data['edit_sub'].blockSignals(False)
            
            # Update delete button connection
            try: row_data['btn_del'].clicked.disconnect()
            except: pass
            row_data['btn_del'].clicked.connect(lambda _, m=m: self.parent_window.remove_marker_item(m, mode))

    def refresh_theme(self):
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        
        self.setStyleSheet(f"""
            MarkerPanel {{ 
                background-color: {p.bg_widget}; 
                border-bottom: 2px solid {p.bg_main};
            }}
            QPushButton#mode_btn {{
                background-color: {p.bg_sidebar};
                border: 1px solid {p.border};
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
            QPushButton {{ background: none; border: none; color: {p.text_dim}; padding: 0; text-transform: uppercase; font-size: 10px; }}
            QPushButton:hover {{ color: {p.text_header}; }}
            QPushButton:checked {{ color: {p.accent}; }}
        """
        if hasattr(self, 'btn_lock_delta'):
            for btn in [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]:
                btn.setStyleSheet(lock_style)

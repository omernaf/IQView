from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QCheckBox, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
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

        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        
        # Mutual Exclusion Group
        from PyQt6.QtWidgets import QButtonGroup
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_freq)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.addButton(self.btn_bpf)
        self.mode_group.setExclusive(True)

        # Connections

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_freq.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        self.btn_bpf.clicked.connect(lambda: self.interactionModeChanged.emit('FILTER'))
        
        self.btn_marker_time.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME'))
        self.btn_marker_freq.doubleClicked.connect(lambda: self.markerClearRequested.emit('FREQ'))
        self.btn_bpf.doubleClicked.connect(lambda: self.markerClearRequested.emit('FILTER'))

        # Grid for marker data
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        self.main_layout.addLayout(self.grid, 1)

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
        from PyQt6.QtWidgets import QVBoxLayout, QWidget
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
        
        # Explicit Default Force
        self.btn_marker_time.setChecked(True)
        self.interactionModeChanged.emit('TIME')

    def _clear_marker_locks(self, keep=None):
        """Uncheck all marker-position locks except the one named in `keep`."""
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
            self.lock_states[self.current_mode][key] = False
            btn.blockSignals(False)

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
        self.btn_zoom.blockSignals(True)
        self.btn_move.blockSignals(True)
        
        self.btn_marker_time.setChecked(mode == 'TIME')
        self.btn_marker_freq.setChecked(mode == 'FREQ')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        self.btn_bpf.setChecked(mode == 'FILTER')
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_freq.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)
        self.btn_bpf.blockSignals(False)

        self.current_mode = mode
        if mode == 'FREQ':
            self.row1_label.setText("Freq (Hz)")
            self.row2_label.setText("Bin")
        elif mode == 'TIME':
            self.row1_label.setText("Time (sec)")
            self.row2_label.setText("Samples")
        elif mode == 'FILTER':
            self.row1_label.setText("Freq (Hz)")
            self.row2_label.setText("Bin")
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

from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QCheckBox, QPushButton, QVBoxLayout, QWidget, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QMouseEvent

class DoubleClickButton(QPushButton):
    doubleClicked = pyqtSignal()
    
    def mouseDoubleClickEvent(self, a0: QMouseEvent) -> None:
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(a0)

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
        
        self.setStyleSheet("""
            MarkerPanel { 
                background-color: #252525; 
                border-bottom: 2px solid #1a1a1a;
            }
            QPushButton#mode_btn {
                background-color: #333;
                border: 1px solid #444;
                border-radius: 4px;
                min-width: 34px;
                min-height: 34px;
                font-size: 16px;
                padding: 0;
            }
            QPushButton#mode_btn:hover { background-color: #444; }
            QPushButton#mode_btn:checked { 
                background-color: #004488; 
                border-color: #00aaff;
                color: #00aaff;
            }
            QLineEdit {
                background-color: #151515;
                font-family: 'Consolas', 'Courier New';
                font-size: 13px;
                border: 1px solid #333;
                border-radius: 3px;
                padding: 2px 4px;
            }
            QLineEdit:focus { border-color: #00aaff; }
            QLabel#header_label {
                color: #888;
                font-size: 10px;
                text-transform: uppercase;
                font-weight: bold;
            }
        """)
        
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 8, 15, 8)
        self.main_layout.setSpacing(15)

        # State
        self.current_mode = 'TIME'
        self.lock_states = {
            'TIME': {'delta': False, 'center': False},
            'FREQ': {'delta': False, 'center': False}
        }

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(6)
        self.main_layout.addLayout(self.mode_btn_layout, 0)

        # 1. Time (Top-Left)
        self.btn_marker_time = DoubleClickButton("〓")
        self.btn_marker_time.setObjectName("mode_btn")
        self.btn_marker_time.setToolTip("Time Markers (Double-click to clear)")
        self.btn_marker_time.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)
        
        # 2. Freq (Bottom-Left)
        self.btn_marker_freq = DoubleClickButton("║")
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

        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        
        # Mutual Exclusion Group
        from PyQt6.QtWidgets import QButtonGroup
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_freq)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.setExclusive(True)

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_freq.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        
        self.btn_marker_time.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME'))
        self.btn_marker_freq.doubleClicked.connect(lambda: self.markerClearRequested.emit('FREQ'))

        # Grid for marker data
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        self.main_layout.addLayout(self.grid, 1)

        # Table Headers
        self.grid.addWidget(QLabel(""), 0, 0) # Top-left empty
        h1 = QLabel("Marker 1"); h1.setObjectName("header_label")
        h2 = QLabel("Marker 2"); h2.setObjectName("header_label")
        self.grid.addWidget(h1, 0, 1, Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(h2, 0, 2, Qt.AlignmentFlag.AlignCenter)

        # Delta Header (Combined with Lock)
        self.btn_lock_delta = QPushButton("Delta (Δ) 🔓")
        self.btn_lock_delta.setFont(self.header_font)
        self.btn_lock_delta.setCheckable(True)
        self.btn_lock_delta.setStyleSheet("""
            QPushButton { background: none; border: none; color: #888; padding: 0; text-transform: uppercase; font-size: 10px; }
            QPushButton:hover { color: #FFF; }
            QPushButton:checked { color: #00aaff; }
        """)
        self.grid.addWidget(self.btn_lock_delta, 0, 3)

        # Center Header (Combined with Lock)
        self.btn_lock_center = QPushButton("Center 🔓")
        self.btn_lock_center.setFont(self.header_font)
        self.btn_lock_center.setCheckable(True)
        self.btn_lock_center.setStyleSheet("""
            QPushButton { background: none; border: none; color: #888; padding: 0; text-transform: uppercase; font-size: 10px; }
            QPushButton:hover { color: #FFF; }
            QPushButton:checked { color: #00aaff; }
        """)
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
            sec_edit = QLineEdit(); sec_edit.setFixedWidth(130); sec_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sam_edit = QLineEdit(); sam_edit.setFixedWidth(130); sam_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_edit.setObjectName(f"m{i}_sec")
            sam_edit.setObjectName(f"m{i}_sam")
            sec_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            sam_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            self.grid.addWidget(sec_edit, 1, i + 1)
            self.grid.addWidget(sam_edit, 2, i + 1)
            self.widgets.append({'sec': sec_edit, 'sam': sam_edit})

        # Delta/Center Edits
        self.delta_sec = QLineEdit(); self.delta_sec.setFixedWidth(130); self.delta_sec.setObjectName("delta_sec"); self.delta_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sam = QLineEdit(); self.delta_sam.setFixedWidth(130); self.delta_sam.setObjectName("delta_sam"); self.delta_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sec = QLineEdit(); self.center_sec.setFixedWidth(130); self.center_sec.setObjectName("center_sec"); self.center_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sam = QLineEdit(); self.center_sam.setFixedWidth(130); self.center_sam.setObjectName("center_sam"); self.center_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        for w in [self.delta_sec, self.delta_sam, self.center_sec, self.center_sam]:
            w.returnPressed.connect(self.parent_window.marker_edit_finished)
            
        self.grid.addWidget(self.delta_sec, 1, 3); self.grid.addWidget(self.delta_sam, 2, 3)
        self.grid.addWidget(self.center_sec, 1, 4); self.grid.addWidget(self.center_sam, 2, 4)
        
        # Connect locks to parent
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)
        
        # Explicit Default Force
        self.btn_marker_time.setChecked(True)
        self.interactionModeChanged.emit('TIME')

    def on_lock_delta_toggled(self, checked):
        self.lock_states[self.current_mode]['delta'] = checked
        if checked:
            self.lock_states[self.current_mode]['center'] = False
        
        self.btn_lock_delta.setText(f"Delta (Δ) {'🔒' if checked else '🔓'}")
        self.parent_window.handle_lock_change('delta', checked)

    def on_lock_center_toggled(self, checked):
        self.lock_states[self.current_mode]['center'] = checked
        if checked:
            self.lock_states[self.current_mode]['delta'] = False
            
        self.btn_lock_center.setText(f"Center {'🔒' if checked else '🔓'}")
        self.parent_window.handle_lock_change('center', checked)

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
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_freq.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)

        self.current_mode = mode
        if mode == 'FREQ':
            self.row1_label.setText("Freq (Hz)")
            self.row2_label.setText("Bin")
        elif mode == 'TIME':
            self.row1_label.setText("Time (sec)")
            self.row2_label.setText("Samples")
            
        # Sync lock UI with saved state for this mode (if applicable)
        if mode in self.lock_states:
            self.btn_lock_delta.blockSignals(True)
            self.btn_lock_center.blockSignals(True)
            
            d_locked = self.lock_states[mode]['delta']
            c_locked = self.lock_states[mode]['center']
            
            self.btn_lock_delta.setChecked(d_locked)
            self.btn_lock_delta.setText(f"Delta (Δ) {'🔒' if d_locked else '🔓'}")
            
            self.btn_lock_center.setChecked(c_locked)
            self.btn_lock_center.setText(f"Center {'🔒' if c_locked else '🔓'}")
            
            self.btn_lock_delta.blockSignals(False)
            self.btn_lock_center.blockSignals(False)
            self.btn_lock_delta.setEnabled(True)
            self.btn_lock_center.setEnabled(True)
        else:
            self.btn_lock_delta.setEnabled(False)
            self.btn_lock_center.setEnabled(False)

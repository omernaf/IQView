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
        self.setStyleSheet("""
            QFrame { 
                background-color: #1e1e1e; 
                border: 1px solid #444; 
                border-bottom: none;
                border-radius: 0px; 
                padding: 4px; 
            }
            QLabel { 
                color: #DDD; 
            }
            QLineEdit {
                background-color: #111;
                color: #FFF;
                border: 1px solid #555;
                padding: 2px;
                border-radius: 2px;
            }
            QPushButton {
                background-color: #333;
                color: #EEE;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px;
                font-size: 14px;
                min-width: 40px;
                min-height: 40px;
            }
            QPushButton:hover {
                background-color: #444;
            }
            QPushButton:pressed {
                background-color: #222;
            }
            QPushButton:checked {
                background-color: #0066cc;
                border-color: #0088ff;
            }
        """)
        
        # Fonts (Init early for labels)
        self.header_font = QFont("Inter", 9, QFont.Weight.Bold)
        self.mono_font = QFont("Courier New", 10)

        # Main layout is horizontal to accommodate buttons on both sides
        self.main_layout = QGridLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(10)

        # State
        self.current_mode = 'TIME'
        self.lock_states = {
            'TIME': {'delta': False, 'center': False},
            'FREQ': {'delta': False, 'center': False}
        }

        # Row Labels (Init early to avoid AttributeError)
        self.row1_label = QLabel("Time (sec)")
        self.row2_label = QLabel("Samples")
        self.row1_label.setFont(self.header_font)
        self.row2_label.setFont(self.header_font)

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(5)
        self.main_layout.addLayout(self.mode_btn_layout, 0, 0)

        # Time Marker Button
        self.btn_marker_time = DoubleClickButton("║")
        self.btn_marker_time.setToolTip("Time Markers (Double-click to clear)")
        self.btn_marker_time.setCheckable(True)
        self.btn_marker_time.setChecked(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)

        # Frequency Marker Button
        self.btn_marker_freq = DoubleClickButton("〓")
        self.btn_marker_freq.setToolTip("Frequency Markers (Double-click to clear)")
        self.btn_marker_freq.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq, 1, 0)

        # Zoom Button
        self.btn_zoom = QPushButton("🔍")
        self.btn_zoom.setToolTip("Zoom Mode (Rubberband)")
        self.btn_zoom.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_zoom, 0, 1)
        
        # Move Button
        self.btn_move = QPushButton("✥")
        self.btn_move.setToolTip("Free Move Mode (Pan)")
        self.btn_move.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_move, 1, 1)
        
        # Home Button
        self.btn_home = QPushButton("🏠")
        self.btn_home.setToolTip("Reset Zoom (Home)")
        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        self.mode_btn_layout.addWidget(self.btn_home, 0, 2)

        # Mutual Exclusion Group
        from PyQt6.QtWidgets import QButtonGroup
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_freq)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.setExclusive(True)
        
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_freq.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        
        self.btn_marker_time.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME'))
        self.btn_marker_freq.doubleClicked.connect(lambda: self.markerClearRequested.emit('FREQ'))

        # Grid for marker data
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self.main_layout.addLayout(self.grid, 0, 1)
        
        # Table Headers (Columns)
        self.grid.addWidget(QLabel(""), 0, 0)
        
        # Row Labels (Placement)
        self.grid.addWidget(self.row1_label, 1, 0)
        self.grid.addWidget(self.row2_label, 2, 0)

        # Static Headers
        for col, text in enumerate(["Marker 1", "Marker 2"]):
            h = QLabel(text)
            h.setFont(self.header_font)
            h.setStyleSheet("color: #AAA;")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(h, 0, col + 1)

        # Delta Header (Combined with Lock)
        self.btn_lock_delta = QPushButton("Delta (Δ) 🔓")
        self.btn_lock_delta.setFont(self.header_font)
        self.btn_lock_delta.setCheckable(True)
        self.btn_lock_delta.setStyleSheet("""
            QPushButton { 
                background: none; 
                border: none; 
                color: #AAA; 
                padding: 0; 
                text-align: center;
            }
            QPushButton:hover { color: #FFF; background-color: #333; border-radius: 4px; }
            QPushButton:checked { color: #0088ff; }
        """)
        self.grid.addWidget(self.btn_lock_delta, 0, 3)

        # Center Header (Combined with Lock)
        self.btn_lock_center = QPushButton("Center 🔓")
        self.btn_lock_center.setFont(self.header_font)
        self.btn_lock_center.setCheckable(True)
        self.btn_lock_center.setStyleSheet("""
            QPushButton { 
                background: none; 
                border: none; 
                color: #AAA; 
                padding: 0; 
                text-align: center;
            }
            QPushButton:hover { color: #FFF; background-color: #333; border-radius: 4px; }
            QPushButton:checked { color: #0088ff; }
        """)
        self.grid.addWidget(self.btn_lock_center, 0, 4)

        # Edit Widgets
        self.widgets = []
        for i in range(2):
            sec_edit = QLineEdit()
            sec_edit.setFixedWidth(150)
            sec_edit.setFont(self.mono_font)
            sec_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_edit.setObjectName(f"m{i}_sec")
            
            sam_edit = QLineEdit()
            sam_edit.setFixedWidth(150)
            sam_edit.setFont(self.mono_font)
            sam_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sam_edit.setObjectName(f"m{i}_sam")
            
            sec_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            sam_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            
            self.grid.addWidget(sec_edit, 1, i + 1)
            self.grid.addWidget(sam_edit, 2, i + 1)
            self.widgets.append({'sec': sec_edit, 'sam': sam_edit})

        # Delta Edits
        self.delta_sec = QLineEdit()
        self.delta_sec.setFixedWidth(150)
        self.delta_sec.setFont(self.mono_font)
        self.delta_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sec.setObjectName("delta_sec")
        self.delta_sec.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.delta_sec, 1, 3)

        self.delta_sam = QLineEdit()
        self.delta_sam.setFixedWidth(150)
        self.delta_sam.setFont(self.mono_font)
        self.delta_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sam.setObjectName("delta_sam")
        self.delta_sam.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.delta_sam, 2, 3)

        # Center Edits
        self.center_sec = QLineEdit()
        self.center_sec.setFixedWidth(150)
        self.center_sec.setFont(self.mono_font)
        self.center_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sec.setObjectName("center_sec")
        self.center_sec.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.center_sec, 1, 4)

        self.center_sam = QLineEdit()
        self.center_sam.setFixedWidth(150)
        self.center_sam.setFont(self.mono_font)
        self.center_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sam.setObjectName("center_sam")
        self.center_sam.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.center_sam, 2, 4)
        
        # Connect locks to parent
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)

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
        self.current_mode = mode
        if mode == 'FREQ':
            self.row1_label.setText("Freq (Hz)")
            self.row2_label.setText("Bin")
        else:
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

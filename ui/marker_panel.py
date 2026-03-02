from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QCheckBox, QPushButton, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

class MarkerPanel(QFrame):
    interactionModeChanged = pyqtSignal(str) # 'TIME', 'FREQ', 'ZOOM'
    resetZoomRequested = pyqtSignal()

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QFrame { 
                background-color: #1e1e1e; 
                border: 1px solid #444; 
                border-radius: 6px; 
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
        
        # Main layout is horizontal to accommodate buttons on both sides
        self.main_layout = QGridLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(10)

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(5)
        self.main_layout.addLayout(self.mode_btn_layout, 0, 0)

        # Time Marker Button
        self.btn_marker_time = QPushButton("║")
        self.btn_marker_time.setToolTip("Time Marker Mode (Vertical Lines)")
        self.btn_marker_time.setCheckable(True)
        self.btn_marker_time.setChecked(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)

        # Freq Marker Button
        self.btn_marker_freq = QPushButton("〓")
        self.btn_marker_freq.setToolTip("Frequency Marker Mode (Horizontal Lines)")
        self.btn_marker_freq.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq, 0, 1)

        # Zoom Button
        self.btn_zoom = QPushButton("🔍")
        self.btn_zoom.setToolTip("Zoom Mode (Rubberband)")
        self.btn_zoom.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_zoom, 1, 0)
        
        # Home Button
        self.btn_home = QPushButton("🏠")
        self.btn_home.setToolTip("Reset Zoom (Home)")
        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        self.mode_btn_layout.addWidget(self.btn_home, 1, 1)

        # Mutual Exclusion Group
        from PyQt6.QtWidgets import QButtonGroup
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_freq)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.setExclusive(True)
        
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_freq.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))

        # Grid for marker data
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self.main_layout.addLayout(self.grid, 0, 1)
        
        header_font = QFont("Inter", 9, QFont.Weight.Bold)
        mono_font = QFont("Courier New", 10)

        # Table Headers (Columns)
        self.grid.addWidget(QLabel(""), 0, 0)
        col_headers = ["Marker 1", "Marker 2", "Delta (Δ)", "Center"]
        for col, text in enumerate(col_headers):
            h = QLabel(text)
            h.setFont(header_font)
            h.setStyleSheet("color: #AAA;")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(h, 0, col + 1)

        # Row Labels
        self.row1_label = QLabel("Time (sec)")
        self.row2_label = QLabel("Samples")
        self.row1_label.setFont(header_font)
        self.row2_label.setFont(header_font)
        self.grid.addWidget(self.row1_label, 1, 0)
        self.grid.addWidget(self.row2_label, 2, 0)

        # Edit Widgets
        self.widgets = []
        for i in range(2):
            sec_edit = QLineEdit()
            sec_edit.setFixedWidth(150)
            sec_edit.setFont(mono_font)
            sec_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_edit.setObjectName(f"m{i}_sec")
            
            sam_edit = QLineEdit()
            sam_edit.setFixedWidth(150)
            sam_edit.setFont(mono_font)
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
        self.delta_sec.setFont(mono_font)
        self.delta_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sec.setObjectName("delta_sec")
        self.delta_sec.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.delta_sec, 1, 3)

        self.delta_sam = QLineEdit()
        self.delta_sam.setFixedWidth(150)
        self.delta_sam.setFont(mono_font)
        self.delta_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sam.setObjectName("delta_sam")
        self.delta_sam.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.delta_sam, 2, 3)

        # Center Edits
        self.center_sec = QLineEdit()
        self.center_sec.setFixedWidth(150)
        self.center_sec.setFont(mono_font)
        self.center_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sec.setObjectName("center_sec")
        self.center_sec.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.center_sec, 1, 4)

        self.center_sam = QLineEdit()
        self.center_sam.setFixedWidth(150)
        self.center_sam.setFont(mono_font)
        self.center_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sam.setObjectName("center_sam")
        self.center_sam.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.center_sam, 2, 4)

        # Lock Row
        lock_label = QLabel("Lock State")
        lock_label.setFont(header_font)
        self.grid.addWidget(lock_label, 3, 0)
        
        self.lock_delta_cb = QCheckBox("Lock Delta (Δ)")
        self.lock_center_cb = QCheckBox("Lock Center")
        self.lock_delta_cb.setStyleSheet("color: #DDD;")
        self.lock_center_cb.setStyleSheet("color: #DDD;")
        
        self.grid.addWidget(self.lock_delta_cb, 3, 3)
        self.grid.addWidget(self.lock_center_cb, 3, 4)
        
        # Connect locks to parent - will move these connections to main_window for safety
        self.lock_delta_cb.toggled.connect(lambda checked: self.parent_window.handle_lock_change('delta', checked))
        self.lock_center_cb.toggled.connect(lambda checked: self.parent_window.handle_lock_change('center', checked))

    def update_headers(self, mode):
        if mode == 'FREQ':
            self.row1_label.setText("Freq (Hz)")
            self.row2_label.setText("Bin")
        else:
            self.row1_label.setText("Time (sec)")
            self.row2_label.setText("Samples")

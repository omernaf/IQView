from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QHBoxLayout, QButtonGroup
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from .widgets import FormattedLineEdit, DoubleClickButton

class TimeDomainMarkerPanel(QFrame):
    interactionModeChanged = pyqtSignal(str) # 'TIME', 'Y', 'ZOOM', 'MOVE'
    resetZoomRequested = pyqtSignal()
    markerClearRequested = pyqtSignal(str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(115)
        self.header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        
        self.setStyleSheet("""
            TimeDomainMarkerPanel { 
                background-color: #252525; 
                border-radius: 6px;
                border: 1px solid #333;
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
                color: #fff;
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

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(6)
        self.main_layout.addLayout(self.mode_btn_layout)

        # 1. Time (Top-Left)
        self.btn_marker_time = DoubleClickButton("║")
        self.btn_marker_time.setObjectName("mode_btn")
        self.btn_marker_time.setToolTip("Time Markers (Double-click to clear)")
        self.btn_marker_time.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)
        
        # 2. Y-Marker (Bottom-Left)
        self.btn_marker_y = DoubleClickButton("〓")
        self.btn_marker_y.setObjectName("mode_btn")
        self.btn_marker_y.setToolTip("Y Markers (Double-click to clear)")
        self.btn_marker_y.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_y, 1, 0)
        
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
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_y)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.setExclusive(True)

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_y.clicked.connect(lambda: self.interactionModeChanged.emit('Y'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        
        self.btn_marker_time.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME'))
        self.btn_marker_y.doubleClicked.connect(lambda: self.markerClearRequested.emit('Y'))

        # Grid for marker data
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        self.main_layout.addLayout(self.grid)

        # Table Headers
        self.grid.addWidget(QLabel(""), 0, 0) 
        h1 = QLabel("Marker 1"); h1.setObjectName("header_label")
        h2 = QLabel("Marker 2"); h2.setObjectName("header_label")
        delta_h = QLabel("Delta (Δ)"); delta_h.setObjectName("header_label")
        center_h = QLabel("Center"); center_h.setObjectName("header_label")
        self.grid.addWidget(h1, 0, 1, Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(h2, 0, 2, Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(delta_h, 0, 3, Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(center_h, 0, 4, Qt.AlignmentFlag.AlignCenter)

        # Side labels (Row names)
        self.row_time_label = QLabel("Time (sec)")
        self.row_y_label = QLabel("Value")
        self.row_time_label.setObjectName("header_label")
        self.row_y_label.setObjectName("header_label")
        self.grid.addWidget(self.row_time_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row_y_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Edit Widgets
        self.time_edits = []
        self.y_edits = []
        for i in range(2):
            t_edit = FormattedLineEdit(); t_edit.setFixedWidth(130); t_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            y_edit = FormattedLineEdit(); y_edit.setFixedWidth(130); y_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t_edit.returnPressed.connect(self.controller.marker_edit_finished)
            y_edit.returnPressed.connect(self.controller.marker_edit_finished)
            self.grid.addWidget(t_edit, 1, i + 1)
            self.grid.addWidget(y_edit, 2, i + 1)
            self.time_edits.append(t_edit)
            self.y_edits.append(y_edit)

        # Delta/Center Edits (Reference only for now, not locked like Spectrogram yet)
        self.delta_t = FormattedLineEdit(); self.delta_t.setFixedWidth(130); self.delta_t.setReadOnly(True); self.delta_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_y = FormattedLineEdit(); self.delta_y.setFixedWidth(130); self.delta_y.setReadOnly(True); self.delta_y.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_t = FormattedLineEdit(); self.center_t.setFixedWidth(130); self.center_t.setReadOnly(True); self.center_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_y = FormattedLineEdit(); self.center_y.setFixedWidth(130); self.center_y.setReadOnly(True); self.center_y.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.grid.addWidget(self.delta_t, 1, 3); self.grid.addWidget(self.delta_y, 2, 3)
        self.grid.addWidget(self.center_t, 1, 4); self.grid.addWidget(self.center_y, 2, 4)
        
        self.btn_marker_time.setChecked(True)

    def set_y_label(self, label):
        self.row_y_label.setText(label)

    def update_mode_ui(self, mode):
        self.btn_marker_time.blockSignals(True)
        self.btn_marker_y.blockSignals(True)
        self.btn_zoom.blockSignals(True)
        self.btn_move.blockSignals(True)
        
        self.btn_marker_time.setChecked(mode == 'TIME')
        self.btn_marker_y.setChecked(mode == 'Y')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_y.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)

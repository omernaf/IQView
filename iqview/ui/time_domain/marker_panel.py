from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QHBoxLayout, QButtonGroup
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
        
        # 2. Magnitude (Bottom-Left)
        self.btn_marker_mag = DoubleClickButton("〓")
        self.btn_marker_mag.setObjectName("mode_btn")
        self.btn_marker_mag.setToolTip("Magnitude Markers (Double-click to clear) [F/M]")
        self.btn_marker_mag.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_mag, 1, 0)
        
        # 3. Zoom
        self.btn_zoom = QPushButton("🔍")
        self.btn_zoom.setObjectName("mode_btn")
        self.btn_zoom.setToolTip("Zoom Mode [Hold Ctrl]")
        self.btn_zoom.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_zoom, 0, 1)
        
        # 4. Move
        self.btn_move = QPushButton("✥")
        self.btn_move.setObjectName("mode_btn")
        self.btn_move.setToolTip("Free Move Mode")
        self.btn_move.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_move, 1, 1)
        
        # 5. Home
        self.btn_home = QPushButton("🏠")
        self.btn_home.setObjectName("mode_btn")
        self.btn_home.setToolTip("Reset Zoom")
        self.mode_btn_layout.addWidget(self.btn_home, 0, 2)
        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        
        # Mutual Exclusion Group
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_time)
        self.mode_group.addButton(self.btn_marker_mag)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.setExclusive(True)

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_mag.clicked.connect(lambda: self.interactionModeChanged.emit('MAG'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        
        self.btn_marker_time.doubleClicked.connect(lambda: self.markerClearRequested.emit('TIME'))
        self.btn_marker_mag.doubleClicked.connect(lambda: self.markerClearRequested.emit('Y')) # Controller handles markers_y

        # Grid for marker data
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        self.main_layout.addLayout(self.grid)

        # Table Headers
        self.grid.addWidget(QLabel(""), 0, 0) 
        h1 = QLabel("Marker 1"); h1.setObjectName("header_label")
        h2 = QLabel("Marker 2"); h2.setObjectName("header_label")
        self.grid.addWidget(h1, 0, 1, Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(h2, 0, 2, Qt.AlignmentFlag.AlignCenter)

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
        self.btn_lock_delta.toggled.connect(lambda checked: self.controller.handle_lock_change('delta', checked))
        self.btn_lock_center.toggled.connect(lambda checked: self.controller.handle_lock_change('center', checked))
        
        self.btn_marker_time.setChecked(True)

    def set_y_label(self, label):
        # We handle this via update_headers now
        pass

    def update_headers(self, mode, y_axis_label="Magnitude"):
        self.row_v1_label.blockSignals(True)
        self.row_v2_label.blockSignals(True)
        
        if mode == 'TIME':
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

    def update_mode_ui(self, mode):
        self.btn_marker_time.blockSignals(True)
        self.btn_marker_mag.blockSignals(True)
        self.btn_zoom.blockSignals(True)
        self.btn_move.blockSignals(True)
        
        self.btn_marker_time.setChecked(mode == 'TIME')
        self.btn_marker_mag.setChecked(mode == 'MAG')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_mag.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)
        
        self.btn_lock_delta.setEnabled(mode in ['TIME', 'MAG'])
        self.btn_lock_center.setEnabled(mode in ['TIME', 'MAG'])

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
            self.btn_lock_delta.setStyleSheet(lock_style)
            self.btn_lock_center.setStyleSheet(lock_style)

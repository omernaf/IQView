from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QHBoxLayout, QButtonGroup, QStackedWidget, QWidget, QVBoxLayout, QScrollArea
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap
import importlib.resources
import os
from ..widgets import FormattedLineEdit, DoubleClickButton
from ..themes import get_palette

class FrequencyDomainMarkerPanel(QFrame):
    interactionModeChanged = pyqtSignal(str) # 'FREQ', 'MAG', 'ZOOM', 'MOVE'
    resetZoomRequested = pyqtSignal()
    markerClearRequested = pyqtSignal(str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.lock_states = {
            'FREQ': {'delta': False, 'center': False, 'm1': False, 'm2': False},
            'MAG':  {'delta': False, 'center': False, 'm1': False, 'm2': False}
        }
        self.last_marker_mode = 'FREQ'
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(140) 
        self.header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 6, 15, 6)
        self.main_layout.setSpacing(15)

        # --- Interaction Mode Buttons (Left Side) ---
        self.mode_btn_layout = QGridLayout()
        self.mode_btn_layout.setSpacing(6)
        self.main_layout.addLayout(self.mode_btn_layout)

        # 1. Frequency (Top-Left)
        self.btn_marker_freq = DoubleClickButton("")
        self.btn_marker_freq.setIcon(self._get_icon("vertical_markers"))
        self.btn_marker_freq.setIconSize(QSize(32, 32))
        self.btn_marker_freq.setObjectName("mode_btn")
        self.btn_marker_freq.setToolTip("Frequency Markers (Double-click to clear) [F]")
        self.btn_marker_freq.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq, 0, 0)
        
        # 1b. Endless Frequency
        self.btn_marker_freq_endless = DoubleClickButton("")
        self.btn_marker_freq_endless.setIcon(self._get_icon("endless_vertical_markers"))
        self.btn_marker_freq_endless.setIconSize(QSize(32, 32))
        self.btn_marker_freq_endless.setObjectName("mode_btn")
        self.btn_marker_freq_endless.setToolTip("Endless Frequency Markers")
        self.btn_marker_freq_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq_endless, 0, 1)

        # 3. Zoom
        self.btn_zoom = QPushButton("")
        self.btn_zoom.setIcon(self._get_icon("zoom_mode"))
        self.btn_zoom.setIconSize(QSize(32, 32))
        self.btn_zoom.setObjectName("mode_btn")
        self.btn_zoom.setToolTip("Zoom Mode (Rubberband) [Z]")
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
        self.btn_marker_mag.setToolTip("Magnitude Markers (Double-click to clear) [M]")
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
        self.btn_move.setToolTip("Free Move Mode (Pan) [P]")
        self.btn_move.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_move, 1, 2)
        
        # 6. Stats
        self.btn_stats = DoubleClickButton("")
        self.btn_stats.setIcon(self._get_icon("region_statistics"))
        self.btn_stats.setIconSize(QSize(32, 32))
        self.btn_stats.setObjectName("mode_btn")
        self.btn_stats.setToolTip("Region Statistics (Double-click to clear) [S]")
        self.btn_stats.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_stats, 1, 3)
        self.btn_home.clicked.connect(self.resetZoomRequested.emit)
        
        # Mutual Exclusion Group
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_marker_freq)
        self.mode_group.addButton(self.btn_marker_freq_endless)
        self.mode_group.addButton(self.btn_marker_mag)
        self.mode_group.addButton(self.btn_marker_mag_endless)
        self.mode_group.addButton(self.btn_zoom)
        self.mode_group.addButton(self.btn_move)
        self.mode_group.addButton(self.btn_stats)
        self.mode_group.setExclusive(True)

        # Connections
        self.btn_marker_freq.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ'))
        self.btn_marker_freq_endless.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ_ENDLESS'))
        self.btn_marker_mag.clicked.connect(lambda: self.interactionModeChanged.emit('MAG'))
        self.btn_marker_mag_endless.clicked.connect(lambda: self.interactionModeChanged.emit('MAG_ENDLESS'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        self.btn_stats.clicked.connect(lambda: self.interactionModeChanged.emit('STATS'))
        
        self.btn_marker_freq.doubleClicked.connect(lambda: self.markerClearRequested.emit('FREQ'))
        self.btn_marker_freq_endless.doubleClicked.connect(lambda: self.markerClearRequested.emit('FREQ_ENDLESS'))
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

        self.btn_lock_delta = QPushButton("Delta (Δ)")
        self.btn_lock_delta.setFont(self.header_font)
        self.btn_lock_delta.setCheckable(True)
        self.grid.addWidget(self.btn_lock_delta, 0, 3)

        self.btn_lock_center = QPushButton("Center")
        self.btn_lock_center.setFont(self.header_font)
        self.btn_lock_center.setCheckable(True)
        self.grid.addWidget(self.btn_lock_center, 0, 4)

        # Side labels (Row names)
        self.row_v1_label = QLabel("Frequency (Hz)")
        self.row_v2_label = QLabel("Index")
        self.row_v1_label.setObjectName("header_label")
        self.row_v2_label.setObjectName("header_label")
        self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row_v2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Edit Widgets (3 Rows)
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
        self.delta_v2 = FormattedLineEdit(); self.delta_v2.setFixedWidth(130); self.delta_v2.setObjectName("delta_v2"); self.delta_v2.setAlignment(Qt.AlignmentFlag.AlignCenter); self.delta_v2.setReadOnly(True)
        
        self.center_v1 = FormattedLineEdit(); self.center_v1.setFixedWidth(130); self.center_v1.setObjectName("center_v1"); self.center_v1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_v2 = FormattedLineEdit(); self.center_v2.setFixedWidth(130); self.center_v2.setObjectName("center_v2"); self.center_v2.setAlignment(Qt.AlignmentFlag.AlignCenter); self.center_v2.setReadOnly(True)
        
        for w in [self.delta_v1, self.center_v1]:
            w.returnPressed.connect(self.controller.marker_edit_finished)
            
        self.grid.addWidget(self.delta_v1, 1, 3); self.grid.addWidget(self.delta_v2, 2, 3)
        self.grid.addWidget(self.center_v1, 1, 4); self.grid.addWidget(self.center_v2, 2, 4)
        
        # Connect locks
        self.btn_lock_m1.toggled.connect(self.on_lock_m1_toggled)
        self.btn_lock_m2.toggled.connect(self.on_lock_m2_toggled)
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)
        
        self.btn_marker_freq.setChecked(True)

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

        # Page 3: Statistics Layout
        self.stats_widget = QWidget()
        self.stacked.addWidget(self.stats_widget)
        self.stats_main_layout = QVBoxLayout(self.stats_widget)
        self.stats_main_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_main_layout.setSpacing(4)

        # --- Statistics Tab Bar ---
        self.stats_tab_layout = QHBoxLayout()
        self.stats_tab_layout.setSpacing(10)
        self.stats_main_layout.addLayout(self.stats_tab_layout)

        self.btn_stats_def = QPushButton("Definition")
        self.btn_stats_res = QPushButton("Results")
        for btn in [self.btn_stats_def, self.btn_stats_res]:
            btn.setCheckable(True)
            btn.setObjectName("stats_tab_btn")
            btn.setFixedHeight(22)
            self.stats_tab_layout.addWidget(btn)
        
        self.stats_tab_group = QButtonGroup(self)
        self.stats_tab_group.addButton(self.btn_stats_def)
        self.stats_tab_group.addButton(self.btn_stats_res)
        self.stats_tab_group.setExclusive(True)
        self.btn_stats_res.setChecked(True)
        self.stats_tab_layout.addStretch()

        # --- Sub-Stacked Widget ---
        self.stats_sub_stack = QStackedWidget()
        self.stats_main_layout.addWidget(self.stats_sub_stack)

        # Sub-Page 1: Region Definition
        self.st_def_widget = QWidget()
        self.stats_sub_stack.addWidget(self.st_def_widget)
        self.st_layout = QGridLayout(self.st_def_widget)
        self.st_layout.setContentsMargins(0, 0, 0, 0)
        self.st_layout.setHorizontalSpacing(10)
        self.st_layout.setVerticalSpacing(4)

        # Region Definition Content
        self.st_layout.addWidget(QLabel(""), 0, 0) 

        self.st_widgets = []
        for i in range(2):
            v1 = FormattedLineEdit(); v1.setFixedWidth(110); v1.setAlignment(Qt.AlignmentFlag.AlignCenter); v1.setObjectName(f"st_m{i}_v1")
            v2 = FormattedLineEdit(); v2.setFixedWidth(110); v2.setAlignment(Qt.AlignmentFlag.AlignCenter); v2.setObjectName(f"st_m{i}_v2")
            for w in [v1, v2]: w.returnPressed.connect(self.controller.marker_edit_finished)
            self.st_layout.addWidget(v1, 1, i + 1)
            self.st_layout.addWidget(v2, 2, i + 1)
            self.st_widgets.append({'v1': v1, 'v2': v2})

        self.st_delta_v1 = FormattedLineEdit(); self.st_delta_v1.setFixedWidth(110); self.st_delta_v1.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_delta_v1.setObjectName("st_delta_v1")
        self.st_delta_v2 = FormattedLineEdit(); self.st_delta_v2.setFixedWidth(110); self.st_delta_v2.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_delta_v2.setObjectName("st_delta_v2"); self.st_delta_v2.setReadOnly(True)
        
        self.st_center_v1 = FormattedLineEdit(); self.st_center_v1.setFixedWidth(110); self.st_center_v1.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_center_v1.setObjectName("st_center_v1")
        self.st_center_v2 = FormattedLineEdit(); self.st_center_v2.setFixedWidth(110); self.st_center_v2.setAlignment(Qt.AlignmentFlag.AlignCenter); self.st_center_v2.setObjectName("st_center_v2"); self.st_center_v2.setReadOnly(True)

        for w in [self.st_delta_v1, self.st_center_v1]: w.returnPressed.connect(self.controller.marker_edit_finished)
        self.st_layout.addWidget(self.st_delta_v1, 1, 3); self.st_layout.addWidget(self.st_delta_v2, 2, 3)
        self.st_layout.addWidget(self.st_center_v1, 1, 4); self.st_layout.addWidget(self.st_center_v2, 2, 4)

        self.st_row_v1_lbl = QLabel("Region (Hz)"); self.st_row_v1_lbl.setObjectName("header_label")
        self.st_row_v2_lbl = QLabel("Index"); self.st_row_v2_lbl.setObjectName("header_label")
        self.st_layout.addWidget(self.st_row_v1_lbl, 1, 0, Qt.AlignmentFlag.AlignRight)
        self.st_layout.addWidget(self.st_row_v2_lbl, 2, 0, Qt.AlignmentFlag.AlignRight)

        # Sub-Page 2: Measurement Results
        self.st_res_widget = QWidget()
        self.stats_sub_stack.addWidget(self.st_res_widget)
        self.res_layout = QGridLayout(self.st_res_widget)
        self.res_layout.setContentsMargins(0, 0, 0, 0)
        self.res_layout.setHorizontalSpacing(10)
        self.res_layout.setVerticalSpacing(4)

        res_headers = ["Maximum", "Minimum", "Mean", "Median", "Integrated"]
        for i, h in enumerate(res_headers):
            lbl = QLabel(h); lbl.setFont(self.header_font); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #888; text-transform: uppercase; font-size: 10px;")
            self.res_layout.addWidget(lbl, 0, i + 1)

        lbl_val = QLabel("Value"); lbl_val.setObjectName("header_label")
        lbl_freq = QLabel("Freq (Hz)"); lbl_freq.setObjectName("header_label")
        lbl_idx = QLabel("Index"); lbl_idx.setObjectName("header_label")
        self.res_layout.addWidget(lbl_val, 1, 0, Qt.AlignmentFlag.AlignRight)
        self.res_layout.addWidget(lbl_freq, 2, 0, Qt.AlignmentFlag.AlignRight)
        self.res_layout.addWidget(lbl_idx, 3, 0, Qt.AlignmentFlag.AlignRight)

        self.stats_max_val = FormattedLineEdit(); self.stats_max_val.setFixedWidth(110); self.stats_max_val.setReadOnly(True); self.stats_max_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_min_val = FormattedLineEdit(); self.stats_min_val.setFixedWidth(110); self.stats_min_val.setReadOnly(True); self.stats_min_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_mean_val = FormattedLineEdit(); self.stats_mean_val.setFixedWidth(110); self.stats_mean_val.setReadOnly(True); self.stats_mean_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_median_val = FormattedLineEdit(); self.stats_median_val.setFixedWidth(110); self.stats_median_val.setReadOnly(True); self.stats_median_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_total_power = FormattedLineEdit(); self.stats_total_power.setFixedWidth(110); self.stats_total_power.setReadOnly(True); self.stats_total_power.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_max_freq = FormattedLineEdit(); self.stats_max_freq.setFixedWidth(110); self.stats_max_freq.setReadOnly(True); self.stats_max_freq.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_min_freq = FormattedLineEdit(); self.stats_min_freq.setFixedWidth(110); self.stats_min_freq.setReadOnly(True); self.stats_min_freq.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_max_idx = FormattedLineEdit(); self.stats_max_idx.setFixedWidth(110); self.stats_max_idx.setReadOnly(True); self.stats_max_idx.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_min_idx = FormattedLineEdit(); self.stats_min_idx.setFixedWidth(110); self.stats_min_idx.setReadOnly(True); self.stats_min_idx.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.res_layout.addWidget(self.stats_max_val, 1, 1); self.res_layout.addWidget(self.stats_min_val, 1, 2)
        self.res_layout.addWidget(self.stats_mean_val, 1, 3); self.res_layout.addWidget(self.stats_median_val, 1, 4)
        self.res_layout.addWidget(self.stats_total_power, 1, 5)
        self.res_layout.addWidget(self.stats_max_freq, 2, 1); self.res_layout.addWidget(self.stats_min_freq, 2, 2)
        self.res_layout.addWidget(self.stats_max_idx, 3, 1); self.res_layout.addWidget(self.stats_min_idx, 3, 2)

        lbl_90th = QLabel("90th %"); lbl_10th = QLabel("10th %"); lbl_diff = QLabel("90-10 Diff")
        for lbl in [lbl_90th, lbl_10th, lbl_diff]: lbl.setObjectName("header_label")
        self.res_layout.addWidget(lbl_90th, 1, 6, Qt.AlignmentFlag.AlignRight)
        self.res_layout.addWidget(lbl_10th, 2, 6, Qt.AlignmentFlag.AlignRight)
        self.res_layout.addWidget(lbl_diff, 3, 6, Qt.AlignmentFlag.AlignRight)

        self.stats_90th_val = FormattedLineEdit(); self.stats_90th_val.setFixedWidth(110); self.stats_90th_val.setReadOnly(True); self.stats_90th_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_10th_val = FormattedLineEdit(); self.stats_10th_val.setFixedWidth(110); self.stats_10th_val.setReadOnly(True); self.stats_10th_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_diff_val = FormattedLineEdit(); self.stats_diff_val.setFixedWidth(110); self.stats_diff_val.setReadOnly(True); self.stats_diff_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.res_layout.addWidget(self.stats_90th_val, 1, 7)
        self.res_layout.addWidget(self.stats_10th_val, 2, 7)
        self.res_layout.addWidget(self.stats_diff_val, 3, 7)

        self.stats_sub_stack.setCurrentIndex(1) # Now it's safe to set index 1

        # Connect internal tab switching
        self.btn_stats_def.clicked.connect(lambda: self.stats_sub_stack.setCurrentIndex(0))
        self.btn_stats_res.clicked.connect(lambda: self.stats_sub_stack.setCurrentIndex(1))

        # Apply theme (must be done AFTER buttons are initialized)
        self.refresh_theme()

    def _get_icon(self, name, theme="Light"):
        """Helper to load icons from resources/assets."""
        suffix = "_dark" if theme == "Dark" else ""
        icon_name = f"{name}{suffix}"
        try:
            from importlib.resources import files
            icon_resource = files("iqview.resources.assets").joinpath(f"{icon_name}.png")
            with icon_resource.open("rb") as f:
                pixmap = QPixmap()
                pixmap.loadFromData(f.read())
                return QIcon(pixmap)
        except Exception:
            # Fallback for local dev
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            local_path = os.path.join(base_path, "iqview", "resources", "assets", f"{icon_name}.png")
            if not os.path.exists(local_path) and suffix:
                local_path = os.path.join(base_path, "iqview", "resources", "assets", f"{name}.png")
            return QIcon(local_path)

    def update_headers(self, mode, y_axis_label="Magnitude"):
        self.row_v1_label.blockSignals(True)
        self.row_v2_label.blockSignals(True)
        
        if mode in ['FREQ', 'MAG', 'FREQ_ENDLESS', 'MAG_ENDLESS', 'STATS']:
            self.last_marker_mode = mode
            
        display_mode = self.last_marker_mode if mode in ['ZOOM', 'MOVE'] else mode
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

        if display_mode in ['FREQ', 'FREQ_ENDLESS']:
            self.row_v1_label.setText("Frequency (Hz)")
            self.row_v2_label.setText("Index")
            self.row_v1_label.show()
            self.row_v2_label.show()
            for i in range(2): 
                self.m_widgets[i]['v2'].show()
            self.delta_v2.show()
            self.center_v2.show()
        else: # MAG
            self.row_v1_label.setText(y_axis_label)
            self.row_v2_label.setText("")
            self.row_v2_label.hide()
            for i in range(2): 
                self.m_widgets[i]['v2'].hide()
            self.delta_v2.hide()
            self.center_v2.hide()
            
        self.row_v1_label.blockSignals(False)
        self.row_v2_label.blockSignals(False)

        base_mode = display_mode
        if display_mode in ['FREQ_ENDLESS', 'MAG_ENDLESS']: 
             base_mode = 'FREQ' if 'FREQ' in display_mode else 'MAG'
        
        if base_mode in self.lock_states:
            for key, btn in [
                ('m1',     self.btn_lock_m1),
                ('m2',     self.btn_lock_m2),
                ('delta',  self.btn_lock_delta),
                ('center', self.btn_lock_center),
            ]:
                locked = self.lock_states[base_mode].get(key, False)
                if btn:
                    btn.blockSignals(True)
                    btn.setChecked(locked)
                    btn.setEnabled('ENDLESS' not in display_mode)
                    btn.blockSignals(False)

    def update_mode_ui(self, mode):
        self.btn_marker_freq.blockSignals(True)
        self.btn_marker_freq_endless.blockSignals(True)
        self.btn_marker_mag.blockSignals(True)
        self.btn_marker_mag_endless.blockSignals(True)
        self.btn_zoom.blockSignals(True)
        self.btn_move.blockSignals(True)
        self.btn_stats.blockSignals(True)
        
        self.btn_marker_freq.setChecked(mode == 'FREQ')
        self.btn_marker_freq_endless.setChecked(mode == 'FREQ_ENDLESS')
        self.btn_marker_mag.setChecked(mode == 'MAG')
        self.btn_marker_mag_endless.setChecked(mode == 'MAG_ENDLESS')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        self.btn_stats.setChecked(mode == 'STATS')
        
        self.btn_marker_freq.blockSignals(False)
        self.btn_marker_freq_endless.blockSignals(False)
        self.btn_marker_mag.blockSignals(False)
        self.btn_marker_mag_endless.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)
        self.btn_stats.blockSignals(False)
        
        self.btn_lock_delta.setEnabled(mode in ['FREQ', 'MAG'])
        self.btn_lock_center.setEnabled(mode in ['FREQ', 'MAG'])

    def update_endless_list(self, markers, mode):
        is_freq = 'FREQ' in mode
        unit_main = "Hz" if is_freq else self.controller.y_label_text
        unit_sub = "Bin" if is_freq else ""
        
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
            self.refresh_theme() 

        for lbl in self._header_widget.findChildren(QLabel, "header_label"):
            if lbl.property("role") == "pos_header":
                lbl.setText(f"Pos ({unit_main})")
            elif lbl.property("role") == "sub_header":
                lbl.setText(unit_sub)
        
        if not is_freq:
            for lbl in self._header_widget.findChildren(QLabel, "header_label"):
                if lbl.property("role") == "sub_header": lbl.hide()
        else:
            for lbl in self._header_widget.findChildren(QLabel, "header_label"):
                if lbl.property("role") == "sub_header": lbl.show()

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

        for i, m in enumerate(markers):
            row_data = self._endless_rows[i]
            val = m.value()
            prec = 3 if is_freq else 6
            
            row_data['lbl_id'].setText(f"M{i+1}")
            
            row_data['edit_pos'].blockSignals(True)
            row_data['edit_pos'].setObjectName(f"em_{i}_hz")
            row_data['edit_pos'].setText(f"{val:.{prec}f}")
            row_data['edit_pos'].blockSignals(False)
            
            if is_freq:
                sub_val = self.controller.freq_to_index(val)
                row_data['edit_sub'].show()
                row_data['edit_sub'].blockSignals(True)
                row_data['edit_sub'].setObjectName(f"em_{i}_bin")
                row_data['edit_sub'].setText(f"{sub_val}")
                row_data['edit_sub'].blockSignals(False)
            else:
                row_data['edit_sub'].hide()
            
            try: row_data['btn_del'].clicked.disconnect()
            except: pass
            row_data['btn_del'].clicked.connect(lambda _, m=m: self.controller.remove_marker_item(m, mode))

    def _clear_marker_locks(self, mode, keep=None):
        base_mode = mode
        if base_mode in ['FREQ_ENDLESS', 'MAG_ENDLESS']: 
             base_mode = 'FREQ' if 'FREQ' in base_mode else 'MAG'
             
        if base_mode not in self.lock_states: return

        for key, btn in [
            ('m1',     self.btn_lock_m1),
            ('m2',     self.btn_lock_m2),
            ('delta',  self.btn_lock_delta),
            ('center', self.btn_lock_center),
        ]:
            if key == keep: continue
            if btn:
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)
            self.lock_states[base_mode][key] = False

    def set_locks_enabled(self, m1_placed, m2_placed):
        self.btn_lock_m1.setEnabled(m1_placed)
        self.btn_lock_m2.setEnabled(m2_placed)
        
        can_pair_lock = m1_placed and m2_placed
        self.btn_lock_delta.setEnabled(can_pair_lock)
        self.btn_lock_center.setEnabled(can_pair_lock)
        
        if not m1_placed and self.btn_lock_m1.isChecked(): self.on_lock_m1_toggled(False)
        if not m2_placed and self.btn_lock_m2.isChecked(): self.on_lock_m2_toggled(False)
        if not can_pair_lock:
            if self.btn_lock_delta.isChecked(): self.on_lock_delta_toggled(False)
            if self.btn_lock_center.isChecked(): self.on_lock_center_toggled(False)

    def on_lock_delta_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'FREQ' if 'FREQ' in mode else 'MAG'
        if base_mode not in self.lock_states: return
        self.lock_states[base_mode]['delta'] = checked
        if checked: self._clear_marker_locks(mode, keep='delta')
        self.controller.handle_lock_change('delta', checked)

    def on_lock_center_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'FREQ' if 'FREQ' in mode else 'MAG'
        if base_mode not in self.lock_states: return
        self.lock_states[base_mode]['center'] = checked
        if checked: self._clear_marker_locks(mode, keep='center')
        self.controller.handle_lock_change('center', checked)

    def on_lock_m1_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'FREQ' if 'FREQ' in mode else 'MAG'
        if base_mode not in self.lock_states: return
        self.lock_states[base_mode]['m1'] = checked
        if checked: self._clear_marker_locks(mode, keep='m1')
        self.controller.handle_lock_change('m1', checked)

    def on_lock_m2_toggled(self, checked):
        mode = self.controller.interaction_mode
        base_mode = 'FREQ' if 'FREQ' in mode else 'MAG'
        if base_mode not in self.lock_states: return
        self.lock_states[base_mode]['m2'] = checked
        if checked: self._clear_marker_locks(mode, keep='m2')
        self.controller.handle_lock_change('m2', checked)

    def flip_m_lock(self, mode):
        base_mode = mode
        if base_mode in ['FREQ_ENDLESS', 'MAG_ENDLESS']: 
             base_mode = 'FREQ' if 'FREQ' in base_mode else 'MAG'

        m1 = self.lock_states[base_mode]['m1']
        m2 = self.lock_states[base_mode]['m2']
        if not m1 and not m2: return
        
        self.lock_states[base_mode]['m1'] = m2
        self.lock_states[base_mode]['m2'] = m1
        
        # Update buttons
        self.btn_lock_m1.blockSignals(True); self.btn_lock_m2.blockSignals(True)
        self.btn_lock_m1.setChecked(m2);     self.btn_lock_m2.setChecked(m1)
        self.btn_lock_m1.blockSignals(False); self.btn_lock_m2.blockSignals(False)

    def refresh_theme(self):
        theme = self.controller.parent_window.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        
        # Update Icons based on theme
        self.btn_marker_freq.setIcon(self._get_icon("vertical_markers", theme))
        self.btn_marker_freq_endless.setIcon(self._get_icon("endless_vertical_markers", theme))
        self.btn_marker_mag.setIcon(self._get_icon("horizontal_markers", theme))
        self.btn_marker_mag_endless.setIcon(self._get_icon("endless_horizontal_markers", theme))
        self.btn_zoom.setIcon(self._get_icon("zoom_mode", theme))
        self.btn_move.setIcon(self._get_icon("free_move_mode", theme))
        self.btn_stats.setIcon(self._get_icon("region_statistics", theme))
        self.btn_home.setIcon(self._get_icon("reset_zoom", theme))
        
        self.setStyleSheet(f"""
            FrequencyDomainMarkerPanel {{ 
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
            lock_btns = [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]
            for btn in lock_btns:
                if btn: btn.setStyleSheet(lock_style)

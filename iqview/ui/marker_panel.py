from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QCheckBox, QPushButton, QHBoxLayout, QStackedWidget, QWidget, QScrollArea, QVBoxLayout, QButtonGroup
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap
import importlib.resources
import os
from .widgets import FormattedLineEdit, DoubleClickButton
from .themes import get_palette

class MarkerPanel(QFrame):
    interactionModeChanged = pyqtSignal(str) # 'TIME', 'FREQ', 'ZOOM', 'OVERLAY', …
    resetZoomRequested = pyqtSignal()
    markerClearRequested = pyqtSignal(str)

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(140)
        self.header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self.mono_font = QFont("Consolas", 10)
        
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 8, 15, 8)
        self.main_layout.setSpacing(15)

        # State
        self.current_mode = 'TIME'
        self.last_marker_mode = 'TIME'
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
        self.btn_marker_time = DoubleClickButton("")
        self.btn_marker_time.setIcon(self._get_icon("vertical_markers"))
        self.btn_marker_time.setIconSize(QSize(32, 32))
        self.btn_marker_time.setObjectName("mode_btn")
        self.btn_marker_time.setToolTip("Time Markers (Double-click to clear)")
        self.btn_marker_time.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time, 0, 0)
        
        # 1b. Time Endless
        self.btn_marker_time_endless = DoubleClickButton("")
        self.btn_marker_time_endless.setIcon(self._get_icon("endless_vertical_markers"))
        self.btn_marker_time_endless.setIconSize(QSize(32, 32))
        self.btn_marker_time_endless.setObjectName("mode_btn")
        self.btn_marker_time_endless.setToolTip("Endless Time Markers")
        self.btn_marker_time_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_time_endless, 0, 1)

        # 2. Zoom
        self.btn_zoom = QPushButton("")
        self.btn_zoom.setIcon(self._get_icon("zoom_mode"))
        self.btn_zoom.setIconSize(QSize(32, 32))
        self.btn_zoom.setObjectName("mode_btn")
        self.btn_zoom.setToolTip("Zoom Mode (Rubberband)")
        self.btn_zoom.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_zoom, 0, 2)
        
        # 3. Home
        self.btn_home = QPushButton("")
        self.btn_home.setIcon(self._get_icon("reset_zoom"))
        self.btn_home.setIconSize(QSize(32, 32))
        self.btn_home.setObjectName("mode_btn")
        self.btn_home.setToolTip("Reset Zoom (Home)")
        self.mode_btn_layout.addWidget(self.btn_home, 0, 3)

        # --- Row 2 ---
        
        # 4. Freq
        self.btn_marker_freq = DoubleClickButton("")
        self.btn_marker_freq.setIcon(self._get_icon("horizontal_markers"))
        self.btn_marker_freq.setIconSize(QSize(32, 32))
        self.btn_marker_freq.setObjectName("mode_btn")
        self.btn_marker_freq.setToolTip("Frequency Markers (Double-click to clear)")
        self.btn_marker_freq.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq, 1, 0)
        
        # 4b. Freq Endless
        self.btn_marker_freq_endless = DoubleClickButton("")
        self.btn_marker_freq_endless.setIcon(self._get_icon("endless_horizontal_markers"))
        self.btn_marker_freq_endless.setIconSize(QSize(32, 32))
        self.btn_marker_freq_endless.setObjectName("mode_btn")
        self.btn_marker_freq_endless.setToolTip("Endless Frequency Markers")
        self.btn_marker_freq_endless.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_marker_freq_endless, 1, 1)

        # 5. Move
        self.btn_move = QPushButton("")
        self.btn_move.setIcon(self._get_icon("free_move_mode"))
        self.btn_move.setIconSize(QSize(32, 32))
        self.btn_move.setObjectName("mode_btn")
        self.btn_move.setToolTip("Free Move Mode (Pan)")
        self.btn_move.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_move, 1, 2)
        
        # 6. BPF Mode
        self.btn_bpf = DoubleClickButton("")
        self.btn_bpf.setIcon(self._get_icon("bpf_selection_mode"))
        self.btn_bpf.setIconSize(QSize(32, 32))
        self.btn_bpf.setObjectName("mode_btn")
        self.btn_bpf.setToolTip("BPF Selection Mode (Double-click to clear)")
        self.btn_bpf.setCheckable(True)
        self.mode_btn_layout.addWidget(self.btn_bpf, 1, 3)

        # 7. Overlay Mode
        self.btn_overlay = QPushButton("⬛")
        self.btn_overlay.setObjectName("mode_btn")
        self.btn_overlay.setToolTip("Overlay Mode — click or drag to place a shape")
        self.btn_overlay.setCheckable(True)
        self.btn_overlay.setFont(QFont("Segoe UI", 13))
        self.mode_btn_layout.addWidget(self.btn_overlay, 0, 4)

        # Re-assign BPF to row 1, col 3 (push it down) — already done above

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
        self.mode_group.addButton(self.btn_overlay)
        self.mode_group.setExclusive(True)

        # Connections
        self.btn_marker_time.clicked.connect(lambda: self.interactionModeChanged.emit('TIME'))
        self.btn_marker_freq.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ'))
        self.btn_marker_time_endless.clicked.connect(lambda: self.interactionModeChanged.emit('TIME_ENDLESS'))
        self.btn_marker_freq_endless.clicked.connect(lambda: self.interactionModeChanged.emit('FREQ_ENDLESS'))
        self.btn_zoom.clicked.connect(lambda: self.interactionModeChanged.emit('ZOOM'))
        self.btn_move.clicked.connect(lambda: self.interactionModeChanged.emit('MOVE'))
        self.btn_bpf.clicked.connect(lambda: self.interactionModeChanged.emit('FILTER'))
        self.btn_overlay.clicked.connect(lambda: self.interactionModeChanged.emit('OVERLAY'))
        
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
        self.row1_label = QLabel("Samples")
        self.row2_label = QLabel("Time (sec)")
        self.row3_label = QLabel("1/T (Hz)")
        self.row1_label.setObjectName("header_label")
        self.row2_label.setObjectName("header_label")
        self.row3_label.setObjectName("header_label")
        self.grid.addWidget(self.row1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.row3_label, 3, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Edit Widgets
        self.widgets = []
        for i in range(2):
            sam_edit = FormattedLineEdit(); sam_edit.setFixedWidth(130); sam_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_edit = FormattedLineEdit(); sec_edit.setFixedWidth(130); sec_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inv_edit = FormattedLineEdit(); inv_edit.setFixedWidth(130); inv_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            sam_edit.setObjectName(f"m{i}_sam")
            sec_edit.setObjectName(f"m{i}_sec")
            inv_edit.setObjectName(f"m{i}_inv")
            
            sam_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            sec_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            inv_edit.setReadOnly(True)  
            
            self.grid.addWidget(sam_edit, 1, i + 1)
            self.grid.addWidget(sec_edit, 2, i + 1)
            self.grid.addWidget(inv_edit, 3, i + 1)
            self.widgets.append({'sam': sam_edit, 'sec': sec_edit, 'inv': inv_edit})

        # Delta/Center Edits
        self.delta_sam = FormattedLineEdit(); self.delta_sam.setFixedWidth(130); self.delta_sam.setObjectName("delta_sam"); self.delta_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sec = FormattedLineEdit(); self.delta_sec.setFixedWidth(130); self.delta_sec.setObjectName("delta_sec"); self.delta_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_inv = FormattedLineEdit(); self.delta_inv.setFixedWidth(130); self.delta_inv.setObjectName("delta_inv"); self.delta_inv.setAlignment(Qt.AlignmentFlag.AlignCenter); self.delta_inv.setReadOnly(True)
        
        self.center_sam = FormattedLineEdit(); self.center_sam.setFixedWidth(130); self.center_sam.setObjectName("center_sam"); self.center_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sec = FormattedLineEdit(); self.center_sec.setFixedWidth(130); self.center_sec.setObjectName("center_sec"); self.center_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_inv = FormattedLineEdit(); self.center_inv.setFixedWidth(130); self.center_inv.setObjectName("center_inv"); self.center_inv.setAlignment(Qt.AlignmentFlag.AlignCenter); self.center_inv.setReadOnly(True)
        
        for w in [self.delta_sam, self.delta_sec, self.center_sam, self.center_sec]:
            w.returnPressed.connect(self.parent_window.marker_edit_finished)
            
        self.grid.addWidget(self.delta_sam, 1, 3); self.grid.addWidget(self.delta_sec, 2, 3); self.grid.addWidget(self.delta_inv, 3, 3)
        self.grid.addWidget(self.center_sam, 1, 4); self.grid.addWidget(self.center_sec, 2, 4); self.grid.addWidget(self.center_inv, 3, 4)

        # Connect locks to parent
        self.btn_lock_m1.toggled.connect(self.on_lock_m1_toggled)
        self.btn_lock_m2.toggled.connect(self.on_lock_m2_toggled)
        self.btn_lock_delta.toggled.connect(self.on_lock_delta_toggled)
        self.btn_lock_center.toggled.connect(self.on_lock_center_toggled)

        # Filter Activation Checkboxes (BPF / BSF)
        self.filter_container = QWidget()
        self.filter_layout = QVBoxLayout(self.filter_container)
        self.filter_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_layout.setSpacing(2)
        
        self.cb_bpf = QCheckBox("BPF")
        self.cb_bsf = QCheckBox("BSF")
        self.cb_bpf.setToolTip("Enable Band-Pass Filter")
        self.cb_bsf.setToolTip("Enable Band-Stop Filter")
        
        for cb in [self.cb_bpf, self.cb_bsf]:
            cb.setEnabled(False)
            cb.clicked.connect(self.on_filter_clicked)
            self.filter_layout.addWidget(cb)
            
        self.filter_container.setFixedWidth(80)
        self.filter_container.setVisible(False)
        self.grid.addWidget(self.filter_container, 1, 5, 2, 1)
        
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
            # Fallback for local dev if package structure isn't perfect
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            local_path = os.path.join(base_path, "iqview", "resources", "assets", f"{icon_name}.png")
            if not os.path.exists(local_path) and suffix:
                # Fallback to light version if dark doesn't exist
                local_path = os.path.join(base_path, "iqview", "resources", "assets", f"{name}.png")
            return QIcon(local_path)

    def _clear_marker_locks(self, mode=None, keep=None):
        """Uncheck all marker-position locks except the one named in `keep`."""
        target_mode = mode if mode else self.current_mode
        if target_mode not in self.lock_states: return

        for key, btn in [
            ('m1',     self.btn_lock_m1),
            ('m2',     self.btn_lock_m2),
            ('delta',  self.btn_lock_delta),
            ('center', self.btn_lock_center),
        ]:
            if key == keep:
                continue
            btn.blockSignals(True)
            btn.setChecked(False)
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
        self.parent_window.handle_lock_change('delta', checked)

    def on_lock_center_toggled(self, checked):
        self.lock_states[self.current_mode]['center'] = checked
        if checked:
            self._clear_marker_locks(keep='center')
        self.parent_window.handle_lock_change('center', checked)

    def on_lock_m1_toggled(self, checked):
        self.lock_states[self.current_mode]['m1'] = checked
        if checked:
            self._clear_marker_locks(keep='m1')
        self.parent_window.handle_lock_change('m1', checked)

    def on_lock_m2_toggled(self, checked):
        self.lock_states[self.current_mode]['m2'] = checked
        if checked:
            self._clear_marker_locks(keep='m2')
        self.parent_window.handle_lock_change('m2', checked)

    def on_filter_clicked(self):
        """Handle BPF/BSF exclusivity and notify parent."""
        sender = self.sender()
        if sender == self.cb_bpf and self.cb_bpf.isChecked():
            self.cb_bsf.setChecked(False)
        elif sender == self.cb_bsf and self.cb_bsf.isChecked():
            self.cb_bpf.setChecked(False)
            
        # Determine mode
        mode = None
        if self.cb_bpf.isChecked(): mode = 'bpf'
        elif self.cb_bsf.isChecked(): mode = 'bsf'
        
        self.parent_window.on_filter_changed(mode)

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
        self.btn_overlay.blockSignals(True)
        
        self.btn_marker_time.setChecked(mode == 'TIME')
        self.btn_marker_freq.setChecked(mode == 'FREQ')
        self.btn_marker_time_endless.setChecked(mode == 'TIME_ENDLESS')
        self.btn_marker_freq_endless.setChecked(mode == 'FREQ_ENDLESS')
        self.btn_zoom.setChecked(mode == 'ZOOM')
        self.btn_move.setChecked(mode == 'MOVE')
        self.btn_bpf.setChecked(mode == 'FILTER')
        self.btn_overlay.setChecked(mode == 'OVERLAY')
        
        self.btn_marker_time.blockSignals(False)
        self.btn_marker_freq.blockSignals(False)
        self.btn_marker_time_endless.blockSignals(False)
        self.btn_marker_freq_endless.blockSignals(False)
        self.btn_zoom.blockSignals(False)
        self.btn_move.blockSignals(False)
        self.btn_bpf.blockSignals(False)
        self.btn_overlay.blockSignals(False)

        self.current_mode = mode
        
        # Track the last valid marker mode to display in the table
        if mode in ['TIME', 'FREQ', 'TIME_ENDLESS', 'FREQ_ENDLESS', 'OVERLAY']:
            self.last_marker_mode = mode
            
        display_mode = self.last_marker_mode if mode in ['ZOOM', 'MOVE'] else mode

        if display_mode in ['TIME_ENDLESS', 'FREQ_ENDLESS', 'OVERLAY']:
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)

        if display_mode in ['FREQ', 'FREQ_ENDLESS', 'FILTER']:
            self.row1_label.setText("Bin")
            self.row2_label.setText("Freq (Hz)")
            self.row1_label.show()
            self.row2_label.show()
            
            # Move Frequency widgets back to Row 2
            self.grid.addWidget(self.row1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.widgets[i]['sam'], 1, i + 1)
                self.grid.addWidget(self.widgets[i]['sec'], 2, i + 1)
                self.widgets[i]['sam'].show()
                self.widgets[i]['sec'].show()
            self.grid.addWidget(self.delta_sam, 1, 3); self.delta_sam.show()
            self.grid.addWidget(self.delta_sec, 2, 3); self.delta_sec.show()
            self.grid.addWidget(self.center_sam, 1, 4); self.center_sam.show()
            self.grid.addWidget(self.center_sec, 2, 4); self.center_sec.show()

            if display_mode == 'FILTER':
                # Enable checkboxes only if 2 bounds are placed
                has_bounds = getattr(self.parent_window, 'filter_placed', False)
                self.cb_bpf.setEnabled(has_bounds)
                self.cb_bsf.setEnabled(has_bounds)
        elif display_mode in ['TIME', 'TIME_ENDLESS']:
            self.row1_label.setText("Samples")
            self.row2_label.setText("Time (sec)")
            self.row1_label.show()
            self.row2_label.show()
            
            # Move Time widgets back to Row 2
            self.grid.addWidget(self.row1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.widgets[i]['sam'], 1, i + 1)
                self.grid.addWidget(self.widgets[i]['sec'], 2, i + 1)
                self.widgets[i]['sam'].show()
                self.widgets[i]['sec'].show()
            self.grid.addWidget(self.delta_sam, 1, 3); self.delta_sam.show()
            self.grid.addWidget(self.delta_sec, 2, 3); self.delta_sec.show()
            self.grid.addWidget(self.center_sam, 1, 4); self.center_sam.show()
            self.grid.addWidget(self.center_sec, 2, 4); self.center_sec.show()
            
        show_inv = self.parent_window.settings_mgr.get("ui/show_inv_time", False)
        is_time_mode = display_mode in ['TIME', 'TIME_ENDLESS']
        should_show = show_inv and is_time_mode
        self.row3_label.setVisible(should_show)
        for i in range(2): self.widgets[i]['inv'].setVisible(should_show)
        self.delta_inv.setVisible(should_show)
        self.center_inv.setVisible(should_show)
            
        # Sync lock UI with saved state for this display mode
        if display_mode in self.lock_states:
            for key, btn in [
                ('m1',     self.btn_lock_m1),
                ('m2',     self.btn_lock_m2),
                ('delta',  self.btn_lock_delta),
                ('center', self.btn_lock_center),
            ]:
                locked = self.lock_states[display_mode].get(key, False)
                btn.blockSignals(True)
                btn.setChecked(locked)
                btn.setEnabled(True)
                btn.blockSignals(False)
        else:
            for btn in [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]:
                btn.setEnabled(False)

    def update_overlay_list(self, overlays):
        """
        Populate the shared scroll area with overlay rows.
        Each row: index-label | shape | display-tag | Edit btn | Del btn
        No dialog is shown on Add — the overlay was already placed via click/drag.
        Edit opens the full OverlayDialog.
        """
        if not hasattr(self, '_overlay_rows'):
            self._overlay_rows = []

        # Build / rebuild header once
        if not hasattr(self, '_overlay_header_widget'):
            hw = QWidget()
            hl = QHBoxLayout(hw)
            hl.setContentsMargins(5, 2, 5, 2)
            hl.setSpacing(8)
            l_id   = QLabel("#");          l_id.setFixedWidth(22);  l_id.setObjectName("header_label")
            l_sh   = QLabel("Shape");      l_sh.setObjectName("header_label"); l_sh.setFixedWidth(40)
            l_tag  = QLabel("Tag");        l_tag.setObjectName("header_label")
            hl.addWidget(l_id)
            hl.addWidget(l_sh)
            hl.addWidget(l_tag, 1)
            self._overlay_header_widget = hw
            self.scroll_layout.insertWidget(0, hw)

        # Sync row count
        while len(self._overlay_rows) > len(overlays):
            rd = self._overlay_rows.pop()
            rd['widget'].deleteLater()
        while len(self._overlay_rows) < len(overlays):
            from PyQt6.QtWidgets import QLineEdit
            i   = len(self._overlay_rows)
            row = QWidget()
            rl  = QHBoxLayout(row)
            rl.setContentsMargins(5, 0, 5, 0)
            rl.setSpacing(8)

            lbl_id  = QLabel(f"{i+1}")
            lbl_id.setFixedWidth(22)
            lbl_id.setStyleSheet("color: #008800; font-weight: bold;")

            lbl_shape = QLabel("RECT")
            lbl_shape.setFixedWidth(40)

            edit_tag = QLineEdit()
            edit_tag.setFixedHeight(24)
            edit_tag.setPlaceholderText("...")

            btn_vis = QPushButton("Hide")
            btn_vis.setFixedHeight(28)
            btn_vis.setToolTip("Toggle Visibility")

            btn_edit = QPushButton("Edit")
            btn_edit.setFixedHeight(28)
            btn_edit.setToolTip("Edit overlay properties")

            btn_del = QPushButton("Del")
            btn_del.setFixedHeight(28)
            btn_del.setToolTip("Delete overlay")
            btn_del.setStyleSheet("""
                QPushButton { background: none; color: #ff4444; font-weight: bold;
                              font-size: 13px; border-radius: 4px; border: 1px solid #ff4444; }
                QPushButton:hover { background: rgba(255,68,68,0.2); }
            """)

            rl.addWidget(lbl_id)
            rl.addWidget(lbl_shape)
            rl.addWidget(edit_tag, 1)
            rl.addWidget(btn_vis)
            rl.addWidget(btn_edit)
            rl.addWidget(btn_del)

            self.scroll_layout.insertWidget(self.scroll_layout.count()-1, row)
            self._overlay_rows.append({
                'widget': row, 'lbl_id': lbl_id,
                'lbl_shape': lbl_shape, 'edit_tag': edit_tag,
                'btn_vis': btn_vis, 'btn_edit': btn_edit, 'btn_del': btn_del,
            })

        # Show/hide headers
        if hasattr(self, '_header_widget'):
            self._header_widget.setVisible(False)
        if hasattr(self, '_overlay_header_widget'):
            self._overlay_header_widget.setVisible(True)

        # Hide endless rows
        for rd in getattr(self, '_endless_rows', []):
            rd['widget'].setVisible(False)

        # Update data
        for i, overlay in enumerate(overlays):
            rd = self._overlay_rows[i]
            rd['widget'].setVisible(True)
            rd['lbl_id'].setText(str(i + 1))
            rd['lbl_id'].setStyleSheet(
                f"color: {overlay.border_color or overlay.color or '#008800'}; font-weight: bold;"
            )
            rd['lbl_shape'].setText(overlay.shape.value)
            rd['edit_tag'].blockSignals(True)
            rd['edit_tag'].setText(overlay.display_str or "")
            rd['edit_tag'].setToolTip(overlay.hover_str or "")
            rd['edit_tag'].blockSignals(False)

            rd['btn_vis'].setText("Hide" if overlay.visible else "Show")

            oid = overlay.id
            try: rd['edit_tag'].editingFinished.disconnect()
            except: pass
            try: rd['btn_vis'].clicked.disconnect()
            except: pass
            try: rd['btn_edit'].clicked.disconnect()
            except: pass
            try: rd['btn_del'].clicked.disconnect()
            except: pass
            
            rd['edit_tag'].editingFinished.connect(lambda r=rd, o=oid: self.parent_window.update_overlay(o, display_str=r['edit_tag'].text()))
            rd['btn_vis'].clicked.connect(lambda _, o=oid: self.parent_window.update_overlay(
                o, visible=not self.parent_window._get_overlay_by_id(o).visible))
            rd['btn_edit'].clicked.connect(lambda _, o=oid: self._on_overlay_edit(o))
            rd['btn_del'].clicked.connect(lambda _, o=oid: self.parent_window.remove_overlay(o))

        # Hide extra overlay rows that don't correspond to any overlay
        for rd in self._overlay_rows[len(overlays):]:
            rd['widget'].setVisible(False)

    def _show_endless_rows(self):
        """Switch the scroll area back to showing endless-marker rows."""
        if hasattr(self, '_overlay_header_widget'):
            self._overlay_header_widget.setVisible(False)
        for rd in getattr(self, '_overlay_rows', []):
            rd['widget'].setVisible(False)
        if hasattr(self, '_header_widget'):
            self._header_widget.setVisible(True)
        for rd in getattr(self, '_endless_rows', []):
            rd['widget'].setVisible(True)

    def _on_overlay_edit(self, overlay_id):
        overlay = self.parent_window._get_overlay_by_id(overlay_id)
        if overlay is None:
            return
        from PyQt6.QtWidgets import QDialog
        from .overlay_dialog import OverlayDialog
        dlg = OverlayDialog(
            parent=self,
            parent_window=self.parent_window,
            overlay=overlay,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_overlay()
            self.parent_window.update_overlay(
                overlay_id,
                shape=updated.shape,
                points=updated.points,
                center=updated.center,
                radii=updated.radii,
                color=updated.color,
                alpha=updated.alpha,
                border_width=updated.border_width,
                border_color=updated.border_color,
                border_style=updated.border_style,
                display_str=updated.display_str,
                hover_str=updated.hover_str,
                tag_pos=updated.tag_pos,
                visible=updated.visible,
                z_order=updated.z_order,
                source=updated.source,
            )

    def update_endless_list(self, markers, mode):
        """Update the scroll area with rows for each endless marker, reusing widgets where possible."""
        # Switch header/rows to endless view
        self._show_endless_rows()
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
            l_sub = QLabel(unit_sub)
            l_sub.setObjectName("header_label")
            l_sub.setProperty("role", "sub_header")
            l_main = QLabel(f"Pos ({unit_main})")
            l_main.setObjectName("header_label")
            l_main.setProperty("role", "pos_header")
            
            h_layout.addWidget(l_id)
            h_layout.addWidget(l_sub, 1)
            h_layout.addWidget(l_main, 1)
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
            
            edit_sub = FormattedLineEdit()
            edit_sub.setFixedHeight(24)
            edit_sub.returnPressed.connect(self.parent_window.marker_edit_finished)

            edit_pos = FormattedLineEdit()
            edit_pos.setFixedHeight(24)
            edit_pos.returnPressed.connect(self.parent_window.marker_edit_finished)
            
            btn_del = QPushButton("Del")
            btn_del.setFixedHeight(28)
            btn_del.setToolTip("Remove marker")
            btn_del.setStyleSheet("""
                QPushButton { background: none; color: #ff4444; font-weight: bold; font-size: 13px; border-radius: 4px; border: 1px solid #ff4444; }
                QPushButton:hover { background: rgba(255, 68, 68, 0.2); }
            """)
            
            row_layout.addWidget(lbl_id)
            row_layout.addWidget(edit_sub, 1)
            row_layout.addWidget(edit_pos, 1)
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
        
        # Update Icons based on theme
        self.btn_marker_time.setIcon(self._get_icon("vertical_markers", theme))
        self.btn_marker_freq.setIcon(self._get_icon("horizontal_markers", theme))
        self.btn_zoom.setIcon(self._get_icon("zoom_mode", theme))
        self.btn_move.setIcon(self._get_icon("free_move_mode", theme))
        self.btn_home.setIcon(self._get_icon("reset_zoom", theme))
        self.btn_bpf.setIcon(self._get_icon("bpf_selection_mode", theme))
        self.btn_marker_time_endless.setIcon(self._get_icon("endless_vertical_markers", theme))
        self.btn_marker_freq_endless.setIcon(self._get_icon("endless_horizontal_markers", theme))
        # Overlay button has no icon, but update font colour from theme
        self.btn_overlay.setStyleSheet(f"""QPushButton#mode_btn {{ color: {p.get('accent', '#00aaff') if isinstance(p, dict) else p.accent}; }}""")
        
        self.setStyleSheet(f"""
            MarkerPanel {{ 
                background-color: {p.bg_widget}; 
                border-bottom: 2px solid {p.bg_main};
            }}
            QPushButton#mode_btn {{
                background-color: transparent; 
                border: 2px solid transparent;
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
            for btn in [self.btn_lock_m1, self.btn_lock_m2, self.btn_lock_delta, self.btn_lock_center]:
                btn.setStyleSheet(lock_style)

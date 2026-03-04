from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, 
                             QWidget, QLabel, QLineEdit, QComboBox, QPushButton, 
                             QFormLayout, QDialogButtonBox, QKeySequenceEdit)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from .widgets import KeyBindEdit

class SettingsDialog(QDialog):
    settingsApplied = pyqtSignal()

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.mgr = settings_manager
        self.setWindowTitle("Settings")
        self.resize(500, 400)
        self.setup_ui()

        self.layout.addWidget(self.tabs)

    def _add_reset_row(self, form, label, widget, key):
        """Helper to add a row with a reset button."""
        row_layout = QHBoxLayout()
        row_layout.addWidget(widget)
        
        reset_btn = QPushButton("🔄")
        reset_btn.setToolTip("Reset to default")
        reset_btn.setFixedWidth(30)
        reset_btn.setStyleSheet("padding: 2px; font-size: 14px;")
        
        def reset_clicked():
            default_val = self.mgr.get_default(key)
            if isinstance(widget, QLineEdit):
                widget.setText(str(default_val))
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(default_val))
            elif isinstance(widget, KeyBindEdit):
                widget.setText(str(default_val))
            elif isinstance(widget, QKeySequenceEdit):
                widget.setKeySequence(QKeySequence(str(default_val)))
        
        reset_btn.clicked.connect(reset_clicked)
        row_layout.addWidget(reset_btn)
        
        form.addRow(label, row_layout)

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        # --- General Tab ---
        self.general_tab = QWidget()
        self.general_form = QFormLayout(self.general_tab)
        
        self.fc_edit = QLineEdit(str(self.mgr.get("core/fc")))
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["int8", "int16", "int32", "float32", "float64", "complex64"])
        self.type_combo.setCurrentText(str(self.mgr.get("core/type", "complex64")))
        
        self.fft_combo = QComboBox()
        powers = [2**i for i in range(5, 17)]
        self.fft_combo.addItems([str(p) for p in powers])
        self.fft_combo.setCurrentText(str(self.mgr.get("core/fft_size")))

        self.overlap_edit = QLineEdit(str(self.mgr.get("core/overlap")))
        self.window_combo = QComboBox()
        self.window_combo.addItems(["Hanning", "Hamming", "Blackman", "Bartlett", "Rectangular"])
        self.window_combo.setCurrentText(str(self.mgr.get("core/window_type")))

        self._add_reset_row(self.general_form, "Default Center Freq (Hz):", self.fc_edit, "core/fc")
        self._add_reset_row(self.general_form, "Default File Type:", self.type_combo, "core/type")
        self._add_reset_row(self.general_form, "Default FFT Size:", self.fft_combo, "core/fft_size")
        self._add_reset_row(self.general_form, "Default Overlap (%):", self.overlap_edit, "core/overlap")
        self._add_reset_row(self.general_form, "Default Window:", self.window_combo, "core/window_type")
        
        self.tabs.addTab(self.general_tab, "General")

        # --- Appearance Tab ---
        self.appearance_tab = QWidget()
        self.appearance_form = QFormLayout(self.appearance_tab)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        self.theme_combo.setCurrentText(str(self.mgr.get("ui/theme")))
        
        self._add_reset_row(self.appearance_form, "Theme:", self.theme_combo, "ui/theme")
        self.tabs.addTab(self.appearance_tab, "Appearance")

        # --- Keyboard Tab ---
        self.keyboard_tab = QWidget()
        self.keyboard_form = QFormLayout(self.keyboard_tab)
        
        self.time_key = KeyBindEdit()
        self.time_key.setText(str(self.mgr.get("keybinds/time_markers")))
        
        self.mag_key = KeyBindEdit()
        self.mag_key.setText(str(self.mgr.get("keybinds/mag_markers")))
        
        self.zoom_key = KeyBindEdit()
        self.zoom_key.setText(str(self.mgr.get("keybinds/zoom_mode")))
        
        self._add_reset_row(self.keyboard_form, "Time Markers Key:", self.time_key, "keybinds/time_markers")
        self._add_reset_row(self.keyboard_form, "Magnitude/Freq Markers Key:", self.mag_key, "keybinds/mag_markers")
        self._add_reset_row(self.keyboard_form, "Zoom Pulse Key (Hold):", self.zoom_key, "keybinds/zoom_mode")
        
        self.tabs.addTab(self.keyboard_tab, "Keyboard")

        # --- Buttons ---
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Apply | 
            QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.save_and_close)
        self.button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_settings)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def apply_settings(self):
        if self.save_settings():
            self.settingsApplied.emit()

    def save_and_close(self):
        if self.save_settings():
            self.settingsApplied.emit()
            self.accept()

    def save_settings(self):
        try:
            self.mgr.set("core/fc", float(self.fc_edit.text()))
            self.mgr.set("core/type", self.type_combo.currentText())
            self.mgr.set("core/fft_size", int(self.fft_combo.currentText()))
            self.mgr.set("core/overlap", float(self.overlap_edit.text()))
            self.mgr.set("core/window_type", self.window_combo.currentText())
            self.mgr.set("ui/theme", self.theme_combo.currentText())
            
            self.mgr.set("keybinds/time_markers", self.time_key.text())
            self.mgr.set("keybinds/mag_markers", self.mag_key.text())
            self.mgr.set("keybinds/zoom_mode", self.zoom_key.text())
            return True
        except ValueError as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Invalid Value", f"Please check your inputs.\nError: {str(e)}")
            return False

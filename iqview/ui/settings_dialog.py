from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, 
                             QWidget, QLabel, QLineEdit, QComboBox, QPushButton, 
                             QFormLayout, QDialogButtonBox, QKeySequenceEdit)
from PyQt6.QtCore import Qt

class SettingsDialog(QDialog):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.mgr = settings_manager
        self.setWindowTitle("Settings")
        self.resize(500, 400)
        self.setup_ui()

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        # --- General Tab ---
        self.general_tab = QWidget()
        self.general_form = QFormLayout(self.general_tab)
        
        self.fs_edit = QLineEdit(str(self.mgr.get("core/fs")))
        self.fc_edit = QLineEdit(str(self.mgr.get("core/fc")))
        
        self.fft_combo = QComboBox()
        powers = [2**i for i in range(5, 17)]
        self.fft_combo.addItems([str(p) for p in powers])
        self.fft_combo.setCurrentText(str(self.mgr.get("core/fft_size")))

        self.overlap_edit = QLineEdit(str(self.mgr.get("core/overlap")))
        self.window_combo = QComboBox()
        self.window_combo.addItems(["Hanning", "Hamming", "Blackman", "Bartlett", "Rectangular"])
        self.window_combo.setCurrentText(str(self.mgr.get("core/window_type")))

        self.general_form.addRow("Default Sample Rate (Hz):", self.fs_edit)
        self.general_form.addRow("Default Center Freq (Hz):", self.fc_edit)
        self.general_form.addRow("Default FFT Size:", self.fft_combo)
        self.general_form.addRow("Default Overlap (%):", self.overlap_edit)
        self.general_form.addRow("Default Window:", self.window_combo)
        
        self.tabs.addTab(self.general_tab, "General")

        # --- Appearance Tab ---
        self.appearance_tab = QWidget()
        self.appearance_form = QFormLayout(self.appearance_tab)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        self.theme_combo.setCurrentText(str(self.mgr.get("ui/theme")))
        
        self.appearance_form.addRow("Theme:", self.theme_combo)
        self.tabs.addTab(self.appearance_tab, "Appearance")

        # --- Keyboard Tab ---
        self.keyboard_tab = QWidget()
        self.keyboard_form = QFormLayout(self.keyboard_tab)
        
        # In a real app we'd use QKeySequenceEdit, but for single-key triggers like 'T'
        # we'll stick to a simple mapping for now.
        self.time_key = QLineEdit(str(self.mgr.get("keybinds/time_markers")))
        self.mag_key = QLineEdit(str(self.mgr.get("keybinds/mag_markers")))
        self.zoom_key = QLineEdit(str(self.mgr.get("keybinds/zoom_mode")))
        
        self.keyboard_form.addRow("Time Markers Key:", self.time_key)
        self.keyboard_form.addRow("Magnitude/Freq Markers Key:", self.mag_key)
        self.keyboard_form.addRow("Zoom Pulse Key (Hold):", self.zoom_key)
        
        self.tabs.addTab(self.keyboard_tab, "Keyboard")

        # --- Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.save_and_close)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def save_and_close(self):
        try:
            self.mgr.set("core/fs", float(self.fs_edit.text()))
            self.mgr.set("core/fc", float(self.fc_edit.text()))
            self.mgr.set("core/fft_size", int(self.fft_combo.currentText()))
            self.mgr.set("core/overlap", float(self.overlap_edit.text()))
            self.mgr.set("core/window_type", self.window_combo.currentText())
            self.mgr.set("ui/theme", self.theme_combo.currentText())
            
            self.mgr.set("keybinds/time_markers", self.time_key.text().upper())
            self.mgr.set("keybinds/mag_markers", self.mag_key.text().upper())
            self.mgr.set("keybinds/zoom_mode", self.zoom_key.text())
            
            self.accept()
        except ValueError as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Invalid Value", f"Please check your inputs.\nError: {str(e)}")

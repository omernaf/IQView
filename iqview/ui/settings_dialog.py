from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, 
                             QWidget, QLabel, QLineEdit, QComboBox, QPushButton, 
                             QFormLayout, QDialogButtonBox, QKeySequenceEdit, QCheckBox,
                             QColorDialog, QSlider, QSpinBox)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QKeySequence, QIcon, QPixmap, QPainter, QLinearGradient, QColor
from .widgets import KeyBindEdit

class ColorButton(QPushButton):
    colorChanged = pyqtSignal(str)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(QSize(40, 24))
        self.clicked.connect(self._on_clicked)
        self._update_style()

    def _update_style(self):
        self.setStyleSheet(f"background-color: {self._color}; border: 1px solid #888; border-radius: 4px;")

    def color(self):
        return self._color

    def setColor(self, color):
        self._color = color
        self._update_style()

    def _on_clicked(self):
        new_color = QColorDialog.getColor(QColor(self._color), self)
        if new_color.isValid():
            self._color = new_color.name()
            self._update_style()
            self.colorChanged.emit(self._color)

class SettingsDialog(QDialog):
    settingsApplied = pyqtSignal()

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.mgr = settings_manager
        self.setWindowTitle("Settings")
        self.resize(500, 400)
        self.setup_ui()

    def _make_colormap_icon(self, cmap_name):
        from pyqtgraph.graphicsItems.GradientPresets import Gradients
        if cmap_name not in Gradients:
            return QIcon()
        
        pixmap = QPixmap(64, 16)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        
        gradient = QLinearGradient(0, 0, 64, 0)
        preset = Gradients[cmap_name]
        for pos, color in preset['ticks']:
            if isinstance(color, tuple):
                qcolor = QColor(*color)
            else:
                qcolor = QColor(color)
            gradient.setColorAt(pos, qcolor)
            
        painter.fillRect(pixmap.rect(), gradient)
        painter.end()
        return QIcon(pixmap)

    def _add_reset_row(self, form, label, widget, key_or_func):
        """Helper to add a row with a reset button. key_or_func can be a string or a callable."""
        row_layout = QHBoxLayout()
        row_layout.addWidget(widget)
        
        reset_btn = QPushButton("🔄")
        reset_btn.setToolTip("Reset to default")
        reset_btn.setFixedWidth(30)
        reset_btn.setStyleSheet("padding: 2px; font-size: 14px;")
        
        def reset_clicked():
            key = key_or_func() if callable(key_or_func) else key_or_func
            default_val = self.mgr.get_default(key)
            if isinstance(widget, QLineEdit):
                widget.setText(str(default_val))
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(default_val))
            elif isinstance(widget, KeyBindEdit):
                widget.setText(str(default_val))
            elif isinstance(widget, QKeySequenceEdit):
                widget.setKeySequence(QKeySequence(str(default_val)))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(default_val))
            elif isinstance(widget, ColorButton):
                widget.setColor(str(default_val))
        
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
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        
        self.cmap_combo = QComboBox()
        cmaps = ['thermal', 'flame', 'yellowy', 'bipolar', 'spectrum', 'cyclic', 'greyclip', 'grey', 'viridis', 'inferno', 'plasma', 'magma', 'turbo']
        for name in cmaps:
            icon = self._make_colormap_icon(name)
            self.cmap_combo.addItem(icon, name)
        self.cmap_combo.setCurrentText(str(self.mgr.get("ui/colormap", "turbo")))
        
        self.cmap_reverse_cb = QCheckBox("Reverse")
        self.cmap_reverse_cb.setChecked(bool(self.mgr.get("ui/colormap_reversed", False)))

        # Marker and Zoom Box Styles
        self.marker_styles = ["SolidLine", "DashLine", "DotLine", "DashDotLine"]
        
        # Time Markers
        self.time_color_btn = ColorButton("#000000")
        self.time_style_combo = QComboBox()
        self.time_style_combo.addItems(self.marker_styles)
        
        # Freq Markers
        self.freq_color_btn = ColorButton("#000000")
        self.freq_style_combo = QComboBox()
        self.freq_style_combo.addItems(self.marker_styles)
        
        # Zoom Box
        self.zoom_color_btn = ColorButton("#000000")
        self.zoom_style_combo = QComboBox()
        self.zoom_style_combo.addItems(self.marker_styles)

        self._add_reset_row(self.appearance_form, "Theme:", self.theme_combo, "ui/theme")
        self._add_reset_row(self.appearance_form, "Default Colormap:", self.cmap_combo, "ui/colormap")
        self._add_reset_row(self.appearance_form, "Reverse Colormap:", self.cmap_reverse_cb, "ui/colormap_reversed")
        
        self.appearance_form.addRow(QLabel(" "))
        self.appearance_form.addRow(QLabel("<b>Grid Customization</b>"))
        
        self.grid_enabled_cb = QCheckBox("Enabled")
        self.grid_color_btn = ColorButton("#c8c8ff")
        self.grid_style_combo = QComboBox()
        self.grid_style_combo.addItems(["SolidLine", "DashLine", "DotLine", "DashDotLine"])
        
        self.grid_alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self.grid_alpha_slider.setRange(0, 100)
        self.grid_alpha_slider.setTickInterval(10)
        self.grid_alpha_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.grid_alpha_label = QLabel("30%")
        self.grid_alpha_slider.valueChanged.connect(lambda v: self.grid_alpha_label.setText(f"{v}%"))
        
        grid_alpha_layout = QHBoxLayout()
        grid_alpha_layout.addWidget(self.grid_alpha_slider)
        grid_alpha_layout.addWidget(self.grid_alpha_label)
        
        self.appearance_form.addRow("Grid Visibility:", self.grid_enabled_cb)
        self._add_reset_row(self.appearance_form, "Grid Color:", self.grid_color_btn, lambda: f"ui/{self.theme_combo.currentText().lower()}/grid_color")
        self._add_reset_row(self.appearance_form, "Grid Style:", self.grid_style_combo, lambda: f"ui/{self.theme_combo.currentText().lower()}/grid_style")
        self.appearance_form.addRow("Grid Opacity:", grid_alpha_layout)

        self.appearance_form.addRow(QLabel(" "))
        self.appearance_form.addRow(QLabel("<b>Font & Scaling</b>"))
        
        self.axis_font_spin = QSpinBox()
        self.axis_font_spin.setRange(6, 24)
        self.precision_spin = QSpinBox()
        self.precision_spin.setRange(0, 12)
        
        self._add_reset_row(self.appearance_form, "Axis Font Size:", self.axis_font_spin, "ui/axis_font_size")
        self._add_reset_row(self.appearance_form, "Label Precision:", self.precision_spin, "ui/label_precision")

        self.appearance_form.addRow(QLabel(" "))
        self.appearance_form.addRow(QLabel("<b>Marker & Zoom Customization</b>"))
        
        t_key = lambda: f"ui/{self.theme_combo.currentText().lower()}"
        self._add_reset_row(self.appearance_form, "Time Marker Color:", self.time_color_btn, lambda: f"{t_key()}/time_marker_color")
        self._add_reset_row(self.appearance_form, "Time Marker Style:", self.time_style_combo, lambda: f"{t_key()}/time_marker_style")
        
        self._add_reset_row(self.appearance_form, "Freq Marker Color:", self.freq_color_btn, lambda: f"{t_key()}/freq_marker_color")
        self._add_reset_row(self.appearance_form, "Freq Marker Style:", self.freq_style_combo, lambda: f"{t_key()}/freq_marker_style")
        
        self._add_reset_row(self.appearance_form, "Zoom Box Color:", self.zoom_color_btn, lambda: f"{t_key()}/zoom_box_color")
        self._add_reset_row(self.appearance_form, "Zoom Box Style:", self.zoom_style_combo, lambda: f"{t_key()}/zoom_box_style")

        # Initial load based on current theme
        self._load_theme_specific_settings(self.theme_combo.currentText())
        
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
            self.mgr.set("ui/colormap", self.cmap_combo.currentText())
            self.mgr.set("ui/colormap_reversed", self.cmap_reverse_cb.isChecked())
            
            # Save theme-specific styles for the CURRENTLY SELECTED theme in the dialog
            theme = self.theme_combo.currentText().lower()
            self.mgr.set(f"ui/{theme}/time_marker_color", self.time_color_btn.color())
            self.mgr.set(f"ui/{theme}/time_marker_style", self.time_style_combo.currentText())
            self.mgr.set(f"ui/{theme}/freq_marker_color", self.freq_color_btn.color())
            self.mgr.set(f"ui/{theme}/freq_marker_style", self.freq_style_combo.currentText())
            self.mgr.set(f"ui/{theme}/zoom_box_color", self.zoom_color_btn.color())
            self.mgr.set(f"ui/{theme}/zoom_box_style", self.zoom_style_combo.currentText())

            # Grid Settings
            self.mgr.set("ui/grid_enabled", self.grid_enabled_cb.isChecked())
            self.mgr.set("ui/grid_alpha", self.grid_alpha_slider.value())
            self.mgr.set(f"ui/{theme}/grid_color", self.grid_color_btn.color())
            self.mgr.set(f"ui/{theme}/grid_style", self.grid_style_combo.currentText())
            
            # Font & Scaling
            self.mgr.set("ui/axis_font_size", self.axis_font_spin.value())
            self.mgr.set("ui/label_precision", self.precision_spin.value())

            self.mgr.set("keybinds/time_markers", self.time_key.text())
            self.mgr.set("keybinds/mag_markers", self.mag_key.text())
            self.mgr.set("keybinds/zoom_mode", self.zoom_key.text())
            return True
        except ValueError as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Invalid Value", f"Please check your inputs.\nError: {str(e)}")
            return False

    def _on_theme_changed(self, theme_text):
        self._load_theme_specific_settings(theme_text)

    def _load_theme_specific_settings(self, theme_text):
        theme = theme_text.lower()
        self.time_color_btn.setColor(str(self.mgr.get(f"ui/{theme}/time_marker_color")))
        self.time_style_combo.setCurrentText(str(self.mgr.get(f"ui/{theme}/time_marker_style")))
        self.freq_color_btn.setColor(str(self.mgr.get(f"ui/{theme}/freq_marker_color")))
        self.freq_style_combo.setCurrentText(str(self.mgr.get(f"ui/{theme}/freq_marker_style")))
        self.zoom_color_btn.setColor(str(self.mgr.get(f"ui/{theme}/zoom_box_color")))
        self.zoom_style_combo.setCurrentText(str(self.mgr.get(f"ui/{theme}/zoom_box_style")))
        
        self.grid_color_btn.setColor(str(self.mgr.get(f"ui/{theme}/grid_color")))
        self.grid_style_combo.setCurrentText(str(self.mgr.get(f"ui/{theme}/grid_style")))
        
        # Load non-theme specific but related to appearance
        self.grid_enabled_cb.setChecked(bool(self.mgr.get("ui/grid_enabled", True)))
        alpha = int(self.mgr.get("ui/grid_alpha", 30))
        self.grid_alpha_slider.setValue(alpha)
        self.grid_alpha_label.setText(f"{alpha}%")
        
        self.axis_font_spin.setValue(int(self.mgr.get("ui/axis_font_size", 10)))
        self.precision_spin.setValue(int(self.mgr.get("ui/label_precision", 6)))

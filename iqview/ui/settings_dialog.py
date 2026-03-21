from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget, 
                             QWidget, QLabel, QLineEdit, QComboBox, QPushButton, 
                             QFormLayout, QDialogButtonBox, QKeySequenceEdit, QCheckBox,
                             QColorDialog, QSlider, QSpinBox, QListWidget, QListWidgetItem,
                             QAbstractItemView, QTableWidget, QTableWidgetItem, QHeaderView,
                             QScrollArea, QFrame)
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

class PlotItemWidget(QWidget):
    def __init__(self, text, checked, filter_len=None, parent=None):
        super().__init__(parent)
        self.text = text
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 2, 10, 2)
        
        self.cb = QCheckBox(text)
        self.cb.setChecked(checked)
        self.layout.addWidget(self.cb)
        
        self.layout.addStretch()
        
        self.spin = None
        if filter_len is not None:
            self.label = QLabel("Median Filter:")
            self.layout.addWidget(self.label)
            self.spin = QSpinBox()
            self.spin.setRange(1, 101)
            self.spin.setSingleStep(2)
            self.spin.setValue(filter_len)
            self.spin.setFixedWidth(60)
            self.layout.addWidget(self.spin)
        
        self.setStyleSheet("background: transparent; color: inherit;")

class SettingsDialog(QDialog):
    settingsApplied = pyqtSignal()

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.mgr = settings_manager
        self.setWindowTitle("Settings")
        self.setMinimumSize(730, 560)
        self.setup_ui()
        self._update_dialog_style(self.mgr.get("ui/theme", "Dark"))

    def _update_dialog_style(self, theme_text):
        from .themes import get_main_stylesheet
        self.setStyleSheet(get_main_stylesheet(theme_text))

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
        reset_btn.setFixedHeight(30)
        # Use a property for specific styling if needed, but let it inherit from QPushButton global style
        reset_btn.setProperty("is_reset", True)
        reset_btn.setFlat(True) # Make it subtly integrate better into the row layout
        
        def reset_clicked():
            key = key_or_func() if callable(key_or_func) else key_or_func
            default_val = self.mgr.get_default(key)
            
            if isinstance(widget, QLineEdit):
                widget.setText(str(default_val))
            elif isinstance(widget, QComboBox):
                if isinstance(default_val, bool):
                    target_text = "On" if default_val else "Off"
                else:
                    target_text = str(default_val)
                
                # Find best match in combo
                index = widget.findText(target_text)
                if index >= 0:
                    widget.setCurrentIndex(index)
                else:
                    widget.setCurrentText(target_text)
            elif isinstance(widget, QSpinBox) or isinstance(widget, QDoubleSpinBox):
                widget.setValue(default_val)
            elif isinstance(widget, KeyBindEdit):
                widget.setText(str(default_val))
            elif isinstance(widget, QKeySequenceEdit):
                widget.setKeySequence(QKeySequence(str(default_val)))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(default_val))
            elif isinstance(widget, ColorButton):
                widget.setColor(str(default_val))
        
        reset_btn.clicked.connect(reset_clicked)
        row_layout.addSpacing(10)
        row_layout.addWidget(reset_btn)
        
        form.addRow(label, row_layout)

    def add_side_tab(self, widget, title):
        self.stacked_widget.addWidget(widget)
        item = QListWidgetItem(title)
        item.setSizeHint(QSize(110, 30))
        self.side_menu.addItem(item)

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        
        self.main_content = QHBoxLayout()
        self.side_menu = QListWidget()
        self.side_menu.setFixedWidth(130)
        
        # Style applied dynamically in _update_sidebar_style
        
        self.stacked_widget = QStackedWidget()
        self.main_content.addWidget(self.side_menu)
        self.main_content.addWidget(self.stacked_widget, 1)
        self.layout.addLayout(self.main_content)
        
        self.side_menu.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
        
        # --- Helper for Plot Lists ---
        def add_plot_item(list_widget, text, checked, filter_len=None):
            # Keep item empty so QListWidget doesn't render text/checkbox over our widget
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 36))
            
            # Store serializable data in UserRole for drag-drop persistence
            # QVariant can handle dictionaries (QMap) fine without recursion errors
            data = {"text": text, "checked": checked, "filter_len": filter_len}
            item.setData(Qt.ItemDataRole.UserRole, data)
            
            list_widget.addItem(item)
            widget = PlotItemWidget(text, checked, filter_len)
            list_widget.setItemWidget(item, widget)
            
            # Sync widget changes back to item data dictionary
            def update_data():
                d = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(d, dict):
                    d["checked"] = widget.cb.isChecked()
                    if widget.spin:
                        d["filter_len"] = widget.spin.value()
                    item.setData(Qt.ItemDataRole.UserRole, d)
                    
            widget.cb.toggled.connect(update_data)
            if widget.spin:
                widget.spin.valueChanged.connect(update_data)
            
            return item

        # Initialize all tabs and forms first so we can style them uniformly
        tabs_info = [
            ('general', 'General'),
            ('appearance', 'Appearance'),
            ('keyboard', 'Keyboard'),
            ('filter', 'Filter')
        ]
        
        for name, _ in tabs_info:
            content_widget = QWidget()
            form_layout = QFormLayout(content_widget)
            
            # Use generous spacing and margins for an airy, premium feel
            form_layout.setSpacing(22)
            form_layout.setContentsMargins(40, 35, 40, 35)
            form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            
            setattr(self, f"{name}_tab", content_widget)
            setattr(self, f"{name}_form", form_layout)
            setattr(self, f"{name}_content", content_widget)

        # --- General Tab Population ---
        self.fs_edit = QLineEdit(str(self.mgr.get("core/fs", 1e6)))
        self.fc_edit = QLineEdit(str(self.mgr.get("core/fc")))
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["int16", "float32", "float64", "complex64", "complex128"])
        self.type_combo.setCurrentText(str(self.mgr.get("core/type", "complex64")))
        
        self.fft_combo = QComboBox()
        powers = [2**i for i in range(5, 17)]
        self.fft_combo.addItems([str(p) for p in powers])
        self.fft_combo.setCurrentText(str(self.mgr.get("core/fft_size")))

        self.overlap_edit = QLineEdit(str(self.mgr.get("core/overlap")))
        self.window_combo = QComboBox()
        self.window_combo.addItems(["Hanning", "Hamming", "Blackman", "Bartlett", "Rectangular"])
        self.window_combo.setCurrentText(str(self.mgr.get("core/window_type")))

        self._add_reset_row(self.general_form, "Default Sample Rate (Hz):", self.fs_edit, "core/fs")
        self._add_reset_row(self.general_form, "Default Center Freq (Hz):", self.fc_edit, "core/fc")
        self._add_reset_row(self.general_form, "Default File Type:", self.type_combo, "core/type")
        self._add_reset_row(self.general_form, "Default FFT Size:", self.fft_combo, "core/fft_size")
        self._add_reset_row(self.general_form, "Default Overlap (%):", self.overlap_edit, "core/overlap")
        self._add_reset_row(self.general_form, "Default Window:", self.window_combo, "core/window_type")
        
        self.general_form.addRow(QLabel(" "))
        self.show_inv_combo = QComboBox()
        self.show_inv_combo.addItems(["Off", "On"])
        show_inv_val = self.mgr.get("ui/show_inv_time", False)
        self.show_inv_combo.setCurrentText("On" if show_inv_val else "Off")
        self._add_reset_row(self.general_form, "Show 1/T (Hz) Row in Markers:", self.show_inv_combo, "ui/show_inv_time")
        
        self.add_side_tab(self.general_tab, "General")

        # --- Appearance Tab ---
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
        self._update_sidebar_style(self.theme_combo.currentText())
        
        self.add_side_tab(self.appearance_tab, "Appearance")

        # --- Keyboard Tab ---
        self.time_key = KeyBindEdit()
        self.time_key.setText(str(self.mgr.get("keybinds/time_markers")))
        
        self.mag_key = KeyBindEdit()
        self.mag_key.setText(str(self.mgr.get("keybinds/mag_markers")))
        
        self.zoom_key = KeyBindEdit()
        self.zoom_key.setText(str(self.mgr.get("keybinds/zoom_mode")))
        
        self._add_reset_row(self.keyboard_form, "Time Markers Key:", self.time_key, "keybinds/time_markers")
        self._add_reset_row(self.keyboard_form, "Magnitude/Freq Markers Key:", self.mag_key, "keybinds/mag_markers")
        self._add_reset_row(self.keyboard_form, "Zoom Pulse Key (Hold):", self.zoom_key, "keybinds/zoom_mode")
        
        self.add_side_tab(self.keyboard_tab, "Keyboard")

        # --- Filter Tab ---
        self.filter_type_combo = QComboBox()
        self.filter_type_combo.addItems(["Butterworth", "Chebyshev I", "Chebyshev II", "Elliptic", "Bessel"])
        self.filter_type_combo.setCurrentText(str(self.mgr.get("core/filter_type", "Elliptic")))
        self.filter_type_combo.currentTextChanged.connect(self._on_filter_type_changed)
        
        self.filter_order_spin = QSpinBox()
        self.filter_order_spin.setRange(1, 32)
        self.filter_order_spin.setValue(int(self.mgr.get("core/filter_order", 8)))
        
        self.filter_ripple_edit = QLineEdit(str(self.mgr.get("core/filter_ripple", 0.1)))
        self.filter_stopband_edit = QLineEdit(str(self.mgr.get("core/filter_stopband", 60.0)))
        
        self.filter_bessel_norm_combo = QComboBox()
        self.filter_bessel_norm_combo.addItems(["phase", "delay", "mag"])
        self.filter_bessel_norm_combo.setCurrentText(str(self.mgr.get("core/filter_bessel_norm", "phase")))
        
        self._add_reset_row(self.filter_form, "Filter Type:", self.filter_type_combo, "core/filter_type")
        self._add_reset_row(self.filter_form, "Filter Order:", self.filter_order_spin, "core/filter_order")
        self._add_reset_row(self.filter_form, "Passband Ripple (dB):", self.filter_ripple_edit, "core/filter_ripple")
        self._add_reset_row(self.filter_form, "Stopband Atten (dB):", self.filter_stopband_edit, "core/filter_stopband")
        self._add_reset_row(self.filter_form, "Bessel Norm:", self.filter_bessel_norm_combo, "core/filter_bessel_norm")
        
        self._on_filter_type_changed(self.filter_type_combo.currentText())
        
        self.add_side_tab(self.filter_tab, "Filter")

        # --- Plots Tab ---
        self.plots_tab = QWidget()
        self.plots_layout = QVBoxLayout(self.plots_tab)
        
        help_lbl = QLabel("Drag to reorder. Checked plots appear in the Time Domain toolbar.")
        help_lbl.setStyleSheet("font-style: italic;")
        self.plots_layout.addWidget(help_lbl)
        
        self.plots_list = QListWidget()
        self.plots_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.plots_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        
        # All available plot types
        all_plots = [
            "Real", "Real [dB]", "Imaginary", "Imaginary [dB]", 
            "Phase", "Unwrapped phase", "instant frequency", 
            "magnitude", "magnitude [dB]", "magnitude^2", 
            "magnitude^2 [dB]"
        ]
        
        # Load active/sorted plots from settings
        saved_plots = self.mgr.get("core/time_plots", [])
        
        # 1. Add saved ones
        filter_len = int(self.mgr.get("core/inst_freq_filter_len", 7))
        for p in saved_plots:
            if p in all_plots:
                add_plot_item(self.plots_list, p, True, filter_len if p == "instant frequency" else None)
                
        # 2. Add remaining
        for p in all_plots:
            if p not in saved_plots:
                add_plot_item(self.plots_list, p, False, filter_len if p == "instant frequency" else None)
                
        self.plots_layout.addWidget(self.plots_list)
        
        # Reset to Default button
        reset_plots_btn = QPushButton("Reset to Default")
        def reset_plots():
            self.plots_list.clear()
            defaults = self.mgr.get_default("core/time_plots")
            for p in defaults:
                if p in all_plots:
                    add_plot_item(self.plots_list, p, True, filter_len if p == "instant frequency" else None)
            for p in all_plots:
                if p not in defaults:
                    add_plot_item(self.plots_list, p, False, filter_len if p == "instant frequency" else None)
        reset_plots_btn.clicked.connect(reset_plots)
        self.plots_layout.addWidget(reset_plots_btn)
        
        self.add_side_tab(self.plots_tab, "Time Plots")

        # --- Frequency Plots Tab ---
        self.freq_plots_tab = QWidget()
        self.freq_plots_layout = QVBoxLayout(self.freq_plots_tab)
        
        freq_help_lbl = QLabel("Select and reorder frequency domain plots (Drag-and-drop to reorder):")
        freq_help_lbl.setStyleSheet("font-style: italic;")
        self.freq_plots_layout.addWidget(freq_help_lbl)
        
        self.freq_plots_list = QListWidget()
        self.freq_plots_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.freq_plots_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        
        all_freq_plots = [
            "magnitude", "magnitude [dB]", "magnitude^2", 
            "magnitude^2 [dB]", "real", "real [dB]", 
            "imag", "imag [dB]", "phase", "unwrapped phase"
        ]
        
        saved_freq_plots = self.mgr.get("core/frequency_plots", [])
        
        # 1. Add saved ones
        for p in saved_freq_plots:
            if p in all_freq_plots:
                add_plot_item(self.freq_plots_list, p, True)
                
        # 2. Add remaining
        for p in all_freq_plots:
            if p not in saved_freq_plots:
                add_plot_item(self.freq_plots_list, p, False)
                
        self.freq_plots_layout.addWidget(self.freq_plots_list)
        
        reset_freq_plots_btn = QPushButton("Reset to Default")
        def reset_freq_plots():
            self.freq_plots_list.clear()
            defaults = self.mgr.get_default("core/frequency_plots")
            if not defaults: defaults = ["magnitude", "magnitude [dB]"]
            for p in defaults:
                if p in all_freq_plots:
                    add_plot_item(self.freq_plots_list, p, True)
            for p in all_freq_plots:
                if p not in defaults:
                    add_plot_item(self.freq_plots_list, p, False)
        reset_freq_plots_btn.clicked.connect(reset_freq_plots)
        self.freq_plots_layout.addWidget(reset_freq_plots_btn)
        
        self.add_side_tab(self.freq_plots_tab, "Frequency Plots")

        # --- File Types Tab ---
        self.file_types_tab = QWidget()
        self.file_types_layout = QVBoxLayout(self.file_types_tab)
        
        ft_help = QLabel("Map file extensions (e.g. '.32f') to a data type. These are used when auto-detecting the data type of an opened file.")
        ft_help.setWordWrap(True)
        ft_help.setStyleSheet("font-style: italic;")
        self.file_types_layout.addWidget(ft_help)
        
        self.ext_table = QTableWidget()
        self.ext_table.setColumnCount(2)
        self.ext_table.setHorizontalHeaderLabels(["Extension", "Data Type"])
        self.ext_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.ext_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ext_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_types_layout.addWidget(self.ext_table)
        
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add")
        remove_btn = QPushButton("Remove Selected")
        reset_ft_btn = QPushButton("Reset to Default")
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_ft_btn)
        self.file_types_layout.addLayout(btn_layout)
        
        self._load_extension_mappings()
        
        add_btn.clicked.connect(self._add_ext_mapping_row)
        remove_btn.clicked.connect(self._remove_ext_mapping_row)
        reset_ft_btn.clicked.connect(self._reset_ext_mappings)

        self.add_side_tab(self.file_types_tab, "File Types")
        if self.side_menu.count() > 0:
            self.side_menu.setCurrentRow(0)

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
            self.mgr.set("core/fs", float(self.fs_edit.text()))
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
            self.mgr.set("ui/show_inv_time", (self.show_inv_combo.currentText() == "On"))

            self.mgr.set("keybinds/time_markers", self.time_key.text())
            self.mgr.set("keybinds/mag_markers", self.mag_key.text())
            self.mgr.set("keybinds/zoom_mode", self.zoom_key.text())

            # Filter Settings
            self.mgr.set("core/filter_type", self.filter_type_combo.currentText())
            self.mgr.set("core/filter_order", self.filter_order_spin.value())
            self.mgr.set("core/filter_ripple", float(self.filter_ripple_edit.text()))
            self.mgr.set("core/filter_stopband", float(self.filter_stopband_edit.text()))
            self.mgr.set("core/filter_bessel_norm", self.filter_bessel_norm_combo.currentText())
            
            # Save Plots
            active_plots = []
            for i in range(self.plots_list.count()):
                item = self.plots_list.item(i)
                widget = self.plots_list.itemWidget(item)
                data = item.data(Qt.ItemDataRole.UserRole)
                
                # Preferred: read from widget
                if widget:
                    if widget.cb.isChecked():
                        active_plots.append(widget.text)
                        if widget.spin:
                            self.mgr.set("core/inst_freq_filter_len", widget.spin.value())
                # Fallback: read from persistent dictionary
                elif isinstance(data, dict):
                    if data.get("checked"):
                        plot_name = data.get("text")
                        active_plots.append(plot_name)
                        if plot_name == "instant frequency":
                            self.mgr.set("core/inst_freq_filter_len", data.get("filter_len", 7))
            self.mgr.set("core/time_plots", active_plots)

            active_freq_plots = []
            for i in range(self.freq_plots_list.count()):
                item = self.freq_plots_list.item(i)
                widget = self.freq_plots_list.itemWidget(item)
                data = item.data(Qt.ItemDataRole.UserRole)
                
                if widget:
                    if widget.cb.isChecked():
                        active_freq_plots.append(widget.text)
                elif isinstance(data, dict):
                    if data.get("checked"):
                        active_freq_plots.append(data.get("text"))
            self.mgr.set("core/frequency_plots", active_freq_plots)
            
            # Save Extension Mappings
            ext_map = {}
            for row in range(self.ext_table.rowCount()):
                ext_item = self.ext_table.item(row, 0)
                type_widget = self.ext_table.cellWidget(row, 1)
                
                if ext_item and type_widget:
                    ext_text = ext_item.text().strip().lower()
                    if ext_text and not ext_text.startswith('.'):
                        ext_text = '.' + ext_text
                    
                    if ext_text:
                        ext_map[ext_text] = type_widget.currentText()
            self.mgr.set("core/extension_mapping", ext_map)
            
            return True
        except ValueError as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Invalid Value", f"Please check your inputs.\nError: {str(e)}")
            return False

    def _on_theme_changed(self, theme_text):
        self._load_theme_specific_settings(theme_text)
        self._update_sidebar_style(theme_text)
        self._update_dialog_style(theme_text)

    def _update_sidebar_style(self, theme_text):
        theme = theme_text.lower()
        if theme == "dark":
            bg = "#1e1e1e"
            text = "#d4d4d4"
            sel_bg = "#007acc"
            sel_text = "#ffffff"
        else:
            bg = "#f3f3f3"
            text = "#000000"
            sel_bg = "#007acc"
            sel_text = "#ffffff"
            
        self.side_menu.setStyleSheet(f"""
            QListWidget {{ 
                border: none; 
                outline: none; 
                background-color: {bg};
            }}
            QListWidget::item {{ 
                padding: 8px 5px; 
                border-radius: 4px; 
                color: {text};
                margin-bottom: 2px;
            }}
            QListWidget::item:hover {{
                background-color: rgba(128, 128, 128, 0.1);
            }}
            QListWidget::item:selected {{ 
                background-color: {sel_bg};
                color: {sel_text};
                font-weight: bold; 
            }}
        """)

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

    def _on_filter_type_changed(self, filter_type):
        """Show/Hide ripple, stopband, and norm inputs based on filter type."""
        is_ripple_valid = filter_type in ["Chebyshev I", "Elliptic"]
        is_stopband_valid = filter_type in ["Chebyshev II", "Elliptic"]
        is_bessel = filter_type == "Bessel"
        
        # QFormLayout.setRowVisible is available in Qt 5.15+ (PyQt6 6.0+)
        # Rows are: 0: Type, 1: Order, 2: Ripple, 3: Stopband, 4: Bessel Norm
        self.filter_form.setRowVisible(2, is_ripple_valid)
        self.filter_form.setRowVisible(3, is_stopband_valid)
        self.filter_form.setRowVisible(4, is_bessel)

    def _load_extension_mappings(self):
        self.ext_table.setRowCount(0)
        mappings = self.mgr.get("core/extension_mapping", self.mgr.get_default("core/extension_mapping"))
        for ext, dtype in mappings.items():
            self._add_ext_mapping_row(ext, dtype)

    def _add_ext_mapping_row(self, ext="", dtype="complex64"):
        row = self.ext_table.rowCount()
        self.ext_table.insertRow(row)
        
        ext_item = QTableWidgetItem(ext)
        self.ext_table.setItem(row, 0, ext_item)
        
        dtype_combo = QComboBox()
        valid_types = ["int16", "float32", "float64", "complex64", "complex128"]
        dtype_combo.addItems(valid_types)
        
        # In case an invalid type somehow got saved, default to complex64
        if dtype not in valid_types:
            dtype = "complex64"
        dtype_combo.setCurrentText(dtype)
        
        self.ext_table.setCellWidget(row, 1, dtype_combo)

    def _remove_ext_mapping_row(self):
        selected_rows = set(index.row() for index in self.ext_table.selectedIndexes())
        for row in sorted(selected_rows, reverse=True):
            self.ext_table.removeRow(row)
            
    def _reset_ext_mappings(self):
        self.ext_table.setRowCount(0)
        defaults = self.mgr.get_default("core/extension_mapping")
        for ext, dtype in defaults.items():
            self._add_ext_mapping_row(ext, dtype)

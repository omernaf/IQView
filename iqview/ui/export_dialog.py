import os
import numpy as np
import scipy.io
from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import Qt, pyqtSlot
import pyqtgraph as pg

class ExportDialog(QtWidgets.QDialog):
    def __init__(self, ui_controller, parent=None):
        super().__init__(parent)
        self.ui_controller = ui_controller
        self.setWindowTitle("Export Data & Image")
        self.resize(500, 600)
        
        self.layout = QtWidgets.QVBoxLayout(self)
        
        # Tabs
        self.tabs = QtWidgets.QTabWidget()
        self.layout.addWidget(self.tabs)
        
        self.setup_image_tab()
        self.setup_data_tab()
        self.setup_metadata_tab()
        
        # Bottom Buttons
        self.btn_layout = QtWidgets.QHBoxLayout()
        self.btn_close = QtWidgets.QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_close)
        self.layout.addLayout(self.btn_layout)
        
        self.refresh_theme()

    def setup_image_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        
        # Scope Group
        scope_group = QtWidgets.QGroupBox("Image Scope")
        scope_layout = QtWidgets.QVBoxLayout(scope_group)
        self.radio_raw = QtWidgets.QRadioButton("Raw Spectrogram (Pixels only)")
        self.radio_axes = QtWidgets.QRadioButton("Plot with Axes and Markers")
        self.radio_window = QtWidgets.QRadioButton("Entire Window")
        self.radio_axes.setChecked(True)
        scope_layout.addWidget(self.radio_raw)
        scope_layout.addWidget(self.radio_axes)
        scope_layout.addWidget(self.radio_window)
        layout.addWidget(scope_group)
        
        # Format Group
        fmt_group = QtWidgets.QGroupBox("Format")
        fmt_layout = QtWidgets.QHBoxLayout(fmt_group)
        self.combo_img_fmt = QtWidgets.QComboBox()
        self.combo_img_fmt.addItems(["PNG", "JPG", "BMP"])
        fmt_layout.addWidget(QtWidgets.QLabel("Format:"))
        fmt_layout.addWidget(self.combo_img_fmt)
        layout.addWidget(fmt_group)
        
        # Actions
        actions_group = QtWidgets.QGroupBox("Actions")
        actions_layout = QtWidgets.QHBoxLayout(actions_group)
        self.btn_save_img = QtWidgets.QPushButton("Save to File...")
        self.btn_copy_img = QtWidgets.QPushButton("Copy to Clipboard")
        self.btn_save_img.clicked.connect(self.export_image_file)
        self.btn_copy_img.clicked.connect(self.export_image_clipboard)
        actions_layout.addWidget(self.btn_save_img)
        actions_layout.addWidget(self.btn_copy_img)
        layout.addWidget(actions_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Image")

    def setup_data_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        
        # Format Group
        fmt_group = QtWidgets.QGroupBox("Data Format")
        fmt_layout = QtWidgets.QVBoxLayout(fmt_group)
        self.radio_mat = QtWidgets.QRadioButton("MATLAB (.mat)")
        
        # Determine dynamic extension for display
        s = self.ui_controller
        if not s.is_complex:
            bin_ext = ".32f" if s.data_type == np.float32 else ".64f"
            bin_label = f"Raw Binary (Real, {bin_ext})"
        else:
            if s.data_type == np.int16:
                bin_ext = ".16tc"
            elif s.data_type == np.float64:
                bin_ext = ".64fc"
            else:
                bin_ext = ".32fc"
            bin_label = f"Raw Binary IQ (Complex, {bin_ext})"
            
        self.radio_bin = QtWidgets.QRadioButton(bin_label)
        self.radio_mat.setChecked(True)
        fmt_layout.addWidget(self.radio_mat)
        fmt_layout.addWidget(self.radio_bin)
        layout.addWidget(fmt_group)
        
        # Range Group
        range_group = QtWidgets.QGroupBox("Data Range")
        range_layout = QtWidgets.QVBoxLayout(range_group)
        self.radio_full = QtWidgets.QRadioButton("Full Loaded Data")
        self.radio_visible = QtWidgets.QRadioButton("Visible View")
        self.radio_markers = QtWidgets.QRadioButton("Between Time Markers (M1/M2)")
        self.radio_full.setChecked(True)
        
        # Check if markers exist to enable the option
        has_two_markers = len(getattr(self.ui_controller, 'markers_time', [])) == 2
        self.radio_markers.setEnabled(has_two_markers)
        if not has_two_markers:
            self.radio_markers.setToolTip("Place two time markers to enable this option.")
        
        range_layout.addWidget(self.radio_full)
        range_layout.addWidget(self.radio_visible)
        range_layout.addWidget(self.radio_markers)
        layout.addWidget(range_group)
        
        # Export Button
        self.btn_export_data = QtWidgets.QPushButton("Export Data...")
        self.btn_export_data.clicked.connect(self.export_data)
        layout.addWidget(self.btn_export_data)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Data")

    def setup_metadata_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        
        info = QtWidgets.QTextEdit()
        info.setReadOnly(True)
        
        # Gather info
        s = self.ui_controller
        md = [
            f"Source: {s.data_source}",
            f"Center Freq: {s.fc / 1e6:.3f} MHz",
            f"Sample Rate: {s.rate / 1e6:.3f} MHz",
            f"FFT Size: {s.fft_size}",
            f"Overlap: {s.overlap_percent}%",
            f"Duration: {s.time_duration:.3f} s",
            f"Data Type: {s.data_type}"
        ]
        info.setText("\n".join(md))
        layout.addWidget(QtWidgets.QLabel("Signal Metadata Overview:"))
        layout.addWidget(info)
        
        self.btn_save_json = QtWidgets.QPushButton("Save Sidebar JSON...")
        self.btn_save_json.clicked.connect(self.export_metadata_json)
        layout.addWidget(self.btn_save_json)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Metadata")

    def get_selected_image(self):
        if self.radio_raw.isChecked():
            return self.ui_controller.spectrogram_view.capture_raw_image()
        elif self.radio_axes.isChecked():
            return self.ui_controller.spectrogram_view.capture_plot_with_axes()
        else:
            # Entire Window - use a global screen grab at the window's frame coordinate.
            # frameGeometry() includes title bar and borders.
            screen = QtWidgets.QApplication.primaryScreen()
            if screen:
                geom = self.ui_controller.frameGeometry()
                # Use the window's own winId() instead of 0 (desktop) to capture only THIS window
                # and ignore anything on top of it.
                pixmap = screen.grabWindow(self.ui_controller.winId())
                return pixmap.toImage()
            return self.ui_controller.grab().toImage()

    def export_image_file(self):
        is_window_capture = self.radio_window.isChecked()
        if is_window_capture:
            # Ensure the window is on top and updated
            self.ui_controller.raise_()
            self.ui_controller.activateWindow()
            self.hide()
            # Give WM/DWM time to hide and redraw the composite buffer
            for _ in range(3):
                QtWidgets.QApplication.processEvents()
            QtCore.QThread.msleep(300)
            
        img = self.get_selected_image()
        
        if is_window_capture:
            self.show()
            self.raise_()
            self.activateWindow()
        fmt = self.combo_img_fmt.currentText().lower()
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Image", "", f"{fmt.upper()} Files (*.{fmt})"
        )
        if path:
            if not path.lower().endswith(f".{fmt}"):
                path += f".{fmt}"
            img.save(path)
            # QtWidgets.QMessageBox.information(self, "Export Successful", f"Image saved to {path}")

    def export_image_clipboard(self):
        is_window_capture = self.radio_window.isChecked()
        if is_window_capture:
            # Ensure the window is on top and updated
            self.ui_controller.raise_()
            self.ui_controller.activateWindow()
            self.hide()
            # Give WM/DWM time to hide and redraw the composite buffer
            for _ in range(3):
                QtWidgets.QApplication.processEvents()
            QtCore.QThread.msleep(300)

        img = self.get_selected_image()
        
        if is_window_capture:
            self.show()
            self.raise_()
            self.activateWindow()
        QtWidgets.QApplication.clipboard().setImage(img)
        # Maybe a small temporary tooltip or status bar message?
        self.btn_copy_img.setText("Copied!")
        QtCore.QTimer.singleShot(2000, lambda: self.btn_copy_img.setText("Copy to Clipboard"))

    def export_data(self):
        # 1. Determine Range
        start_sec, end_sec = 0, self.ui_controller.time_duration
        
        if self.radio_visible.isChecked():
            xr, _ = self.ui_controller.spectrogram_view.view_box.viewRange()
            start_sec, end_sec = xr[0], xr[1]
        elif self.radio_markers.isChecked():
            m1 = self.ui_controller.markers_time[0].value()
            m2 = self.ui_controller.markers_time[1].value()
            start_sec, end_sec = min(m1, m2), max(m1, m2)
        
        # 2. Extract Data
        data = self.ui_controller.extract_iq_segment(start_sec, end_sec)
        if data is None:
            QtWidgets.QMessageBox.warning(self, "Export Failed", "Could not extract data for the selected range.")
            return

        # 3. File Dialog
        is_mat = self.radio_mat.isChecked()
        s = self.ui_controller
        
        if is_mat:
            ext = "mat"
            filter_str = "MATLAB Files (*.mat)"
        else:
            if not s.is_complex:
                ext = "32f" if s.data_type == np.float32 else "64f"
            else:
                if s.data_type == np.int16:
                    ext = "16tc"
                elif s.data_type == np.float64:
                    ext = "64fc"
                else:
                    ext = "32fc"
            filter_str = f"Binary Files (*.{ext})"
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Data", "", filter_str
        )
        if not path: return
        
        if not path.lower().endswith(f".{ext}"):
            path += f".{ext}"

        try:
            if is_mat:
                # MATLAB format updates:
                # 1. Y = data / sqrt(10)
                # 2. XDelta = 1 / fs
                # 3. InputCenter = fc
                scipy.io.savemat(path, {
                    "Y": data / np.sqrt(10),
                    "XDelta": 1.0 / s.rate,
                    "InputCenter": s.fc,
                    "t_start": start_sec,
                    "t_end": end_sec,
                    "source": str(s.data_source)
                })
            else:
                if not s.is_complex:
                    # Save as Real
                    data.real.astype(s.data_type).tofile(path)
                else:
                    if s.data_type == np.int16:
                        # Interleave back to int16
                        interleaved = np.empty(len(data) * 2, dtype=np.int16)
                        interleaved[0::2] = np.round(data.real).astype(np.int16)
                        interleaved[1::2] = np.round(data.imag).astype(np.int16)
                        interleaved.tofile(path)
                    else:
                        # complex64/128 are saved as interleaved floats by numpy.tofile
                        out_dtype = np.complex128 if s.data_type == np.float64 else np.complex64
                        data.astype(out_dtype).tofile(path)
            
            QtWidgets.QMessageBox.information(self, "Export Successful", f"Data exported to {os.path.basename(path)}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Error", f"Failed to export data: {str(e)}")

    def export_metadata_json(self):
        import json
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Metadata", "", "JSON Files (*.json)"
        )
        if not path: return
        
        if not path.endswith(".json"): path += ".json"
        
        s = self.ui_controller
        meta = {
            "source": str(s.data_source),
            "center_freq_hz": s.fc,
            "sample_rate_hz": s.rate,
            "fft_size": s.fft_size,
            "overlap_percent": s.overlap_percent,
            "duration_s": s.time_duration,
            "data_type": str(s.data_type)
        }
        
        try:
            with open(path, 'w') as f:
                json.dump(meta, f, indent=4)
            QtWidgets.QMessageBox.information(self, "Export Successful", f"Metadata saved to {os.path.basename(path)}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Error", f"Failed to save metadata: {str(e)}")

    def refresh_theme(self):
        from .themes import get_palette
        theme = self.ui_controller.settings_mgr.get("ui/theme", "Dark")
        p = get_palette(theme)
        
        self.setStyleSheet(f"""
            QDialog {{ background-color: {p.bg_main}; color: {p.text_main}; }}
            QTabWidget::pane {{ border: 1px solid {p.border}; background: {p.bg_sidebar}; }}
            QTabBar::tab {{ background: {p.bg_main}; color: {p.text_dim}; padding: 8px 12px; border: 1px solid {p.border}; }}
            QTabBar::tab:selected {{ background: {p.bg_sidebar}; color: {p.text_main}; border-bottom-color: {p.bg_sidebar}; }}
            QGroupBox {{ font-weight: bold; border: 1px solid {p.border}; margin-top: 15px; padding: 15px; color: {p.text_header}; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }}
            QLabel {{ color: {p.text_main}; }}
            QPushButton {{ background-color: {p.bg_main}; border: 1px solid {p.border}; padding: 8px; border-radius: 4px; color: {p.text_main}; }}
            QPushButton:hover {{ background-color: {p.accent_dim}; border-color: {p.accent}; }}
            QComboBox, QLineEdit, QTextEdit {{ background-color: {p.bg_main}; color: {p.text_main}; border: 1px solid {p.border}; padding: 4px; border-radius: 4px; }}
            QRadioButton {{ color: {p.text_main}; spacing: 5px; }}
            QRadioButton::indicator {{ width: 14px; height: 14px; }}
        """)

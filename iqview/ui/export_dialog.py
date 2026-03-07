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
        # True when opened from a TimeDomainView instead of the main SpectrogramWindow
        self.is_time_domain = not getattr(ui_controller, 'is_spectrogram', True)
        self.setWindowTitle("Export Data & Image")
        self.resize(520, 730)
        
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
        # Cache the window snapshot once so the preview doesn't capture the dialog
        self._window_snapshot = None
        QtCore.QTimer.singleShot(50, self._cache_window_snapshot)

    def setup_image_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setSpacing(8)
        
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
        
        # Wire radios to update preview
        self.radio_raw.toggled.connect(self._on_scope_changed)
        self.radio_axes.toggled.connect(self._on_scope_changed)
        self.radio_window.toggled.connect(self._on_scope_changed)

        # Preview Group
        preview_group = QtWidgets.QGroupBox("Preview")
        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(8, 16, 8, 8)

        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(220)
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setText("Loading preview…")
        preview_layout.addWidget(self.preview_label)

        # Pixel-size hint label
        self.preview_size_label = QtWidgets.QLabel()
        self.preview_size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_size_label.setObjectName("previewSizeLabel")
        preview_layout.addWidget(self.preview_size_label)

        layout.addWidget(preview_group)

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
        self.btn_save_img = QtWidgets.QPushButton("Save to File…")
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

        if self.is_time_domain:
            # ---- Time Domain data export ----
            fmt_group = QtWidgets.QGroupBox("Data Format")
            fmt_layout = QtWidgets.QVBoxLayout(fmt_group)
            self.radio_mat = QtWidgets.QRadioButton("MATLAB (.mat)  —  complex IQ struct")
            self.radio_npy = QtWidgets.QRadioButton("NumPy (.npy)  —  complex64 array")
            self.radio_bin = QtWidgets.QRadioButton("Raw Binary (.32fc)  —  interleaved float32")
            self.radio_mat.setChecked(True)
            fmt_layout.addWidget(self.radio_mat)
            fmt_layout.addWidget(self.radio_npy)
            fmt_layout.addWidget(self.radio_bin)
            layout.addWidget(fmt_group)

            range_group = QtWidgets.QGroupBox("Data Range")
            range_layout = QtWidgets.QVBoxLayout(range_group)
            self.radio_full = QtWidgets.QRadioButton("Full Segment")
            self.radio_visible = QtWidgets.QRadioButton("Visible View")
            self.radio_markers = QtWidgets.QRadioButton("Between Time Markers (M1/M2)")
            self.radio_full.setChecked(True)
            has_two_markers = len(getattr(self.ui_controller, 'markers_time', [])) == 2
            self.radio_markers.setEnabled(has_two_markers)
            if not has_two_markers:
                self.radio_markers.setToolTip("Place two time markers to enable this option.")
            range_layout.addWidget(self.radio_full)
            range_layout.addWidget(self.radio_visible)
            range_layout.addWidget(self.radio_markers)
            layout.addWidget(range_group)
        else:
            # ---- Spectrogram / IQ data export ----
            fmt_group = QtWidgets.QGroupBox("Data Format")
            fmt_layout = QtWidgets.QVBoxLayout(fmt_group)
            self.radio_mat = QtWidgets.QRadioButton("MATLAB (.mat)")
            self.radio_npy = QtWidgets.QRadioButton("NumPy (.npy)  —  complex64 array")
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
            fmt_layout.addWidget(self.radio_npy)
            fmt_layout.addWidget(self.radio_bin)
            layout.addWidget(fmt_group)

            range_group = QtWidgets.QGroupBox("Data Range")
            range_layout = QtWidgets.QVBoxLayout(range_group)
            self.radio_full = QtWidgets.QRadioButton("Full Loaded Data")
            self.radio_visible = QtWidgets.QRadioButton("Visible View")
            range_layout.addWidget(self.radio_full)
            range_layout.addWidget(self.radio_visible)
            
            self.radio_filter = QtWidgets.QRadioButton("Between Filter Bounds")
            has_filter = len(getattr(self.ui_controller, 'filter_bounds', [])) == 2
            self.radio_filter.setEnabled(has_filter)
            if not has_filter:
                self.radio_filter.setToolTip("Place two filter bounds to enable this option.")
            range_layout.addWidget(self.radio_filter)
            
            self.radio_markers = QtWidgets.QRadioButton("Between Time Markers (M1/M2)")
            self.radio_full.setChecked(True)
            has_two_markers = len(getattr(self.ui_controller, 'markers_time', [])) == 2
            self.radio_markers.setEnabled(has_two_markers)
            if not has_two_markers:
                self.radio_markers.setToolTip("Place two time markers to enable this option.")
            range_layout.addWidget(self.radio_markers)
            layout.addWidget(range_group)

        self.chk_auto_metadata = QtWidgets.QCheckBox("Also save metadata JSON")
        self.chk_auto_metadata.setChecked(True)
        layout.addWidget(self.chk_auto_metadata)

        # Export Button (shared)
        self.btn_export_data = QtWidgets.QPushButton("Export Data...")
        self.btn_export_data.clicked.connect(self.export_data)
        layout.addWidget(self.btn_export_data)

        layout.addStretch()
        self.tabs.addTab(tab, "Data")

    def _get_source_name(self):
        s = self.ui_controller
        src = getattr(s.parent_window if self.is_time_domain else s, 'data_source', 'N/A')
        if isinstance(src, (bytes, bytearray)):
            return "<stdin>"
        return str(src)

    def setup_metadata_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)

        info = QtWidgets.QTextEdit()
        info.setReadOnly(True)

        s = self.ui_controller
        src_str = self._get_source_name()
        
        if self.is_time_domain:
            duration = len(s.samples) / s.rate
            md = [
                f"Source: {src_str}",
                f"Sample Rate: {s.rate / 1e6:.3f} MHz",
                f"Segment Start: {s.start_time:.6f} s",
                f"Segment Duration: {duration:.6f} s",
                f"Samples: {len(s.samples)}",
            ]
        else:
            md = [
                f"Source: {src_str}",
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

        self.btn_save_json = QtWidgets.QPushButton("Save Metadata JSON...")
        self.btn_save_json.clicked.connect(self.export_metadata_json)
        layout.addWidget(self.btn_save_json)

        layout.addStretch()
        self.tabs.addTab(tab, "Metadata")

    # ------------------------------------------------------------------ preview
    def _cache_window_snapshot(self):
        """Grab a screenshot of the main window once at dialog open time.
        We do this on a timer so the export dialog itself is visible but
        not overlapping the main window grab."""
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            pix = screen.grabWindow(self.ui_controller.winId())
            self._window_snapshot = pix
        else:
            self._window_snapshot = self.ui_controller.grab()
        self.refresh_preview()

    def _on_scope_changed(self, checked):
        """Triggered when a radio button is toggled. Only react when a button
        becomes checked (not when it becomes unchecked)."""
        if checked:
            self.refresh_preview()

    def _capture_td_raw(self):
        """Capture the raw waveform pixels from the TimeDomainView plot."""
        from pyqtgraph.exporters import ImageExporter
        exporter = ImageExporter(self.ui_controller.plot_widget.plotItem)
        return QtGui.QPixmap.fromImage(exporter.export(toBytes=True))

    def _capture_td_axes(self):
        """Capture the TimeDomainView plot including axes and markers."""
        from pyqtgraph.exporters import ImageExporter
        exporter = ImageExporter(self.ui_controller.plot_widget.scene())
        return QtGui.QPixmap.fromImage(exporter.export(toBytes=True))

    def refresh_preview(self):
        """Render the currently-selected export type and show a thumbnail."""
        if not hasattr(self, 'preview_label'):
            return
        try:
            if self.radio_raw.isChecked():
                if self.is_time_domain:
                    pix = self._capture_td_raw()
                else:
                    img = self.ui_controller.spectrogram_view.capture_raw_image()
                    pix = QtGui.QPixmap.fromImage(img)
            elif self.radio_axes.isChecked():
                if self.is_time_domain:
                    pix = self._capture_td_axes()
                else:
                    img = self.ui_controller.spectrogram_view.capture_plot_with_axes()
                    pix = QtGui.QPixmap.fromImage(img)
            else:  # Entire Window
                if self._window_snapshot is not None:
                    pix = self._window_snapshot
                else:
                    pix = self.ui_controller.grab()

            if pix.isNull():
                self.preview_label.setText("Preview unavailable")
                self.preview_size_label.setText("")
                return

            # Record original pixel dims for the size hint
            orig_w, orig_h = pix.width(), pix.height()

            # Scale to fit the label, keeping aspect ratio
            max_w = self.preview_label.width() or 480
            max_h = self.preview_label.minimumHeight()
            scaled = pix.scaled(
                max_w, max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled)
            self.preview_size_label.setText(f"{orig_w} × {orig_h} px")
        except Exception as e:
            self.preview_label.setText(f"Preview error: {e}")
            self.preview_size_label.setText("")

    def get_selected_image(self):
        if self.radio_raw.isChecked():
            if self.is_time_domain:
                return self._capture_td_raw().toImage()
            return self.ui_controller.spectrogram_view.capture_raw_image()
        elif self.radio_axes.isChecked():
            if self.is_time_domain:
                return self._capture_td_axes().toImage()
            return self.ui_controller.spectrogram_view.capture_plot_with_axes()
        else:
            # Entire Window — use cached snapshot if available (avoids dialog covering the window)
            if self._window_snapshot is not None:
                return self._window_snapshot.toImage()
            screen = QtWidgets.QApplication.primaryScreen()
            if screen:
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
        s = self.ui_controller

        if self.is_time_domain:
            # ---- Time Domain export ----
            # 1. Determine sample range
            t_start_seg = s.start_time
            t_end_seg = s.start_time + len(s.samples) / s.rate

            if self.radio_visible.isChecked():
                xr, _ = s.view_box.viewRange()
                t_start_seg, t_end_seg = xr[0], xr[1]
            elif self.radio_markers.isChecked():
                m1 = s.markers_time[0].value()
                m2 = s.markers_time[1].value()
                t_start_seg, t_end_seg = min(m1, m2), max(m1, m2)

            # Clamp and slice
            t0 = s.start_time
            i_start = max(0, int((t_start_seg - t0) * s.rate))
            i_end = min(len(s.samples), int((t_end_seg - t0) * s.rate))
            data = s.samples[i_start:i_end]
            if len(data) == 0:
                QtWidgets.QMessageBox.warning(self, "Export Failed", "No samples in selected range.")
                return

            is_mat = self.radio_mat.isChecked()
            is_npy = self.radio_npy.isChecked()
            if is_mat:
                ext, filter_str = "mat", "MATLAB Files (*.mat)"
            elif is_npy:
                ext, filter_str = "npy", "NumPy Files (*.npy)"
            else:
                ext, filter_str = "32fc", "Raw Binary Files (*.32fc)"

            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Data", "", filter_str)
            if not path: return
            if not path.lower().endswith(f".{ext}"): path += f".{ext}"

            try:
                if is_mat:
                    scipy.io.savemat(path, {
                        "Y": data.astype(np.complex64),
                        "XDelta": 1.0 / s.rate,
                        "t_start": t_start_seg,
                        "t_end": t_end_seg,
                    })
                elif is_npy:
                    np.save(path, data.astype(np.complex64))
                else:  # raw binary .32fc
                    data.astype(np.complex64).tofile(path)
                
                if self.chk_auto_metadata.isChecked():
                    json_path = os.path.splitext(path)[0] + '.json'
                    self.export_metadata_json(auto_path=json_path)

                QtWidgets.QMessageBox.information(self, "Export Successful", f"Data exported to {os.path.basename(path)}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Export Error", f"Failed to export data: {str(e)}")
            return

        # ---- Spectrogram / IQ export ----
        start_sec, end_sec = 0, s.time_duration
        apply_filter_export = False
        
        if self.radio_visible.isChecked():
            xr, _ = s.spectrogram_view.view_box.viewRange()
            start_sec, end_sec = xr[0], xr[1]
        elif getattr(self, 'radio_filter', None) and self.radio_filter.isChecked():
            # Export data for the whole segment but explicitly run the filter on it
            start_sec, end_sec = 0, s.time_duration
            apply_filter_export = True
        elif self.radio_markers.isChecked():
            m1 = s.markers_time[0].value()
            m2 = s.markers_time[1].value()
            start_sec, end_sec = min(m1, m2), max(m1, m2)

        data = s.extract_iq_segment(start_sec, end_sec)
        if data is None:
            QtWidgets.QMessageBox.warning(self, "Export Failed", "Could not extract data for the selected range.")
            return

        if apply_filter_export:
            from iqview.dsp.dsp import apply_bpf
            f_low, f_high = s.filter_bounds[0], s.filter_bounds[1]
            try:
                filter_type = s.settings_mgr.get('dsp/filter_type', 'Elliptic')
                filter_order = int(s.settings_mgr.get('dsp/filter_order', 8))
                filter_ripple = float(s.settings_mgr.get('dsp/filter_ripple', 0.1))
                filter_stopband = float(s.settings_mgr.get('dsp/filter_stopband', 60.0))
                bessel_norm = s.settings_mgr.get('dsp/filter_bessel_norm', 'phase')
                
                data = apply_bpf(
                    data, s.rate, f_low, f_high, 
                    filter_type=filter_type, order=filter_order, 
                    rp=filter_ripple, rs=filter_stopband, bessel_norm=bessel_norm
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Export Error", f"Filter failed: {str(e)}")
                return

        is_mat = self.radio_mat.isChecked()
        is_npy = self.radio_npy.isChecked()
        if is_mat:
            ext = "mat"
            filter_str = "MATLAB Files (*.mat)"
        elif is_npy:
            ext = "npy"
            filter_str = "NumPy Files (*.npy)"
        else:
            if not s.is_complex:
                ext = "32f" if s.data_type == np.float32 else "64f"
            else:
                ext = "16tc" if s.data_type == np.int16 else ("64fc" if s.data_type == np.float64 else "32fc")
            filter_str = f"Binary Files (*.{ext})"

        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Data", "", filter_str)
        if not path: return
        if not path.lower().endswith(f".{ext}"): path += f".{ext}"

        try:
            if is_mat:
                source_str = self._get_source_name()
                scipy.io.savemat(path, {
                    "Y": data / np.sqrt(10),
                    "XDelta": 1.0 / s.rate,
                    "InputCenter": s.fc,
                    "t_start": start_sec,
                    "t_end": end_sec,
                    "source": source_str
                })
            elif is_npy:
                np.save(path, data.astype(np.complex64))
            else:
                if not s.is_complex:
                    data.real.astype(s.data_type).tofile(path)
                else:
                    if s.data_type == np.int16:
                        interleaved = np.empty(len(data) * 2, dtype=np.int16)
                        interleaved[0::2] = np.round(data.real).astype(np.int16)
                        interleaved[1::2] = np.round(data.imag).astype(np.int16)
                        interleaved.tofile(path)
                    else:
                        out_dtype = np.complex128 if s.data_type == np.float64 else np.complex64
                        data.astype(out_dtype).tofile(path)
                        
            if self.chk_auto_metadata.isChecked():
                json_path = os.path.splitext(path)[0] + '.json'
                self.export_metadata_json(auto_path=json_path)
                
            QtWidgets.QMessageBox.information(self, "Export Successful", f"Data exported to {os.path.basename(path)}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Error", f"Failed to export data: {str(e)}")

    def export_metadata_json(self, auto_path=None):
        import json
        if auto_path is not None:
            path = auto_path
        else:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save Metadata", "", "JSON Files (*.json)"
            )
            if not path: return
        if not path.endswith(".json"): path += ".json"

        s = self.ui_controller
        src_str = self._get_source_name()
        
        if self.is_time_domain:
            meta = {
                "source": src_str,
                "sample_rate_hz": s.rate,
                "segment_start_s": s.start_time,
                "segment_duration_s": len(s.samples) / s.rate,
                "num_samples": len(s.samples),
            }
            if len(s.markers_time) >= 1: meta["marker_1_s"] = s.markers_time[0].value()
            if len(s.markers_time) >= 2: meta["marker_2_s"] = s.markers_time[1].value()
        else:
            meta = {
                "source": src_str,
                "center_freq_hz": s.fc,
                "sample_rate_hz": s.rate,
                "fft_size": s.fft_size,
                "overlap_percent": s.overlap_percent,
                "duration_s": s.time_duration,
                "data_type": str(s.data_type)
            }
            if len(s.markers_time) >= 1: meta["time_marker_1_s"] = s.markers_time[0].value()
            if len(s.markers_time) >= 2: meta["time_marker_2_s"] = s.markers_time[1].value()
            if len(s.markers_freq) >= 1: meta["freq_marker_1_hz"] = s.markers_freq[0].value()
            if len(s.markers_freq) >= 2: meta["freq_marker_2_hz"] = s.markers_freq[1].value()
            if len(getattr(s, 'filter_bounds', [])) == 2:
                meta["filter_low_hz"] = s.filter_bounds[0]
                meta["filter_high_hz"] = s.filter_bounds[1]
        
        try:
            with open(path, 'w') as f:
                json.dump(meta, f, indent=4)
            if auto_path is None:
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
            QLabel#previewLabel {{
                background-color: {p.bg_main};
                border: 1px solid {p.border};
                border-radius: 6px;
                color: {p.text_dim};
                padding: 4px;
            }}
            QLabel#previewSizeLabel {{
                color: {p.text_dim};
                font-size: 10px;
                padding: 0px;
                border: none;
                background: transparent;
            }}
        """)


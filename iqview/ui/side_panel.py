from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QTabWidget, QCheckBox, QWidget
from PyQt6.QtCore import pyqtSignal, Qt, QObject
from PyQt6.QtGui import QFont, QPixmap
from PyQt6 import QtGui
import numpy as np
import importlib.resources
import os
import threading
import subprocess
import sys
import re

class VersionChecker(QObject):
    version_checked = pyqtSignal(str)

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version

    def start(self):
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self):
        try:
            # Run pip index versions iqview using the current python executable
            cmd = [sys.executable, "-m", "pip", "index", "versions", "iqview"]
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                startupinfo=startupinfo
            )
            
            if result.returncode == 0:
                output = result.stdout
                # Parse LATEST: x.y.z
                match = re.search(r'LATEST:\s+(\S+)', output)
                if not match:
                    # Fallback to package (x.y.z) parsing on first line
                    first_line = output.strip().split('\n')[0]
                    match = re.search(r'^[a-zA-Z0-9_-]+\s+\(([^)]+)\)', first_line)
                
                if match:
                    latest = match.group(1).strip()
                    if self._is_newer(latest, self.current_version):
                        self.version_checked.emit(latest)
                        return
        except Exception as e:
            # Fail silently to avoid interrupting the user
            print(f"Error checking version: {e}")
        
        self.version_checked.emit("")

    def _is_newer(self, latest, current):
        try:
            from packaging.version import parse as parse_version
            return parse_version(latest) > parse_version(current)
        except Exception:
            try:
                l_parts = [int(x) for x in re.findall(r'\d+', latest)]
                c_parts = [int(x) for x in re.findall(r'\d+', current)]
                return tuple(l_parts) > tuple(c_parts)
            except Exception:
                return latest != current


def format_frequency(val):
    abs_val = abs(val)
    if abs_val >= 1e6:
        return f"{val / 1e6:.6f} MHz"
    elif abs_val >= 1e3:
        return f"{val / 1e3:.6f} kHz"
    else:
        return f"{val:.6f} Hz"

class FocusLineEdit(QLineEdit):
    def __init__(self, val_formatter, parent=None):
        super().__init__(parent)
        self.val_formatter = val_formatter
        self.raw_value = 0.0
        
    def set_value(self, val):
        self.raw_value = val
        if not self.hasFocus():
            self.setText(self.val_formatter(val))
            
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.setText(f"{self.raw_value:.6f}".rstrip('0').rstrip('.'))
        
    def focusOutEvent(self, event):
        text = self.text().strip()
        if text:
            try:
                self.raw_value = float(text)
            except ValueError:
                pass
        self.setText(self.val_formatter(self.raw_value))
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            text = self.text().strip()
            if text:
                try:
                    self.raw_value = float(text)
                except ValueError:
                    pass
            self.setText(self.val_formatter(self.raw_value))
            self.clearFocus()
        super().keyPressEvent(event)


class SidePanel(QFrame):
    parametersChanged = pyqtSignal(dict)
    multirowChanged = pyqtSignal(dict)

    def __init__(self, fs, fc, fft_size, window_type="Hamming", overlap_percent=99.0, window_size=None, parent_window=None):
        super().__init__()
        self.parent_window = parent_window
        self.fs = fs
        self.fc = fc
        self.fft_size = fft_size
        self.window_size = window_size if window_size is not None else fft_size
        self.window_type = window_type
        self.overlap_percent = overlap_percent
        
        self.setup_ui()
        self.update_derived_values()
        
        # Start background version checker
        self.checker = VersionChecker(self.current_version)
        self.checker.version_checked.connect(self.on_version_checked)
        self.checker.start()

    def setup_ui(self):
        self.setFixedWidth(240)
        # Base style handled by main stylesheet, but keep sidebar specific borders
        self.setStyleSheet("""
            SidePanel { 
                border-right: 1px solid #2a2a2a;
            }
            QLabel#section_header {
                color: #00aaff;
                font-size: 11px;
                font-weight: bold;
                margin-top: 15px;
                margin-bottom: 5px;
                border-bottom: 1px solid #2a2a2a;
                padding-bottom: 3px;
                text-transform: uppercase;
            }
            QLabel#title {
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(15, 15, 15, 15)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("IQView")
        title.setObjectName("title")
        title_layout.addWidget(title)

        try:
            from iqview import __version__ as ver
        except Exception:
            try:
                from importlib.metadata import version
                ver = version('iqview')
            except Exception:
                ver = "0.6.0"

        self.current_version = ver
        version_lbl = QLabel(f"v{ver}")
        version_lbl.setStyleSheet("color: #888; font-size: 11px; margin-bottom: 10px; margin-left: 5px;")
        title_layout.addWidget(version_lbl, alignment=Qt.AlignmentFlag.AlignBottom)
        title_layout.addStretch()

        self.layout.addLayout(title_layout)

        # Update available label
        self.update_lbl = QLabel("")
        self.update_lbl.setStyleSheet("color: #ffaa00; font-size: 11px; font-weight: bold; margin-bottom: 5px;")
        self.update_lbl.setVisible(False)
        self.layout.addWidget(self.update_lbl)

        # --- TAB WIDGET ---
        self.tabs = QTabWidget()
        self.tabs.setObjectName("side_tabs")
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2a2a2a;
                background: #1e1e1e;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #252525;
                color: #888;
                border: 1px solid #2a2a2a;
                border-bottom: none;
                padding: 6px 12px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #1e1e1e;
                color: #00aaff;
                border-color: #2a2a2a;
            }
        """)
        self.layout.addWidget(self.tabs)

        # Tab 1: Main (Standard Settings)
        self.main_tab = QWidget()
        self.main_tab_layout = QVBoxLayout(self.main_tab)
        self.main_tab_layout.setContentsMargins(10, 10, 10, 10)
        self.main_tab_layout.setSpacing(5)
        self.main_tab_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- CORE SETTINGS ---
        core_header = QLabel("Core Settings")
        core_header.setObjectName("section_header")
        self.main_tab_layout.addWidget(core_header)

        self.main_tab_layout.addWidget(QLabel("Sample Rate (Hz)"))
        self.fs_edit = QLineEdit(str(self.fs))
        self.fs_edit.returnPressed.connect(self.on_edit_finished)
        self.main_tab_layout.addWidget(self.fs_edit)

        self.main_tab_layout.addWidget(QLabel("Center Freq (Hz)"))
        self.fc_edit = QLineEdit(str(self.fc))
        self.fc_edit.returnPressed.connect(self.on_edit_finished)
        self.main_tab_layout.addWidget(self.fc_edit)

        # --- DSP SETTINGS ---
        dsp_header = QLabel("DSP Settings")
        dsp_header.setObjectName("section_header")
        self.main_tab_layout.addWidget(dsp_header)

        self.main_tab_layout.addWidget(QLabel("FFT Size (bins)"))
        self.fft_combo = QComboBox()
        powers = [2**i for i in range(5, 17)]
        self.fft_combo.addItems([str(p) for p in powers])
        idx = self.fft_combo.findText(str(self.fft_size))
        if idx >= 0: self.fft_combo.setCurrentIndex(idx)
        self.fft_combo.currentIndexChanged.connect(self.on_fft_combo_changed)
        self.main_tab_layout.addWidget(self.fft_combo)

        self.main_tab_layout.addWidget(QLabel("Window Size (samples)"))
        self.window_size_edit = QLineEdit(str(self.window_size))
        self.window_size_edit.returnPressed.connect(self.on_window_size_edited)
        self.main_tab_layout.addWidget(self.window_size_edit)

        self.main_tab_layout.addWidget(QLabel("Overlap (%)"))
        self.overlap_edit = QLineEdit(str(self.overlap_percent))
        self.overlap_edit.returnPressed.connect(self.on_overlap_edited)
        self.main_tab_layout.addWidget(self.overlap_edit)

        self.main_tab_layout.addWidget(QLabel("Window Type"))
        self.window_type_combo = QComboBox()
        self.window_type_combo.addItems(["Hanning", "Hamming", "Blackman", "Bartlett", "Rectangular"])
        self.window_type_combo.setCurrentText(self.window_type)
        self.window_type_combo.currentIndexChanged.connect(self.on_window_type_changed)
        self.main_tab_layout.addWidget(self.window_type_combo)

        # --- DIAGNOSTICS ---
        diag_header = QLabel("Diagnostics")
        diag_header.setObjectName("section_header")
        self.main_tab_layout.addWidget(diag_header)

        self.main_tab_layout.addWidget(QLabel("Time Resolution (dt) [s]"))
        self.dt_display = QLineEdit()
        self.dt_display.setReadOnly(True)
        self.main_tab_layout.addWidget(self.dt_display)

        self.main_tab_layout.addWidget(QLabel("RBW (Hz)"))
        self.rbw_display = QLineEdit()
        self.rbw_display.setReadOnly(True)
        self.main_tab_layout.addWidget(self.rbw_display)

        # --- FILE INFORMATION ---
        file_header = QLabel("File Information")
        file_header.setObjectName("section_header")
        self.main_tab_layout.addWidget(file_header)

        self.main_tab_layout.addWidget(QLabel("File Type"))
        self.type_display = QLineEdit("N/A")
        self.type_display.setReadOnly(True)
        self.main_tab_layout.addWidget(self.type_display)

        self.main_tab_layout.addWidget(QLabel("File Size"))
        self.size_display = QLineEdit("N/A")
        self.size_display.setReadOnly(True)
        self.main_tab_layout.addWidget(self.size_display)

        # Tab 2: Multi-Row (Raster Settings)
        self.multirow_tab = QWidget()
        self.multirow_tab_layout = QVBoxLayout(self.multirow_tab)
        self.multirow_tab_layout.setContentsMargins(10, 10, 10, 10)
        self.multirow_tab_layout.setSpacing(5)
        self.multirow_tab_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Number of Rows
        self.multirow_tab_layout.addWidget(QLabel("Number of Rows"))
        self.num_rows_edit = QLineEdit("1")
        self.num_rows_edit.returnPressed.connect(self.on_multirow_edited)
        self.multirow_tab_layout.addWidget(self.num_rows_edit)

        # Start Sample
        self.multirow_tab_layout.addWidget(QLabel("Start Sample"))
        self.start_sample_edit = QLineEdit("0")
        self.start_sample_edit.returnPressed.connect(self.on_multirow_edited)
        self.multirow_tab_layout.addWidget(self.start_sample_edit)

        # Samples Per Row
        self.multirow_tab_layout.addWidget(QLabel("Samples Per Row"))
        self.samples_per_row_edit = QLineEdit("1000")
        self.samples_per_row_edit.returnPressed.connect(self.on_multirow_edited)
        self.multirow_tab_layout.addWidget(self.samples_per_row_edit)

        # Row Period (samples)
        self.multirow_tab_layout.addWidget(QLabel("Row Period (samples)"))
        self.period_edit = QLineEdit("1000")
        self.period_edit.returnPressed.connect(self.on_multirow_edited)
        self.multirow_tab_layout.addWidget(self.period_edit)

        # Frequency Limits
        self.multirow_tab_layout.addWidget(QLabel("Frequency Min"))
        self.freq_min_edit = FocusLineEdit(format_frequency)
        self.freq_min_edit.set_value(self.fc - self.fs / 2)
        self.freq_min_edit.returnPressed.connect(self.on_multirow_edited)
        self.multirow_tab_layout.addWidget(self.freq_min_edit)

        self.multirow_tab_layout.addWidget(QLabel("Frequency Max"))
        self.freq_max_edit = FocusLineEdit(format_frequency)
        self.freq_max_edit.set_value(self.fc + self.fs / 2)
        self.freq_max_edit.returnPressed.connect(self.on_multirow_edited)
        self.multirow_tab_layout.addWidget(self.freq_max_edit)

        # Add tabs
        self.tabs.addTab(self.main_tab, "Main")
        self.tabs.addTab(self.multirow_tab, "Multi-Row")

        self.layout.addStretch()

        # --- SETTINGS BUTTON ---
        self.settings_btn = QPushButton("⚙️ Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        self.layout.addWidget(self.settings_btn)

    def open_settings(self):
        if self.parent_window:
            from .settings_dialog import SettingsDialog
            dialog = SettingsDialog(self.parent_window.settings_mgr, self.parent_window)
            dialog.settingsApplied.connect(self.parent_window.on_settings_applied)
            if dialog.exec():
                # Apply changes (redundant now, but keeps the dialog.exec() logic)
                self.parent_window.apply_current_theme()
                # We could update other things here too

    def set_file_info(self, file_type, size_bytes):
        self.type_display.setText(str(file_type))
        if size_bytes is None:
            self.size_display.setText("N/A")
            return
            
        # Format size bytes to human readable
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                self.size_display.setText(f"{size_bytes:.2f} {unit}")
                break
            size_bytes /= 1024.0
        else:
            self.size_display.setText(f"{size_bytes:.2f} PB")

    def update_derived_values(self):
        # RBW = Fs / FFT
        rbw = self.fs / self.fft_size
        if rbw >= 1e6:
            self.rbw_display.setText(f"{rbw/1e6:.2f} MHz")
        elif rbw >= 1e3:
            self.rbw_display.setText(f"{rbw/1e3:.2f} kHz")
        else:
            self.rbw_display.setText(f"{rbw:.2f} Hz")
        
        # dt = step_size / Fs
        step_size = int(self.window_size * (1.0 - self.overlap_percent / 100.0))
        step_size = max(1, step_size)
        
        if self.fs == 0:
            self.dt_display.setText("inf")
        else:
            dt = step_size / self.fs
            if dt < 1e-3:
                self.dt_display.setText(f"{dt*1e6:.2f} µs")
            elif dt < 1:
                self.dt_display.setText(f"{dt*1e3:.2f} ms")
            else:
                self.dt_display.setText(f"{dt:.6f} s")

    def on_fft_combo_changed(self):
        old_fft = self.fft_size
        self.fft_size = int(self.fft_combo.currentText())
        if self.window_size == old_fft or self.window_size > self.fft_size:
            self.window_size = self.fft_size
            self.window_size_edit.setText(str(self.window_size))
        self.on_edit_finished()

    def on_window_size_edited(self):
        try:
            val = int(self.window_size_edit.text())
            if val > self.fft_size:
                val = self.fft_size
            elif val < 1:
                val = 1
            self.window_size = val
            self.window_size_edit.setText(str(self.window_size))
            self.on_edit_finished()
        except ValueError:
            self.window_size_edit.setText(str(self.window_size))
            self.update_derived_values()

    def on_window_type_changed(self):
        self.window_type = self.window_type_combo.currentText()
        self.on_edit_finished()
        
    def on_overlap_edited(self):
        try:
            self.overlap_percent = np.clip(float(self.overlap_edit.text()), 0, 99.9)
            self.overlap_edit.setText(f"{self.overlap_percent:.1f}")
            self.on_edit_finished()
        except ValueError:
            self.update_derived_values()

    def on_edit_finished(self):
        try:
            self.fs = float(self.fs_edit.text())
            self.fc = float(self.fc_edit.text())
            
            self.update_derived_values()
            
            params = {
                'fs': self.fs,
                'fc': self.fc,
                'fft_size': self.fft_size,
                'window_size': self.window_size,
                'window_type': self.window_type,
                'overlap_percent': self.overlap_percent
            }
            self.parametersChanged.emit(params)
        except ValueError:
            pass

    def update_params(self, fs=None, fc=None):
        if fs is not None:
            self.fs = fs
            self.fs_edit.setText(str(fs))
        if fc is not None:
            self.fc = fc
            self.fc_edit.setText(str(fc))
        self.update_derived_values()

    def on_multirow_edited(self):
        try:
            num_rows = int(self.num_rows_edit.text())
            if num_rows < 1:
                num_rows = 1
                self.num_rows_edit.setText("1")
            is_enabled = num_rows > 1
                
            start_sample = int(self.start_sample_edit.text())
            samples_per_row = int(self.samples_per_row_edit.text())
            period = int(self.period_edit.text())
            
            freq_min = self.freq_min_edit.raw_value
            freq_max = self.freq_max_edit.raw_value
            
            data = {
                'enabled': is_enabled,
                'num_rows': num_rows,
                'start_sample': start_sample,
                'samples_per_row': samples_per_row,
                'period': period,
                'freq_min': freq_min,
                'freq_max': freq_max
            }
            self.multirowChanged.emit(data)
        except ValueError:
            pass

    def update_multirow_fields(self, start_sample, samples_per_row, freq_min, freq_max):
        self.start_sample_edit.blockSignals(True)
        self.samples_per_row_edit.blockSignals(True)
        self.freq_min_edit.blockSignals(True)
        self.freq_max_edit.blockSignals(True)
        try:
            self.start_sample_edit.setText(str(start_sample))
            self.samples_per_row_edit.setText(str(samples_per_row))
            self.freq_min_edit.set_value(freq_min)
            self.freq_max_edit.set_value(freq_max)
        finally:
            self.start_sample_edit.blockSignals(False)
            self.samples_per_row_edit.blockSignals(False)
            self.freq_min_edit.blockSignals(False)
            self.freq_max_edit.blockSignals(False)

    def on_version_checked(self, latest_version):
        if latest_version:
            self.update_lbl.setText(f"Update available: v{latest_version}")
            self.update_lbl.setVisible(True)



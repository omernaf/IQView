from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton
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


class SidePanel(QFrame):
    parametersChanged = pyqtSignal(dict)

    def __init__(self, fs, fc, fft_size, window_type="Hamming", overlap_percent=99.0, parent_window=None):
        super().__init__()
        self.parent_window = parent_window
        self.fs = fs
        self.fc = fc
        self.fft_size = fft_size
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
            from importlib.metadata import version
            ver = version('iqview')
        except Exception:
            ver = "0.5.1"

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

        # --- CORE SETTINGS ---
        core_header = QLabel("Core Settings")
        core_header.setObjectName("section_header")
        self.layout.addWidget(core_header)

        self.layout.addWidget(QLabel("Sample Rate (Hz)"))
        self.fs_edit = QLineEdit(str(self.fs))
        self.fs_edit.returnPressed.connect(self.on_edit_finished)
        self.layout.addWidget(self.fs_edit)

        self.layout.addWidget(QLabel("Center Freq (Hz)"))
        self.fc_edit = QLineEdit(str(self.fc))
        self.fc_edit.returnPressed.connect(self.on_edit_finished)
        self.layout.addWidget(self.fc_edit)

        # --- DSP SETTINGS ---
        dsp_header = QLabel("DSP Settings")
        dsp_header.setObjectName("section_header")
        self.layout.addWidget(dsp_header)

        self.layout.addWidget(QLabel("FFT Size (bins)"))
        self.fft_combo = QComboBox()
        powers = [2**i for i in range(5, 17)]
        self.fft_combo.addItems([str(p) for p in powers])
        idx = self.fft_combo.findText(str(self.fft_size))
        if idx >= 0: self.fft_combo.setCurrentIndex(idx)
        self.fft_combo.currentIndexChanged.connect(self.on_fft_combo_changed)
        self.layout.addWidget(self.fft_combo)

        self.layout.addWidget(QLabel("Overlap (%)"))
        self.overlap_edit = QLineEdit(str(self.overlap_percent))
        self.overlap_edit.returnPressed.connect(self.on_overlap_edited)
        self.layout.addWidget(self.overlap_edit)

        self.layout.addWidget(QLabel("Window Type"))
        self.window_type_combo = QComboBox()
        self.window_type_combo.addItems(["Hanning", "Hamming", "Blackman", "Bartlett", "Rectangular"])
        self.window_type_combo.setCurrentText(self.window_type)
        self.window_type_combo.currentIndexChanged.connect(self.on_window_type_changed)
        self.layout.addWidget(self.window_type_combo)

        # --- DIAGNOSTICS ---
        diag_header = QLabel("Diagnostics")
        diag_header.setObjectName("section_header")
        self.layout.addWidget(diag_header)

        self.layout.addWidget(QLabel("Time Resolution (dt) [s]"))
        self.dt_display = QLineEdit()
        self.dt_display.setReadOnly(True)
        self.layout.addWidget(self.dt_display)

        self.layout.addWidget(QLabel("RBW (Hz)"))
        self.rbw_display = QLineEdit()
        self.rbw_display.setReadOnly(True)
        self.layout.addWidget(self.rbw_display)

        # --- FILE INFORMATION ---
        file_header = QLabel("File Information")
        file_header.setObjectName("section_header")
        self.layout.addWidget(file_header)

        self.layout.addWidget(QLabel("File Type"))
        self.type_display = QLineEdit("N/A")
        self.type_display.setReadOnly(True)
        self.layout.addWidget(self.type_display)

        self.layout.addWidget(QLabel("File Size"))
        self.size_display = QLineEdit("N/A")
        self.size_display.setReadOnly(True)
        self.layout.addWidget(self.size_display)

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
        step_size = int(self.fft_size * (1.0 - self.overlap_percent / 100.0))
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
        self.fft_size = int(self.fft_combo.currentText())
        self.on_edit_finished()

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
            # self.fft_size already updated by combo change or rbw logic
            
            self.update_derived_values()
            
            params = {
                'fs': self.fs,
                'fc': self.fc,
                'fft_size': self.fft_size,
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

    def on_version_checked(self, latest_version):
        if latest_version:
            self.update_lbl.setText(f"Update available: v{latest_version}")
            self.update_lbl.setVisible(True)



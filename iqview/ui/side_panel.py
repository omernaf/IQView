from PyQt6.QtWidgets import (QFrame, QGridLayout, QLabel, QLineEdit, QVBoxLayout,
                              QHBoxLayout, QComboBox, QPushButton, QTabWidget,
                              QWidget, QScrollArea)
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


class FocusLineEdit(QLineEdit):
    """A QLineEdit that shows a formatted string when unfocused and raw Hz when focused.

    Used for frequency inputs: displays e.g. '433.920000 MHz' when unfocused,
    but switches to the raw numeric value in Hz when the user clicks into it.
    """
    def __init__(self, raw_value=0.0, parent=None):
        super().__init__(parent)
        self._raw_value = float(raw_value)
        self._update_display()

    @property
    def raw_value(self):
        return self._raw_value

    @raw_value.setter
    def raw_value(self, v):
        self._raw_value = float(v)
        if not self.hasFocus():
            self._update_display()

    def focusInEvent(self, event):
        """Switch to raw numeric text for editing."""
        super().focusInEvent(event)
        self.setText(str(self._raw_value))
        self.selectAll()

    def focusOutEvent(self, event):
        """Parse the edited text and switch back to formatted display."""
        super().focusOutEvent(event)
        try:
            self._raw_value = float(self.text())
        except ValueError:
            pass  # Keep old value
        self._update_display()

    def _update_display(self):
        """Show value with appropriate unit suffix."""
        v = abs(self._raw_value)
        if v >= 1e9:
            self.setText(f"{self._raw_value/1e9:.6f} GHz")
        elif v >= 1e6:
            self.setText(f"{self._raw_value/1e6:.6f} MHz")
        elif v >= 1e3:
            self.setText(f"{self._raw_value/1e3:.3f} kHz")
        else:
            self.setText(f"{self._raw_value:.2f} Hz")


class SidePanel(QFrame):
    parametersChanged = pyqtSignal(dict)
    multirowChanged = pyqtSignal()  # Emitted when any multi-row control changes

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

        # ============================================================
        # Tab Widget
        # ============================================================
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 4px 12px; font-size: 11px; }
        """)
        self.layout.addWidget(self.tab_widget)

        # ---- Tab 1: Main ----
        self._build_main_tab()

        # ---- Tab 2: Multi-Row ----
        self._build_multirow_tab()

        # ============================================================
        # Settings Button — always visible, outside tabs
        # ============================================================
        self.layout.addStretch()
        self.settings_btn = QPushButton("⚙️ Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        self.layout.addWidget(self.settings_btn)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_main_tab(self):
        """Build the Main tab containing Core, DSP, Diagnostics, File Info."""
        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main_scroll.setFrameShape(QFrame.Shape.NoFrame)

        main_widget = QWidget()
        ml = QVBoxLayout(main_widget)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(2)
        ml.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- CORE SETTINGS ---
        core_header = QLabel("Core Settings")
        core_header.setObjectName("section_header")
        ml.addWidget(core_header)

        ml.addWidget(QLabel("Sample Rate (Hz)"))
        self.fs_edit = QLineEdit(str(self.fs))
        self.fs_edit.returnPressed.connect(self.on_edit_finished)
        ml.addWidget(self.fs_edit)

        ml.addWidget(QLabel("Center Freq (Hz)"))
        self.fc_edit = QLineEdit(str(self.fc))
        self.fc_edit.returnPressed.connect(self.on_edit_finished)
        ml.addWidget(self.fc_edit)

        # --- DSP SETTINGS ---
        dsp_header = QLabel("DSP Settings")
        dsp_header.setObjectName("section_header")
        ml.addWidget(dsp_header)

        ml.addWidget(QLabel("FFT Size (bins)"))
        self.fft_combo = QComboBox()
        powers = [2**i for i in range(5, 17)]
        self.fft_combo.addItems([str(p) for p in powers])
        idx = self.fft_combo.findText(str(self.fft_size))
        if idx >= 0: self.fft_combo.setCurrentIndex(idx)
        self.fft_combo.currentIndexChanged.connect(self.on_fft_combo_changed)
        ml.addWidget(self.fft_combo)

        ml.addWidget(QLabel("Window Size (samples)"))
        self.window_size_edit = QLineEdit(str(self.window_size))
        self.window_size_edit.returnPressed.connect(self.on_window_size_edited)
        ml.addWidget(self.window_size_edit)

        ml.addWidget(QLabel("Overlap (%)"))
        self.overlap_edit = QLineEdit(str(self.overlap_percent))
        self.overlap_edit.returnPressed.connect(self.on_overlap_edited)
        ml.addWidget(self.overlap_edit)

        ml.addWidget(QLabel("Window Type"))
        self.window_type_combo = QComboBox()
        self.window_type_combo.addItems(["Hanning", "Hamming", "Blackman", "Bartlett", "Rectangular"])
        self.window_type_combo.setCurrentText(self.window_type)
        self.window_type_combo.currentIndexChanged.connect(self.on_window_type_changed)
        ml.addWidget(self.window_type_combo)

        # --- DIAGNOSTICS ---
        diag_header = QLabel("Diagnostics")
        diag_header.setObjectName("section_header")
        ml.addWidget(diag_header)

        ml.addWidget(QLabel("Time Resolution (dt) [s]"))
        self.dt_display = QLineEdit()
        self.dt_display.setReadOnly(True)
        ml.addWidget(self.dt_display)

        ml.addWidget(QLabel("RBW (Hz)"))
        self.rbw_display = QLineEdit()
        self.rbw_display.setReadOnly(True)
        ml.addWidget(self.rbw_display)

        # --- FILE INFORMATION ---
        file_header = QLabel("File Information")
        file_header.setObjectName("section_header")
        ml.addWidget(file_header)

        ml.addWidget(QLabel("File Type"))
        self.type_display = QLineEdit("N/A")
        self.type_display.setReadOnly(True)
        ml.addWidget(self.type_display)

        ml.addWidget(QLabel("File Size"))
        self.size_display = QLineEdit("N/A")
        self.size_display.setReadOnly(True)
        ml.addWidget(self.size_display)

        ml.addStretch()
        main_scroll.setWidget(main_widget)
        self.tab_widget.addTab(main_scroll, "Main")

    def _build_multirow_tab(self):
        """Build the Multi-Row tab with row configuration and frequency controls."""
        mr_scroll = QScrollArea()
        mr_scroll.setWidgetResizable(True)
        mr_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        mr_scroll.setFrameShape(QFrame.Shape.NoFrame)

        mr_widget = QWidget()
        ml = QVBoxLayout(mr_widget)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(2)
        ml.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- ROW CONFIGURATION ---
        row_header = QLabel("Row Configuration")
        row_header.setObjectName("section_header")
        ml.addWidget(row_header)

        ml.addWidget(QLabel("Number of Rows"))
        self.num_rows_edit = QLineEdit("1")
        self.num_rows_edit.setToolTip("Set to >1 to activate multi-row split view")
        self.num_rows_edit.returnPressed.connect(self._on_multirow_input_changed)
        ml.addWidget(self.num_rows_edit)

        ml.addWidget(QLabel("Start Sample"))
        self.start_sample_edit = QLineEdit("0")
        self.start_sample_edit.returnPressed.connect(self._on_multirow_input_changed)
        ml.addWidget(self.start_sample_edit)

        ml.addWidget(QLabel("Samples Per Row"))
        self.samples_per_row_edit = QLineEdit("0")
        self.samples_per_row_edit.returnPressed.connect(self._on_multirow_input_changed)
        ml.addWidget(self.samples_per_row_edit)

        ml.addWidget(QLabel("Row Period (samples)"))
        self.period_edit = QLineEdit("0")
        self.period_edit.setToolTip("Interval between the start of consecutive rows")
        self.period_edit.returnPressed.connect(self._on_multirow_input_changed)
        ml.addWidget(self.period_edit)

        # --- FREQUENCY LIMITS ---
        freq_header = QLabel("Frequency Limits")
        freq_header.setObjectName("section_header")
        ml.addWidget(freq_header)

        ml.addWidget(QLabel("Freq Min"))
        self.freq_min_edit = FocusLineEdit(0.0)
        self.freq_min_edit.returnPressed.connect(self._on_multirow_input_changed)
        ml.addWidget(self.freq_min_edit)

        ml.addWidget(QLabel("Freq Max"))
        self.freq_max_edit = FocusLineEdit(0.0)
        self.freq_max_edit.returnPressed.connect(self._on_multirow_input_changed)
        ml.addWidget(self.freq_max_edit)

        ml.addStretch()
        mr_scroll.setWidget(mr_widget)
        self.multirow_tab = mr_scroll
        self.tab_widget.addTab(mr_scroll, "Multi-Row")

    # ------------------------------------------------------------------
    # Multi-row helpers
    # ------------------------------------------------------------------

    def get_num_rows(self):
        """Return the current number-of-rows value (min 1)."""
        try:
            return max(1, int(self.num_rows_edit.text()))
        except ValueError:
            return 1

    def get_multirow_params(self):
        """Return a dict of the current multi-row control values."""
        try:
            num_rows = max(1, int(self.num_rows_edit.text()))
        except ValueError:
            num_rows = 1
        try:
            start_sample = int(float(self.start_sample_edit.text()))
        except ValueError:
            start_sample = 0
        try:
            samples_per_row = int(float(self.samples_per_row_edit.text()))
        except ValueError:
            samples_per_row = 0
        try:
            period = int(float(self.period_edit.text()))
        except ValueError:
            period = 0

        return {
            'num_rows': num_rows,
            'start_sample': start_sample,
            'samples_per_row': samples_per_row,
            'period': period,
            'freq_min': self.freq_min_edit.raw_value,
            'freq_max': self.freq_max_edit.raw_value,
        }

    def set_multirow_defaults(self, total_samples, fs, fc):
        """Set sensible defaults for multi-row controls based on file parameters."""
        num_rows = self.get_num_rows()
        if num_rows <= 1:
            num_rows = 1
        samples_per_row = total_samples // max(num_rows, 1)
        period = samples_per_row

        self.start_sample_edit.setText("0")
        self.samples_per_row_edit.setText(str(samples_per_row))
        self.period_edit.setText(str(period))
        self.freq_min_edit.raw_value = fc - fs / 2
        self.freq_max_edit.raw_value = fc + fs / 2

    def _on_multirow_input_changed(self):
        """Called when any multi-row input is committed."""
        # Parse freq edits on return press
        try:
            self.freq_min_edit._raw_value = float(self.freq_min_edit.text())
        except ValueError:
            pass
        try:
            self.freq_max_edit._raw_value = float(self.freq_max_edit.text())
        except ValueError:
            pass
        self.multirowChanged.emit()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

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

    def on_version_checked(self, latest_version):
        if latest_version:
            self.update_lbl.setText(f"Update available: v{latest_version}")
            self.update_lbl.setVisible(True)



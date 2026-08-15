from PyQt6.QtWidgets import (QFrame, QGridLayout, QLabel, QLineEdit,
                              QVBoxLayout, QHBoxLayout, QComboBox,
                              QPushButton, QTabWidget, QWidget, QCheckBox)
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


class FocusLineEdit(QLineEdit):
    """QLineEdit that displays a formatted string with units when unfocused
    and the raw Hz value when focused (for easy editing).

    Supports scientific notation such as ``1e5`` and unit suffixes such as
    ``433.92 MHz`` during input.
    """

    def __init__(self, default_hz=0.0, parent=None):
        super().__init__(parent)
        self._raw_hz = float(default_hz)
        self._refresh_display()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_hz(hz):
        """Format a Hz value with an appropriate unit suffix."""
        a = abs(hz)
        if a >= 1e9:
            return f"{hz / 1e9:.6f} GHz"
        if a >= 1e6:
            return f"{hz / 1e6:.6f} MHz"
        if a >= 1e3:
            return f"{hz / 1e3:.6f} kHz"
        return f"{hz:.2f} Hz"

    @staticmethod
    def _parse_hz(text):
        """Parse a frequency string (scientific notation or with units)."""
        text = text.strip()
        # Plain float / scientific notation ("1e5", "433920000")
        try:
            return float(text)
        except ValueError:
            pass
        # With unit suffix ("433.92 MHz", "100 kHz", "2.4 GHz")
        m = re.match(
            r'^\s*([0-9.eE+\-]+)\s*(GHz|MHz|kHz|Hz)?\s*$', text, re.IGNORECASE
        )
        if m:
            num  = float(m.group(1))
            unit = (m.group(2) or 'Hz').lower()
            mult = {'ghz': 1e9, 'mhz': 1e6, 'khz': 1e3, 'hz': 1.0}
            return num * mult.get(unit, 1.0)
        raise ValueError(f"Cannot parse frequency: {text!r}")

    def _refresh_display(self):
        self.setText(self._format_hz(self._raw_hz))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_hz(self):
        """Return the current frequency in Hz."""
        return self._raw_hz

    def set_hz(self, hz):
        """Set the frequency value (Hz); updates display if not focused."""
        self._raw_hz = float(hz)
        if not self.hasFocus():
            self._refresh_display()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def focusInEvent(self, event):
        super().focusInEvent(event)
        # Show raw value for editing
        self.setText(f"{self._raw_hz:g}")
        self.selectAll()

    def focusOutEvent(self, event):
        old_hz = self._raw_hz
        try:
            self._raw_hz = self._parse_hz(self.text())
        except ValueError:
            pass  # keep previous value
        self._refresh_display()
        super().focusOutEvent(event)
        if self._raw_hz != old_hz:
            self.editingFinished.emit()


# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------


class SidePanel(QFrame):
    parametersChanged = pyqtSignal(dict)
    multirowChanged   = pyqtSignal(dict)

    def __init__(self, fs, fc, fft_size, window_type="Hamming",
                 overlap_percent=99.0, window_size=None, parent_window=None):
        super().__init__()
        self.parent_window   = parent_window
        self.fs              = fs
        self.fc              = fc
        self.fft_size        = fft_size
        self.window_size     = window_size if window_size is not None else fft_size
        self.window_type     = window_type
        self.overlap_percent = overlap_percent
        
        self.setup_ui()
        self.update_derived_values()
        
        # Start background version checker
        self.checker = VersionChecker(self.current_version)
        self.checker.version_checked.connect(self.on_version_checked)
        self.checker.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def setup_ui(self):
        self.setFixedWidth(240)
        # Base style handled by main stylesheet; keep sidebar-specific borders
        self.setStyleSheet("""
            SidePanel { 
                border-right: 1px solid #2a2a2a;
            }
            QLabel#section_header {
                color: #00aaff;
                font-size: 11px;
                font-weight: bold;
                margin-top: 12px;
                margin-bottom: 4px;
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
        
        # Root layout for the whole sidebar frame
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(15, 15, 10, 10)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ---- Title row (outside tabs) ----
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
                ver = "0.6.2"

        self.current_version = ver
        version_lbl = QLabel(f"v{ver}")
        version_lbl.setStyleSheet(
            "color: #888; font-size: 11px; margin-bottom: 10px; margin-left: 5px;"
        )
        title_layout.addWidget(version_lbl,
                               alignment=Qt.AlignmentFlag.AlignBottom)
        title_layout.addStretch()
        self.layout.addLayout(title_layout)

        # Update-available label (outside tabs)
        self.update_lbl = QLabel("")
        self.update_lbl.setStyleSheet(
            "color: #ffaa00; font-size: 11px; font-weight: bold; margin-bottom: 5px;"
        )
        self.update_lbl.setVisible(False)
        self.layout.addWidget(self.update_lbl)

        # ---- Tab widget ----
        self.tab_widget = QTabWidget()
        self.layout.addWidget(self.tab_widget)

        # -- Tab 1: Main --
        self._build_main_tab()

        # -- Tab 2: Multi-Row --
        self._build_multirow_tab()

        # ---- Settings button (outside tabs, always visible) ----
        self.settings_btn = QPushButton("⚙️ Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        self.layout.addWidget(self.settings_btn)

    def _add_section_header(self, parent_layout, text):
        """Helper: add a styled section header label to *parent_layout*."""
        header = QLabel(text)
        header.setObjectName("section_header")
        parent_layout.addWidget(header)

    # -- Tab 1 --

    def _build_main_tab(self):
        tab = QWidget()
        lyt = QVBoxLayout(tab)
        lyt.setContentsMargins(0, 8, 0, 0)
        lyt.setSpacing(2)
        lyt.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- CORE SETTINGS ---
        self._add_section_header(lyt, "Core Settings")

        lyt.addWidget(QLabel("Sample Rate (Hz)"))
        self.fs_edit = QLineEdit(str(self.fs))
        self.fs_edit.returnPressed.connect(self.on_edit_finished)
        lyt.addWidget(self.fs_edit)

        lyt.addWidget(QLabel("Center Freq (Hz)"))
        self.fc_edit = QLineEdit(str(self.fc))
        self.fc_edit.returnPressed.connect(self.on_edit_finished)
        lyt.addWidget(self.fc_edit)

        # --- DSP SETTINGS ---
        self._add_section_header(lyt, "DSP Settings")

        lyt.addWidget(QLabel("FFT Size (bins)"))
        self.fft_combo = QComboBox()
        powers = [2**i for i in range(5, 17)]
        self.fft_combo.addItems([str(p) for p in powers])
        idx = self.fft_combo.findText(str(self.fft_size))
        if idx >= 0:
            self.fft_combo.setCurrentIndex(idx)
        self.fft_combo.currentIndexChanged.connect(self.on_fft_combo_changed)
        lyt.addWidget(self.fft_combo)

        lyt.addWidget(QLabel("Window Size (samples)"))
        self.window_size_edit = QLineEdit(str(self.window_size))
        self.window_size_edit.returnPressed.connect(self.on_window_size_edited)
        lyt.addWidget(self.window_size_edit)

        lyt.addWidget(QLabel("Overlap (%)"))
        self.overlap_edit = QLineEdit(str(self.overlap_percent))
        self.overlap_edit.returnPressed.connect(self.on_overlap_edited)
        lyt.addWidget(self.overlap_edit)

        lyt.addWidget(QLabel("Window Type"))
        self.window_type_combo = QComboBox()
        self.window_type_combo.addItems(
            ["Hanning", "Hamming", "Blackman", "Bartlett", "Rectangular"]
        )
        self.window_type_combo.setCurrentText(self.window_type)
        self.window_type_combo.currentIndexChanged.connect(
            self.on_window_type_changed
        )
        lyt.addWidget(self.window_type_combo)

        # --- DIAGNOSTICS ---
        self._add_section_header(lyt, "Diagnostics")

        lyt.addWidget(QLabel("Time Resolution (dt) [s]"))
        self.dt_display = QLineEdit()
        self.dt_display.setReadOnly(True)
        lyt.addWidget(self.dt_display)

        lyt.addWidget(QLabel("RBW (Hz)"))
        self.rbw_display = QLineEdit()
        self.rbw_display.setReadOnly(True)
        lyt.addWidget(self.rbw_display)

        # --- FILE INFORMATION ---
        self._add_section_header(lyt, "File Information")

        lyt.addWidget(QLabel("File Type"))
        self.type_display = QLineEdit("N/A")
        self.type_display.setReadOnly(True)
        lyt.addWidget(self.type_display)

        lyt.addWidget(QLabel("File Size"))
        self.size_display = QLineEdit("N/A")
        self.size_display.setReadOnly(True)
        lyt.addWidget(self.size_display)

        lyt.addStretch()
        self.tab_widget.addTab(tab, "Main")

    # -- Tab 2 --

    def _build_multirow_tab(self):
        tab = QWidget()
        lyt = QVBoxLayout(tab)
        lyt.setContentsMargins(0, 8, 0, 0)
        lyt.setSpacing(2)
        lyt.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- SPECTROGRAM SETTINGS ---
        self._add_section_header(lyt, "Spectrogram Settings")

        self.waterfall_cb = QCheckBox("Waterfall Mode")
        self.waterfall_cb.setToolTip("Toggle Waterfall Orientation for the current session (Freq → X, Time → Y)")
        self.waterfall_cb.toggled.connect(self.on_waterfall_toggled)
        lyt.addWidget(self.waterfall_cb)

        lyt.addWidget(QLabel("Number of Rows"))
        self.num_rows_edit = QLineEdit("1")
        self.num_rows_edit.editingFinished.connect(self.on_multirow_edit_finished)
        lyt.addWidget(self.num_rows_edit)

        lyt.addWidget(QLabel("Start Sample"))
        self.start_sample_edit = QLineEdit("0")
        self.start_sample_edit.editingFinished.connect(
            self.on_multirow_edit_finished
        )
        lyt.addWidget(self.start_sample_edit)

        lyt.addWidget(QLabel("Samples Per Row"))
        self.samples_per_row_edit = QLineEdit("0")
        self.samples_per_row_edit.editingFinished.connect(
            self.on_multirow_edit_finished
        )
        lyt.addWidget(self.samples_per_row_edit)

        lyt.addWidget(QLabel("Row Period (samples)"))
        self.period_edit = QLineEdit("0")
        self.period_edit.editingFinished.connect(self.on_multirow_edit_finished)
        lyt.addWidget(self.period_edit)

        # --- FREQUENCY RANGE ---
        self._add_section_header(lyt, "Frequency Range")

        lyt.addWidget(QLabel("Freq Max"))
        self.freq_max_edit = FocusLineEdit(
            default_hz=self.fc + self.fs / 2.0
        )
        self.freq_max_edit.editingFinished.connect(self.on_multirow_edit_finished)
        lyt.addWidget(self.freq_max_edit)

        lyt.addWidget(QLabel("Freq Min"))
        self.freq_min_edit = FocusLineEdit(
            default_hz=self.fc - self.fs / 2.0
        )
        self.freq_min_edit.editingFinished.connect(self.on_multirow_edit_finished)
        lyt.addWidget(self.freq_min_edit)

        tip = QLabel(
            "Press Enter in any field to\n"
            "update view range & zoom.\n"
            "Set Rows > 1 for multi-row."
        )
        tip.setStyleSheet("color: #666; font-size: 10px; margin-top: 8px;")
        lyt.addWidget(tip)

        lyt.addStretch()
        self.tab_widget.addTab(tab, "Spectrogram\nSettings")

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def open_settings(self):
        if self.parent_window:
            from .settings_dialog import SettingsDialog
            dialog = SettingsDialog(self.parent_window.settings_mgr,
                                    self.parent_window)
            dialog.settingsApplied.connect(
                self.parent_window.on_settings_applied
            )
            if dialog.exec():
                self.parent_window.apply_current_theme()

    # ------------------------------------------------------------------
    # File info
    # ------------------------------------------------------------------

    def set_file_info(self, file_type, size_bytes):
        self.type_display.setText(str(file_type))
        if size_bytes is None:
            self.size_display.setText("N/A")
            return
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                self.size_display.setText(f"{size_bytes:.2f} {unit}")
                break
            size_bytes /= 1024.0
        else:
            self.size_display.setText(f"{size_bytes:.2f} PB")

    # ------------------------------------------------------------------
    # Derived-values display
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Parameter slots (Main tab)
    # ------------------------------------------------------------------

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
            self.overlap_percent = np.clip(
                float(self.overlap_edit.text()), 0, 99.9
            )
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

    # ------------------------------------------------------------------
    # Multi-row slots (Multi-Row tab)
    # ------------------------------------------------------------------

    def on_multirow_edit_finished(self):
        """Collect multi-row parameters and emit multirowChanged."""
        try:
            num_rows = max(1, int(float(self.num_rows_edit.text())))
            self.num_rows_edit.setText(str(num_rows))
        except ValueError:
            return

        try:
            start_sample = max(0, int(float(self.start_sample_edit.text())))
        except ValueError:
            start_sample = 0

        try:
            spr = max(0, int(float(self.samples_per_row_edit.text())))
        except ValueError:
            spr = 0

        try:
            period = max(0, int(float(self.period_edit.text())))
        except ValueError:
            period = 0

        self.multirowChanged.emit({
            'num_rows':        num_rows,
            'start_sample':    start_sample,
            'samples_per_row': spr,
            'period':          period,
            'freq_min':        self.freq_min_edit.get_hz(),
            'freq_max':        self.freq_max_edit.get_hz(),
        })

    # ------------------------------------------------------------------
    # External update helpers
    # ------------------------------------------------------------------

    def update_params(self, fs=None, fc=None):
        """Called by the main window when fs/fc are detected from filename."""
        if fs is not None:
            self.fs = fs
            self.fs_edit.setText(str(fs))
        if fc is not None:
            self.fc = fc
            self.fc_edit.setText(str(fc))
        if hasattr(self, 'freq_min_edit') and hasattr(self, 'freq_max_edit'):
            self.freq_min_edit.set_hz(self.fc - self.fs / 2.0)
            self.freq_max_edit.set_hz(self.fc + self.fs / 2.0)
        self.update_derived_values()

    def update_multirow_defaults(self, samples_per_row, period, start_sample=None):
        """Push auto-computed defaults into the multi-row tab inputs."""
        self.samples_per_row_edit.setText(str(samples_per_row))
        self.period_edit.setText(str(period))
        if start_sample is not None and hasattr(self, 'start_sample_edit'):
            self.start_sample_edit.setText(str(start_sample))

    def on_waterfall_toggled(self, checked):
        """Slot when the user toggles Waterfall Mode in the Spectrogram Settings tab."""
        if self.parent_window and hasattr(self.parent_window, 'spectrogram_view'):
            if self.parent_window.spectrogram_view.is_waterfall != checked:
                self.parent_window.spectrogram_view.set_waterfall_mode(checked)

    def update_waterfall_checkbox(self):
        """Sync checkbox state with active spectrogram view orientation."""
        if hasattr(self, 'waterfall_cb') and self.parent_window and hasattr(self.parent_window, 'spectrogram_view'):
            self.waterfall_cb.blockSignals(True)
            self.waterfall_cb.setChecked(self.parent_window.spectrogram_view.is_waterfall)
            self.waterfall_cb.blockSignals(False)

    # ------------------------------------------------------------------
    # Version checker
    # ------------------------------------------------------------------

    def on_version_checked(self, latest_version):
        if latest_version:
            self.update_lbl.setText(f"Update available: v{latest_version}")
            self.update_lbl.setVisible(True)

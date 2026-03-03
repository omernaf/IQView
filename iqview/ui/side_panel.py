from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QVBoxLayout, QComboBox
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont
import numpy as np

class SidePanel(QFrame):
    parametersChanged = pyqtSignal(dict)

    def __init__(self, fs, fc, fft_size):
        super().__init__()
        self.fs = fs
        self.fc = fc
        self.fft_size = fft_size
        self.window_type = "Hanning"
        self.overlap_percent = 99.0 # Default
        
        self.setup_ui()
        self.update_derived_values()

    def setup_ui(self):
        self.setFixedWidth(240)
        self.setStyleSheet("""
            QFrame { 
                background-color: #1a1a1a; 
                border-right: 1px solid #2a2a2a;
                padding: 15px;
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
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(15, 15, 15, 15)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("IQView")
        title.setObjectName("title")
        self.layout.addWidget(title)

        # --- CORE SETTINGS ---
        core_header = QLabel("⚙️ Core Settings")
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
        dsp_header = QLabel("📡 DSP Settings")
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
        diag_header = QLabel("🔍 Diagnostics")
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

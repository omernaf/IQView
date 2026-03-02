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
        self.setFixedWidth(250)
        self.setStyleSheet("""
            QFrame { 
                background-color: #252525; 
                border-right: 1px solid #444;
                padding: 10px;
            }
            QLabel { 
                color: #AAA; 
                font-size: 10px;
                text-transform: uppercase;
                font-weight: bold;
            }
            QLineEdit, QComboBox {
                background-color: #111;
                color: #FFF;
                border: 1px solid #555;
                padding: 5px;
                border-radius: 4px;
                font-family: 'Courier New';
                font-size: 13px;
                margin-bottom: 15px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #111;
                color: #FFF;
                selection-background-color: #444;
                border: 1px solid #555;
            }
        """)
        
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Signal Parameters")
        title.setStyleSheet("color: #FFF; font-size: 14px; margin-bottom: 15px;")
        self.layout.addWidget(title)

        # Sampling Rate
        self.layout.addWidget(QLabel("Sample Rate (Hz)"))
        self.fs_edit = QLineEdit(str(self.fs))
        self.fs_edit.returnPressed.connect(self.on_edit_finished)
        self.layout.addWidget(self.fs_edit)

        # Center Freq
        self.layout.addWidget(QLabel("Center Freq (Hz)"))
        self.fc_edit = QLineEdit(str(self.fc))
        self.fc_edit.returnPressed.connect(self.on_edit_finished)
        self.layout.addWidget(self.fc_edit)

        # Overlap
        self.layout.addWidget(QLabel("Overlap (%)"))
        self.overlap_edit = QLineEdit(str(self.overlap_percent))
        self.overlap_edit.returnPressed.connect(self.on_overlap_edited)
        self.layout.addWidget(self.overlap_edit)

        # FFT Size (ComboBox)
        self.layout.addWidget(QLabel("FFT Size (bins)"))
        self.fft_combo = QComboBox()
        powers = [2**i for i in range(5, 17)] # 32 to 65536
        self.fft_combo.addItems([str(p) for p in powers])
        
        # Select current fft_size if it exists in list
        idx = self.fft_combo.findText(str(self.fft_size))
        if idx >= 0:
            self.fft_combo.setCurrentIndex(idx)
            
        self.fft_combo.currentIndexChanged.connect(self.on_fft_combo_changed)
        self.layout.addWidget(self.fft_combo)

        # Window Type
        self.window_type_combo = QComboBox()
        self.window_type_combo.addItems(["Hanning", "Hamming", "Blackman", "Bartlett", "Rectangular"])
        self.window_type_combo.setCurrentText(self.window_type)
        self.window_type_combo.currentIndexChanged.connect(self.on_window_type_changed)
        self.layout.addWidget(QLabel("Window Type"))
        self.layout.addWidget(self.window_type_combo)

        # Time Resolution (dt)
        self.layout.addWidget(QLabel("Time Resolution (dt) [s]"))
        self.dt_display = QLineEdit()
        self.dt_display.setReadOnly(True)
        self.dt_display.setStyleSheet("color: #888; background-color: #0c0c0c;")
        self.layout.addWidget(self.dt_display)

        # RBW (Resolution BW) - Read Only
        self.layout.addWidget(QLabel("RBW (Hz) - Resolution BW"))
        self.rbw_display = QLineEdit()
        self.rbw_display.setReadOnly(True)
        self.rbw_display.setStyleSheet("color: #888; background-color: #0c0c0c;")
        self.layout.addWidget(self.rbw_display)

    def update_derived_values(self):
        # RBW = Fs / FFT
        rbw = self.fs / self.fft_size
        self.rbw_display.setText(f"{rbw:.2f}")
        
        # dt = step_size / Fs
        step_size = int(self.fft_size * (1.0 - self.overlap_percent / 100.0))
        step_size = max(1, step_size)
        dt = step_size / self.fs
        self.dt_display.setText(f"{dt:.6f}")

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

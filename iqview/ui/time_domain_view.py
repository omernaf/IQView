import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLabel, QFrame)
from PyQt6.QtCore import Qt

class TimeDomainView(QWidget):
    """
    A detailed view of a signal segment in the time domain.
    Supports Real, Imag, Magnitude, and Instantaneous Frequency plots.
    """
    def __init__(self, samples, start_time, sample_rate, parent=None):
        super().__init__(parent)
        self.samples = samples # Complex numpy array
        self.start_time = start_time
        self.rate = sample_rate
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        
        # --- Toolbar ---
        self.toolbar = QFrame()
        self.toolbar.setObjectName("td_toolbar")
        self.toolbar.setStyleSheet("""
            QFrame#td_toolbar { background-color: #1a1a1a; border-radius: 6px; border: 1px solid #333; }
            QPushButton { background-color: #252525; padding: 5px 15px; border-radius: 3px; }
            QPushButton:checked { background-color: #004488; color: #00aaff; border: 1px solid #00aaff; }
        """)
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.toolbar_layout.addWidget(QLabel("Plot Mode:"))
        
        self.mode_group = QButtonGroup(self)
        self.modes = [
            ("Real (I)", self.plot_real),
            ("Imag (Q)", self.plot_imag),
            ("Absolute", self.plot_abs),
            ("Inst. Freq", self.plot_inst_freq)
        ]
        
        for i, (name, callback) in enumerate(self.modes):
            btn = QPushButton(name)
            btn.setCheckable(True)
            self.mode_group.addButton(btn, i)
            self.toolbar_layout.addWidget(btn)
            btn.clicked.connect(callback)
            if i == 0: btn.setChecked(True)
            
        self.toolbar_layout.addStretch()
        
        # Range Info
        end_time = start_time + len(samples) / sample_rate
        range_label = QLabel(f"Range: {start_time:,.6f} to {end_time:,.6f} sec ({len(samples):,} samples)")
        range_label.setStyleSheet("color: #888; font-family: Consolas; font-size: 11px;")
        self.toolbar_layout.addWidget(range_label)
        
        self.layout.addWidget(self.toolbar)
        
        # --- Plot ---
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#121212')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.getAxis('bottom').setLabel('Time', units='s')
        self.plot_widget.getAxis('left').setPen('#666')
        self.plot_widget.getAxis('bottom').setPen('#666')
        self.layout.addWidget(self.plot_widget)
        
        self.time_axis = np.linspace(start_time, end_time, len(samples))
        self.plot_real() # Default plot

    def plot_real(self):
        self._update_plot(self.samples.real, "Amplitude (Real)")

    def plot_imag(self):
        self._update_plot(self.samples.imag, "Amplitude (Imag)")

    def plot_abs(self):
        self._update_plot(np.abs(self.samples), "Magnitude")

    def plot_inst_freq(self):
        # Phase difference between samples
        phase = np.unwrap(np.angle(self.samples))
        freq = np.diff(phase) / (2 * np.pi) * self.rate
        # Frequency has one less sample than time_axis
        self._update_plot(freq, "Instantaneous Frequency (Hz)", use_diff_time=True)

    def _update_plot(self, data, y_label, use_diff_time=False):
        self.plot_widget.clear()
        self.plot_widget.getAxis('left').setLabel(y_label)
        
        x_data = self.time_axis
        if use_diff_time:
            # Shift time axis slightly to center the frequency estimate between samples
            x_data = (self.time_axis[:-1] + self.time_axis[1:]) / 2
            
        pen = pg.mkPen('#00aaff', width=1.5)
        self.plot_widget.plot(x_data, data, pen=pen)
        self.plot_widget.autoRange()

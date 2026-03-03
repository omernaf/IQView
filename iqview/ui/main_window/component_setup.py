from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QProgressBar, QLabel
from PyQt6.QtCore import Qt, QTimer
from ..marker_panel import MarkerPanel
from ..spectrogram_view import SpectrogramView
from ..side_panel import SidePanel

class UIComponentsMixin:
    def setup_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget#central { background-color: #121212; color: #e0e0e0; font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif; }
            QLabel { color: #aaaaaa; }
            QPushButton { background-color: #2a2a2a; color: #ffffff; border: 1px solid #3d3d3d; border-radius: 4px; padding: 6px 12px; font-size: 13px; }
            QPushButton:hover { background-color: #353535; border-color: #555555; }
            QPushButton:pressed { background-color: #1a1a1a; }
            QPushButton:checked { background-color: #004488; border-color: #00aaff; color: #00aaff; }
            QLineEdit { background-color: #1a1a1a; color: #ffffff; border: 1px solid #3d3d3d; border-radius: 4px; padding: 4px 8px; selection-background-color: #00aaff; }
            QLineEdit:focus { border-color: #00aaff; }
            QLineEdit[readOnly="true"] { color: #777777; background-color: #151515; }
            QComboBox { background-color: #1a1a1a; color: #ffffff; border: 1px solid #3d3d3d; border-radius: 4px; padding: 4px 8px; }
            QComboBox:on { border-color: #00aaff; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView { background-color: #1a1a1a; color: #ffffff; selection-background-color: #333333; border: 1px solid #3d3d3d; outline: none; }
        """)
        self.central_widget = QWidget()
        self.central_widget.setObjectName("central")
        self.setCentralWidget(self.central_widget)
        self.main_h_layout = QHBoxLayout(self.central_widget)
        self.main_h_layout.setContentsMargins(0, 0, 0, 0)
        self.main_h_layout.setSpacing(0)
        self.sidebar = SidePanel(self.rate, self.fc, self.fft_size)
        self.sidebar.parametersChanged.connect(self.on_parameters_changed)
        self.main_h_layout.addWidget(self.sidebar)
        self.main_v_container = QWidget()
        self.v_layout = QVBoxLayout(self.main_v_container)
        self.v_layout.setContentsMargins(0, 0, 0, 0)
        self.v_layout.setSpacing(0)
        self.main_h_layout.addWidget(self.main_v_container)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: transparent; border: none; } QProgressBar::chunk { background-color: #00aaff; }")
        self.v_layout.addWidget(self.progress_bar)
        self.marker_panel = MarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.v_layout.addWidget(self.marker_panel)
        self.spectrogram_view = SpectrogramView(self)
        self.v_layout.addWidget(self.spectrogram_view)
        self.set_interaction_mode('TIME')
        QTimer.singleShot(250, lambda: self.set_interaction_mode('TIME'))

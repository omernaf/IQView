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
        
        # --- Root Layout (Vertical) ---
        self.root_layout = QVBoxLayout(self.central_widget)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        
        # 1. Global Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: transparent; border: none; } QProgressBar::chunk { background-color: #00aaff; }")
        self.root_layout.addWidget(self.progress_bar)
        
        # 2. Main Tab Widget
        from PyQt6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False) # Removed explicit close button
        self.tabs.setMovable(False)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #333; top: -1px; background-color: #121212; }
            QTabBar::tab { 
                background-color: #1a1a1a; color: #888; padding: 8px 20px; 
                border: 1px solid #333; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
                margin-right: 2px; font-size: 12px; font-weight: bold;
            }
             QTabBar::tab:hover { background-color: #252525; color: #ccc; }
             QTabBar::tab:selected { background-color: #121212; color: #00aaff; border-bottom: 2px solid #00aaff; }
        """)
        self.root_layout.addWidget(self.tabs)
        
        # Install event filter for middle/right click closing
        self.tabs.tabBar().installEventFilter(self)
        
        # --- Spectrogram Tab Content (Specialized Layout) ---
        self.spec_tab_page = QWidget()
        self.spec_h_layout = QHBoxLayout(self.spec_tab_page)
        self.spec_h_layout.setContentsMargins(0, 0, 0, 0)
        self.spec_h_layout.setSpacing(0)
        
        # Sidebar (Left)
        self.sidebar = SidePanel(self.rate, self.fc, self.fft_size)
        self.sidebar.parametersChanged.connect(self.on_parameters_changed)
        self.spec_h_layout.addWidget(self.sidebar)
        
        # Right Side Container (MarkerPanel + SpectrogramView)
        self.spec_v_container = QWidget()
        self.spec_v_layout = QVBoxLayout(self.spec_v_container)
        self.spec_v_layout.setContentsMargins(0, 0, 0, 0)
        self.spec_v_layout.setSpacing(0)
        self.spec_h_layout.addWidget(self.spec_v_container)
        
        self.marker_panel = MarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.spec_v_layout.addWidget(self.marker_panel)
        
        self.spectrogram_view = SpectrogramView(self)
        self.spec_v_layout.addWidget(self.spectrogram_view)
        
        # Add to tabs
        self.tabs.addTab(self.spec_tab_page, "Spectrogram")
        
        # Hide close button on the first tab
        from PyQt6.QtWidgets import QTabBar
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)

        self.set_interaction_mode('TIME')
        QTimer.singleShot(250, lambda: self.set_interaction_mode('TIME'))

    def close_tab(self, index):
        if index > 0: # Don't close Spectrogram
            widget = self.tabs.widget(index)
            self.tabs.removeTab(index)
            widget.deleteLater()

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QProgressBar, QLabel
from PyQt6.QtCore import Qt, QTimer
from ..marker_panel import MarkerPanel
from ..spectrogram_view import SpectrogramView
from ..side_panel import SidePanel

class UIComponentsMixin:
    def setup_ui(self):
        # The main stylesheet is now handled by apply_current_theme in SpectrogramWindow
        
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
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False) # Removed explicit close button
        self.tabs.setMovable(False)
        # Tab style moved to themes.py but we keep the pane/selected override if specific to QTabWidget
        self.root_layout.addWidget(self.tabs)
        
        # Install event filter for middle/right click closing
        self.tabs.tabBar().installEventFilter(self)
        
        # --- Spectrogram Tab Content (Specialized Layout) ---
        self.spec_tab_page = QWidget()
        self.spec_h_layout = QHBoxLayout(self.spec_tab_page)
        self.spec_h_layout.setContentsMargins(0, 0, 0, 0)
        self.spec_h_layout.setSpacing(0)
        
        # Sidebar (Left)
        self.sidebar = SidePanel(self.rate, self.fc, self.fft_size, parent_window=self)
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
            self.update_tab_names()

    def update_tab_names(self):
        """Update tab names dynamically: 'Time Domain' or 'Time Domain (1)', '(2)', etc."""
        td_indices = [i for i in range(self.tabs.count()) if i > 0]
        if len(td_indices) == 1:
            self.tabs.setTabText(td_indices[0], "Time Domain")
        elif len(td_indices) > 1:
            for i, idx in enumerate(td_indices):
                self.tabs.setTabText(idx, f"Time Domain ({i+1})")

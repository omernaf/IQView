from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QProgressBar, QLabel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from ..marker_panel import MarkerPanel
from ..spectrogram_view import SpectrogramView
from ..side_panel import SidePanel

class UIComponentsMixin:
    def setup_ui(self):
        # The main stylesheet is now handled by apply_current_theme in SpectrogramWindow

        self.central_widget = QWidget()
        self.central_widget.setObjectName("central")
        self.setCentralWidget(self.central_widget)

        # --- Menu Bar ---
        self._build_menu_bar()

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
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(False)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(False)
        self.root_layout.addWidget(self.tabs)

        # Install event filter for middle/right click closing
        self.tabs.tabBar().installEventFilter(self)

        # --- Spectrogram Tab Content (Specialized Layout) ---
        self.spec_tab_page = QWidget()
        self.spec_h_layout = QHBoxLayout(self.spec_tab_page)
        self.spec_h_layout.setContentsMargins(0, 0, 0, 0)
        self.spec_h_layout.setSpacing(0)

        # Sidebar (Left)
        self.sidebar = SidePanel(self.rate, self.fc, self.fft_size,
                                 window_type=self.window_type,
                                 overlap_percent=self.overlap_percent,
                                 parent_window=self)
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

    def _build_menu_bar(self):
        """Create the File menu with Open File and Open Recent."""
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")

        open_action = QAction("&Open File...", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.setStatusTip("Open an IQ binary file")
        open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        self.recent_menu = file_menu.addMenu("Open &Recent")
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        """Populate the Open Recent sub-menu from settings."""
        self.recent_menu.clear()
        recent = self._get_recent_files()
        if not recent:
            placeholder = QAction("(no recent files)", self)
            placeholder.setEnabled(False)
            self.recent_menu.addAction(placeholder)
            return
        for path in recent:
            import os
            action = QAction(os.path.basename(path), self)
            action.setToolTip(path)
            action.triggered.connect(lambda checked, p=path: self.load_new_file(p))
            self.recent_menu.addAction(action)
        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def _get_recent_files(self):
        raw = self.settings_mgr.get("ui/recent_files", "")
        return [p for p in raw.split(";;") if p.strip()] if raw else []

    def _add_recent_file(self, path):
        recent = [p for p in self._get_recent_files() if p != path]
        recent.insert(0, path)
        self.settings_mgr.set("ui/recent_files", ";;".join(recent[:10]))
        self._rebuild_recent_menu()

    def _clear_recent_files(self):
        self.settings_mgr.set("ui/recent_files", "")
        self._rebuild_recent_menu()

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

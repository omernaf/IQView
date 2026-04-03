from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QToolBar
from PyQt6.QtCore import Qt, QEvent, QTimer
from PyQt6.QtGui import QAction
from iqview.ui.themes import get_main_stylesheet, get_palette

class DetachedViewWindow(QMainWindow):
    """
    A standalone window that hosts a TimeDomainView or FrequencyDomainView.
    Includes a toolbar with a "Dock Back" button to return the view to the
    main window's tab bar.
    """
    def __init__(self, view, parent_window):
        # We set parent_window to None to make it a top-level window
        super().__init__(None)
        self.view = view
        self.parent_window = parent_window

        # Match the stylesheet targeting QWidget#central
        self.view.setObjectName("central")

        # Set central widget directly
        self.setCentralWidget(view)

        # Add the Dock Back toolbar
        self._setup_toolbar()

        # Apply current theme (toolbar included)
        self.refresh_theme()

        # Initial title from view
        self.update_title()

        self.resize(1200, 800)

        # Visibility and layout kick
        self.show()

        # Use a slight delay to ensure the window has been fully mapped
        # and has its final geometry before forcing a layout refresh.
        QTimer.singleShot(100, self._force_refresh)

    def _setup_toolbar(self):
        """Add a slim toolbar with a Dock Back button at the top of the window."""
        self._toolbar = QToolBar("Detached Window Controls", self)
        self._toolbar.setObjectName("detached_toolbar")
        self._toolbar.setMovable(False)
        self._toolbar.setFloatable(False)

        # Dock Back action
        self._dock_action = QAction("↩  Dock Back", self)
        self._dock_action.setToolTip("Return this view to the main window's tab bar")
        self._dock_action.triggered.connect(self.dock_back)
        self._toolbar.addAction(self._dock_action)

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

    def _force_refresh(self):
        """Force the view to re-layout and re-paint."""
        if self.view:
            if self.view.layout():
                self.view.layout().activate()
            self.view.update()
            self.view.show()
            self.view.raise_()
        self.refresh_theme()

    def refresh_theme(self):
        """Apply the global application theme to this window."""
        theme = "Light"
        if self.parent_window and hasattr(self.parent_window, 'settings_mgr'):
            theme = self.parent_window.settings_mgr.get("ui/theme", "Light")

        # Apply base stylesheet
        self.setStyleSheet(get_main_stylesheet(theme) + self._toolbar_stylesheet(theme))

        # Also ensure the view refreshes its theme
        if hasattr(self.view, 'refresh_theme'):
            self.view.refresh_theme()

    def _toolbar_stylesheet(self, theme):
        """Return extra CSS for the Dock Back toolbar so it looks polished."""
        p = get_palette(theme)
        return f"""
            QToolBar#detached_toolbar {{
                background-color: {p.bg_sidebar};
                border-bottom: 1px solid {p.border};
                padding: 2px 4px;
                spacing: 4px;
            }}
            QToolBar#detached_toolbar QToolButton {{
                background-color: {p.bg_widget};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 4px;
                padding: 4px 14px;
                font-size: 12px;
                font-weight: bold;
            }}
            QToolBar#detached_toolbar QToolButton:hover {{
                background-color: {p.accent_dim};
                border-color: {p.accent};
                color: {p.accent};
            }}
            QToolBar#detached_toolbar QToolButton:pressed {{
                background-color: {p.accent};
                color: {p.bg_main};
            }}
        """

    def update_title(self):
        # We can dynamically determine a good title based on the view type
        from .time_domain.view import TimeDomainView
        from .frequency_domain.view import FrequencyDomainView

        if isinstance(self.view, TimeDomainView):
            base = "Time Domain"
        elif isinstance(self.view, FrequencyDomainView):
            base = "Freq Domain"
        else:
            base = "Detached View"

        self.setWindowTitle(f"IQView - {base}")

    def closeEvent(self, event):
        # The user wants "close completely" when the detached window is closed.
        if hasattr(self.parent_window, 'close_detached_view'):
            self.parent_window.close_detached_view(self)
        event.accept()

    def dock_back(self):
        """Request the main window to dock this view back."""
        if hasattr(self.parent_window, 'dock_view'):
            self.parent_window.dock_view(self.view)

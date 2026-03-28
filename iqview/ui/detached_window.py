from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, QEvent, QTimer
from iqview.ui.themes import get_main_stylesheet

class DetachedViewWindow(QMainWindow):
    """
    A standalone window that hosts a TimeDomainView or FrequencyDomainView.
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
        
        # Apply current theme
        self.refresh_theme()
        
        # Initial title from view
        self.update_title()
        
        self.resize(1200, 800)
        
        # Visibility and layout kick
        self.show()
        
        # Use a slight delay to ensure the window has been fully mapped
        # and has its final geometry before forcing a layout refresh.
        QTimer.singleShot(100, self._force_refresh)
    
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
        if self.parent_window and hasattr(self.parent_window, 'settings_mgr'):
            theme = self.parent_window.settings_mgr.get("ui/theme", "Light")
            self.setStyleSheet(get_main_stylesheet(theme))
        
        # Also ensure the view refreshes its theme
        if hasattr(self.view, 'refresh_theme'):
            self.view.refresh_theme()

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

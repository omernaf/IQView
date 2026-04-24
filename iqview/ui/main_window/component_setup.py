from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QProgressBar,
                               QLabel, QTabBar, QTabWidget)
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QAction, QKeySequence, QPainter, QPixmap
from ..marker_panel import MarkerPanel
from ..spectrogram_view import SpectrogramView
from ..side_panel import SidePanel


class DetachableTabBar(QTabBar):
    """
    A QTabBar subclass that supports:
      - Reordering tabs by dragging left/right (the Spectrogram tab is pinned at index 0)
      - Tearing a tab off by dragging it vertically, showing a ghost preview, then
        calling undock_tab() on the parent SpectrogramWindow on release.
    """

    # Vertical pixel threshold before switching to "undock" mode
    UNDOCK_Y_THRESHOLD = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_start_pos = None
        self._drag_tab_index = -1
        self._ghost_label = None
        self._is_dragging_out = False

        # Allow horizontal tab reordering
        self.setMovable(True)

        # Enforce the Spectrogram tab stays pinned after any reorder
        self.tabMoved.connect(self._on_tab_moved)

    # ------------------------------------------------------------------ #
    #  Mouse event overrides                                               #
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.tabAt(event.pos())
            self._drag_tab_index = idx
            self._drag_start_pos = event.pos()
            self._is_dragging_out = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return

        # Block the Spectrogram tab (index 0) from being dragged at all
        if self._drag_tab_index == 0:
            event.accept()
            return

        if self._drag_start_pos is None or self._drag_tab_index < 0:
            super().mouseMoveEvent(event)
            return

        delta = event.pos() - self._drag_start_pos

        # Vertical drag exceeds threshold → switch to undock ghost mode
        if not self._is_dragging_out and abs(delta.y()) > self.UNDOCK_Y_THRESHOLD:
            self._is_dragging_out = True
            self._show_ghost(event.pos())

        if self._is_dragging_out:
            # Keep ghost following the cursor
            if self._ghost_label:
                global_pos = self.mapToGlobal(event.pos())
                self._ghost_label.move(
                    global_pos.x() - self._ghost_label.width() // 2,
                    global_pos.y() - 20,
                )
            event.accept()
            return

        # Otherwise: normal left/right tab reordering handled by Qt
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_dragging_out and self._drag_tab_index > 0:
            self._hide_ghost()
            global_pos = self.mapToGlobal(event.pos())

            # The parent chain: DetachableTabBar → QTabWidget → central_widget → SpectrogramWindow
            # self.window() is the reliable shortcut to the top-level QMainWindow.
            main_window = self.window()
            if hasattr(main_window, 'undock_tab'):
                tab_idx = self._drag_tab_index

                # Find which screen the cursor is on — handles multi-monitor
                # setups where secondary screens may have negative coordinates
                # (screen to the left of primary) or large positive coordinates
                # (screen to the right).  max(0, ...) would be wrong for both cases.
                from PyQt6.QtGui import QGuiApplication
                screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
                sg = screen.geometry()

                win_w, win_h = 1200, 800
                x = global_pos.x() - win_w // 2           # centre under cursor
                y = global_pos.y() - 30                   # just below release point
                # Clamp so the window doesn't overshoot any edge of this screen
                x = max(sg.left(), min(x, sg.right()  - win_w))
                y = max(sg.top(),  min(y, sg.bottom() - win_h))

                main_window.undock_tab(tab_idx, initial_pos=QPoint(x, y))

            self._reset_drag_state()
            event.accept()
            return

        self._reset_drag_state()
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------ #
    #  Ghost preview helpers                                               #
    # ------------------------------------------------------------------ #

    def _show_ghost(self, local_pos):
        """Render a semi-transparent thumbnail of the tab content and float it."""
        tab_widget = self.parent()
        if not tab_widget:
            return

        widget = tab_widget.widget(self._drag_tab_index)
        if widget:
            original = widget.grab()
            thumbnail = original.scaled(
                min(original.width(), 360),
                min(original.height(), 225),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            thumbnail = QPixmap(360, 225)
            thumbnail.fill(Qt.GlobalColor.darkGray)

        # Add a thin border to make the ghost look like a floating window
        bordered = QPixmap(thumbnail.width() + 4, thumbnail.height() + 4)
        bordered.fill(Qt.GlobalColor.transparent)
        border_painter = QPainter(bordered)
        border_painter.setPen(Qt.GlobalColor.darkGray)
        border_painter.drawRect(0, 0, bordered.width() - 1, bordered.height() - 1)
        border_painter.drawPixmap(2, 2, thumbnail)
        border_painter.end()

        # Apply semi-transparency
        ghost_pixmap = QPixmap(bordered.size())
        ghost_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(ghost_pixmap)
        painter.setOpacity(0.72)
        painter.drawPixmap(0, 0, bordered)
        painter.end()

        self._ghost_label = QLabel()
        self._ghost_label.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._ghost_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._ghost_label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._ghost_label.setPixmap(ghost_pixmap)
        self._ghost_label.resize(ghost_pixmap.size())

        global_pos = self.mapToGlobal(local_pos)
        self._ghost_label.move(
            global_pos.x() - ghost_pixmap.width() // 2,
            global_pos.y() - 20,
        )
        self._ghost_label.show()
        self.setCursor(Qt.CursorShape.DragMoveCursor)

    def _hide_ghost(self):
        if self._ghost_label:
            self._ghost_label.hide()
            self._ghost_label.deleteLater()
            self._ghost_label = None
        self.unsetCursor()

    def _reset_drag_state(self):
        self._drag_start_pos = None
        self._drag_tab_index = -1
        self._is_dragging_out = False
        self._hide_ghost()

    # ------------------------------------------------------------------ #
    #  Spectrogram tab pinning                                             #
    # ------------------------------------------------------------------ #

    def _on_tab_moved(self, from_idx, to_idx):
        """If any move would displace the Spectrogram tab from index 0, revert it."""
        if to_idx == 0 or from_idx == 0:
            QTimer.singleShot(0, self._enforce_spectrogram_at_zero)

    def _enforce_spectrogram_at_zero(self):
        """Find spec_tab_page and move it back to index 0 if displaced."""
        tab_widget = self.parent()
        if not tab_widget:
            return
        main_window = self.window()
        spec_page = getattr(main_window, 'spec_tab_page', None)
        if spec_page is None:
            return
        for i in range(tab_widget.count()):
            if tab_widget.widget(i) is spec_page:
                if i != 0:
                    self.moveTab(i, 0)
                break


# ======================================================================= #


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
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: transparent; border: none; } "
            "QProgressBar::chunk { background-color: #00aaff; }"
        )
        self.root_layout.addWidget(self.progress_bar)

        # 2. Main Tab Widget — backed by a DetachableTabBar
        self.tabs = QTabWidget()
        detachable_bar = DetachableTabBar(self.tabs)
        self.tabs.setTabBar(detachable_bar)
        self.tabs.setTabsClosable(False)
        # NOTE: setMovable is controlled inside DetachableTabBar (it sets self.setMovable(True))
        self.root_layout.addWidget(self.tabs)

        # Install event filter for middle/right click on the tab bar
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

        # --- Overlays Menu ---
        overlays_menu = mb.addMenu("&Overlays")
        
        import_action = QAction("&Import Overlays...", self)
        import_action.setStatusTip("Import overlays from a JSON file and add them to the current view")
        import_action.triggered.connect(self.import_overlays)
        overlays_menu.addAction(import_action)

        export_action = QAction("&Export Overlays...", self)
        export_action.setStatusTip("Export all currently placed overlays to a JSON file")
        export_action.triggered.connect(self.export_overlays)
        overlays_menu.addAction(export_action)

        # --- Plugins Menu ---
        self._plugins_menu = mb.addMenu("&Plugins")
        # Initial population is handled by PluginManagerMixin._rebuild_plugins_menu()
        if hasattr(self, '_rebuild_plugins_menu'):
            self._rebuild_plugins_menu()

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
        if index > 0:  # Don't close Spectrogram
            widget = self.tabs.widget(index)
            self.tabs.removeTab(index)
            widget.deleteLater()
            self.update_tab_names()

    def update_tab_names(self):
        """Update tab names dynamically: 'Time Domain' or 'Freq Domain'."""
        from ..time_domain.view import TimeDomainView
        from ..frequency_domain.view import FrequencyDomainView

        td_indices = []
        fd_indices = []

        for i in range(1, self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, TimeDomainView):
                td_indices.append(i)
            elif isinstance(widget, FrequencyDomainView):
                fd_indices.append(i)

        # Update Time Domain tabs
        if len(td_indices) == 1:
            self.tabs.setTabText(td_indices[0], "Time Domain")
        elif len(td_indices) > 1:
            for i, idx in enumerate(td_indices):
                self.tabs.setTabText(idx, f"Time Domain ({i+1})")

        # Update Freq Domain tabs
        if len(fd_indices) == 1:
            self.tabs.setTabText(fd_indices[0], "Freq Domain")
        elif len(fd_indices) > 1:
            for i, idx in enumerate(fd_indices):
                self.tabs.setTabText(idx, f"Freq Domain ({i+1})")

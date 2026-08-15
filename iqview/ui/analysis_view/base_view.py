import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from ..widgets import CustomViewBox
from ..themes import get_palette, get_scrollbar_stylesheet


class BaseAnalysisView(QWidget):
    """
    Base widget providing shared UI scaffold, zoom/pan navigation, scrollbars,
    theming, and grid line generation for 1D analysis views (Time Domain & Frequency Domain).
    """
    toolbar_id = "analysis_toolbar"

    def __init__(self, parent=None, parent_window=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.parent_window = parent_window
        self.settings_mgr = parent_window.settings_mgr if parent_window else None
        self.is_spectrogram = False
        self.zoom_mode = False
        self.last_move_scene_pos = None
        self._block_signals = False
        self.zoom_history = []
        self.zoom_y_dict = {}

        # Grid state
        self.grid_primary_enabled = False
        self.grid_primary_tracking = True
        self.grid_lines_primary = []

        self.grid_mag_enabled = False
        self.grid_mag_tracking = True
        self.grid_lines_mag = []

        self._grid_timer = QTimer(self)
        self._grid_timer.setSingleShot(True)
        self._grid_timer.timeout.connect(self._do_update_grid)
        self._grid_pending_axes = set()

        # Build UI Scaffold
        self._setup_scaffold()

    def _setup_scaffold(self):
        """Construct the core Qt layout, plot widget, scrollbars, and toolbar."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(5)

        # Toolbar container
        self.toolbar = QFrame()
        self.toolbar.setObjectName(self.toolbar_id)
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 5, 10, 5)

        self.mode_group = QButtonGroup(self)
        self.plot_buttons = []
        self.plot_buttons_layout = QHBoxLayout()
        self.plot_buttons_layout.setSpacing(5)

        # Plot & Scrollbars container
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)

        self.view_box = CustomViewBox(self)
        self.plot_widget = pg.PlotWidget(viewBox=self.view_box)
        self.plot_item = self.plot_widget.getPlotItem()

        self.x_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.y_scroll = QScrollBar(Qt.Orientation.Vertical)

        palette = get_palette(self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark")
        scrollbar_style = get_scrollbar_stylesheet(palette)
        self.x_scroll.setStyleSheet(scrollbar_style)
        self.y_scroll.setStyleSheet(scrollbar_style)

        self.grid_layout.addWidget(self.plot_widget, 0, 1)
        self.grid_layout.addWidget(self.y_scroll, 0, 0)
        self.grid_layout.addWidget(self.x_scroll, 1, 1)

        self.x_scroll.hide()
        self.y_scroll.hide()

        # Connect scrollbar signals
        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.view_box.sigRangeChanged.connect(lambda: self.update_grid('PRIMARY'))
        self.view_box.sigRangeChanged.connect(lambda: self.update_grid('MAG'))
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

    # -------------------------------------------------------------------------
    # Zoom & Navigation
    # -------------------------------------------------------------------------
    def undo_zoom(self):
        if self.zoom_history:
            prev_rect = self.zoom_history.pop()
            self.plot_item.setRange(rect=prev_rect, padding=0)

    def reset_zoom(self):
        if hasattr(self, 'view_box') and self.view_box.viewRect() is not None:
            self.zoom_history.append(self.plot_item.viewRect())
        p_min, p_max = self._get_primary_bounds()
        y_min, y_max = self._get_y_bounds()
        y_pad = (y_max - y_min) * 0.05 if y_max != y_min else 1.0
        self.plot_item.setXRange(p_min, p_max, padding=0)
        self.plot_item.setYRange(y_min - y_pad, y_max + y_pad, padding=0)

    def reset_zoom_x(self):
        if hasattr(self, 'view_box') and self.view_box.viewRect() is not None:
            self.zoom_history.append(self.plot_item.viewRect())
        p_min, p_max = self._get_primary_bounds()
        self.plot_item.setXRange(p_min, p_max, padding=0)

    def reset_zoom_y(self):
        if hasattr(self, 'view_box') and self.view_box.viewRect() is not None:
            self.zoom_history.append(self.plot_item.viewRect())
        y_min, y_max = self._get_y_bounds()
        y_pad = (y_max - y_min) * 0.05 if y_max != y_min else 1.0
        self.plot_item.setYRange(y_min - y_pad, y_max + y_pad, padding=0)

    def handle_zoom_rectangle(self, rect, zoom_type='BOTH', source_vb=None, **kwargs):
        self.zoom_history.append(self.plot_item.viewRect())
        if rect.width() <= 0 and zoom_type != 'Y_ONLY': return
        if rect.height() <= 0 and zoom_type != 'X_ONLY': return
        if zoom_type == 'Y_ONLY':
            self.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
        elif zoom_type == 'X_ONLY':
            self.plot_item.setXRange(rect.left(), rect.right(), padding=0)
        else:
            self.plot_item.setRange(rect, padding=0)

    def handle_move_drag(self, pos, is_start=False, is_finish=False, source_vb=None, **kwargs):
        if is_start:
            self.last_move_scene_pos = pos
            return
        if self.last_move_scene_pos is None:
            return
        vb = source_vb if source_vb is not None else self.view_box
        p1 = vb.mapSceneToView(self.last_move_scene_pos)
        p2 = vb.mapSceneToView(pos)
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        vb.translateBy(x=-dx, y=-dy)
        self.last_move_scene_pos = pos
        if is_finish:
            self.last_move_scene_pos = None

    def fit_to_markers(self):
        is_primary = self.is_primary_mode(self.interaction_mode)
        is_endless = 'ENDLESS' in self.interaction_mode
        if is_endless:
            active = self.markers_primary_endless if is_primary else self.markers_y_endless_dict.get(self.y_label_text, [])
        else:
            active = self.markers_primary if is_primary else self.markers_y_dict.get(self.y_label_text, [])

        if len(active) >= 2:
            self.zoom_history.append(self.plot_item.viewRect())
            sorted_m = sorted(active, key=lambda m: m.value())
            v1, v2 = sorted_m[0].value(), sorted_m[-1].value()
            if is_primary:
                self.plot_item.setXRange(v1, v2, padding=0)
            else:
                self.plot_item.setYRange(v1, v2, padding=0)

    # -------------------------------------------------------------------------
    # Scrollbar Handling
    # -------------------------------------------------------------------------
    def _get_primary_bounds(self):
        """Returns (x_min, x_max) for the primary domain axis. Override in subclass."""
        if hasattr(self, 'time_axis') and len(self.time_axis) > 0:
            return self.time_axis[0], self.time_axis[-1]
        if hasattr(self, 'freq_axis') and len(self.freq_axis) > 0:
            return self.freq_axis[0], self.freq_axis[-1]
        return 0.0, 1.0

    def _get_y_bounds(self):
        """Returns (y_min, y_max) for the current plot data. Override in subclass if needed."""
        if hasattr(self, 'current_plot_data') and len(self.current_plot_data) > 0:
            return float(np.min(self.current_plot_data)), float(np.max(self.current_plot_data))
        return 0.0, 1.0

    def update_scrollbars(self):
        if self._block_signals: return
        self._block_signals = True

        xr, yr = self.view_box.viewRange()

        # Primary axis (X)
        x_start, x_end = self._get_primary_bounds()
        x_total = x_end - x_start
        if x_total > 0:
            visible_ratio_x = (xr[1] - xr[0]) / x_total
            if visible_ratio_x < 0.999:
                self.x_scroll.show()
                page_step = int(visible_ratio_x * 1000)
                self.x_scroll.setRange(0, 1000 - page_step)
                self.x_scroll.setPageStep(page_step)
                pos = (xr[0] - x_start) / x_total * 1000
                self.x_scroll.setValue(int(pos))
            else:
                self.x_scroll.hide()

        # Magnitude axis (Y)
        y_min_data, y_max_data = self._get_y_bounds()
        y_range_total = y_max_data - y_min_data
        if y_range_total > 0:
            visible_ratio_y = (yr[1] - yr[0]) / y_range_total
            if visible_ratio_y < 0.999:
                self.y_scroll.show()
                page_step = int(visible_ratio_y * 1000)
                self.y_scroll.setRange(0, 1000 - page_step)
                self.y_scroll.setPageStep(page_step)
                pos_from_bottom = (yr[0] - y_min_data) / y_range_total * 1000
                inv_pos = 1000 - page_step - int(pos_from_bottom)
                self.y_scroll.setValue(inv_pos)
            else:
                self.y_scroll.hide()

        self._block_signals = False

    def scroll_view(self):
        if self._block_signals: return
        self._block_signals = True

        val_x = self.x_scroll.value()
        val_y = self.y_scroll.value()

        x_start, x_end = self._get_primary_bounds()
        x_total = x_end - x_start

        y_min_data, y_max_data = self._get_y_bounds()
        y_range_total = y_max_data - y_min_data

        xr, yr = self.view_box.viewRange()
        width = xr[1] - xr[0]
        height = yr[1] - yr[0]

        new_left = x_start + (val_x / 1000.0) * x_total
        inv_val_y = 1000 - self.y_scroll.pageStep() - val_y
        new_bottom = y_min_data + (inv_val_y / 1000.0) * y_range_total

        if self.x_scroll.isVisible():
            self.plot_item.setXRange(new_left, new_left + width, padding=0)
        if self.y_scroll.isVisible():
            self.plot_item.setYRange(new_bottom, new_bottom + height, padding=0)

        self._block_signals = False

    # -------------------------------------------------------------------------
    # Theming & Styling
    # -------------------------------------------------------------------------
    def refresh_theme(self):
        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)

        self.update_toolbar_style()
        self.refresh_plot_style()
        if hasattr(self, 'marker_panel') and hasattr(self.marker_panel, 'refresh_theme'):
            self.marker_panel.refresh_theme()

        sb_style = get_scrollbar_stylesheet(p)
        self.x_scroll.setStyleSheet(sb_style)
        self.y_scroll.setStyleSheet(sb_style)

        if hasattr(self, '_replot_current'):
            self._replot_current()

    def update_toolbar_style(self):
        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)
        self.toolbar.setStyleSheet(f"""
            QFrame#{self.toolbar_id} {{ background-color: {p.bg_sidebar}; border-radius: 6px; border: 1px solid {p.border}; }}
            QPushButton {{ background-color: {p.bg_widget}; padding: 5px 15px; border-radius: 3px; color: {p.text_main}; }}
            QPushButton:hover {{ background-color: {p.border_light}; }}
            QPushButton:checked {{ background-color: {p.accent_dim}; color: {p.accent}; border: 1px solid {p.accent}; }}
        """)

    def refresh_plot_style(self):
        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)
        self.plot_widget.setBackground(p.plot_bg)

        font = QFont()
        font.setPointSize(int(self.settings_mgr.get("ui/axis_font_size", 10)) if self.settings_mgr else 10)

        grid_enabled = bool(self.settings_mgr.get("ui/grid_enabled", True)) if self.settings_mgr else True
        grid_alpha = (int(self.settings_mgr.get("ui/grid_alpha", 30)) / 100.0) if self.settings_mgr else 0.3

        self.plot_item.getAxis('left').setTickFont(font)
        self.plot_item.getAxis('bottom').setTickFont(font)
        self.plot_widget.showGrid(x=grid_enabled, y=grid_enabled, alpha=grid_alpha)

        self.plot_item.getAxis('left').setPen(p.text_dim)
        self.plot_item.getAxis('bottom').setPen(p.text_dim)

    def refresh_cursor(self):
        mode = getattr(self, 'interaction_mode', 'TIME')
        cursor = Qt.CursorShape.ArrowCursor
        if mode == 'ZOOM': cursor = Qt.CursorShape.CrossCursor
        elif mode == 'MOVE': cursor = Qt.CursorShape.SizeAllCursor
        elif mode in ['TIME', 'FREQ', 'MAG', 'Y', 'FILTER', 'TIME_ENDLESS', 'FREQ_ENDLESS', 'MAG_ENDLESS']:
            cursor = Qt.CursorShape.CrossCursor
        self.plot_widget.setCursor(cursor)

    # -------------------------------------------------------------------------
    # Grid & Shadow Markers
    # -------------------------------------------------------------------------
    def is_primary_mode(self, mode):
        """Returns True if the mode operates on the primary (X) axis. Override in subclass."""
        return mode in ['TIME', 'TIME_ENDLESS', 'FREQ', 'FREQ_ENDLESS', 'STATS']

    def toggle_grid(self, axis, enabled):
        axis_norm = self._normalize_axis_name(axis)
        if axis_norm == 'PRIMARY': self.grid_primary_enabled = enabled
        else: self.grid_mag_enabled = enabled
        self.update_grid(axis, force=True)

    def toggle_tracking(self, axis, enabled):
        axis_norm = self._normalize_axis_name(axis)
        if axis_norm == 'PRIMARY': self.grid_primary_tracking = enabled
        else: self.grid_mag_tracking = enabled
        self.update_grid(axis, force=True)

    def _normalize_axis_name(self, axis):
        if axis in ['TIME', 'FREQ', 'PRIMARY']: return 'PRIMARY'
        return 'MAG'

    def update_grid(self, axis, force=False):
        if force:
            self._do_update_grid(axis, force=True)
        else:
            self._grid_pending_axes.add(axis)
            if not self._grid_timer.isActive():
                self._grid_timer.start(50)

    def _do_update_grid(self, axis=None, force=False):
        if axis is None:
            axes_to_update = list(self._grid_pending_axes)
            self._grid_pending_axes.clear()
            for a in axes_to_update:
                self._do_update_grid(a, force=force)
            return

        axis_norm = self._normalize_axis_name(axis)
        is_primary = (axis_norm == 'PRIMARY')
        enabled = self.grid_primary_enabled if is_primary else self.grid_mag_enabled
        tracking = self.grid_primary_tracking if is_primary else self.grid_mag_tracking
        active_markers = self.markers_primary if is_primary else self.markers_y_dict.get(self.y_label_text, [])
        grid_lines = self.grid_lines_primary if is_primary else self.grid_lines_mag

        if not enabled:
            for line in grid_lines: self.plot_item.removeItem(line)
            grid_lines.clear()
            return
        if not tracking and not force: return
        for line in grid_lines: self.plot_item.removeItem(line)
        grid_lines.clear()
        if len(active_markers) != 2: return

        sorted_m = sorted(active_markers, key=lambda m: m.value())
        p1, p2 = sorted_m[0].value(), sorted_m[1].value()
        delta = abs(p2 - p1)
        if delta <= 0: return

        vr = self.plot_item.viewRange()
        v_min_visible, v_max_visible = vr[0] if is_primary else vr[1]

        if (v_max_visible - v_min_visible) / delta > 500:
            return

        angle = 90 if is_primary else 0
        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        color = self.settings_mgr.get(f"ui/{theme}/marker_grid_color", "#c8c8ff") if self.settings_mgr else "#c8c8ff"
        style_name = self.settings_mgr.get(f"ui/{theme}/marker_grid_style", "SolidLine") if self.settings_mgr else "SolidLine"
        alpha = int(self.settings_mgr.get("ui/marker_grid_alpha", 50)) if self.settings_mgr else 50
        width = int(self.settings_mgr.get("ui/marker_grid_width", 1)) if self.settings_mgr else 1

        style_map = {
            "SolidLine": Qt.PenStyle.SolidLine,
            "DashLine": Qt.PenStyle.DashLine,
            "DotLine": Qt.PenStyle.DotLine,
            "DashDotLine": Qt.PenStyle.DashDotLine
        }
        style = style_map.get(str(style_name), Qt.PenStyle.SolidLine)

        qcolor = QColor(color)
        qcolor.setAlphaF(alpha / 100.0)
        pen = pg.mkPen(qcolor, width=width, style=style)

        start_count = np.ceil((v_min_visible - p1) / delta)
        curr = p1 + start_count * delta

        count = 0
        while curr <= v_max_visible + 1e-9 and count < 500:
            line = pg.InfiniteLine(pos=curr, angle=angle, pen=pen, movable=False)
            line.setHoverPen(pg.mkPen(255, 0, 0, width=2))
            line.setAcceptHoverEvents(True)
            line.setZValue(5)
            self.plot_item.addItem(line, ignoreBounds=True)
            grid_lines.append(line)
            curr += delta
            count += 1

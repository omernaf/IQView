import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QApplication, QLineEdit, QDoubleSpinBox, QSpinBox
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from ..widgets import key_event_to_name, format_tooltip_with_keybind
from ..themes import get_palette


class Base1DPlotView(QWidget):
    """Shared base class for 1D interactive signal views (TimeDomainView and FrequencyDomainView).

    Centralizes:
      - Zoom & pan stack (`undo_zoom`, `reset_zoom`, `handle_zoom_rectangle`, `handle_move_drag`, `fit_to_markers`)
      - Synchronized X/Y zoom scrollbars (`update_scrollbars`, `scroll_view`)
      - Fixed & endless marker placement, 20px hit-testing, age-based teleportation, and crossing swaps
      - `M1`, `M2`, `Delta`, and `Center` locked dragging
      - Shadow marker grid generation (`_do_update_grid` with 50ms throttle) and shadow-line dragging
      - Region Statistics bound placement and dragging
      - Marker text-field editing (`marker_edit_finished`) and clearing (`handle_marker_clear`, `clear_all_markers`)
      - Keyboard shortcut handling (`keyPressEvent`, `keyReleaseEvent`)
    """

    primary_mode = "TIME"
    primary_endless_mode = "TIME_ENDLESS"
    primary_kb_key = "keybinds/time_markers"
    primary_kb_default = "T"
    primary_endless_kb_key = "keybinds/time_endless_markers"
    primary_endless_kb_default = "E"

    def _get_x_axis(self) -> np.ndarray:
        return getattr(self, "time_axis", getattr(self, "freq_axis", np.array([])))

    def _get_primary_markers(self) -> list:
        return self.markers_time if self.primary_mode == "TIME" else self.markers_freq

    def _get_primary_endless_markers(self) -> list:
        return self.markers_time_endless if self.primary_mode == "TIME" else self.markers_freq_endless

    def _get_primary_grid_lines(self) -> list:
        return self.grid_lines_time if self.primary_mode == "TIME" else self.grid_lines_freq

    def _is_primary_grid_enabled(self) -> bool:
        return self.grid_time_enabled if self.primary_mode == "TIME" else self.grid_freq_enabled

    def _set_primary_grid_enabled(self, enabled: bool):
        if self.primary_mode == "TIME":
            self.grid_time_enabled = enabled
        else:
            self.grid_freq_enabled = enabled

    def _is_primary_grid_tracking(self) -> bool:
        return self.grid_time_tracking if self.primary_mode == "TIME" else self.grid_freq_tracking

    def _set_primary_grid_tracking(self, enabled: bool):
        if self.primary_mode == "TIME":
            self.grid_time_tracking = enabled
        else:
            self.grid_freq_tracking = enabled

    def _sub_unit_to_primary_val(self, val: float) -> float:
        if self.primary_mode == "TIME":
            return (val - 1.0) / self.rate
        x_axis = self._get_x_axis()
        if len(x_axis) == 0:
            return val
        idx_val = max(0, min(len(x_axis) - 1, int(val)))
        return float(x_axis[idx_val])

    def _sub_delta_to_primary_delta(self, val: float) -> float:
        if self.primary_mode == "TIME":
            return (val - 1.0) / self.rate
        x_axis = self._get_x_axis()
        if len(x_axis) > 1:
            return float(val * (x_axis[1] - x_axis[0]))
        return val

    def _get_y_bounds(self):
        data = getattr(self, "current_plot_data", np.array([]))
        if data is None or len(data) == 0:
            return 0.0, 1.0
        valid_data = data[np.isfinite(data)]
        if len(valid_data) == 0:
            return 0.0, 1.0
        return float(np.min(valid_data)), float(np.max(valid_data))

    def _get_theme_name(self) -> str:
        if getattr(self, "settings_mgr", None):
            return str(self.settings_mgr.get("ui/theme", "Dark"))
        if getattr(self, "parent_window", None) and getattr(self.parent_window, "settings_mgr", None):
            return str(self.parent_window.settings_mgr.get("ui/theme", "Dark"))
        return "Dark"

    # ------------------------------------------------------------------
    # Shared Toolbar Style & Oversample Controls
    # ------------------------------------------------------------------

    def update_toolbar_style(self):
        if not hasattr(self, "toolbar"):
            return
        theme = self._get_theme_name()
        p = get_palette(theme)
        obj_name = self.toolbar.objectName()
        frame_sel = f"QFrame#{obj_name}" if obj_name else "QFrame"
        self.toolbar.setStyleSheet(f"""
            {frame_sel} {{ background-color: {p.bg_sidebar}; border-radius: 6px; border: 1px solid {p.border}; }}
            QLabel {{ color: {p.text_dim}; background: transparent; border: none; }}
            QDoubleSpinBox, QSpinBox {{ background-color: {p.bg_input}; color: {p.text_main}; border: 1px solid {p.border}; border-radius: 4px; padding: 3px 6px; }}
            QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {p.accent}; }}
            QPushButton {{ background-color: {p.bg_widget}; padding: 5px 15px; border-radius: 3px; color: {p.text_main}; }}
            QPushButton:hover {{ background-color: {p.border_light}; }}
            QPushButton:checked {{ background-color: {p.accent_dim}; color: {p.accent}; border: 1px solid {p.accent}; }}
        """)

    def setup_oversample_controls(self, toolbar_layout):
        """Create the shared 'Oversample:' label and spinbox in any 1D plot toolbar."""
        from PyQt6.QtWidgets import QLabel, QDoubleSpinBox

        self._base_samples = getattr(self, "samples", None)
        self._base_rate = float(getattr(self, "rate", 1.0) or 1.0)

        self.oversample_label = QLabel("Oversample:")
        self.oversample_spin = QDoubleSpinBox()
        self.oversample_spin.setRange(0.1, 1000.0)
        self.oversample_spin.setDecimals(2)
        self.oversample_spin.setSingleStep(0.5)
        self.oversample_spin.setSuffix(" ×")
        self.oversample_spin.setValue(1.0)
        self.oversample_spin.setKeyboardTracking(False)
        self.oversample_spin.setFixedWidth(92)
        self.oversample_spin.setToolTip(
            f"Oversampling factor relative to base sample rate ({self._base_rate:g} Hz).\n"
            f"For example, 5.20 × resamples the signal to {self._base_rate * 5.2:g} Hz."
        )

        toolbar_layout.addWidget(self.oversample_label)
        toolbar_layout.addWidget(self.oversample_spin)
        toolbar_layout.addSpacing(12)

        self.oversample_spin.valueChanged.connect(self._on_oversample_factor_changed)

    def _on_oversample_factor_changed(self, val: float):
        factor = max(0.01, float(val))
        base_samples = getattr(self, "_base_samples", None)
        base_rate = float(getattr(self, "_base_rate", getattr(self, "rate", 1.0)) or 1.0)
        if base_samples is None or len(base_samples) == 0 or not hasattr(self, "set_samples"):
            return

        if abs(factor - 1.0) < 1e-6:
            self.set_samples(base_samples, base_rate)
        else:
            from scipy import signal as sp_signal
            num_out = max(2, int(round(len(base_samples) * factor)))
            resampled = sp_signal.resample(base_samples, num_out).astype(base_samples.dtype, copy=False)
            self.set_samples(resampled, base_rate * factor)

    # ------------------------------------------------------------------
    # Keybinds & Tooltips
    # ------------------------------------------------------------------

    def update_button_tooltips(self):
        if hasattr(self, "marker_panel"):
            self.marker_panel.update_button_tooltips()
        s = getattr(self, "settings_mgr", None)
        for i, btn in enumerate(getattr(self, "plot_buttons", [])):
            if i < 10:
                kb = s.get(f"keybinds/plot_mode_{i+1}", f"F{i+1}") if s else f"F{i+1}"
            else:
                kb = ""
            btn.setToolTip(format_tooltip_with_keybind(f"Plot {btn.text()}", kb))

    def _get_kb(self, key, default):
        s = getattr(self, "settings_mgr", None)
        return str(s.get(key, default)) if s else default

    def _handle_domain_keypress(self, key_name: str) -> bool:
        """Hook for subclasses to handle domain-specific keybinds."""
        return False

    def keyPressEvent(self, event):
        event._from_subview = True
        if event.isAutoRepeat():
            return
        if isinstance(QApplication.focusWidget(), (QLineEdit, QDoubleSpinBox, QSpinBox)):
            super().keyPressEvent(event)
            return
        key_name = key_event_to_name(event)
        if not key_name:
            super().keyPressEvent(event)
            return

        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.undo_zoom()
            return

        if key_name == self._get_kb("keybinds/zoom_mode", "Ctrl"):
            if self.interaction_mode not in ("ZOOM", "MOVE"):
                self._prev_interaction_mode = self.interaction_mode
            self._zoom_key_held = True
            self.set_interaction_mode("ZOOM")
            return
        elif key_name == self._get_kb("keybinds/move_mode", "Space"):
            if self.interaction_mode not in ("ZOOM", "MOVE"):
                self._prev_interaction_mode = self.interaction_mode
            self._move_key_held = True
            self.set_interaction_mode("MOVE")
            return
        elif key_name == self._get_kb("keybinds/reset_zoom", "R"):
            self.reset_zoom()
            return
        elif key_name == self._get_kb("keybinds/undo_zoom", "Ctrl+Z"):
            self.undo_zoom()
            return
        elif key_name == self._get_kb("keybinds/clear_markers", "Backspace"):
            clear_mode = "Y" if self.interaction_mode == "MAG" else self.interaction_mode
            if clear_mode in ("ZOOM", "MOVE"):
                last_m = getattr(self.marker_panel, "last_marker_mode", self.primary_mode)
                clear_mode = "Y" if last_m == "MAG" else last_m
            self.handle_marker_clear(clear_mode)
            return
        elif key_name == self._get_kb("keybinds/open_settings", "I"):
            if self.parent_window and hasattr(self.parent_window, "sidebar"):
                self.parent_window.sidebar.open_settings()
            return
        elif key_name == self._get_kb(self.primary_kb_key, self.primary_kb_default):
            self._prev_interaction_mode = self.primary_mode
            self.set_interaction_mode(self.primary_mode)
            return
        elif key_name == self._get_kb(self.primary_endless_kb_key, self.primary_endless_kb_default):
            self._prev_interaction_mode = self.primary_endless_mode
            self.set_interaction_mode(self.primary_endless_mode)
            return
        elif key_name == self._get_kb("keybinds/mag_markers", "M"):
            self._prev_interaction_mode = "MAG"
            self.set_interaction_mode("MAG")
            return
        elif key_name == self._get_kb("keybinds/mag_endless_markers", "N"):
            self._prev_interaction_mode = "MAG_ENDLESS"
            self.set_interaction_mode("MAG_ENDLESS")
            return
        elif key_name == self._get_kb("keybinds/stats_mode", "S"):
            self._prev_interaction_mode = "STATS"
            self.set_interaction_mode("STATS")
            return
        elif key_name == self._get_kb("keybinds/lock_m1", "1"):
            if self.marker_panel.btn_lock_m1.isEnabled():
                self.marker_panel.btn_lock_m1.click()
            return
        elif key_name == self._get_kb("keybinds/lock_m2", "2"):
            if self.marker_panel.btn_lock_m2.isEnabled():
                self.marker_panel.btn_lock_m2.click()
            return
        elif key_name == self._get_kb("keybinds/lock_delta", "D"):
            if self.marker_panel.btn_lock_delta.isEnabled():
                self.marker_panel.btn_lock_delta.click()
            return
        elif key_name == self._get_kb("keybinds/lock_center", "C"):
            if self.marker_panel.btn_lock_center.isEnabled():
                self.marker_panel.btn_lock_center.click()
            return
        elif key_name == self._get_kb("keybinds/stats_def", "Q"):
            if self.interaction_mode == "STATS":
                self.marker_panel.btn_stats_def.click()
            return
        elif key_name == self._get_kb("keybinds/stats_res", "W"):
            if self.interaction_mode == "STATS":
                self.marker_panel.btn_stats_res.click()
            return

        if self._handle_domain_keypress(key_name):
            return

        for i, btn in enumerate(self.plot_buttons[:10]):
            if key_name == self._get_kb(f"keybinds/plot_mode_{i+1}", f"F{i+1}"):
                btn.click()
                return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        event._from_subview = True
        if event.isAutoRepeat():
            return
        if isinstance(QApplication.focusWidget(), (QLineEdit, QDoubleSpinBox, QSpinBox)):
            super().keyReleaseEvent(event)
            return
        key_name = key_event_to_name(event)

        if key_name == self._get_kb("keybinds/zoom_mode", "Ctrl") and getattr(self, "_zoom_key_held", False):
            self._zoom_key_held = False
            if getattr(self, "_move_key_held", False):
                self.set_interaction_mode("MOVE")
            else:
                self.set_interaction_mode(getattr(self, "_prev_interaction_mode", self.primary_mode))
            return
        elif key_name == self._get_kb("keybinds/move_mode", "Space") and getattr(self, "_move_key_held", False):
            self._move_key_held = False
            if getattr(self, "_zoom_key_held", False):
                self.set_interaction_mode("ZOOM")
            else:
                self.set_interaction_mode(getattr(self, "_prev_interaction_mode", self.primary_mode))
            return
        super().keyReleaseEvent(event)

    # ------------------------------------------------------------------
    # Zoom, Pan & Scrollbars
    # ------------------------------------------------------------------

    def undo_zoom(self):
        if self.zoom_history:
            prev_rect = self.zoom_history.pop()
            self.plot_item.setRange(rect=prev_rect, padding=0)

    def reset_zoom(self):
        self.zoom_history.append(self.plot_item.viewRect())
        self.plot_item.autoRange()

    def reset_zoom_x(self):
        self.zoom_history.append(self.plot_item.viewRect())
        self.plot_item.enableAutoRange(axis="x")

    def reset_zoom_y(self):
        self.zoom_history.append(self.plot_item.viewRect())
        self.plot_item.enableAutoRange(axis="y")

    def handle_zoom_rectangle(self, rect, zoom_type="BOTH", source_vb=None, **kwargs):
        self.zoom_history.append(self.plot_item.viewRect())
        if rect.width() <= 0 and zoom_type != "Y_ONLY":
            return
        if rect.height() <= 0 and zoom_type != "X_ONLY":
            return
        if zoom_type == "Y_ONLY":
            self.plot_item.setYRange(rect.top(), rect.bottom(), padding=0)
        elif zoom_type == "X_ONLY":
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
        is_primary = self.interaction_mode in [self.primary_mode, self.primary_endless_mode]
        is_endless = "ENDLESS" in self.interaction_mode
        if is_endless:
            active_markers = (
                self._get_primary_endless_markers()
                if is_primary
                else self.markers_y_endless_dict.get(self.y_label_text, [])
            )
        else:
            active_markers = (
                self._get_primary_markers()
                if is_primary
                else self.markers_y_dict.get(self.y_label_text, [])
            )

        if len(active_markers) >= 2:
            self.zoom_history.append(self.plot_item.viewRect())
            sorted_m = sorted(active_markers, key=lambda m: m.value())
            v1, v2 = sorted_m[0].value(), sorted_m[-1].value()
            if is_primary:
                self.plot_item.setXRange(v1, v2, padding=0)
            else:
                self.plot_item.setYRange(v1, v2, padding=0)

    def update_scrollbars(self):
        if self._block_signals:
            return
        x_axis = self._get_x_axis()
        if len(x_axis) == 0:
            return
        self._block_signals = True

        xr, yr = self.view_box.viewRange()

        # Primary axis (X)
        x_start, x_end = float(x_axis[0]), float(x_axis[-1])
        x_total = x_end - x_start
        if x_total > 0:
            visible_ratio_x = (xr[1] - xr[0]) / x_total
            if visible_ratio_x < 0.999:
                self.x_scroll.show()
                page_step = max(1, min(1000, int(visible_ratio_x * 1000)))
                self.x_scroll.setRange(0, max(0, 1000 - page_step))
                self.x_scroll.setPageStep(page_step)
                pos = (xr[0] - x_start) / x_total * 1000
                self.x_scroll.setValue(int(np.clip(pos, 0, max(0, 1000 - page_step))))
            else:
                self.x_scroll.hide()

        # Magnitude axis (Y)
        y_min_data, y_max_data = self._get_y_bounds()
        y_range_total = y_max_data - y_min_data
        if y_range_total > 0:
            visible_ratio_y = (yr[1] - yr[0]) / y_range_total
            if visible_ratio_y < 0.999:
                self.y_scroll.show()
                page_step = max(1, min(1000, int(visible_ratio_y * 1000)))
                self.y_scroll.setRange(0, max(0, 1000 - page_step))
                self.y_scroll.setPageStep(page_step)
                pos_from_bottom = (yr[0] - y_min_data) / y_range_total * 1000
                inv_pos = 1000 - page_step - int(pos_from_bottom)
                self.y_scroll.setValue(int(np.clip(inv_pos, 0, max(0, 1000 - page_step))))
            else:
                self.y_scroll.hide()

        self._block_signals = False

    def scroll_view(self):
        if self._block_signals:
            return
        x_axis = self._get_x_axis()
        if len(x_axis) == 0:
            return
        self._block_signals = True

        val_x = self.x_scroll.value()
        val_y = self.y_scroll.value()

        x_start, x_end = float(x_axis[0]), float(x_axis[-1])
        x_total = x_end - x_start

        y_min_data, y_max_data = self._get_y_bounds()
        y_range_total = y_max_data - y_min_data

        xr, yr = self.view_box.viewRange()
        width = xr[1] - xr[0]
        height = yr[1] - yr[0]

        new_left = x_start + (val_x / 1000.0) * x_total
        inv_val_y = 1000 - self.y_scroll.pageStep() - val_y
        new_bottom = y_min_data + (inv_val_y / 1000.0) * y_range_total

        if not self.x_scroll.isHidden():
            self.plot_item.setXRange(new_left, new_left + width, padding=0)
        if not self.y_scroll.isHidden():
            self.plot_item.setYRange(new_bottom, new_bottom + height, padding=0)

        self._block_signals = False

    # ------------------------------------------------------------------
    # Marker Placement, Dragging & Editing
    # ------------------------------------------------------------------

    def handle_lock_change(self, lock_type, checked):
        self.update_marker_info()

    def clear_all_markers(self):
        prim = self._get_primary_markers()
        prim_endless = self._get_primary_endless_markers()
        for m in prim + prim_endless:
            self.plot_item.removeItem(m)
            self._marker_age.pop(m, None)
        prim.clear()
        prim_endless.clear()

        for y_label in self.markers_y_dict:
            for m in self.markers_y_dict[y_label]:
                self.plot_item.removeItem(m)
                self._marker_age.pop(m, None)
            self.markers_y_dict[y_label].clear()

        for y_label in self.markers_y_endless_dict:
            for m in self.markers_y_endless_dict[y_label]:
                self.plot_item.removeItem(m)
            self.markers_y_endless_dict[y_label].clear()

        self.stats_bounds.clear()
        self.stats_marker_order.clear()
        if getattr(self, "stats_region", None):
            self.stats_region.hide()
        if getattr(self, "stats_line", None):
            self.stats_line.hide()
        if getattr(self, "stats_markers", None):
            self.stats_markers.clear()
        if getattr(self, "stats_p10_line", None):
            self.stats_p10_line.hide()
        if getattr(self, "stats_p90_line", None):
            self.stats_p90_line.hide()
        self.marker_panel.clear_stats_fields()

        if hasattr(self, "_clear_filter_state"):
            self._clear_filter_state(replot=True)

        self.toggle_grid(self.primary_mode, False)
        self.toggle_grid("MAG", False)

        self.update_marker_info()

    def _place_stats_bound(self, scene_pos, val, drag_mode):
        if self.stats_bounds:
            best_idx = -1
            min_dist = 20  # pixels
            for i, b_val in enumerate(self.stats_bounds):
                pi = self.view_box.mapViewToScene(pg.Point(b_val, 0))
                dist = abs(scene_pos.x() - pi.x())
                if dist < min_dist:
                    min_dist = dist
                    best_idx = i

            if best_idx != -1:
                self.stats_bounds[best_idx] = val
                self.stats_bounds.sort()
                self.stats_marker_order = list(self.stats_bounds)
                self.active_drag_stats_bound_idx = (
                    self.stats_bounds.index(val) if val in self.stats_bounds else 0
                )
                if len(self.stats_bounds) == 1:
                    if self.stats_line:
                        self.stats_line.setPos(val)
                else:
                    self.stats_region.setRegion(self.stats_bounds)
                self.update_statistics()
                return

        if len(self.stats_marker_order) >= 2:
            oldest_v = self.stats_marker_order.pop(0)
            if oldest_v in self.stats_bounds:
                self.stats_bounds.remove(oldest_v)

        self.stats_marker_order.append(val)
        self.stats_bounds.append(val)
        self.stats_bounds.sort()

        if drag_mode:
            self.active_drag_stats_bound_idx = self.stats_bounds.index(val)

        if len(self.stats_bounds) == 1:
            if getattr(self, "stats_line", None) is None:
                p = get_palette(self._get_theme_name())
                color = (
                    p.marker_freq
                    if (self.primary_mode == "FREQ" and hasattr(p, "marker_freq"))
                    else p.marker_time
                )
                self.stats_line = pg.InfiniteLine(
                    angle=90,
                    pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine),
                    movable=False,
                )
                self.stats_line.setHoverPen(pg.mkPen(255, 0, 0, width=2))
                self.stats_line.setAcceptHoverEvents(True)
                self.stats_line.setZValue(100 if self.primary_mode == "FREQ" else 10)
            if self.stats_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_line)
            self.stats_line.setPos(val)
            self.stats_line.show()
            self.stats_region.hide()
            self.stats_markers.hide()
            if getattr(self, "stats_p10_line", None):
                self.stats_p10_line.hide()
            if getattr(self, "stats_p90_line", None):
                self.stats_p90_line.hide()
        else:
            if self.stats_line:
                self.stats_line.hide()
            self.stats_region.setRegion(self.stats_bounds)
            self.stats_region.show()
            self.stats_markers.show()
            show_p10 = self.marker_panel.cb_p10.isChecked() if hasattr(self.marker_panel, "cb_p10") else True
            show_p90 = self.marker_panel.cb_p90.isChecked() if hasattr(self.marker_panel, "cb_p90") else True
            if getattr(self, "stats_p10_line", None):
                self.stats_p10_line.setVisible(show_p10)
            if getattr(self, "stats_p90_line", None):
                self.stats_p90_line.setVisible(show_p90)

        self.update_statistics()

    def place_marker(self, scene_pos, drag_mode=False, source_vb=None):
        vb = source_vb if source_vb is not None else self.view_box
        v_pos = vb.mapSceneToView(scene_pos)

        if self.interaction_mode == "FILTER" and hasattr(self, "_place_filter_bound"):
            self._place_filter_bound(scene_pos, v_pos, drag_mode)
            return

        is_primary = self.interaction_mode in [self.primary_mode, self.primary_endless_mode, "STATS"]
        is_endless = "ENDLESS" in self.interaction_mode

        x_axis = self._get_x_axis()
        if is_primary:
            c_min, c_max = float(x_axis[0]), float(x_axis[-1])
            val = max(c_min, min(c_max, v_pos.x()))
        else:
            c_min, c_max = self._get_y_bounds()
            val = max(c_min, min(c_max, v_pos.y()))

        if is_endless:
            active_markers = (
                self._get_primary_endless_markers()
                if is_primary
                else self.markers_y_endless_dict[self.y_label_text]
            )
        else:
            active_markers = (
                self._get_primary_markers()
                if is_primary
                else self.markers_y_dict[self.y_label_text]
            )

        if self.interaction_mode == "STATS":
            self._place_stats_bound(scene_pos, val, drag_mode)
            return

        if self.interaction_mode in ["ZOOM", "MOVE"]:
            return

        # 1. Hit-test existing markers
        found_marker = None
        min_dist = float("inf")
        prim_markers = self._get_primary_markers()
        prim_endless_markers = self._get_primary_endless_markers()
        for i, m in enumerate(active_markers):
            is_m_locked = (i == 0 and self.marker_panel.btn_lock_m1.isChecked()) or (
                i == 1 and self.marker_panel.btn_lock_m2.isChecked()
            )
            if is_m_locked and len(active_markers) == 2:
                if not (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                    continue

            m_is_primary = m in prim_markers or m in prim_endless_markers
            m_pixel = self.view_box.mapViewToScene(
                pg.Point(m.value(), 0) if m_is_primary else pg.Point(0, m.value())
            )
            dist = abs(scene_pos.x() - m_pixel.x()) if m_is_primary else abs(scene_pos.y() - m_pixel.y())
            if dist < 20 and dist < min_dist:
                min_dist = dist
                found_marker = m

        if found_marker:
            if len(active_markers) == 2 and (
                self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()
            ):
                old_v = found_marker.value()
                shift = val - old_v
                other = active_markers[0] if active_markers[1] == found_marker else active_markers[1]

                if self.marker_panel.btn_lock_delta.isChecked():
                    new_o = other.value() + shift
                    if c_min <= val <= c_max and c_min <= new_o <= c_max:
                        found_marker.setValue(val)
                        other.setValue(new_o)
                elif self.marker_panel.btn_lock_center.isChecked():
                    ct = (old_v + other.value()) / 2
                    new_o = 2 * ct - val
                    if c_min <= val <= c_max and c_min <= new_o <= c_max:
                        found_marker.setValue(val)
                        other.setValue(new_o)
            else:
                found_marker.setValue(val)

            if drag_mode:
                self.active_drag_marker = found_marker
            self.update_marker_info()
            return

        # 2. Check for Grid Lines (Shadow Markers)
        if self.interaction_mode in [self.primary_mode, "MAG", "Y"]:
            grid_lines = self._get_primary_grid_lines() if is_primary else self.grid_lines_mag
            best_gl = None
            min_gl_dist = 20  # pixels

            for gl in grid_lines:
                gl_pos = gl.value()
                p_scene = self.view_box.mapViewToScene(
                    pg.Point(gl_pos, 0) if is_primary else pg.Point(0, gl_pos)
                )
                dist = abs(scene_pos.x() - p_scene.x()) if is_primary else abs(scene_pos.y() - p_scene.y())
                if dist < min_gl_dist:
                    min_gl_dist = dist
                    best_gl = gl

            if best_gl and len(active_markers) == 2:
                sorted_m = sorted(active_markers, key=lambda m: m.value())
                p1, p2 = sorted_m[0].value(), sorted_m[1].value()
                delta = p2 - p1
                g_pos = best_gl.value()
                k = (g_pos - p1) / delta if delta != 0.0 else 1.0

                lock_m1 = self.marker_panel.btn_lock_m1.isChecked()
                lock_m2 = self.marker_panel.btn_lock_m2.isChecked()
                lock_delta = self.marker_panel.btn_lock_delta.isChecked()
                lock_center = self.marker_panel.btn_lock_center.isChecked()

                move_p1 = k < 0.5
                if lock_m1 and not lock_m2:
                    move_p1 = False
                elif lock_m2 and not lock_m1:
                    move_p1 = True

                if drag_mode:
                    self.active_drag_grid_info = {
                        "k": k,
                        "moving_marker": sorted_m[0] if move_p1 else sorted_m[1],
                        "fixed_marker": sorted_m[1] if move_p1 else sorted_m[0],
                        "is_p1": move_p1,
                        "is_primary": is_primary,
                        "lock_delta": lock_delta,
                        "lock_center": lock_center,
                    }
                    self.active_drag_marker = None
                return

        # 3. Teleport existing markers if clicked outside
        if not is_endless and len(active_markers) == 2:
            m1_pos, m2_pos = active_markers[0].value(), active_markers[1].value()
            lock_m1 = self.marker_panel.btn_lock_m1.isChecked()
            lock_m2 = self.marker_panel.btn_lock_m2.isChecked()
            lock_delta = self.marker_panel.btn_lock_delta.isChecked()
            lock_center = self.marker_panel.btn_lock_center.isChecked()

            if lock_m1 and not lock_m2:
                target, other = active_markers[1], active_markers[0]
                target_idx = 1
            elif lock_m2 and not lock_m1:
                target, other = active_markers[0], active_markers[1]
                target_idx = 0
            else:
                target = min(active_markers, key=lambda m: self._marker_age.get(m, 0))
                other = active_markers[1] if target is active_markers[0] else active_markers[0]
                target_idx = 0 if target is active_markers[0] else 1

            if (target_idx == 0 and lock_m1) or (target_idx == 1 and lock_m2):
                if not (lock_delta or lock_center):
                    return

            shift = val - target.value()
            if lock_delta:
                new_t, new_o = val, other.value() + shift
                if c_min <= new_t <= c_max and c_min <= new_o <= c_max:
                    target.setValue(new_t)
                    other.setValue(new_o)
            elif lock_center:
                ct = (m1_pos + m2_pos) / 2
                new_o = 2 * ct - val
                if c_min <= val <= c_max and c_min <= new_o <= c_max:
                    target.setValue(val)
                    other.setValue(new_o)
            else:
                target.setValue(val)
                if (val > other.value() and target_idx == 0) or (val < other.value() and target_idx == 1):
                    active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                    self.marker_panel.flip_m_lock(self.interaction_mode)

            if not drag_mode:
                self._marker_age[target] = self._marker_age_counter
                self._marker_age_counter += 1
            else:
                self.active_drag_marker = target

            self.update_marker_info()
            return

        # 4. Add brand new marker
        if is_endless and len(active_markers) >= 100:
            return
        elif not is_endless and len(active_markers) >= 2:
            old_m = active_markers.pop(0)
            self.plot_item.removeItem(old_m)

        p = get_palette(self._get_theme_name())
        if is_primary:
            color = p.marker_freq if (self.primary_mode == "FREQ" and hasattr(p, "marker_freq")) else p.marker_time
        else:
            color = p.marker_mag
        orient = 90 if is_primary else 0

        new_m = pg.InfiniteLine(
            pos=val,
            angle=orient,
            pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine),
            movable=False,
        )
        new_m.setHoverPen(pg.mkPen(255, 0, 0, width=2))
        new_m.setAcceptHoverEvents(True)
        new_m.setZValue(100)
        self._marker_age[new_m] = self._marker_age_counter
        self._marker_age_counter += 1

        if is_endless:
            label_text = f"M{len(active_markers)+1}"
            if self.primary_mode == "TIME":
                new_m.label = pg.InfLineLabel(new_m, text=label_text, position=0.95, rotateAxis=(1, 0), anchor=(1, 1))
                new_m.label.setColor(color)
            else:
                new_m.label = pg.InfLineLabel(new_m, text=label_text, position=0.9, color=color)

        active_markers.append(new_m)
        self.plot_item.addItem(new_m, ignoreBounds=True)
        if drag_mode:
            self.active_drag_marker = new_m
        self.update_marker_info()

    def _handle_extra_drag(self, scene_pos, v_pos) -> bool:
        """Hook for subclasses to handle extra drag modes (e.g. FILTER bounds in FrequencyDomainView)."""
        return False

    def update_drag(self, scene_pos, source_vb=None):
        vb = source_vb if source_vb is not None else self.view_box
        v_pos = vb.mapSceneToView(scene_pos)

        if self._handle_extra_drag(scene_pos, v_pos):
            return

        # 1. Handle Shadow Marker (Grid Line) dragging
        if getattr(self, "active_drag_grid_info", None):
            info = self.active_drag_grid_info
            is_primary = info.get("is_primary", info.get("is_time", info.get("is_freq", True)))
            k = info["k"]
            m_move = info["moving_marker"]
            m_fixed = info["fixed_marker"]
            is_p1 = info["is_p1"]
            p_fixed = m_fixed.value()
            lock_delta = info.get("lock_delta", False)
            lock_center = info.get("lock_center", False)

            x_axis = self._get_x_axis()
            if is_primary:
                curr_min, curr_max = float(x_axis[0]), float(x_axis[-1])
                g_prime = max(curr_min, min(curr_max, v_pos.x()))
            else:
                curr_min, curr_max = self._get_y_bounds()
                g_prime = max(curr_min, min(curr_max, v_pos.y()))

            active_markers = (
                self._get_primary_markers()
                if is_primary
                else self.markers_y_dict[self.y_label_text]
            )
            if len(active_markers) == 2:
                try:
                    if lock_delta:
                        sorted_m = sorted(active_markers, key=lambda m: m.value())
                        p1_orig, p2_orig = sorted_m[0].value(), sorted_m[1].value()
                        delta_orig = p2_orig - p1_orig
                        shift = g_prime - (p1_orig + k * delta_orig)

                        shift_min = max(curr_min - p1_orig, curr_min - p2_orig)
                        shift_max = min(curr_max - p1_orig, curr_max - p2_orig)
                        shift_clamped = np.clip(shift, shift_min, shift_max)
                        sorted_m[0].setValue(p1_orig + shift_clamped)
                        sorted_m[1].setValue(p2_orig + shift_clamped)
                    elif lock_center:
                        sorted_m = sorted(active_markers, key=lambda m: m.value())
                        p1_orig, p2_orig = sorted_m[0].value(), sorted_m[1].value()
                        center = (p1_orig + p2_orig) / 2
                        if abs(k - 0.5) > 1e-9:
                            new_delta = (g_prime - center) / (k - 0.5)
                            max_half_delta = min(center - curr_min, curr_max - center)
                            half_delta_clamped = np.clip(abs(new_delta / 2), 0.0, max_half_delta)
                            sorted_m[0].setValue(center - half_delta_clamped)
                            sorted_m[1].setValue(center + half_delta_clamped)
                    else:
                        if is_p1:
                            if abs(1 - k) > 1e-9:
                                new_v = (g_prime - k * p_fixed) / (1 - k)
                                if curr_min <= new_v <= curr_max:
                                    m_move.setValue(new_v)
                        else:
                            if abs(k) > 1e-9:
                                new_v = p_fixed + (g_prime - p_fixed) / k
                                if curr_min <= new_v <= curr_max:
                                    m_move.setValue(new_v)

                    if active_markers[0].value() > active_markers[1].value():
                        active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                        self.marker_panel.flip_m_lock(self.interaction_mode)
                except ZeroDivisionError:
                    pass

            self.update_marker_info()
            return

        # 2. Handle STATS Region bound dragging
        if self.interaction_mode == "STATS" or getattr(self, "active_drag_stats_bound_idx", -1) != -1:
            if getattr(self, "active_drag_stats_bound_idx", -1) != -1:
                idx = self.active_drag_stats_bound_idx
                x_axis = self._get_x_axis()
                x_min, x_max = float(x_axis[0]), float(x_axis[-1])
                val = max(x_min, min(x_max, v_pos.x()))

                if len(self.stats_bounds) == 2:
                    self.stats_bounds[idx] = val
                    self.stats_bounds.sort()
                    if val in self.stats_bounds:
                        self.active_drag_stats_bound_idx = self.stats_bounds.index(val)
                    self.stats_region.setRegion(self.stats_bounds)
                elif len(self.stats_bounds) == 1:
                    self.stats_bounds[0] = val
                    if self.stats_line:
                        self.stats_line.setPos(val)

                self.update_statistics()
            if self.interaction_mode == "STATS":
                return

        # 3. Handle regular/endless marker dragging
        if not getattr(self, "active_drag_marker", None):
            return

        prim_markers = self._get_primary_markers()
        prim_endless_markers = self._get_primary_endless_markers()
        is_primary = self.active_drag_marker in prim_markers or self.active_drag_marker in prim_endless_markers
        is_endless = "ENDLESS" in self.interaction_mode

        x_axis = self._get_x_axis()
        if is_primary:
            curr_min, curr_max = float(x_axis[0]), float(x_axis[-1])
            val = max(curr_min, min(curr_max, v_pos.x()))
        else:
            curr_min, curr_max = self._get_y_bounds()
            val = max(curr_min, min(curr_max, v_pos.y()))

        if is_endless:
            active_markers = (
                prim_endless_markers
                if is_primary
                else self.markers_y_endless_dict[self.y_label_text]
            )
        else:
            active_markers = (
                prim_markers
                if is_primary
                else self.markers_y_dict[self.y_label_text]
            )

        if not is_endless and len(active_markers) == 2:
            other = active_markers[0] if active_markers[1] == self.active_drag_marker else active_markers[1]
            target_idx = 0 if self.active_drag_marker == active_markers[0] else 1

            lock_target = (
                self.marker_panel.btn_lock_m1.isChecked()
                if target_idx == 0
                else self.marker_panel.btn_lock_m2.isChecked()
            )
            lock_delta = self.marker_panel.btn_lock_delta.isChecked()
            lock_center = self.marker_panel.btn_lock_center.isChecked()

            if lock_target:
                return

            shift = val - self.active_drag_marker.value()
            if lock_delta:
                potential_other = other.value() + shift
                potential_other_clamped = np.clip(potential_other, curr_min, curr_max)
                actual_shift = potential_other_clamped - other.value()
                self.active_drag_marker.setValue(self.active_drag_marker.value() + actual_shift)
                other.setValue(potential_other_clamped)
            elif lock_center:
                ct = (self.active_drag_marker.value() + other.value()) / 2
                potential_other = 2 * ct - val
                potential_other_clamped = np.clip(potential_other, curr_min, curr_max)
                self.active_drag_marker.setValue(2 * ct - potential_other_clamped)
                other.setValue(potential_other_clamped)
            else:
                self.active_drag_marker.setValue(val)
                if (val > other.value() and target_idx == 0) or (val < other.value() and target_idx == 1):
                    active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                    self.marker_panel.flip_m_lock(self.interaction_mode)
        else:
            self.active_drag_marker.setValue(val)
        self.update_marker_info()

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        eff_mode = self.interaction_mode
        if eff_mode in ["ZOOM", "MOVE"]:
            eff_mode = getattr(self.marker_panel, "last_marker_mode", self.primary_mode)
        is_primary = eff_mode in [self.primary_mode, self.primary_endless_mode]

        try:
            val = float(sender.text())
            x_axis = self._get_x_axis()
            if is_primary:
                curr_min, curr_max = float(x_axis[0]), float(x_axis[-1])
            else:
                curr_min, curr_max = self._get_y_bounds()

            if name.startswith("em_"):
                parts = name.split("_")
                idx = int(parts[1])
                unit = parts[2]
                active_list = (
                    self._get_primary_endless_markers()
                    if is_primary
                    else self.markers_y_endless_dict[self.y_label_text]
                )
                if idx < len(active_list):
                    m = active_list[idx]
                    if is_primary and unit in ("sam", "bin"):
                        new_p = np.clip(self._sub_unit_to_primary_val(val), curr_min, curr_max)
                    else:
                        new_p = np.clip(val, curr_min, curr_max)
                    m.setPos(new_p)
                self.update_marker_info()
                return

            if name.startswith("st_"):
                if not self.stats_bounds:
                    return
                x_min, x_max = float(x_axis[0]), float(x_axis[-1])
                if "m" in name:
                    idx = int(name[4])
                    if idx >= len(self.stats_bounds):
                        return
                    new_p = self._sub_unit_to_primary_val(val) if "v2" in name else val
                    new_p = float(np.clip(new_p, x_min, x_max))
                    self.stats_bounds[idx] = new_p
                elif "delta" in name:
                    if len(self.stats_bounds) != 2:
                        return
                    dv = self._sub_delta_to_primary_delta(val) if "v2" in name else val
                    ct = sum(self.stats_bounds) / 2
                    self.stats_bounds = [ct - dv / 2, ct + dv / 2]
                elif "center" in name:
                    if len(self.stats_bounds) != 2:
                        return
                    ct = self._sub_unit_to_primary_val(val) if "v2" in name else val
                    dv = abs(self.stats_bounds[1] - self.stats_bounds[0])
                    self.stats_bounds = [ct - dv / 2, ct + dv / 2]

                self.stats_bounds.sort()
                if len(self.stats_bounds) == 1:
                    if self.stats_line:
                        self.stats_line.setPos(self.stats_bounds[0])
                else:
                    self.stats_region.setRegion(self.stats_bounds)
                self.update_statistics()
                return

            active_markers = (
                self._get_primary_markers()
                if is_primary
                else self.markers_y_dict[self.y_label_text]
            )
            sorted_markers = sorted(active_markers, key=lambda m: m.value())

            if name.startswith("m"):
                idx = int(name[1])
                if idx >= len(sorted_markers):
                    return

                new_p = self._sub_unit_to_primary_val(val) if ("v2" in name and is_primary) else val
                new_p = float(np.clip(new_p, curr_min, curr_max))

                if len(sorted_markers) == 2:
                    other_idx = 1 - idx
                    shift = new_p - sorted_markers[idx].value()
                    if self.marker_panel.btn_lock_delta.isChecked():
                        new_o = sorted_markers[other_idx].value() + shift
                        if curr_min <= new_o <= curr_max:
                            sorted_markers[idx].setValue(new_p)
                            sorted_markers[other_idx].setValue(new_o)
                    elif self.marker_panel.btn_lock_center.isChecked():
                        ct = (sorted_markers[0].value() + sorted_markers[1].value()) / 2
                        new_o = 2 * ct - new_p
                        if curr_min <= new_o <= curr_max:
                            sorted_markers[idx].setValue(new_p)
                            sorted_markers[other_idx].setValue(new_o)
                    else:
                        sorted_markers[idx].setValue(new_p)
                else:
                    sorted_markers[idx].setValue(new_p)

            elif len(sorted_markers) == 2:
                p1, p2 = sorted_markers[0].value(), sorted_markers[1].value()
                if "delta" in name:
                    dv = self._sub_delta_to_primary_delta(val) if ("v2" in name and is_primary) else val
                    sorted_markers[0].setValue((p1 + p2) / 2 - dv / 2)
                    sorted_markers[1].setValue((p1 + p2) / 2 + dv / 2)
                elif "center" in name:
                    ct = self._sub_unit_to_primary_val(val) if ("v2" in name and is_primary) else val
                    dv = abs(p2 - p1)
                    sorted_markers[0].setValue(ct - dv / 2)
                    sorted_markers[1].setValue(ct + dv / 2)

            self.update_marker_info()
        except Exception:
            pass

    def handle_marker_clear(self, mode):
        if mode == self.primary_mode:
            prim = self._get_primary_markers()
            for m in prim:
                self.plot_item.removeItem(m)
                self._marker_age.pop(m, None)
            prim.clear()
            self.marker_panel._clear_marker_locks(self.primary_mode)
            self.toggle_grid(self.primary_mode, False)
        elif mode == self.primary_endless_mode:
            prim_endless = self._get_primary_endless_markers()
            for m in prim_endless:
                self.plot_item.removeItem(m)
            prim_endless.clear()
        elif mode == "MAG_ENDLESS":
            active_list = self.markers_y_endless_dict.get(self.y_label_text, [])
            for m in active_list:
                self.plot_item.removeItem(m)
            active_list.clear()
        elif mode == "STATS":
            self.stats_bounds.clear()
            self.stats_marker_order.clear()
            if getattr(self, "stats_line", None):
                self.plot_item.removeItem(self.stats_line)
                self.stats_line = None
            self.stats_region.hide()
            self.stats_markers.hide()
            if getattr(self, "stats_p10_line", None):
                self.stats_p10_line.hide()
            if getattr(self, "stats_p90_line", None):
                self.stats_p90_line.hide()
            self.marker_panel.clear_stats_fields()
        elif mode == "FILTER" and hasattr(self, "_clear_filter_state"):
            self._clear_filter_state(replot=True)
        else:  # 'Y' / 'MAG'
            active_list = self.markers_y_dict.get(self.y_label_text, [])
            for m in active_list:
                self.plot_item.removeItem(m)
                self._marker_age.pop(m, None)
            active_list.clear()
            self.marker_panel._clear_marker_locks("MAG")
            self.toggle_grid("MAG", False)
        self.update_marker_info()

    def remove_marker_item(self, marker, mode):
        if marker in self.plot_item.items:
            self.plot_item.removeItem(marker)

        is_primary = self.primary_mode in mode
        active_list = (
            self._get_primary_endless_markers()
            if is_primary
            else self.markers_y_endless_dict[self.y_label_text]
        )

        if marker in active_list:
            active_list.remove(marker)
            for i, m in enumerate(active_list):
                if hasattr(m, "label"):
                    m.label.setFormat(f"M{i+1}")

        self.update_marker_info()

    # ------------------------------------------------------------------
    # Shadow Marker Grid
    # ------------------------------------------------------------------

    def toggle_grid(self, axis, enabled):
        if axis == self.primary_mode:
            self._set_primary_grid_enabled(enabled)
        else:
            self.grid_mag_enabled = enabled
        self.update_grid(axis, force=True)

    def toggle_tracking(self, axis, enabled):
        if axis == self.primary_mode:
            self._set_primary_grid_tracking(enabled)
        else:
            self.grid_mag_tracking = enabled
        self.update_grid(axis, force=True)

    def update_grid(self, axis, force=False):
        if not hasattr(self, "_grid_timer"):
            self._grid_timer = QTimer()
            self._grid_timer.setSingleShot(True)
            self._grid_timer.timeout.connect(self._do_update_grid)
            self._grid_pending_axes = set()

        if force:
            self._do_update_grid(axis, force=True)
        else:
            self._grid_pending_axes.add(axis)
            if not self._grid_timer.isActive():
                self._grid_timer.start(50)  # 50ms throttle

    def _do_update_grid(self, axis=None, force=False):
        if axis is None:
            axes_to_update = list(self._grid_pending_axes)
            self._grid_pending_axes.clear()
            for a in axes_to_update:
                self._do_update_grid(a, force=force)
            return

        is_primary = axis == self.primary_mode
        enabled = self._is_primary_grid_enabled() if is_primary else self.grid_mag_enabled
        tracking = self._is_primary_grid_tracking() if is_primary else self.grid_mag_tracking
        active_markers = (
            self._get_primary_markers()
            if is_primary
            else self.markers_y_dict.get(self.y_label_text, [])
        )
        grid_lines = self._get_primary_grid_lines() if is_primary else self.grid_lines_mag

        if not enabled:
            for line in grid_lines:
                self.plot_item.removeItem(line)
            grid_lines.clear()
            return
        if not tracking and not force:
            return
        for line in grid_lines:
            self.plot_item.removeItem(line)
        grid_lines.clear()
        if len(active_markers) != 2:
            return

        sorted_m = sorted(active_markers, key=lambda m: m.value())
        p1, p2 = sorted_m[0].value(), sorted_m[1].value()
        delta = abs(p2 - p1)
        if delta <= 0:
            return

        vr = self.plot_item.viewRange()
        v_min_visible, v_max_visible = vr[0] if is_primary else vr[1]

        if (v_max_visible - v_min_visible) / delta > 500:
            return

        angle = 90 if is_primary else 0
        s = getattr(self, "settings_mgr", None) or getattr(self.parent_window, "settings_mgr", None)
        theme = self._get_theme_name()
        color = s.get(f"ui/{theme}/marker_grid_color", "#c8c8ff") if s else "#c8c8ff"
        style_name = s.get(f"ui/{theme}/marker_grid_style", "SolidLine") if s else "SolidLine"
        alpha = int(s.get("ui/marker_grid_alpha", 50)) if s else 50
        width = int(s.get("ui/marker_grid_width", 1)) if s else 1

        style_map = {
            "SolidLine": Qt.PenStyle.SolidLine,
            "DashLine": Qt.PenStyle.DashLine,
            "DotLine": Qt.PenStyle.DotLine,
            "DashDotLine": Qt.PenStyle.DashDotLine,
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

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from ..themes import get_palette


class FrequencyDomainFilterMixin:
    """
    Mixin managing the BPF/BSF filter region and zero-phase filtering pipeline for FrequencyDomainView.
    """

    def init_filter(self):
        self.filter_bounds = []
        self.filter_marker_order = []
        self.filter_placed = False
        self.filter_mode = None
        self._filtered_samples = None
        self.active_drag_filter_bound_idx = -1
        self.filter_line = None

        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)

        self.filter_region = pg.LinearRegionItem(
            values=[0, 0],
            orientation='vertical',
            brush=pg.mkBrush(255, 100, 0, 40),
            pen=pg.mkPen('#ff6400', width=2),
            movable=False
        )
        self.filter_region.sigRegionChanged.connect(self._on_filter_changed)
        self.filter_region.sigRegionChangeFinished.connect(self.on_filter_region_finished)
        self.plot_item.addItem(self.filter_region)
        self.filter_region.hide()

        self.filter_bounds.clear()
        self.filter_marker_order.clear()

    def _place_filter_bound(self, scene_pos, v_pos, drag_mode):
        f_min, f_max = self._get_primary_bounds()
        val = max(f_min, min(f_max, v_pos.x()))

        # If 2 bounds exist and Delta or Center is locked: teleport nearest bound & preserve lock
        if len(self.filter_bounds) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
            sorted_bounds = sorted(self.filter_bounds)
            b0, b1 = sorted_bounds[0], sorted_bounds[1]

            if self.marker_panel.btn_lock_delta.isChecked():
                delta = b1 - b0
                dist0 = abs(val - b0)
                dist1 = abs(val - b1)
                if dist0 <= dist1:
                    new_b0 = val
                    new_b1 = val + delta
                    if new_b1 > f_max:
                        new_b1 = f_max
                        new_b0 = f_max - delta
                    if new_b0 < f_min:
                        new_b0 = f_min
                        new_b1 = f_min + delta
                    self.active_drag_filter_bound_idx = 0
                else:
                    new_b1 = val
                    new_b0 = val - delta
                    if new_b0 < f_min:
                        new_b0 = f_min
                        new_b1 = f_min + delta
                    if new_b1 > f_max:
                        new_b1 = f_max
                        new_b0 = f_max - delta
                    self.active_drag_filter_bound_idx = 1
                self.filter_bounds = [new_b0, new_b1]
            elif self.marker_panel.btn_lock_center.isChecked():
                center = (b0 + b1) / 2
                half_delta = abs(val - center)
                max_half_delta = min(center - f_min, f_max - center)
                half_delta = min(half_delta, max_half_delta)
                new_b0 = center - half_delta
                new_b1 = center + half_delta
                self.filter_bounds = [new_b0, new_b1]
                self.active_drag_filter_bound_idx = 0 if val < center else 1

            self.filter_marker_order = list(self.filter_bounds)
            if self.filter_region:
                self.filter_region.setRegion(self.filter_bounds)
                self.filter_region.show()
            if self.filter_line: self.filter_line.hide()
            self.filter_placed = True
            if hasattr(self.marker_panel, 'set_filter_checkboxes_enabled'):
                self.marker_panel.set_filter_checkboxes_enabled(True)
            self.update_marker_info()
            return

        # Hit-test existing bounds within 20 screen-pixels
        if self.filter_bounds:
            view_range = self.plot_item.viewRange()[0]
            view_width = self.plot_item.vb.width()
            if view_width > 0:
                px_per_hz = view_width / max(view_range[1] - view_range[0], 1e-20)
                HIT_PX = 20.0
                best_idx, best_dist = -1, float('inf')
                for i, bv in enumerate(self.filter_bounds):
                    dist = abs(val - bv) * px_per_hz
                    if dist < HIT_PX and dist < best_dist:
                        best_dist, best_idx = dist, i
                if best_idx != -1:
                    old_v = self.filter_bounds[best_idx]
                    self.filter_bounds[best_idx] = val
                    if old_v in self.filter_marker_order:
                        oidx = self.filter_marker_order.index(old_v)
                        self.filter_marker_order[oidx] = val
                    self.filter_bounds.sort()
                    try:
                        self.active_drag_filter_bound_idx = self.filter_bounds.index(val)
                    except ValueError:
                        self.active_drag_filter_bound_idx = 0
                    if len(self.filter_bounds) == 1:
                        if self.filter_line: self.filter_line.setPos(val)
                    else:
                        if self.filter_region: self.filter_region.setRegion(self.filter_bounds)
                    self.update_marker_info()
                    return

        # FIFO: replace oldest when 2 bounds already placed
        if len(self.filter_bounds) >= 2:
            if len(self.filter_marker_order) > 0:
                oldest_v = self.filter_marker_order.pop(0)
                if oldest_v in self.filter_bounds:
                    self.filter_bounds.remove(oldest_v)
            else:
                self.filter_bounds.pop(0)

        self.filter_bounds.append(val)
        self.filter_marker_order.append(val)
        self.filter_bounds.sort()
        try:
            self.active_drag_filter_bound_idx = self.filter_bounds.index(val)
        except ValueError:
            self.active_drag_filter_bound_idx = 0

        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)

        if len(self.filter_bounds) == 1:
            if self.filter_line is None:
                self.filter_line = pg.InfiniteLine(
                    pos=val, angle=90,
                    pen=pg.mkPen(p.accent, width=2, style=Qt.PenStyle.DashLine),
                    movable=False
                )
                self.filter_line.setZValue(9)
                self.plot_item.addItem(self.filter_line)
            else:
                self.filter_line.setPos(val)
                self.filter_line.show()
            self.filter_region.hide()
            self.filter_placed = False
        elif len(self.filter_bounds) == 2:
            if self.filter_line: self.filter_line.hide()
            self.filter_region.setRegion(self.filter_bounds)
            self.filter_region.show()
            self.filter_placed = True
            if hasattr(self.marker_panel, 'set_filter_checkboxes_enabled'):
                self.marker_panel.set_filter_checkboxes_enabled(True)

        self.update_marker_info()

    def _update_filter_drag(self, v_pos):
        if getattr(self, 'active_drag_filter_bound_idx', -1) == -1:
            return False

        idx = self.active_drag_filter_bound_idx
        f_min, f_max = self._get_primary_bounds()
        val = max(f_min, min(f_max, v_pos.x()))

        if len(self.filter_bounds) == 2:
            b0, b1 = self.filter_bounds[0], self.filter_bounds[1]
            if self.marker_panel.btn_lock_delta.isChecked():
                delta = b1 - b0
                if idx == 0:
                    new_b0 = val
                    new_b1 = new_b0 + delta
                    if new_b1 > f_max:
                        new_b1 = f_max
                        new_b0 = f_max - delta
                    if new_b0 < f_min:
                        new_b0 = f_min
                        new_b1 = f_min + delta
                    self.active_drag_filter_bound_idx = 0
                else:
                    new_b1 = val
                    new_b0 = new_b1 - delta
                    if new_b0 < f_min:
                        new_b0 = f_min
                        new_b1 = f_min + delta
                    if new_b1 > f_max:
                        new_b1 = f_max
                        new_b0 = f_max - delta
                    self.active_drag_filter_bound_idx = 1
                self.filter_bounds = [new_b0, new_b1]
            elif self.marker_panel.btn_lock_center.isChecked():
                center = (b0 + b1) / 2
                half_delta = abs(val - center)
                max_half_delta = min(center - f_min, f_max - center)
                half_delta = min(half_delta, max_half_delta)
                new_b0 = center - half_delta
                new_b1 = center + half_delta
                self.filter_bounds = [new_b0, new_b1]
                self.active_drag_filter_bound_idx = 0 if val < center else 1
            else:
                self.filter_bounds[idx] = val
                self.filter_bounds.sort()
                try:
                    self.active_drag_filter_bound_idx = self.filter_bounds.index(val)
                except ValueError:
                    pass

            self.filter_marker_order = list(self.filter_bounds)
            if self.filter_region: self.filter_region.setRegion(self.filter_bounds)
        elif len(self.filter_bounds) == 1:
            self.filter_bounds[0] = val
            if self.filter_line: self.filter_line.setPos(val)

        self.update_marker_info()
        return True

    def _clear_filter_state(self, replot=False):
        self.filter_bounds.clear()
        self.filter_marker_order.clear()
        self.filter_placed = False
        self.filter_mode = None
        self._filtered_samples = None
        self.active_drag_filter_bound_idx = -1
        if self.filter_region: self.filter_region.hide()
        if self.filter_line: self.filter_line.hide()
        if hasattr(self.marker_panel, 'set_filter_checkboxes_enabled'):
            self.marker_panel.set_filter_checkboxes_enabled(False)
        if hasattr(self.marker_panel, 'cb_bpf'):
            self.marker_panel.cb_bpf.setChecked(False)
            self.marker_panel.cb_bsf.setChecked(False)
        if replot:
            self._apply_filter_and_replot()

    def on_filter_mode_changed(self, mode):
        self.filter_mode = mode if mode else None
        self._apply_filter_and_replot()

    def _apply_filter_and_replot(self):
        saved_mode = getattr(self, '_current_plot_mode_key', 'magnitude')
        if (self.filter_mode in ('bpf', 'bsf')
                and len(self.filter_bounds) == 2
                and hasattr(self, 'samples') and len(self.samples) > 0):
            from iqview.dsp import apply_filter
            sb = sorted(self.filter_bounds)
            f1_rel = sb[0] - self.center_freq
            f2_rel = sb[1] - self.center_freq
            try:
                self._filtered_samples = apply_filter(
                    self.samples, self.rate, f1_rel, f2_rel, mode=self.filter_mode
                )
            except Exception as e:
                print(f"[FrequencyDomainView] Filter error: {e}")
                self._filtered_samples = None
        else:
            self._filtered_samples = None

        self.compute_fft()
        available = getattr(self, 'available_modes', {})
        target = saved_mode if saved_mode in available else 'magnitude'
        if target in available:
            available[target]()

    def _on_filter_changed(self, region):
        if not getattr(self, 'filter_placed', False) and len(self.filter_bounds) < 2:
            return
        r = region.getRegion()
        self.filter_bounds = sorted(list(r))
        self.update_marker_info()

    def on_filter_region_finished(self):
        if self.filter_mode in ('bpf', 'bsf') and self.filter_placed:
            self._apply_filter_and_replot()

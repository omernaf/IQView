import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from ..themes import get_palette


class AnalysisStatsMixin:
    """
    Unified 1D Region Statistics Engine for Time Domain and Frequency Domain analysis views.
    Handles statistics region boundaries, calculation of percentiles/means/extrema, and visual indicators.
    """

    def init_statistics(self):
        """Initialize statistics items and state."""
        self.stats_bounds = []
        self.stats_marker_order = []
        self.stats_line = None
        self.active_drag_stats_bound_idx = -1

        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)

        self.stats_region = pg.LinearRegionItem(
            values=[0, 0],
            orientation='vertical',
            brush=pg.mkBrush(255, 100, 0, 40),
            pen=pg.mkPen('#ff6400', width=2),
            movable=False
        )
        self.stats_region.sigRegionChanged.connect(self.update_statistics)
        self.plot_item.addItem(self.stats_region)
        self.stats_region.hide()

        self.stats_markers = pg.ScatterPlotItem(size=10)
        self.plot_item.addItem(self.stats_markers)
        self.stats_markers.hide()

    # -------------------------------------------------------------------------
    # Bound Placement & Dragging
    # -------------------------------------------------------------------------
    def _place_stats_bound(self, scene_pos, v_pos, drag_mode):
        p_min, p_max = self._get_primary_bounds()
        val = max(p_min, min(p_max, v_pos.x()))

        # Hit-test existing bounds within 20 screen-pixels
        if self.stats_bounds:
            min_dist = 20
            best_idx = -1
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
                self.active_drag_stats_bound_idx = self.stats_bounds.index(val) if val in self.stats_bounds else 0

                if len(self.stats_bounds) == 1:
                    if self.stats_line: self.stats_line.setPos(val)
                else:
                    self.stats_region.setRegion(self.stats_bounds)
                self.update_statistics()
                return

        # FIFO: replace oldest if 2 bounds already placed
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
            if getattr(self, 'stats_line', None) is None:
                theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
                p = get_palette(theme)
                self.stats_line = pg.InfiniteLine(
                    angle=90,
                    pen=pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine),
                    movable=False
                )
                self.stats_line.setHoverPen(pg.mkPen(255, 0, 0, width=2))
                self.stats_line.setAcceptHoverEvents(True)
                self.stats_line.setZValue(10)
            if self.stats_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_line)
            self.stats_line.setPos(val)
            self.stats_line.show()
            self.stats_region.hide()
            self.stats_markers.hide()
        else:
            if self.stats_line: self.stats_line.hide()
            self.stats_region.setRegion(self.stats_bounds)
            self.stats_region.show()
            self.stats_markers.show()

        self.update_statistics()

    def _update_stats_drag(self, v_pos):
        if getattr(self, 'active_drag_stats_bound_idx', -1) == -1:
            return

        idx = self.active_drag_stats_bound_idx
        p_min, p_max = self._get_primary_bounds()
        val = max(p_min, min(p_max, v_pos.x()))

        if len(self.stats_bounds) == 2:
            self.stats_bounds[idx] = val
            self.stats_bounds.sort()
            if val in self.stats_bounds:
                self.active_drag_stats_bound_idx = self.stats_bounds.index(val)
            self.stats_region.setRegion(self.stats_bounds)
        else:
            self.stats_bounds[0] = val
            if self.stats_line: self.stats_line.setPos(val)

        self.update_statistics()

    def _clear_stats(self):
        self.stats_bounds.clear()
        self.stats_marker_order.clear()
        if hasattr(self, 'stats_line') and self.stats_line:
            self.plot_item.removeItem(self.stats_line)
            self.stats_line = None
        self.stats_region.hide()
        self.stats_markers.hide()
        self.stats_markers.clear()

    # -------------------------------------------------------------------------
    # Statistics Computation
    # -------------------------------------------------------------------------
    def update_statistics(self):
        """Calculates Min, Max, Mean, Median, Percentiles for the active region."""
        if not self.stats_region.isVisible() or len(self.current_plot_data) == 0:
            return

        r_min, r_max = self.stats_region.getRegion()
        axis = getattr(self, 'time_axis', getattr(self, 'freq_axis', None))
        if axis is None or len(axis) == 0:
            return

        i_min = np.searchsorted(axis, r_min)
        i_max = np.searchsorted(axis, r_max)

        i_min = max(0, min(len(axis) - 1, i_min))
        i_max = max(0, min(len(axis), i_max))

        if i_min >= i_max:
            return

        slice_data = self.current_plot_data[i_min:i_max]
        if len(slice_data) == 0:
            return

        p_max = float(np.max(slice_data))
        p_min = float(np.min(slice_data))
        p_median = float(np.median(slice_data))
        p_10, p_90 = np.percentile(slice_data, [10, 90])
        p_diff = float(p_90 - p_10)

        # Mean Calculation: For dB plots, average in linear power domain
        if "[dB]" in self.y_label_text:
            factor = 10 if "magnitude^2" in self.y_label_text.lower() or "psd" in self.y_label_text.lower() else 20
            lin_data = 10 ** (slice_data / factor)
            lin_mean = np.mean(lin_data)
            p_mean = float(factor * np.log10(lin_mean + 1e-15))
        else:
            p_mean = float(np.mean(slice_data))

        idx_max = int(i_min + np.argmax(slice_data))
        idx_min = int(i_min + np.argmin(slice_data))
        x_max = axis[idx_max]
        x_min = axis[idx_min]

        # Update Marker Panel Region Definition & Results
        b1, b2 = sorted([r_min, r_max])
        self._format_stats_region_readouts(b1, b2)

        mp = self.marker_panel
        mp.stats_max_val.setText(f"{p_max:.6g}")
        mp.stats_min_val.setText(f"{p_min:.6g}")
        mp.stats_mean_val.setText(f"{p_mean:.6g}")
        mp.stats_median_val.setText(f"{p_median:.6g}")
        mp.stats_90th_val.setText(f"{p_90:.6g}")
        mp.stats_10th_val.setText(f"{p_10:.6g}")
        mp.stats_diff_val.setText(f"{p_diff:.6g}")

        if hasattr(mp, 'stats_max_time'):
            mp.stats_max_time.setText(f"{x_max:.6f}")
            mp.stats_min_time.setText(f"{x_min:.6f}")
        elif hasattr(mp, 'stats_max_freq'):
            mp.stats_max_freq.setText(f"{x_max:.6f}")
            mp.stats_min_freq.setText(f"{x_min:.6f}")

        if hasattr(mp, 'stats_max_idx'):
            mp.stats_max_idx.setText(f"{idx_max}")
        if hasattr(mp, 'stats_min_idx'):
            mp.stats_min_idx.setText(f"{idx_min}")
        if hasattr(mp, 'stats_max_bin'):
            mp.stats_max_bin.setText(f"{idx_max}")
        if hasattr(mp, 'stats_min_bin'):
            mp.stats_min_bin.setText(f"{idx_min}")

        if hasattr(mp, 'stats_total_power'):
            if "[dB]" in self.y_label_text:
                factor = 10 if "magnitude^2" in self.y_label_text.lower() or "psd" in self.y_label_text.lower() else 20
                lin_data = 10 ** (slice_data / factor)
                tot_lin = np.sum(lin_data)
                tot_db = factor * np.log10(tot_lin + 1e-15)
                mp.stats_total_power.setText(f"{tot_db:.6g}")
            else:
                total_power = float(np.sum(slice_data))
                mp.stats_total_power.setText(f"{total_power:.6g}")

        # Update graphical scatter indicators
        self.stats_markers.setData([
            {'pos': (x_max, p_max), 'brush': pg.mkBrush(255, 50, 50), 'pen': pg.mkPen('#ff3232', width=2), 'symbol': 'o'},
            {'pos': (x_min, p_min), 'brush': pg.mkBrush(50, 255, 50), 'pen': pg.mkPen('#32ff32', width=2), 'symbol': 't'}
        ])

    def _format_stats_region_readouts(self, b1, b2):
        """Populate stats region bounds table. Override in subclass for domain readouts."""
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9)) if self.settings_mgr else 9
        for i, val in enumerate([b1, b2]):
            w = self.marker_panel.st_widgets[i]
            w['v1'].blockSignals(True); w['v1'].setText(f"{val:.{prec1}f}"); w['v1'].blockSignals(False)

        dv = abs(b2 - b1)
        cv = (b1 + b2) / 2
        self.marker_panel.st_delta_v1.blockSignals(True); self.marker_panel.st_delta_v1.setText(f"{dv:.{prec1}f}"); self.marker_panel.st_delta_v1.blockSignals(False)
        self.marker_panel.st_center_v1.blockSignals(True); self.marker_panel.st_center_v1.setText(f"{cv:.{prec1}f}"); self.marker_panel.st_center_v1.blockSignals(False)

    def _parse_stats_edit(self, name, val, curr_min, curr_max):
        """Parse manual table edit on stats region."""
        if not self.stats_bounds: return
        if 'm' in name:
            idx = int(name[4])
            if idx >= len(self.stats_bounds): return
            new_p = self._parse_marker_value_by_unit(val, 'v2' if 'v2' in name else 'v1', True, curr_min, curr_max)
            self.stats_bounds[idx] = new_p
        elif 'delta' in name:
            if len(self.stats_bounds) != 2: return
            dv = self._parse_delta_value_by_unit(val, 'v2' if 'v2' in name else 'v1', True)
            ct = sum(self.stats_bounds) / 2
            self.stats_bounds = [ct - dv/2, ct + dv/2]
        elif 'center' in name:
            if len(self.stats_bounds) != 2: return
            ct = self._parse_marker_value_by_unit(val, 'v2' if 'v2' in name else 'v1', True, curr_min, curr_max)
            dv = abs(self.stats_bounds[1] - self.stats_bounds[0])
            self.stats_bounds = [ct - dv/2, ct + dv/2]

        self.stats_bounds.sort()
        self.stats_region.setRegion(self.stats_bounds)
        self.update_statistics()

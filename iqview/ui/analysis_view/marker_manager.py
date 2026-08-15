import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel
from ..themes import get_palette


class AnalysisMarkerMixin:
    """
    Unified 1D Marker Engine for Time Domain and Frequency Domain analysis views.
    Handles marker placement, dragging, delta/center locks, shadow markers, endless markers,
    and marker table synchronization with zero code duplication.
    """

    def init_markers(self):
        """Initialize marker data structures."""
        self.markers_primary = []
        self.markers_primary_endless = []

        # Mode-specific Magnitude/Y markers
        self.markers_y_dict = {
            "Real": [], "Real [dB]": [],
            "real": [], "real [dB]": [],
            "Imaginary": [], "Imaginary [dB]": [],
            "imag": [], "imag [dB]": [],
            "Phase": [], "phase": [],
            "Unwrapped phase": [], "unwrapped phase": [],
            "instant frequency": [],
            "magnitude": [], "magnitude [dB]": [],
            "magnitude^2": [], "magnitude^2 [dB]": [],
            "PSD [dB]": [], "power spectrum density (PSD)": []
        }
        self.markers_y_endless_dict = {k: [] for k in self.markers_y_dict.keys()}

        # Age tracking for FIFO marker replacement on click
        self._marker_age = {}
        self._marker_age_counter = 0

        self.active_drag_marker = None
        self.active_drag_grid_info = None

    # -------------------------------------------------------------------------
    # Backward compatibility properties
    # -------------------------------------------------------------------------
    @property
    def markers_time(self): return self.markers_primary
    @markers_time.setter
    def markers_time(self, val): self.markers_primary = val

    @property
    def markers_freq(self): return self.markers_primary
    @markers_freq.setter
    def markers_freq(self, val): self.markers_primary = val

    @property
    def markers_time_endless(self): return self.markers_primary_endless
    @markers_time_endless.setter
    def markers_time_endless(self, val): self.markers_primary_endless = val

    @property
    def markers_freq_endless(self): return self.markers_primary_endless
    @markers_freq_endless.setter
    def markers_freq_endless(self, val): self.markers_primary_endless = val

    @property
    def grid_lines_time(self): return self.grid_lines_primary
    @grid_lines_time.setter
    def grid_lines_time(self, val): self.grid_lines_primary = val

    @property
    def grid_lines_freq(self): return self.grid_lines_primary
    @grid_lines_freq.setter
    def grid_lines_freq(self, val): self.grid_lines_primary = val

    @property
    def grid_time_enabled(self): return self.grid_primary_enabled
    @grid_time_enabled.setter
    def grid_time_enabled(self, val): self.grid_primary_enabled = val

    @property
    def grid_freq_enabled(self): return self.grid_primary_enabled
    @grid_freq_enabled.setter
    def grid_freq_enabled(self, val): self.grid_primary_enabled = val

    @property
    def grid_time_tracking(self): return self.grid_primary_tracking
    @grid_time_tracking.setter
    def grid_time_tracking(self, val): self.grid_primary_tracking = val

    @property
    def grid_freq_tracking(self): return self.grid_primary_tracking
    @grid_freq_tracking.setter
    def grid_freq_tracking(self, val): self.grid_primary_tracking = val

    # -------------------------------------------------------------------------
    # Marker Placement
    # -------------------------------------------------------------------------
    def place_marker(self, scene_pos, drag_mode=False, source_vb=None):
        vb = source_vb if source_vb is not None else self.view_box
        v_pos = vb.mapSceneToView(scene_pos)

        # Delegate STATS bound placement
        if self.interaction_mode == 'STATS' and hasattr(self, '_place_stats_bound'):
            self._place_stats_bound(scene_pos, v_pos, drag_mode)
            return

        # Delegate FILTER bound placement (Frequency Domain)
        if self.interaction_mode == 'FILTER' and hasattr(self, '_place_filter_bound'):
            self._place_filter_bound(scene_pos, v_pos, drag_mode)
            return

        is_primary = self.is_primary_mode(self.interaction_mode)
        is_endless = 'ENDLESS' in self.interaction_mode

        if is_primary:
            p_min, p_max = self._get_primary_bounds()
            val = max(p_min, min(p_max, v_pos.x()))
        else:
            y_min, y_max = self._get_y_bounds()
            val = max(y_min, min(y_max, v_pos.y()))

        if is_endless:
            active_markers = self.markers_primary_endless if is_primary else self.markers_y_endless_dict.setdefault(self.y_label_text, [])
        else:
            active_markers = self.markers_primary if is_primary else self.markers_y_dict.setdefault(self.y_label_text, [])

        # 1. Hit-test existing markers
        found_marker = None
        for i, m in enumerate(active_markers):
            is_m_locked = (i == 0 and self.marker_panel.btn_lock_m1.isChecked()) or \
                          (i == 1 and self.marker_panel.btn_lock_m2.isChecked())
            if is_m_locked and len(active_markers) == 2:
                if not (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                    continue

            m_is_primary = (m in self.markers_primary or m in self.markers_primary_endless)
            m_pixel = self.view_box.mapViewToScene(pg.Point(m.value(), 0) if m_is_primary else pg.Point(0, m.value()))
            dist = abs(scene_pos.x() - m_pixel.x()) if m_is_primary else abs(scene_pos.y() - m_pixel.y())
            if dist < 20:
                found_marker = m
                break

        if found_marker:
            if len(active_markers) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                old_v = found_marker.value()
                shift = val - old_v
                other = active_markers[0] if active_markers[1] == found_marker else active_markers[1]
                curr_min, curr_max = (p_min, p_max) if is_primary else (y_min, y_max)

                if self.marker_panel.btn_lock_delta.isChecked():
                    new_o = other.value() + shift
                    if curr_min <= val <= curr_max and curr_min <= new_o <= curr_max:
                        found_marker.setValue(val)
                        other.setValue(new_o)
                elif self.marker_panel.btn_lock_center.isChecked():
                    ct = (old_v + other.value()) / 2
                    new_o = 2 * ct - val
                    if curr_min <= val <= curr_max and curr_min <= new_o <= curr_max:
                        found_marker.setValue(val)
                        other.setValue(new_o)
            else:
                found_marker.setValue(val)

            if drag_mode:
                self.active_drag_marker = found_marker
            self.update_marker_info()
            return

        # 2. Check for Grid Lines (Shadow Markers)
        if self.interaction_mode in ['TIME', 'FREQ', 'MAG', 'Y']:
            grid_lines = self.grid_lines_primary if is_primary else self.grid_lines_mag
            best_gl, min_gl_dist = None, 20

            for gl in grid_lines:
                gl_pos = gl.value()
                p_scene = self.view_box.mapViewToScene(pg.Point(gl_pos, 0) if is_primary else pg.Point(0, gl_pos))
                dist = abs(scene_pos.x() - p_scene.x()) if is_primary else abs(scene_pos.y() - p_scene.y())
                if dist < min_gl_dist:
                    min_gl_dist = dist
                    best_gl = gl

            if best_gl and len(active_markers) == 2:
                sorted_m = sorted(active_markers, key=lambda m: m.value())
                p1, p2 = sorted_m[0].value(), sorted_m[1].value()
                delta = p2 - p1
                k = (best_gl.value() - p1) / delta if delta != 0 else 1.0

                lock_m1 = self.marker_panel.btn_lock_m1.isChecked()
                lock_m2 = self.marker_panel.btn_lock_m2.isChecked()
                lock_delta = self.marker_panel.btn_lock_delta.isChecked()
                lock_center = self.marker_panel.btn_lock_center.isChecked()

                move_p1 = (k < 0.5)
                if lock_m1 and not lock_m2: move_p1 = False
                elif lock_m2 and not lock_m1: move_p1 = True

                if drag_mode:
                    sorted_m = sorted(active_markers, key=lambda m: m.value())
                    self.active_drag_grid_info = {
                        'k': k,
                        'moving_marker': sorted_m[0] if move_p1 else sorted_m[1],
                        'fixed_marker': sorted_m[1] if move_p1 else sorted_m[0],
                        'is_p1': move_p1,
                        'is_primary': is_primary,
                        'lock_delta': lock_delta,
                        'lock_center': lock_center
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
                if not (lock_delta or lock_center): return

            shift = val - target.value()
            curr_min, curr_max = (p_min, p_max) if is_primary else (y_min, y_max)

            if lock_delta:
                new_t, new_o = val, other.value() + shift
                if curr_min <= new_t <= curr_max and curr_min <= new_o <= curr_max:
                    target.setValue(new_t)
                    other.setValue(new_o)
            elif lock_center:
                ct = (m1_pos + m2_pos) / 2
                new_o = 2 * ct - val
                if curr_min <= val <= curr_max and curr_min <= new_o <= curr_max:
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
        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)
        color = p.marker_time if is_primary else p.marker_mag
        orient = 90 if is_primary else 0

        if not is_endless and len(active_markers) >= 2:
            old_m = active_markers.pop(0)
            self.plot_item.removeItem(old_m)

        new_m = pg.InfiniteLine(pos=val, angle=orient, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine), movable=False)
        new_m.setHoverPen(pg.mkPen(255, 0, 0, width=2))
        new_m.setAcceptHoverEvents(True)
        new_m.setZValue(100)
        self._marker_age[new_m] = self._marker_age_counter
        self._marker_age_counter += 1

        if is_endless:
            label_text = f"M{len(active_markers)+1}"
            new_m.label = pg.InfLineLabel(new_m, text=label_text, position=0.95, rotateAxis=(1, 0), anchor=(1, 1))
            new_m.label.setColor(color)

        active_markers.append(new_m)
        self.plot_item.addItem(new_m, ignoreBounds=True)
        if drag_mode: self.active_drag_marker = new_m
        self.update_marker_info()

    # -------------------------------------------------------------------------
    # Drag Handling
    # -------------------------------------------------------------------------
    def update_drag(self, scene_pos, source_vb=None):
        vb = source_vb if source_vb is not None else self.view_box
        v_pos = vb.mapSceneToView(scene_pos)

        # 0. Handle FILTER dragging (Frequency Domain)
        if hasattr(self, '_update_filter_drag'):
            handled = self._update_filter_drag(v_pos)
            if handled: return

        # 1. Handle STATS Region dragging
        if self.interaction_mode == 'STATS' and hasattr(self, '_update_stats_drag'):
            self._update_stats_drag(v_pos)
            return

        # 1.5 Handle Shadow Marker (Grid Line) dragging
        if getattr(self, 'active_drag_grid_info', None):
            info = self.active_drag_grid_info
            is_primary = info.get('is_primary', info.get('is_time', True))
            k = info['k']
            m_move = info['moving_marker']
            m_fixed = info['fixed_marker']
            is_p1 = info['is_p1']
            p_fixed = m_fixed.value()
            lock_delta = info.get('lock_delta', False)
            lock_center = info.get('lock_center', False)

            if is_primary:
                curr_min, curr_max = self._get_primary_bounds()
                g_prime = max(curr_min, min(curr_max, v_pos.x()))
            else:
                curr_min, curr_max = self._get_y_bounds()
                g_prime = max(curr_min, min(curr_max, v_pos.y()))

            active_markers = self.markers_primary if is_primary else self.markers_y_dict.get(self.y_label_text, [])
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
                        sorted_m[0].setPos(p1_orig + shift_clamped)
                        sorted_m[1].setPos(p2_orig + shift_clamped)
                    elif lock_center:
                        sorted_m = sorted(active_markers, key=lambda m: m.value())
                        p1_orig, p2_orig = sorted_m[0].value(), sorted_m[1].value()
                        center = (p1_orig + p2_orig) / 2
                        if abs(k - 0.5) > 1e-9:
                            new_delta = (g_prime - center) / (k - 0.5)
                            max_half_delta = min(center - curr_min, curr_max - center)
                            half_delta_clamped = np.clip(abs(new_delta / 2), 0.0, max_half_delta)
                            sorted_m[0].setPos(center - half_delta_clamped)
                            sorted_m[1].setPos(center + half_delta_clamped)
                    else:
                        if is_p1:
                            if abs(1 - k) > 1e-9:
                                new_v = (g_prime - k * p_fixed) / (1 - k)
                                if curr_min <= new_v <= curr_max:
                                    m_move.setPos(new_v)
                        else:
                            if abs(k) > 1e-9:
                                new_v = p_fixed + (g_prime - p_fixed) / k
                                if curr_min <= new_v <= curr_max:
                                    m_move.setPos(new_v)

                    if active_markers[0].value() > active_markers[1].value():
                        active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                        self.marker_panel.flip_m_lock(self.interaction_mode)
                except ZeroDivisionError:
                    pass

            self.update_marker_info()
            return

        # 2. Handle Primary or Magnitude Marker dragging
        if not getattr(self, 'active_drag_marker', None):
            return

        is_primary = (self.active_drag_marker in self.markers_primary or self.active_drag_marker in self.markers_primary_endless)
        is_endless = 'ENDLESS' in self.interaction_mode

        if is_primary:
            curr_min, curr_max = self._get_primary_bounds()
            val = max(curr_min, min(curr_max, v_pos.x()))
        else:
            curr_min, curr_max = self._get_y_bounds()
            val = max(curr_min, min(curr_max, v_pos.y()))

        if is_endless:
            active_markers = self.markers_primary_endless if is_primary else self.markers_y_endless_dict.setdefault(self.y_label_text, [])
        else:
            active_markers = self.markers_primary if is_primary else self.markers_y_dict.setdefault(self.y_label_text, [])

        if not is_endless and len(active_markers) == 2:
            other = active_markers[0] if active_markers[1] == self.active_drag_marker else active_markers[1]
            target_idx = 0 if self.active_drag_marker == active_markers[0] else 1

            lock_target = self.marker_panel.btn_lock_m1.isChecked() if target_idx == 0 else self.marker_panel.btn_lock_m2.isChecked()
            lock_delta = self.marker_panel.btn_lock_delta.isChecked()
            lock_center = self.marker_panel.btn_lock_center.isChecked()

            if lock_target: return

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

    # -------------------------------------------------------------------------
    # Marker Table Synchronization & Editing
    # -------------------------------------------------------------------------
    def update_marker_info(self):
        display_mode = self.interaction_mode
        if display_mode in ['ZOOM', 'MOVE', 'STATS']:
            display_mode = getattr(self.marker_panel, 'last_marker_mode', getattr(self, 'default_marker_mode', 'TIME'))

        is_primary = self.is_primary_mode(display_mode)
        is_endless = 'ENDLESS' in display_mode

        if is_endless:
            active_markers = self.markers_primary_endless if is_primary else self.markers_y_endless_dict.setdefault(self.y_label_text, [])
            self.marker_panel.update_endless_list(active_markers, display_mode)
            for i, m in enumerate(active_markers):
                if hasattr(m, 'label'): m.label.setFormat(f"M{i+1}")
            if self.interaction_mode not in ['ZOOM', 'MOVE', 'STATS']: return
        else:
            active_markers = self.markers_primary if is_primary else self.markers_y_dict.setdefault(self.y_label_text, [])

        sorted_m = sorted(active_markers, key=lambda m: m.value())
        self.marker_panel.update_headers(display_mode, self.y_label_text)

        # Clear marker panel fields
        for widget in self.marker_panel.m_widgets:
            for k in widget:
                widget[k].blockSignals(True); widget[k].clear(); widget[k].blockSignals(False)
        for name in ['delta_v1', 'delta_v2', 'delta_v3', 'center_v1', 'center_v2', 'center_v3']:
            if hasattr(self.marker_panel, name):
                w = getattr(self.marker_panel, name)
                w.blockSignals(True); w.clear(); w.blockSignals(False)

        if not sorted_m:
            return

        # Update M1, M2 rows
        for i in range(min(2, len(sorted_m))):
            m_val = sorted_m[i].value()
            row_dict = self.marker_panel.m_widgets[i]
            for k in row_dict: row_dict[k].blockSignals(True)
            self._format_marker_row(m_val, row_dict, is_primary)
            for k in row_dict: row_dict[k].blockSignals(False)

        # Update Delta / Center rows
        if len(sorted_m) == 2:
            v1, v2 = sorted_m[0].value(), sorted_m[1].value()
            self._format_delta_center(v1, v2, is_primary)

        if self.interaction_mode not in ['ZOOM', 'MOVE', 'STATS'] and not is_endless:
            self.marker_panel.set_locks_enabled(len(sorted_m) >= 1, len(sorted_m) >= 2)

        self.update_grid('PRIMARY')
        self.update_grid('MAG')

    def _format_marker_row(self, m_val, row_dict, is_primary):
        """Format a single marker row (v1, v2, v3). Override in subclass for domain readouts."""
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9 if is_primary else 6)) if self.settings_mgr else (9 if is_primary else 6)
        row_dict['v1'].setText(f"{m_val:.{prec1}f}")

    def _format_delta_center(self, v1, v2, is_primary):
        """Format Delta and Center rows. Override in subclass for domain readouts."""
        prec1 = int(self.settings_mgr.get("ui/label_precision", 9 if is_primary else 6)) if self.settings_mgr else (9 if is_primary else 6)
        self.marker_panel.delta_v1.blockSignals(True)
        self.marker_panel.center_v1.blockSignals(True)
        self.marker_panel.delta_v1.setText(f"{abs(v2 - v1):.{prec1}f}")
        self.marker_panel.center_v1.setText(f"{(v1 + v2)/2:.{prec1}f}")
        self.marker_panel.delta_v1.blockSignals(False)
        self.marker_panel.center_v1.blockSignals(False)

    def marker_edit_finished(self):
        sender = self.sender()
        if not sender: return
        name = sender.objectName()

        eff_mode = self.interaction_mode
        if eff_mode in ['ZOOM', 'MOVE', 'STATS']:
            eff_mode = getattr(self.marker_panel, 'last_marker_mode', getattr(self, 'default_marker_mode', 'TIME'))
        is_primary = self.is_primary_mode(eff_mode)

        try:
            val = float(sender.text())
            curr_min, curr_max = self._get_primary_bounds() if is_primary else self._get_y_bounds()

            # 1. Endless marker editing
            if name.startswith('em_'):
                parts = name.split('_')
                idx, unit = int(parts[1]), parts[2]
                active_list = self.markers_primary_endless if is_primary else self.markers_y_endless_dict.setdefault(self.y_label_text, [])
                if idx < len(active_list):
                    new_p = self._parse_marker_value_by_unit(val, unit, is_primary, curr_min, curr_max)
                    active_list[idx].setPos(new_p)
                self.update_marker_info()
                return

            # 2. Stats region editing
            if name.startswith('st_'):
                if hasattr(self, '_parse_stats_edit'):
                    self._parse_stats_edit(name, val, curr_min, curr_max)
                return

            # 3. Fixed primary / secondary markers
            active_markers = self.markers_primary if is_primary else self.markers_y_dict.setdefault(self.y_label_text, [])
            sorted_markers = sorted(active_markers, key=lambda m: m.value())

            if name.startswith('m'):
                idx = int(name[1])
                if idx >= len(sorted_markers): return

                new_p = self._parse_marker_value_by_unit(val, 'v2' if 'v2' in name else 'v1', is_primary, curr_min, curr_max)

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
                if 'delta' in name:
                    dv = self._parse_delta_value_by_unit(val, 'v2' if 'v2' in name else 'v1', is_primary)
                    sorted_markers[0].setValue((p1 + p2)/2 - dv/2)
                    sorted_markers[1].setValue((p1 + p2)/2 + dv/2)
                elif 'center' in name:
                    ct = self._parse_marker_value_by_unit(val, 'v2' if 'v2' in name else 'v1', is_primary, curr_min, curr_max)
                    dv = abs(p2 - p1)
                    sorted_markers[0].setValue(ct - dv/2)
                    sorted_markers[1].setValue(ct + dv/2)

            self.update_marker_info()
        except Exception:
            pass

    def _parse_marker_value_by_unit(self, val, unit, is_primary, curr_min, curr_max):
        """Parse text value based on unit column (v1, v2, sec, sam, etc.). Override in subclass."""
        return np.clip(val, curr_min, curr_max)

    def _parse_delta_value_by_unit(self, val, unit, is_primary):
        """Parse delta text value based on unit column. Override in subclass."""
        return val

    # -------------------------------------------------------------------------
    # Marker Clearing & Deletion
    # -------------------------------------------------------------------------
    def handle_lock_change(self, lock_type, checked):
        self.update_marker_info()

    def handle_marker_clear(self, mode):
        primary_mode_name = getattr(self, 'default_marker_mode', 'TIME')
        if mode == primary_mode_name:
            for m in self.markers_primary:
                self.plot_item.removeItem(m)
                self._marker_age.pop(m, None)
            self.markers_primary = []
            self.marker_panel._clear_marker_locks(primary_mode_name)
            self.toggle_grid('PRIMARY', False)
        elif mode in ['TIME_ENDLESS', 'FREQ_ENDLESS']:
            for m in self.markers_primary_endless:
                self.plot_item.removeItem(m)
            self.markers_primary_endless = []
        elif mode == 'MAG_ENDLESS':
            for m in self.markers_y_endless_dict.get(self.y_label_text, []):
                self.plot_item.removeItem(m)
            self.markers_y_endless_dict[self.y_label_text] = []
        elif mode == 'STATS':
            if hasattr(self, '_clear_stats'): self._clear_stats()
        elif mode == 'FILTER':
            if hasattr(self, '_clear_filter_state'): self._clear_filter_state(replot=True)
        else: # Secondary (Y / MAG)
            for m in self.markers_y_dict.get(self.y_label_text, []):
                self.plot_item.removeItem(m)
                self._marker_age.pop(m, None)
            self.markers_y_dict[self.y_label_text] = []
            self.marker_panel._clear_marker_locks('MAG')
            self.toggle_grid('MAG', False)
        self.update_marker_info()

    def remove_marker_item(self, marker, mode):
        if marker in self.plot_item.items:
            self.plot_item.removeItem(marker)

        is_primary = self.is_primary_mode(mode)
        active_list = self.markers_primary_endless if is_primary else self.markers_y_endless_dict.get(self.y_label_text, [])

        if marker in active_list:
            active_list.remove(marker)
            for i, m in enumerate(active_list):
                if hasattr(m, 'label'):
                    m.label.setFormat(f"M{i+1}")

        self.update_marker_info()

    def clear_all_markers(self):
        for m in (self.markers_primary + self.markers_primary_endless):
            self.plot_item.removeItem(m)
        self.markers_primary.clear()
        self.markers_primary_endless.clear()

        for y_label in self.markers_y_dict:
            for m in self.markers_y_dict[y_label]:
                self.plot_item.removeItem(m)
            self.markers_y_dict[y_label].clear()

        for y_label in self.markers_y_endless_dict:
            for m in self.markers_y_endless_dict[y_label]:
                self.plot_item.removeItem(m)
            self.markers_y_endless_dict[y_label].clear()

        if hasattr(self, '_clear_stats'):
            self._clear_stats()
        if hasattr(self, '_clear_filter_state'):
            self._clear_filter_state(replot=False)

        self.toggle_grid('PRIMARY', False)
        self.toggle_grid('MAG', False)
        self.update_marker_info()

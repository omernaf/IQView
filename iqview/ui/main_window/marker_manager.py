import pyqtgraph as pg
import numpy as np
from PyQt6.QtCore import Qt

class MarkerManagerMixin:
    def place_marker(self, scene_pos, drag_mode=False):
        if self.spectrogram_view.plot_item.sceneBoundingRect().contains(scene_pos):
            vb = self.spectrogram_view.plot_item.vb
            mouse_v = vb.mapSceneToView(scene_pos)
            
            is_time = (self.interaction_mode == 'TIME')
            active_markers = self.markers_time if is_time else self.markers_freq
            curr_min, curr_max = (0.0, self.time_duration) if is_time else (self.fc - self.rate/2, self.fc + self.rate/2)
            angle = 90 if is_time else 0
            
            # 1. Determine the target logical value
            if is_time:
                raw_val = float(np.clip(mouse_v.x(), 0.0, self.time_duration))
                sample = int(round(raw_val * self.rate)) + 1
                val = (sample - 1.0) / self.rate
            else:
                f_min = self.fc - self.rate/2
                raw_val = float(np.clip(mouse_v.y(), f_min, self.fc + self.rate/2))
                rbw = self.rate / self.fft_size
                bin_idx = int(round((raw_val - f_min) / rbw)) + 1
                val = f_min + (bin_idx - 1.0) * rbw

            # 2. HIGHEST PRIORITY: If 2 markers exist and lock is on, ALWAYS shift the pair
            if len(active_markers) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                m1_pos, m2_pos = active_markers[0].value(), active_markers[1].value()
                dist1 = abs(val - m1_pos)
                dist2 = abs(val - m2_pos)
                target = active_markers[0] if dist1 < dist2 else active_markers[1]
                other = active_markers[1] if dist1 < dist2 else active_markers[0]
                
                old_p = target.value()
                shift = val - old_p
                
                if self.marker_panel.btn_lock_delta.isChecked():
                    new_target_p = val
                    new_other_p = other.value() + shift
                    if curr_min <= new_target_p <= curr_max and curr_min <= new_other_p <= curr_max:
                        target.setPos(new_target_p)
                        other.setPos(new_other_p)
                elif self.marker_panel.btn_lock_center.isChecked():
                    new_target_p = val
                    center = (m1_pos + m2_pos) / 2
                    new_other_p = 2 * center - new_target_p
                    if curr_min <= new_target_p <= curr_max and curr_min <= new_other_p <= curr_max:
                        target.setPos(new_target_p)
                        other.setPos(new_other_p)
                
                if drag_mode: self.active_drag_marker = target

            # 3. SECOND PRIORITY: Hit-test for dragging a single marker
            else:
                hit_threshold = 20 # pixels
                best_marker = None
                min_dist = float('inf')
                
                for m in active_markers:
                    m_pos = m.value()
                    p_scene = vb.mapViewToScene(pg.Point(m_pos, 0)) if is_time else vb.mapViewToScene(pg.Point(0, m_pos))
                    dist = abs(scene_pos.x() - p_scene.x()) if is_time else abs(scene_pos.y() - p_scene.y())
                    
                    if dist < hit_threshold and dist < min_dist:
                        min_dist = dist
                        best_marker = m

                if best_marker:
                    best_marker.setPos(val)
                    if drag_mode: self.active_drag_marker = best_marker
                else:
                    # 4. LOWEST PRIORITY: Place brand new marker (and replace oldest if needed)
                    if len(active_markers) >= 2:
                        old_marker = active_markers.pop(0)
                        self.spectrogram_view.plot_item.removeItem(old_marker)
                    
                    marker = pg.InfiniteLine(pos=val, angle=angle, movable=False, pen=pg.mkPen('r', width=2))
                    marker.setZValue(10)
                    self.spectrogram_view.plot_item.addItem(marker, ignoreBounds=True)
                    active_markers.append(marker)
                    if drag_mode: self.active_drag_marker = marker
            
            self.update_marker_info()

    def update_drag(self, scene_pos):
        if self.active_drag_marker and self.spectrogram_view.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_v = self.spectrogram_view.plot_item.vb.mapSceneToView(scene_pos)
            is_time = self.active_drag_marker in self.markers_time
            active_markers = self.markers_time if is_time else self.markers_freq
            
            if is_time:
                get_pos = lambda m: m.value()
                f_min, f_max = 0.0, self.time_duration
                raw_val = float(np.clip(mouse_v.x(), 0.0, self.time_duration))
                sample = int(round(raw_val * self.rate)) + 1
                new_v = (sample - 1.0) / self.rate
            else:
                f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
                get_pos = lambda m: m.value()
                raw_val = float(np.clip(mouse_v.y(), f_min, f_max))
                rbw = self.rate / self.fft_size
                bin_idx = int(round((raw_val - f_min) / rbw)) + 1
                new_v = f_min + (bin_idx - 1.0) * rbw

            if len(active_markers) == 2:
                other_marker = active_markers[0] if active_markers[1] == self.active_drag_marker else active_markers[1]
                old_v = get_pos(self.active_drag_marker)
                shift = new_v - old_v
                if self.marker_panel.btn_lock_delta.isChecked():
                    other_new = get_pos(other_marker) + shift
                    if f_min <= other_new <= f_max:
                        self.active_drag_marker.setPos(new_v)
                        other_marker.setPos(other_new)
                elif self.marker_panel.btn_lock_center.isChecked():
                    p1, p2 = get_pos(active_markers[0]), get_pos(active_markers[1])
                    ct = (p1 + p2) / 2
                    other_new = 2 * ct - new_v
                    if f_min <= other_new <= f_max:
                        self.active_drag_marker.setPos(new_v)
                        other_marker.setPos(other_new)
                else: self.active_drag_marker.setPos(new_v)
            else: self.active_drag_marker.setPos(new_v)
            self.update_marker_info()

    def update_marker_info(self):
        is_freq = (self.interaction_mode == 'FREQ')
        active_markers = self.markers_freq if is_freq else self.markers_time
        get_pos = lambda m: m.value()
        sorted_markers = sorted(active_markers, key=get_pos)
        
        for widgets in self.marker_panel.widgets:
            widgets['sec'].clear()
            widgets['sam'].clear()
        self.marker_panel.delta_sec.clear()
        self.marker_panel.delta_sam.clear()
        self.marker_panel.center_sec.clear()
        self.marker_panel.center_sam.clear()

        if not sorted_markers: return

        for i, marker in enumerate(sorted_markers):
            val = get_pos(marker)
            self.marker_panel.widgets[i]['sec'].blockSignals(True)
            self.marker_panel.widgets[i]['sam'].blockSignals(True)
            if is_freq:
                rbw = self.rate / self.fft_size
                bin_idx = int(round((val - (self.fc - self.rate/2)) / rbw)) + 1
                bin_idx = max(1, min(bin_idx, self.fft_size))
                self.marker_panel.widgets[i]['sec'].setText(f"{val:.2f}")
                self.marker_panel.widgets[i]['sam'].setText(f"{bin_idx}")
            else:
                sample = int(round(val * self.rate)) + 1
                sample = max(1, min(sample, getattr(self, 'total_samples_in_cache', 1e9)))
                self.marker_panel.widgets[i]['sec'].setText(f"{val:.6f}")
                self.marker_panel.widgets[i]['sam'].setText(f"{sample}")
            self.marker_panel.widgets[i]['sec'].blockSignals(False)
            self.marker_panel.widgets[i]['sam'].blockSignals(False)

        if len(sorted_markers) == 2:
            p1, p2 = get_pos(sorted_markers[0]), get_pos(sorted_markers[1])
            self.marker_panel.delta_sec.blockSignals(True)
            self.marker_panel.delta_sam.blockSignals(True)
            self.marker_panel.center_sec.blockSignals(True)
            self.marker_panel.center_sam.blockSignals(True)

            if is_freq:
                f_min = self.fc - self.rate/2
                rbw = self.rate / self.fft_size
                s1 = int(round((p1 - f_min) / rbw)) + 1
                s2 = int(round((p2 - f_min) / rbw)) + 1
                s1, s2 = np.clip([s1, s2], 1, self.fft_size)
                ds = abs(s2 - s1) + 1
                cp = (p1 + p2) / 2
                cs = int(round((cp - f_min) / rbw)) + 1
                cs = max(1, min(cs, self.fft_size))
                self.marker_panel.delta_sec.setText(f"{abs(p2 - p1):.2f}")
                self.marker_panel.delta_sam.setText(f"{ds}")
                self.marker_panel.center_sec.setText(f"{cp:.2f}")
                self.marker_panel.center_sam.setText(f"{cs}")
            else:
                s1 = int(round(p1 * self.rate)) + 1
                s2 = int(round(p2 * self.rate)) + 1
                max_s = getattr(self, 'total_samples_in_cache', 1e9)
                s1, s2 = np.clip([s1, s2], 1, max_s)
                ds = abs(s2 - s1) + 1
                cp = (p1 + p2) / 2
                cs = int(round(cp * self.rate)) + 1
                cs = max(1, min(cs, max_s))
                self.marker_panel.delta_sec.setText(f"{abs(p2 - p1):.6f}")
                self.marker_panel.delta_sam.setText(f"{ds}")
                self.marker_panel.center_sec.setText(f"{cp:.6f}")
                self.marker_panel.center_sam.setText(f"{cs}")

            self.marker_panel.delta_sec.blockSignals(False)
            self.marker_panel.delta_sam.blockSignals(False)
            self.marker_panel.center_sec.blockSignals(False)
            self.marker_panel.center_sam.blockSignals(False)
        self.update_grid('TIME')
        self.update_grid('FREQ')

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        is_freq = (self.interaction_mode == 'FREQ')
        active_markers = self.markers_freq if is_freq else self.markers_time
        get_pos = lambda m: m.value()
        try:
            val = float(sender.text())
            sorted_markers = sorted(active_markers, key=get_pos)
            f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
            rbw = self.rate / self.fft_size
            curr_max = f_max if is_freq else self.time_duration
            curr_min = f_min if is_freq else 0
            if name.startswith('m') and len(sorted_markers) > int(name[1]):
                idx, unit = int(name[1]), name[3:]
                if is_freq:
                    bin_val = max(1, min(val, self.fft_size))
                    new_p = np.clip(f_min + (bin_val - 1) * rbw if unit == 'sam' else val, f_min, f_max)
                else:
                    max_s = getattr(self, 'total_samples_in_cache', 1e9)
                    s_val = np.clip(val if unit == 'sam' else val * self.rate + 1.0, 1, max_s)
                    new_p = np.clip((s_val - 1.0) / self.rate, 0.0, self.time_duration)
                if len(sorted_markers) == 2:
                    other_idx = 1 - idx
                    old_p = get_pos(sorted_markers[idx])
                    shift = new_p - old_p
                    if self.marker_panel.btn_lock_delta.isChecked():
                        other_new = get_pos(sorted_markers[other_idx]) + shift
                        if curr_min <= other_new <= curr_max:
                            sorted_markers[idx].setPos(new_p)
                            sorted_markers[other_idx].setPos(other_new)
                    elif self.marker_panel.btn_lock_center.isChecked():
                        p1, p2 = get_pos(sorted_markers[0]), get_pos(sorted_markers[1])
                        ct = (p1 + p2) / 2
                        other_new = 2 * ct - new_p
                        if curr_min <= other_new <= curr_max:
                            sorted_markers[idx].setPos(new_p)
                            sorted_markers[other_idx].setPos(other_new)
                    else: sorted_markers[idx].setPos(new_p)
                else: sorted_markers[idx].setPos(new_p)
            elif len(sorted_markers) == 2:
                p1, p2 = get_pos(sorted_markers[0]), get_pos(sorted_markers[1])
                dt_coords, ct_coords = abs(p2 - p1), (p1 + p2) / 2
                if 'delta' in name:
                    if is_freq: new_dt_coords = np.clip((val - 1) * rbw if 'sam' in name else val, 0, self.rate)
                    else: new_dt_coords = np.clip((val - 1) / self.rate if 'sam' in name else val, 0, self.time_duration)
                    m1_new, m2_new = ct_coords - new_dt_coords/2, ct_coords + new_dt_coords/2
                    if curr_min <= m1_new and m2_new <= curr_max:
                        sorted_markers[0].setPos(m1_new)
                        sorted_markers[1].setPos(m2_new)
                elif 'center' in name:
                    if is_freq: new_ct_coords = np.clip((val - 1) * rbw + f_min if 'sam' in name else val, f_min, f_max)
                    else: new_ct_coords = np.clip((val - 1) / self.rate if 'sam' in name else val, 0.0, self.time_duration)
                    m1_new, m2_new = new_ct_coords - dt_coords/2, new_ct_coords + dt_coords/2
                    if curr_min <= m1_new and m2_new <= curr_max:
                        sorted_markers[0].setPos(m1_new)
                        sorted_markers[1].setPos(m2_new)
            self.update_marker_info()
        except ValueError: self.update_marker_info()

    def handle_lock_change(self, lock_type, checked):
        if not checked: return
        if lock_type == 'delta':
            self.marker_panel.btn_lock_center.blockSignals(True)
            self.marker_panel.btn_lock_center.setChecked(False)
            self.marker_panel.btn_lock_center.setText("Center 🔓")
            self.marker_panel.btn_lock_center.blockSignals(False)
        else:
            self.marker_panel.btn_lock_delta.blockSignals(True)
            self.marker_panel.btn_lock_delta.setChecked(False)
            self.marker_panel.btn_lock_delta.setText("Delta (Δ) 🔓")
            self.marker_panel.btn_lock_delta.blockSignals(False)

    def handle_marker_clear(self, mode):
        markers = self.markers_time if mode == 'TIME' else self.markers_freq
        for marker in markers:
            self.spectrogram_view.plot_item.removeItem(marker)
        markers.clear()
        self.update_marker_info()

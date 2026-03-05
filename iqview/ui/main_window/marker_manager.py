import pyqtgraph as pg
import numpy as np
from PyQt6.QtCore import Qt
from ..themes import get_palette

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

            # 2. HIGHEST PRIORITY: Handle FILTER mode placement
            if self.interaction_mode == 'FILTER':
                if not getattr(self, 'filter_placing', False):
                    # Start placing
                    self.filter_placing = True
                    self.filter_placed = False
                    self._filter_placement_start = val
                    
                    if not self.filter_region:
                        # Lazily create the region
                        self.filter_region = pg.LinearRegionItem(
                            values=[val, val], 
                            orientation='horizontal',
                            brush=pg.mkBrush(255, 100, 0, 40),
                            pen=pg.mkPen('#ff6400', width=2)
                        )
                        self.spectrogram_view.plot_item.addItem(self.filter_region)
                        self.filter_region.sigRegionChanged.connect(self.on_filter_region_changed)
                        self.filter_region.sigRegionChangeFinished.connect(self.on_filter_region_finished)
                    else:
                        self.filter_region.setRegion([val, val])
                    
                    self.filter_region.show()
                    self.filter_region.setMovable(False) # Keep fixed while placing
                else:
                    # Finish placing
                    self.filter_placing = False
                    self.filter_placed = True
                    self.filter_region.setMovable(True)
                    # Trigger filter reprocessing
                    self.on_filter_region_finished()
                
                self.update_marker_info()
                return

            # 3. SECOND PRIORITY: If 2 markers exist and lock is on, ALWAYS shift the pair
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
                    
                    theme = self.settings_mgr.get("ui/theme", "Dark").lower()
                    color = self.settings_mgr.get(f"ui/{theme}/time_marker_color") if is_time else self.settings_mgr.get(f"ui/{theme}/freq_marker_color")
                    style_name = self.settings_mgr.get(f"ui/{theme}/time_marker_style") if is_time else self.settings_mgr.get(f"ui/{theme}/freq_marker_style")
                    
                    style_map = {
                        "SolidLine": Qt.PenStyle.SolidLine,
                        "DashLine": Qt.PenStyle.DashLine,
                        "DotLine": Qt.PenStyle.DotLine,
                        "DashDotLine": Qt.PenStyle.DashDotLine
                    }
                    style = style_map.get(str(style_name), Qt.PenStyle.DashLine)
                    
                    marker = pg.InfiniteLine(pos=val, angle=angle, movable=False, pen=pg.mkPen(color, width=2, style=style))
                    marker.setZValue(10)
                    self.spectrogram_view.plot_item.addItem(marker, ignoreBounds=True)
                    active_markers.append(marker)
                    if drag_mode: self.active_drag_marker = marker
            
            self.update_marker_info()

    def update_drag(self, scene_pos):
        if self.spectrogram_view.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_v = self.spectrogram_view.plot_item.vb.mapSceneToView(scene_pos)
            
            # Handle BPF placement drag (while moving mouse before second click)
            if self.interaction_mode == 'FILTER' and getattr(self, 'filter_placing', False):
                f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
                raw_val = float(np.clip(mouse_v.y(), f_min, f_max))
                rbw = self.rate / self.fft_size
                bin_idx = int(round((raw_val - f_min) / rbw)) + 1
                new_v = f_min + (bin_idx - 1.0) * rbw
                
                # In placement mode, we fix the first bound and update the second
                r1, r2 = self.filter_region.getRegion()
                # Note: We don't know which one was the "start", but usually it's the one we set in place_marker
                # Let's assume the first element of values in setRegion was the intended start.
                # LinearRegionItem doesn't strictly track "first" vs "second", so we might need to store it.
                # However, if we just set [start, new_v], it works fine.
                if not hasattr(self, '_filter_placement_start'):
                    self._filter_placement_start = r1
                
                self.filter_region.setRegion([self._filter_placement_start, new_v])
                self.update_marker_info()
                return

            if self.active_drag_marker:
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
        is_filter = (self.interaction_mode == 'FILTER')
        
        if is_filter:
            if not getattr(self, 'filter_placed', False) and not getattr(self, 'filter_placing', False):
                # Clear all widgets and return
                for widgets in self.marker_panel.widgets:
                    widgets['sec'].clear()
                    widgets['sam'].clear()
                self.marker_panel.delta_sec.clear()
                self.marker_panel.delta_sam.clear()
                self.marker_panel.center_sec.clear()
                self.marker_panel.center_sam.clear()
                return
            if not self.filter_region: return
            f1, f2 = self.filter_region.getRegion()
            active_values = sorted([f1, f2])
        else:
            active_markers = self.markers_freq if is_freq else self.markers_time
            get_pos = lambda m: m.value()
            active_values = sorted([get_pos(m) for m in active_markers])
        
        for widgets in self.marker_panel.widgets:
            widgets['sec'].clear()
            widgets['sam'].clear()
        self.marker_panel.delta_sec.clear()
        self.marker_panel.delta_sam.clear()
        self.marker_panel.center_sec.clear()
        self.marker_panel.center_sam.clear()

        if not active_values: return

        for i, val in enumerate(active_values):
            if i >= 2: break
            self.marker_panel.widgets[i]['sec'].blockSignals(True)
            self.marker_panel.widgets[i]['sam'].blockSignals(True)
            if is_freq or is_filter:
                rbw = self.rate / self.fft_size
                label_val = int(round((val - (self.fc - self.rate/2)) / rbw)) + 1
                label_val = max(1, min(label_val, self.fft_size))
            else:
                sample = int(round(val * self.rate)) + 1
                label_val = max(1, min(sample, getattr(self, 'total_samples_in_cache', 1e9)))
                
            prec = int(self.settings_mgr.get("ui/label_precision", 6 if (is_freq or is_filter) else 9))
            self.marker_panel.widgets[i]['sec'].setText(f"{val:.{prec}f}")
            self.marker_panel.widgets[i]['sam'].setText(f"{label_val}")
            self.marker_panel.widgets[i]['sec'].blockSignals(False)
            self.marker_panel.widgets[i]['sam'].blockSignals(False)

        if len(active_values) == 2:
            p1, p2 = active_values[0], active_values[1]
            self.marker_panel.delta_sec.blockSignals(True)
            self.marker_panel.delta_sam.blockSignals(True)
            self.marker_panel.center_sec.blockSignals(True)
            self.marker_panel.center_sam.blockSignals(True)

            prec = int(self.settings_mgr.get("ui/label_precision", 6 if (is_freq or is_filter) else 9))
            self.marker_panel.delta_sec.setText(f"{abs(p2 - p1):.{prec}f}")
            cp = (p1 + p2) / 2
            self.marker_panel.center_sec.setText(f"{cp:.{prec}f}")

            if is_freq or is_filter:
                f_min = self.fc - self.rate/2
                rbw = self.rate / self.fft_size
                s1 = int(round((p1 - f_min) / rbw)) + 1
                s2 = int(round((p2 - f_min) / rbw)) + 1
                s1, s2 = np.clip([s1, s2], 1, self.fft_size)
                ds = abs(s2 - s1) + 1
                cs = int(round((cp - f_min) / rbw)) + 1
                cs = max(1, min(cs, self.fft_size))
            else:
                s1 = int(round(p1 * self.rate)) + 1
                s2 = int(round(p2 * self.rate)) + 1
                limit = getattr(self, 'total_samples_in_cache', 1e9)
                s1, s2 = np.clip([s1, s2], 1, limit)
                ds = abs(s2 - s1) + 1
                cs = int(round(cp * self.rate)) + 1
                cs = max(1, min(cs, limit))

            self.marker_panel.delta_sam.setText(f"{ds}")
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
        is_filter = (self.interaction_mode == 'FILTER')
        
        if is_filter:
            if not self.filter_region: return
            f1, f2 = self.filter_region.getRegion()
            active_values = sorted([f1, f2])
        else:
            active_markers = self.markers_freq if is_freq else self.markers_time
            get_pos = lambda m: m.value()
            active_values = sorted([get_pos(m) for m in active_markers])
            
        try:
            val = float(sender.text())
            f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
            rbw = self.rate / self.fft_size
            curr_max = f_max if (is_freq or is_filter) else self.time_duration
            curr_min = f_min if (is_freq or is_filter) else 0
            
            if name.startswith('m') and len(active_values) > int(name[1]):
                idx, unit = int(name[1]), name[3:]
                if is_freq or is_filter:
                    bin_val = max(1, min(val, self.fft_size))
                    new_p = np.clip(f_min + (bin_val - 1) * rbw if unit == 'sam' else val, f_min, f_max)
                else:
                    max_s = getattr(self, 'total_samples_in_cache', 1e9)
                    s_val = np.clip(val if unit == 'sam' else val * self.rate + 1.0, 1, max_s)
                    new_p = np.clip((s_val - 1.0) / self.rate, 0.0, self.time_duration)
                
                if is_filter:
                    new_region = list(active_values)
                    new_region[idx] = new_p
                    self.filter_region.setRegion(new_region)
                elif len(active_values) == 2:
                    sorted_markers = sorted(active_markers, key=get_pos)
                    other_idx = 1 - idx
                    old_p = active_values[idx]
                    shift = new_p - old_p
                    if self.marker_panel.btn_lock_delta.isChecked():
                        other_new = active_values[other_idx] + shift
                        if curr_min <= other_new <= curr_max:
                            sorted_markers[idx].setPos(new_p)
                            sorted_markers[other_idx].setPos(other_new)
                    elif self.marker_panel.btn_lock_center.isChecked():
                        p1, p2 = active_values[0], active_values[1]
                        ct = (p1 + p2) / 2
                        other_new = 2 * ct - new_p
                        if curr_min <= other_new <= curr_max:
                            sorted_markers[idx].setPos(new_p)
                            sorted_markers[other_idx].setPos(other_new)
                    else: sorted_markers[idx].setPos(new_p)
                else: 
                    sorted_markers = sorted(active_markers, key=get_pos)
                    sorted_markers[idx].setPos(new_p)
                    
            elif len(active_values) == 2:
                p1, p2 = active_values[0], active_values[1]
                dt_coords, ct_coords = abs(p2 - p1), (p1 + p2) / 2
                if 'delta' in name:
                    if is_freq or is_filter: new_dt_coords = np.clip((val - 1) * rbw if 'sam' in name else val, 0, self.rate)
                    else: new_dt_coords = np.clip((val - 1) / self.rate if 'sam' in name else val, 0, self.time_duration)
                    m1_new, m2_new = ct_coords - new_dt_coords/2, ct_coords + new_dt_coords/2
                    if curr_min <= m1_new and m2_new <= curr_max:
                        if is_filter: self.filter_region.setRegion([m1_new, m2_new])
                        else:
                            sorted_markers = sorted(active_markers, key=get_pos)
                            sorted_markers[0].setPos(m1_new)
                            sorted_markers[1].setPos(m2_new)
                elif 'center' in name:
                    if is_freq or is_filter: new_ct_coords = np.clip((val - 1) * rbw + f_min if 'sam' in name else val, f_min, f_max)
                    else: new_ct_coords = np.clip((val - 1) / self.rate if 'sam' in name else val, 0.0, self.time_duration)
                    m1_new, m2_new = new_ct_coords - dt_coords/2, new_ct_coords + dt_coords/2
                    if curr_min <= m1_new and m2_new <= curr_max:
                        if is_filter: self.filter_region.setRegion([m1_new, m2_new])
                        else:
                            sorted_markers = sorted(active_markers, key=get_pos)
                            sorted_markers[0].setPos(m1_new)
                            sorted_markers[1].setPos(m2_new)
            self.update_marker_info()
            if is_filter: self.on_filter_region_finished()
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

    def refresh_spectrogram_markers(self):
        theme = self.settings_mgr.get("ui/theme", "Dark").lower()
        
        style_map = {
            "SolidLine": Qt.PenStyle.SolidLine,
            "DashLine": Qt.PenStyle.DashLine,
            "DotLine": Qt.PenStyle.DotLine,
            "DashDotLine": Qt.PenStyle.DashDotLine
        }

        t_color = self.settings_mgr.get(f"ui/{theme}/time_marker_color")
        t_style = style_map.get(str(self.settings_mgr.get(f"ui/{theme}/time_marker_style")), Qt.PenStyle.DashLine)
        
        f_color = self.settings_mgr.get(f"ui/{theme}/freq_marker_color")
        f_style = style_map.get(str(self.settings_mgr.get(f"ui/{theme}/freq_marker_style")), Qt.PenStyle.DashLine)
        
        for m in self.markers_time:
            m.setPen(pg.mkPen(t_color, width=2, style=t_style))
        for m in self.markers_freq:
            m.setPen(pg.mkPen(f_color, width=2, style=f_style))

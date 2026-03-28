import pyqtgraph as pg
import numpy as np
from PyQt6.QtCore import Qt
from ..themes import get_palette

class MarkerManagerMixin:
    def place_marker(self, scene_pos, drag_mode=False):
        if self.interaction_mode in ['ZOOM', 'MOVE']:
            return
            
        if self.spectrogram_view.plot_item.sceneBoundingRect().contains(scene_pos):
            vb = self.spectrogram_view.plot_item.vb
            mouse_v = vb.mapSceneToView(scene_pos)
            
            is_time = (self.interaction_mode in ['TIME', 'TIME_ENDLESS'])
            is_endless = 'ENDLESS' in self.interaction_mode
            
            if is_endless:
                active_markers = self.markers_time_endless if is_time else self.markers_freq_endless
            else:
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
                # 1. Hit-test for existing bounds
                if self.filter_bounds:
                    hit_threshold = 20 # pixels
                    vb = self.spectrogram_view.plot_item.vb
                    best_idx = -1
                    min_dist = hit_threshold
                    
                    # Sticky Lock: If 2 bounds exist and a lock is on, always hit the closest one
                    is_locked = len(self.filter_bounds) == 2 and (
                        self.marker_panel.btn_lock_delta.isChecked() or 
                        self.marker_panel.btn_lock_center.isChecked()
                    )
                    
                    for i, b_val in enumerate(self.filter_bounds):
                        p_scene = vb.mapViewToScene(pg.Point(0, b_val))
                        dist = abs(scene_pos.y() - p_scene.y())
                        if is_locked:
                            # Bypass threshold, find global nearest
                            if best_idx == -1 or dist < min_dist:
                                min_dist = dist
                                best_idx = i
                        elif dist < min_dist:
                            min_dist = dist
                            best_idx = i
                    
                    if best_idx != -1:
                        # Success: Drag existing bound
                        old_v = self.filter_bounds[best_idx]
                        
                        # --- LOCKED MOVEMENT SUPPORT ---
                        if len(self.filter_bounds) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                            shift = val - old_v
                            other_idx = 1 - best_idx
                            other_old_v = self.filter_bounds[other_idx]
                            
                            f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
                            
                            if self.marker_panel.btn_lock_delta.isChecked():
                                new_other_v = other_old_v + shift
                                if f_min <= val <= f_max and f_min <= new_other_v <= f_max:
                                    self.filter_bounds[best_idx] = val
                                    self.filter_bounds[other_idx] = new_other_v
                            elif self.marker_panel.btn_lock_center.isChecked():
                                center = (old_v + other_old_v) / 2
                                new_other_v = 2 * center - val
                                if f_min <= val <= f_max and f_min <= new_other_v <= f_max:
                                    self.filter_bounds[best_idx] = val
                                    self.filter_bounds[other_idx] = new_other_v
                            
                            # Sync both values in the placement-order tracker
                            for i, v in enumerate([old_v, other_old_v]):
                                if v in self.filter_marker_order:
                                    oidx = self.filter_marker_order.index(v)
                                    self.filter_marker_order[oidx] = self.filter_bounds[best_idx if i==0 else other_idx]
                        else:
                            # Standard single bound jump
                            self.filter_bounds[best_idx] = val 
                            if old_v in self.filter_marker_order:
                                oidx = self.filter_marker_order.index(old_v)
                                self.filter_marker_order[oidx] = val
                        
                        # Maintain sorted state for UI/Region
                        self.filter_bounds.sort()
                        self.active_drag_filter_bound_idx = self.filter_bounds.index(val)
                        
                        if len(self.filter_bounds) == 1:
                            if self.filter_line: self.filter_line.setPos(val)
                        else:
                            if self.filter_region: self.filter_region.setRegion(self.filter_bounds)
                        self.update_marker_info()
                        return

                # 2. No hit - Place new bound or replace oldest in PLACEMENT ORDER
                if len(self.filter_marker_order) >= 2:
                    oldest_v = self.filter_marker_order.pop(0)
                    if oldest_v in self.filter_bounds:
                        self.filter_bounds.remove(oldest_v)

                self.filter_marker_order.append(val)
                self.filter_bounds.append(val)
                self.filter_bounds.sort()
                self.active_drag_filter_bound_idx = self.filter_bounds.index(val)
                
                if len(self.filter_bounds) == 1:
                    if not self.filter_line:
                        self.filter_line = pg.InfiniteLine(angle=0, pen=pg.mkPen('#ff6400', width=2, style=Qt.PenStyle.DashLine))
                        self.filter_line.setZValue(10)
                    if self.filter_line not in self.spectrogram_view.plot_item.items:
                        self.spectrogram_view.plot_item.addItem(self.filter_line)
                    self.filter_line.setPos(val)
                    self.filter_line.show()
                else:
                    if self.filter_line: self.filter_line.hide()
                    f1 = self.filter_bounds[0]
                    f2 = self.filter_bounds[1]
                    if not self.filter_region:
                        # Lazily create the region
                        self.filter_region = pg.LinearRegionItem(
                            values=[f1, f2], orientation='horizontal',
                            brush=pg.mkBrush(255, 100, 0, 40), pen=pg.mkPen('#ff6400', width=2),
                            movable=False
                        )
                        self.filter_region.setZValue(9)
                        self.filter_region.sigRegionChanged.connect(self.on_filter_region_changed)
                        self.filter_region.sigRegionChangeFinished.connect(self.on_filter_region_finished)

                    if self.filter_region not in self.spectrogram_view.plot_item.items:
                        self.spectrogram_view.plot_item.addItem(self.filter_region)
                    else:
                        self.filter_region.setRegion(self.filter_bounds)
                        self.filter_region.show()
                    
                    self.filter_placed = True
                    self.marker_panel.filter_enable_cb.setEnabled(True)
                    if not drag_mode:
                        self.on_filter_region_finished()
                
                self.update_marker_info()
                return

            # 3. SECOND PRIORITY: Hit-test for dragging a single marker or grid line
            hit_threshold = 20 # pixels
            best_marker = None
            min_dist = float('inf')
            
            for m in active_markers:
                m_pos = m.value()
                p_scene = vb.mapViewToScene(pg.Point(m_pos, 0)) if is_time else vb.mapViewToScene(pg.Point(0, m_pos))
                dist = abs(scene_pos.x() - p_scene.x()) if is_time else abs(scene_pos.y() - p_scene.y())
                
                # Skip the locked marker so only the free one is draggable
                if len(active_markers) == 2 and (
                    self.marker_panel.btn_lock_m1.isChecked() or
                    self.marker_panel.btn_lock_m2.isChecked()
                ):
                    sorted_m = sorted(active_markers, key=lambda m: m.value())
                    locked_marker = sorted_m[0] if self.marker_panel.btn_lock_m1.isChecked() else sorted_m[1]
                    if m is locked_marker:
                        continue

                if dist < hit_threshold and dist < min_dist:
                    min_dist = dist
                    best_marker = m

            # If we hit a marker, move it and handle the logic (may move others if locked)
            if best_marker:
                is_drag_target = (self.active_drag_marker == best_marker) # Not really needed here, we just hit it
                
                # If a lock is active, move the other marker too
                if len(active_markers) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                    old_v = best_marker.value()
                    shift = val - old_v
                    other = active_markers[0] if active_markers[1] == best_marker else active_markers[1]
                    
                    if self.marker_panel.btn_lock_delta.isChecked():
                        other_new = other.value() + shift
                        if curr_min <= val <= curr_max and curr_min <= other_new <= curr_max:
                            best_marker.setPos(val)
                            other.setPos(other_new)
                    elif self.marker_panel.btn_lock_center.isChecked():
                        ct = (old_v + other.value()) / 2
                        other_new = 2 * ct - val
                        if curr_min <= val <= curr_max and curr_min <= other_new <= curr_max:
                            best_marker.setPos(val)
                            other.setPos(other_new)
                else:
                    best_marker.setPos(val)

                if drag_mode: self.active_drag_marker = best_marker
                self.update_marker_info()
                return

            # Check for Grid Lines (Shadow Markers)
            if self.interaction_mode in ['TIME', 'FREQ']:
                grid_lines = getattr(self, 'grid_lines_time' if is_time else 'grid_lines_freq', [])
                best_gl = None
                min_gl_dist = 20 # pixels
                
                for gl in grid_lines:
                    gl_pos = gl.value()
                    p_scene = vb.mapViewToScene(pg.Point(gl_pos, 0)) if is_time else vb.mapViewToScene(pg.Point(0, gl_pos))
                    dist = abs(scene_pos.x() - p_scene.x()) if is_time else abs(scene_pos.y() - p_scene.y())
                    
                    if dist < min_gl_dist:
                        min_gl_dist = dist
                        best_gl = gl
                
                if best_gl and len(active_markers) == 2:
                    # We hit a shadow marker! Calculate k and figure out which marker to move.
                    sorted_m = sorted(active_markers, key=lambda m: m.value())
                    p1, p2 = sorted_m[0].value(), sorted_m[1].value()
                    delta = p2 - p1
                    g_pos = best_gl.value()
                    k = (g_pos - p1) / delta if delta != 0.0 else 1.0
                    
                    lock_m1 = self.marker_panel.btn_lock_m1.isChecked()
                    lock_m2 = self.marker_panel.btn_lock_m2.isChecked()
                    lock_delta = self.marker_panel.btn_lock_delta.isChecked()
                    lock_center = self.marker_panel.btn_lock_center.isChecked()
                    
                    move_p1 = (k < 0.5)
                    if lock_m1 and not lock_m2: move_p1 = False
                    elif lock_m2 and not lock_m1: move_p1 = True
                    
                    if drag_mode:
                        self.active_drag_grid_info = {
                            'k': k,
                            'moving_marker': sorted_m[0] if move_p1 else sorted_m[1],
                            'fixed_marker': sorted_m[1] if move_p1 else sorted_m[0],
                            'is_p1': move_p1,
                            'is_time': is_time,
                            'lock_delta': lock_delta,
                            'lock_center': lock_center
                        }
                        self.active_drag_marker = None 
                    return

            # 4. THIRD PRIORITY: If 2 markers exist and lock is on, shift/teleport the pair
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
                self.update_marker_info()
                return

            # 5. LOWEST PRIORITY: Place brand new marker (and replace oldest if needed)
            if is_endless:
                theme = self.settings_mgr.get("ui/theme", "Dark").lower()
                color = self.settings_mgr.get(f"ui/{theme}/time_marker_color") if is_time else self.settings_mgr.get(f"ui/{theme}/freq_marker_color")
                
                m_count = len(active_markers)
                marker = pg.InfiniteLine(
                    pos=val, angle=angle, movable=False, 
                    pen=pg.mkPen(color, width=2, style=Qt.PenStyle.SolidLine),
                    label=f"M{m_count + 1}",
                    labelOpts={'position': 0.1, 'color': color, 'anchors': [(0,0), (0,0)]}
                )
                marker.setZValue(10)
                self.spectrogram_view.plot_item.addItem(marker, ignoreBounds=True)
                active_markers.append(marker)
                if drag_mode: self.active_drag_marker = marker
            else:
                # If a marker position is locked and we have 2 markers, move only the free one.
                lock_m1 = self.marker_panel.btn_lock_m1.isChecked()
                lock_m2 = self.marker_panel.btn_lock_m2.isChecked()
                if len(active_markers) == 2 and (lock_m1 or lock_m2):
                    sorted_m = sorted(active_markers, key=lambda m: m.value())
                    free_m = sorted_m[1] if lock_m1 else sorted_m[0]
                    locked_m = sorted_m[0] if lock_m1 else sorted_m[1]
                    free_m.setPos(val)
                    if drag_mode: self.active_drag_marker = free_m
                    # Swap list order and lock if free marker crossed the locked one
                    if (lock_m1 and val < locked_m.value()) or (lock_m2 and val > locked_m.value()):
                        active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                        self.marker_panel.flip_m_lock()
                else:
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
        if True: # Let mapSceneToView and np.clip handle out-of-bounds coordinates
            mouse_v = self.spectrogram_view.plot_item.vb.mapSceneToView(scene_pos)
            
            # 1. Handle explicit BPF bound dragging (highest priority)
            if self.interaction_mode == 'FILTER' and getattr(self, 'active_drag_filter_bound_idx', -1) != -1:
                idx = self.active_drag_filter_bound_idx
                f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
                raw_val = float(np.clip(mouse_v.y(), f_min, f_max))
                rbw = self.rate / self.fft_size
                bin_idx = int(round((raw_val - f_min) / rbw)) + 1
                new_v = f_min + (bin_idx - 1.0) * rbw
                
                old_v = self.filter_bounds[idx]
                
                # --- LOCKED MOVEMENT SUPPORT ---
                if len(self.filter_bounds) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                    shift = new_v - old_v
                    other_idx = 1 - idx
                    other_old_v = self.filter_bounds[other_idx]
                    
                    actual_new_v = old_v
                    actual_other_new_v = other_old_v
                    
                    if self.marker_panel.btn_lock_delta.isChecked():
                        potential_other = other_old_v + shift
                        if f_min <= new_v <= f_max and f_min <= potential_other <= f_max:
                            actual_new_v = new_v
                            actual_other_new_v = potential_other
                    elif self.marker_panel.btn_lock_center.isChecked():
                        center = (old_v + other_old_v) / 2
                        potential_other = 2 * center - new_v
                        if f_min <= new_v <= f_max and f_min <= potential_other <= f_max:
                            actual_new_v = new_v
                            actual_other_new_v = potential_other
                            
                    self.filter_bounds[idx] = actual_new_v
                    self.filter_bounds[other_idx] = actual_other_new_v
                    
                    # Sync placement order too
                    for v_old, v_new in [(old_v, actual_new_v), (other_old_v, actual_other_new_v)]:
                        if hasattr(self, 'filter_marker_order') and v_old in self.filter_marker_order:
                            oidx = self.filter_marker_order.index(v_old)
                            self.filter_marker_order[oidx] = v_new
                else:
                    # Standard single bound drag
                    self.filter_bounds[idx] = new_v
                    if hasattr(self, 'filter_marker_order') and old_v in self.filter_marker_order:
                        order_idx = self.filter_marker_order.index(old_v)
                        self.filter_marker_order[order_idx] = new_v
                
                if len(self.filter_bounds) == 2:
                    self.filter_bounds.sort()
                    # Re-find index to stay attached to the same edge
                    self.active_drag_filter_bound_idx = self.filter_bounds.index(new_v if (not (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked())) else self.filter_bounds[idx])
                
                if len(self.filter_bounds) == 1:
                    if self.filter_line: self.filter_line.setPos(new_v)
                elif len(self.filter_bounds) == 2:
                    if self.filter_region: self.filter_region.setRegion(self.filter_bounds)

                self.update_marker_info()
                return

            # 2. Handle BPF placement preview (rubberband between first bound and mouse)
            if self.interaction_mode == 'FILTER' and len(self.filter_bounds) == 1:
                f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
                raw_val = float(np.clip(mouse_v.y(), f_min, f_max))
                rbw = self.rate / self.fft_size
                bin_idx = int(round((raw_val - f_min) / rbw)) + 1
                new_v = f_min + (bin_idx - 1.0) * rbw
                
                f1 = self.filter_bounds[0]
                if not self.filter_region:
                    self.filter_region = pg.LinearRegionItem(
                        values=[f1, new_v], orientation='horizontal',
                        brush=pg.mkBrush(255, 100, 0, 40), pen=pg.mkPen('#ff6400', width=2),
                        movable=False
                    )
                    if self.filter_region not in self.spectrogram_view.plot_item.items:
                        self.spectrogram_view.plot_item.addItem(self.filter_region)
                    self.filter_region.sigRegionChanged.connect(self.on_filter_region_changed)
                    self.filter_region.sigRegionChangeFinished.connect(self.on_filter_region_finished)
                
                self.filter_region.setRegion([f1, new_v])
                self.filter_region.show()
                if self.filter_line: self.filter_line.hide()

                self.update_marker_info()
                return

            # 1.5 Handle Shadow Marker (Grid Line) dragging
            if getattr(self, 'active_drag_grid_info', None):
                info = self.active_drag_grid_info
                is_time = info['is_time']
                k = info['k']
                m_move = info['moving_marker']
                m_fixed = info['fixed_marker']
                is_p1 = info['is_p1']
                p_fixed = m_fixed.value()
                lock_delta = info.get('lock_delta', False)
                lock_center = info.get('lock_center', False)
                
                if is_time:
                    f_min, f_max = 0.0, self.time_duration
                    raw_val = float(np.clip(mouse_v.x(), 0.0, self.time_duration))
                    sample = int(round(raw_val * self.rate)) + 1
                    g_prime = (sample - 1.0) / self.rate
                else:
                    f_min, f_max = self.fc - self.rate/2, self.fc + self.rate/2
                    raw_val = float(np.clip(mouse_v.y(), f_min, f_max))
                    rbw = self.rate / self.fft_size
                    bin_idx = int(round((raw_val - f_min) / rbw)) + 1
                    g_prime = f_min + (bin_idx - 1.0) * rbw
                
                active_markers = self.markers_time if is_time else self.markers_freq
                if len(active_markers) == 2:
                    try:
                        if lock_delta:
                            # Dragging the whole grid while preserving delta
                            # k was calculated as (g - p1) / (p2 - p1)
                            # g = p1 + k*(p2 - p1)
                            sorted_m = sorted(active_markers, key=lambda m: m.value())
                            p1_orig, p2_orig = sorted_m[0].value(), sorted_m[1].value()
                            delta_orig = p2_orig - p1_orig
                            shift = g_prime - (p1_orig + k * delta_orig)
                            
                            new_p1, new_p2 = p1_orig + shift, p2_orig + shift
                            if f_min <= new_p1 <= f_max and f_min <= new_p2 <= f_max:
                                sorted_m[0].setPos(new_p1); sorted_m[1].setPos(new_p2)
                        elif lock_center:
                            sorted_m = sorted(active_markers, key=lambda m: m.value())
                            p1_orig, p2_orig = sorted_m[0].value(), sorted_m[1].value()
                            center = (p1_orig + p2_orig) / 2
                            if abs(k - 0.5) > 1e-9:
                                new_delta = (g_prime - center) / (k - 0.5)
                                new_p1 = center - new_delta / 2
                                new_p2 = center + new_delta / 2
                                if f_min <= new_p1 <= f_max and f_min <= new_p2 <= f_max:
                                    # Still don't allow inversion in center-locked mode as it's confusing
                                    if new_p1 <= new_p2:
                                        sorted_m[0].setPos(new_p1); sorted_m[1].setPos(new_p2)
                        else:
                            if is_p1:
                                if abs(1 - k) > 1e-9:
                                    new_v = (g_prime - k * p_fixed) / (1 - k)
                                    if f_min <= new_v <= f_max: m_move.setPos(new_v)
                            else:
                                if abs(k) > 1e-9:
                                    new_v = p_fixed + (g_prime - p_fixed) / k
                                    if f_min <= new_v <= f_max: m_move.setPos(new_v)
                            
                        # Crossing detection and swap
                        if (active_markers[0].value() > active_markers[1].value()):
                            active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                            self.marker_panel.flip_m_lock()
                    except ZeroDivisionError: pass
                    
                self.update_marker_info()
                return

            if not self.active_drag_marker:
                return

            is_time_endless = self.active_drag_marker in self.markers_time_endless
            is_freq_endless = self.active_drag_marker in self.markers_freq_endless
            is_endless = is_time_endless or is_freq_endless
            
            if is_endless:
                is_time = is_time_endless
                active_markers = self.markers_time_endless if is_time else self.markers_freq_endless
            else:
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

            if is_endless:
                self.active_drag_marker.setPos(new_v)
            elif len(active_markers) == 2:
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
                else:
                    self.active_drag_marker.setPos(new_v)
                    # Swap list order if the free marker crossed the locked one
                    lock_m1 = self.marker_panel.btn_lock_m1.isChecked()
                    lock_m2 = self.marker_panel.btn_lock_m2.isChecked()
                    if (lock_m1 or lock_m2) and len(active_markers) == 2:
                        sorted_m = sorted(active_markers, key=lambda m: m.value())
                        if active_markers[0] is not sorted_m[0]:  # order flipped
                            active_markers[0], active_markers[1] = active_markers[1], active_markers[0]
                            self.marker_panel.flip_m_lock()
            else: self.active_drag_marker.setPos(new_v)
            self.update_marker_info()

    def update_marker_info(self):
        # Determine the display mode for the table (e.g. if we are panning/zooming, we still want to see the last marker mode's info)
        display_mode = self.interaction_mode
        if display_mode in ['ZOOM', 'MOVE']:
            display_mode = getattr(self.marker_panel, 'last_marker_mode', 'TIME')
            
        is_freq = (display_mode in ['FREQ', 'FREQ_ENDLESS'])
        is_time = (display_mode in ['TIME', 'TIME_ENDLESS'])
        is_endless = 'ENDLESS' in display_mode
        is_filter = (display_mode == 'FILTER')
        
        if is_endless:
            markers = self.markers_time_endless if is_time else self.markers_freq_endless
            self.marker_panel.update_endless_list(markers, display_mode)
            if self.interaction_mode not in ['ZOOM', 'MOVE']: return

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
            widgets['inv'].clear()
        self.marker_panel.delta_sec.clear()
        self.marker_panel.delta_sam.clear()
        self.marker_panel.delta_inv.clear()
        self.marker_panel.center_sec.clear()
        self.marker_panel.center_sam.clear()
        self.marker_panel.center_inv.clear()

        if not active_values: return

        for i, val in enumerate(active_values):
            if i >= 2: break
            self.marker_panel.widgets[i]['sec'].blockSignals(True)
            self.marker_panel.widgets[i]['sam'].blockSignals(True)
            if is_freq or is_filter:
                rbw = self.rate / self.fft_size
                label_val = int(round((val - (self.fc - self.rate/2)) / rbw)) + 1
                label_val = max(1, min(label_val, self.fft_size))
                inv_val = (1.0 / val) if abs(val) > 1e-12 else float('inf')
            else:
                sample = int(round(val * self.rate)) + 1
                label_val = max(1, min(sample, getattr(self, 'total_samples_in_cache', 1e9)))
                inv_val = (1.0 / val) if abs(val) > 1e-12 else float('inf')
                
            prec = int(self.settings_mgr.get("ui/label_precision", 6 if (is_freq or is_filter) else 9))
            self.marker_panel.widgets[i]['sec'].setText(f"{val:.{prec}f}")
            self.marker_panel.widgets[i]['sam'].setText(f"{label_val}")
            if inv_val == float('inf'): self.marker_panel.widgets[i]['inv'].setText("∞")
            else: self.marker_panel.widgets[i]['inv'].setText(f"{inv_val:.{prec}f}")
            self.marker_panel.widgets[i]['sec'].blockSignals(False)
            self.marker_panel.widgets[i]['sam'].blockSignals(False)

        if len(active_values) == 2:
            p1, p2 = active_values[0], active_values[1]
            self.marker_panel.delta_sec.blockSignals(True)
            self.marker_panel.delta_sam.blockSignals(True)
            self.marker_panel.center_sec.blockSignals(True)
            self.marker_panel.center_sam.blockSignals(True)

            prec = int(self.settings_mgr.get("ui/label_precision", 6 if (is_freq or is_filter) else 9))
            dt = abs(p2 - p1)
            self.marker_panel.delta_sec.setText(f"{dt:.{prec}f}")
            if dt > 1e-12: self.marker_panel.delta_inv.setText(f"{1.0/dt:.{prec}f}")
            else: self.marker_panel.delta_inv.setText("∞")
                
            cp = (p1 + p2) / 2
            self.marker_panel.center_sec.setText(f"{cp:.{prec}f}")
            if abs(cp) > 1e-12: self.marker_panel.center_inv.setText(f"{1.0/cp:.{prec}f}")
            else: self.marker_panel.center_inv.setText("∞")

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
        
        # Sync lock button availability conditionally (we shouldn't disable all locks just because we entered ZOOM)
        if self.interaction_mode in ['ZOOM', 'MOVE']:
            pass # Keep them as they are
        elif is_filter:
            m1_p, m2_p = (len(active_values) >= 1), (len(active_values) >= 2)
            self.marker_panel.set_locks_enabled(m1_p, m2_p)
        elif not is_endless:
            m1_p, m2_p = (len(active_values) >= 1), (len(active_values) >= 2)
            self.marker_panel.set_locks_enabled(m1_p, m2_p)

        self.update_grid('TIME')
        self.update_grid('FREQ')

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        is_freq = (self.interaction_mode in ['FREQ', 'FREQ_ENDLESS'])
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
            
            if name.startswith('em_'):
                # Endless Marker Edit: em_{index}_{sec/sam}
                parts = name.split('_')
                idx = int(parts[1])
                unit = parts[2]
                
                active_list = self.markers_time_endless if not is_freq else self.markers_freq_endless
                if idx < len(active_list):
                    marker = active_list[idx]
                    if is_freq:
                        bin_val = max(1, min(val, self.fft_size))
                        new_p = np.clip(f_min + (bin_val - 1) * rbw if unit == 'sam' else val, f_min, f_max)
                    else:
                        max_s = getattr(self, 'total_samples_in_cache', 1e9)
                        s_val = np.clip(val if unit == 'sam' else val * self.rate + 1.0, 1, max_s)
                        new_p = np.clip((s_val - 1.0) / self.rate, 0.0, self.time_duration)
                    
                    marker.setPos(new_p)
                    self.update_marker_info()
                return

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
                    old_v = new_region[idx]
                    
                    if len(new_region) == 2 and (self.marker_panel.btn_lock_delta.isChecked() or self.marker_panel.btn_lock_center.isChecked()):
                        shift = new_p - old_v
                        other_idx = 1 - idx
                        other_old_v = new_region[other_idx]
                        
                        if self.marker_panel.btn_lock_delta.isChecked():
                            other_new = other_old_v + shift
                            if curr_min <= new_p <= curr_max and curr_min <= other_new <= curr_max:
                                new_region[idx] = new_p
                                new_region[other_idx] = other_new
                        elif self.marker_panel.btn_lock_center.isChecked():
                            center = (old_v + other_old_v) / 2
                            other_new = 2 * center - new_p
                            if curr_min <= new_p <= curr_max and curr_min <= other_new <= curr_max:
                                new_region[idx] = new_p
                                new_region[other_idx] = other_new
                    else:
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
        # Mutual exclusion between delta and center is already handled in the panel toggle handlers.
        # Nothing extra needed here for m1/m2 either — _clear_marker_locks does it.
        pass

    def handle_marker_clear(self, mode):
        if mode == 'FILTER':
            # 1. Remove items from plot
            if self.filter_line:
                self.spectrogram_view.plot_item.removeItem(self.filter_line)
                self.filter_line = None
            if self.filter_region:
                self.spectrogram_view.plot_item.removeItem(self.filter_region)
                self.filter_region = None
            
            # 2. Reset internal state
            self.filter_bounds = []
            self.filter_marker_order = []
            self.filter_placed = False
            self.filter_placing = False
            self.filter_enabled = False
            
            # 3. Update UI
            self.marker_panel.filter_enable_cb.setChecked(False)
            self.marker_panel.filter_enable_cb.setEnabled(False)
            self.marker_panel._clear_marker_locks(mode)
        elif mode == 'TIME_ENDLESS':
            for marker in self.markers_time_endless:
                self.spectrogram_view.plot_item.removeItem(marker)
            self.markers_time_endless.clear()
        elif mode == 'FREQ_ENDLESS':
            for marker in self.markers_freq_endless:
                self.spectrogram_view.plot_item.removeItem(marker)
            self.markers_freq_endless.clear()
        else:
            is_time = (mode == 'TIME')
            markers = self.markers_time if is_time else self.markers_freq
            for marker in markers:
                self.spectrogram_view.plot_item.removeItem(marker)
            markers.clear()
            # Disable grid when markers are cleared
            self.toggle_grid('TIME' if is_time else 'FREQ', False)
            self.marker_panel._clear_marker_locks(mode)
        self.update_marker_info()

    def remove_marker_item(self, marker, mode):
        """Remove a specific marker from the endless collections."""
        is_time = 'TIME' in mode
        active_markers = self.markers_time_endless if is_time else self.markers_freq_endless
        if marker in active_markers:
            self.spectrogram_view.plot_item.removeItem(marker)
            active_markers.remove(marker)
            # Renumber remaining labels
            for i, m in enumerate(active_markers):
                if hasattr(m, 'label'):
                    m.label.setText(f"M{i+1}")
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

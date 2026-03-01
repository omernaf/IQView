import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QProgressBar, QLineEdit, QGridLayout, QFrame, QCheckBox
from PyQt6.QtCore import pyqtSlot, Qt, QRectF
from PyQt6.QtGui import QFont, QAction
from utils import FileReaderThread

class CustomViewBox(pg.ViewBox):
    def __init__(self, ui_controller, *args, **kwds):
        super().__init__(*args, **kwds)
        self.ui_controller = ui_controller

    def mouseDragEvent(self, ev):
        if not hasattr(ev, 'isStart'):
            super().mouseDragEvent(ev)
            return
            
        if ev.button() == Qt.MouseButton.LeftButton:
            if ev.isStart():
                self.ui_controller.place_marker(ev.buttonDownScenePos(), drag_mode=True)
            elif ev.isFinish():
                self.ui_controller.active_drag_marker = None
            else:
                self.ui_controller.update_drag(ev.scenePos())
            ev.accept()
        else:
            super().mouseDragEvent(ev)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.ui_controller.place_marker(ev.scenePos(), drag_mode=False)
            ev.accept()
        else:
            super().mouseClickEvent(ev)

class SpectrogramWindow(QMainWindow):
    def __init__(self, file_path, data_type, sample_rate, center_freq, fft_size):
        super().__init__()
        self.setWindowTitle("Antigravity Spectrogram Viewer")
        self.resize(1024, 768)
        
        self.fc = center_freq
        self.rate = sample_rate
        self.fft_size = fft_size
        self.file_path = file_path
        self.data_type = data_type
        
        self.active_drag_marker = None
        self.markers = []
        self.time_duration = 1.0 # Default until data loads
        
        self.setup_ui()
        self.start_processing()

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.info_layout = QHBoxLayout()
        self.info_layout.setContentsMargins(10, 5, 10, 5)
        
        help_label = QLabel("<b>Interactive Controls:</b> Left Click/Drag - Place & Move Time Marker")
        self.info_layout.addWidget(help_label)
        self.layout.addLayout(self.info_layout)
        
        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)

        # Premium Marker Table Panel (Now Full Width below Progress Bar)
        self.marker_frame = QFrame()
        self.marker_frame.setStyleSheet("""
            QFrame { 
                background-color: #1e1e1e; 
                border: 1px solid #444; 
                border-radius: 6px; 
                padding: 4px; 
            }
            QLabel { 
                color: #DDD; 
            }
            QLineEdit {
                background-color: #111;
                color: #FFF;
                border: 1px solid #555;
                padding: 2px;
                border-radius: 2px;
            }
        """)
        self.marker_grid = QGridLayout(self.marker_frame)
        self.marker_grid.setSpacing(8)
        
        # Table Headers (Columns)
        self.marker_grid.addWidget(QLabel(""), 0, 0)
        header_font = QFont("Inter", 9, QFont.Weight.Bold)
        mono_font = QFont("Courier New", 10)
        
        col_headers = ["Marker 1", "Marker 2", "Delta (Δ)", "Center"]
        for col, text in enumerate(col_headers):
            h = QLabel(text)
            h.setFont(header_font)
            h.setStyleSheet("color: #AAA;")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.marker_grid.addWidget(h, 0, col + 1)

        # Row Labels
        r1_label = QLabel("Time (sec)")
        r2_label = QLabel("Samples")
        r1_label.setFont(header_font)
        r2_label.setFont(header_font)
        self.marker_grid.addWidget(r1_label, 1, 0)
        self.marker_grid.addWidget(r2_label, 2, 0)

        # Edit Widgets
        self.marker_widgets = []
        for i in range(2):
            sec_edit = QLineEdit()
            sec_edit.setFixedWidth(150)
            sec_edit.setFont(mono_font)
            sec_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_edit.setObjectName(f"m{i}_sec")
            
            sam_edit = QLineEdit()
            sam_edit.setFixedWidth(150)
            sam_edit.setFont(mono_font)
            sam_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sam_edit.setObjectName(f"m{i}_sam")
            
            sec_edit.returnPressed.connect(self.marker_edit_finished)
            sam_edit.returnPressed.connect(self.marker_edit_finished)
            
            self.marker_grid.addWidget(sec_edit, 1, i + 1)
            self.marker_grid.addWidget(sam_edit, 2, i + 1)
            self.marker_widgets.append({'sec': sec_edit, 'sam': sam_edit})

        # Delta Edits
        self.delta_sec = QLineEdit()
        self.delta_sec.setFixedWidth(150)
        self.delta_sec.setFont(mono_font)
        self.delta_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sec.setObjectName("delta_sec")
        self.delta_sec.returnPressed.connect(self.marker_edit_finished)
        self.marker_grid.addWidget(self.delta_sec, 1, 3)

        self.delta_sam = QLineEdit()
        self.delta_sam.setFixedWidth(150)
        self.delta_sam.setFont(mono_font)
        self.delta_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sam.setObjectName("delta_sam")
        self.delta_sam.returnPressed.connect(self.marker_edit_finished)
        self.marker_grid.addWidget(self.delta_sam, 2, 3)

        # Center Edits
        self.center_sec = QLineEdit()
        self.center_sec.setFixedWidth(150)
        self.center_sec.setFont(mono_font)
        self.center_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sec.setObjectName("center_sec")
        self.center_sec.returnPressed.connect(self.marker_edit_finished)
        self.marker_grid.addWidget(self.center_sec, 1, 4)

        self.center_sam = QLineEdit()
        self.center_sam.setFixedWidth(150)
        self.center_sam.setFont(mono_font)
        self.center_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sam.setObjectName("center_sam")
        self.center_sam.returnPressed.connect(self.marker_edit_finished)
        self.marker_grid.addWidget(self.center_sam, 2, 4)

        # Lock Row
        lock_label = QLabel("Lock State")
        lock_label.setFont(header_font)
        self.marker_grid.addWidget(lock_label, 3, 0)
        
        self.lock_delta_cb = QCheckBox("Lock Delta (Δ)")
        self.lock_center_cb = QCheckBox("Lock Center")
        self.lock_delta_cb.setStyleSheet("color: #DDD;")
        self.lock_center_cb.setStyleSheet("color: #DDD;")
        
        self.lock_delta_cb.toggled.connect(lambda checked: self.handle_lock_change('delta', checked))
        self.lock_center_cb.toggled.connect(lambda checked: self.handle_lock_change('center', checked))
        
        self.marker_grid.addWidget(self.lock_delta_cb, 3, 3)
        self.marker_grid.addWidget(self.lock_center_cb, 3, 4)

        self.layout.addWidget(self.marker_frame)
        
        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.layout.addWidget(self.graphics_layout)
        
        # Plot Item with Custom ViewBox
        self.view_box = CustomViewBox(ui_controller=self)
        self.plot_item = self.graphics_layout.addPlot(viewBox=self.view_box, title="Static Full-File Spectrogram")
        self.plot_item.setLabel('bottom', "Time", units='s')
        self.plot_item.setLabel('left', "Frequency", units='Hz')
        
        self.plot_item.setMouseEnabled(x=False, y=False)
        self.plot_item.hideButtons()
        
        self.img = pg.ImageItem()
        self.plot_item.addItem(self.img)
        
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img)
        self.graphics_layout.addItem(self.hist)

        colormap = pg.colormap.get('turbo')
        self.hist.gradient.setColorMap(colormap)
        self._current_cmap = colormap
        self._cmap_reversed = False
        
        # Disable the default viewbox menu so right-clicking purely opens the Colormap picker
        self.hist.vb.setMenuEnabled(False)
        
        # Override the Gradient editor menu to show native pyqtgraph top-level gradients with icons
        def custom_gradient_menu(ev):
            if ev.button() != Qt.MouseButton.RightButton:
                return
                
            from pyqtgraph.widgets.ColorMapMenu import ColorMapMenu
            from pyqtgraph.graphicsItems.GradientPresets import Gradients
            from PyQt6.QtGui import QAction
            
            # Feed the legacy preset gradients into the native ColorMapMenu generator
            presets = [(name, 'preset-gradient') for name in Gradients.keys()]
            menu = ColorMapMenu(userList=presets, showColorMapSubMenus=False, showGradientSubMenu=False)
            
            # Remove the 'None' option generated by Pyqtgraph natively
            for action in menu.actions():
                if action.text() == "None":
                    menu.removeAction(action)
                    break
                    
            menu.addSeparator()
            reverse_act = QAction("Reverse Colormap", menu)
            reverse_act.setCheckable(True)
            reverse_act.setChecked(self._cmap_reversed)
            menu.addAction(reverse_act)

            def handle_cmap_triggered(cmap):
                # When pyqtgraph native menu emits a cmap, we intercept it here to apply formatting
                self._current_cmap = cmap
                
                # Copy the colormap so we don't irreversibly corrupt the global Pyqtgraph cache
                import copy
                display_cmap = copy.deepcopy(cmap)
                if self._cmap_reversed:
                    display_cmap.reverse()
                self.hist.gradient.setColorMap(display_cmap)
                
            def toggle_reverse(checked):
                self._cmap_reversed = checked
                if hasattr(self, '_current_cmap'):
                    handle_cmap_triggered(self._current_cmap)
                    
            reverse_act.toggled.connect(toggle_reverse)
            menu.sigColorMapTriggered.connect(handle_cmap_triggered)
            
            menu.exec(ev.screenPos().toPoint())
            ev.accept()
            
        self.hist.gradient.mouseClickEvent = custom_gradient_menu
        

    def start_processing(self):
        self.worker = FileReaderThread(self.file_path, self.data_type, self.fft_size)
        
        self.worker.progress.connect(self.update_progress)
        self.worker.finished_processing.connect(self.display_spectrogram)
        self.worker.start()

    def place_marker(self, scene_pos, drag_mode=False):
        if self.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_v = self.plot_item.vb.mapSceneToView(scene_pos)
            pos_x = float(np.clip(mouse_v.x(), 0, self.time_duration))
            
            # If we have 2 markers and a lock is active, move the nearest one instead of adding/replacing
            if len(self.markers) == 2 and (self.lock_delta_cb.isChecked() or self.lock_center_cb.isChecked()):
                m0_dist = abs(self.markers[0].getXPos() - pos_x)
                m1_dist = abs(self.markers[1].getXPos() - pos_x)
                
                target = self.markers[0] if m0_dist < m1_dist else self.markers[1]
                other = self.markers[1] if m0_dist < m1_dist else self.markers[0]
                
                old_x = target.getXPos()
                shift = pos_x - old_x
                
                if self.lock_delta_cb.isChecked():
                    other_new_x = other.getXPos() + shift
                    if 0 <= other_new_x <= self.time_duration:
                        target.setPos(pos_x)
                        other.setPos(other_new_x)
                elif self.lock_center_cb.isChecked():
                    t1, t2 = self.markers[0].getXPos(), self.markers[1].getXPos()
                    ct = (t1 + t2) / 2
                    other_new_x = 2 * ct - pos_x
                    if 0 <= other_new_x <= self.time_duration:
                        target.setPos(pos_x)
                        other.setPos(other_new_x)
                
                if drag_mode:
                    self.active_drag_marker = target
            else:
                # Standard behavior: Add new or replace oldest
                if len(self.markers) >= 2:
                    old_marker = self.markers.pop(0)
                    self.plot_item.removeItem(old_marker)
                    
                marker = pg.InfiniteLine(
                    pos=pos_x, 
                    angle=90, 
                    movable=False,
                    pen=pg.mkPen('r', width=2)
                )
                self.plot_item.addItem(marker, ignoreBounds=True)
                self.markers.append(marker)
                
                if drag_mode:
                    self.active_drag_marker = marker
            
            self.update_marker_info()

    def update_drag(self, scene_pos):
        if self.active_drag_marker and self.plot_item.sceneBoundingRect().contains(scene_pos):
            mouse_v = self.plot_item.vb.mapSceneToView(scene_pos)
            new_x = float(np.clip(mouse_v.x(), 0, self.time_duration))
            
            # If locking is active, move the other marker relative to this one
            if len(self.markers) == 2:
                other_marker = self.markers[0] if self.markers[1] == self.active_drag_marker else self.markers[1]
                old_x = self.active_drag_marker.getXPos()
                shift = new_x - old_x
                
                if self.lock_delta_cb.isChecked():
                    other_new_x = other_marker.getXPos() + shift
                    # If other marker hits bounds, cap the movement of both
                    if 0 <= other_new_x <= self.time_duration:
                        self.active_drag_marker.setPos(new_x)
                        other_marker.setPos(other_new_x)
                elif self.lock_center_cb.isChecked():
                    # Keep existing center
                    t1, t2 = self.markers[0].getXPos(), self.markers[1].getXPos()
                    ct = (t1 + t2) / 2
                    other_new_x = 2 * ct - new_x
                    if 0 <= other_new_x <= self.time_duration:
                        self.active_drag_marker.setPos(new_x)
                        other_marker.setPos(other_new_x)
                else:
                    self.active_drag_marker.setPos(new_x)
            else:
                self.active_drag_marker.setPos(new_x)
                
            self.update_marker_info()

    def handle_lock_change(self, lock_type, checked):
        if not checked:
            return
            
        if lock_type == 'delta':
            self.lock_center_cb.blockSignals(True)
            self.lock_center_cb.setChecked(False)
            self.lock_center_cb.blockSignals(False)
        else:
            self.lock_delta_cb.blockSignals(True)
            self.lock_delta_cb.setChecked(False)
            self.lock_delta_cb.blockSignals(False)

    def update_marker_info(self):
        sorted_markers = sorted(self.markers, key=lambda m: m.getXPos())
        
        # Reset all fields
        for widgets in self.marker_widgets:
            widgets['sec'].clear()
            widgets['sam'].clear()
        self.delta_sec.clear()
        self.delta_sam.clear()
        self.center_sec.clear()
        self.center_sam.clear()

        if not sorted_markers:
            return

        for i, marker in enumerate(sorted_markers):
            t = marker.getXPos()
            samples = int(t * self.rate)
            
            self.marker_widgets[i]['sec'].blockSignals(True)
            self.marker_widgets[i]['sam'].blockSignals(True)
            self.marker_widgets[i]['sec'].setText(f"{t:.6f}")
            self.marker_widgets[i]['sam'].setText(f"{samples}")
            self.marker_widgets[i]['sec'].blockSignals(False)
            self.marker_widgets[i]['sam'].blockSignals(False)

        if len(sorted_markers) == 2:
            t1 = sorted_markers[0].getXPos()
            t2 = sorted_markers[1].getXPos()
            dt = abs(t2 - t1)
            ds = int(dt * self.rate)
            ct = (t1 + t2) / 2
            cs = int(ct * self.rate)
            
            self.delta_sec.blockSignals(True)
            self.delta_sam.blockSignals(True)
            self.center_sec.blockSignals(True)
            self.center_sam.blockSignals(True)
            
            self.delta_sec.setText(f"{dt:.6f}")
            self.delta_sam.setText(f"{ds}")
            self.center_sec.setText(f"{ct:.6f}")
            self.center_sam.setText(f"{cs}")
            
            self.delta_sec.blockSignals(False)
            self.delta_sam.blockSignals(False)
            self.center_sec.blockSignals(False)
            self.center_sam.blockSignals(False)

    def marker_edit_finished(self):
        sender = self.sender()
        name = sender.objectName()
        
        try:
            val = float(sender.text())
            sorted_markers = sorted(self.markers, key=lambda m: m.getXPos())

            if name.startswith('m') and len(sorted_markers) > int(name[1]):
                idx = int(name[1])
                unit = name[3:]
                new_t = val / self.rate if unit == 'sam' else val
                new_t = np.clip(new_t, 0, self.time_duration)
                
                if len(sorted_markers) == 2:
                    other_idx = 1 - idx
                    old_t = sorted_markers[idx].getXPos()
                    shift = new_t - old_t
                    
                    if self.lock_delta_cb.isChecked():
                        other_new_t = sorted_markers[other_idx].getXPos() + shift
                        if 0 <= other_new_t <= self.time_duration:
                            sorted_markers[idx].setPos(new_t)
                            sorted_markers[other_idx].setPos(other_new_t)
                    elif self.lock_center_cb.isChecked():
                        t1, t2 = sorted_markers[0].getXPos(), sorted_markers[1].getXPos()
                        ct = (t1 + t2) / 2
                        other_new_t = 2 * ct - new_t
                        if 0 <= other_new_t <= self.time_duration:
                            sorted_markers[idx].setPos(new_t)
                            sorted_markers[other_idx].setPos(other_new_t)
                    else:
                        sorted_markers[idx].setPos(new_t)
                else:
                    sorted_markers[idx].setPos(new_t)
            
            elif len(sorted_markers) == 2:
                t1, t2 = sorted_markers[0].getXPos(), sorted_markers[1].getXPos()
                dt = abs(t2 - t1)
                ct = (t1 + t2) / 2
                
                if 'delta' in name:
                    new_dt = val / self.rate if 'sam' in name else val
                    # Clamp delta to total duration
                    new_dt = np.clip(new_dt, 0, self.time_duration)
                    # Recalculate based on current center
                    m1_new = ct - new_dt/2
                    m2_new = ct + new_dt/2
                    # Final clamping to ensure logic doesn't push markers out
                    sorted_markers[0].setPos(np.clip(m1_new, 0, self.time_duration))
                    sorted_markers[1].setPos(np.clip(m2_new, 0, self.time_duration))
                elif 'center' in name:
                    new_ct = val / self.rate if 'sam' in name else val
                    new_ct = np.clip(new_ct, 0, self.time_duration)
                    # Shift markers keeping same distance
                    sorted_markers[0].setPos(np.clip(new_ct - dt/2, 0, self.time_duration))
                    sorted_markers[1].setPos(np.clip(new_ct + dt/2, 0, self.time_duration))
            
            self.update_marker_info()
        except ValueError:
            self.update_marker_info()

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(np.ndarray)
    def display_spectrogram(self, full_spectrogram):
        self.progress_bar.hide()
        min_v = float(np.min(full_spectrogram))
        max_v = float(np.max(full_spectrogram))
        
        num_time_steps = full_spectrogram.shape[1]
        self.time_duration = (num_time_steps * self.fft_size) / self.rate
        
        self.img.setImage(full_spectrogram, autoLevels=False, levels=[min_v, max_v], autoDownsample=True)
        self.img.setRect(QRectF(0, self.fc - self.rate/2, self.time_duration, self.rate))
        
        # Fit the view to the image data
        self.plot_item.autoRange()
        
        # Lock histogram view entirely so it stays simple and static
        self.hist.vb.setMouseEnabled(x=False, y=False)
        self.hist.vb.disableAutoRange()
        self.hist.vb.setLimits(yMin=min_v, yMax=max_v)
        self.hist.setLevels(min_v, max_v)
        self.hist.region.setBounds([min_v, max_v])

    def closeEvent(self, event):
        if hasattr(self, 'worker'):
            self.worker.stop()
        event.accept()

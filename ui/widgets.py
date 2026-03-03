import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6 import QtWidgets

class CustomViewBox(pg.ViewBox):
    def __init__(self, ui_controller, *args, **kwds):
        super().__init__(*args, **kwds)
        self.ui_controller = ui_controller
        self.zoom_rect = None
        self.setMenuEnabled(False) # Disable default pg menu

    def mouseDragEvent(self, ev, axis=None):
        if not hasattr(ev, 'isStart'):
            super().mouseDragEvent(ev)
            return
            
        if ev.button() == Qt.MouseButton.LeftButton:
            if self.ui_controller.interaction_mode == 'ZOOM':
                # --- Rubberband Zoom Logic ---
                if ev.isStart():
                    if self.zoom_rect: self.removeItem(self.zoom_rect)
                    # We'll use a QGraphicsPathItem for the dynamic 1D/2D visual
                    self.zoom_rect = QtWidgets.QGraphicsPathItem()
                    self.addItem(self.zoom_rect)
                    self.zoom_start_v = self.mapSceneToView(ev.buttonDownScenePos())
                    self.zoom_type = 'BOTH'
                
                elif ev.isFinish():
                    if self.zoom_rect:
                        rect = self.zoom_rect.path().boundingRect()
                        self.removeItem(self.zoom_rect)
                        self.zoom_rect = None
                        self.ui_controller.handle_zoom_rectangle(rect, self.zoom_type)
                else:
                    if self.zoom_rect:
                        curr_v = self.mapSceneToView(ev.scenePos())
                        p1, p2 = self.zoom_start_v, curr_v
                        
                        # Detect Zoom Type
                        xr, yr = self.viewRange()
                        dx, dy = abs(p2.x() - p1.x()), abs(p2.y() - p1.y())
                        ndx, ndy = dx / (xr[1]-xr[0]), dy / (yr[1]-yr[0])
                        
                        path = pg.QtGui.QPainterPath()
                        pen = pg.mkPen('#00aaff', width=2) # Premium Blue Accent
                        if ndx < 0.15 * ndy:
                            self.zoom_type = 'Y_ONLY'
                            # Vertical line with horizontal ticks
                            y_min, y_max = min(p1.y(), p2.y()), max(p1.y(), p2.y())
                            tick = (xr[1] - xr[0]) * 0.02
                            path.moveTo(p1.x(), y_min)
                            path.lineTo(p1.x(), y_max)
                            path.moveTo(p1.x() - tick, y_min)
                            path.lineTo(p1.x() + tick, y_min)
                            path.moveTo(p1.x() - tick, y_max)
                            path.lineTo(p1.x() + tick, y_max)
                        elif ndy < 0.15 * ndx:
                            self.zoom_type = 'X_ONLY'
                            # Horizontal line with vertical ticks
                            x_min, x_max = min(p1.x(), p2.x()), max(p1.x(), p2.x())
                            tick = (yr[1] - yr[0]) * 0.02
                            path.moveTo(x_min, p1.y())
                            path.lineTo(x_max, p1.y())
                            path.moveTo(x_min, p1.y() - tick)
                            path.lineTo(x_min, p1.y() + tick)
                            path.moveTo(x_max, p1.y() - tick)
                            path.lineTo(x_max, p1.y() + tick)
                        else:
                            self.zoom_type = 'BOTH'
                            pen = pg.mkPen('#00aaff', width=2, style=Qt.PenStyle.DashLine)
                            self.zoom_rect.setBrush(pg.mkBrush(0, 170, 255, 40))
                            path.addRect(pg.QtCore.QRectF(p1, p2))
                        
                        self.zoom_rect.setPath(path)
                        self.zoom_rect.setPen(pen)
                ev.accept()
            elif self.ui_controller.interaction_mode == 'MOVE':
                if ev.isStart():
                    self.ui_controller.handle_move_drag(ev.buttonDownScenePos(), is_start=True)
                elif ev.isFinish():
                    self.ui_controller.handle_move_drag(ev.scenePos(), is_finish=True)
                else:
                    self.ui_controller.handle_move_drag(ev.scenePos())
                ev.accept()
            else:
                # --- Marker Logic ---
                if self.ui_controller.interaction_mode in ['TIME', 'FREQ']:
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
            if self.ui_controller.interaction_mode in ['TIME', 'FREQ']:
                self.ui_controller.place_marker(ev.scenePos(), drag_mode=False)
            ev.accept()
        elif ev.button() == Qt.MouseButton.RightButton:
            self.raise_custom_menu(ev)
            ev.accept()
        else:
            super().mouseClickEvent(ev)

    def raise_custom_menu(self, ev):
        menu = QtWidgets.QMenu()
        
        view_all_act = menu.addAction("View All")
        view_all_act.triggered.connect(self.ui_controller.reset_zoom)
        
        fit_act = menu.addAction("Fit to Screen")
        active_markers = self.ui_controller.markers_freq if self.ui_controller.interaction_mode == 'FREQ' else self.ui_controller.markers_time
        fit_act.setEnabled(len(active_markers) == 2)
        fit_act.triggered.connect(self.ui_controller.fit_to_markers)
        
        menu.addSeparator()
        
        # Time Grid Submenu
        grid_time_menu = menu.addMenu("Time Grid")
        grid_time_menu.setEnabled(len(self.ui_controller.markers_time) == 2)
        
        grid_time_enable_act = grid_time_menu.addAction("Enabled")
        grid_time_enable_act.setCheckable(True)
        grid_time_enable_act.setChecked(self.ui_controller.grid_time_enabled)
        grid_time_enable_act.triggered.connect(lambda checked: self.ui_controller.toggle_grid('TIME', checked))
        
        grid_time_track_act = grid_time_menu.addAction("Tracking")
        grid_time_track_act.setCheckable(True)
        grid_time_track_act.setChecked(self.ui_controller.grid_time_tracking)
        grid_time_track_act.triggered.connect(lambda checked: self.ui_controller.toggle_tracking('TIME', checked))
        
        # Freq Grid Submenu
        grid_freq_menu = menu.addMenu("Frequency Grid")
        grid_freq_menu.setEnabled(len(self.ui_controller.markers_freq) == 2)
        
        grid_freq_enable_act = grid_freq_menu.addAction("Enabled")
        grid_freq_enable_act.setCheckable(True)
        grid_freq_enable_act.setChecked(self.ui_controller.grid_freq_enabled)
        grid_freq_enable_act.triggered.connect(lambda checked: self.ui_controller.toggle_grid('FREQ', checked))
        
        grid_freq_track_act = grid_freq_menu.addAction("Tracking")
        grid_freq_track_act.setCheckable(True)
        grid_freq_track_act.setChecked(self.ui_controller.grid_freq_tracking)
        grid_freq_track_act.triggered.connect(lambda checked: self.ui_controller.toggle_tracking('FREQ', checked))
        
        menu.addSeparator()
        
        export_act = menu.addAction("Export...")
        def open_export():
            try:
                from pyqtgraph.exportDialog import ExportDialog
            except ImportError:
                # Fallback for different pyqtgraph versions
                from pyqtgraph.exporters.exportDialog import ExportDialog
            self.export_dialog = ExportDialog(self.scene())
            self.export_dialog.show()
        export_act.triggered.connect(open_export)
        
        menu.exec(ev.screenPos().toPoint())

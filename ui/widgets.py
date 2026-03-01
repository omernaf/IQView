import pyqtgraph as pg
from PyQt6.QtCore import Qt

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

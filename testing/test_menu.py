import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication
from pyqtgraph.widgets.ColorMapMenu import ColorMapMenu
from pyqtgraph.graphicsItems.GradientPresets import Gradients

app = QApplication([])
user_list = [(name, 'preset-gradient') for name in Gradients.keys()]
menu = ColorMapMenu(userList=user_list)

import sys
import threading
def save_and_close():
    pg.QtGui.QApplication.processEvents()
    for act in menu.actions():
        print(act.data())
    app.quit()
threading.Timer(1.0, save_and_close).start()

menu.exec(pg.QtCore.QPoint(0,0))

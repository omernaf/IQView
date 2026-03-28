
import sys, time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication.instance() or QApplication(sys.argv)
import cProfile, pstats
import iqview.main
from iqview.ui.main_window.data_handler import DataHandlerMixin
original_display = DataHandlerMixin.display_lazy_tile
def mock_display(self, *args, **kwargs):
    original_display(self, *args, **kwargs)
    print('Rendered lazy tile!')
    QApplication.quit()
DataHandlerMixin.display_lazy_tile = mock_display

pr = cProfile.Profile()
pr.enable()
t0 = time.time()
import iqview.ui.main_window
window = iqview.ui.main_window.SpectrogramWindow('samples/fake_huge.32fc', 'complex64', 1_000_000, 433_000_000, 1024, is_complex=True, lazy_rendering=True)
window.show()

QTimer.singleShot(15000, QApplication.quit)
app.exec()
pr.disable()
stats = pstats.Stats(pr).sort_stats('tottime')
stats.print_stats(30)

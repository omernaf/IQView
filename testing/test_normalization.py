"""
test_normalization.py — Comprehensive unit tests for Normalization Factor (dB).
"""

import sys
import unittest
from unittest.mock import MagicMock
import numpy as np
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox

# Ensure non-interactive execution
QMessageBox.information = lambda *a, **k: None
QMessageBox.warning = lambda *a, **k: None
QMessageBox.critical = lambda *a, **k: None

from iqview.ui.side_panel import SidePanel
from iqview.dsp.utils import FileReaderThread, ViewportAwareReader, MultiRowProcessor
from iqview.ui.main_window.data_handler import DataHandlerMixin
from iqview.ui.main_window.view_controller import ViewControllerMixin
from iqview.utils.settings_manager import SettingsManager


def _make_interleaved_bytes(complex_array: np.ndarray) -> bytes:
    """Helper to convert complex64 array to interleaved float32 bytes as used in IQView."""
    interleaved = np.empty(len(complex_array) * 2, dtype=np.float32)
    interleaved[0::2] = complex_array.real.astype(np.float32)
    interleaved[1::2] = complex_array.imag.astype(np.float32)
    return interleaved.tobytes()


class _MockMainWindow(QMainWindow, ViewControllerMixin, DataHandlerMixin):
    def __init__(self, data_source=None, data_type=np.float32, rate=1e6, fc=0.0, norm_db=0.0):
        super().__init__()
        self.settings_mgr = SettingsManager()
        self.data_source = data_source
        self.data_type = data_type
        self.rate = rate
        self.fc = fc
        self.fft_size = 1024
        self.window_size = 1024
        self.window_type = "Hamming"
        self.overlap_percent = 100.0
        self.is_complex = True
        self.profile_enabled = False
        self.filter_mode = None
        self.filter_bounds = []
        self.time_duration = 1.0
        self.norm_db = float(norm_db)
        self.reprocess_called = False
        self.markers_time = []
        self.markers_freq = []
        self.update_marker_info = MagicMock()

        # Mock spectrogram view
        self.spectrogram_view = MagicMock()
        self.spectrogram_view.is_waterfall = False
        self.spectrogram_view.plot_item = MagicMock()
        self.spectrogram_view.view_box = MagicMock()
        self.spectrogram_view.plot_item.viewRange.return_value = [[0.0, 1.0], [-500000.0, 500000.0]]
        self.spectrogram_view.level_region = MagicMock()
        self.spectrogram_view.level_region.getRegion.return_value = [-100.0, 0.0]
        self.spectrogram_view.level_region.lines = []

    def start_processing(self):
        self.reprocess_called = True


class TestNormalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_side_panel_defaults_and_ui(self):
        """Test that SidePanel defaults to 0 dB and displays properly."""
        panel = SidePanel(fs=1e6, fc=0.0, fft_size=1024)
        self.assertEqual(panel.norm_db, 0.0)
        self.assertTrue(hasattr(panel, 'norm_edit'))
        self.assertEqual(panel.norm_edit.text(), "0")

    def test_side_panel_custom_init(self):
        """Test initializing SidePanel with a non-zero normalization factor."""
        panel = SidePanel(fs=1e6, fc=0.0, fft_size=1024, norm_db=10.0)
        self.assertEqual(panel.norm_db, 10.0)
        self.assertEqual(panel.norm_edit.text(), "10")

    def test_side_panel_edit_signal(self):
        """Test that editing normalization factor emits parametersChanged with norm_db."""
        panel = SidePanel(fs=1e6, fc=0.0, fft_size=1024)
        received_params = []
        panel.parametersChanged.connect(lambda p: received_params.append(p))

        panel.norm_edit.setText("10")
        panel.on_edit_finished()

        self.assertEqual(len(received_params), 1)
        self.assertIn('norm_db', received_params[0])
        self.assertEqual(received_params[0]['norm_db'], 10.0)
        self.assertEqual(panel.norm_db, 10.0)

    def test_side_panel_update_params(self):
        """Test external update_params updates norm_db and line edit."""
        panel = SidePanel(fs=1e6, fc=0.0, fft_size=1024)
        panel.update_params(norm_db=15.5)
        self.assertEqual(panel.norm_db, 15.5)
        self.assertEqual(panel.norm_edit.text(), "15.5")

    def test_extract_iq_segment_power_scaling(self):
        """Test that extract_iq_segment scales samples according to power-based dB scaling."""
        n = 10000
        tone = np.exp(2j * np.pi * 1000 * np.arange(n) / 1e6).astype(np.complex64)
        data_bytes = _make_interleaved_bytes(tone)

        # Window with norm_db = 0.0
        win0 = _MockMainWindow(data_source=data_bytes, data_type=np.float32, rate=1e6, norm_db=0.0)
        samples0 = win0.extract_iq_segment(0.0, 0.005)
        self.assertIsNotNone(samples0)
        pwr0 = np.mean(np.abs(samples0) ** 2)

        # Window with norm_db = 10.0 dB
        # 10 dB normalization must make power exactly 10x smaller (i.e. pwr1 / pwr0 = 0.1)
        win10 = _MockMainWindow(data_source=data_bytes, data_type=np.float32, rate=1e6, norm_db=10.0)
        samples10 = win10.extract_iq_segment(0.0, 0.005)
        self.assertIsNotNone(samples10)
        pwr10 = np.mean(np.abs(samples10) ** 2)

        # Power ratio should be 0.1 (10 times smaller)
        power_ratio = pwr10 / pwr0
        self.assertAlmostEqual(power_ratio, 0.1, places=5)

        # Amplitude ratio should be 10^(-10/20) = 1/sqrt(10) ~ 0.3162277
        amp_ratio = np.mean(np.abs(samples10)) / np.mean(np.abs(samples0))
        expected_amp_ratio = 10.0 ** (-10.0 / 20.0)
        self.assertAlmostEqual(amp_ratio, expected_amp_ratio, places=5)

        # Difference in dB should be exactly 10.0 dB
        delta_db = 10.0 * np.log10(pwr0) - 10.0 * np.log10(pwr10)
        self.assertAlmostEqual(delta_db, 10.0, places=4)

    def test_file_reader_thread_spectrogram_scaling(self):
        """Test that FileReaderThread reduces output dB by exactly norm_db."""
        np.random.seed(42)
        n = 8192
        signal = (np.exp(2j * np.pi * 50e3 * np.arange(n) / 1e6) +
                  0.1 * (np.random.randn(n) + 1j * np.random.randn(n))).astype(np.complex64)
        data_bytes = _make_interleaved_bytes(signal)

        # Run with norm_db = 0.0
        spec0 = []
        worker0 = FileReaderThread(data_bytes, np.float32, 1024, 0.0, 1e6, is_complex=True, norm_db=0.0)
        worker0.finished_processing.connect(lambda s, t0, t1: spec0.append(s))
        worker0.run()
        self.assertEqual(len(spec0), 1)

        # Run with norm_db = 10.0
        spec10 = []
        worker10 = FileReaderThread(data_bytes, np.float32, 1024, 0.0, 1e6, is_complex=True, norm_db=10.0)
        worker10.finished_processing.connect(lambda s, t0, t1: spec10.append(s))
        worker10.run()
        self.assertEqual(len(spec10), 1)

        # Difference for all non-clipped bins should be 10.0 dB within float32 precision
        diff = spec0[0] - spec10[0]
        mask = spec10[0] > -200
        np.testing.assert_allclose(diff[mask], 10.0, atol=1e-3)

    def test_viewport_aware_reader_spectrogram_scaling(self):
        """Test that ViewportAwareReader reduces output dB by exactly norm_db."""
        np.random.seed(42)
        n = 8192
        signal = (np.exp(2j * np.pi * 50e3 * np.arange(n) / 1e6) +
                  0.1 * (np.random.randn(n) + 1j * np.random.randn(n))).astype(np.complex64)
        data_bytes = _make_interleaved_bytes(signal)

        spec0 = []
        worker0 = ViewportAwareReader(data_bytes, np.float32, 1024, 1e6, 0.0, 0.008, 100, is_complex=True, norm_db=0.0)
        worker0.finished_processing.connect(lambda s, t0, t1: spec0.append(s))
        worker0.run()
        self.assertEqual(len(spec0), 1)

        spec10 = []
        worker10 = ViewportAwareReader(data_bytes, np.float32, 1024, 1e6, 0.0, 0.008, 100, is_complex=True, norm_db=10.0)
        worker10.finished_processing.connect(lambda s, t0, t1: spec10.append(s))
        worker10.run()
        self.assertEqual(len(spec10), 1)

        diff = spec0[0] - spec10[0]
        mask = spec10[0] > -200
        np.testing.assert_allclose(diff[mask], 10.0, atol=1e-3)

    def test_multi_row_processor_spectrogram_scaling(self):
        """Test that MultiRowProcessor reduces output dB by exactly norm_db."""
        np.random.seed(42)
        n = 8192
        signal = (np.exp(2j * np.pi * 50e3 * np.arange(n) / 1e6) +
                  0.1 * (np.random.randn(n) + 1j * np.random.randn(n))).astype(np.complex64)
        data_bytes = _make_interleaved_bytes(signal)

        results0 = []
        worker0 = MultiRowProcessor(data_bytes, np.float32, 1024, 1e6, num_rows=2,
                                     start_sample=0, samples_per_row=2048, period=2048,
                                     is_complex=True, norm_db=0.0)
        worker0.finished.connect(lambda r: results0.append(r))
        worker0.run()
        self.assertEqual(len(results0), 1)

        results10 = []
        worker10 = MultiRowProcessor(data_bytes, np.float32, 1024, 1e6, num_rows=2,
                                      start_sample=0, samples_per_row=2048, period=2048,
                                      is_complex=True, norm_db=10.0)
        worker10.finished.connect(lambda r: results10.append(r))
        worker10.run()
        self.assertEqual(len(results10), 1)

        for row_i in range(2):
            diff = results0[0][row_i] - results10[0][row_i]
            mask = results10[0][row_i] > -200
            np.testing.assert_allclose(diff[mask], 10.0, atol=1e-2)

    def test_view_controller_parameter_change(self):
        """Test on_parameters_changed triggers reprocess when norm_db changes."""
        win = _MockMainWindow(norm_db=0.0)
        win.sidebar = SidePanel(fs=1e6, fc=0.0, fft_size=1024)

        params = {
            'fs': win.rate,
            'fc': win.fc,
            'norm_db': 12.0,
            'fft_size': win.fft_size,
            'window_size': win.window_size,
            'window_type': win.window_type,
            'overlap_percent': win.overlap_percent,
        }
        win.on_parameters_changed(params)
        self.assertEqual(win.norm_db, 12.0)
        self.assertTrue(win.reprocess_called)


if __name__ == '__main__':
    unittest.main()

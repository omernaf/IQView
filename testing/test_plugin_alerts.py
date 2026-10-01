"""testing/test_plugin_alerts.py

Unit tests for the fail-safe pop-up alert system across PluginResult, PluginContext,
PluginChain, PluginManagerMixin, and built-in plugins (LoRa, FSK, UW Sync, FEC, CRC, Snap).
"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from iqview.plugins.plugin_result import PluginResult
from iqview.plugins.context import PluginContext, PluginParams
from iqview.plugins.chain import PluginChain
from iqview.plugins.plugin_manager import _merge_plugin_results, PluginManagerMixin
from iqview.ui.overlay import Overlay, OverlayShape

import iqview.plugins.builtin.lora_demodulator as lora_mod
import iqview.plugins.builtin.fsk_demodulator as fsk_mod
import iqview.plugins.builtin.uw_sync as uw_mod
import iqview.plugins.builtin.block_fec_decoder as fec_mod
import iqview.plugins.builtin.crc_checker as crc_mod
import iqview.plugins.builtin.snap_to_burst as snap_mod


class TestPluginResultAlerts(unittest.TestCase):
    def test_alert_builder_methods(self):
        res = PluginResult()
        self.assertEqual(res.alerts, [])

        ret = res.info("Info message", title="My Info")
        self.assertIs(ret, res)
        ret = res.warning("Warning message", title="My Warn")
        self.assertIs(ret, res)
        ret = res.error("Error message", title="My Err")
        self.assertIs(ret, res)
        ret = res.alert("Custom message", level="UNKNOWN")
        self.assertIs(ret, res)

        self.assertEqual(len(res.alerts), 4)
        self.assertEqual(res.alerts[0], {"message": "Info message", "title": "My Info", "level": "info"})
        self.assertEqual(res.alerts[1], {"message": "Warning message", "title": "My Warn", "level": "warning"})
        self.assertEqual(res.alerts[2], {"message": "Error message", "title": "My Err", "level": "error"})
        self.assertEqual(res.alerts[3], {"message": "Custom message", "title": None, "level": "warning"})
        self.assertIn("alerts=4", repr(res))


class TestPluginContextAlerts(unittest.TestCase):
    def test_context_alert_methods_and_copy(self):
        ctx = PluginContext(
            sample_rate=1e6,
            center_freq=0.0,
            t_start=0.0,
            t_end=1.0,
            f_start=-500e3,
            f_end=500e3,
        )
        self.assertEqual(ctx.alerts, [])
        ctx.warning("Context warning", title="Ctx Warn")
        self.assertEqual(len(ctx.alerts), 1)
        self.assertEqual(ctx.alerts[0]["level"], "warning")

        ctx2 = ctx.copy_with(t_start=0.2)
        self.assertEqual(len(ctx2.alerts), 1)
        self.assertEqual(ctx2.alerts[0]["message"], "Context warning")


class TestChainAlertAggregation(unittest.TestCase):
    def test_chain_aggregates_step_alerts(self):
        def step1(samples, info):
            res = PluginResult()
            res.warning("Issue in step 1")
            return res

        def step2(samples, info):
            # Queue alert via info directly
            info.error("Critical issue in step 2")
            return PluginResult()

        chain = PluginChain(
            name="TestChain",
            steps=[
                (step1, {}, "First Step"),
                (step2, {}, "Second Step"),
            ]
        )

        ctx = PluginContext(
            sample_rate=1e6,
            center_freq=0.0,
            t_start=0.0,
            t_end=1.0,
            f_start=-500e3,
            f_end=500e3,
        )

        res = chain.run(np.zeros(100, dtype=np.complex64), ctx)
        self.assertEqual(len(res.alerts), 2)
        self.assertEqual(res.alerts[0]["source"], "First Step")
        self.assertEqual(res.alerts[0]["message"], "Issue in step 1")
        self.assertEqual(res.alerts[0]["level"], "warning")

        self.assertEqual(res.alerts[1]["source"], "Second Step")
        self.assertEqual(res.alerts[1]["message"], "Critical issue in step 2")
        self.assertEqual(res.alerts[1]["level"], "error")

    def test_batch_merge_preserves_alerts(self):
        target = PluginResult()
        part = PluginResult().warning("Batch warning")
        _merge_plugin_results(target, part)
        self.assertEqual(len(target.alerts), 1)
        self.assertEqual(target.alerts[0]["message"], "Batch warning")


class TestPluginManagerAlertPopups(unittest.TestCase):
    class DummyHost(PluginManagerMixin):
        def __init__(self):
            self._loaded_plugins = {}
            self.tabs = MagicMock()
            self._plugin_launch_mode = None
            self._statusBar = MagicMock()

        def statusBar(self):
            return self._statusBar

        def save_plugin_params(self, name):
            pass

    @patch("iqview.plugins.plugin_manager.QMessageBox")
    def test_single_alert_popup(self, mock_msgbox):
        host = self.DummyHost()
        res = PluginResult().warning("Could not demodulate bursts", title="My Modem")
        host._on_plugin_finished("My Modem", res)

        mock_msgbox.warning.assert_called_once()
        args, kwargs = mock_msgbox.warning.call_args
        self.assertEqual(args[0], host)
        self.assertEqual(args[1], "My Modem")
        self.assertIn("Could not demodulate bursts", args[2])

    @patch("iqview.plugins.plugin_manager.QMessageBox")
    def test_multiple_alerts_grouped_popup(self, mock_msgbox):
        host = self.DummyHost()
        res = PluginResult()
        res.warning("Warning 1", title="Step A")
        res.error("Error 2", title="Step B")
        host._on_plugin_finished("Test Chain", res)

        # Since one alert is error, highest severity QMessageBox.critical is used
        mock_msgbox.critical.assert_called_once()
        args, kwargs = mock_msgbox.critical.call_args
        self.assertEqual(args[0], host)
        self.assertEqual(args[1], "Plugin Error — Test Chain")
        self.assertIn("Step A", args[2])
        self.assertIn("Warning 1", args[2])
        self.assertIn("Step B", args[2])
        self.assertIn("Error 2", args[2])


class TestBuiltinPluginFailSafes(unittest.TestCase):
    def test_lora_no_overlays(self):
        ctx = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3, overlays=[]
        )
        res = lora_mod.run(np.zeros(1000, dtype=np.complex64), ctx)
        self.assertEqual(len(res.alerts), 1)
        self.assertEqual(res.alerts[0]["level"], "warning")
        self.assertIn("No Rect overlays found", res.alerts[0]["message"])

    def test_lora_demod_failure_alert(self):
        # Noise burst that cannot be demodulated as LoRa
        rect = Overlay(shape=OverlayShape.RECT, points=[(0.1, -100e3), (0.2, 100e3)])
        rect.id = "test_rect_1"
        rect.iq = np.zeros(2048, dtype=np.complex64)
        rect.fs = 250e3

        ctx = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3,
            overlays=[rect]
        )
        res = lora_mod.run(np.zeros(1000, dtype=np.complex64), ctx)
        self.assertEqual(len(res.alerts), 1)
        self.assertEqual(res.alerts[0]["level"], "warning")
        self.assertIn("Could not synchronize or demodulate any LoRa bursts", res.alerts[0]["message"])

    def test_fsk_no_overlays_and_failure(self):
        ctx = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3, overlays=[]
        )
        res = fsk_mod.run(np.zeros(1000, dtype=np.complex64), ctx)
        self.assertEqual(len(res.alerts), 1)
        self.assertIn("No Rect overlays found", res.alerts[0]["message"])

    def test_uw_sync_alerts(self):
        # 1. Invalid sync word hex
        rect = Overlay(shape=OverlayShape.RECT, points=[(0.1, -100e3), (0.2, 100e3)])
        rect.metadata = {"bits": "10101010"}
        ctx = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3,
            overlays=[rect], params={"uw_hex": "INVALID_HEX"}
        )
        res = uw_mod.run(np.zeros(100, dtype=np.complex64), ctx)
        self.assertEqual(len(res.alerts), 1)
        self.assertEqual(res.alerts[0]["level"], "error")
        self.assertIn("Invalid or empty sync word hex", res.alerts[0]["message"])

        # 2. No bits in metadata
        rect_nobits = Overlay(shape=OverlayShape.RECT, points=[(0.1, -100e3), (0.2, 100e3)])
        rect_nobits.metadata = {}
        ctx_nobits = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3,
            overlays=[rect_nobits], params={"uw_hex": "0x7E76"}
        )
        res_nobits = uw_mod.run(np.zeros(100, dtype=np.complex64), ctx_nobits)
        self.assertEqual(len(res_nobits.alerts), 1)
        self.assertEqual(res_nobits.alerts[0]["level"], "warning")
        self.assertIn("None of the candidate bursts contain demodulated 'bits'", res_nobits.alerts[0]["message"])

    def test_block_fec_invalid_custom_g(self):
        rect = Overlay(shape=OverlayShape.RECT, points=[(0.1, -100e3), (0.2, 100e3)])
        rect.metadata = {"bits": "10101010"}
        ctx = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3,
            overlays=[rect], params={"code": "Custom Generator Matrix", "custom_g_matrix": "invalid matrix"}
        )
        res = fec_mod.run(np.zeros(100, dtype=np.complex64), ctx)
        self.assertEqual(len(res.alerts), 1)
        self.assertEqual(res.alerts[0]["level"], "error")
        self.assertIn("Invalid Custom Generator Matrix", res.alerts[0]["message"])

    def test_crc_checker_alerts(self):
        # 1. Invalid width
        rect = Overlay(shape=OverlayShape.RECT, points=[(0.1, -100e3), (0.2, 100e3)])
        rect.metadata = {"bits": "10101010"}
        ctx = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3,
            overlays=[rect], params={"preset": "Custom", "crc_bits": 64}
        )
        res = crc_mod.run(np.zeros(100, dtype=np.complex64), ctx)
        self.assertEqual(len(res.alerts), 1)
        self.assertEqual(res.alerts[0]["level"], "error")
        self.assertIn("Invalid CRC width", res.alerts[0]["message"])

        # 2. No bits in metadata
        rect_nobits = Overlay(shape=OverlayShape.RECT, points=[(0.1, -100e3), (0.2, 100e3)])
        rect_nobits.metadata = {}
        ctx_nobits = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3,
            overlays=[rect_nobits], params={"preset": "Custom", "crc_bits": 16}
        )
        res_nobits = crc_mod.run(np.zeros(100, dtype=np.complex64), ctx_nobits)
        self.assertEqual(len(res_nobits.alerts), 1)
        self.assertEqual(res_nobits.alerts[0]["level"], "warning")
        self.assertIn("None of the candidate bursts contain demodulated 'bits'", res_nobits.alerts[0]["message"])

    def test_snap_to_burst_no_burst_detected(self):
        # Pure zeros inside candidate box
        rect = Overlay(shape=OverlayShape.RECT, points=[(0.1, -100e3), (0.2, 100e3)])
        rect.id = "snap_rect_1"
        rect.iq = np.zeros(2048, dtype=np.complex64)
        rect.fs = 250e3

        ctx = PluginContext(
            sample_rate=1e6, center_freq=0.0, t_start=0.0, t_end=1.0, f_start=-500e3, f_end=500e3,
            overlays=[rect], params={"threshold_db": 6.0}
        )
        res = snap_mod.run(np.zeros(1000, dtype=np.complex64), ctx)
        self.assertEqual(len(res.alerts), 1)
        self.assertEqual(res.alerts[0]["level"], "warning")
        self.assertIn("Could not detect burst signals exceeding threshold", res.alerts[0]["message"])


if __name__ == "__main__":
    unittest.main()

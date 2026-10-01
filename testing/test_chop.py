"""testing/test_chop.py

Unit tests for the Chop bit-slice plugin.
"""

from __future__ import annotations

import unittest

import numpy as np

from iqview.overlays import Overlay, OverlayShape
from iqview.plugins import PluginContext, PluginResult
from iqview.plugins.builtin import get_builtin_plugin
import iqview.plugins.builtin.chop as chop_mod


def _context(overlay, params=None, overlays=None):
    return PluginContext(
        sample_rate=1_000_000.0,
        center_freq=433_920_000.0,
        t_start=0.0,
        t_end=0.1,
        f_start=433_820_000.0,
        f_end=434_020_000.0,
        overlays=overlays if overlays is not None else [overlay],
        params=params or {},
    )


def _apply(overlay, res: PluginResult):
    for oid, fields in res.updates:
        if str(oid) == str(overlay.id):
            for key, value in fields.items():
                setattr(overlay, key, value)
    return overlay


class TestChopRegistry(unittest.TestCase):
    def test_discovery(self):
        self.assertIs(get_builtin_plugin("Chop"), chop_mod)
        self.assertIs(get_builtin_plugin("chop"), chop_mod)
        self.assertEqual(chop_mod.PLUGIN_CATEGORY, "Bit Manipulation")
        self.assertFalse(chop_mod.PLUGIN_NEEDS_WIDEBAND_IQ)
        self.assertEqual(chop_mod.PLUGIN_PARAMS["offset"]["default"], 0)
        self.assertIn("length", chop_mod.PLUGIN_PARAMS)


class TestChopSlice(unittest.TestCase):
    def test_removes_the_first_n_bits_when_offset_is_zero(self):
        overlay = Overlay(shape=OverlayShape.RECT, display_str="Burst")
        overlay.metadata = {"bits": "110010101111", "snr_db": 12.5}

        res = chop_mod.run(
            np.empty(0, dtype=np.complex64),
            _context(overlay, {"length": 4, "offset": 0}),
        )
        _apply(overlay, res)

        self.assertEqual(overlay.metadata["bits_pre_chop"], "110010101111")
        self.assertEqual(overlay.metadata["bits"], "10101111")
        self.assertEqual(overlay.metadata["num_bits"], 8)
        self.assertEqual(overlay.metadata["chop_offset"], 0)
        self.assertEqual(overlay.metadata["chop_length"], 4)
        self.assertEqual(overlay.metadata["chop_removed"], 4)
        self.assertEqual(overlay.metadata["hex"], "AF")
        self.assertEqual(overlay.metadata["snr_db"], 12.5)
        self.assertIn("[Chop -4]", overlay.display_str)
        self.assertIn("Chop: skipped 0 bits, removed 4 of 4", overlay.hover_str)
        self.assertIn("Bits: 10101111", overlay.hover_str)

    def test_skips_offset_then_removes_n(self):
        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": "11001010"}

        res = chop_mod.run(
            np.empty(0, dtype=np.complex64),
            _context(overlay, {"length": 4, "offset": 3}),
        )
        _apply(overlay, res)

        self.assertEqual(overlay.metadata["bits"], "1100")
        self.assertEqual(overlay.metadata["chop_offset"], 3)
        self.assertEqual(overlay.metadata["chop_removed"], 4)
        self.assertIn("[Chop @3 -4]", overlay.display_str)

    def test_short_stream_removes_only_what_remains(self):
        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": "11001010"}

        res = chop_mod.run(
            np.empty(0, dtype=np.complex64),
            _context(overlay, {"length": 8, "offset": 6}),
        )
        _apply(overlay, res)

        self.assertEqual(overlay.metadata["bits"], "110010")
        self.assertEqual(overlay.metadata["num_bits"], 6)
        self.assertEqual(overlay.metadata["chop_removed"], 2)
        self.assertIn("removed 2 of 8", overlay.hover_str)
        self.assertTrue(any("fewer than" in msg for msg in res.logs))

    def test_offset_past_the_end_leaves_the_burst_unchanged(self):
        overlay = Overlay(shape=OverlayShape.RECT, display_str="Burst", hover_str="FSK")
        overlay.metadata = {"bits": "1100"}

        res = chop_mod.run(
            np.empty(0, dtype=np.complex64),
            _context(overlay, {"length": 4, "offset": 8}),
        )

        self.assertEqual(res.updates, [])
        self.assertEqual(overlay.metadata["bits"], "1100")
        self.assertEqual(overlay.display_str, "Burst")
        self.assertTrue(res.alerts)

    def test_ignores_overlays_without_bits(self):
        empty = Overlay(shape=OverlayShape.RECT)
        empty.metadata = {}
        res = chop_mod.run(
            np.empty(0, dtype=np.complex64),
            _context(empty, {"length": 4}),
        )
        self.assertEqual(res.updates, [])
        self.assertTrue(res.alerts)


if __name__ == "__main__":
    unittest.main()

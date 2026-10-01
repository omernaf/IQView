"""testing/test_occupied_bandwidth.py

Unit tests for the Occupied Bandwidth built-in plugin.
"""

from __future__ import annotations

import unittest

import numpy as np

from iqview.overlays import FreqRegion, OverlayShape, Rect
from iqview.plugins import PluginContext
from iqview.plugins.builtin import get_builtin_plugin
import iqview.plugins.builtin.occupied_bandwidth as obw_mod


def _context(samples, fs, fc, f_start, f_end, params=None, overlays=None):
    n = 0 if samples is None else len(samples)
    duration = n / fs if fs else 0.0
    return PluginContext(
        sample_rate=fs,
        center_freq=fc,
        t_start=0.0,
        t_end=duration,
        f_start=f_start,
        f_end=f_end,
        overlays=overlays,
        params=params or {},
        scope="view",
        file_duration=duration,
    )


class TestOccupiedBandwidthRegistry(unittest.TestCase):
    def test_discovery_by_name_and_stem(self):
        by_name = get_builtin_plugin("Occupied Bandwidth")
        self.assertIs(by_name, obw_mod)
        by_stem = get_builtin_plugin("occupied_bandwidth")
        self.assertIs(by_stem, obw_mod)

    def test_metadata(self):
        self.assertEqual(obw_mod.PLUGIN_CATEGORY, "Analysis")
        self.assertTrue(obw_mod.PLUGIN_NEEDS_WIDEBAND_IQ)
        self.assertIsNone(obw_mod.PLUGIN_BATCH_SECONDS)
        self.assertIn("obw_percent", obw_mod.PLUGIN_PARAMS)
        self.assertIn("subtract_noise", obw_mod.PLUGIN_PARAMS)
        self.assertIn("Integrated power", obw_mod.PLUGIN_DOC)


class TestWelchCoverage(unittest.TestCase):
    def test_segment_starts_cover_the_buffer(self):
        for n, nperseg in ((32, 32), (100, 32), (96, 32), (100000, 65536), (131072, 65536)):
            step = max(1, nperseg - nperseg // 2)
            starts = list(obw_mod._segment_starts(n, nperseg, step))
            self.assertEqual(starts[0], 0)
            self.assertEqual(starts[-1], n - nperseg)
            self.assertEqual(len(starts), obw_mod._segment_count(n, nperseg, step))
            self.assertEqual(len(starts), len(set(starts)))


class TestOccupiedBandwidthMeasurement(unittest.TestCase):
    def _tone(self, fs, fc, f_rel, amplitude, n, noise=0.0, seed=0):
        t = np.arange(n, dtype=np.float64) / fs
        tone = amplitude * np.exp(1j * 2.0 * np.pi * f_rel * t)
        if noise > 0.0:
            rng = np.random.default_rng(seed)
            tone = tone + noise * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        return tone.astype(np.complex64)

    def test_empty_and_short_samples_add_nothing(self):
        fs = 1.0e6
        fc = 915.0e6
        info = _context(np.zeros(0, dtype=np.complex64), fs, fc, fc - fs / 2, fc + fs / 2)
        result = obw_mod.run(np.zeros(0, dtype=np.complex64), info)
        self.assertEqual(result._adds, [])

        short = np.zeros(8, dtype=np.complex64)
        result = obw_mod.run(short, _context(short, fs, fc, fc - fs / 2, fc + fs / 2))
        self.assertEqual(result._adds, [])

    def test_tone_bandwidth_and_integrated_power(self):
        fs = 1.0e6
        fc = 915.0e6
        f_rel = 25_000.0
        amplitude = 0.5
        n = 131072
        samples = self._tone(fs, fc, f_rel, amplitude, n, noise=0.01, seed=3)
        info = _context(samples, fs, fc, fc - fs / 2, fc + fs / 2)
        result = obw_mod.run(samples, info)

        self.assertEqual(len(result._adds), 1)
        region = result._adds[0]
        self.assertEqual(region.shape, OverlayShape.Y_REGION)
        self.assertTrue(region.locked)

        meta = region.metadata
        self.assertIn("obw_hz", meta)
        self.assertIn("integrated_power", meta)
        self.assertIn("integrated_power_db", meta)
        self.assertAlmostEqual(meta["obw_percent"], 99.0, places=1)
        self.assertTrue(meta["noise_floor_subtracted"])

        tone_hz = fc + f_rel
        self.assertGreater(region.f_end, tone_hz)
        self.assertLess(region.f_start, tone_hz)
        self.assertLess(region.bandwidth, 2.0e3)
        self.assertAlmostEqual(meta["obw_hz"], region.bandwidth, places=1)
        self.assertAlmostEqual(meta["f_low_hz"], region.f_start, places=1)
        self.assertAlmostEqual(meta["f_high_hz"], region.f_end, places=1)

        expected_db = 10.0 * np.log10(amplitude ** 2)
        self.assertAlmostEqual(meta["integrated_power_db"], expected_db, delta=0.8)
        self.assertAlmostEqual(meta["integrated_power"], amplitude ** 2, delta=0.04)

        self.assertIn(f"{meta['obw_hz']:,.1f} Hz", region.hover_str)
        self.assertIn("Integrated power:", region.hover_str)
        self.assertIn("dB", region.hover_str)
        self.assertNotIn("dBFS", region.hover_str)
        self.assertIn("Hz", region.display_str)
        self.assertIn("dB", region.display_str)
        self.assertNotIn("dBFS", region.display_str)

    def test_bandlimited_signal_width(self):
        fs = 1.0e6
        fc = 100.0e6
        n = 131072
        rng = np.random.default_rng(4)
        sig = 0.4 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        spectrum = np.fft.fft(sig)
        freqs = np.fft.fftfreq(n, d=1.0 / fs)
        half_bw = 20_000.0
        center_rel = 80_000.0
        spectrum[np.abs(freqs - center_rel) > half_bw] = 0
        band = np.fft.ifft(spectrum).astype(np.complex64)
        noise = 0.015 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        samples = (band + noise).astype(np.complex64)

        info = _context(samples, fs, fc, fc - fs / 2, fc + fs / 2)
        result = obw_mod.run(samples, info)
        region = result._adds[0]
        meta = region.metadata

        self.assertAlmostEqual(region.f_center, fc + center_rel, delta=2.0e3)
        self.assertAlmostEqual(meta["obw_hz"], 2.0 * half_bw, delta=3.0e3)

        band_power = float(np.mean(np.abs(band) ** 2))
        self.assertAlmostEqual(meta["integrated_power"], band_power, delta=band_power * 0.35)

    def test_frequency_scope_ignores_out_of_view_tone(self):
        fs = 1.0e6
        fc = 915.0e6
        n = 131072
        t = np.arange(n, dtype=np.float64) / fs
        in_band = 0.25 * np.exp(1j * 2.0 * np.pi * 40_000.0 * t)
        out_of_band = 1.0 * np.exp(1j * 2.0 * np.pi * (-300_000.0) * t)
        samples = (in_band + out_of_band).astype(np.complex64)

        # Positive-frequency half only: the loud tone at -300 kHz is outside.
        info = _context(samples, fs, fc, fc, fc + fs / 2)
        result = obw_mod.run(samples, info)
        region = result._adds[0]

        self.assertGreater(region.f_start, fc)
        self.assertLess(region.f_end, fc + 80_000.0)
        self.assertAlmostEqual(region.f_center, fc + 40_000.0, delta=1.0e3)
        expected_db = 10.0 * np.log10(0.25 ** 2)
        self.assertAlmostEqual(region.metadata["integrated_power_db"], expected_db, delta=1.0)

    def test_rerun_removes_only_this_plugins_y_region(self):
        fs = 1.0e6
        fc = 433.0e6
        n = 65536
        samples = self._tone(fs, fc, 10_000.0, 0.4, n, noise=0.005, seed=5)

        previous = FreqRegion(fc - 5.0e3, fc + 5.0e3, display_str="old")
        previous.source = f"plugin:{obw_mod.PLUGIN_NAME}"
        user_band = FreqRegion(fc - 50.0e3, fc + 50.0e3, display_str="user")
        user_band.source = "user"
        other = Rect(0.0, fc - 1.0e3, 0.01, fc + 1.0e3, display_str="burst")
        other.source = "plugin:Burst Energy Detector"

        info = _context(
            samples, fs, fc, fc - fs / 2, fc + fs / 2,
            overlays=[previous, user_band, other],
        )
        result = obw_mod.run(samples, info)
        self.assertEqual(result._removes, [previous.id])
        self.assertEqual(len(result._adds), 1)
        self.assertNotEqual(result._adds[0].display_str, "old")


if __name__ == "__main__":
    unittest.main()

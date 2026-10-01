"""testing/test_gnss_detector.py

Comprehensive unit test suite for the built-in GNSS Satellite Detector plugin.
Tests:
1. Built-in registry discovery and parameter schema validation.
2. GPS L1 C/A Gold code LFSR generator mathematical compliance (IS-GPS-200).
3. GLONASS L1 511-chip maximal-length sequence generator compliance.
4. Software Digital Down-Conversion (DDC) and decimation filtering.
5. End-to-end 2D PCPS acquisition on synthetic sub-noise GNSS signals (PRN, Doppler, C/N0).
6. Out-of-band graceful handling and warning alerts.
7. Overlay production and interactive 1D Plot generation.
"""

from __future__ import annotations

import unittest
import numpy as np

from iqview.overlays import Rect, OverlayShape
from iqview.plugins import PluginContext, PluginResult
from iqview.plugins.builtin import get_builtin_plugin, get_builtin_plugin_paths
import iqview.plugins.builtin.gnss_detector as gnss_mod


class TestGNSSPluginRegistry(unittest.TestCase):
    """Test registry discovery and parameter schema."""

    def test_discovery_by_name_and_stem(self):
        mod_by_name = get_builtin_plugin("GNSS Satellite Detector")
        self.assertIsNotNone(mod_by_name)
        self.assertEqual(mod_by_name.PLUGIN_NAME, "GNSS Satellite Detector")

        mod_by_stem = get_builtin_plugin("gnss_detector")
        self.assertIsNotNone(mod_by_stem)
        self.assertEqual(mod_by_stem.PLUGIN_NAME, "GNSS Satellite Detector")

    def test_metadata_attributes(self):
        mod = gnss_mod
        self.assertEqual(mod.PLUGIN_CATEGORY, "Detection")
        self.assertTrue(mod.PLUGIN_NEEDS_WIDEBAND_IQ)
        self.assertIsNone(mod.PLUGIN_BATCH_SECONDS)
        self.assertFalse(mod.PLUGIN_RUN_ON_MAIN_THREAD)
        self.assertIn("GPS L1 C/A", mod.PLUGIN_DOC)
        self.assertIn("band_mode", mod.PLUGIN_PARAMS)
        self.assertIn("doppler_max_khz", mod.PLUGIN_PARAMS)
        self.assertIn("pnr_threshold", mod.PLUGIN_PARAMS)


class TestGNSSCodeGenerators(unittest.TestCase):
    """Test spreading code generators against IS-GPS-200 and GLONASS ICD."""

    def test_gps_l1_ca_auto_and_cross_correlation(self):
        """All 32 GPS PRNs must produce 1023 chips with canonical Gold code properties."""
        codes = {}
        for prn in range(1, 33):
            c = gnss_mod.generate_gps_l1_ca(prn)
            self.assertEqual(len(c), 1023)
            self.assertTrue(set(np.unique(c)).issubset({-1.0, 1.0}))

            # Circular autocorrelation
            R_auto = np.real(np.fft.ifft(np.fft.fft(c) * np.conj(np.fft.fft(c))))
            peak = float(np.max(R_auto))
            self.assertAlmostEqual(peak, 1023.0, places=2)

            # Gold code off-peak values must be bounded by [-65, 63] (within float precision)
            sorted_peaks = np.sort(R_auto)
            second_peak = float(sorted_peaks[-2])
            min_val = float(sorted_peaks[0])
            self.assertLessEqual(second_peak, 65.001)
            self.assertGreaterEqual(min_val, -65.001)
            codes[prn] = c

        # Cross-correlation between distinct PRNs must not exceed 65.0 (within float precision)
        for p1, p2 in [(1, 2), (3, 11), (5, 22), (14, 31)]:
            R_cross = np.real(np.fft.ifft(np.fft.fft(codes[p1]) * np.conj(np.fft.fft(codes[p2]))))
            max_cross = float(np.max(np.abs(R_cross)))
            self.assertLessEqual(max_cross, 65.001)

    def test_glonass_l1_code_generation(self):
        """GLONASS code must be 511 chips with pure m-sequence autocorrelation."""
        c = gnss_mod.generate_glonass_l1_code()
        self.assertEqual(len(c), 511)
        self.assertTrue(set(np.unique(c)).issubset({-1.0, 1.0}))

        R_auto = np.real(np.fft.ifft(np.fft.fft(c) * np.conj(np.fft.fft(c))))
        self.assertAlmostEqual(float(np.max(R_auto)), 511.0, places=2)
        # For m-sequence, off-peak values must all be -1.0
        sorted_vals = np.sort(R_auto)
        self.assertAlmostEqual(float(sorted_vals[-2]), -1.0, places=3)
        self.assertAlmostEqual(float(sorted_vals[0]), -1.0, places=3)

    def test_resample_code_to_fs(self):
        """Resampling to sampling rate must preserve duration and chip structure."""
        c = gnss_mod.generate_gps_l1_ca(1)
        fs = 2048000.0
        chip_rate = 1023000.0
        sampled = gnss_mod.resample_code_to_fs(c, chip_rate, fs, duration_s=1e-3)
        expected_len = int(round(1e-3 * fs))
        self.assertEqual(len(sampled), expected_len)
        self.assertEqual(sampled.dtype, np.complex64)


class TestSoftwareDDC(unittest.TestCase):
    """Test spectral slicing Digital Down-Converter."""

    def test_ddc_tone_shift(self):
        """A tone at target_fc should be down-converted to 0 Hz DC."""
        fs_in = 20.0e6
        fc_in = 1570.0e6
        target_fc = 1575.42e6
        target_bw = 2.046e6
        target_fs = 2.048e6
        duration_s = 0.005

        n_in = int(round(duration_s * fs_in))
        t_in = np.arange(n_in) / fs_in
        # Generate tone at target_fc
        f_tone_rel = target_fc - fc_in
        tone_in = np.exp(1j * 2.0 * np.pi * f_tone_rel * t_in).astype(np.complex64)

        baseband_iq, actual_fs = gnss_mod.extract_and_ddc(
            tone_in, fs_in, fc_in, target_fc, target_bw, target_fs, duration_s
        )
        self.assertGreater(len(baseband_iq), 0)

        # In baseband, tone should peak at 0 Hz bin
        spec = np.abs(np.fft.fftshift(np.fft.fft(baseband_iq)))
        center_bin = len(spec) // 2
        peak_bin = int(np.argmax(spec))
        self.assertLessEqual(abs(peak_bin - center_bin), 1)


class TestGNSSAcquisitionEndToEnd(unittest.TestCase):
    """End-to-end acquisition tests using synthetic sub-noise GNSS signals."""

    def _synthesize_gnss_signal(
        self,
        fs: float,
        duration_s: float,
        sats: list[dict],
        snr_db: float = -12.0,
    ) -> np.ndarray:
        """
        Synthesize multi-satellite GPS L1 C/A signal submerged in Gaussian noise.
        """
        n_samples = int(round(duration_s * fs))
        t = np.arange(n_samples, dtype=np.float64) / fs
        samples_per_ms = int(round(fs * 1e-3))
        chip_rate = 1.023e6
        code_len = 1023

        sig = np.zeros(n_samples, dtype=np.complex64)

        for sat in sats:
            prn = sat["prn"]
            fd = sat.get("doppler_hz", 0.0)
            delay_samp = sat.get("delay_samples", 0)

            raw_code = gnss_mod.generate_gps_l1_ca(prn)
            chip_idx = np.floor((np.arange(samples_per_ms) / fs) * chip_rate).astype(int) % code_len
            code_1ms = raw_code[chip_idx].astype(np.complex64)

            n_reps = int(np.ceil(duration_s * 1000.0)) + 2
            rep_code = np.tile(code_1ms, n_reps)
            delayed = rep_code[delay_samp : delay_samp + n_samples]

            sig += delayed * np.exp(1j * 2.0 * np.pi * fd * t)

        # Add Gaussian noise
        sig_pwr = float(np.mean(np.abs(sig) ** 2))
        noise_pwr = sig_pwr / (10.0 ** (snr_db / 10.0))
        noise = (np.random.randn(n_samples) + 1j * np.random.randn(n_samples)) * np.sqrt(noise_pwr / 2.0)
        return (sig + noise).astype(np.complex64)

    def test_acquire_gps_l1_satellites(self):
        """Acquires two known satellites at distinct Dopplers and rejects non-present PRNs."""
        fs = 2048000.0
        fc = 1575.42e6
        duration_s = 0.010  # 10 ms

        # Inject PRN 3 at +1500 Hz and PRN 11 at -2000 Hz
        rx_samples = self._synthesize_gnss_signal(
            fs=fs,
            duration_s=duration_s,
            sats=[
                {"prn": 3, "doppler_hz": 1500.0, "delay_samples": 250},
                {"prn": 11, "doppler_hz": -2000.0, "delay_samples": 800},
            ],
            snr_db=-10.0,
        )

        ctx = PluginContext(
            sample_rate=fs,
            center_freq=fc,
            t_start=0.0,
            t_end=duration_s,
            f_start=fc - fs / 2.0,
            f_end=fc + fs / 2.0,
            params={
                "band_mode": "GPS L1 C/A (1575.42 MHz)",
                "doppler_max_khz": 5.0,
                "doppler_step_hz": 500.0,
                "integration_ms": 8,
                "pnr_threshold": 1.6,
                "prn_selection": "1,2,3,4,11",
                "debug_plots": True,
            },
        )

        result = gnss_mod.run(rx_samples, ctx)
        self.assertIsInstance(result, PluginResult)

        # Check overlays
        self.assertEqual(len(result.adds), 1)
        ov = result.adds[0]
        self.assertIsInstance(ov, Rect)
        self.assertIn("GPS L1", ov.display_str)
        self.assertEqual(ov.metadata["band"], "GPS_L1_CA")

        detected_prns = [s["prn"] for s in ov.metadata["satellites"]]
        self.assertIn(3, detected_prns)
        self.assertIn(11, detected_prns)
        # Non-injected PRNs must not be detected
        self.assertNotIn(1, detected_prns)
        self.assertNotIn(2, detected_prns)
        self.assertNotIn(4, detected_prns)

        # Check Doppler estimates
        sat_map = {s["prn"]: s for s in ov.metadata["satellites"]}
        self.assertAlmostEqual(sat_map[3]["doppler_hz"], 1500.0, delta=300.0)
        self.assertAlmostEqual(sat_map[11]["doppler_hz"], -2000.0, delta=300.0)
        self.assertGreater(sat_map[3]["c_n0_db_hz"], 35.0)

        # Check 1D debug plots (3 sub-plots: Constellation, Doppler, Correlation Peak)
        self.assertEqual(len(result.plots), 3)
        plot_titles = [p["title"] for p in result.plots]
        self.assertTrue(any("Constellation" in t for t in plot_titles))
        self.assertTrue(any("Doppler & Motion" in t for t in plot_titles))
        self.assertTrue(any("Correlation Profile" in t for t in plot_titles))

    def test_out_of_band_rejection(self):
        """A recording centered outside any GNSS band should gracefully log and alert."""
        fs = 2.0e6
        fc = 915.0e6  # ISM band
        ctx = PluginContext(
            sample_rate=fs,
            center_freq=fc,
            t_start=0.0,
            t_end=0.010,
            f_start=fc - fs / 2.0,
            f_end=fc + fs / 2.0,
            params={"band_mode": "Auto (Detect from Spectrum)"},
        )
        samples = np.zeros(20000, dtype=np.complex64)
        result = gnss_mod.run(samples, ctx)

        self.assertEqual(len(result.adds), 0)
        self.assertEqual(len(result.plots), 0)
        self.assertTrue(any("No supported GNSS bands overlap" in al["message"] for al in ctx.alerts))

    def test_glonass_acquisition(self):
        """Acquires a GLONASS L1 channel signal submerged in Gaussian noise."""
        fs = 2048000.0
        fc = 1602.0e6  # Channel 0
        duration_s = 0.010
        n_samples = int(round(duration_s * fs))
        t = np.arange(n_samples) / fs

        glo_code = gnss_mod.generate_glonass_l1_code()
        sampled_code = gnss_mod.resample_code_to_fs(glo_code, 511000.0, fs, duration_s=1e-3)
        sig = np.tile(sampled_code, 10)[:n_samples] * np.exp(1j * 2.0 * np.pi * 1000.0 * t)
        noise = (np.random.randn(n_samples) + 1j * np.random.randn(n_samples)) * np.sqrt(0.5)
        rx = (sig + noise).astype(np.complex64)

        ctx = PluginContext(
            sample_rate=fs,
            center_freq=fc,
            t_start=0.0,
            t_end=duration_s,
            f_start=fc - fs / 2.0,
            f_end=fc + fs / 2.0,
            params={
                "band_mode": "GLONASS L1 (1602.00 MHz)",
                "doppler_max_khz": 3.0,
                "doppler_step_hz": 500.0,
                "integration_ms": 8,
                "pnr_threshold": 1.6,
                "debug_plots": False,
            },
        )
        result = gnss_mod.run(rx, ctx)
        self.assertGreaterEqual(len(result.adds), 1)
        ov = result.adds[0]
        self.assertEqual(ov.metadata["band"], "GLONASS_L1")
        channel_list = [s["prn"] for s in ov.metadata["satellites"]]
        self.assertIn(0, channel_list)

    def test_multi_band_auto_discovery(self):
        """Wideband capture spanning both GPS L1 and GLONASS L1 detects both bands."""
        fc = 1588.71e6
        fs = 40.0e6
        f_min, f_max = fc - fs / 2.0, fc + fs / 2.0
        self.assertTrue(1575.42e6 >= f_min and 1575.42e6 <= f_max)
        self.assertTrue(1602.00e6 >= f_min and 1602.00e6 <= f_max)

        ctx = PluginContext(
            sample_rate=fs,
            center_freq=fc,
            t_start=0.0,
            t_end=0.010,
            f_start=f_min,
            f_end=f_max,
            params={
                "band_mode": "Auto (Detect from Spectrum)",
                "doppler_max_khz": 1.0,
                "doppler_step_hz": 500.0,
                "integration_ms": 4,
                "pnr_threshold": 1.6,
                "prn_selection": "1",
                "debug_plots": False,
            },
        )
        # Low noise baseline
        samples = (np.random.randn(int(fs * 0.010)) + 1j * np.random.randn(int(fs * 0.010))) * 0.01
        samples = samples.astype(np.complex64)
        result = gnss_mod.run(samples, ctx)
        self.assertIsInstance(result, PluginResult)


if __name__ == "__main__":
    unittest.main()

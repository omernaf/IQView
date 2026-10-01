"""testing/test_lora_demodulator.py

Comprehensive unit test suite for the built-in LoRa Demodulator plugin.
Tests:
1. Built-in registry discovery and metadata validation.
2. Core DSP physical-layer demodulation across SFs (5..12), Sub-GHz and 2.4 GHz BWs.
3. Preamble sync, SFD detection, NetID extraction, and payload demodulation.
4. Upchirp (standard) and Downchirp (inverted) polarity detection.
5. End-to-end plugin run() execution on Rect overlays with metadata and debug plot generation.
"""

from __future__ import annotations

import unittest
import numpy as np
from scipy import signal as sp_signal

from iqview.overlays import Overlay, OverlayShape
from iqview.plugins import PluginContext, PluginResult
from iqview.plugins.builtin import get_builtin_plugin, get_builtin_plugin_paths
import iqview.plugins.builtin.lora_demodulator as lora_mod


def _generate_lora_burst(
    sf: int = 7,
    bw: float = 125000.0,
    direction: str = "up",
    netid: tuple[int, int] = (18, 34),
    payload_symbols: list[int] | None = None,
    preamble_len: int = 8,
    cfo_hz: float = 0.0,
    snr_db: float | None = 35.0,
) -> tuple[np.ndarray, float]:
    """
    Synthesize an ideal LoRa physical-layer transmission with preamble, NetID,
    SFD (2.25 symbols), and payload chirps at sample_rate = bw.
    """
    if payload_symbols is None:
        payload_symbols = [10, 25, 42, 63, 100, 120]

    N = 2 ** sf
    n = np.arange(N, dtype=np.float64)

    # Base chirps
    c_up = np.exp(1j * 2.0 * np.pi * (-0.5 * n + 0.5 * (n ** 2) / float(N)), dtype=np.complex64)
    c_down = np.conj(c_up)

    pre_chirp = c_up if direction == "up" else c_down
    sfd_chirp = c_down if direction == "up" else c_up

    chunks = []

    # 1. Preamble unmodulated chirps
    for _ in range(preamble_len):
        chunks.append(pre_chirp)

    # 2. NetID symbols (2 symbols modulated onto preamble polarity)
    for sym_val in netid:
        shift = int(sym_val) % N
        chunks.append(np.roll(pre_chirp, -shift))

    # 3. SFD (2.25 symbols of opposite polarity)
    chunks.append(sfd_chirp)
    chunks.append(sfd_chirp)
    chunks.append(sfd_chirp[: N // 4])

    # 4. Modulated payload symbols
    for sym_val in payload_symbols:
        shift = int(sym_val) % N
        chunks.append(np.roll(pre_chirp, -shift))

    sig = np.concatenate(chunks)

    # Guard silence
    guard = np.zeros(N, dtype=np.complex64)
    sig = np.concatenate([guard, sig, guard])

    # Carrier Frequency Offset (CFO)
    if abs(cfo_hz) > 1e-3:
        t = np.arange(len(sig), dtype=np.float64) / bw
        sig = sig * np.exp(1j * 2.0 * np.pi * cfo_hz * t, dtype=np.complex64)

    # Add AWGN if requested
    if snr_db is not None:
        pwr = np.mean(np.abs(sig) ** 2)
        noise_pwr = pwr / (10.0 ** (snr_db / 10.0))
        noise = (np.random.randn(len(sig)) + 1j * np.random.randn(len(sig))) * np.sqrt(noise_pwr / 2.0)
        sig = (sig + noise).astype(np.complex64)

    return sig, bw


class TestLoRaPluginRegistry(unittest.TestCase):
    """Test registry discovery and metadata structure of the LoRa Demodulator plugin."""

    def test_discovery_by_name_and_stem(self):
        mod_by_name = get_builtin_plugin("LoRa Demodulator")
        self.assertIsNotNone(mod_by_name)
        self.assertEqual(mod_by_name.PLUGIN_NAME, "LoRa Demodulator")

        mod_by_stem = get_builtin_plugin("lora_demodulator")
        self.assertIs(mod_by_name, mod_by_stem)

    def test_paths_contains_lora(self):
        paths = get_builtin_plugin_paths()
        lora_paths = [p for p in paths if "lora_demodulator.py" in p.lower()]
        self.assertTrue(len(lora_paths) >= 1)

    def test_plugin_metadata(self):
        self.assertEqual(lora_mod.PLUGIN_NAME, "LoRa Demodulator")
        self.assertEqual(lora_mod.PLUGIN_CATEGORY, "Demodulation")
        self.assertFalse(lora_mod.PLUGIN_NEEDS_WIDEBAND_IQ)
        self.assertIn("LoRa Demodulator", lora_mod.PLUGIN_DOC)

        # Check required parameter declarations
        params = lora_mod.PLUGIN_PARAMS
        self.assertIn("sf", params)
        self.assertIn("bw", params)
        self.assertIn("trim_edges", params)
        self.assertIn("max_hover_symbols", params)
        self.assertIn("debug_plots", params)


class TestLoRaCoreDemodulation(unittest.TestCase):
    """Test core DSP estimation and demodulation functions."""

    def test_standard_upchirp_sf7_125k(self):
        expected_netid = (18, 34)
        expected_syms = [15, 28, 45, 92, 110, 3]
        sig, fs = _generate_lora_burst(
            sf=7,
            bw=125000.0,
            direction="up",
            netid=expected_netid,
            payload_symbols=expected_syms,
            cfo_hz=250.0,
        )

        res = lora_mod._demodulate_lora_iq(
            iq=sig,
            fs=fs,
            overlay_bw=125000.0,
            sf_param=0,  # Auto
            bw_param=0.0,  # Auto
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["sf"], 7)
        self.assertEqual(res["bw"], 125000.0)
        self.assertEqual(res["direction"], "up")
        self.assertEqual(res["netid"], list(expected_netid))
        self.assertEqual(res["symbols"], expected_syms)
        self.assertAlmostEqual(res["cfo_hz"], 250.0, delta=100.0)

    def test_inverted_downchirp_sf8_250k(self):
        expected_netid = (55, 77)
        expected_syms = [20, 80, 140, 200, 250]
        sig, fs = _generate_lora_burst(
            sf=8,
            bw=250000.0,
            direction="down",
            netid=expected_netid,
            payload_symbols=expected_syms,
            cfo_hz=-400.0,
        )

        res = lora_mod._demodulate_lora_iq(
            iq=sig,
            fs=fs,
            overlay_bw=250000.0,
            sf_param=0,
            bw_param=0.0,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["sf"], 8)
        self.assertEqual(res["bw"], 250000.0)
        self.assertEqual(res["direction"], "down")
        self.assertEqual(res["netid"], list(expected_netid))
        self.assertEqual(res["symbols"], expected_syms)

    def test_2_4ghz_band_sf6_812k(self):
        expected_netid = (8, 16)
        expected_syms = [1, 10, 25, 40, 55]
        sig, fs = _generate_lora_burst(
            sf=6,
            bw=812500.0,
            direction="up",
            netid=expected_netid,
            payload_symbols=expected_syms,
        )

        # Give an approximate overlay bandwidth (e.g. 815 kHz) to verify snap to 812.5 kHz
        res = lora_mod._demodulate_lora_iq(
            iq=sig,
            fs=fs,
            overlay_bw=815000.0,
            sf_param=6,
            bw_param=0.0,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["sf"], 6)
        self.assertEqual(res["bw"], 812500.0)
        self.assertEqual(res["netid"], list(expected_netid))
        self.assertEqual(res["symbols"], expected_syms)

    def test_all_sf_and_directions_sweep(self):
        """Verify 100% accurate demodulation across all SFs (5..12) and both chirp directions."""
        for test_sf in range(5, 13):
            for direction in ["up", "down"]:
                expected_netid = (2, 5)
                expected_syms = [1, 10, min(20, (2 ** test_sf) - 1)]
                sig, fs = _generate_lora_burst(
                    sf=test_sf,
                    bw=125000.0,
                    direction=direction,
                    netid=expected_netid,
                    payload_symbols=expected_syms,
                    cfo_hz=75.0,
                )

                res = lora_mod._demodulate_lora_iq(
                    iq=sig,
                    fs=fs,
                    overlay_bw=125000.0,
                    sf_param=test_sf,
                    bw_param=125000.0,
                )
                self.assertIsNotNone(res, f"Demodulation failed for SF{test_sf} {direction}")
                self.assertEqual(res["sf"], test_sf)
                self.assertEqual(res["direction"], direction)
                self.assertEqual(res["netid"], list(expected_netid))
                self.assertEqual(res["symbols"], expected_syms)


class TestLoRaPluginRunInterface(unittest.TestCase):
    """Test the full plugin run() method with PluginContext and Overlay updates."""

    def test_run_demodulates_overlay(self):
        expected_netid = (18, 34)
        expected_syms = [10, 20, 30, 40, 50, 60]
        sig, fs = _generate_lora_burst(
            sf=7,
            bw=125000.0,
            direction="up",
            netid=expected_netid,
            payload_symbols=expected_syms,
        )

        duration = len(sig) / fs
        # Create Rect overlay spanning the burst in time and frequency
        ov = Overlay(
            shape=OverlayShape.RECT,
            points=[(0.0, -62500.0), (duration, 62500.0)],
        )
        ov.iq = sig
        ov.fs = fs

        ctx = PluginContext(
            sample_rate=fs,
            center_freq=868.1e6,
            t_start=0.0,
            t_end=duration,
            f_start=-62500.0,
            f_end=62500.0,
            overlays=[ov],
            params={"sf": 0, "bw": 0.0, "debug_plots": True},
        )

        res = lora_mod.run(None, ctx)
        self.assertIsInstance(res, PluginResult)
        updates_dict = dict(res.updates)
        self.assertIn(str(ov.id), updates_dict)

        patch = updates_dict[str(ov.id)]
        meta = patch.get("metadata", {})
        self.assertEqual(meta.get("protocol"), "LoRa")
        self.assertEqual(meta.get("sf"), 7)
        self.assertEqual(meta.get("bw_hz"), 125000.0)
        self.assertEqual(meta.get("chirp_direction"), "up")
        self.assertEqual(meta.get("netid"), [18, 34])
        self.assertEqual(meta.get("symbols"), expected_syms)
        self.assertEqual(meta.get("num_symbols"), len(expected_syms))

        # Check display and hover strings
        display_str = patch.get("display_str", "")
        self.assertIn("LoRa SF7", display_str)
        self.assertIn("NetID: [18,34]", display_str)

        hover_str = patch.get("hover_str", "")
        self.assertIn("LoRa Physical Layer (Upchirp (Standard))", hover_str)
        self.assertIn("NetID: [18, 34] (0x12 0x22)", hover_str)

        # Check debug plot tab created
        self.assertTrue(len(res.plots) >= 1)
        self.assertIn("LoRa", res.plot_tab_title)

    def test_run_no_rect_overlays(self):
        ctx = PluginContext(
            sample_rate=1e6,
            center_freq=0.0,
            t_start=0.0,
            t_end=1.0,
            f_start=-5e5,
            f_end=5e5,
            overlays=[],
        )
        res = lora_mod.run(None, ctx)
        self.assertEqual(len(res.updates), 0)
        self.assertTrue(any("No Rect overlays" in msg for msg in res.logs))

    def test_run_cancellation(self):
        sig, fs = _generate_lora_burst(sf=7, bw=125000.0)
        ov = Overlay(shape=OverlayShape.RECT, points=[(0.0, -62500.0), (len(sig) / fs, 62500.0)])
        ov.iq = sig
        ov.fs = fs

        # Cancel immediately
        ctx = PluginContext(
            sample_rate=fs,
            center_freq=0.0,
            t_start=0.0,
            t_end=1.0,
            f_start=-62500.0,
            f_end=62500.0,
            overlays=[ov],
            cancel_cb=lambda: True,
        )
        res = lora_mod.run(None, ctx)
        self.assertEqual(len(res.updates), 0)

    def test_run_hover_truncation(self):
        many_syms = list(range(50))
        sig, fs = _generate_lora_burst(sf=7, bw=125000.0, payload_symbols=many_syms)
        ov = Overlay(shape=OverlayShape.RECT, points=[(0.0, -62500.0), (len(sig) / fs, 62500.0)])
        ov.iq = sig
        ov.fs = fs

        ctx = PluginContext(
            sample_rate=fs,
            center_freq=0.0,
            t_start=0.0,
            t_end=1.0,
            f_start=-62500.0,
            f_end=62500.0,
            overlays=[ov],
            params={"max_hover_symbols": 10},
        )
        res = lora_mod.run(None, ctx)
        updates_dict = dict(res.updates)
        hover_str = updates_dict[str(ov.id)].get("hover_str", "")
        self.assertIn("more)", hover_str)


if __name__ == "__main__":
    unittest.main()

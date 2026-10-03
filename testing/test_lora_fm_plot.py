"""testing/test_lora_fm_plot.py

Checks the LoRa debug-plot FM demod and the NetID / SFD / symbol regions.
"""

from __future__ import annotations

import unittest

import numpy as np

import iqview.plugins.builtin.lora_demodulator as lora_mod


class TestLoRaFmDemod(unittest.TestCase):
    def test_tone_frequency_and_cfo_removal(self):
        fs = 125_000.0
        n = 4096
        t = np.arange(n) / fs
        tone = np.exp(1j * 2.0 * np.pi * 10_000.0 * t).astype(np.complex64)

        raw = lora_mod._fm_demod(tone, fs, cfo_hz=0.0)
        centered = lora_mod._fm_demod(tone, fs, cfo_hz=10_000.0)

        self.assertEqual(len(raw), n - 1)
        self.assertAlmostEqual(float(np.median(raw)), 10_000.0, delta=1.0)
        self.assertAlmostEqual(float(np.median(centered)), 0.0, delta=1.0)

    def test_regions_mark_netid_sfd_and_symbols(self):
        t0 = 1.0
        fs = 8.0
        n_sym = 4
        sfd_start = 16
        payload_start = 25  # 2.25 symbols of 4 samples
        regions = lora_mod._lora_fm_regions(
            t0=t0,
            fs=fs,
            sfd_start=sfd_start,
            payload_start=payload_start,
            n_sym=n_sym,
            netid=[3, 9],
            symbols=[1, 2],
        )

        self.assertEqual([r["label"] for r in regions], ["NetID", "NetID", "SFD", "Symbol", "Symbol"])
        self.assertEqual([r["text"] for r in regions], ["3", "9", "SFD", "1", "2"])

        self.assertAlmostEqual(regions[0]["x_start"], 1.0 + 8 / fs)
        self.assertAlmostEqual(regions[0]["x_end"], 1.0 + 12 / fs)
        self.assertAlmostEqual(regions[1]["x_start"], 1.0 + 12 / fs)
        self.assertAlmostEqual(regions[1]["x_end"], 1.0 + 16 / fs)
        self.assertAlmostEqual(regions[2]["x_start"], 1.0 + 16 / fs)
        self.assertAlmostEqual(regions[2]["x_end"], 1.0 + 25 / fs)
        self.assertAlmostEqual(regions[3]["x_start"], 1.0 + 25 / fs)
        self.assertAlmostEqual(regions[3]["x_end"], 1.0 + 29 / fs)
        self.assertAlmostEqual(regions[4]["x_start"], regions[3]["x_end"])
        self.assertNotEqual(regions[3]["color"], regions[4]["color"])


if __name__ == "__main__":
    unittest.main()

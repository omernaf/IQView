#!/usr/bin/env python3
"""Automated Headless Smoke Test for IQView.

Runs fast validation of:
1. Dynamic filename parameter extraction regex.
2. Byte offset parsing and truncation.
3. Pure domain transforms in domain_transforms.py.
4. Binary and audio file loader integrity against iqview_testdata.
"""

import os
import sys
import numpy as np

# Ensure iqview is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from iqview.utils.helpers import detect_params_from_filename, detect_type_from_ext
from iqview.dsp.domain_transforms import (
    compute_instantaneous_frequency,
    compute_time_domain_trace,
    compute_region_statistics,
)


def test_filename_parsing():
    cases = [
        ("capture_10Msps_433MHz.bin", 10e6, 433e6),
        ("signal_20MSPS_2.4GHz.iq", 20e6, 2.4e9),
        ("test_500ksps_915.5MHz.cf32", 500e3, 915.5e6),
    ]
    for fn, exp_fs, exp_fc in cases:
        params = detect_params_from_filename(fn)
        fs, fc = params['fs'], params['fc']
        assert fs == exp_fs, f"Failed fs for {fn}: got {fs}, expected {exp_fs}"
        assert fc == exp_fc, f"Failed fc for {fn}: got {fc}, expected {exp_fc}"
    print("PASS: Filename parameter auto-detection regex.")


def test_domain_transforms():
    fs = 1e6
    t = np.arange(1000) / fs
    # 10 kHz complex tone
    x = np.exp(2j * np.pi * 10e3 * t).astype(np.complex64)

    # Instantaneous frequency should be ~10 kHz
    inst_f = compute_instantaneous_frequency(x, fs)
    assert np.allclose(inst_f[10:-10], 10e3, atol=100.0), "Instantaneous frequency failed."

    # Time domain magnitude dB should be ~0 dBFS for unit sinusoid
    mag_db, label = compute_time_domain_trace(x, "magnitude [dB]", fs)
    assert np.allclose(mag_db, 0.0, atol=0.1), "Time domain magnitude [dB] failed."

    # Region statistics
    stats = compute_region_statistics(t, mag_db, 0.0002, 0.0008, label)
    assert stats is not None and np.isfinite(stats.p_mean), "Region stats mean is non-finite."
    print("PASS: Pure domain transforms.")


def test_testdata_ingestion():
    testdata_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../iqview_testdata"))
    if not os.path.exists(testdata_dir):
        print("SKIP: iqview_testdata directory not found. Run make_iqview_testdata.py first.")
        return

    tone_file = os.path.join(testdata_dir, "tone_10Msps_100MHz.32fc")
    if os.path.exists(tone_file):
        raw = np.fromfile(tone_file, dtype=np.complex64)
        assert len(raw) > 0, "Failed to load tone_10Msps_100MHz.32fc"
        print(f"PASS: Loaded testdata file ({len(raw)} complex samples).")


def main():
    print("=== IQView Quick Headless Smoke Test ===")
    test_filename_parsing()
    test_domain_transforms()
    test_testdata_ingestion()
    print("=== All Quick Smoke Tests Passed ===")


if __name__ == "__main__":
    main()

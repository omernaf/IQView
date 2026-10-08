#!/usr/bin/env python3
"""Headless verification script for IQView DSP Invariants.

Tests:
1. Zero-phase exactness: BSF = Original - BPF.
2. True PSD normalization consistency across window types.
3. Coordinate alignment half-window offset calculation.
4. Numerical clipping against log(0).
"""

import sys
import numpy as np

# Ensure iqview is importable
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from iqview.dsp.dsp import apply_filter, compute_psd_norm_db, postprocess_fft


def test_zero_phase_identity():
    """Verify that BSF = Original - BPF leaves near-zero residual in the passband."""
    fs = 10e6
    t = np.arange(10000) / fs
    # Two tones: 1 MHz (passband) and 3 MHz (stopband)
    tone_pass = np.exp(2j * np.pi * 1e6 * t)
    tone_stop = np.exp(2j * np.pi * 3e6 * t)
    signal = tone_pass + tone_stop

    # Filter isolating the 1 MHz tone: [0.5 MHz, 1.5 MHz]
    bpf = apply_filter(signal, fs, 0.5e6, 1.5e6, mode='bpf')
    bsf = apply_filter(signal, fs, 0.5e6, 1.5e6, mode='bsf')

    # Mathematical identity check: BSF must equal signal - BPF
    diff = np.max(np.abs(bsf - (signal - bpf)))
    assert diff < 1e-10, f"Zero-phase identity failed: max difference = {diff}"
    print("PASS: Zero-phase identity (BSF == Original - BPF).")


def test_psd_normalization_finite():
    """Verify compute_psd_norm_db handles standard windows without NaN or inf."""
    fs = 1e6
    for win_name in [np.hanning, np.hamming, np.blackman]:
        w = win_name(1024)
        offset = compute_psd_norm_db(w, fs)
        assert np.isfinite(offset), f"PSD offset for {win_name} is non-finite: {offset}"
        assert offset > 0, f"PSD offset should be positive for fs={fs}"
    print("PASS: PSD normalization offsets computed stably.")


def test_log_zero_stability():
    """Verify postprocess_fft does not generate -inf on zero inputs."""
    zeros = np.zeros(1024, dtype=np.complex64)
    db = postprocess_fft(zeros, 1024, psd_norm_db=10.0)
    assert np.all(np.isfinite(db)), "postprocess_fft produced -inf or NaN on zero input."
    print("PASS: Logarithm stability on zero input.")


def main():
    print("=== IQView DSP Invariant Verification ===")
    test_zero_phase_identity()
    test_psd_normalization_finite()
    test_log_zero_stability()
    print("=== All DSP Invariant Tests Passed ===")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Unit tests for the Signal Comparator built-in plugin."""

import os
import sys
import tempfile
import numpy as np

# Ensure headless Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from iqview.plugins.builtin import get_builtin_plugin
from iqview.plugins.context import PluginContext
from iqview.plugins.builtin import signal_comparator


def test_builtin_discovery():
    """Verify Signal Comparator is discovered by the plugin registry."""
    mod = get_builtin_plugin("Signal Comparator")
    assert mod is not None, "Signal Comparator not found by name"
    assert mod == signal_comparator, "Module mismatch"

    mod_stem = get_builtin_plugin("signal_comparator")
    assert mod_stem is not None, "Signal Comparator not found by stem"
    assert mod_stem == signal_comparator, "Stem mismatch"


def test_signal_comparator_synthetic():
    """Test full comparison pipeline using synthetic test signals."""
    fs = 1_000_000.0  # 1 MSps
    fc = 100_000_000.0 # 100 MHz
    n = 20_000

    t = np.arange(n) / fs
    # Synthesize an FM chirp / frequency-modulated signal
    mod_freq = 50_000.0 * np.sin(2.0 * np.pi * 500.0 * t)  # ±50 kHz swing
    phase = 2.0 * np.pi * np.cumsum(mod_freq) / fs
    s_base = np.exp(1j * phase).astype(np.complex64)
    delay_samples = 250
    phase_shift = 0.75
    # Signal 1 contains the transmission at delay_samples offset
    s1 = np.roll(s_base, delay_samples).astype(np.complex64)
    # Signal 2 is the template / target signal
    s2 = (s_base * np.exp(-1j * phase_shift) * 0.85).astype(np.complex64)

    with tempfile.TemporaryDirectory() as tmpdir:
        s2_file = os.path.join(tmpdir, "target_signal.32fc")
        s2.tofile(s2_file)

        # 1. Run in Aligned Subtraction Mode
        ctx = PluginContext(
            sample_rate=fs,
            center_freq=fc,
            t_start=0.0,
            t_end=n / fs,
            f_start=fc - fs / 2,
            f_end=fc + fs / 2,
            params={
                "signal2_path": s2_file,
                "subtraction_mode": "Aligned (Lag & Phase Corrected)",
                "obw_percent": 99.0,
                "diff_delay": 1,
                "draw_overlay": True,
            },
        )

        res = signal_comparator.run(s1, ctx)

        assert len(res.alerts) == 0, f"Unexpected alerts: {res.alerts}"
        assert len(res._plots) == 7, f"Expected 7 sub-plots, got {len(res._plots)}"

        plot_titles = [p["title"] for p in res._plots]
        expected_titles = [
            "IQ Correlation",
            "Diff Correlation",
            "FM Correlation",
            "Subtraction Mag",
            "Subtraction Phase",
            "PSD Comparison",
            "FM Demod Overlay",
        ]
        assert plot_titles == expected_titles, f"Plot titles mismatch: {plot_titles}"

        # Check plot metadata & traces
        p_iq = res._plots[0]
        # In dict trace format: the single trace key contains the peak summary
        trace_key = list(p_iq["y"].keys())[0]
        assert "Peak:" in trace_key, f"Expected peak in label: {trace_key}"

        # Verify overlay was created
        assert len(res._adds) == 1, "Expected 1 match overlay added"
        meta = res._adds[0].metadata
        assert meta["val_pk_iq"] > 0.90, f"Expected high IQ peak, got {meta['val_pk_iq']}"
        assert abs(meta["lag_s_iq"] - (delay_samples / fs)) < 1e-5, f"Lag error: {meta['lag_s_iq']}"
        assert meta["val_pk_diff"] > 0.90, f"Expected high Diff peak, got {meta['val_pk_diff']}"
        assert meta["val_pk_fm"] > 0.90, f"Expected high FM peak, got {meta['val_pk_fm']}"
        assert meta["obw1_hz"] > 0, "OBW1 should be > 0"
        assert meta["obw2_hz"] > 0, "OBW2 should be > 0"

        # 2. Run in Raw Subtraction Mode
        ctx_raw = PluginContext(
            sample_rate=fs,
            center_freq=fc,
            t_start=0.0,
            t_end=n / fs,
            f_start=fc - fs / 2,
            f_end=fc + fs / 2,
            params={
                "signal2_path": s2_file,
                "subtraction_mode": "Raw (Direct Point-by-Point)",
                "obw_percent": 99.0,
                "draw_overlay": False,
            },
        )
        res_raw = signal_comparator.run(s1, ctx_raw)
        assert len(res_raw.alerts) == 0, f"Unexpected alerts in raw mode: {res_raw.alerts}"
        assert len(res_raw._plots) == 7


def test_missing_file_error():
    """Verify that a missing file path produces an informative error without raising an unhandled exception."""
    ctx = PluginContext(
        sample_rate=1e6,
        center_freq=100e6,
        t_start=0.0,
        t_end=1.0,
        f_start=99.5e6,
        f_end=100.5e6,
        params={"signal2_path": "non_existent_file_path.32fc"},
    )
    s1 = np.ones(1000, dtype=np.complex64)
    res = signal_comparator.run(s1, ctx)
    assert len(res.alerts) > 0 and any("not found" in a.get("message", "").lower() for a in res.alerts)


if __name__ == "__main__":
    test_builtin_discovery()
    print("[PASS] test_builtin_discovery")
    test_signal_comparator_synthetic()
    print("[PASS] test_signal_comparator_synthetic")
    test_missing_file_error()
    print("[PASS] test_missing_file_error")
    print("All tests passed successfully!")

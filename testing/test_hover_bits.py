"""testing/test_hover_bits.py

Unit tests verifying that plugins editing the 'bits' field of a burst
update the overlay's hover tooltip text (hover_str) accordingly.
"""

import unittest
from unittest.mock import MagicMock
import numpy as np

from iqview.ui.overlay import Overlay, OverlayShape, format_hover_bits
from iqview.plugins.context import PluginContext
from iqview.plugins.plugin_result import PluginResult
from iqview.plugins.chain import PluginChain
from iqview.plugins.plugin_manager import PluginManagerMixin

import iqview.plugins.builtin.uw_sync as uw_mod
import iqview.plugins.builtin.block_fec_decoder as fec_mod
import iqview.plugins.builtin.crc_checker as crc_mod
import iqview.plugins.builtin.diff_decoder as diff_mod
import iqview.plugins.builtin.xor_mask as xor_mod
import iqview.plugins.builtin.bit_reversal as rev_mod


def _make_context(overlay: Overlay, params: dict | None = None) -> PluginContext:
    return PluginContext(
        sample_rate=1e6,
        center_freq=0.0,
        t_start=0.0,
        t_end=1.0,
        f_start=-500e3,
        f_end=500e3,
        overlays=[overlay],
        params=params or {},
    )


def _apply_result(overlay: Overlay, res: PluginResult) -> Overlay:
    for oid, fields in res.updates:
        if str(oid) == str(overlay.id):
            for k, v in fields.items():
                setattr(overlay, k, v)
    return overlay


class TestFormatHoverBits(unittest.TestCase):
    def test_format_fresh_hover(self):
        base = "FSK: 100.0 kBd | ±25.0 kHz"
        bits = "11001010"
        hover = format_hover_bits(base, bits)
        self.assertIn("FSK: 100.0 kBd | ±25.0 kHz", hover)
        self.assertIn("Bits: 11001010", hover)
        self.assertIn("Hex: CA", hover)

    def test_replace_old_bits_and_hex(self):
        base = "FSK: 100.0 kBd\nBits: 00000000\nHex: 00"
        new_bits = "11111111"
        hover = format_hover_bits(base, new_bits)
        self.assertNotIn("Bits: 00000000", hover)
        self.assertNotIn("Hex: 00", hover)
        self.assertIn("Bits: 11111111", hover)
        self.assertIn("Hex: FF", hover)
        self.assertEqual(hover.count("Bits:"), 1)
        self.assertEqual(hover.count("Hex:"), 1)

    def test_truncation_for_long_bits(self):
        long_bits = "1" * 128
        hover = format_hover_bits("", long_bits, max_hover_bits=32)
        self.assertIn("... (128 bits)", hover)

    def test_overlay_method(self):
        ov = Overlay(shape=OverlayShape.RECT, hover_str="Header Line")
        ov.update_hover_bits("1010")
        self.assertIn("Header Line", ov.hover_str)
        self.assertIn("Bits: 1010", ov.hover_str)
        self.assertIn("Hex: A", ov.hover_str)


class TestPluginsUpdateHoverBits(unittest.TestCase):
    def test_uw_sync_updates_hover(self):
        # 16-bit preamble (AAAA), 16-bit UW (7E76), 16-bit payload (1234)
        stream = "101010101010101001111110011101100001001000110100"
        ov = Overlay(shape=OverlayShape.RECT, hover_str="FSK: 100 kBd\nBits: " + stream)
        ov.metadata = {"bits": stream}

        ctx = _make_context(ov, {"uw_hex": "0x7E76", "min_match_pct": 95.0})
        res = uw_mod.run(np.empty(0, dtype=np.complex64), ctx)
        _apply_result(ov, res)

        self.assertIn("Sync: Locked @ bit 16", ov.hover_str)
        self.assertIn("Bits: 0001001000110100", ov.hover_str)
        self.assertIn("Hex: 1234", ov.hover_str)
        self.assertNotIn(stream, ov.hover_str)

    def test_block_fec_updates_hover(self):
        # Hamming(7,4) encoded block for message with 1 bit flip
        received = "0011001"
        ov = Overlay(shape=OverlayShape.RECT, hover_str="Sync: Locked\nBits: " + received)
        ov.metadata = {"bits": received}

        ctx = _make_context(ov, {"code": "Hamming(7,4)"})
        res = fec_mod.run(np.empty(0, dtype=np.complex64), ctx)
        _apply_result(ov, res)

        self.assertIn("FEC (Hamming(7,4))", ov.hover_str)
        self.assertIn(f"Bits: {ov.metadata['bits']}", ov.hover_str)
        self.assertIn(f"Hex: {ov.metadata['hex']}", ov.hover_str)

    def test_crc_checker_updates_hover(self):
        # Payload 0x1234 + CRC-16-CCITT
        payload = np.array([0,0,0,1, 0,0,1,0, 0,0,1,1, 0,1,0,0], dtype=np.uint8)
        crc_val = crc_mod._calc_crc(payload, 0x1021, 16, 0xFFFF, 0x0000, False, False)
        crc_bits = np.array([(crc_val >> (15 - i)) & 1 for i in range(16)], dtype=np.uint8)
        packet = np.concatenate([payload, crc_bits])
        packet_str = "".join(str(b) for b in packet)

        ov = Overlay(shape=OverlayShape.RECT, hover_str="Pre-CRC info\nBits: " + packet_str)
        ov.metadata = {"bits": packet_str}

        ctx = _make_context(ov, {
            "preset": "Custom", "crc_bits": 16, "poly_hex": "0x1021",
            "init_hex": "0xFFFF", "xorout_hex": "0x0000", "refin": False, "refout": False
        })
        res = crc_mod.run(np.empty(0, dtype=np.complex64), ctx)
        _apply_result(ov, res)

        self.assertIn("CRC: PASS", ov.hover_str)
        self.assertIn("Bits: 0001001000110100", ov.hover_str)
        self.assertIn("Hex: 1234", ov.hover_str)
        self.assertNotIn(packet_str, ov.hover_str)

    def test_diff_decoder_updates_hover(self):
        bits = "0110"
        ov = Overlay(shape=OverlayShape.RECT, hover_str="Bits: " + bits)
        ov.metadata = {"bits": bits}

        ctx = _make_context(ov, {"mode": "NRZ-M (1 on bit change)", "init_bit": 0})
        res = diff_mod.run(np.empty(0, dtype=np.complex64), ctx)
        _apply_result(ov, res)

        self.assertIn("Diff: Decoded", ov.hover_str)
        self.assertIn(f"Bits: {ov.metadata['bits']}", ov.hover_str)

    def test_xor_mask_updates_hover(self):
        bits = "11110000"
        ov = Overlay(shape=OverlayShape.RECT, hover_str="Bits: " + bits)
        ov.metadata = {"bits": bits}

        ctx = _make_context(ov, {"preset": "Custom Hex Mask", "mask_hex": "0xFF"})
        res = xor_mod.run(np.empty(0, dtype=np.complex64), ctx)
        _apply_result(ov, res)

        self.assertIn("XOR: Masked", ov.hover_str)
        self.assertIn("Bits: 00001111", ov.hover_str)
        self.assertIn("Hex: 0F", ov.hover_str)

    def test_bit_reversal_updates_hover(self):
        bits = "10000000"  # MSB 0x80 -> reversed 8-bit becomes 0x01 (00000001)
        ov = Overlay(shape=OverlayShape.RECT, hover_str="Bits: " + bits)
        ov.metadata = {"bits": bits}

        ctx = _make_context(ov, {"chunk_size": 8})
        res = rev_mod.run(np.empty(0, dtype=np.complex64), ctx)
        _apply_result(ov, res)

        self.assertIn("Rev: Flipped", ov.hover_str)
        self.assertIn("Bits: 00000001", ov.hover_str)
        self.assertIn("Hex: 01", ov.hover_str)


class TestFrameworkAutoHoverBits(unittest.TestCase):
    def test_chain_auto_updates_hover_when_plugin_only_edits_bits(self):
        # A custom plugin that edits metadata["bits"] but does not touch hover_str
        def custom_step(samples, info):
            res = PluginResult()
            for o in info.overlays:
                new_meta = dict(o.metadata)
                new_meta["bits"] = "11001100"
                new_meta["hex"] = "CC"
                res.update(o.id, metadata=new_meta)
            return res

        ov = Overlay(shape=OverlayShape.RECT, hover_str="Existing Burst\nBits: 00000000\nHex: 00")
        ov.metadata = {"bits": "00000000"}

        chain = PluginChain(
            steps=[(custom_step, {}, "Bit Inverter")],
            name="TestAutoHoverChain"
        )
        ctx = _make_context(ov)
        res = chain.run(np.zeros(10, dtype=np.complex64), ctx)

        # Inspect updates generated by the chain
        self.assertEqual(len(res.updates), 1)
        oid, fields = res.updates[0]
        self.assertIn("hover_str", fields)
        self.assertIn("Bits: 11001100", fields["hover_str"])
        self.assertIn("Hex: CC", fields["hover_str"])
        self.assertNotIn("Bits: 00000000", fields["hover_str"])


if __name__ == "__main__":
    unittest.main()

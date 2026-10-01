"""testing/test_demod_extensions.py

Comprehensive unit test suite for the 6 new built-in post-demodulation bit plugins:
1. Sync Word Slicer (uw_sync.py)
2. Differential Decoder (diff_decoder.py)
3. XOR Mask / De-whitener (xor_mask.py)
4. Bit Reversal / rev8 (bit_reversal.py)
5. Block FEC Decoder (block_fec_decoder.py)
6. CRC Checker (crc_checker.py)
Plus End-to-End composable pipeline execution.
"""

from __future__ import annotations

import unittest
import numpy as np

from iqview.overlays import Overlay, OverlayShape
from iqview.plugins import PluginContext, PluginResult
from iqview.plugins.builtin import get_builtin_plugin

import iqview.plugins.builtin.uw_sync as uw_mod
import iqview.plugins.builtin.diff_decoder as diff_mod
import iqview.plugins.builtin.xor_mask as xor_mod
import iqview.plugins.builtin.bit_reversal as rev_mod
import iqview.plugins.builtin.block_fec_decoder as fec_mod
import iqview.plugins.builtin.crc_checker as crc_mod


def _make_context(overlay: Overlay, params: dict | None = None) -> PluginContext:
    """Helper to construct a mock PluginContext for testing."""
    return PluginContext(
        sample_rate=1_000_000.0,
        center_freq=433_920_000.0,
        t_start=0.0,
        t_end=0.1,
        f_start=433_820_000.0,
        f_end=434_020_000.0,
        overlays=[overlay],
        params=params or {},
    )


def _apply_result(overlay: Overlay, res: PluginResult) -> Overlay:
    """Apply PluginResult mutations to overlay object matching IQView runtime behavior."""
    for oid, fields in res.updates:
        if str(oid) == str(overlay.id):
            for k, v in fields.items():
                setattr(overlay, k, v)
    return overlay


class TestDemodExtensionsRegistry(unittest.TestCase):
    """Test registry discovery and metadata for all 6 demod extension plugins."""

    def test_discovery_by_name_and_stem(self):
        plugins = [
            ("Sync Word Slicer", "uw_sync", uw_mod),
            ("Differential Decoder", "diff_decoder", diff_mod),
            ("XOR Mask", "xor_mask", xor_mod),
            ("Bit Reversal (rev8)", "bit_reversal", rev_mod),
            ("Block FEC Decoder", "block_fec_decoder", fec_mod),
            ("CRC Checker", "crc_checker", crc_mod),
        ]
        for name, stem, expected_mod in plugins:
            mod_by_name = get_builtin_plugin(name)
            self.assertIsNotNone(mod_by_name, f"Failed to find {name} by name")
            self.assertEqual(mod_by_name, expected_mod)

            mod_by_stem = get_builtin_plugin(stem)
            self.assertIsNotNone(mod_by_stem, f"Failed to find {stem} by stem")
            self.assertEqual(mod_by_stem, expected_mod)

            # Assert all 6 do not require wideband IQ
            self.assertFalse(
                getattr(expected_mod, "PLUGIN_NEEDS_WIDEBAND_IQ", True),
                f"{name} should have PLUGIN_NEEDS_WIDEBAND_IQ = False",
            )


class TestUWSync(unittest.TestCase):
    """Test Sync Word Slicer (uw_sync.py)."""

    def test_exact_sync_and_slice(self):
        # Preamble (0xAAAA) + UW (0x7E76) + Payload (0x1234)
        preamble = "1010101010101010"
        uw       = "0111111001110110"  # 0x7E76
        payload  = "0001001000110100"  # 0x1234
        full_stream = preamble + uw + payload

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": full_stream}

        ctx = _make_context(overlay, {"uw_hex": "0x7E76", "min_match_pct": 95.0})
        res = uw_mod.run(np.empty(0, dtype=np.complex64), ctx)
        self.assertEqual(len(res.updates), 1)

        up = _apply_result(overlay, res)
        # Verify bits_pre_sync preserves original
        self.assertEqual(up.metadata["bits_pre_sync"], full_stream)
        # Verify payload is sliced starting after UW
        self.assertEqual(up.metadata["bits"], payload)
        self.assertEqual(up.metadata["num_bits"], len(payload))
        self.assertTrue(up.metadata["uw_found"])
        self.assertEqual(up.metadata["uw_index"], len(preamble))
        self.assertEqual(up.metadata["uw_bit_errors"], 0)
        self.assertEqual(up.metadata["uw_match_pct"], 100.0)

    def test_bit_error_tolerance(self):
        # UW with 1 bit flip (0x7F76 vs 0x7E76 -> 15/16 match = 93.75%)
        preamble = "10101010"
        uw_flips = "0111111101110110"  # 0x7F76 (bit 7 flipped from 0 to 1)
        payload  = "11001100"
        full_stream = preamble + uw_flips + payload

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": full_stream}

        # With 90% tolerance, should lock
        ctx = _make_context(overlay, {"uw_hex": "0x7E76", "min_match_pct": 90.0})
        res = uw_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        self.assertTrue(up.metadata["uw_found"])
        self.assertEqual(up.metadata["uw_bit_errors"], 1)
        self.assertAlmostEqual(up.metadata["uw_match_pct"], 93.75, places=2)
        self.assertEqual(up.metadata["bits"], payload)

    def test_locks_onto_first_match(self):
        # Two identical sync words in stream: should slice from the FIRST one
        uw = "0111111001110110"  # 0x7E76
        stream = "0000" + uw + "1111" + uw + "0000"
        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": stream}

        ctx = _make_context(overlay, {"uw_hex": "0x7E76", "min_match_pct": 100.0})
        res = uw_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        self.assertTrue(up.metadata["uw_found"])
        self.assertEqual(up.metadata["uw_index"], 4)
        # Payload is everything after first UW
        self.assertEqual(up.metadata["bits"], "1111" + uw + "0000")


class TestDiffDecoder(unittest.TestCase):
    """Test Differential Decoder (diff_decoder.py)."""

    def test_nrz_m_roundtrip(self):
        # Test stream
        original_bits = [1, 0, 1, 1, 0, 0, 1, 0, 1]
        init_bit = 0

        # Encode NRZ-M: s_0 = b_0 ^ init, s_n = b_n ^ s_{n-1}
        tx_symbols = []
        prev = init_bit
        for b in original_bits:
            s = b ^ prev
            tx_symbols.append(s)
            prev = s

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": "".join(str(s) for s in tx_symbols)}

        ctx = _make_context(overlay, {"mode": "NRZ-M (1 on bit change)", "init_bit": 0})
        res = diff_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        self.assertEqual(up.metadata["bits_pre_diff"], "".join(str(s) for s in tx_symbols))
        self.assertEqual(up.metadata["bits"], "".join(str(b) for b in original_bits))

    def test_nrz_m_init_bit_1(self):
        original_bits = [1, 1, 0, 1]
        init_bit = 1

        tx_symbols = []
        prev = init_bit
        for b in original_bits:
            s = b ^ prev
            tx_symbols.append(s)
            prev = s

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": "".join(str(s) for s in tx_symbols)}

        ctx = _make_context(overlay, {"mode": "NRZ-M (1 on bit change)", "init_bit": 1})
        res = diff_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        self.assertEqual(up.metadata["bits"], "".join(str(b) for b in original_bits))


class TestXORMask(unittest.TestCase):
    """Test XOR Mask / De-whitener (xor_mask.py)."""

    def test_custom_hex_mask_invertibility(self):
        raw_bits = "101100101101000111110000"
        mask_hex = "0xA5"  # 10100101

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": raw_bits}

        # First pass: de-whiten
        ctx1 = _make_context(overlay, {"preset": "Custom Hex Mask", "mask_hex": mask_hex})
        res1 = xor_mod.run(np.empty(0, dtype=np.complex64), ctx1)
        up1 = _apply_result(overlay, res1)
        masked_bits = up1.metadata["bits"]

        self.assertNotEqual(masked_bits, raw_bits)
        self.assertEqual(up1.metadata["bits_pre_xor"], raw_bits)

        # Second pass: XOR is self-inverting
        ctx2 = _make_context(up1, {"preset": "Custom Hex Mask", "mask_hex": mask_hex})
        res2 = xor_mod.run(np.empty(0, dtype=np.complex64), ctx2)
        up2 = _apply_result(up1, res2)

        self.assertEqual(up2.metadata["bits"], raw_bits)

    def test_invert_all_preset(self):
        raw_bits = "11001010"
        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": raw_bits}

        ctx = _make_context(overlay, {"preset": "Invert All (0xFF)"})
        res = xor_mod.run(np.empty(0, dtype=np.complex64), ctx)
        up = _apply_result(overlay, res)

        expected = "00110101"
        self.assertEqual(up.metadata["bits"], expected)


class TestBitReversal(unittest.TestCase):
    """Test Bit Reversal (rev8) (bit_reversal.py)."""

    def test_rev8_chunk_8(self):
        # 0x80 -> 10000000 -> rev8 -> 00000001 (0x01)
        # 0xB2 -> 10110010 -> rev8 -> 01001101 (0x4D)
        raw_bits = "10000000" "10110010"
        expected = "00000001" "01001101"

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": raw_bits}

        ctx = _make_context(overlay, {"chunk_size": 8})
        res = rev_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        self.assertEqual(up.metadata["bits_pre_rev8"], raw_bits)
        self.assertEqual(up.metadata["bits"], expected)

    def test_odd_length_trailing_bits_preserved(self):
        # 10 bits: 8 bits reversed, 2 trailing bits intact
        raw_bits = "10000000" "10"
        expected = "00000001" "10"

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": raw_bits}

        ctx = _make_context(overlay, {"chunk_size": 8})
        res = rev_mod.run(np.empty(0, dtype=np.complex64), ctx)
        up = _apply_result(overlay, res)
        self.assertEqual(up.metadata["bits"], expected)


class TestBlockFECDecoder(unittest.TestCase):
    """Test Block FEC Decoder (block_fec_decoder.py)."""

    def test_hamming_7_4_clean(self):
        # Message nibble 0b1011 (k=4)
        msg = np.array([1, 0, 1, 1], dtype=np.uint8)
        cw = (msg @ fec_mod.G_HAMMING74) % 2
        codeword = "".join(str(b) for b in cw)
        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": codeword}

        ctx = _make_context(overlay, {"code": "Hamming(7,4)"})
        res = fec_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        self.assertEqual(up.metadata["bits"], "1011")
        self.assertEqual(up.metadata["fec_clean_blocks"], 1)
        self.assertEqual(up.metadata["fec_corrected_blocks"], 0)

    def test_hamming_7_4_corrects_single_bit_error(self):
        msg = np.array([1, 0, 1, 1], dtype=np.uint8)
        cw = (msg @ fec_mod.G_HAMMING74) % 2
        cw_err = cw.copy()
        cw_err[5] ^= 1  # Flip parity bit
        codeword_err = "".join(str(b) for b in cw_err)
        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": codeword_err}

        ctx = _make_context(overlay, {"code": "Hamming(7,4)"})
        res = fec_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        # Must still decode to original message "1011"
        self.assertEqual(up.metadata["bits"], "1011")
        self.assertEqual(up.metadata["fec_clean_blocks"], 0)
        self.assertEqual(up.metadata["fec_corrected_blocks"], 1)
        self.assertEqual(up.metadata["fec_bit_errors_corrected"], 1)

    def test_golay_24_12_corrects_three_errors(self):
        # Generate valid Golay(24,12) codeword for message 12 bits
        G = fec_mod.G_GOLAY24
        msg = np.array([1, 0, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1], dtype=np.uint8)
        codeword = (msg @ G) % 2

        # Inject 3 bit errors at positions 2, 7, 19
        rx = codeword.copy()
        rx[2] ^= 1
        rx[7] ^= 1
        rx[19] ^= 1

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": "".join(str(b) for b in rx)}

        ctx = _make_context(overlay, {"code": "Golay(24,12)"})
        res = fec_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        expected_msg = "".join(str(b) for b in msg)
        self.assertEqual(up.metadata["bits"], expected_msg)
        self.assertEqual(up.metadata["fec_corrected_blocks"], 1)
        self.assertEqual(up.metadata["fec_bit_errors_corrected"], 3)

    def test_zero_padding_requirement(self):
        # 10 bits input for Hamming(7,4): should pad 4 zeros to reach 14 bits (2 blocks)
        bits_10 = "1011100" "101"
        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": bits_10}

        ctx = _make_context(overlay, {"code": "Hamming(7,4)"})
        res = fec_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        self.assertEqual(up.metadata["fec_pad_bits"], 4)
        self.assertEqual(up.metadata["fec_total_blocks"], 2)


class TestCRCChecker(unittest.TestCase):
    """Test CRC Checker (crc_checker.py)."""

    def test_crc16_ccitt_pass_and_strip(self):
        # Payload b"123456789"
        msg = b"123456789"
        payload_bits = []
        for b in msg:
            for s in range(7, -1, -1):
                payload_bits.append((b >> s) & 1)
        payload_str = "".join(str(b) for b in payload_bits)

        # Expected CRC-16-CCITT for b"123456789" is 0x29B1 = 0010 1001 1011 0001
        crc_val = 0x29B1
        crc_str = f"{crc_val:016b}"

        # Combine payload + CRC
        full_packet = payload_str + crc_str

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": full_packet}

        ctx = _make_context(overlay, {"preset": "CRC-16-CCITT"})
        res = crc_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        # Assert PASS
        self.assertTrue(up.metadata["crc_valid"])
        # Green color on PASS
        self.assertEqual(up.color, "#2ecc71")
        # Assert CRC is stripped from bits
        self.assertEqual(up.metadata["bits"], payload_str)
        # Assert CRC hex is saved
        self.assertEqual(up.metadata["crc_hex"], "0x29b1")
        # Assert bits_pre_crc saved original
        self.assertEqual(up.metadata["bits_pre_crc"], full_packet)

    def test_crc16_ccitt_fail_color(self):
        # Corrupt one bit in payload
        msg = b"123456789"
        payload_bits = []
        for b in msg:
            for s in range(7, -1, -1):
                payload_bits.append((b >> s) & 1)
        payload_bits[0] ^= 1  # Corrupt bit
        payload_str = "".join(str(b) for b in payload_bits)

        crc_str = f"{0x29B1:016b}"
        full_packet = payload_str + crc_str

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": full_packet}

        ctx = _make_context(overlay, {"preset": "CRC-16-CCITT"})
        res = crc_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        # Assert FAIL
        self.assertFalse(up.metadata["crc_valid"])
        # Red color on FAIL
        self.assertEqual(up.color, "#e74c3c")
        # Still strips CRC
        self.assertEqual(up.metadata["bits"], payload_str)

    def test_crc32_ieee_pass(self):
        msg = b"123456789"
        # Reflected input for CRC-32
        payload_bits = []
        for b in msg:
            for s in range(8):
                payload_bits.append((b >> s) & 1)
        payload_str = "".join(str(b) for b in payload_bits)

        # Expected 0xCBF43926
        crc_val = 0xCBF43926
        crc_str = f"{crc_val:032b}"
        full_packet = payload_str + crc_str

        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": full_packet}

        ctx = _make_context(overlay, {"preset": "CRC-32-IEEE"})
        res = crc_mod.run(np.empty(0, dtype=np.complex64), ctx)

        up = _apply_result(overlay, res)
        self.assertTrue(up.metadata["crc_valid"])
        self.assertEqual(up.color, "#2ecc71")
        self.assertEqual(up.metadata["crc_hex"], "0xcbf43926")


class TestEndToEndChaining(unittest.TestCase):
    """
    Test end-to-end chaining of all 6 plugins:
    Demod -> UW Sync -> Differential Decoder -> XOR Mask -> rev8 -> Block FEC -> CRC Checker
    """

    def test_full_pipeline(self):
        # Target after FEC decode + CRC:
        target_payload = "1011"
        crc_val = crc_mod._calc_crc(np.array([1, 0, 1, 1], dtype=np.uint8), 0x1021, 16, 0xFFFF, 0, False, False)
        target_with_crc = target_payload + f"{crc_val:016b}"  # 4 + 16 = 20 bits

        # FEC Encode with Hamming(7,4): 20 bits is 5 blocks of 4 -> 5 * 7 = 35 bits
        G = fec_mod.G_HAMMING74
        encoded_bits = []
        for i in range(0, len(target_with_crc), 4):
            nibble = np.array([int(b) for b in target_with_crc[i : i + 4]], dtype=np.uint8)
            cw = (nibble @ G) % 2
            encoded_bits.extend(cw)
        # Inject 1 bit error in block 0
        encoded_bits[3] ^= 1

        # Apply rev8 inverse (rev8 is self-inverting)
        rev8_applied = rev_mod._rev_bits(np.array(encoded_bits, dtype=np.uint8), 8)

        # Apply XOR mask 0xAA (self-inverting)
        mask_bits = xor_mod._hex_to_mask_bits("0xAA", "msb_first")
        xor_applied = xor_mod._apply_xor_mask(rev8_applied, mask_bits)

        # Apply Diff encode (NRZ-M inverse)
        diff_applied = []
        prev = 0
        for b in xor_applied:
            s = b ^ prev
            diff_applied.append(s)
            prev = s

        # Prepend Preamble (0xAAAA) + UW (0x7E76)
        preamble = "1010101010101010"
        uw = "0111111001110110"
        full_received_bits = preamble + uw + "".join(str(b) for b in diff_applied)

        # Now execute the 6 plugins in sequence!
        overlay = Overlay(shape=OverlayShape.RECT)
        overlay.metadata = {"bits": full_received_bits}

        # Step 1: UW Sync
        ctx1 = _make_context(overlay, {"uw_hex": "0x7E76", "min_match_pct": 95.0})
        res1 = uw_mod.run(np.empty(0, dtype=np.complex64), ctx1)
        o1 = _apply_result(overlay, res1)
        self.assertTrue(o1.metadata["uw_found"])

        # Step 2: Diff Decode
        ctx2 = _make_context(o1, {"mode": "NRZ-M (1 on bit change)", "init_bit": 0})
        res2 = diff_mod.run(np.empty(0, dtype=np.complex64), ctx2)
        o2 = _apply_result(o1, res2)

        # Step 3: XOR Mask
        ctx3 = _make_context(o2, {"preset": "Custom Hex Mask", "mask_hex": "0xAA"})
        res3 = xor_mod.run(np.empty(0, dtype=np.complex64), ctx3)
        o3 = _apply_result(o2, res3)

        # Step 4: rev8
        ctx4 = _make_context(o3, {"chunk_size": 8})
        res4 = rev_mod.run(np.empty(0, dtype=np.complex64), ctx4)
        o4 = _apply_result(o3, res4)

        # Step 5: FEC Decode (Hamming(7,4) corrects injected bit error)
        ctx5 = _make_context(o4, {"code": "Hamming(7,4)"})
        res5 = fec_mod.run(np.empty(0, dtype=np.complex64), ctx5)
        o5 = _apply_result(o4, res5)
        self.assertEqual(o5.metadata["fec_corrected_blocks"], 1)

        # Step 6: CRC Checker
        ctx6 = _make_context(o5, {"preset": "CRC-16-CCITT"})
        res6 = crc_mod.run(np.empty(0, dtype=np.complex64), ctx6)
        o6 = _apply_result(o5, res6)

        # Verify final assertions!
        self.assertTrue(o6.metadata["crc_valid"])
        self.assertEqual(o6.color, "#2ecc71")
        self.assertEqual(o6.metadata["bits"], target_payload)
        self.assertEqual(o6.metadata["crc_hex"], f"0x{crc_val:04x}")

        # Verify full pre-state preservation trail
        self.assertIn("bits_pre_sync", o6.metadata)
        self.assertIn("bits_pre_diff", o6.metadata)
        self.assertIn("bits_pre_xor", o6.metadata)
        self.assertIn("bits_pre_rev8", o6.metadata)
        self.assertIn("bits_pre_fec", o6.metadata)
        self.assertIn("bits_pre_crc", o6.metadata)


class TestDropdownChoiceParameters(unittest.TestCase):
    """Verify that presets and modes are configured as choices dropdowns."""

    def test_preset_choices_configured(self):
        cases = [
            (crc_mod, "preset", ["CRC-16-CCITT", "CRC-16-IBM", "CRC-32-IEEE", "Custom"]),
            (crc_mod, "crc_position", ["end", "start"]),
            (crc_mod, "crc_endianness", ["auto", "msb_first", "lsb_first"]),
            (xor_mod, "preset", ["Custom Hex Mask", "Invert All (0xFF)", "CC1101 PN9"]),
            (xor_mod, "bit_order", ["msb_first", "lsb_first"]),
            (fec_mod, "code", ["Hamming(7,4)", "Hamming(8,4)", "Golay(24,12)", "Custom G Matrix"]),
            (diff_mod, "mode", ["NRZ-M (1 on bit change)", "NRZ-S (0 on bit change)"]),
            (diff_mod, "init_bit", [0, 1]),
            (rev_mod, "chunk_size", [8, 4, 16, 32]),
        ]
        for mod, param_key, expected_subset in cases:
            spec = mod.PLUGIN_PARAMS.get(param_key, {})
            self.assertEqual(spec.get("type"), "choice", f"{mod.PLUGIN_NAME}.{param_key} should be 'choice'")
            choices = spec.get("choices") or spec.get("options") or []
            for item in expected_subset:
                self.assertIn(item, choices, f"{item} should be in {mod.PLUGIN_NAME}.{param_key} choices")


if __name__ == "__main__":
    unittest.main()


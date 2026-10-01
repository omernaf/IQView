"""iqview/plugins/builtin/crc_checker.py

Built-in IQView Plugin: CRC Checker & Validator.

Validates packet integrity using configurable cyclic redundancy checks (CRC-8, CRC-16,
CRC-24, CRC-32, or custom polynomials). Extracts and strips the CRC field from
`overlay.metadata["bits"]`, saves the extracted CRC to `metadata["crc_hex"]`,
saves pre-check bits to `metadata["bits_pre_crc"]`, and colorizes the overlay
(green on PASS, red on FAIL).
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from iqview import PluginResult, PluginContext
from iqview.overlays import OverlayShape


PLUGIN_NAME              = "CRC Checker"
PLUGIN_DESCRIPTION       = (
    "Validates packet integrity via configurable CRC (polynomial, init, xorout, refin/refout, rev8), "
    "strips the CRC field, and highlights overlays green on PASS or red on FAIL."
)
PLUGIN_CATEGORY          = "Integrity & Validation"
PLUGIN_NEEDS_WIDEBAND_IQ = False

PLUGIN_DOC = """# CRC Checker & Validator

Computes cyclic redundancy check (CRC) verification across demodulated packet bits, strips the CRC field from `metadata["bits"]`, and visually updates the overlay color according to check results.

### Features
* **Standard Presets & Custom Polynomials**: Includes CRC-8, CRC-16-CCITT, CRC-16-IBM, CRC-16-MODBUS, CRC-24-BLE, CRC-32-IEEE, CRC-32C, and fully customizable parameters.
* **Rocksoft Parameter Model**: Supports custom polynomial, width (1–32 bits), initial value, final XOR, input reflection (`refin`), and output reflection (`refout`).
* **Pre-CRC rev8 Option**: Option to reverse bit order within each 8-bit byte before computing/extracting the CRC.
* **Configurable CRC Position**: Default at the end of the packet (`"end"`), at the start (`"start"`), or at an explicit bit index.
* **Automatic Stripping**: Always slices and removes the CRC from `metadata["bits"]` so downstream plugins only process clean payload data.
* **Pre-State Preservation**: Saves original bitstream to `metadata["bits_pre_crc"]`.
* **Visual Status Coloring**: Sets overlay color to vibrant green (`#2ecc71`) on PASS, or red (`#e74c3c`) on FAIL.

### Parameters
* **Preset** (`preset`): Standard preset or `"Custom"`.
* **Polynomial (Hex)** (`poly_hex`): Generator polynomial (e.g. `0x1021`, `0x8005`, `0x04C11DB7`).
* **CRC Width (Bits)** (`crc_bits`): CRC width in bits (e.g. `8`, `16`, `24`, `32`).
* **Initial Value (Hex)** (`init_hex`): Register preset value (e.g. `0xFFFF`, `0x0000`, `0xFFFFFFFF`).
* **Final XOR (Hex)** (`xorout_hex`): Value XORed into final CRC (e.g. `0x0000`, `0xFFFFFFFF`).
* **Reflect Input** (`refin`): Process byte bits LSB first.
* **Reflect Output** (`refout`): Reflect final CRC bits before XOR.
* **Byte Bit Reversal (rev8)** (`rev8`): Reverse bit order of every 8-bit byte before CRC calculation.
* **CRC Position** (`crc_position`): Location of CRC bits in packet (`"end"`, `"start"`, or integer bit offset).
* **CRC Endianness** (`crc_endianness`): Bit/byte packing of received CRC (`"auto"`, `"msb_first"`, `"lsb_first"`, `"little_endian_bytes"`, `"big_endian_bytes"`).

### Output Metadata
* `metadata["bits_pre_crc"]`: Unaltered bitstream prior to CRC check and stripping
* `metadata["bits"]`: Sliced payload bitstream (CRC stripped)
* `metadata["hex"]`: Hex formatted payload
* `metadata["num_bits"]`: Payload bit count
* `metadata["crc_valid"]`: `True` if calculated CRC matches received CRC, `False` otherwise
* `metadata["crc_hex"]`: Extracted received CRC in hex (e.g. `"0x6fd5"`)
* `metadata["crc_calculated"]`: Computed CRC in hex (e.g. `"0x6fd5"`)
* `metadata["crc_poly"]`: CRC polynomial used
* `metadata["crc_bits"]`: CRC width in bits
"""

# Preset definitions: (width, poly, init, xorout, refin, refout)
CRC_PRESETS = {
    "Custom": None,
    "CRC-8":              (8,  0x07,       0x00,       0x00,       False, False),
    "CRC-8-Dallas":       (8,  0x31,       0x00,       0x00,       True,  True),
    "CRC-16-CCITT":       (16, 0x1021,     0xFFFF,     0x0000,     False, False),
    "CRC-16-IBM":         (16, 0x8005,     0x0000,     0x0000,     True,  True),
    "CRC-16-MODBUS":      (16, 0x8005,     0xFFFF,     0x0000,     True,  True),
    "CRC-16-KERMIT":      (16, 0x1021,     0x0000,     0x0000,     True,  True),
    "CRC-24-BLE":         (24, 0x00065B,   0x555555,   0x000000,   True,  True),
    "CRC-32-IEEE":        (32, 0x04C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True,  True),
    "CRC-32C":            (32, 0x1EDC6F41, 0xFFFFFFFF, 0xFFFFFFFF, True,  True),
}

CRC_PRESET_VALUES = {
    "CRC-8":              {"crc_bits": 8,  "poly_hex": "0x07",       "init_hex": "0x00",       "xorout_hex": "0x00",       "refin": False, "refout": False},
    "CRC-8-Dallas":       {"crc_bits": 8,  "poly_hex": "0x31",       "init_hex": "0x00",       "xorout_hex": "0x00",       "refin": True,  "refout": True},
    "CRC-16-CCITT":       {"crc_bits": 16, "poly_hex": "0x1021",     "init_hex": "0xFFFF",     "xorout_hex": "0x0000",     "refin": False, "refout": False},
    "CRC-16-IBM":         {"crc_bits": 16, "poly_hex": "0x8005",     "init_hex": "0x0000",     "xorout_hex": "0x0000",     "refin": True,  "refout": True},
    "CRC-16-MODBUS":      {"crc_bits": 16, "poly_hex": "0x8005",     "init_hex": "0xFFFF",     "xorout_hex": "0x0000",     "refin": True,  "refout": True},
    "CRC-16-KERMIT":      {"crc_bits": 16, "poly_hex": "0x1021",     "init_hex": "0x0000",     "xorout_hex": "0x0000",     "refin": True,  "refout": True},
    "CRC-24-BLE":         {"crc_bits": 24, "poly_hex": "0x00065B",   "init_hex": "0x555555",   "xorout_hex": "0x000000",   "refin": True,  "refout": True},
    "CRC-32-IEEE":        {"crc_bits": 32, "poly_hex": "0x04C11DB7", "init_hex": "0xFFFFFFFF", "xorout_hex": "0xFFFFFFFF", "refin": True,  "refout": True},
    "CRC-32C":            {"crc_bits": 32, "poly_hex": "0x1EDC6F41", "init_hex": "0xFFFFFFFF", "xorout_hex": "0xFFFFFFFF", "refin": True,  "refout": True},
}

PLUGIN_PARAMS = {
    "preset": {
        "type": "choice",
        "default": "CRC-16-CCITT",
        "choices": [
            "CRC-16-CCITT",
            "CRC-16-IBM",
            "CRC-16-MODBUS",
            "CRC-16-KERMIT",
            "CRC-8",
            "CRC-8-Dallas",
            "CRC-24-BLE",
            "CRC-32-IEEE",
            "CRC-32C",
            "Custom",
        ],
        "preset_values": CRC_PRESET_VALUES,
        "label": "Preset",
        "tooltip": "Standard CRC preset configuration or choose Custom to specify all fields.",
    },
    "poly_hex": {
        "type": "str",
        "default": "0x1021",
        "label": "Polynomial (Hex)",
        "tooltip": "Generator polynomial in hex, e.g. 0x07 (CRC-8), 0x1021 (CCITT), 0x04C11DB7 (CRC-32).",
    },
    "crc_bits": {
        "type": "int",
        "default": 16,
        "label": "CRC Width (Bits)",
        "tooltip": "Bit length of the CRC check sequence (1 to 32 bits).",
    },
    "init_hex": {
        "type": "str",
        "default": "0xFFFF",
        "label": "Initial Value (Hex)",
        "tooltip": "Initial shift register value before processing, e.g. 0x0000 or 0xFFFF.",
    },
    "xorout_hex": {
        "type": "str",
        "default": "0x0000",
        "label": "Final XOR (Hex)",
        "tooltip": "Value XORed with the final shift register value, e.g. 0x0000 or 0xFFFFFFFF.",
    },
    "refin": {
        "type": "bool",
        "default": False,
        "label": "Reflect Input (refin)",
        "tooltip": "Treat input bits as reflected (LSB first within each byte).",
    },
    "refout": {
        "type": "bool",
        "default": False,
        "label": "Reflect Output (refout)",
        "tooltip": "Reflect shift register bits before applying final XOR.",
    },
    "rev8": {
        "type": "bool",
        "default": False,
        "label": "Byte Bit Reversal (rev8)",
        "tooltip": "Reverse bit order within every 8-bit byte before CRC calculation and slicing.",
    },
    "crc_position": {
        "type": "choice",
        "default": "end",
        "choices": ["end", "start"],
        "label": "CRC Position",
        "tooltip": "'end' (last bits of packet), 'start' (first bits), or 0-indexed integer bit position.",
    },
    "crc_endianness": {
        "type": "choice",
        "default": "auto",
        "choices": ["auto", "msb_first", "lsb_first", "little_endian_bytes", "big_endian_bytes"],
        "label": "CRC Endianness",
        "tooltip": "Packing of received CRC bits: 'auto', 'msb_first', 'lsb_first', 'little_endian_bytes', 'big_endian_bytes'.",
    },
}


def _parse_hex_int(val: Any, default: int = 0) -> int:
    """Parse hex or int string to integer."""
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if not s:
        return default
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s, 16) if any(c in "abcdefABCDEF" for c in s) else int(s, 10)
    except Exception:
        return default


def _ref_bits(val: int, width: int) -> int:
    """Reflect (reverse) bit order of an integer of given bit width."""
    res = 0
    for _ in range(width):
        res = (res << 1) | (val & 1)
        val >>= 1
    return res


def _rev8_bits(bits: np.ndarray) -> np.ndarray:
    """Reverse bit order within each 8-bit byte chunk."""
    n = len(bits)
    out = np.empty(n, dtype=np.uint8)
    full_chunks = n // 8
    for i in range(full_chunks):
        s = i * 8
        out[s : s + 8] = bits[s : s + 8][::-1]
    rem = n % 8
    if rem > 0:
        out[full_chunks * 8 :] = bits[full_chunks * 8 :]
    return out


def _calc_crc(
    data_bits: np.ndarray,
    poly: int,
    width: int,
    init: int,
    xorout: int,
    refin: bool,
    refout: bool,
) -> int:
    """
    Calculate standard Rocksoft-model CRC bit-by-bit over 1D uint8 bit array.
    """
    mask = (1 << width) - 1
    if refin:
        poly_rev = _ref_bits(poly, width)
        reg = _ref_bits(init, width)
        for b in data_bits:
            bit_xor = (reg & 1) ^ int(b)
            reg = reg >> 1
            if bit_xor:
                reg ^= poly_rev
        if not refout:
            reg = _ref_bits(reg, width)
    else:
        reg = init & mask
        for b in data_bits:
            bit_xor = ((reg >> (width - 1)) & 1) ^ int(b)
            reg = (reg << 1) & mask
            if bit_xor:
                reg ^= poly
        if refout:
            reg = _ref_bits(reg, width)

    return (reg ^ xorout) & mask


def _decode_crc_integer(crc_bits: np.ndarray, width: int, endianness: str) -> int:
    """Convert received CRC bits to integer under the specified endianness/packing."""
    if endianness == "lsb_first":
        val = 0
        for i, b in enumerate(crc_bits[:width]):
            val |= (int(b) & 1) << i
        return val
    elif endianness == "little_endian_bytes":
        # Byte-swapped: byte 0 is lowest significant byte
        val = 0
        num_bytes = (width + 7) // 8
        for byte_idx in range(num_bytes):
            byte_start = byte_idx * 8
            byte_bits = crc_bits[byte_start : min(byte_start + 8, width)]
            byte_val = 0
            for b in byte_bits:
                byte_val = (byte_val << 1) | int(b)
            val |= byte_val << (byte_idx * 8)
        return val
    else:
        # Default big_endian / msb_first
        val = 0
        for b in crc_bits[:width]:
            val = (val << 1) | int(b)
        return val


def _parse_bits(raw: Any) -> Optional[np.ndarray]:
    """Parse 'bits' from overlay metadata into 1D uint8 bit array."""
    if raw is None:
        return None
    if isinstance(raw, str):
        cleaned = [1 if c in ("1", "T", "t") else 0 for c in raw if c in ("0", "1", "T", "t", "F", "f")]
        return np.asarray(cleaned, dtype=np.uint8) if cleaned else None
    if isinstance(raw, (list, tuple, np.ndarray)):
        arr = np.asarray(raw, dtype=np.uint8).ravel()
        return (arr != 0).astype(np.uint8) if len(arr) > 0 else None
    if isinstance(raw, (bytes, bytearray)):
        bits = []
        for b in raw:
            for s in range(7, -1, -1):
                bits.append((b >> s) & 1)
        return np.asarray(bits, dtype=np.uint8) if bits else None
    return None


def _bits_to_str(bits: np.ndarray) -> str:
    """Format bit array as binary string."""
    return "".join(str(int(b)) for b in bits)


def _bits_to_hex(bits: np.ndarray) -> str:
    """Convert bit array to formatted uppercase hex string."""
    n = len(bits)
    if n == 0:
        return ""
    pad_len = (8 - (n % 8)) % 8
    padded = np.pad(bits, (0, pad_len), constant_values=0) if pad_len > 0 else bits
    byte_vals = []
    for i in range(0, len(padded), 8):
        byte_val = 0
        for bit in padded[i : i + 8]:
            byte_val = (byte_val << 1) | int(bit)
        byte_vals.append(f"{byte_val:02X}")
    return " ".join(byte_vals)


def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()

    target_overlays = [
        o for o in info.overlays
        if o.shape == OverlayShape.RECT or (hasattr(o, "_shape_name") and o._shape_name() == "RECT")
    ]
    if not target_overlays:
        result.log("No Rect overlays found in active scope.")
        result.warning("No Rect overlays found in active scope.", title="CRC Checker")
        return result

    # Resolve preset if specified
    preset_name = str(info.params.get("preset", "Custom")).strip()
    preset_vals = CRC_PRESETS.get(preset_name)

    if preset_vals is not None:
        p_width, p_poly, p_init, p_xorout, p_refin, p_refout = preset_vals
        width  = p_width
        poly   = p_poly
        init   = p_init
        xorout = p_xorout
        refin  = p_refin
        refout = p_refout
    else:
        width  = int(info.params.get("crc_bits", 16))
        poly   = _parse_hex_int(info.params.get("poly_hex", "0x1021"), default=0x1021)
        init   = _parse_hex_int(info.params.get("init_hex", "0xFFFF"), default=0xFFFF)
        xorout = _parse_hex_int(info.params.get("xorout_hex", "0x0000"), default=0x0000)
        refin  = bool(info.params.get("refin", False))
        refout = bool(info.params.get("refout", False))

    rev8_opt    = bool(info.params.get("rev8", False))
    crc_pos_str = str(info.params.get("crc_position", "end")).strip().lower()
    crc_endian  = str(info.params.get("crc_endianness", "auto")).strip().lower()

    if width < 1 or width > 32:
        result.log(f"Invalid CRC width {width}. Must be between 1 and 32.")
        result.error(f"Invalid CRC width {width}. Must be between 1 and 32 bits.", title="CRC Checker")
        return result

    hex_len = (width + 3) // 4
    processed_count = 0
    pass_count = 0
    fail_count = 0

    for overlay in target_overlays:
        raw_bits = overlay.metadata.get("bits")
        bits = _parse_bits(raw_bits)
        if bits is None or len(bits) == 0:
            continue

        # Save pre-check bitstream
        overlay.metadata["bits_pre_crc"] = _bits_to_str(bits)

        # Apply rev8 if requested
        working_bits = _rev8_bits(bits) if rev8_opt else bits.copy()

        n_total = len(working_bits)
        if n_total < width:
            result.log(f"Overlay #{overlay.id}: bit length ({n_total}) shorter than CRC width ({width}). Marked FAIL.")
            overlay.color = "#e74c3c"
            overlay.border_color = "#c0392b"
            overlay.metadata["crc_valid"] = False
            overlay.metadata["crc_hex"] = "0x0"
            overlay.metadata["crc_calculated"] = f"0x{0:0{hex_len}x}"
            result.update(overlay)
            fail_count += 1
            processed_count += 1
            continue

        # Extract CRC bits and slice payload bits
        if crc_pos_str == "end":
            payload_bits = working_bits[:-width]
            rx_crc_bits  = working_bits[-width:]
        elif crc_pos_str == "start":
            payload_bits = working_bits[width:]
            rx_crc_bits  = working_bits[:width]
        else:
            try:
                split_idx = int(crc_pos_str)
                split_idx = max(0, min(split_idx, n_total - width))
                payload_bits = np.concatenate([working_bits[:split_idx], working_bits[split_idx + width :]])
                rx_crc_bits  = working_bits[split_idx : split_idx + width]
            except Exception:
                # Default to end
                payload_bits = working_bits[:-width]
                rx_crc_bits  = working_bits[-width:]

        # Compute calculated CRC
        calc_crc = _calc_crc(payload_bits, poly, width, init, xorout, refin, refout)

        # Compare received CRC with calculated CRC
        # If endianness is 'auto', test msb_first, lsb_first, and little_endian_bytes
        rx_crc_val = _decode_crc_integer(rx_crc_bits, width, endianness="msb_first")
        crc_valid = False

        if crc_endian == "auto":
            candidates = [
                ("msb_first", _decode_crc_integer(rx_crc_bits, width, "msb_first")),
                ("lsb_first", _decode_crc_integer(rx_crc_bits, width, "lsb_first")),
                ("little_endian_bytes", _decode_crc_integer(rx_crc_bits, width, "little_endian_bytes")),
            ]
            for order_name, cand_val in candidates:
                if cand_val == calc_crc:
                    crc_valid = True
                    rx_crc_val = cand_val
                    break
        else:
            rx_crc_val = _decode_crc_integer(rx_crc_bits, width, crc_endian)
            crc_valid = (rx_crc_val == calc_crc)

        # Visual color updates: Green for PASS, Red for FAIL
        if crc_valid:
            overlay.color = "#2ecc71"
            overlay.border_color = "#27ae60"
            pass_count += 1
        else:
            overlay.color = "#e74c3c"
            overlay.border_color = "#c0392b"
            fail_count += 1

        # Strip CRC and update overlay payload bits
        overlay.metadata["bits"]           = _bits_to_str(payload_bits)
        overlay.metadata["hex"]            = _bits_to_hex(payload_bits)
        overlay.metadata["num_bits"]       = len(payload_bits)
        overlay.metadata["crc_valid"]      = bool(crc_valid)
        overlay.metadata["crc_hex"]        = f"0x{rx_crc_val:0{hex_len}x}"
        overlay.metadata["crc_calculated"] = f"0x{calc_crc:0{hex_len}x}"
        overlay.metadata["crc_poly"]       = f"0x{poly:X}"
        overlay.metadata["crc_bits"]       = width

        result.update(overlay)
        processed_count += 1

    result.log(
        f"CRC Checker: evaluated {processed_count} bursts. "
        f"PASS: {pass_count}, FAIL: {fail_count} (poly=0x{poly:X}, width={width})."
    )
    if processed_count == 0 and len(target_overlays) > 0:
        result.warning(
            "None of the candidate bursts contain demodulated 'bits' in metadata to check CRC.\n\n"
            "Run a demodulator plugin (such as FSK Demodulator) before CRC Checker.",
            title="CRC Checker",
        )
    return result

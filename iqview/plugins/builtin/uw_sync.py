"""iqview/plugins/builtin/uw_sync.py

Built-in IQView Plugin: Sync Word Slicer (Unique Word Synchronization).

Searches for a user-specified Unique Word (Sync Word) in `overlay.metadata["bits"]`
with configurable bit-error tolerance (e.g. >= 90% accuracy). Upon finding the first
match, it records sync telemetry, saves the original bitstream to `bits_pre_sync`,
and slices the payload bits starting immediately after the Unique Word.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from iqview import PluginResult, PluginContext, format_hover_bits
from iqview.overlays import OverlayShape


PLUGIN_NAME              = "Sync Word Slicer"
PLUGIN_DESCRIPTION       = (
    "Synchronizes to a target Unique Word (Sync Word) with bit-error tolerance, "
    "stripping preamble and UW to extract the clean payload bitstream."
)
PLUGIN_CATEGORY          = "Framing & Synchronization"
PLUGIN_NEEDS_WIDEBAND_IQ = False

PLUGIN_DOC = """# Sync Word Slicer (Unique Word Sync)

Correlates against a target Unique Word (Sync Word) in `metadata["bits"]` with bit-error tolerance, locks onto the packet boundary at the first valid occurrence, and slices the payload.

### Features
* **Bit-Error Tolerance**: Matches even with bit flips (default `min_match_pct = 90.0%`, e.g. allows 1 bit flip in a 16-bit word).
* **Payload Slicing**: Strips the preamble and the sync word itself, setting `metadata["bits"]` to the payload following the UW.
* **Full Pre-State Preservation**: Saves the original un-sliced bitstream to `metadata["bits_pre_sync"]`.
* **Polarity Detection**: Optionally tests for bitwise inverted sync words (for $180^\\circ$ phase ambiguity resolution).

### Parameters
* **Sync Word (Hex)** (`uw_hex`): Target sync word in hex, e.g. `0x7E76`, `0xD391`, `0x2DD4`.
* **Min Match Accuracy (%)** (`min_match_pct`): Minimum bit match percentage required to lock sync (default 90.0%).
* **Max Search Depth (bits)** (`max_search_bits`): Search window from start of burst in bits (`0` = search entire burst).
* **Allow Inverted Polarity** (`allow_inverted`): Also detect $180^\\circ$ inverted sync words.

### Output Metadata
* `metadata["bits_pre_sync"]`: Original bitstream before slicing
* `metadata["bits"]`: Sliced payload bitstream after the sync word
* `metadata["hex"]`: Hex formatted payload
* `metadata["num_bits"]`: Payload bit count
* `metadata["uw_found"]`: `True` if sync locked, `False` otherwise
* `metadata["uw_index"]`: Bit index of the sync word start
* `metadata["uw_hex_received"]`: Hex representation of the received sync word window
* `metadata["uw_match_pct"]`: Exact bit match percentage
* `metadata["uw_bit_errors"]`: Number of bit mismatches
* `metadata["uw_polarity"]`: `"normal"` or `"inverted"`
"""

PLUGIN_PARAMS = {
    "uw_hex": {
        "type": "str",
        "default": "0x7E76",
        "label": "Sync Word (Hex)",
        "tooltip": "Target sync word in hex, e.g. 0x7E76, 0xD391, 0x2DD4, 0xAAAA.",
    },
    "min_match_pct": {
        "type": "float",
        "default": 90.0,
        "label": "Min Match Accuracy (%)",
        "tooltip": "Minimum bit match percentage required to lock sync (e.g. 90% allows 1 bit flip in a 16-bit sync word).",
    },
    "max_search_bits": {
        "type": "int",
        "default": 512,
        "label": "Max Search Depth (bits)",
        "tooltip": "Maximum number of bits from burst start to search for sync (0 = search entire burst).",
    },
    "allow_inverted": {
        "type": "bool",
        "default": True,
        "label": "Allow Inverted Polarity",
        "tooltip": "Also check for bitwise-inverted sync word (resolves 180° BPSK/FSK phase ambiguity).",
    },
}


def _hex_to_bits(hex_str: str) -> np.ndarray:
    """Convert hex string (e.g. '0x7E76' or 'D3 91') to 1D uint8 array."""
    s = str(hex_str).strip()
    s = re.sub(r"^0[xX]", "", s)
    if re.search(r"[^0-9a-fA-F\s,._-]", s):
        return np.empty(0, dtype=np.uint8)
    cleaned = re.sub(r"[^0-9a-fA-F]", "", s)
    if not cleaned:
        return np.empty(0, dtype=np.uint8)
    if len(cleaned) % 2 != 0:
        cleaned = "0" + cleaned
    raw_bytes = bytes.fromhex(cleaned)
    bits = []
    for b in raw_bytes:
        for s_idx in range(7, -1, -1):
            bits.append((b >> s_idx) & 1)
    return np.asarray(bits, dtype=np.uint8)


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
        result.warning("No Rect overlays found in active scope.", title="Sync Word Slicer")
        return result

    uw_hex          = str(info.params.get("uw_hex", "0x7E76")).strip()
    min_match_pct   = float(info.params.get("min_match_pct", 90.0))
    max_search_bits = int(info.params.get("max_search_bits", 512))
    allow_inverted  = bool(info.params.get("allow_inverted", True))

    uw_bits = _hex_to_bits(uw_hex)
    if len(uw_bits) == 0:
        result.log(f"Invalid or empty sync word hex: {uw_hex!r}")
        result.error(
            f"Invalid or empty sync word hex: {uw_hex!r}.\n"
            "Please specify a valid hexadecimal string (e.g. 0x7E76).",
            title="Sync Word Slicer",
        )
        return result

    L = len(uw_bits)
    min_matching_bits = int(np.ceil((min_match_pct / 100.0) * L))
    inv_uw_bits = 1 - uw_bits if allow_inverted else None

    synced_count = 0
    bursts_with_bits = 0
    total = len(target_overlays)

    for idx, ov in enumerate(target_overlays):
        if info.is_cancelled():
            break

        info.progress(int((idx / total) * 100), f"Slicing sync word {idx + 1}/{total}…")

        meta = ov.metadata or {}
        raw_bits = meta.get("bits")
        bits = _parse_bits(raw_bits)
        if bits is not None and len(bits) > 0:
            bursts_with_bits += 1
        if bits is None or len(bits) < L:
            continue

        search_limit = len(bits) if max_search_bits <= 0 else min(len(bits), max_search_bits)
        if search_limit < L:
            search_limit = len(bits)

        # Sliding search for the FIRST matching window
        found_idx = -1
        found_polarity = "normal"
        found_errors = 0
        found_match_pct = 0.0

        for i in range(0, search_limit - L + 1):
            window = bits[i : i + L]
            matches_normal = int(np.sum(window == uw_bits))
            if matches_normal >= min_matching_bits:
                found_idx = i
                found_polarity = "normal"
                found_errors = L - matches_normal
                found_match_pct = (matches_normal / float(L)) * 100.0
                break

            if allow_inverted and inv_uw_bits is not None:
                matches_inv = int(np.sum(window == inv_uw_bits))
                if matches_inv >= min_matching_bits:
                    found_idx = i
                    found_polarity = "inverted"
                    found_errors = L - matches_inv
                    found_match_pct = (matches_inv / float(L)) * 100.0
                    break

        new_meta = copy.deepcopy(meta)
        new_meta["bits_pre_sync"] = _bits_to_str(bits)

        if found_idx != -1:
            rx_window = bits[found_idx : found_idx + L]
            if found_polarity == "inverted":
                # Invert entire stream to resolve 180° ambiguity
                bits = 1 - bits
                rx_window = bits[found_idx : found_idx + L]

            # Slice payload bits starting immediately after the Unique Word
            payload_bits = bits[found_idx + L :]
            rx_hex = _bits_to_hex(rx_window).replace(" ", "")

            new_meta.update({
                "bits":             _bits_to_str(payload_bits),
                "hex":              _bits_to_hex(payload_bits),
                "num_bits":         len(payload_bits),
                "uw_found":         True,
                "uw_index":         int(found_idx),
                "uw_hex_received":  f"0x{rx_hex}",
                "uw_match_pct":     round(found_match_pct, 2),
                "uw_bit_errors":    int(found_errors),
                "uw_polarity":      found_polarity,
            })

            # Update display and hover strings
            base_label = (getattr(ov, "display_str", "") or "").split(" [Sync")[0].strip()
            if not base_label:
                base_label = f"Burst #{idx + 1}"
            new_label = f"{base_label} [Sync: 0x{rx_hex} ({found_match_pct:.0f}%)]"

            base_hover = (getattr(ov, "hover_str", "") or "").strip()
            kept_lines = [ln for ln in base_hover.splitlines() if not ln.startswith("Sync:")]
            sync_line = (
                f"Sync: Locked @ bit {found_idx} (0x{rx_hex}, {found_match_pct:.1f}% match, "
                f"{found_errors} err, {found_polarity}) | {len(payload_bits)} payload bits"
            )
            kept_lines.append(sync_line)
            updated_hover = format_hover_bits(
                "\n".join(kept_lines),
                payload_bits,
                hex_str=new_meta.get("hex"),
            )

            result.update(
                ov.id,
                display_str=new_label,
                hover_str=updated_hover,
                metadata=new_meta,
            )
            synced_count += 1
        else:
            new_meta["uw_found"] = False
            base_hover = (getattr(ov, "hover_str", "") or "").strip()
            kept_lines = [ln for ln in base_hover.splitlines() if not ln.startswith("Sync:")]
            kept_lines.append(f"Sync: No sync word {uw_hex} match found")
            result.update(ov.id, hover_str="\n".join(kept_lines), metadata=new_meta)

    result.log(f"Sync Word Slicer: Synchronized {synced_count}/{total} burst(s).")
    if bursts_with_bits == 0 and total > 0:
        result.warning(
            "None of the candidate bursts contain demodulated 'bits' in metadata.\n\n"
            "Run a demodulator plugin (such as FSK Demodulator) before Sync Word Slicer.",
            title="Sync Word Slicer",
        )
    elif synced_count == 0 and total > 0:
        result.warning(
            f"Sync word {uw_hex} was not found in any of the {total} burst(s).\n\n"
            "Possible causes:\n"
            f"• Preceding demodulator produced bit errors.\n"
            f"• Min Match Accuracy ({min_match_pct:.0f}%) is too high.\n"
            f"• Max Search Depth ({max_search_bits} bits) did not cover the preamble.",
            title="Sync Word Slicer",
        )
    info.progress(100, "Done")
    return result

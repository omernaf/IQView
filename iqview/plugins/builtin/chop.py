"""iqview/plugins/builtin/chop.py

Built-in IQView Plugin: Chop.

Skips M leading bits, then removes the next N bits from metadata["bits"].
"""

from __future__ import annotations

import copy
from typing import Any, Optional

import numpy as np

from iqview import PluginResult, PluginContext, format_hover_bits
from iqview.overlays import OverlayShape


PLUGIN_NAME              = "Chop"
PLUGIN_DESCRIPTION       = (
    "Skips M leading bits, then removes the next N bits from each burst bitstream."
)
PLUGIN_CATEGORY          = "Bit Manipulation"
PLUGIN_NEEDS_WIDEBAND_IQ = False

PLUGIN_DOC = """# Chop

Removes a run of bits from `metadata["bits"]`. It leaves the first $M$ bits in place, deletes the next $N$ bits, and keeps everything after that.

$$[b_0, \\dots, b_{M-1},\\, b_M, \\dots, b_{M+N-1},\\, b_{M+N}, \\dots] \\longrightarrow [b_0, \\dots, b_{M-1},\\, b_{M+N}, \\dots]$$

With the default offset $M = 0$, the first $N$ bits are removed. If fewer than $N$ bits remain after the offset, those remaining bits are removed. A burst whose offset is past the last bit is left unchanged.

### Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `length` | `int` | `8` | Number of bits to remove ($N$). |
| `offset` | `int` | `0` | Number of leading bits to leave in place before the removal ($M$). |

### Output Metadata
* `metadata["bits_pre_chop"]`: Bits before the removal
* `metadata["bits"]`: Bits that remain
* `metadata["hex"]`: Hex of the remaining bits
* `metadata["num_bits"]`: Length of the remaining bitstream
* `metadata["chop_offset"]`: Offset $M$ that was applied
* `metadata["chop_length"]`: Requested removal length $N$
* `metadata["chop_removed"]`: Number of bits actually removed
"""

PLUGIN_PARAMS = {
    "length": {
        "type": "int",
        "default": 8,
        "label": "Length N (bits)",
        "tooltip": "Number of bits to remove after the offset.",
    },
    "offset": {
        "type": "int",
        "default": 0,
        "label": "Offset M (bits)",
        "tooltip": "Number of leading bits to leave in place. 0 removes the first N bits.",
    },
}


def _parse_bits(raw: Any) -> Optional[np.ndarray]:
    """Parse 'bits' from overlay metadata into a 1D uint8 bit array."""
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
    """Format a bit array as a binary string."""
    return "".join(str(int(b)) for b in bits)


def _bits_to_hex(bits: np.ndarray) -> str:
    """Convert a bit array to a formatted uppercase hex string."""
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


def _chop_bits(bits: np.ndarray, offset: int, length: int) -> tuple[np.ndarray, int]:
    """Drop `length` bits starting at `offset`. Returns the remainder and how many were removed."""
    start = min(max(0, int(offset)), len(bits))
    end = min(start + max(0, int(length)), len(bits))
    removed = end - start
    if removed <= 0:
        return np.asarray(bits, dtype=np.uint8), 0
    kept = np.concatenate([bits[:start], bits[end:]]).astype(np.uint8, copy=False)
    return kept, removed


def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()

    target_overlays = [
        o for o in info.overlays
        if o.shape == OverlayShape.RECT or (hasattr(o, "_shape_name") and o._shape_name() == "RECT")
    ]
    if not target_overlays:
        result.log("No Rect overlays found in active scope.")
        result.warning("No Rect overlays found in active scope.", title="Chop")
        return result

    length = int(info.params.get("length", 8))
    offset = int(info.params.get("offset", 0))
    if length < 1:
        result.log("Chop length N must be at least 1.")
        result.warning("Chop length N must be at least 1 bit.", title="Chop")
        return result
    if offset < 0:
        offset = 0

    chopped_count = 0
    short_count = 0
    past_end_count = 0
    total = len(target_overlays)

    for idx, ov in enumerate(target_overlays):
        if info.is_cancelled():
            break

        info.progress(int((idx / total) * 100), f"Chopping bits {idx + 1}/{total}…")

        meta = ov.metadata or {}
        bits = _parse_bits(meta.get("bits"))
        if bits is None or len(bits) == 0:
            continue

        out_bits, removed = _chop_bits(bits, offset, length)
        if removed <= 0:
            past_end_count += 1
            continue
        if removed < length:
            short_count += 1

        new_meta = copy.deepcopy(meta)
        new_meta.update({
            "bits_pre_chop": _bits_to_str(bits),
            "bits":          _bits_to_str(out_bits),
            "hex":           _bits_to_hex(out_bits),
            "num_bits":      len(out_bits),
            "chop_offset":   offset,
            "chop_length":   length,
            "chop_removed":  removed,
        })

        base_label = (getattr(ov, "display_str", "") or "").split(" [Chop")[0].strip()
        if not base_label:
            base_label = f"Burst #{idx + 1}"
        if offset:
            new_label = f"{base_label} [Chop @{offset} -{removed}]"
        else:
            new_label = f"{base_label} [Chop -{removed}]"

        base_hover = (getattr(ov, "hover_str", "") or "").strip()
        kept_lines = [ln for ln in base_hover.splitlines() if not ln.startswith("Chop:")]
        kept_lines.append(
            f"Chop: skipped {offset} bits, removed {removed} of {length}"
        )
        updated_hover = format_hover_bits(
            "\n".join(kept_lines),
            out_bits,
            hex_str=new_meta.get("hex"),
        )

        result.update(
            ov.id,
            display_str=new_label,
            hover_str=updated_hover,
            metadata=new_meta,
        )
        chopped_count += 1

    result.log(
        f"Chop: removed {length} bits at offset {offset} on {chopped_count}/{total} burst(s)."
    )
    if chopped_count == 0 and past_end_count == 0 and total > 0:
        result.warning(
            "None of the candidate bursts contain demodulated 'bits' in metadata.\n\n"
            "Run a demodulator plugin before Chop.",
            title="Chop",
        )
    elif past_end_count > 0 and chopped_count == 0:
        result.warning(
            f"Offset {offset} is past the end of the bitstream on every burst.",
            title="Chop",
        )
    elif short_count > 0:
        result.log(
            f"Chop: {short_count} burst(s) had fewer than {length} bits left after the offset."
        )
    info.progress(100, "Done")
    return result

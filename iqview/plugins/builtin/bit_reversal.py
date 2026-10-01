"""iqview/plugins/builtin/bit_reversal.py

Built-in IQView Plugin: Bit Reversal (rev8).

Reverses the bit order within each chunk of N bits (defaulting to 8 bits / byte-level endianness).
Often needed when a transmitter serializes bytes LSB-first but the receiver decodes MSB-first.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
import numpy as np

from iqview import PluginResult, PluginContext
from iqview.overlays import OverlayShape


PLUGIN_NAME              = "Bit Reversal (rev8)"
PLUGIN_DESCRIPTION       = (
    "Reverses the bit order within each chunk of N bits (default N=8 for byte endianness, "
    "or 4 for nibble, 16 for word) to convert between LSB-first and MSB-first bit order."
)
PLUGIN_CATEGORY          = "Bit Manipulation"
PLUGIN_NEEDS_WIDEBAND_IQ = False

PLUGIN_DOC = """# Bit Reversal (rev8)

Reverses the bit order within each chunk of $N$ bits (default $N=8$, byte-level reflection).

### Operation
For each chunk of $N$ bits:
$$[b_0, b_1, \\dots, b_{N-1}] \\longrightarrow [b_{N-1}, \\dots, b_1, b_0]$$

Trailing residual bits ($< N$) at the end of the packet are preserved intact.

### Parameters
* **Chunk Size (bits)** (`chunk_size`): Number of bits per reversal block (default `8` for byte, `4` for nibble, `16` for 16-bit word).

### Output Metadata
* `metadata["bits_pre_rev8"]`: Bits before reversal
* `metadata["bits"]`: Bit-reversed bitstream
* `metadata["hex"]`: Hex formatted output
* `metadata["rev8_chunk_size"]`: Chunk size used
"""

PLUGIN_PARAMS = {
    "chunk_size": {
        "type": "choice",
        "default": 8,
        "choices": [8, 4, 16, 32],
        "label": "Chunk Size (bits)",
        "tooltip": "Number of bits per reversal block (8 for byte, 4 for nibble, 16 for word, 32 for dword).",
    },
}


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


def _rev_bits(bits: np.ndarray, chunk_size: int = 8) -> np.ndarray:
    """Reverse bit order within each chunk of chunk_size bits."""
    n_bits = len(bits)
    if n_bits == 0:
        return np.empty(0, dtype=np.uint8)
    out_chunks = []
    for i in range(0, n_bits, chunk_size):
        chunk = bits[i : i + chunk_size]
        if len(chunk) == chunk_size:
            out_chunks.append(chunk[::-1])
        else:
            out_chunks.append(chunk)
    return np.concatenate(out_chunks).astype(np.uint8)


def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()

    target_overlays = [
        o for o in info.overlays
        if o.shape == OverlayShape.RECT or (hasattr(o, "_shape_name") and o._shape_name() == "RECT")
    ]
    if not target_overlays:
        result.log("No Rect overlays found in active scope.")
        return result

    chunk_size = max(1, int(info.params.get("chunk_size", 8)))
    reversed_count = 0
    total = len(target_overlays)

    for idx, ov in enumerate(target_overlays):
        if info.is_cancelled():
            break

        info.progress(int((idx / total) * 100), f"Reversing bits {idx + 1}/{total}…")

        meta = ov.metadata or {}
        raw_bits = meta.get("bits")
        bits = _parse_bits(raw_bits)
        if bits is None or len(bits) == 0:
            continue

        out_bits = _rev_bits(bits, chunk_size)

        new_meta = copy.deepcopy(meta)
        new_meta.update({
            "bits_pre_rev8":      _bits_to_str(bits),
            "bits":               _bits_to_str(out_bits),
            "hex":                _bits_to_hex(out_bits),
            "num_bits":           len(out_bits),
            "rev8_chunk_size":    chunk_size,
        })

        base_label = (getattr(ov, "display_str", "") or "").split(" [rev")[0].strip()
        if not base_label:
            base_label = f"Burst #{idx + 1}"
        new_label = f"{base_label} [rev{chunk_size}]"

        base_hover = (getattr(ov, "hover_str", "") or "").strip()
        kept_lines = [ln for ln in base_hover.splitlines() if not ln.startswith("Rev:")]
        kept_lines.append(f"Rev: Flipped {len(out_bits)} bits in {chunk_size}-bit chunks")

        result.update(
            ov.id,
            display_str=new_label,
            hover_str="\n".join(kept_lines),
            metadata=new_meta,
        )
        reversed_count += 1

    result.log(f"Bit Reversal: Processed {reversed_count}/{total} burst(s) (chunk_size={chunk_size}).")
    info.progress(100, "Done")
    return result

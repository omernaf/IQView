"""iqview/plugins/builtin/diff_decoder.py

Built-in IQView Plugin: Differential Decoder.

Decodes transition-encoded bitstreams (NRZ-M and NRZ-S).
In differential encoding, a bit transition indicates '1' and no change indicates '0'.
This plugin performs the inverse decoding: b[n] = s[n] ^ s[n-1], with a configurable
initial reference bit s[-1] (defaulting to 0).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
import numpy as np

from iqview import PluginResult, PluginContext
from iqview.overlays import OverlayShape


PLUGIN_NAME              = "Differential Decoder"
PLUGIN_DESCRIPTION       = (
    "Decodes transition-encoded bitstreams (NRZ-M / NRZ-S), mapping bit flips to '1' "
    "and constant levels to '0' with a configurable initial reference bit."
)
PLUGIN_CATEGORY          = "Bit Manipulation"
PLUGIN_NEEDS_WIDEBAND_IQ = False

PLUGIN_DOC = """# Differential Decoder

Decodes transition-encoded bitstreams (commonly used in PSK, FSK, and telemetry to resolve carrier phase ambiguities).

### Operation
In standard differential encoding (NRZ-M):
* A bit flip between successive symbols represents `'1'`.
* Constant symbol level between successive symbols represents `'0'`.

The differential decoder computes:
$$b_0 = s_0 \\oplus \\text{init\\_bit}$$
$$b_n = s_n \\oplus s_{n-1} \\quad \\text{for } n \\ge 1$$

In NRZ-S mode, the logic is inverted ($b_n = \\neg(s_n \\oplus s_{n-1})$).

### Parameters
* **Decoding Mode** (`mode`): `"NRZ-M (1 on bit change)"` (default) or `"NRZ-S (0 on bit change)"`.
* **Initial Reference Bit** (`init_bit`): Assumed state before the first bit (`0` or `1`, default `0`).

### Output Metadata
* `metadata["bits_pre_diff"]`: Original bits before differential decoding
* `metadata["bits"]`: Differentially decoded bitstream
* `metadata["hex"]`: Hex formatted output
* `metadata["diff_mode"]`: Selected mode
* `metadata["diff_init"]`: Initial bit value used
"""

PLUGIN_PARAMS = {
    "mode": {
        "type": "choice",
        "default": "NRZ-M (1 on bit change)",
        "choices": [
            "NRZ-M (1 on bit change)",
            "NRZ-S (0 on bit change)",
        ],
        "label": "Decoding Mode",
        "tooltip": "NRZ-M: 1 on bit transition, 0 on same. NRZ-S: 0 on transition, 1 on same.",
    },
    "init_bit": {
        "type": "choice",
        "default": 0,
        "choices": [0, 1],
        "label": "Initial Reference Bit",
        "tooltip": "Assumed reference bit state before the first symbol (0 or 1).",
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


def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
    result = PluginResult()

    target_overlays = [
        o for o in info.overlays
        if o.shape == OverlayShape.RECT or (hasattr(o, "_shape_name") and o._shape_name() == "RECT")
    ]
    if not target_overlays:
        result.log("No Rect overlays found in active scope.")
        return result

    mode_param = str(info.params.get("mode", "NRZ-M (1 on bit change)"))
    is_nrz_s   = "NRZ-S" in mode_param.upper()
    init_bit   = 1 if int(info.params.get("init_bit", 0)) != 0 else 0

    mode_label = "NRZ-S" if is_nrz_s else "NRZ-M"
    decoded_count = 0
    total = len(target_overlays)

    for idx, ov in enumerate(target_overlays):
        if info.is_cancelled():
            break

        info.progress(int((idx / total) * 100), f"Differential decoding {idx + 1}/{total}…")

        meta = ov.metadata or {}
        raw_bits = meta.get("bits")
        bits = _parse_bits(raw_bits)
        if bits is None or len(bits) == 0:
            continue

        # Differential decoding: b[n] = s[n] ^ s[n-1]
        prev = np.concatenate([[init_bit], bits[:-1]])
        if is_nrz_s:
            out_bits = (1 - (bits ^ prev)).astype(np.uint8)
        else:
            out_bits = (bits ^ prev).astype(np.uint8)

        new_meta = copy.deepcopy(meta)
        new_meta.update({
            "bits_pre_diff": _bits_to_str(bits),
            "bits":          _bits_to_str(out_bits),
            "hex":           _bits_to_hex(out_bits),
            "num_bits":      len(out_bits),
            "diff_mode":     mode_label,
            "diff_init":     init_bit,
        })

        base_label = (getattr(ov, "display_str", "") or "").split(" [Diff")[0].strip()
        if not base_label:
            base_label = f"Burst #{idx + 1}"
        new_label = f"{base_label} [Diff: {mode_label}]"

        base_hover = (getattr(ov, "hover_str", "") or "").strip()
        kept_lines = [ln for ln in base_hover.splitlines() if not ln.startswith("Diff:")]
        kept_lines.append(f"Diff: Decoded {len(out_bits)} bits ({mode_label}, init={init_bit})")

        result.update(
            ov.id,
            display_str=new_label,
            hover_str="\n".join(kept_lines),
            metadata=new_meta,
        )
        decoded_count += 1

    result.log(f"Differential Decoder: Decoded {decoded_count}/{total} burst(s) ({mode_label}).")
    info.progress(100, "Done")
    return result

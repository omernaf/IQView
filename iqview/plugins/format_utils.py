"""iqview/plugins/format_utils.py

String and metadata formatting utilities for IQView plugins and overlays.
"""

from __future__ import annotations

from typing import Any, Optional


def format_hover_bits(
    base_hover: str,
    bits: Any,
    hex_str: Optional[str] = None,
    max_hover_bits: int = 64,
) -> str:
    """
    Update or append 'Bits: ...' and 'Hex: ...' preview lines in an overlay hover text.

    Preserves existing metadata lines (FSK, Sync, FEC, CRC status, etc.)
    while replacing any previous 'Bits:' or 'Hex:' lines with the latest bit values.

    Parameters
    ----------
    base_hover : str
        Existing hover text of the overlay.
    bits : str, bytes, sequence of int, or numpy array
        Bit sequence to format.
    hex_str : str, optional
        Hex representation of the bits. If omitted, automatically derived.
    max_hover_bits : int
        Maximum number of bits to display before truncating with count.
    """
    if bits is None:
        return base_hover or ""

    if isinstance(bits, str):
        bits_str = "".join(c for c in bits if c in "01")
    elif isinstance(bits, (bytes, bytearray)):
        bits_str = "".join(f"{b:08b}" for b in bits)
    elif hasattr(bits, "__iter__"):
        bits_str = "".join("1" if int(b) else "0" for b in bits)
    else:
        bits_str = str(bits)

    n_bits = len(bits_str)
    if n_bits == 0:
        bits_preview = "(empty)"
    elif n_bits <= max_hover_bits:
        bits_preview = bits_str
    else:
        bits_preview = f"{bits_str[:max_hover_bits]}... ({n_bits} bits)"

    if hex_str is None and n_bits > 0:
        pad = (4 - (n_bits % 4)) % 4
        padded = bits_str + ("0" * pad)
        hex_digits = [f"{int(padded[i : i + 4], 2):X}" for i in range(0, len(padded), 4)]
        derived_hex = "".join(hex_digits)
    else:
        derived_hex = str(hex_str).strip().replace(" ", "") if hex_str else ""

    if len(derived_hex) > 42:
        hex_preview = derived_hex[:42] + "..."
    else:
        hex_preview = derived_hex

    raw = (base_hover or "").strip()
    kept_lines = [
        ln for ln in raw.splitlines()
        if not ln.strip().lower().startswith("bits:") and not ln.strip().lower().startswith("hex:")
    ]

    kept_lines.append(f"Bits: {bits_preview}")
    if derived_hex:
        kept_lines.append(f"Hex: {hex_preview}")

    return "\n".join(kept_lines)

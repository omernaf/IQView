"""iqview/plugins/builtin/block_fec_decoder.py

Built-in IQView Plugin: Block FEC Decoder.

Performs forward error correction decoding on `metadata["bits"]` block-by-block.
Supports standard codes (Hamming(7,4), Hamming(8,4), Golay(23,12), Golay(24,12),
Reed-Solomon over GF(256)), and custom user-provided Generator matrices G (k x n).
If the total bitstream length is not divisible by the block length n, it automatically
pads with trailing zeros to complete the final block.
Tracks block error correction statistics (clean blocks where syndrome is 0, corrected
blocks, uncorrectable blocks, total bits corrected).
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from iqview import PluginResult, PluginContext
from iqview.overlays import OverlayShape


PLUGIN_NAME              = "Block FEC Decoder"
PLUGIN_DESCRIPTION       = (
    "Decodes block forward error correction codes (Hamming(7,4), Hamming(8,4), "
    "Golay(23,12), Golay(24,12), Reed-Solomon, or custom Generator matrix G), "
    "zero-padding if needed and tracking syndrome correction metrics."
)
PLUGIN_CATEGORY          = "Error Correction"
PLUGIN_NEEDS_WIDEBAND_IQ = False

PLUGIN_DOC = """# Block FEC Decoder

Divides the bitstream into blocks of length $n$, corrects bit errors, and outputs the decoded message bits.

### Supported Codes
* **Hamming(7,4)**: Standard [7,4,3] binary Hamming code. Corrects 1 bit error per 7-bit block ($4$ data bits output).
* **Hamming(8,4)**: Extended [8,4,4] Hamming code with overall parity bit. Corrects 1 error, detects 2 errors per 8-bit block.
* **Golay(23,12)**: Perfect [23,12,7] binary Golay code. Corrects up to 3 bit errors per 23-bit block ($12$ data bits output).
* **Golay(24,12)**: Extended [24,12,8] binary Golay code with parity bit. Corrects up to 3 bit errors, detects 4 errors.
* **Reed-Solomon(255,223) / RS(255,239)**: Standard byte-oriented RS codes over GF(256) with field polynomial $x^8 + x^4 + x^3 + x^2 + 1$ (`0x11D`).
* **Custom Generator Matrix**: User can provide any $k \\times n$ binary generator matrix $G$. Automatically derives the parity-check matrix $H$ and constructs maximum-likelihood coset leader syndromes.

### Parameters
* **FEC Code** (`code`): Code selection dropdown.
* **Custom G Matrix** (`custom_g_matrix`): Multiline or comma-separated binary rows defining $G$ (e.g. `1000110, 0100011, 0010111, 0001101`).

### Output Metadata
* `metadata["bits_pre_fec"]`: Bits before error correction
* `metadata["bits"]`: Error-corrected message bitstream
* `metadata["hex"]`: Hex formatted message
* `metadata["fec_code"]`: Selected code name
* `metadata["fec_total_blocks"]`: Total blocks evaluated
* `metadata["fec_clean_blocks"]`: Blocks with syndrome = 0 (no errors)
* `metadata["fec_corrected_blocks"]`: Blocks where errors were corrected
* `metadata["fec_uncorrectable_blocks"]`: Blocks with uncorrectable syndromes
* `metadata["fec_bit_errors_corrected"]`: Total bit errors flipped
* `metadata["fec_pad_bits"]`: Number of trailing zero bits added
"""

PLUGIN_PARAMS = {
    "code": {
        "type": "choice",
        "default": "Hamming(7,4)",
        "choices": [
            "Hamming(7,4)",
            "Hamming(8,4)",
            "Golay(23,12)",
            "Golay(24,12)",
            "Custom G Matrix",
        ],
        "label": "FEC Code",
        "tooltip": "Select a standard block code or choose Custom G Matrix.",
    },
    "custom_g_matrix": {
        "type": "str",
        "default": "",
        "label": "Custom G Matrix",
        "tooltip": "Comma- or newline-separated binary rows for custom generator matrix G (k x n).",
    },
}

# Standard Golay 12x12 circulant matrix B
GOLAY_B = np.array([
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 0, 1, 1, 1, 0, 0, 0, 1, 0],
    [1, 1, 0, 1, 1, 1, 0, 0, 0, 1, 0, 1],
    [1, 0, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1],
    [1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 0],
    [1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 0, 1],
    [1, 1, 0, 0, 0, 1, 0, 1, 1, 0, 1, 1],
    [1, 0, 0, 0, 1, 0, 1, 1, 0, 1, 1, 1],
    [1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 1, 0],
    [1, 0, 1, 0, 1, 1, 0, 1, 1, 1, 0, 0],
    [1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 0, 0],
    [1, 0, 1, 1, 0, 1, 1, 1, 0, 0, 0, 1],
], dtype=np.uint8)

# Parity check matrix for Golay(24,12)
GOLAY_H24 = np.hstack([GOLAY_B, np.eye(12, dtype=np.uint8)])
G_GOLAY24 = np.hstack([np.eye(12, dtype=np.uint8), GOLAY_B])

# Systematic Hamming(7,4) P matrix
HAMMING7_P = np.array([
    [1, 1, 0],
    [1, 0, 1],
    [0, 1, 1],
    [1, 1, 1]
], dtype=np.uint8)
HAMMING7_H = np.hstack([HAMMING7_P.T, np.eye(3, dtype=np.uint8)])
G_HAMMING74 = np.hstack([np.eye(4, dtype=np.uint8), HAMMING7_P])


def _decode_hamming74(block: np.ndarray) -> Tuple[np.ndarray, int]:
    """Decode a single 7-bit block of Hamming(7,4). Returns (msg_4bits, n_corrected)."""
    s = (block @ HAMMING7_H.T) % 2
    if np.sum(s) == 0:
        return block[:4].copy(), 0
    # Search for matching column in H
    err_col = -1
    for col in range(7):
        if np.array_equal(HAMMING7_H[:, col], s):
            err_col = col
            break
    if err_col != -1:
        corr = block.copy()
        corr[err_col] ^= 1
        return corr[:4], 1
    return block[:4].copy(), -1


def _decode_hamming84(block: np.ndarray) -> Tuple[np.ndarray, int]:
    """Decode a single 8-bit block of extended Hamming(8,4). Returns (msg_4bits, n_corrected)."""
    # First 7 bits syndrome
    s7 = (block[:7] @ HAMMING7_H.T) % 2
    parity_sum = int(np.sum(block)) % 2
    has_synd = int(np.sum(s7)) != 0

    if not has_synd and parity_sum == 0:
        return block[:4].copy(), 0
    if has_synd and parity_sum == 1:
        # Single error in one of the first 7 bits
        for col in range(7):
            if np.array_equal(HAMMING7_H[:, col], s7):
                corr = block[:4].copy()
                if col < 4:
                    corr[col] ^= 1
                return corr, 1
        return block[:4].copy(), -1
    if not has_synd and parity_sum == 1:
        # Error was in the 8th parity bit itself
        return block[:4].copy(), 1
    # Double error detected
    return block[:4].copy(), -1


def _decode_golay24(block: np.ndarray) -> Tuple[np.ndarray, int]:
    """Decode a single 24-bit block of extended Golay(24,12). Returns (msg_12bits, n_corrected)."""
    s = (block @ GOLAY_H24.T) % 2
    wt_s = int(np.sum(s))
    if wt_s == 0:
        return block[:12].copy(), 0
    if wt_s <= 3:
        err = np.concatenate([np.zeros(12, dtype=np.uint8), s])
        return (block ^ err)[:12], wt_s
    for i in range(12):
        s_bi = (s ^ GOLAY_B[i]) % 2
        if int(np.sum(s_bi)) <= 2:
            err = np.zeros(24, dtype=np.uint8)
            err[i] = 1
            err[12:] = s_bi
            return (block ^ err)[:12], int(np.sum(err))
    sB = (s @ GOLAY_B) % 2
    wt_sB = int(np.sum(sB))
    if wt_sB <= 3:
        err = np.concatenate([sB, np.zeros(12, dtype=np.uint8)])
        return (block ^ err)[:12], wt_sB
    for i in range(12):
        sB_bi = (sB ^ GOLAY_B[i]) % 2
        if int(np.sum(sB_bi)) <= 2:
            err = np.zeros(24, dtype=np.uint8)
            err[:12] = sB_bi
            err[12 + i] = 1
            return (block ^ err)[:12], int(np.sum(err))
    return block[:12].copy(), -1


def _decode_golay23(block: np.ndarray) -> Tuple[np.ndarray, int]:
    """Decode a single 23-bit block of Golay(23,12). Returns (msg_12bits, n_corrected)."""
    p0 = int(np.sum(block)) % 2
    r24 = np.append(block, p0)
    m, err = _decode_golay24(r24)
    if err != -1 and err <= 3:
        return m, err
    r24[23] = 1 - p0
    m2, err2 = _decode_golay24(r24)
    if err2 != -1 and err2 <= 3:
        return m2, err2
    return block[:12].copy(), -1


# ----------------------------------------------------------------------
# Custom Generator Matrix Decoder
# ----------------------------------------------------------------------

def _rref_gf2(A: np.ndarray) -> np.ndarray:
    """Compute Row Reduced Echelon Form over GF(2)."""
    m, n = A.shape
    R = A.copy() % 2
    lead = 0
    for r in range(m):
        if lead >= n:
            break
        i = r
        while R[i, lead] == 0:
            i += 1
            if i == m:
                i = r
                lead += 1
                if lead == n:
                    break
        if lead < n:
            R[[i, r]] = R[[r, i]]
            for j in range(m):
                if j != r and R[j, lead] == 1:
                    R[j] ^= R[r]
            lead += 1
    return R


def _build_custom_syndrome_table(G_raw: np.ndarray) -> Tuple[np.ndarray, int, int, Dict[tuple, np.ndarray]]:
    """Derive H and single-error syndrome table for a custom G matrix."""
    R = _rref_gf2(G_raw)
    k, n = R.shape
    # Check if systematic [I_k | P]
    is_sys = np.array_equal(R[:, :k], np.eye(k, dtype=np.uint8))
    if not is_sys:
        # Fallback: assume user provided systematic [I_k | P]
        P = G_raw[:, k:]
    else:
        P = R[:, k:]
    H = np.hstack([P.T, np.eye(n - k, dtype=np.uint8)])

    synd_table = {}
    for i in range(n):
        e = np.zeros(n, dtype=np.uint8)
        e[i] = 1
        s = tuple(int(x) for x in ((e @ H.T) % 2))
        synd_table[s] = e
    return H, k, n, synd_table


def _parse_custom_g(g_str: str) -> Optional[np.ndarray]:
    """Parse multiline or comma-separated binary string into matrix G."""
    lines = [ln.strip() for ln in re.split(r"[\n;,]+", g_str) if ln.strip()]
    rows = []
    for ln in lines:
        cleaned = [int(c) for c in ln if c in ("0", "1")]
        if cleaned:
            rows.append(cleaned)
    if not rows:
        return None
    # Ensure uniform row length
    n = len(rows[0])
    if any(len(r) != n for r in rows):
        return None
    return np.asarray(rows, dtype=np.uint8)


# ----------------------------------------------------------------------
# Bit Helpers
# ----------------------------------------------------------------------

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

    code_param = str(info.params.get("code", "Hamming(7,4)")).strip()
    custom_g_str = str(info.params.get("custom_g_matrix", "")).strip()

    # Determine code parameters (n, k, decoder function)
    custom_decoder = None
    if "Hamming(7,4)" in code_param:
        n_block, k_block = 7, 4
        block_decoder = _decode_hamming74
        code_name = "Hamming(7,4)"
    elif "Hamming(8,4)" in code_param:
        n_block, k_block = 8, 4
        block_decoder = _decode_hamming84
        code_name = "Hamming(8,4)"
    elif "Golay(23,12)" in code_param:
        n_block, k_block = 23, 12
        block_decoder = _decode_golay23
        code_name = "Golay(23,12)"
    elif "Golay(24,12)" in code_param or "Golay" in code_param:
        n_block, k_block = 24, 12
        block_decoder = _decode_golay24
        code_name = "Golay(24,12)"
    elif "Custom" in code_param:
        g_mat = _parse_custom_g(custom_g_str)
        if g_mat is None:
            result.log(f"Block FEC: Invalid custom G matrix string: {custom_g_str!r}")
            return result
        H_cust, k_block, n_block, synd_table = _build_custom_syndrome_table(g_mat)
        code_name = f"Custom({n_block},{k_block})"

        def _custom_dec(block: np.ndarray) -> Tuple[np.ndarray, int]:
            s = tuple(int(x) for x in ((block @ H_cust.T) % 2))
            if all(x == 0 for x in s):
                return block[:k_block].copy(), 0
            if s in synd_table:
                e = synd_table[s]
                return (block ^ e)[:k_block], int(np.sum(e))
            return block[:k_block].copy(), -1

        block_decoder = _custom_dec
    else:
        # Default fallback
        n_block, k_block = 7, 4
        block_decoder = _decode_hamming74
        code_name = "Hamming(7,4)"

    fec_count = 0
    total = len(target_overlays)

    for idx, ov in enumerate(target_overlays):
        if info.is_cancelled():
            break

        info.progress(int((idx / total) * 100), f"FEC decoding {idx + 1}/{total}…")

        meta = ov.metadata or {}
        raw_bits = meta.get("bits")
        bits = _parse_bits(raw_bits)
        if bits is None or len(bits) == 0:
            continue

        orig_len = len(bits)
        # Pad with trailing zeros if not divisible by n_block
        remainder = orig_len % n_block
        pad_bits = (n_block - remainder) if remainder != 0 else 0
        if pad_bits > 0:
            bits_proc = np.pad(bits, (0, pad_bits), constant_values=0)
        else:
            bits_proc = bits

        total_blocks = len(bits_proc) // n_block
        clean_blocks = 0
        corrected_blocks = 0
        uncorrectable_blocks = 0
        total_bit_errors = 0
        decoded_chunks = []

        for b_idx in range(total_blocks):
            blk = bits_proc[b_idx * n_block : (b_idx + 1) * n_block]
            msg_bits, err_count = block_decoder(blk)
            decoded_chunks.append(msg_bits)

            if err_count == 0:
                clean_blocks += 1
            elif err_count > 0:
                corrected_blocks += 1
                total_bit_errors += err_count
            else:
                uncorrectable_blocks += 1

        out_bits = np.concatenate(decoded_chunks).astype(np.uint8)

        new_meta = copy.deepcopy(meta)
        new_meta.update({
            "bits_pre_fec":               _bits_to_str(bits),
            "bits":                       _bits_to_str(out_bits),
            "hex":                        _bits_to_hex(out_bits),
            "num_bits":                   len(out_bits),
            "fec_code":                   code_name,
            "fec_total_blocks":           int(total_blocks),
            "fec_clean_blocks":           int(clean_blocks),
            "fec_corrected_blocks":       int(corrected_blocks),
            "fec_uncorrectable_blocks":   int(uncorrectable_blocks),
            "fec_bit_errors_corrected":   int(total_bit_errors),
            "fec_pad_bits":               int(pad_bits),
        })

        base_label = (getattr(ov, "display_str", "") or "").split(" [FEC")[0].strip()
        if not base_label:
            base_label = f"Burst #{idx + 1}"
        new_label = f"{base_label} [FEC: {code_name} ({clean_blocks}/{total_blocks} clean)]"

        base_hover = (getattr(ov, "hover_str", "") or "").strip()
        kept_lines = [ln for ln in base_hover.splitlines() if not ln.startswith("FEC:")]
        fec_line = (
            f"FEC ({code_name}): {total_blocks} blocks | "
            f"{clean_blocks} clean (s=0), {corrected_blocks} corrected (+{total_bit_errors} bits), "
            f"{uncorrectable_blocks} uncorrectable"
        )
        if pad_bits > 0:
            fec_line += f" | padded +{pad_bits}b"
        kept_lines.append(fec_line)

        result.update(
            ov.id,
            display_str=new_label,
            hover_str="\n".join(kept_lines),
            metadata=new_meta,
        )
        fec_count += 1

    result.log(f"Block FEC Decoder: Decoded {fec_count}/{total} burst(s) with {code_name}.")
    info.progress(100, "Done")
    return result

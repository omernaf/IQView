---
name: iqview-io-formats
description: >-
  File formats, binary IQ loaders, audio decoding, Tektronix .r3f, Keysight .mat,
  stdin streaming, byte range slicing, and export routines in IQView. Use when adding
  or debugging file ingestion, hardware formats, or export pipelines.
---

# IQView File Formats, I/O & Streaming Skill

This skill documents file loaders, hardware formats, audio decoding, stdin streaming, byte slicing, and export routines in IQView.

---

## 1. Supported Formats Matrix

| Extension | Format / Type | Description / Handling |
| :--- | :--- | :--- |
| `.32fc`, `.cf32`, `.iq`, `.bin` | `complex64` | Standard 32-bit floating-point interleaved IQ (4-byte float I, 4-byte float Q). |
| `.16tc`, `.cs16`, `.16sc` | `int16` | Interleaved 16-bit signed integer IQ. Normalized automatically to $[-1.0, 1.0]$. |
| `.32f` | `float32` | Real-valued 32-bit floating point. |
| `.64fc` | `complex128` | Double-precision complex IQ. |
| `.r3f` | Tektronix RSA | 16 KB header frame parsing ($F_c, F_{s,\text{real}}, F_{c,\text{IF}}$). Vectorized baseband DDC + decimation. |
| `.mat` | Keysight / MATLAB | Requires variables `Y` (complex array), `XDelta` ($1/f_s$), and `InputCenter` ($f_c$). Supports `.mat.overlays` sidecars. |
| `.wav`, `.flac`, `.ogg`, `.aiff`, etc. | `audio` / `caudio` | Standard audio downmixed to mono $[-1.0, 1.0]$ (`-t aud`) or interleaved mono deinterleaved to complex IQ (`-t caudio`). |

---

## 2. Byte Slicing Safety Guidelines

CLI flags `--start-byte`, `--stop-byte`, and `--bytes START:STOP` permit reading arbitrary file slices.

> [!CRITICAL]
> Offsets are arbitrary byte indices and might not align to sample boundaries (e.g. 17-byte header offset on 8-byte `complex64` data).
>
> **Truncate trailing partial bytes before calling `np.frombuffer`**:
> ```python
> item_bytes = np.dtype(dtype).itemsize * (2 if is_complex else 1)
> valid_bytes = (len(raw_slice) // item_bytes) * item_bytes
> aligned_buffer = raw_slice[:valid_bytes]
> samples = np.frombuffer(aligned_buffer, dtype=dtype)
> ```
> Never pass unaligned buffer slices to NumPy without truncating, as this raises `ValueError: buffer size must be a multiple of element size`.

---

## 3. Dynamic Filename Parameter Extraction

Function [`detect_params_from_filename(filename)`](file:///d:/Projects/IQView/iqview/utils/helpers.py):
- Automatically extracts sample rate ($f_s$) and center frequency ($f_c$) from filename strings:
  - `capture_10Msps_433MHz.bin` $\rightarrow f_s = 10\text{ MHz}, f_c = 433\text{ MHz}$
  - `signal_2.4GHz_20MSPS.iq` $\rightarrow f_s = 20\text{ MHz}, f_c = 2.4\text{ GHz}$
  - `record_500ksps_915.5MHz.cf32` $\rightarrow f_s = 500\text{ kHz}, f_c = 915.5\text{ MHz}$
- Supports `k`, `M`, `G` unit prefixes and case-insensitive matching.
- Explicit CLI or API parameters (`-r`, `-c`, `fs=...`, `fc=...`) always override filename parsing.

---

## 4. Structured Format Error Handling

When parsing proprietary formats like Keysight `.mat` or Tektronix `.r3f`:
1. **Never exit abruptly** via `sys.exit(1)` or crash with unhandled tracebacks.
2. Raise dedicated exceptions:
   - `MatFileFormatError(msg, detail)`
   - `R3FFileFormatError(msg, detail)`
3. GUI callers catch these exceptions, open the empty canvas ("No File Loaded"), and display informative `QMessageBox.critical` dialogs explaining the missing structure and expected fields.

---

## 5. Export Routines ([`ExportDialog`](file:///d:/Projects/IQView/iqview/ui/export_dialog.py))

- **Signal Data**:
  - Raw binary IQ (`.32fc`, `.16tc`).
  - MATLAB `.mat` (saving compliant `Y`, `XDelta`, `InputCenter`).
  - NumPy `.npy`.
  - CSV `.csv` (for frequency domain spectra: `Frequency (Hz), Value`).
- **Images**:
  - Full plot with axes & labels.
  - Raw image (trace/pixels only, non-curve items hidden during render).
- **Overlays**:
  - JSON format with optional `"metadata"` block containing capture parameters.

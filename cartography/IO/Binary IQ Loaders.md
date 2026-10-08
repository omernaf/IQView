---
type: io
tags:
  - code/io
file: iqview/utils/helpers.py
title: "Binary IQ Loaders"
---

# 💾 Binary IQ Loaders

Ingests raw binary In-phase / Quadrature (IQ) captures across standard floating-point and integer formats.

---

## ⚡ Supported Types & Extensions

- `complex64` (`.32fc`, `.cf32`, `.iq`, `.bin`): 32-bit float real + 32-bit float imaginary.
- `int16` (`.16tc`, `.cs16`, `.16sc`): 16-bit signed integer interleaved. Scaled automatically to $[-1.0, 1.0]$.
- `float32` (`.32f`): Real-valued 32-bit floating point.
- `complex128` (`.64fc`): Double-precision complex IQ.

### Dynamic Filename Parameter Detection
Function `detect_params_from_filename(filename)` uses regex to auto-detect sample rate and center frequency:
- e.g., `capture_10Msps_433MHz.bin` $\rightarrow f_s = 10\text{ MHz}, f_c = 433\text{ MHz}$.

---

## 🔗 Related Notes
- [[MOC - IO and Formats]]
- [[Byte Range Slicing]]
- [[utils.py (DSP Readers)]]

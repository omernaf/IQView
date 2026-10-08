---
type: io
tags:
  - code/io
file: iqview/utils/helpers.py
title: "Audio Format Ingestion"
---

# 🎵 Audio Format Ingestion

Loads 12 audio container formats using `soundfile` with a fallback to `scipy.io.wavfile`.

---

## ⚡ Ingestion Modes

1. **Standard Audio (`-t aud` / `-t audio`)**:
   - Supported extensions: `.wav`, `.flac`, `.ogg`, `.aiff`, `.au`, `.w64`, `.rf64`, `.caf`, `.sd2`.
   - Downmixes multi-channel files to mono floating-point samples in $[-1.0, 1.0]$.
   - Sample rate is extracted directly from the audio file header.
2. **Interleaved Complex IQ Audio (`-t caudio` / `-t caud`)**:
   - Downmixes to mono, then deinterleaves into complex64:
     `x[0::2] + 1j * x[1::2]`.
   - Safely drops trailing odd samples to keep I/Q pairs balanced.

---

## 🔗 Related Notes
- [[MOC - IO and Formats]]
- [[Binary IQ Loaders]]

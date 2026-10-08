---
type: io
tags:
  - code/io
file: iqview/utils/helpers.py
title: "Keysight .mat Loader"
---

# 📊 Keysight .mat Loader

Loads MATLAB `.mat` files structured according to Keysight spectrum analyzer conventions.

---

## ⚡ Required Variables

- `Y`: Complex NumPy array of samples (scaled by $1/\sqrt{10}$).
- `XDelta`: Sample period in seconds ($1/f_s$).
- `InputCenter`: RF center frequency in Hz ($f_c$).

### Error Handling & Sidecars
- If variables are missing or non-compliant, raises `MatFileFormatError` with a structured error dialog showing a MATLAB `save()` example.
- Supports companion `.mat.overlays` JSON sidecar files for saving and restoring annotations.

---

## 🔗 Related Notes
- [[MOC - IO and Formats]]
- [[OverlayManagerMixin]]

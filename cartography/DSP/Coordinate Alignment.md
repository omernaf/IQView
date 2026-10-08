---
type: dsp
tags:
  - code/dsp
  - invariant
title: "Coordinate Alignment"
---

# 🎯 Coordinate Alignment

Ensures that the visual center of every FFT pixel in the spectrogram aligns with the physical center of the windowed sample slice.

---

## 📐 The Coordinate Shift Formula

Because an FFT window covers $W$ samples and advances by hop $H$, the physical center of the window is shifted relative to sample index 0:

$$\Delta t_{\text{offset}} = \frac{W/2 - H/2}{f_s}$$

Where:
- $W = \text{window\_size}$
- $H = \text{step\_size}$
- $f_s = \text{sample\_rate}$

Without applying this offset to the image bounding box, placed markers drift out of alignment with visual signal features when zooming in.

---

## 🔗 Related Notes
- [[MOC - DSP Pipeline]]
- [[SpectrogramView]]
- [[dsp.py]]

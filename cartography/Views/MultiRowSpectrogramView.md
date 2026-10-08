---
type: view
tags:
  - code/ui/view
  - domain/spectrogram
file: iqview/ui/multi_row_view.py
title: "MultiRowSpectrogramView"
---

# 📑 MultiRowSpectrogramView

Visualizes periodic or pulsed RF signals by slicing the recording across $N$ vertically stacked, synchronized viewports.

```mermaid
graph TD
    Win["[[SpectrogramWindow]]"] --> Multi["[[MultiRowSpectrogramView]]"]
    Multi --> Rows["N x Stacked Sub-Viewports"]
    Multi --> Sync["Axis & Zoom Synchronization Engine"]
    Multi --> Overlays["Overlay Wrapping Manager"]
```

---

## ⚡ Core Capabilities

- **Sample-Indexed Period Control**:
  - `samples_per_row`: Duration in samples per row.
  - `period`: Cycle interval in samples (e.g. 20,000 samples for 2 ms at 10 Msps). Slicing off-period (e.g. 19,900) produces a diagonal pulse tilt confirming exact sample-level resolution.
  - `start_sample`: Phase alignment offset to shift the vertical alignment.
- **Bi-Directional Axis Sync**:
  - Zooming or panning any row instantly updates all $N$ rows simultaneously.
  - Frequency bounds and relative time spans stay perfectly matched.
- **Overlay & Marker Distribution**:
  - Shapes drawn in a single row wrap and project onto corresponding time slices in adjacent rows.

---

## 🔗 Related Notes
- [[MOC - Views Hierarchy]]
- [[SpectrogramView]]
- [[CustomViewBox]]

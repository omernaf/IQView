---
type: mixin
tags:
  - code/ui/mixin
file: iqview/ui/main_window/overlay_manager.py
title: "OverlayManagerMixin"
---

# 📐 OverlayManagerMixin

Coordinates user-drawn and plugin-generated geometric overlays rendered atop the spectrogram.

```mermaid
graph TD
    OM["[[OverlayManagerMixin]]"] --> Overlays["[[Overlays Hierarchy]] (Rect, Poly, Ellipse)"]
    OM --> Table["Overlays Table Widget"]
    OM --> JSON["JSON Export / Import"]
    OM --> Sidecars[".mat.overlays Sidecar Handling"]
```

---

## ⚡ Core Capabilities

- **Interactive Manipulation**:
  - Dragging, resizing, and vertex editing for arbitrary polygons.
  - Locking individual overlays to prevent accidental movement.
- **Serialization**:
  - Exports overlays to JSON with capture metadata (`fs`, `fc`, FFT size, window type).
  - Automatically loads and saves `.mat.overlays` sidecars when working with Keysight `.mat` files.

---

## 🔗 Related Notes
- [[SpectrogramWindow]]
- [[Overlays Hierarchy]]
- [[MOC - Plugin Subsystem]]

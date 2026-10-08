---
type: plugin
tags:
  - code/plugin
  - code/ui/view
file: iqview/overlays/__init__.py
title: "Overlays Hierarchy"
---

# 📐 Overlays Hierarchy

Geometric and annotation shapes rendered interactively over the 2D spectrogram.

```mermaid
classDiagram
    class BaseOverlay {
        +label: str
        +color: str
        +locked: bool
        +iq: np.ndarray
        +fs: float
        +get_samples()
    }
    class Rect {
        +t_start, t_end
        +f_min, f_max
    }
    class Polygon {
        +points: list[(t, f)]
    }
    class Ellipse {
        +t_center, f_center
        +r_t, r_f
    }
    class XRegion {
        +t_start, t_end
    }
    class YRegion {
        +f_min, f_max
    }
    class Line {
        +t1, f1, t2, f2
    }

    BaseOverlay <|-- Rect
    BaseOverlay <|-- Polygon
    BaseOverlay <|-- Ellipse
    BaseOverlay <|-- XRegion
    BaseOverlay <|-- YRegion
    BaseOverlay <|-- Line
```

---

## ⚡ Baseband IQ Caching (`o.iq`, `o.fs`)

- Overlays can store baseband IQ slices directly in memory (`o.iq = burst_samples`).
- When downstream algorithms invoke `o.get_samples()`:
  1. If `o.iq` is present, it returns cached samples instantly with **zero disk I/O**.
  2. If `o.iq` is absent, it performs lazy Digital Down-Conversion (DDC) from the parent capture file.

---

## 🔗 Related Notes
- [[Plugin System 2.0]]
- [[PluginResult]]
- [[OverlayManagerMixin]]

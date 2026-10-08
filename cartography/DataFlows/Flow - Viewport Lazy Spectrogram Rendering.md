---
type: flow
tags:
  - code/flow
title: "Flow - Viewport Lazy Spectrogram Rendering"
---

# 🔄 Flow - Viewport Lazy Spectrogram Rendering

Traces how IQView renders multi-gigabyte captures in milliseconds without RAM exhaustion.

```mermaid
sequenceDiagram
    participant User as User Interaction
    participant View as SpectrogramView
    participant Reader as ViewportAwareReader (QThread)
    participant DSP as dsp.py
    participant GL as PyOpenGL / pg.ImageItem

    User->>View: Pan or Zoom Viewport [t_start, t_end]
    View->>View: Debounce timer fires (50 ms)
    View->>Reader: Spawn reader with visible [t_start, t_end]
    Reader->>Reader: Calculate step_size = (samples) / (4 * canvas_pixels)
    Reader->>Reader: Read only visible sample slice from disk
    loop Each FFT Row
        Reader->>DSP: preprocess_chunk() (apply window)
        Reader->>DSP: np.fft.fft()
        Reader->>DSP: postprocess_fft() (fftshift + dB/Hz offset)
    end
    Reader->>View: finished_processing.emit(spectrogram_tile)
    View->>GL: Update image texture with coordinate offset
    GL->>User: Display crisp spectrogram slice
```

---

## 🔗 Related Notes
- [[MOC - DSP Pipeline]]
- [[SpectrogramView]]
- [[utils.py (DSP Readers)]]
- [[Coordinate Alignment]]

---
type: mixin
tags:
  - code/ui/mixin
file: iqview/ui/main_window/data_handler.py
title: "DataHandlerMixin"
---

# 📦 DataHandlerMixin

Manages file opening, data source resolution, background thread dispatch, and sample segment extraction.

---

## ⚡ Core Capabilities

- Ingests file paths, in-memory byte buffers (stdin), or NumPy arrays.
- Launches background reader threads (`FileReaderThread` or `ViewportAwareReader`).
- Implements `extract_iq_segment(start_t, end_t)`:
  - Extracts the requested time slice from the data source.
  - Applies active normalization scaling `norm_db`.
  - Dispatches to popup analysis tabs (`TimeDomainView`, `EyeDiagramView`, etc.).

---

## 🔗 Related Notes
- [[SpectrogramWindow]]
- [[utils.py (DSP Readers)]]
- [[Flow - Marker to Analysis Tab Slicing]]

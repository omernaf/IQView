---
type: plugin
tags:
  - code/plugin
file: iqview/plugins/chain.py
title: "PluginChain"
---

# 🔗 PluginChain

Facilitates multi-step, sequential signal processing pipelines where outputs from one stage propagate into subsequent stages.

```mermaid
graph LR
    Stage1["Stage 1: Energy Detector"] -->|"creates Rects with o.iq"| Stage2["Stage 2: Snap to Burst"]
    Stage2 -->|"tightens bounds"| Stage3["Stage 3: FSK Demodulator"]
    Stage3 -->|"extracts bits"| Stage4["Stage 4: CRC Checker"]
```

---

## ⚡ Core Capabilities

- **Step Isolation**:
  - Each step maintains its own isolated parameter configuration.
- **In-Memory Propagation**:
  - Detected bursts carry cached baseband IQ (`o.iq`, `o.fs`), enabling subsequent demodulators to run with zero disk I/O.
- **Selective Execution**:
  - Supports **"Run Step Only"** and **"Run From Here"** execution modes from the Plugin Studio.

---

## 🔗 Related Notes
- [[Plugin System 2.0]]
- [[PluginStudioDialog]]
- [[Overlays Hierarchy]]

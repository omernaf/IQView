---
type: view
tags:
  - code/ui/view
  - code/plugin
file: iqview/ui/plugin_plot_view.py
title: "PluginPlotView"
---

# 📊 PluginPlotView

A reusable 1D multi-trace plot tab spawned dynamically by plugins via `result.add_plot_tab()`.

```mermaid
graph TD
    Plugin["Plugin run()"] -->|"result.add_plot_tab()"| View["[[PluginPlotView]]"]
    View --> Curves["Multi-Trace Curves & Legend"]
    View --> XRegions["Shaded State Regions (XRegion)"]
    View --> Markers["Markers & Region Statistics"]
```

---

## ⚡ Core Capabilities

- **Multi-Trace Rendering**:
  - Plots arbitrary scalar arrays (e.g., matched-filter correlation profiles, FM demod traces, energy envelopes) with custom colors and labels.
- **Protocol State Regions**:
  - Supports shaded vertical state regions (`XRegion`) for visualizing preamble sync sequences, payload boundaries, or packet headers.
- **Analysis Integration**:
  - Full support for interactive markers, X/Y zoom scrollbars, and region statistics.

---

## 🔗 Related Notes
- [[MOC - Plugin Subsystem]]
- [[PluginResult]]
- [[MOC - Views Hierarchy]]

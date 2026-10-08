---
type: mixin
tags:
  - code/ui/mixin
file: iqview/ui/main_window/component_setup.py
title: "ComponentSetupMixin"
---

# 🛠️ ComponentSetupMixin

Builds the visual interface hierarchy: menus, toolbars, side panels, shortcut actions, and tab containers.

---

## ⚡ Core Capabilities

- Initializes the main `SpectrogramView` and `QTabWidget` container.
- Constructs the side panel for core settings (`fs`, `fc`, FFT size, overlap, window type, `norm_db`).
- Binds global keyboard shortcuts with momentary hold actions (`Hold Ctrl` $\rightarrow$ Zoom, `Hold Space` $\rightarrow$ Pan).
- Formats action button tooltips with bracketed active shortcuts (e.g. `[T]`, `[Hold Ctrl]`).

---

## 🔗 Related Notes
- [[SpectrogramWindow]]
- [[MOC - System Architecture]]

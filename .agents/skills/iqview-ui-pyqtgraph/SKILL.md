---
name: iqview-ui-pyqtgraph
description: >-
  Low-level PyQt6 and pyqtgraph patterns, CustomViewBox event mechanics,
  marker dragging and adaptive boundary clamping, themes, tooltips, and dialogs.
  Use when modifying UI controls, CustomViewBox, marker logic, themes, or settings/export dialogs.
---

# IQView UI & PyQtGraph Integration Skill

This skill documents the low-level UI patterns, event handling, marker mathematics, and PyQt6/pyqtgraph conventions used across IQView.

For complete algorithmic implementations and widget patterns, consult:
- [Event & Marker Mechanics Reference](./references/event_and_marker_mechanics.md)

---

## 1. PyQtGraph & CustomViewBox Event Mechanics

All primary plotting canvases in IQView utilize a custom ViewBox class ([`CustomViewBox`](file:///d:/Projects/IQView/iqview/ui/widgets.py)):

### 1.1 The InfiniteLine Rule
> [!CRITICAL]
> **Never set `movable=True` directly on pyqtgraph `InfiniteLine` instances.**
> Setting `movable=True` allows pyqtgraph's internal graphics item to intercept mouse events directly, which bypasses `CustomViewBox`, skips table synchronization, and breaks marker lock constraints.
>
> **Always keep `movable=False`** and let `CustomViewBox` manage all hit-testing, dragging, and coordinate updates.

### 1.2 Mouse Interaction Protocol
- **Left-Click Drag**:
  - In Marker Mode: Moves the active marker or places a new one.
  - In Zoom Mode (`Hold Ctrl`): Draws rubberband zoom rectangle.
  - In Pan Mode (`Hold Space`): Drags the canvas.
  - In Filter Mode (`B`): Drags filter passband edges.
- **Right-Click Drag**: Dynamic continuous scaling of X and Y axes.
- **Middle-Click (Wheel Button) Drag**: Smooth panning across the canvas.
- **Undo Zoom (`Ctrl+Z`)**: Restores previous ViewBox coordinate ranges from `zoom_history`.

---

## 2. Marker Locking State Machine & Boundary Clamping

IQView supports four marker locking states: `Marker 1 Locked`, `Marker 2 Locked`, `Delta Locked`, and `Center Locked`.

### 2.1 Hit-Testing (Minimum Euclidean Distance)
When the user clicks near closely spaced markers:
- **Do not** return the first marker within 20 pixels.
- **Always** calculate Euclidean distance to all candidate markers and select the one with the strict minimum distance (`min_dist`).

### 2.2 Adaptive Boundary Clamping
When `Delta` ($|M_2 - M_1| = \text{const}$) or `Center` ($(M_1 + M_2)/2 = \text{const}$) is locked:
- If dragging pushes a marker toward a boundary (e.g. $t=0$ or $t=T_{\text{max}}$), **do not discard the movement**. Discarding the movement causes markers to freeze or get stuck before reaching the edge.
- Instead, calculate the maximum allowable shift $\Delta x_{\text{allowed}}$ that keeps *both* markers within bounds, and apply that shift proportionally to both.

```python
# Adaptive clamping pattern:
shift = requested_pos - current_pos
shift = max(shift, min_boundary - other_marker_pos)
shift = min(shift, max_boundary - other_marker_pos)
m1.setPos(m1_pos + shift)
m2.setPos(m2_pos + shift)
```

### 2.3 Recursive Signal Prevention
When clearing markers or updating table values programmatically:
```python
# Block signals on UI widgets before clearing:
self.panel.lock_delta_btn.blockSignals(True)
self.panel.lock_delta_btn.setChecked(False)
self.panel.lock_delta_btn.blockSignals(False)
```

---

## 3. Themes & Styling Architecture

### 3.1 Theme Palette & Colors ([`iqview/ui/themes.py`](file:///d:/Projects/IQView/iqview/ui/themes.py))
- Supports `Light` and `Dark` modes.
- Retrieve palettes via `get_palette(theme_name)`.
- Non-spectrogram 1D trace curves strictly use MATLAB blue (`#0072BD`, width `0.5`).
- Visual indicator lines:
  - 10th percentile line: Dotted green.
  - 90th percentile line: Dotted red.
  - Extrema points: Red circle (Max), Green triangle (Min).
- Zoom box border color dynamically matches the active theme:
  - `#000000` (black) in Light Mode.
  - `#ffffff` (white) in Dark Mode.

### 3.2 Dynamic Tooltip Hotkey Formatting
Every button and checkbox that maps to a keyboard shortcut must display the shortcut in brackets upon hover:
```python
from iqview.ui.widgets import format_tooltip_with_keybind

btn.setToolTip(format_tooltip_with_keybind("Place time markers", "keybinds/time_markers", "T"))
# Renders: "Place time markers [T]"
```

---

## 4. Dialog Stability Patterns

### 4.1 Stable Preview Labels ([`PreviewLabel`](file:///d:/Projects/IQView/iqview/ui/export_dialog.py))
When rendering dynamic image previews in dialogs (e.g. `ExportDialog`):
- Do **not** assign scaled `QPixmap` instances directly to a standard `QLabel` size hint. Doing so causes the dialog window to jitter, jump, or stretch when the aspect ratio changes.
- Use `PreviewLabel`, which decouples widget size hints from image content and performs high-quality scaling inside `paintEvent`.

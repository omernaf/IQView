# IQView Event Pipelines, Marker Mechanics & Widgets Reference

This document provides low-level implementation details and reference code patterns for pyqtgraph event routing, marker mathematics, and custom UI widgets in IQView.

---

## 1. Marker Hit-Testing (Minimum Euclidean Distance)

### Problem
When multiple markers or shadow lines are close together (e.g. within 20 pixels), returning the first line found causes clicks to grab the wrong marker, making precise interaction impossible.

### Reference Implementation
```python
def find_nearest_marker(pos_scene, markers, view_box, hit_threshold_px=20):
    """Finds the marker strictly closest to the scene position in screen pixels."""
    min_dist = float('inf')
    best_marker = None

    pos_screen = view_box.mapViewToDevice(view_box.mapSceneToView(pos_scene))

    for m in markers:
        # Map marker value to screen coordinate
        val = m.value()
        angle = getattr(m, 'angle', 90)
        is_vert = (angle == 90)

        marker_view_pt = pg.QtCore.QPointF(val, 0) if is_vert else pg.QtCore.QPointF(0, val)
        marker_screen_pt = view_box.mapViewToDevice(marker_view_pt)

        # 1D pixel distance along the active axis
        dist = abs(pos_screen.x() - marker_screen_pt.x()) if is_vert else abs(pos_screen.y() - marker_screen_pt.y())

        if dist < hit_threshold_px and dist < min_dist:
            min_dist = dist
            best_marker = m

    return best_marker
```

---

## 2. Adaptive Boundary Clamping Algorithm

### Problem
When `Delta` ($M_2 - M_1 = \Delta$) or `Center` ($(M_1 + M_2)/2 = C$) is locked, if dragging marker $M_1$ toward a boundary causes $M_2$ to exceed the recording bounds, discarding the update leaves the pair frozen before reaching the boundary.

### Reference Implementation
```python
def update_drag_locked_pair(m_active, m_companion, requested_pos, min_bound, max_bound, lock_mode='DELTA'):
    """Slides a locked pair smoothly against boundaries without dropping drag events."""
    curr_active = m_active.value()
    curr_companion = m_companion.value()
    delta = requested_pos - curr_active

    if lock_mode == 'DELTA':
        # Companion shifts identically: companion_new = curr_companion + delta
        # Clamp delta so companion stays inside [min_bound, max_bound]
        min_allowed_delta = min_bound - curr_companion
        max_allowed_delta = max_bound - curr_companion

        # Also clamp delta so active marker stays inside [min_bound, max_bound]
        min_allowed_delta = max(min_allowed_delta, min_bound - curr_active)
        max_allowed_delta = min(max_allowed_delta, max_bound - curr_active)

        applied_delta = max(min_allowed_delta, min(max_allowed_delta, delta))

        m_active.setPos(curr_active + applied_delta)
        m_companion.setPos(curr_companion + applied_delta)

    elif lock_mode == 'CENTER':
        # Center C is fixed: companion_new = 2*C - active_new
        center = (curr_active + curr_companion) / 2.0
        new_active = max(min_bound, min(max_bound, requested_pos))
        new_companion = 2.0 * center - new_active

        # If companion hit boundary, clamp companion and adjust active symmetrically
        if new_companion < min_bound:
            new_companion = min_bound
            new_active = 2.0 * center - new_companion
        elif new_companion > max_bound:
            new_companion = max_bound
            new_active = 2.0 * center - new_companion

        m_active.setPos(new_active)
        m_companion.setPos(new_companion)
```

---

## 3. Stable Preview Labels (`PreviewLabel`)

### Problem
Assigning dynamic `QPixmap` instances to standard `QLabel` causes `sizeHint()` to change continuously, which abruptly jumps or stretches the parent dialog window.

### Reference Implementation
```python
from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter

class PreviewLabel(QLabel):
    """Decouples widget sizeHint from image aspect ratio, scaling cleanly in paintEvent."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self.setMinimumSize(100, 100)

    def setPreviewPixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        if self._pixmap is None or self._pixmap.isNull():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
```

---

## 4. Signal Blocking during Programmatic Resets

To prevent cascading recursive signal loops when updating UI controls programmatically:
```python
# Wrap programmatic updates in blockSignals
widget.blockSignals(True)
try:
    widget.setChecked(desired_state)
    widget.setText(formatted_value)
finally:
    widget.blockSignals(False)
```

"""iqview/ui/main_window/overlay_manager.py

OverlayManagerMixin — mixed into SpectrogramWindow.

Provides the full public overlay API (add_overlay, remove_overlay,
update_overlay, clear_overlays, get_overlays) and manages the matching
pyqtgraph graphics items on the spectrogram PlotItem.

LINE / HLINE overlays use pg.InfiniteLine so they integrate correctly with
the endless-marker system that already relies on those objects.
All other shapes (RECT, POLYGON, CIRCLE, ELLIPSE) use OverlayItem.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import pyqtgraph as pg
from PyQt6.QtCore import Qt

from ..overlay import Overlay, OverlayItem, OverlayShape, _BORDER_STYLE_MAP


class OverlayManagerMixin:
    """
    Manages overlays displayed on the spectrogram.

    Attributes added to the host class
    -----------------------------------
    overlays          : list[Overlay]
    _overlay_items    : dict[str, OverlayItem | pg.InfiniteLine]
    """

    # ------------------------------------------------------------------
    # Initialisation (call from SpectrogramWindow.__init__)
    # ------------------------------------------------------------------

    def _init_overlays(self) -> None:
        self.overlays: List[Overlay] = []
        self._overlay_items: Dict[str, Any] = {}   # id → OverlayItem | pg.InfiniteLine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_overlay(self, overlay: Overlay) -> str:
        """
        Add an overlay to the spectrogram.  Returns the overlay's id.
        Safe to call before the plot is initialised (items are created lazily).
        """
        # Prevent duplicate ids
        if any(o.id == overlay.id for o in self.overlays):
            self._sync_overlay_item(overlay)
            return overlay.id

        self.overlays.append(overlay)
        self._sync_overlay_item(overlay)

        if hasattr(self, 'marker_panel') and self.interaction_mode == 'OVERLAY':
            if hasattr(self.marker_panel, 'update_overlay_list'):
                self.marker_panel.update_overlay_list(self.overlays)
        return overlay.id

    # ------------------------------------------------------------------
    # Placement via click / drag (called from CustomViewBox)
    # ------------------------------------------------------------------

    def place_overlay_by_click(self, view_pos) -> None:
        """
        Single-click in OVERLAY mode → place a vertical LINE at the clicked
        time position with default styling.
        """
        t = view_pos.x()
        overlay = Overlay(
            shape=OverlayShape.LINE,
            points=[(t, 0.0)],
            color='#008800',
            alpha=0.0,
            border_width=2,
            border_style='solid',
            display_str='',
            hover_str='',
            z_order=8,
            source='user',
        )
        self.add_overlay(overlay)
        if hasattr(self, 'update_marker_info'):
            self.update_marker_info()

    def place_overlay_by_drag(self, start_view, end_view) -> None:
        """
        Drag in OVERLAY mode → place a RECT overlay spanning the dragged region.
        start_view / end_view are QPointF in data/view coordinates.
        """
        t0, f0 = start_view.x(), start_view.y()
        t1, f1 = end_view.x(),   end_view.y()
        # Require a minimum drag distance to avoid accidental placements
        xr, yr = self.spectrogram_view.plot_item.viewRange()
        min_w = abs(xr[1] - xr[0]) * 0.005
        min_h = abs(yr[1] - yr[0]) * 0.005
        if abs(t1 - t0) < min_w and abs(f1 - f0) < min_h:
            # Too small — treat as a click instead
            self.place_overlay_by_click(start_view)
            return
        overlay = Overlay(
            shape=OverlayShape.RECT,
            points=[(min(t0, t1), min(f0, f1)), (max(t0, t1), max(f0, f1))],
            color='#008800',
            alpha=0.20,
            border_width=2,
            border_style='solid',
            display_str='',
            hover_str='',
            z_order=8,
            source='user',
        )
        self.add_overlay(overlay)
        if hasattr(self, 'update_marker_info'):
            self.update_marker_info()



    def remove_overlay(self, overlay_id: str) -> None:
        """Remove an overlay by id, cleaning up its graphics item."""
        overlay = self._get_overlay_by_id(overlay_id)
        if overlay is None:
            return

        self._remove_graphics_item(overlay_id, overlay)

        self.overlays = [o for o in self.overlays if o.id != overlay_id]

        if hasattr(self, 'marker_panel') and self.interaction_mode == 'OVERLAY':
            if hasattr(self.marker_panel, 'update_overlay_list'):
                self.marker_panel.update_overlay_list(self.overlays)
        if hasattr(self, 'update_marker_info'):
            self.update_marker_info()

    def update_overlay(self, overlay_id: str, **kwargs) -> None:
        """
        Partial update of an overlay's properties.
        Example: update_overlay(oid, color='#ff0000', display_str='New tag')
        """
        overlay = self._get_overlay_by_id(overlay_id)
        if overlay is None:
            return

        for key, value in kwargs.items():
            if hasattr(overlay, key):
                setattr(overlay, key, value)

        # Re-sync the graphics item (may re-create if shape changed)
        self._sync_overlay_item(overlay)

        if hasattr(self, 'marker_panel') and self.interaction_mode == 'OVERLAY':
            if hasattr(self.marker_panel, 'update_overlay_list'):
                self.marker_panel.update_overlay_list(self.overlays)
        if hasattr(self, 'update_marker_info'):
            self.update_marker_info()

    def clear_overlays(self, source: Optional[str] = None) -> None:
        """
        Remove overlays matching source ('user', a mod name, …).
        Pass source=None to clear ALL overlays regardless of source.
        """
        to_remove = [o.id for o in self.overlays
                     if source is None or o.source == source]
        for oid in to_remove:
            overlay = self._get_overlay_by_id(oid)
            if overlay:
                self._remove_graphics_item(oid, overlay)
        self.overlays = [o for o in self.overlays
                         if source is not None and o.source != source]

        if hasattr(self, 'marker_panel') and self.interaction_mode == 'OVERLAY':
            if hasattr(self.marker_panel, 'update_overlay_list'):
                self.marker_panel.update_overlay_list(self.overlays)

    def get_overlays(self, source: Optional[str] = None) -> List[Overlay]:
        """Return overlays filtered by source, or all if source is None."""
        if source is None:
            return list(self.overlays)
        return [o for o in self.overlays if o.source == source]

    def _get_overlay_by_id(self, overlay_id: str) -> Optional[Overlay]:
        for o in self.overlays:
            if o.id == overlay_id:
                return o
        return None

    # ------------------------------------------------------------------
    # Graphics synchronisation
    # ------------------------------------------------------------------

    def _sync_overlay_item(self, overlay: Overlay) -> None:
        """
        Create or recreate the graphics item for *overlay*.
        Removes any existing item first so changes to shape/geometry are reflected.
        """
        # Remove existing item if present
        if overlay.id in self._overlay_items:
            self._remove_graphics_item(overlay.id, overlay)

        if not hasattr(self, 'spectrogram_view'):
            return  # Not yet initialised

        plot_item = self.spectrogram_view.plot_item

        if overlay.shape in (OverlayShape.LINE, OverlayShape.HLINE):
            item = self._create_line_item(overlay)
            if item is None:
                return
            item.setZValue(overlay.z_order)
            item.setVisible(overlay.visible)
            plot_item.addItem(item, ignoreBounds=True)
            self._overlay_items[overlay.id] = item
        else:
            item = OverlayItem(overlay, on_geometry_changed=self._persist_overlay_drag)
            item.setZValue(overlay.z_order)
            item.setVisible(overlay.visible)
            plot_item.addItem(item)
            item.attach_to_plot(plot_item)
            self._overlay_items[overlay.id] = item

    def _create_line_item(self, overlay: Overlay) -> Optional[pg.InfiniteLine]:
        """Build a pg.InfiniteLine for a LINE or HLINE overlay."""
        if not overlay.points:
            return None

        is_time = (overlay.shape == OverlayShape.LINE)
        angle   = 90 if is_time else 0
        pos     = overlay.points[0][0] if is_time else overlay.points[0][1]
        movable = not overlay.locked

        bc = overlay.border_color or overlay.color
        pen = pg.mkPen(
            bc,
            width=overlay.border_width,
            style=_BORDER_STYLE_MAP.get(overlay.border_style, Qt.PenStyle.SolidLine),
        )
        hover_pen = pg.mkPen(bc, width=overlay.border_width + 1)

        label_opts = {
            'position': 0.1,
            'color': bc,
            'anchors': [(0, 0), (0, 0)],
        }
        line = pg.InfiniteLine(
            pos=pos,
            angle=angle,
            movable=movable,
            pen=pen,
            hoverPen=hover_pen,
            label=overlay.display_str or None,
            labelOpts=label_opts if overlay.display_str else {},
        )
        if overlay.hover_str:
            line.setToolTip(overlay.hover_str)

        if movable:
            oid = overlay.id
            def _on_line_moved(line=line, overlay=overlay, oid=oid):
                pos_val = line.value()
                if overlay.shape == OverlayShape.LINE:
                    overlay.points = [(pos_val, 0.0)]
                else:
                    overlay.points = [(0.0, pos_val)]
                self._persist_overlay_drag(oid, points=overlay.points)
            line.sigPositionChangeFinished.connect(_on_line_moved)

        return line

    def _persist_overlay_drag(self, overlay_id: str, **kwargs) -> None:
        """
        Called when an interactive drag/resize finishes on an OverlayItem or
        InfiniteLine.  Geometry is already mutated in-place; this just refreshes
        the panel and (optionally) triggers save, without recreating graphics.
        """
        overlay = self._get_overlay_by_id(overlay_id)
        if overlay is None:
            return
        # Synchronise any kwargs that differ (safety guard)
        for key, value in kwargs.items():
            if hasattr(overlay, key):
                setattr(overlay, key, value)
        # Refresh label position on OverlayItem without recreating it
        item = self._overlay_items.get(overlay_id)
        if isinstance(item, OverlayItem):
            item.prepareGeometryChange()
            item._update_label_pos()
            item.update()
        if hasattr(self, 'marker_panel') and self.interaction_mode == 'OVERLAY':
            if hasattr(self.marker_panel, 'update_overlay_list'):
                self.marker_panel.update_overlay_list(self.overlays)

    def _remove_graphics_item(self, overlay_id: str, overlay: Overlay) -> None:
        """Remove the graphics item from the scene and clean up side effects."""
        item = self._overlay_items.pop(overlay_id, None)
        if item is None:
            return

        if not hasattr(self, 'spectrogram_view'):
            return

        plot_item = self.spectrogram_view.plot_item

        if isinstance(item, OverlayItem):
            item.detach_from_plot()
            try:
                plot_item.removeItem(item)
            except Exception:
                pass
        else:
            # pg.InfiniteLine — may also live in the endless-marker lists
            try:
                plot_item.removeItem(item)
            except Exception:
                pass
            # Keep endless-marker lists consistent
            if overlay.shape == OverlayShape.LINE:
                if item in getattr(self, 'markers_time_endless', []):
                    self.markers_time_endless.remove(item)
            elif overlay.shape == OverlayShape.HLINE:
                if item in getattr(self, 'markers_freq_endless', []):
                    self.markers_freq_endless.remove(item)

    def refresh_overlays_theme(self) -> None:
        """
        Called when the theme changes.  Re-syncs all overlay items.

        User-defined colours are intentionally NOT overridden here — only
        line overlays that used the auto-theme colour on creation need updating.
        """
        for overlay in list(self.overlays):
            self._sync_overlay_item(overlay)

    # ------------------------------------------------------------------
    # Persistence — JSON sidecar
    # ------------------------------------------------------------------

    def _overlay_sidecar_path(self, file_path: str) -> str:
        return file_path + ".overlays"

    def save_overlay_sidecar(self, file_path: Optional[str] = None) -> None:
        """Persist user-created overlays to a JSON sidecar next to the IQ file."""
        path = file_path or getattr(self, 'file_path', None)
        if not isinstance(path, str):
            return

        user_overlays = [o for o in self.overlays if o.source == 'user']
        if not user_overlays:
            # Remove stale sidecar if all user overlays were deleted
            sidecar = self._overlay_sidecar_path(path)
            if os.path.isfile(sidecar):
                try:
                    os.remove(sidecar)
                except OSError:
                    pass
            return

        data = {
            "version": 1,
            "overlays": [o.to_dict() for o in user_overlays],
        }
        sidecar = self._overlay_sidecar_path(path)
        try:
            with open(sidecar, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            print(f"[IQView] Could not save overlay sidecar: {exc}")

    def load_overlay_sidecar(self, file_path: Optional[str] = None) -> None:
        """Load user overlays from a JSON sidecar if one exists."""
        path = file_path or getattr(self, 'file_path', None)
        if not isinstance(path, str):
            return

        sidecar = self._overlay_sidecar_path(path)
        if not os.path.isfile(sidecar):
            return

        try:
            with open(sidecar, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[IQView] Could not read overlay sidecar: {exc}")
            return

        # Only import 'user' overlays (mods add their own at runtime)
        for d in data.get("overlays", []):
            try:
                o = Overlay.from_dict(d)
                o.source = 'user'
                self.add_overlay(o)
            except Exception as exc:
                print(f"[IQView] Skipping malformed overlay entry: {exc}")

    def export_overlays(self) -> None:
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        
        user_overlays = [o for o in self.overlays if o.source == 'user']
        if not user_overlays:
            QMessageBox.information(self, "Export Overlays", "No user overlays to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Overlays", "", "JSON Files (*.json)"
        )
        if not path:
            return

        data = {
            "version": 1,
            "overlays": [o.to_dict() for o in user_overlays],
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, "Export Successful", f"Saved {len(user_overlays)} overlays to {path}.")
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", f"Failed to export overlays:\n{exc}")

    def import_overlays(self) -> None:
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Overlays", "", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", f"Failed to read overlay file:\n{exc}")
            return

        imported_count = 0
        for d in data.get("overlays", []):
            try:
                import uuid
                o = Overlay.from_dict(d)
                o.source = 'user'
                # Ensure a new random ID so we append instead of overwriting visually overlapping items
                # if the user imports the same file twice, although the API technically just uses the ID inside the dict.
                # The user request: "add them to the current ones rather then replacing"
                o.id = str(uuid.uuid4())
                self.add_overlay(o)
                imported_count += 1
            except Exception as exc:
                print(f"[IQView] Skipping malformed overlay entry during import: {exc}")

        QMessageBox.information(self, "Import Successful", f"Imported {imported_count} overlays.")
        if hasattr(self, 'update_marker_info'):
            self.update_marker_info()


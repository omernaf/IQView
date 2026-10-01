"""iqview/ui/main_window/overlay_manager.py

OverlayManagerMixin — mixed into SpectrogramWindow.

Provides the full public overlay API (add_overlay, remove_overlay,
update_overlay, clear_overlays, get_overlays) and manages the matching
pyqtgraph graphics items on the spectrogram PlotItem.

LINE / HLINE overlays use pg.InfiniteLine so they integrate correctly with
the endless-marker system that already relies on those objects.
All other shapes (RECT, POLYGON, ELLIPSE) use OverlayItem.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

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
        self.selected_overlay_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_overlay(self, overlay: Overlay, _refresh_ui: bool = True) -> str:
        """
        Add an overlay to the spectrogram.  Returns the overlay's id.
        Safe to call before the plot is initialised (items are created lazily).
        """
        # Prevent duplicate ids
        if any(o.id == overlay.id for o in self.overlays):
            self._sync_overlay_item(overlay, _sync_multi_row=_refresh_ui)
            return overlay.id

        self.overlays.append(overlay)
        self._sync_overlay_item(overlay, _sync_multi_row=_refresh_ui)

        if _refresh_ui:
            self.refresh_overlays_ui()
        return overlay.id

    def refresh_overlays_ui(self) -> None:
        """Refresh overlay list panel, plugin overlay pills, marker info, and multi-row view in one pass."""
        if hasattr(self, 'marker_panel'):
            eff_mode = getattr(self, 'interaction_mode', '')
            if eff_mode in ('ZOOM', 'MOVE'):
                eff_mode = getattr(self.marker_panel, 'last_marker_mode', '')
            if eff_mode == 'OVERLAY' and hasattr(self.marker_panel, 'update_overlay_list'):
                self.marker_panel.update_overlay_list(self.overlays)
            if hasattr(self.marker_panel, 'update_plugin_overlay_pills'):
                self.marker_panel.update_plugin_overlay_pills(self.overlays)
        if hasattr(self, 'update_marker_info'):
            self.update_marker_info()
        self.sync_multi_row_overlays()

    def toggle_source_overlays_visible(self, source: str) -> bool:
        """Toggle visibility of all overlays matching *source* and return the new visibility state."""
        matching = [o for o in self.overlays if o.source == source]
        if not matching:
            return True
        any_vis = any(o.visible for o in matching)
        new_vis = not any_vis
        for o in matching:
            o.visible = new_vis
            item = self._overlay_items.get(o.id)
            if item is not None:
                item.setVisible(new_vis)
        self.refresh_overlays_ui()
        return new_vis

    def select_overlay(self, overlay_id: Optional[str], scroll_to_row: bool = True) -> None:
        """
        Select an overlay by id (or pass None to clear selection).
        Highlights the overlay on the spectrogram, switches to the Overlay table
        if needed, and jumps/scrolls to its row in the Overlay table.
        """
        if overlay_id is not None and self._get_overlay_by_id(overlay_id) is None:
            overlay_id = None

        self.selected_overlay_id = overlay_id

        for oid, item in self._overlay_items.items():
            if isinstance(item, OverlayItem):
                new_sel = (oid == overlay_id)
                if getattr(item, '_selected', False) != new_sel:
                    item._selected = new_sel
                    item.update()

        if hasattr(self, 'marker_panel'):
            if overlay_id is not None and scroll_to_row:
                curr_mode = getattr(self, 'interaction_mode', 'TIME')
                if curr_mode in ('ZOOM', 'MOVE'):
                    self._prev_interaction_mode = 'OVERLAY'
                    self.marker_panel.last_marker_mode = 'OVERLAY'
                    self.marker_panel.update_headers(curr_mode)
                elif curr_mode != 'OVERLAY':
                    self.set_interaction_mode('OVERLAY')
                if hasattr(self.marker_panel, 'update_overlay_list'):
                    self.marker_panel.update_overlay_list(self.overlays)
            if hasattr(self.marker_panel, 'set_selected_overlay'):
                self.marker_panel.set_selected_overlay(overlay_id, scroll_to_row=scroll_to_row)

        self.sync_multi_row_overlays()

    # ------------------------------------------------------------------
    # Placement via click / drag (called from CustomViewBox)
    # ------------------------------------------------------------------

    def place_overlay_by_click(self, view_pos) -> None:
        """
        Single-click in OVERLAY mode → place a default-sized shape centered at the click.
        """
        waterfall = self.spectrogram_view.is_waterfall
        # In standard mode: X=time, Y=freq. In waterfall: X=freq, Y=time.
        if waterfall:
            t = view_pos.y()
            f = view_pos.x()
        else:
            t = view_pos.x()
            f = view_pos.y()
        
        shape = OverlayShape.LINE
        if hasattr(self, 'marker_panel') and hasattr(self.marker_panel, 'cb_overlay_shape'):
            shape = self.marker_panel.cb_overlay_shape.currentData() or OverlayShape.LINE
            
        xr, yr = self.spectrogram_view.plot_item.viewRange()
        w = abs(xr[1] - xr[0]) * 0.1
        h = abs(yr[1] - yr[0]) * 0.1
        # Convert view-space w/h to logical time/freq extents
        if waterfall:
            t_span = h   # Y carries time
            f_span = w   # X carries freq
        else:
            t_span = w
            f_span = h
        
        points = []
        center = None
        radii = None
        alpha = 0.20
        
        if shape == OverlayShape.LINE:
            points = [(t, 0.0)]
            alpha = 0.0
        elif shape == OverlayShape.HLINE:
            points = [(0.0, f)]
            alpha = 0.0
        elif shape == OverlayShape.X_REGION:   # time band
            points = [(t - t_span/2, 0.0), (t + t_span/2, 0.0)]
        elif shape == OverlayShape.Y_REGION:   # freq band
            points = [(0.0, f - f_span/2), (0.0, f + f_span/2)]
        elif shape == OverlayShape.RECT:
            points = [(t - t_span/2, f - f_span/2), (t + t_span/2, f + f_span/2)]
        elif shape == OverlayShape.ELLIPSE:
            center = (t, f)
            radii = (t_span/2, f_span/2)
        elif shape == OverlayShape.POLYGON:
            points = [(t, f + f_span/2), (t + t_span/2, f - f_span/2), (t - t_span/2, f - f_span/2)]

        overlay = Overlay(
            shape=shape,
            points=points,
            center=center,
            radii=radii,
            color='#008800',
            alpha=alpha,
            border_width=2,
            border_style='solid',
            display_str='',
            hover_str='',
            z_order=8,
            source='user',
        )
        self.add_overlay(overlay)

    def place_overlay_by_drag(self, start_view, end_view) -> None:
        """
        Drag in OVERLAY mode → place a shape spanning the dragged region.
        start_view / end_view are QPointF in data/view coordinates.
        """
        waterfall = self.spectrogram_view.is_waterfall
        if waterfall:
            # X=freq, Y=time in view space
            t0, f0 = start_view.y(), start_view.x()
            t1, f1 = end_view.y(),   end_view.x()
        else:
            t0, f0 = start_view.x(), start_view.y()
            t1, f1 = end_view.x(),   end_view.y()

        # Require a minimum drag distance to avoid accidental placements
        xr, yr = self.spectrogram_view.plot_item.viewRange()
        min_w = abs(xr[1] - xr[0]) * 0.005
        min_h = abs(yr[1] - yr[0]) * 0.005
        # Use view-space drag for the threshold check
        if abs(end_view.x() - start_view.x()) < min_w and abs(end_view.y() - start_view.y()) < min_h:
            self.place_overlay_by_click(start_view)
            return

        shape = OverlayShape.RECT
        if hasattr(self, 'marker_panel') and hasattr(self.marker_panel, 'cb_overlay_shape'):
            shape = self.marker_panel.cb_overlay_shape.currentData() or OverlayShape.RECT
            
        points = []
        center = None
        radii = None
        alpha = 0.20
        
        if shape == OverlayShape.LINE:
            points = [(t0, 0.0)]
            alpha = 0.0
        elif shape == OverlayShape.HLINE:
            points = [(0.0, f0)]
            alpha = 0.0
        elif shape == OverlayShape.X_REGION:   # time band
            points = [(min(t0, t1), 0.0), (max(t0, t1), 0.0)]
        elif shape == OverlayShape.Y_REGION:   # freq band
            points = [(0.0, min(f0, f1)), (0.0, max(f0, f1))]
        elif shape == OverlayShape.RECT:
            points = [(min(t0, t1), min(f0, f1)), (max(t0, t1), max(f0, f1))]
        elif shape == OverlayShape.ELLIPSE:
            center = ((t0 + t1) / 2, (f0 + f1) / 2)
            radii = (abs(t1 - t0) / 2, abs(f1 - f0) / 2)
        elif shape == OverlayShape.POLYGON:
            t_min, t_max = min(t0, t1), max(t0, t1)
            f_min, f_max = min(f0, f1), max(f0, f1)
            points = [((t_min + t_max) / 2, f_max), (t_max, f_min), (t_min, f_min)]

        overlay = Overlay(
            shape=shape,
            points=points,
            center=center,
            radii=radii,
            color='#008800',
            alpha=alpha,
            border_width=2,
            border_style='solid',
            display_str='',
            hover_str='',
            z_order=8,
            source='user',
        )
        self.add_overlay(overlay)

    def remove_overlay(self, overlay_id: str, _refresh_ui: bool = True) -> None:
        """Remove an overlay by id, cleaning up its graphics item."""
        overlay = self._get_overlay_by_id(overlay_id)
        if overlay is None:
            return

        if getattr(self, 'selected_overlay_id', None) == overlay_id:
            self.selected_overlay_id = None

        self._remove_graphics_item(overlay_id, overlay)

        self.overlays = [o for o in self.overlays if o.id != overlay_id]

        if _refresh_ui:
            self.refresh_overlays_ui()

    def update_overlay(self, overlay_id: str, _refresh_ui: bool = True, **kwargs) -> None:
        """
        Partial update of an overlay's properties.
        Example: update_overlay(oid, color='#ff0000', display_str='New tag')
        """
        overlay = self._get_overlay_by_id(overlay_id)
        if overlay is None:
            return

        geom_changed = any(
            k in kwargs and getattr(overlay, k, None) != kwargs[k]
            for k in ("points", "center", "radii", "shape")
        )

        for key, value in kwargs.items():
            if hasattr(overlay, key):
                setattr(overlay, key, value)

        if geom_changed and "iq" not in kwargs:
            overlay.iq = None
            overlay.fs = None

        # Re-sync the graphics item (may re-create if shape changed)
        self._sync_overlay_item(overlay, _sync_multi_row=_refresh_ui)

        if _refresh_ui:
            self.refresh_overlays_ui()

    def clear_overlays(self, source: Optional[str] = None) -> None:
        """
        Remove overlays matching source ('user', a mod name, …).
        Pass source=None to clear ALL overlays regardless of source.
        """
        to_remove = [o.id for o in self.overlays
                     if source is None or o.source == source]
        if getattr(self, 'selected_overlay_id', None) in to_remove:
            self.selected_overlay_id = None
        for oid in to_remove:
            overlay = self._get_overlay_by_id(oid)
            if overlay:
                self._remove_graphics_item(oid, overlay)
        self.overlays = [o for o in self.overlays
                         if source is not None and o.source != source]

        self.refresh_overlays_ui()

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

    def _sync_overlay_item(self, overlay: Overlay, _sync_multi_row: bool = True) -> None:
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
        elif overlay.shape in (OverlayShape.X_REGION, OverlayShape.Y_REGION):
            item = self._create_region_item(overlay)
            if item is None:
                return
            item.setZValue(overlay.z_order)
            item.setVisible(overlay.visible)
            plot_item.addItem(item, ignoreBounds=True)
            self._overlay_items[overlay.id] = item
        else:
            waterfall = getattr(self.spectrogram_view, 'is_waterfall', False)
            item = OverlayItem(
                overlay,
                waterfall=waterfall,
                on_geometry_changed=self._persist_overlay_drag,
                on_selected=self.select_overlay,
                on_double_clicked=self._on_overlay_item_double_clicked,
            )
            item._selected = (overlay.id == getattr(self, 'selected_overlay_id', None))
            item.setZValue(overlay.z_order)
            item.setVisible(overlay.visible)
            plot_item.addItem(item, ignoreBounds=True)
            item.attach_to_plot(plot_item)
            self._overlay_items[overlay.id] = item

        if _sync_multi_row:
            self.sync_multi_row_overlays()

    def _on_overlay_item_double_clicked(self, oid: str) -> None:
        self.select_overlay(oid, scroll_to_row=True)
        self.inspect_overlay(oid)

    def _create_line_item(self, overlay: Overlay) -> Optional[pg.InfiniteLine]:
        """Build a pg.InfiniteLine for a LINE or HLINE overlay.

        LINE  = time marker (vertical in standard, horizontal in waterfall)
        HLINE = freq marker (horizontal in standard, vertical in waterfall)
        """
        if not overlay.points:
            return None

        waterfall = self.spectrogram_view.is_waterfall
        is_time = (overlay.shape == OverlayShape.LINE)

        # Standard: time=90°, freq=0°  |  Waterfall: time=0°, freq=90°
        if waterfall:
            angle = 0 if is_time else 90
        else:
            angle = 90 if is_time else 0

        pos = overlay.points[0][0] if is_time else overlay.points[0][1]
        movable = False

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
        tip = overlay.get_truncated_hover()
        if tip:
            line.setToolTip(tip)

        return line

    def _create_region_item(self, overlay: Overlay):
        """Build a pg.LinearRegionItem for an X_REGION or Y_REGION overlay.

        X_REGION = time band (vertical stripe in standard, horizontal in waterfall)
        Y_REGION = freq band (horizontal stripe in standard, vertical in waterfall)
        """
        if not overlay.points or len(overlay.points) < 2:
            return None

        waterfall = self.spectrogram_view.is_waterfall
        is_time_band = (overlay.shape == OverlayShape.X_REGION)

        # Standard: time band = vertical strip (orientation='vertical')
        #           freq band = horizontal strip (orientation='horizontal')
        # Waterfall: axes swap, so orientations invert
        if waterfall:
            orientation = 'horizontal' if is_time_band else 'vertical'
        else:
            orientation = 'vertical' if is_time_band else 'horizontal'

        if is_time_band:
            v0 = overlay.points[0][0]   # t_start
            v1 = overlay.points[1][0]   # t_end
        else:
            v0 = overlay.points[0][1]   # f_start
            v1 = overlay.points[1][1]   # f_end

        bc = QColor(overlay.border_color or overlay.color)
        fc = QColor(overlay.color)
        fc.setAlphaF(max(0.0, min(1.0, overlay.alpha)))

        pen = pg.mkPen(
            bc,
            width=overlay.border_width,
            style=_BORDER_STYLE_MAP.get(overlay.border_style, Qt.PenStyle.SolidLine),
        )
        brush = pg.mkBrush(fc)

        movable = not overlay.locked
        region = pg.LinearRegionItem(
            values=[min(v0, v1), max(v0, v1)],
            orientation=orientation,
            brush=brush,
            pen=pen,
            movable=movable,
        )
        tip = overlay.get_truncated_hover()
        if tip:
            region.setToolTip(tip)

        if movable:
            oid = overlay.id
            def _on_region_changed(region=region, overlay=overlay, oid=oid):
                r0, r1 = region.getRegion()
                if overlay.shape == OverlayShape.X_REGION:
                    overlay.points = [(r0, 0.0), (r1, 0.0)]
                else:
                    overlay.points = [(0.0, r0), (0.0, r1)]
                self._persist_overlay_drag(oid, points=overlay.points)
            region.sigRegionChangeFinished.connect(_on_region_changed)

        return region

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
        self.sync_multi_row_overlays()

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
        import datetime

        exportable = list(self.overlays)
        if not exportable:
            QMessageBox.information(self, "Export Overlays", "No overlays to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Overlays", "", "JSON Files (*.json)"
        )
        if not path:
            return

        # ── Build optional metadata block ────────────────────────────────────
        meta: dict = {
            "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        fp = getattr(self, 'file_path', None)
        if fp:
            meta["file_name"] = os.path.basename(fp)
            meta["file_path"] = fp
        rate = getattr(self, 'rate', None)
        if rate is not None:
            meta["sample_rate_hz"] = float(rate)
        fc = getattr(self, 'fc', None)
        if fc is not None:
            meta["center_freq_hz"] = float(fc)
        fft = getattr(self, 'fft_size', None)
        if fft is not None:
            meta["fft_size"] = int(fft)
        wt = getattr(self, 'window_type', None)
        if wt is not None:
            meta["window_type"] = str(wt)
        overlap = getattr(self, 'overlap_percent', None)
        if overlap is not None:
            meta["overlap_percent"] = float(overlap)
        dtype = getattr(self, 'data_type', None)
        if dtype is not None:
            meta["data_type"] = getattr(dtype, '__name__', str(dtype))
        is_complex = getattr(self, 'is_complex', None)
        if is_complex is not None:
            meta["is_complex"] = bool(is_complex)

        data = {
            "version": 1,
            "metadata": meta,
            "overlays": [o.to_dict() for o in exportable],
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, "Export Successful", f"Saved {len(exportable)} overlays to {path}.")
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", f"Failed to export overlays:\n{exc}")

    def promote_plugin_overlays(self, source: Optional[str] = None) -> int:
        """
        Convert plugin-created overlays into permanent 'user' overlays so they
        are saved in the JSON sidecar alongside manual overlays.
        """
        promoted = 0
        for o in self.overlays:
            if o.source != 'user' and (source is None or o.source == source):
                o.metadata.setdefault("original_source", o.source)
                o.source = 'user'
                promoted += 1
        if promoted > 0:
            self.save_overlay_sidecar()
            self.refresh_overlays_ui()
            if hasattr(self, 'statusBar'):
                self.statusBar().showMessage(
                    f"Promoted {promoted} plugin overlay(s) to permanent user overlays.", 3500
                )
        return promoted

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
                o.source = d.get("source", "user") or "user"
                o.id = str(uuid.uuid4())
                self.add_overlay(o, _refresh_ui=False)
                imported_count += 1
            except Exception as exc:
                print(f"[IQView] Skipping malformed overlay entry during import: {exc}")

        self.refresh_overlays_ui()
        QMessageBox.information(self, "Import Successful", f"Imported {imported_count} overlays.")

    # ------------------------------------------------------------------
    # Hit-Testing, Overlay Inspector & Native Tab Analysis
    # ------------------------------------------------------------------

    def find_overlays_at_view_pos(self, view_pos, view_box=None) -> List[Overlay]:
        """
        Return all visible overlays containing *view_pos* (in ViewBox coordinates),
        sorted from most specific (highest z_order / smallest area) to least.
        """
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QPainterPath

        waterfall = getattr(getattr(self, 'spectrogram_view', None), 'is_waterfall', False)
        if waterfall:
            t = float(view_pos.y())
            f = float(view_pos.x())
        else:
            t = float(view_pos.x())
            f = float(view_pos.y())

        # Compute line hit tolerances (~1.2% of visible span)
        t_tol, f_tol = 1e-3, 1e3
        vb = view_box or getattr(getattr(self, 'spectrogram_view', None), 'view_box', None)
        if vb is not None:
            try:
                xr, yr = vb.viewRange()
                if waterfall:
                    f_tol = abs(xr[1] - xr[0]) * 0.012
                    t_tol = abs(yr[1] - yr[0]) * 0.012
                else:
                    t_tol = abs(xr[1] - xr[0]) * 0.012
                    f_tol = abs(yr[1] - yr[0]) * 0.012
            except Exception:
                pass

        hits: List[ tuple[int, float, Overlay] ] = []
        logical_pt = QPointF(t, f)

        for o in self.overlays:
            if not getattr(o, 'visible', True):
                continue
            matched = False
            area = float('inf')

            if o.shape == OverlayShape.RECT:
                if o.t_start <= t <= o.t_end and o.f_start <= f <= o.f_end:
                    matched = True
                    area = max(1e-18, o.duration * o.bandwidth)
            elif o.shape == OverlayShape.ELLIPSE and o.center and o.radii:
                cx, cy = o.center
                rx, ry = o.radii
                if rx > 0 and ry > 0 and (((t - cx) / rx) ** 2 + ((f - cy) / ry) ** 2 <= 1.0):
                    matched = True
                    area = 3.14159 * rx * ry
            elif o.shape == OverlayShape.POLYGON and len(o.points) >= 3:
                path = QPainterPath()
                path.moveTo(*o.points[0])
                for pt in o.points[1:]:
                    path.lineTo(*pt)
                path.closeSubpath()
                if path.contains(logical_pt):
                    matched = True
                    area = max(1e-18, o.duration * o.bandwidth)
            elif o.shape == OverlayShape.X_REGION:
                if o.t_start <= t <= o.t_end:
                    matched = True
                    area = o.duration * float(getattr(self, 'rate', 1e6))
            elif o.shape == OverlayShape.Y_REGION:
                if o.f_start <= f <= o.f_end:
                    matched = True
                    area = float(getattr(self, 'time_duration', 1.0)) * o.bandwidth
            elif o.shape == OverlayShape.LINE:
                if abs(t - o.t_start) <= t_tol:
                    matched = True
                    area = 0.0
            elif o.shape == OverlayShape.HLINE:
                if abs(f - o.f_start) <= f_tol:
                    matched = True
                    area = 0.0

            if matched:
                hits.append((-int(getattr(o, 'z_order', 8)), area, o))

        hits.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in hits]

    def inspect_overlay(self, overlay_or_id) -> None:
        """Open the visual OverlayInspectorDialog for the given Overlay or overlay id."""
        overlay = (
            overlay_or_id
            if isinstance(overlay_or_id, Overlay)
            else self._get_overlay_by_id(str(overlay_or_id))
        )
        if overlay is None:
            return
        from ..overlay_inspector import OverlayInspectorDialog
        dlg = OverlayInspectorDialog(overlay, parent_window=self, parent=self)
        dlg.exec()

    def _get_overlay_display_name(self, overlay: Overlay) -> str:
        """Return the overlay's display_str if non-empty, or a fallback like 'Overlay #1'."""
        if overlay.display_str and overlay.display_str.strip():
            return overlay.display_str.strip()
        for i, o in enumerate(getattr(self, "overlays", [])):
            if o.id == overlay.id:
                return f"Overlay #{i + 1}"
        sh = overlay._shape_name().title() if hasattr(overlay, "_shape_name") else "Overlay"
        return f"{sh} ({overlay.id[:6]})"

    def analyze_overlay_in_tab(self, overlay_or_id, tab_type: str = "time") -> None:
        """
        Extract the narrowband DDC'd IQ for *overlay_or_id* via `o.get_samples()`
        (down-converting `f_center` to `0 Hz` baseband, filtering to `bandwidth`,
        and resampling to `bandwidth`) and open it in a named tab
        `'<Overlay Name> - <Popup Type>'`.
        """
        from PyQt6.QtWidgets import QMessageBox
        from iqview.plugins.context import PluginContext

        overlay = (
            overlay_or_id
            if isinstance(overlay_or_id, Overlay)
            else self._get_overlay_by_id(str(overlay_or_id))
        )
        if overlay is None:
            return

        has_cached_iq = getattr(overlay, "iq", None) is not None and len(overlay.iq) > 0
        if not has_cached_iq and overlay.duration <= 0:
            QMessageBox.information(
                self, "Analyze Overlay",
                "This overlay does not span a non-zero time duration."
            )
            return

        if not has_cached_iq and hasattr(self, "_confirm_large_segment"):
            if not self._confirm_large_segment(overlay.t_start, overlay.t_end, tab_type.title()):
                return

        ctx = PluginContext(
            sample_rate=float(getattr(self, 'rate', 1.0) or 1.0),
            center_freq=float(getattr(self, 'fc', 0.0) or 0.0),
            t_start=overlay.t_start,
            t_end=overlay.t_end,
            f_start=overlay.f_start,
            f_end=overlay.f_end,
            extract_iq_cb=lambda t0, t1: self.extract_iq_segment(t0, t1),
        )

        seg, seg_fs = overlay.get_samples(samples=None, info=ctx)
        if seg is None or len(seg) == 0:
            QMessageBox.warning(
                self, "Analyze Overlay",
                "Could not extract IQ samples for this overlay's time bounds."
            )
            return

        overlay_name = self._get_overlay_display_name(overlay)
        mode = tab_type.lower()
        view = None
        type_label = "Time Domain"

        if mode == "time":
            from ..time_domain.view import TimeDomainView
            type_label = "Time Domain"
            view = TimeDomainView(seg, overlay.t_start, seg_fs, parent_window=self)
        elif mode == "freq":
            from ..frequency_domain.view import FrequencyDomainView
            type_label = "Freq Domain"
            fc_tab = 0.0 if overlay.bandwidth > 0 else getattr(self, 'fc', 0.0)
            view = FrequencyDomainView(seg, fc_tab, seg_fs, parent_window=self)
        elif mode == "eye":
            from ..eye_diagram_dialog import EyeDiagramView
            type_label = "Eye Diagram"
            view = EyeDiagramView(seg, seg_fs, parent_window=self)
        elif mode in ("constellation", "scatter"):
            from ..constellation_dialog import ConstellationView
            type_label = "Scatter Plot"
            view = ConstellationView(seg, seg_fs, parent_window=self)

        if view is not None:
            tab_title = f"{overlay_name} - {type_label}"
            view._custom_tab_title = tab_title
            self.tabs.addTab(view, tab_title)
            self.tabs.setCurrentWidget(view)
            self.update_tab_names()

    def sync_multi_row_overlays(self) -> None:
        if hasattr(self, 'multi_row_view') and hasattr(self, 'spectrogram_stack') and self.spectrogram_stack.currentIndex() == 1:
            self.multi_row_view.sync_overlays(self.overlays, self.spectrogram_view.is_waterfall)



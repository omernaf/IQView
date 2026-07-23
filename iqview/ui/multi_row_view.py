"""Multi-row stacked spectrogram view for periodic signal analysis."""
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QScrollArea, QLabel,
                              QSizePolicy)


class MultiRowSpectrogramView(QWidget):
    """Displays N spectrogram rows stacked vertically, each showing a
    different time segment of the same IQ file.

    Design notes
    ------------
    * Frequency axis zoom is **synchronized** across all rows (same absolute
      Hz range for all rows) via a ``sigRangeChanged`` handler with a
      ``_syncing`` boolean guard to prevent recursive feedback loops.
    * Time axis is **not** synchronized — each row covers its own absolute
      time segment, so time zoom is per-row.
    * pyqtgraph widgets do NOT inherit Qt stylesheets.  All theming is done
      via explicit pyqtgraph API calls (``setBackground``, ``setPen``, etc.)
      inside ``refresh_theme()``.
    """

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        # Pool of row dicts: {widget, plot, img, label, t_start, t_end, marker_items}
        self.rows = []
        # Guard that prevents recursive sigRangeChanged loops during freq sync
        self._syncing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._outer_layout = outer

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(4, 4, 4, 4)
        self._inner_layout.setSpacing(6)
        self._scroll.setWidget(self._inner)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _palette(self):
        """Return the current theme Palette object."""
        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
        from .themes import get_palette
        return get_palette(theme)

    def _make_range_handler(self, row_idx):
        """Return a slot that syncs the freq axis when row *row_idx* changes."""
        def _handler(*args):
            self._on_row_range_changed(row_idx)
        return _handler

    def get_viewbox_for_scene_pos(self, scene_pos):
        """Return (viewbox, row_idx) for the row whose scene contains *scene_pos*.

        Used by place_marker() to identify which row was clicked.
        Returns (None, -1) if no row matches.
        """
        for i, row in enumerate(self.rows):
            if row['plot'].sceneBoundingRect().contains(scene_pos):
                return row['plot'].vb, i
        return None, -1

    # ------------------------------------------------------------------
    # Row widget pool
    # ------------------------------------------------------------------

    def _ensure_rows(self, n):
        """Grow or shrink the pool so exactly *n* row widgets exist."""
        p = self._palette()
        from .widgets import CustomViewBox

        while len(self.rows) < n:
            idx = len(self.rows)

            # -- Row title label --
            label = QLabel()
            label.setFixedHeight(18)
            label.setStyleSheet(
                f"color: {p.text_dim}; font-size: 10px; "
                f"background-color: {p.bg_main}; padding: 2px 4px;"
            )

            # -- PlotWidget with CustomViewBox so all interactions match the main view --
            vb = CustomViewBox(ui_controller=self.parent_window)
            pw = pg.PlotWidget(viewBox=vb)
            pw.setBackground(p.plot_bg)   # explicit theme — CSS doesn't reach pyqtgraph
            pw.setMenuEnabled(False)       # CustomViewBox provides its own right-click menu
            pw.hideButtons()
            # Disable default pan/zoom; CustomViewBox handles all mouse interaction
            pw.setMouseEnabled(x=False, y=False)
            pi = pw.getPlotItem()
            pi.setContentsMargins(0, 0, 0, 0)
            pi.getViewBox().setDefaultPadding(0)
            pi.showGrid(x=False, y=False)

            # Axis pen / text pen (pyqtgraph API — CSS doesn't work here)
            for ax_name in ('left', 'bottom'):
                ax = pi.getAxis(ax_name)
                ax.setPen(p.text_dim)
                ax.setTextPen(p.text_dim)

            pi.setLabel('bottom', "Time",      units='s')
            pi.setLabel('left',   "Frequency", units='Hz')

            img = pg.ImageItem()
            img.setZValue(-100)
            pw.addItem(img)

            pw.setMinimumHeight(100)
            pw.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)

            self._inner_layout.addWidget(label)
            self._inner_layout.addWidget(pw)

            # Connect freq-range sync — use factory to avoid late-binding
            pi.getViewBox().sigRangeChanged.connect(
                self._make_range_handler(idx)
            )

            self.rows.append({
                'widget': pw,
                'plot':   pi,
                'img':    img,
                'label':  label,
                't_start': 0.0,
                't_end':   1.0,
                'marker_items': [],
            })

        # Remove excess row widgets (pop from tail)
        while len(self.rows) > n:
            row = self.rows.pop()
            self._clear_row_markers(row)
            for w in (row['label'], row['widget']):
                self._inner_layout.removeWidget(w)
                w.hide()
                w.deleteLater()

    # ------------------------------------------------------------------
    # Frequency axis synchronization & sidebar feedback
    # ------------------------------------------------------------------

    def _on_row_range_changed(self, source_idx):
        """Sync frequency and time zoom across all rows when one row changes."""
        if self._syncing:
            return
        if source_idx >= len(self.rows):
            return

        vb = self.rows[source_idx]['plot'].getViewBox()
        xr, yr = vb.viewRange()

        is_waterfall = self.parent_window.spectrogram_view.is_waterfall
        freq_range = xr if is_waterfall else yr
        time_range = yr if is_waterfall else xr

        s_row = self.rows[source_idx]
        s_duration = s_row['t_end'] - s_row['t_start']

        if s_duration > 0:
            rel_start = (time_range[0] - s_row['t_start']) / s_duration
            rel_end   = (time_range[1] - s_row['t_start']) / s_duration
        else:
            rel_start, rel_end = 0.0, 1.0

        rel_start = float(np.clip(rel_start, 0.0, 1.0))
        rel_end   = float(np.clip(rel_end, rel_start + 1e-6, 1.0))
        self._current_rel_time = (rel_start, rel_end)

        self._syncing = True
        try:
            for i, row in enumerate(self.rows):
                if i == source_idx:
                    continue
                r_dur = row['t_end'] - row['t_start']
                new_t0 = row['t_start'] + rel_start * r_dur
                new_t1 = row['t_start'] + rel_end * r_dur

                vb_other = row['plot'].getViewBox()
                vb_other.blockSignals(True)
                try:
                    if is_waterfall:
                        row['plot'].setXRange(freq_range[0], freq_range[1], padding=0)
                        row['plot'].setYRange(new_t0, new_t1, padding=0)
                    else:
                        row['plot'].setXRange(new_t0, new_t1, padding=0)
                        row['plot'].setYRange(freq_range[0], freq_range[1], padding=0)
                finally:
                    vb_other.blockSignals(False)
        finally:
            self._syncing = False

        # Update sidebar text inputs (frequency & time/sample ranges)
        self._update_sidebar_inputs(freq_range[0], freq_range[1], rel_start, rel_end)

        # Trigger resolution re-render for the zoomed time window
        if hasattr(self.parent_window, '_schedule_multirow_rerender'):
            self.parent_window._schedule_multirow_rerender()

    def _update_sidebar_inputs(self, f_lo, f_hi, rel_start=0.0, rel_end=1.0):
        """Update Freq Min, Freq Max, Start Sample, and Samples Per Row text fields in sidebar."""
        sb = getattr(self.parent_window, 'sidebar', None)
        if not sb:
            return

        if hasattr(sb, 'freq_min_edit') and hasattr(sb, 'freq_max_edit'):
            sb.freq_min_edit.set_hz(f_lo)
            sb.freq_max_edit.set_hz(f_hi)

        if hasattr(sb, 'start_sample_edit') and hasattr(sb, 'samples_per_row_edit') and len(self.rows) > 0:
            fs = max(getattr(self.parent_window, 'rate', 1.0), 1.0)
            base_start = getattr(self.parent_window, '_multirow_start_sample', 0)
            base_spr   = getattr(self.parent_window, '_multirow_samples_per_row', 0)

            active_start_sample = base_start + int(round(rel_start * base_spr))
            active_spr          = max(1, int(round((rel_end - rel_start) * base_spr)))

            sb.start_sample_edit.blockSignals(True)
            sb.samples_per_row_edit.blockSignals(True)
            sb.start_sample_edit.setText(str(active_start_sample))
            sb.samples_per_row_edit.setText(str(active_spr))
            sb.start_sample_edit.blockSignals(False)
            sb.samples_per_row_edit.blockSignals(False)

    def set_freq_range(self, f_lo, f_hi):
        """Programmatically zoom all rows to the given frequency range."""
        fc   = getattr(self.parent_window, 'fc', 0.0)
        rate = getattr(self.parent_window, 'rate', 1.0)
        f_min_def = fc - rate / 2.0
        f_max_def = fc + rate / 2.0

        f_lo = float(np.clip(f_lo, f_min_def, f_max_def - 1.0))
        f_hi = float(np.clip(f_hi, f_lo + 1.0, f_max_def))

        is_waterfall = self.parent_window.spectrogram_view.is_waterfall
        self._syncing = True
        try:
            for row in self.rows:
                vb_other = row['plot'].getViewBox()
                vb_other.blockSignals(True)
                try:
                    if is_waterfall:
                        row['plot'].setXRange(f_lo, f_hi, padding=0)
                    else:
                        row['plot'].setYRange(f_lo, f_hi, padding=0)
                finally:
                    vb_other.blockSignals(False)
        finally:
            self._syncing = False
        self._update_sidebar_inputs(f_lo, f_hi)

    # ------------------------------------------------------------------
    # Zoom controls (delegated from view_controller)
    # ------------------------------------------------------------------

    def reset_zoom(self):
        """Reset multi-row view and sidebar inputs back to full default extent."""
        self._current_rel_time = (0.0, 1.0)
        fc = self.parent_window.fc
        rate = self.parent_window.rate
        f_lo = fc - rate / 2.0
        f_hi = fc + rate / 2.0

        # Calculate default multi-row sample parameters
        total = self.parent_window.get_total_samples() if hasattr(self.parent_window, 'get_total_samples') else 0
        num_rows = max(1, len(self.rows))
        default_spr = max(1, total // num_rows) if total > 0 else 0
        default_period = default_spr

        self.parent_window._multirow_start_sample   = 0
        self.parent_window._multirow_samples_per_row = default_spr
        self.parent_window._multirow_period         = default_period

        sb = getattr(self.parent_window, 'sidebar', None)
        if sb:
            if hasattr(sb, 'start_sample_edit'):
                sb.start_sample_edit.blockSignals(True)
                sb.start_sample_edit.setText("0")
                sb.start_sample_edit.blockSignals(False)
            if hasattr(sb, 'samples_per_row_edit'):
                sb.samples_per_row_edit.blockSignals(True)
                sb.samples_per_row_edit.setText(str(default_spr))
                sb.samples_per_row_edit.blockSignals(False)
            if hasattr(sb, 'period_edit'):
                sb.period_edit.blockSignals(True)
                sb.period_edit.setText(str(default_period))
                sb.period_edit.blockSignals(False)
            if hasattr(sb, 'freq_min_edit') and hasattr(sb, 'freq_max_edit'):
                sb.freq_min_edit.set_hz(f_lo)
                sb.freq_max_edit.set_hz(f_hi)

        if self.parent_window._has_data():
            self.parent_window.start_processing()
        else:
            self.set_freq_range(f_lo, f_hi)

    def reset_zoom_x(self):
        is_waterfall = self.parent_window.spectrogram_view.is_waterfall
        if is_waterfall:
            # X is freq
            fc = self.parent_window.fc
            rate = self.parent_window.rate
            self.set_freq_range(fc - rate / 2.0, fc + rate / 2.0)
        else:
            # X is time — reset each row's time range
            for row in self.rows:
                row['plot'].setXRange(row['t_start'], row['t_end'], padding=0)

    def reset_zoom_y(self):
        is_waterfall = self.parent_window.spectrogram_view.is_waterfall
        if is_waterfall:
            # Y is time — reset each row's time range
            for row in self.rows:
                row['plot'].setYRange(row['t_start'], row['t_end'], padding=0)
        else:
            # Y is freq
            fc = self.parent_window.fc
            rate = self.parent_window.rate
            self.set_freq_range(fc - rate / 2.0, fc + rate / 2.0)

    def handle_zoom_rectangle(self, rect, zoom_type='BOTH', source_vb=None):
        """Handle rubberband zoom box on multi-row view."""
        is_waterfall = self.parent_window.spectrogram_view.is_waterfall

        # Determine frequency and time components of rect
        if is_waterfall:
            # X = freq, Y = time
            f_lo, f_hi = min(rect.left(), rect.right()), max(rect.left(), rect.right())
            t_lo, t_hi = min(rect.top(), rect.bottom()), max(rect.top(), rect.bottom())
            zoom_freq = (zoom_type in ['BOTH', 'X_ONLY']) and (abs(f_hi - f_lo) > 0)
            zoom_time = (zoom_type in ['BOTH', 'Y_ONLY']) and (abs(t_hi - t_lo) > 0)
        else:
            # X = time, Y = freq
            t_lo, t_hi = min(rect.left(), rect.right()), max(rect.left(), rect.right())
            f_lo, f_hi = min(rect.top(), rect.bottom()), max(rect.top(), rect.bottom())
            zoom_freq = (zoom_type in ['BOTH', 'Y_ONLY']) and (abs(f_hi - f_lo) > 0)
            zoom_time = (zoom_type in ['BOTH', 'X_ONLY']) and (abs(t_hi - t_lo) > 0)

        if zoom_freq:
            self.set_freq_range(f_lo, f_hi)

        if zoom_time and source_vb:
            if is_waterfall:
                source_vb.setYRange(t_lo, t_hi, padding=0)
            else:
                source_vb.setXRange(t_lo, t_hi, padding=0)

    def fit_to_markers(self, active_markers):
        """Zoom to fit the given pair of active markers."""
        if len(active_markers) != 2:
            return

        v1, v2 = active_markers[0].value(), active_markers[1].value()
        v_min, v_max = min(v1, v2), max(v1, v2)
        if v_min == v_max:
            return

        is_freq = (self.parent_window.interaction_mode in ['FREQ', 'FREQ_ENDLESS'])
        if is_freq:
            self.set_freq_range(v_min, v_max)
        else:
            is_waterfall = self.parent_window.spectrogram_view.is_waterfall
            for row in self.rows:
                # Clamp to row's time segment
                t_lo = max(v_min, row['t_start'])
                t_hi = min(v_max, row['t_end'])
                if t_hi > t_lo:
                    if is_waterfall:
                        row['plot'].setYRange(t_lo, t_hi, padding=0)
                    else:
                        row['plot'].setXRange(t_lo, t_hi, padding=0)

    # ------------------------------------------------------------------
    # Marker synchronization across all rows
    # ------------------------------------------------------------------

    def _clear_row_markers(self, row):
        """Remove all synced InfiniteLines from *row*."""
        for item in row.get('marker_items', []):
            try:
                row['plot'].removeItem(item)
            except Exception:
                pass
        row['marker_items'] = []

    def sync_markers(self, markers_time, markers_freq, is_waterfall, theme, settings_mgr):
        """Re-render all time and frequency markers across all rows."""
        style_map = {
            "SolidLine": Qt.PenStyle.SolidLine,
            "DashLine": Qt.PenStyle.DashLine,
            "DotLine": Qt.PenStyle.DotLine,
            "DashDotLine": Qt.PenStyle.DashDotLine
        }
        t_color = settings_mgr.get(f"ui/{theme}/time_marker_color")
        t_style = style_map.get(str(settings_mgr.get(f"ui/{theme}/time_marker_style")), Qt.PenStyle.DashLine)
        t_angle = 0 if is_waterfall else 90

        f_color = settings_mgr.get(f"ui/{theme}/freq_marker_color")
        f_style = style_map.get(str(settings_mgr.get(f"ui/{theme}/freq_marker_style")), Qt.PenStyle.DashLine)
        f_angle = 90 if is_waterfall else 0

        t_pen = pg.mkPen(t_color, width=2, style=t_style)
        f_pen = pg.mkPen(f_color, width=2, style=f_style)

        for row in self.rows:
            self._clear_row_markers(row)
            items = []

            # 1. Frequency markers — appear on ALL rows at position F
            for m in markers_freq:
                f_val = m.value()
                line = pg.InfiniteLine(pos=f_val, angle=f_angle, movable=False, pen=f_pen)
                line.setZValue(10)
                row['plot'].addItem(line, ignoreBounds=True)
                items.append(line)

            # 2. Time markers — appear on row IF time T is inside [row['t_start'], row['t_end']]
            for m in markers_time:
                t_val = m.value()
                if row['t_start'] <= t_val <= row['t_end']:
                    line = pg.InfiniteLine(pos=t_val, angle=t_angle, movable=False, pen=t_pen)
                    line.setZValue(10)
                    row['plot'].addItem(line, ignoreBounds=True)
                    items.append(line)

            row['marker_items'] = items

    def _clear_row_overlays(self, row):
        """Remove all synced overlay items from *row*."""
        for item in row.get('overlay_items', []):
            try:
                row['plot'].removeItem(item)
            except Exception:
                pass
        row['overlay_items'] = []

    def sync_overlays(self, overlays, is_waterfall):
        """Re-render all overlays across all rows."""
        from .overlay import OverlayItem, OverlayShape

        for row in self.rows:
            self._clear_row_overlays(row)
            items = []
            t_s, t_e = row['t_start'], row['t_end']

            for o in overlays:
                if not getattr(o, 'visible', True):
                    continue

                shape = getattr(o, 'shape', None)

                if shape in [OverlayShape.LINE, "LINE"]:
                    t_val = o.points[0][0] if o.points else (o.center[0] if o.center else 0.0)
                    if t_s <= t_val <= t_e:
                        line = pg.InfiniteLine(pos=t_val, angle=(0 if is_waterfall else 90), movable=False, pen=pg.mkPen(o.color, width=o.border_width))
                        line.setZValue(getattr(o, 'z_order', 8))
                        row['plot'].addItem(line, ignoreBounds=True)
                        items.append(line)

                elif shape in [OverlayShape.HLINE, "HLINE"]:
                    f_val = o.points[0][1] if o.points else (o.center[1] if o.center else 0.0)
                    line = pg.InfiniteLine(pos=f_val, angle=(90 if is_waterfall else 0), movable=False, pen=pg.mkPen(o.color, width=o.border_width))
                    line.setZValue(getattr(o, 'z_order', 8))
                    row['plot'].addItem(line, ignoreBounds=True)
                    items.append(line)

                else:
                    t_min_o, t_max_o = -1e9, 1e9
                    if o.points:
                        t_coords = [p[0] for p in o.points]
                        t_min_o, t_max_o = min(t_coords), max(t_coords)
                    elif o.center and o.radii:
                        t_min_o = o.center[0] - o.radii[0]
                        t_max_o = o.center[0] + o.radii[0]

                    if shape == OverlayShape.Y_REGION or (t_max_o >= t_s and t_min_o <= t_e):
                        item = OverlayItem(o, is_waterfall=is_waterfall)
                        row['plot'].addItem(item)
                        items.append(item)

            row['overlay_items'] = items

    # ------------------------------------------------------------------
    # Main display update
    # ------------------------------------------------------------------

    def update_spectrograms(self, spectra, fc, rate,
                            read_start_samples, read_spr,
                            vis_start_samples=None, vis_spr=None):
        """Render one spectrogram per row with 300% buffer for seamless dragging."""
        n = len(spectra)
        if n == 0:
            return

        self._ensure_rows(n)

        if vis_start_samples is None:
            vis_start_samples = read_start_samples
        if vis_spr is None:
            vis_spr = read_spr

        f_min = fc - rate / 2.0
        sr    = max(rate, 1.0)

        # Retrieve requested freq min / max from sidebar if custom range is set
        sb = getattr(self.parent_window, 'sidebar', None)
        custom_freq = False
        if sb and hasattr(sb, 'freq_min_edit') and hasattr(sb, 'freq_max_edit'):
            f_lo_req = sb.freq_min_edit.get_hz()
            f_hi_req = sb.freq_max_edit.get_hz()
            if f_lo_req < f_hi_req and (abs(f_lo_req - f_min) > 1.0 or abs(f_hi_req - (f_min + rate)) > 1.0):
                custom_freq = True

        # ---- Levels and colormap from the main spectrogram histogram ----
        sv     = self.parent_window.spectrogram_view
        levels = list(sv.level_region.getRegion())

        # Auto-initialize levels if they are still at default [0.0, 1.0]
        if abs(levels[0]) < 1e-6 and abs(levels[1] - 1.0) < 1e-6:
            valid_chunks = [s.ravel()[s.ravel() > -190.0] for s in spectra]
            valid_chunks = [c for c in valid_chunks if len(c) > 0]
            if valid_chunks:
                combined = np.concatenate(valid_chunks)
                lo = float(np.percentile(combined, 2))
                hi = float(np.percentile(combined, 98))
                levels = [lo, hi]
                sv.level_region.setRegion([lo, hi])

        cmap         = sv.gradient.colorMap()
        is_waterfall = sv.is_waterfall

        # Block range-changed callbacks during bulk image update
        self._syncing = True
        try:
            for i, (spec, row) in enumerate(zip(spectra, self.rows)):
                s_read = int(read_start_samples[i]) if i < len(read_start_samples) else 0
                t_read_start  = s_read / sr
                t_read_end    = (s_read + read_spr) / sr
                read_duration = max(t_read_end - t_read_start, 1.0 / sr)

                s_vis = int(vis_start_samples[i]) if i < len(vis_start_samples) else s_read
                t_vis_start = s_vis / sr
                t_vis_end   = (s_vis + vis_spr) / sr

                row['t_start'] = t_read_start
                row['t_end']   = t_read_end

                # -- Label --
                if n > 1:
                    row['label'].setText(
                        f"Row {i + 1}  │  Samples {s_vis:,} – "
                        f"{s_vis + vis_spr:,}"
                        f"  │  {t_vis_start:.4f}s – {t_vis_end:.4f}s"
                    )
                    row['label'].setVisible(True)
                else:
                    row['label'].setVisible(False)

                # -- Image and axes --
                f_view_lo = f_lo_req if custom_freq else f_min
                f_view_hi = f_hi_req if custom_freq else (f_min + rate)

                vb_curr = row['plot'].getViewBox()
                vb_curr.blockSignals(True)
                try:
                    if is_waterfall:
                        display = np.ascontiguousarray(spec.T)
                        row['img'].setImage(display, autoLevels=False,
                                           levels=levels, autoDownsample=True)
                        row['img'].setRect(QRectF(f_min, t_read_start, rate, read_duration))
                        row['plot'].setLabel('bottom', "Frequency", units='Hz')
                        row['plot'].setLabel('left',   "Time",      units='s')
                        row['plot'].getViewBox().invertY(True)
                        row['plot'].setXRange(f_view_lo, f_view_hi, padding=0)
                        row['plot'].setYRange(t_vis_start, t_vis_end, padding=0)
                    else:
                        row['img'].setImage(spec, autoLevels=False,
                                           levels=levels, autoDownsample=True)
                        row['img'].setRect(QRectF(t_read_start, f_min, read_duration, rate))
                        row['plot'].setLabel('bottom', "Time",      units='s')
                        row['plot'].setLabel('left',   "Frequency", units='Hz')
                        row['plot'].getViewBox().invertY(False)
                        row['plot'].setXRange(t_vis_start, t_vis_end, padding=0)
                        row['plot'].setYRange(f_view_lo, f_view_hi, padding=0)
                finally:
                    vb_curr.blockSignals(False)

                row['img'].setColorMap(cmap)
                row['img'].setLevels(levels)

            self._current_rel_time = (0.0, 1.0)
        finally:
            self._syncing = False

    def apply_levels_and_colormap(self):
        """Copy levels and colormap from the main SpectrogramView to all rows."""
        sv = getattr(self.parent_window, 'spectrogram_view', None)
        if not sv:
            return
        try:
            levels = sv.level_region.getRegion()
        except Exception:
            levels = [-100, 0]
        try:
            cmap = sv.gradient.colorMap()
        except Exception:
            cmap = None

        for row in self.rows:
            row['img'].setLevels(levels)
            if cmap is not None:
                row['img'].setColorMap(cmap)
            row['img'].update()
            row['widget'].update()

    def pan_view(self, dx, dy):
        """Pan all multi-row plots in real time during mouse drag."""
        if len(self.rows) == 0:
            return

        is_waterfall = self.parent_window.spectrogram_view.is_waterfall
        fc   = self.parent_window.fc
        rate = max(self.parent_window.rate, 1.0)
        f_min_bounds = fc - rate / 2.0
        f_max_bounds = fc + rate / 2.0

        dt = dx if not is_waterfall else dy
        df = dy if not is_waterfall else dx

        base_start = getattr(self.parent_window, '_multirow_start_sample', 0)
        base_spr   = getattr(self.parent_window, '_multirow_samples_per_row', 0)
        fs         = max(self.parent_window.rate, 1.0)
        base_dur   = (base_spr / fs) if base_spr > 0 else 1.0

        row0 = self.rows[0]
        xr0, yr0 = row0['plot'].viewRange()
        f_curr = xr0 if is_waterfall else yr0

        r0, r1 = getattr(self, '_current_rel_time', (0.0, 1.0))
        rel_span = r1 - r0

        vis_ratio_freq = (f_curr[1] - f_curr[0]) / rate

        # 1. Frequency Panning (only if zoomed in on frequency)
        if vis_ratio_freq <= 0.999 and df != 0.0:
            f_span = f_curr[1] - f_curr[0]
            new_f0 = f_curr[0] - df
            new_f1 = f_curr[1] - df
            if new_f0 < f_min_bounds:
                new_f0, new_f1 = f_min_bounds, f_min_bounds + f_span
            elif new_f1 > f_max_bounds:
                new_f0, new_f1 = f_max_bounds - f_span, f_max_bounds
            self.set_freq_range(new_f0, new_f1)

        # 2. Time Panning / File Scrolling
        if dt != 0.0:
            if rel_span <= 0.999:
                # Zoomed in: pan relative fraction (r0, r1)
                dt_rel = dt / max(base_dur, 1e-9)
                new_r0 = float(np.clip(r0 - dt_rel, 0.0, 1.0 - rel_span))
                new_r1 = float(np.clip(new_r0 + rel_span, rel_span, 1.0))
                self._current_rel_time = (new_r0, new_r1)

                self._syncing = True
                try:
                    for row in self.rows:
                        t_s, t_e = row['t_start'], row['t_end']
                        dur = t_e - t_s
                        v0 = t_s + (new_r0 - r0) / max(rel_span, 1e-9) * dur
                        v1 = v0 + dur
                        vb_other = row['plot'].getViewBox()
                        vb_other.blockSignals(True)
                        try:
                            if is_waterfall:
                                row['plot'].setYRange(v0, v1, padding=0)
                            else:
                                row['plot'].setXRange(v0, v1, padding=0)
                        finally:
                            vb_other.blockSignals(False)
                finally:
                    self._syncing = False

                self._update_sidebar_inputs(f_curr[0], f_curr[1], new_r0, new_r1)
            else:
                # Unzoomed (100%): scroll file start_sample
                delta_samples = int(round(dt * fs))
                curr_start = getattr(self.parent_window, '_multirow_start_sample', 0)
                total_samples = self.parent_window.get_total_samples() if hasattr(self.parent_window, 'get_total_samples') else 0
                max_start = max(0, total_samples - base_spr) if total_samples > 0 else 1e9

                new_start = int(np.clip(curr_start - delta_samples, 0, max_start))
                if new_start != curr_start:
                    self.parent_window._multirow_start_sample = new_start
                    sb = getattr(self.parent_window, 'sidebar', None)
                    if sb and hasattr(sb, 'start_sample_edit'):
                        sb.start_sample_edit.blockSignals(True)
                        sb.start_sample_edit.setText(str(new_start))
                        sb.start_sample_edit.blockSignals(False)

                    period = getattr(self.parent_window, '_multirow_period', base_spr)
                    if period <= 0: period = base_spr

                    self._syncing = True
                    try:
                        for i, row in enumerate(self.rows):
                            row_s_idx = new_start + i * period
                            t_s = row_s_idx / fs
                            t_e = (row_s_idx + base_spr) / fs
                            row['t_start'] = t_s
                            row['t_end']   = t_e
                            vb_other = row['plot'].getViewBox()
                            vb_other.blockSignals(True)
                            try:
                                if is_waterfall:
                                    row['plot'].setYRange(t_s, t_e, padding=0)
                                else:
                                    row['plot'].setXRange(t_s, t_e, padding=0)
                            finally:
                                vb_other.blockSignals(False)
                    finally:
                        self._syncing = False

        # Sync existing markers and overlays to the new row layout
        self.sync_markers(
            getattr(self.parent_window, 'markers_time', []),
            getattr(self.parent_window, 'markers_freq', []),
            is_waterfall,
            self.parent_window.settings_mgr.get("ui/theme", "Dark").lower(),
            self.parent_window.settings_mgr
        )
        self.sync_overlays(getattr(self.parent_window, 'overlays', []), is_waterfall)

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def refresh_theme(self):
        """Apply theme to all row widgets using pyqtgraph's native API."""
        p = self._palette()

        self._scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {p.bg_main}; border: none; }}"
        )
        self._inner.setStyleSheet(
            f"QWidget {{ background-color: {p.bg_main}; }}"
        )

        for row in self.rows:
            row['widget'].setBackground(p.plot_bg)
            row['label'].setStyleSheet(
                f"color: {p.text_dim}; font-size: 10px; "
                f"background-color: {p.bg_main}; padding: 2px 4px;"
            )
            for ax_name in ('left', 'bottom'):
                ax = row['plot'].getAxis(ax_name)
                ax.setPen(p.text_dim)
                ax.setTextPen(p.text_dim)

    # ------------------------------------------------------------------
    # Waterfall / orientation toggle
    # ------------------------------------------------------------------

    def apply_waterfall_mode(self):
        """No-op: re-rendering is triggered by start_processing()."""
        pass

    # ------------------------------------------------------------------
    # Key event forwarding
    # ------------------------------------------------------------------

    def keyPressEvent(self, ev):
        """Forward key presses to the parent window so T/F/Ctrl shortcuts work."""
        self.parent_window.keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        """Forward key releases to the parent window."""
        self.parent_window.keyReleaseEvent(ev)

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
        v_start = s_row.get('t_vis_start', s_row['t_start'])
        v_end   = s_row.get('t_vis_end', s_row['t_end'])
        s_duration = max(v_end - v_start, 1e-9)

        rel_start = (time_range[0] - v_start) / s_duration
        rel_end   = (time_range[1] - v_start) / s_duration

        rel_start = float(np.clip(rel_start, 0.0, 1.0))
        rel_end   = float(np.clip(rel_end, rel_start + 1e-6, 1.0))

        # Push state to zoom history before updating
        if hasattr(self.parent_window, 'push_multirow_zoom_state'):
            self.parent_window.push_multirow_zoom_state()

        self._current_rel_time = (rel_start, rel_end)

        self._syncing = True
        try:
            for i, row in enumerate(self.rows):
                if i == source_idx:
                    continue
                r_v_start = row.get('t_vis_start', row['t_start'])
                r_v_end   = row.get('t_vis_end', row['t_end'])
                r_dur     = max(r_v_end - r_v_start, 1e-9)
                new_t0    = r_v_start + rel_start * r_dur
                new_t1    = r_v_start + rel_end * r_dur

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

    def sync_markers(self, markers_time, markers_freq, is_waterfall, theme, settings_mgr, grid_time=None, grid_freq=None, filter_bounds=None, filter_line_pos=None):
        """Re-render all time, frequency, grid markers, and filter region/bound markers across all rows."""
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

        # Grid line styling
        g_color = settings_mgr.get(f"ui/{theme}/marker_grid_color", "#c8c8ff")
        g_style_name = settings_mgr.get(f"ui/{theme}/marker_grid_style", "SolidLine")
        g_style = style_map.get(str(g_style_name), Qt.PenStyle.SolidLine)
        g_alpha = int(settings_mgr.get("ui/marker_grid_alpha", 50))
        g_width = int(settings_mgr.get("ui/marker_grid_width", 1))

        qg_color = pg.mkColor(g_color)
        qg_color.setAlpha(g_alpha)
        g_pen = pg.mkPen(qg_color, width=g_width, style=g_style)

        filter_pen = pg.mkPen('#ff6400', width=2, style=Qt.PenStyle.DashLine)

        grid_time = grid_time or []
        grid_freq = grid_freq or []

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

            # 3. Frequency Grid lines (Shadow Markers) — appear on ALL rows
            for gl in grid_freq:
                f_val = gl.value()
                line = pg.InfiniteLine(pos=f_val, angle=f_angle, movable=False, pen=g_pen)
                line.setZValue(5)
                row['plot'].addItem(line, ignoreBounds=True)
                items.append(line)

            # 4. Time Grid lines (Shadow Markers) — appear on row IF time T is inside [row['t_start'], row['t_end']]
            for gl in grid_time:
                t_val = gl.value()
                if row['t_start'] <= t_val <= row['t_end']:
                    line = pg.InfiniteLine(pos=t_val, angle=t_angle, movable=False, pen=g_pen)
                    line.setZValue(5)
                    row['plot'].addItem(line, ignoreBounds=True)
                    items.append(line)

            # 5. Filter preview line (1 bound marker placed) — appear on ALL rows
            if filter_line_pos is not None:
                line = pg.InfiniteLine(pos=filter_line_pos, angle=f_angle, movable=False, pen=filter_pen)
                line.setZValue(9)
                row['plot'].addItem(line, ignoreBounds=True)
                items.append(line)

            # 6. Filter region and bound markers (2 bound markers placed) — appear on ALL rows
            if filter_bounds is not None and len(filter_bounds) == 2:
                f1, f2 = filter_bounds[0], filter_bounds[1]
                region = pg.LinearRegionItem(
                    values=[f1, f2],
                    orientation=(0 if is_waterfall else 1),
                    brush=pg.mkBrush(255, 100, 0, 40),
                    pen=pg.mkPen('#ff6400', width=2),
                    movable=False
                )
                region.setZValue(9)
                row['plot'].addItem(region)
                items.append(region)

            row['marker_items'] = items

    def _clear_row_overlays(self, row):
        """Remove all synced overlay items from *row*."""
        for item in row.get('overlay_items', []):
            try:
                if hasattr(item, 'detach_from_plot'):
                    item.detach_from_plot()
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
                z_ord = getattr(o, 'z_order', 8)

                if shape in [OverlayShape.LINE, "LINE"]:
                    t_val = o.points[0][0] if o.points else (o.center[0] if o.center else 0.0)
                    if t_s <= t_val <= t_e:
                        line = pg.InfiniteLine(pos=t_val, angle=(0 if is_waterfall else 90), movable=False, pen=pg.mkPen(o.color, width=o.border_width))
                        line.setZValue(z_ord)
                        row['plot'].addItem(line, ignoreBounds=True)
                        items.append(line)

                elif shape in [OverlayShape.HLINE, "HLINE"]:
                    f_val = o.points[0][1] if o.points else (o.center[1] if o.center else 0.0)
                    line = pg.InfiniteLine(pos=f_val, angle=(90 if is_waterfall else 0), movable=False, pen=pg.mkPen(o.color, width=o.border_width))
                    line.setZValue(z_ord)
                    row['plot'].addItem(line, ignoreBounds=True)
                    items.append(line)

                elif shape in [OverlayShape.X_REGION, "X_REGION"]:
                    t_min_o = min(o.points[0][0], o.points[1][0]) if len(o.points) >= 2 else 0.0
                    t_max_o = max(o.points[0][0], o.points[1][0]) if len(o.points) >= 2 else 0.0
                    if t_max_o >= t_s and t_min_o <= t_e:
                        c = pg.mkColor(o.color)
                        c.setAlphaF(getattr(o, 'alpha', 0.25))
                        reg = pg.LinearRegionItem(values=[t_min_o, t_max_o], orientation=(0 if is_waterfall else 1), brush=pg.mkBrush(c), pen=pg.mkPen(o.color, width=o.border_width), movable=False)
                        reg.setZValue(z_ord)
                        row['plot'].addItem(reg)
                        items.append(reg)

                elif shape in [OverlayShape.Y_REGION, "Y_REGION"]:
                    f_min_o = min(o.points[0][1], o.points[1][1]) if len(o.points) >= 2 else 0.0
                    f_max_o = max(o.points[0][1], o.points[1][1]) if len(o.points) >= 2 else 0.0
                    c = pg.mkColor(o.color)
                    c.setAlphaF(getattr(o, 'alpha', 0.25))
                    reg = pg.LinearRegionItem(values=[f_min_o, f_max_o], orientation=(1 if is_waterfall else 0), brush=pg.mkBrush(c), pen=pg.mkPen(o.color, width=o.border_width), movable=False)
                    reg.setZValue(z_ord)
                    row['plot'].addItem(reg)
                    items.append(reg)

                else:
                    t_min_o, t_max_o = -1e9, 1e9
                    if o.points:
                        t_coords = [p[0] for p in o.points]
                        t_min_o, t_max_o = min(t_coords), max(t_coords)
                    elif o.center and o.radii:
                        t_min_o = o.center[0] - o.radii[0]
                        t_max_o = o.center[0] + o.radii[0]

                    if t_max_o >= t_s and t_min_o <= t_e:
                        item = OverlayItem(o, waterfall=is_waterfall)
                        item.setZValue(z_ord)
                        item.setVisible(getattr(o, 'visible', True))
                        row['plot'].addItem(item)
                        item.attach_to_plot(row['plot'])
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

                row['t_start']     = t_read_start
                row['t_end']       = t_read_end
                row['t_vis_start'] = t_vis_start
                row['t_vis_end']   = t_vis_end

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
            levels = list(sv.level_region.getRegion())
        except Exception:
            levels = [-100.0, 0.0]
        try:
            cmap = sv.gradient.colorMap()
        except Exception:
            cmap = None

        for row in self.rows:
            if 'img' in row:
                row['img'].setLevels(levels)
                if cmap is not None:
                    row['img'].setColorMap(cmap)

    # ------------------------------------------------------------------
    # Single Source of Truth: Central Axis Update
    # ------------------------------------------------------------------

    def update_all_row_axes(self):
        """Update PlotItem XRange and YRange for all rows based on current state:
        _multirow_start_sample, _multirow_samples_per_row, _multirow_period,
        _current_rel_time, and _current_freq_range."""
        if not self.rows:
            return

        sr = max(getattr(self.parent_window, 'rate', 1.0), 1.0)
        fc = getattr(self.parent_window, 'fc', 0.0)

        start_s = getattr(self.parent_window, '_multirow_start_sample', 0)
        spr     = getattr(self.parent_window, '_multirow_samples_per_row', 0)
        period  = getattr(self.parent_window, '_multirow_period', spr)
        if spr <= 0:
            spr = 100000
        if period <= 0:
            period = spr

        rel_t0, rel_t1 = getattr(self, '_current_rel_time', (0.0, 1.0))
        f_min_default = fc - sr / 2.0
        f_max_default = fc + sr / 2.0
        f_lo, f_hi = getattr(self, '_current_freq_range', (f_min_default, f_max_default))

        is_waterfall = self.parent_window.spectrogram_view.is_waterfall

        self._syncing = True
        try:
            for i, row in enumerate(self.rows):
                row_start_s = start_s + i * period
                row_spr     = spr
                row_t0      = row_start_s / sr
                row_t_dur   = row_spr / sr

                t_vis_0 = row_t0 + rel_t0 * row_t_dur
                t_vis_1 = row_t0 + rel_t1 * row_t_dur

                row['t_vis_start'] = t_vis_0
                row['t_vis_end']   = t_vis_1

                if len(self.rows) > 1:
                    s_vis_0 = int(round(t_vis_0 * sr))
                    s_vis_1 = int(round(t_vis_1 * sr))
                    row['label'].setText(
                        f"Row {i + 1}  │  Samples {s_vis_0:,} – {s_vis_1:,}"
                        f"  │  {t_vis_0:.4f}s – {t_vis_1:.4f}s"
                    )

                if is_waterfall:
                    row['plot'].setXRange(f_lo, f_hi, padding=0)
                    row['plot'].setYRange(t_vis_0, t_vis_1, padding=0)
                else:
                    row['plot'].setXRange(t_vis_0, t_vis_1, padding=0)
                    row['plot'].setYRange(f_lo, f_hi, padding=0)
        finally:
            self._syncing = False

    # ------------------------------------------------------------------
    # Frequency axis synchronization & sidebar feedback
    # ------------------------------------------------------------------

    def _on_row_range_changed(self, source_idx):
        """Sync frequency and time zoom across all rows when one row changes."""
        if self._syncing:
            return
        if source_idx >= len(self.rows):
            return

        s_row = self.rows[source_idx]
        vb = s_row['plot'].getViewBox()
        xr, yr = vb.viewRange()

        is_waterfall = self.parent_window.spectrogram_view.is_waterfall
        freq_range = xr if is_waterfall else yr
        time_range = yr if is_waterfall else xr

        sr = max(getattr(self.parent_window, 'rate', 1.0), 1.0)
        start_s = getattr(self.parent_window, '_multirow_start_sample', 0)
        spr     = getattr(self.parent_window, '_multirow_samples_per_row', 0)
        period  = getattr(self.parent_window, '_multirow_period', spr)
        if spr <= 0: spr = 100000
        if period <= 0: period = spr

        row_t0    = (start_s + source_idx * period) / sr
        row_t_dur = max(1e-9, spr / sr)

        rel_t0 = float(np.clip((time_range[0] - row_t0) / row_t_dur, 0.0, 1.0))
        rel_t1 = float(np.clip((time_range[1] - row_t0) / row_t_dur, rel_t0 + 1e-6, 1.0))

        # Push state to zoom history before updating
        if hasattr(self.parent_window, 'push_multirow_zoom_state'):
            self.parent_window.push_multirow_zoom_state()

        self._current_rel_time   = (rel_t0, rel_t1)
        self._current_freq_range = (float(freq_range[0]), float(freq_range[1]))

        # Central update of ALL row axes
        self.update_all_row_axes()

        # Update sidebar text inputs
        active_start_s = start_s + int(round(rel_t0 * spr))
        active_spr     = max(1, int(round((rel_t1 - rel_t0) * spr)))
        self._update_sidebar_inputs(freq_range[0], freq_range[1], active_start_s, active_spr)

        # Sync markers & overlays across rows
        if hasattr(self.parent_window, 'sync_multi_row_markers'):
            self.parent_window.sync_multi_row_markers()
        if hasattr(self.parent_window, 'sync_multi_row_overlays'):
            self.parent_window.sync_multi_row_overlays()

        # Trigger resolution re-render for the zoomed time window
        if hasattr(self.parent_window, '_schedule_multirow_rerender'):
            self.parent_window._schedule_multirow_rerender()

    def _update_sidebar_inputs(self, f_lo, f_hi, base_start_sample=None, base_spr=None):
        """Update Freq Min, Freq Max, Start Sample, and Samples Per Row text fields in sidebar."""
        sb = getattr(self.parent_window, 'sidebar', None)
        if not sb:
            return

        if hasattr(sb, 'freq_min_edit') and hasattr(sb, 'freq_max_edit'):
            sb.freq_min_edit.set_hz(f_lo)
            sb.freq_max_edit.set_hz(f_hi)

        if hasattr(sb, 'start_sample_edit') and hasattr(sb, 'samples_per_row_edit'):
            if base_start_sample is None:
                base_start_sample = getattr(self.parent_window, '_multirow_start_sample', 0)
            if base_spr is None:
                base_spr = getattr(self.parent_window, '_multirow_samples_per_row', 0)

            sb.start_sample_edit.blockSignals(True)
            sb.samples_per_row_edit.blockSignals(True)
            sb.start_sample_edit.setText(str(base_start_sample))
            sb.samples_per_row_edit.setText(str(base_spr))
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

        self._current_freq_range = (f_lo, f_hi)
        self.update_all_row_axes()

    def pan_view_view_units(self, dx, dy):
        """Pan all multi-row plot axes using view-unit deltas (seconds, Hz)."""
        if len(self.rows) == 0:
            return

        is_waterfall = self.parent_window.spectrogram_view.is_waterfall
        fc   = self.parent_window.fc
        rate = max(self.parent_window.rate, 1.0)
        f_min_bounds = fc - rate / 2.0
        f_max_bounds = fc + rate / 2.0
        sr = max(self.parent_window.rate, 1.0)

        dt = dx if not is_waterfall else dy
        df = dy if not is_waterfall else dx

        curr_start = getattr(self.parent_window, '_multirow_start_sample', 0)
        delta_samples = int(round(dt * sr))
        base_spr = getattr(self.parent_window, '_multirow_samples_per_row', 100000)
        total_samples = self.parent_window.get_total_samples() if hasattr(self.parent_window, 'get_total_samples') else 0
        max_start = max(0, total_samples - base_spr) if total_samples > 0 else 1e9

        new_start = int(np.clip(curr_start - delta_samples, 0, max_start))
        self.parent_window._multirow_start_sample = new_start

        f0, f1 = getattr(self, '_current_freq_range', (f_min_bounds, f_max_bounds))
        f_span = f1 - f0
        new_f0 = float(np.clip(f0 - df, f_min_bounds, f_max_bounds - f_span))
        new_f1 = new_f0 + f_span
        self._current_freq_range = (new_f0, new_f1)

        self.update_all_row_axes()

        rel_t0, rel_t1 = getattr(self, '_current_rel_time', (0.0, 1.0))
        active_start_s = new_start + int(round(rel_t0 * base_spr))
        active_spr     = max(1, int(round((rel_t1 - rel_t0) * base_spr)))
        self._update_sidebar_inputs(new_f0, new_f1, active_start_s, active_spr)

        if hasattr(self.parent_window, 'sync_multi_row_markers'):
            self.parent_window.sync_multi_row_markers()
        if hasattr(self.parent_window, 'sync_multi_row_overlays'):
            self.parent_window.sync_multi_row_overlays()

    # ------------------------------------------------------------------
    # Theming
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

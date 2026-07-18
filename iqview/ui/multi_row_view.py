"""Multi-row stacked spectrogram view for periodic signal analysis."""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel


class MultiRowSpectrogramView(QWidget):
    """Displays N spectrogram rows stacked vertically, each showing a
    different time segment of the same IQ file.

    * Each row has its own PlotWidget with absolute time + frequency axes.
    * Frequency zoom is linked across all rows (absolute range).
    * Time zoom uses proportional/relative synchronisation (since each row
      covers a different absolute time span).
    * Colormap and intensity levels are synced from the main SpectrogramView.
    """

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.rows = []  # list of dicts: {'plot': PlotWidget, 'img': ImageItem, 'label': QLabel, 't_start': float, 't_end': float}
        self._block_sync = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Scroll area for the rows
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._layout.addWidget(self._scroll)

        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(0, 0, 0, 0)
        self._inner_layout.setSpacing(2)
        self._scroll.setWidget(self._inner)

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def _ensure_rows(self, n):
        """Create or remove PlotWidgets so that exactly *n* rows exist."""
        while len(self.rows) < n:
            from .widgets import CustomViewBox
            vb = CustomViewBox(ui_controller=self.parent_window)
            pw = pg.PlotWidget(viewBox=vb)
            pw.setMenuEnabled(False)
            pw.hideButtons()
            pw.setMouseEnabled(x=True, y=True)
            pw.getPlotItem().setContentsMargins(0, 0, 0, 0)
            pw.getPlotItem().getViewBox().setDefaultPadding(0)
            pw.showGrid(x=False, y=False)

            img = pg.ImageItem()
            img.setZValue(-100)
            pw.addItem(img)

            label = QLabel()
            label.setStyleSheet("color: #aaa; font-size: 10px; padding: 2px 6px;")
            label.setFixedHeight(16)

            self._inner_layout.addWidget(label)
            self._inner_layout.addWidget(pw)

            # Connect range changes for zoom sync
            pw.getPlotItem().getViewBox().sigRangeChanged.connect(self._on_row_range_changed)

            self.rows.append({
                'plot': pw.getPlotItem(),
                'widget': pw,
                'img': img,
                'label': label,
                't_start': 0.0,
                't_end': 1.0,
                'mirrored_items': [],
            })

        while len(self.rows) > n:
            row = self.rows.pop()
            row['widget'].getPlotItem().getViewBox().sigRangeChanged.disconnect(self._on_row_range_changed)
            # Remove any mirrored items
            for item in row.get('mirrored_items', []):
                try:
                    row['plot'].removeItem(item)
                except Exception:
                    pass
            self._inner_layout.removeWidget(row['label'])
            self._inner_layout.removeWidget(row['widget'])
            row['label'].deleteLater()
            row['widget'].deleteLater()

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    def update_spectrograms(self, spectrograms, rate, fc, start_sample,
                            samples_per_row, period):
        """
        Parameters
        ----------
        spectrograms : list[np.ndarray]
            Each element is (fft_size, num_time_bins) — one per row.
        rate : float
            Sample rate.
        fc : float
            Centre frequency.
        start_sample : int
            First sample index.
        samples_per_row : int
            Length of each row segment.
        period : int
            Interval between the start of consecutive rows.
        """
        n = len(spectrograms)
        self._ensure_rows(n)

        self._block_sync = True
        try:
            f_min = fc - rate / 2
            f_max = fc + rate / 2
            f_span = rate

            is_waterfall = bool(self.parent_window.settings_mgr.get("ui/waterfall", False))

            for i, spec in enumerate(spectrograms):
                row = self.rows[i]
                row_start_sample = start_sample + i * period
                row_end_sample = row_start_sample + samples_per_row

                t_row_start = row_start_sample / max(rate, 1)
                t_row_end = row_end_sample / max(rate, 1)
                t_duration = t_row_end - t_row_start

                row['t_start'] = t_row_start
                row['t_end'] = t_row_end

                # Label
                row['label'].setText(
                    f"Row {i+1}: Samples {row_start_sample:,} – {row_end_sample:,}  "
                    f"({t_row_start:.6f}s – {t_row_end:.6f}s)"
                )
                row['label'].setVisible(n > 1)

                # Set image data and rect
                if is_waterfall:
                    display_data = np.ascontiguousarray(spec.T)
                    row['img'].setImage(display_data, autoLevels=False)
                    row['img'].setRect(QRectF(f_min, t_row_start, f_span, t_duration))
                    row['plot'].setRange(xRange=[f_min, f_max], yRange=[t_row_start, t_row_end], padding=0)
                    row['plot'].setLabel('bottom', 'Frequency', units='Hz')
                    row['plot'].setLabel('left', 'Time', units='s')
                else:
                    row['img'].setImage(spec, autoLevels=False)
                    row['img'].setRect(QRectF(t_row_start, f_min, t_duration, f_span))
                    row['plot'].setRange(xRange=[t_row_start, t_row_end], yRange=[f_min, f_max], padding=0)
                    row['plot'].setLabel('bottom', 'Time', units='s')
                    row['plot'].setLabel('left', 'Frequency', units='Hz')

            # Auto-initialize levels if the main view's levels are not yet set
            if hasattr(self.parent_window, 'spectrogram_view') and hasattr(self.parent_window.spectrogram_view, 'level_region'):
                low, high = self.parent_window.spectrogram_view.level_region.getRegion()
                if (low == 0.0 and high == 1.0) or (high - low) <= 1e-3:
                    first_spec = spectrograms[0]
                    p2, p98 = np.percentile(first_spec, [2, 98])
                    self.parent_window.spectrogram_view.level_region.setRegion([float(p2), float(p98)])

            # Sync colormap and levels from the main view
            self.apply_levels_and_colormap()
        finally:
            self._block_sync = False

    # ------------------------------------------------------------------
    # Zoom synchronisation
    # ------------------------------------------------------------------

    def _on_row_range_changed(self):
        """Proportional time zoom + absolute frequency synchronisation."""
        if self._block_sync or len(self.rows) == 0:
            return

        self._block_sync = True
        try:
            # Find sender row
            sender_vb = self.sender()
            sender_idx = None
            for idx, row in enumerate(self.rows):
                if row['plot'].getViewBox() is sender_vb:
                    sender_idx = idx
                    break
            if sender_idx is None:
                return

            s_row = self.rows[sender_idx]
            is_waterfall = bool(self.parent_window.settings_mgr.get("ui/waterfall", False))
            vr = s_row['plot'].viewRange()

            if is_waterfall:
                # X=freq (absolute), Y=time (relative)
                freq_range = vr[0]
                time_range = vr[1]
            else:
                # X=time (relative), Y=freq (absolute)
                time_range = vr[0]
                freq_range = vr[1]

            # Compute relative position of the time viewport within sender's segment
            s_duration = s_row['t_end'] - s_row['t_start']
            if s_duration > 0:
                rel_start = (time_range[0] - s_row['t_start']) / s_duration
                rel_end = (time_range[1] - s_row['t_start']) / s_duration
            else:
                rel_start, rel_end = 0.0, 1.0

            # Apply to all other rows
            for idx, row in enumerate(self.rows):
                if idx == sender_idx:
                    continue
                r_duration = row['t_end'] - row['t_start']
                new_t_start = row['t_start'] + rel_start * r_duration
                new_t_end = row['t_start'] + rel_end * r_duration

                if is_waterfall:
                    row['plot'].setRange(xRange=freq_range, yRange=[new_t_start, new_t_end], padding=0)
                else:
                    row['plot'].setRange(xRange=[new_t_start, new_t_end], yRange=freq_range, padding=0)

            # Update the sidebar edits
            if hasattr(self.parent_window, 'sidebar'):
                sidebar = self.parent_window.sidebar
                mr_params = sidebar.get_multirow_params()
                
                zoomed_start_sample = int(round(mr_params['start_sample'] + rel_start * mr_params['samples_per_row']))
                zoomed_samples_per_row = int(round((rel_end - rel_start) * mr_params['samples_per_row']))

                if not sidebar.start_sample_edit.hasFocus():
                    sidebar.start_sample_edit.setText(str(zoomed_start_sample))
                if not sidebar.samples_per_row_edit.hasFocus():
                    sidebar.samples_per_row_edit.setText(str(zoomed_samples_per_row))
                if not sidebar.freq_min_edit.hasFocus():
                    sidebar.freq_min_edit.raw_value = freq_range[0]
                if not sidebar.freq_max_edit.hasFocus():
                    sidebar.freq_max_edit.raw_value = freq_range[1]
        finally:
            self._block_sync = False

    # ------------------------------------------------------------------
    # Colormap / level sync helpers
    # ------------------------------------------------------------------

    def apply_levels_and_colormap(self):
        """Copy levels and colormap from the main SpectrogramView to all rows."""
        if not hasattr(self.parent_window, 'spectrogram_view'):
            return
        sv = self.parent_window.spectrogram_view
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

    def refresh_markers_and_overlays(self):
        """Re-create and draw all standard/endless markers and overlays on each row plot."""
        # 1. Clear existing mirrored items from each plot
        for row in self.rows:
            if 'mirrored_items' in row:
                for item in row['mirrored_items']:
                    try:
                        row['plot'].removeItem(item)
                    except Exception:
                        pass
            row['mirrored_items'] = []

        if not hasattr(self.parent_window, 'spectrogram_view'):
            return

        # 2. Get active markers and overlays
        markers_time = getattr(self.parent_window, 'markers_time', [])
        markers_freq = getattr(self.parent_window, 'markers_freq', [])
        markers_time_endless = getattr(self.parent_window, 'markers_time_endless', [])
        markers_freq_endless = getattr(self.parent_window, 'markers_freq_endless', [])
        overlays = getattr(self.parent_window, 'overlays', [])

        theme = self.parent_window.settings_mgr.get("ui/theme", "Dark").lower()
        is_waterfall = bool(self.parent_window.settings_mgr.get("ui/waterfall", False))

        style_map = {
            "SolidLine": Qt.PenStyle.SolidLine,
            "DashLine": Qt.PenStyle.DashLine,
            "DotLine": Qt.PenStyle.DotLine,
            "DashDotLine": Qt.PenStyle.DashDotLine
        }

        # Pens/angles for standard time/freq markers
        t_color = self.parent_window.settings_mgr.get(f"ui/{theme}/time_marker_color", '#00ff00')
        t_style = style_map.get(str(self.parent_window.settings_mgr.get(f"ui/{theme}/time_marker_style")), Qt.PenStyle.DashLine)
        t_angle = 0 if is_waterfall else 90

        f_color = self.parent_window.settings_mgr.get(f"ui/{theme}/freq_marker_color", '#ffaa00')
        f_style = style_map.get(str(self.parent_window.settings_mgr.get(f"ui/{theme}/freq_marker_style")), Qt.PenStyle.DashLine)
        f_angle = 90 if is_waterfall else 0

        # Filter region (if placed/active)
        filter_region = getattr(self.parent_window, 'filter_region', None)
        filter_active = getattr(self.parent_window, 'filter_placed', False) or getattr(self.parent_window, 'filter_placing', False)

        for row in self.rows:
            # 3. Add time markers
            for m in markers_time:
                dup = pg.InfiniteLine(pos=m.value(), angle=t_angle, movable=False, pen=pg.mkPen(t_color, width=2, style=t_style))
                dup.setZValue(10)
                row['plot'].addItem(dup, ignoreBounds=True)
                row['mirrored_items'].append(dup)

            for m in markers_time_endless:
                dup = pg.InfiniteLine(pos=m.value(), angle=t_angle, movable=False, pen=pg.mkPen(t_color, width=2, style=t_style))
                dup.setZValue(10)
                row['plot'].addItem(dup, ignoreBounds=True)
                row['mirrored_items'].append(dup)

            # 4. Add freq markers
            for m in markers_freq:
                dup = pg.InfiniteLine(pos=m.value(), angle=f_angle, movable=False, pen=pg.mkPen(f_color, width=2, style=f_style))
                dup.setZValue(10)
                row['plot'].addItem(dup, ignoreBounds=True)
                row['mirrored_items'].append(dup)

            for m in markers_freq_endless:
                dup = pg.InfiniteLine(pos=m.value(), angle=f_angle, movable=False, pen=pg.mkPen(f_color, width=2, style=f_style))
                dup.setZValue(10)
                row['plot'].addItem(dup, ignoreBounds=True)
                row['mirrored_items'].append(dup)

            # 5. Add filter region if active
            if filter_region and filter_active:
                f1, f2 = filter_region.getRegion()
                dup_region = pg.LinearRegionItem(
                    values=[f1, f2],
                    orientation='vertical' if is_waterfall else 'horizontal',
                    brush=pg.mkBrush(0, 170, 255, 30),
                    movable=False
                )
                for line in dup_region.lines:
                    line.setPen(pg.mkPen('#fff', style=Qt.PenStyle.DashLine, width=1.5))
                row['plot'].addItem(dup_region)
                row['mirrored_items'].append(dup_region)

            # 6. Add overlays
            for overlay in overlays:
                from ..overlay import OverlayShape
                bc = overlay.color
                pen = pg.mkPen(bc, width=overlay.border_width, style=style_map.get(overlay.border_style, Qt.PenStyle.SolidLine))
                
                if overlay.shape in [OverlayShape.LINE, OverlayShape.HLINE]:
                    pos_val = overlay.points[0][0] if overlay.shape == OverlayShape.LINE else overlay.points[0][1]
                    if overlay.shape == OverlayShape.LINE:
                        line_angle = 0 if is_waterfall else 90
                    else:
                        line_angle = 90 if is_waterfall else 0
                    
                    dup = pg.InfiniteLine(pos=pos_val, angle=line_angle, movable=False, pen=pen)
                    dup.setZValue(overlay.z_order)
                    row['plot'].addItem(dup, ignoreBounds=True)
                    row['mirrored_items'].append(dup)
                
                elif overlay.shape in [OverlayShape.RECT, OverlayShape.ELLIPSE]:
                    from PyQt6 import QtWidgets
                    from PyQt6.QtGui import QPainterPath, QBrush, QColor
                    path_item = QtWidgets.QGraphicsPathItem()
                    path_item.setPen(pen)
                    if overlay.alpha > 0:
                        c = QColor(bc)
                        c.setAlpha(int(overlay.alpha * 255))
                        path_item.setBrush(QBrush(c))
                    
                    p1 = pg.QtCore.QPointF(overlay.points[0][0], overlay.points[0][1])
                    p2 = pg.QtCore.QPointF(overlay.points[1][0], overlay.points[1][1])
                    path = QPainterPath()
                    if overlay.shape == OverlayShape.RECT:
                        path.addRect(pg.QtCore.QRectF(p1, p2))
                    else:
                        path.addEllipse(pg.QtCore.QRectF(p1, p2))
                    path_item.setPath(path)
                    path_item.setZValue(overlay.z_order)
                    row['plot'].addItem(path_item)
                    row['mirrored_items'].append(path_item)
                    
                elif overlay.shape in [OverlayShape.X_REGION, OverlayShape.Y_REGION]:
                    p1 = pg.QtCore.QPointF(overlay.points[0][0], overlay.points[0][1])
                    p2 = pg.QtCore.QPointF(overlay.points[1][0], overlay.points[1][1])
                    
                    if overlay.shape == OverlayShape.X_REGION:
                        val1, val2 = p1.x(), p2.x()
                        orient = 'vertical' if is_waterfall else 'horizontal'
                    else:
                        val1, val2 = p1.y(), p2.y()
                        orient = 'horizontal' if is_waterfall else 'vertical'
                        
                    c = QColor(bc)
                    c.setAlpha(int(overlay.alpha * 255) if overlay.alpha > 0 else 30)
                    dup_region = pg.LinearRegionItem(
                        values=[val1, val2],
                        orientation=orient,
                        brush=QBrush(c),
                        movable=False
                    )
                    for line in dup_region.lines:
                        line.setPen(pen)
                    row['plot'].addItem(dup_region)
                    row['mirrored_items'].append(dup_region)

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from ..themes import get_palette


class TimeDomainPlotsMixin:
    """
    Mixin providing signal transformations and plotting routines for TimeDomainView.
    """

    def plot_real(self):
        self._update_plot(self.samples.real, "Real")

    def plot_real_db(self):
        data = np.abs(self.samples.real)
        data[data < 1e-12] = 1e-12
        self._update_plot(20 * np.log10(data), "Real [dB]")

    def plot_imaginary(self):
        self._update_plot(self.samples.imag, "Imaginary")

    def plot_imaginary_db(self):
        data = np.abs(self.samples.imag)
        data[data < 1e-12] = 1e-12
        self._update_plot(20 * np.log10(data), "Imaginary [dB]")

    def plot_magnitude(self):
        self._update_plot(np.abs(self.samples), "magnitude")

    def plot_magnitude_db(self):
        data = np.abs(self.samples)
        data[data < 1e-12] = 1e-12
        self._update_plot(20 * np.log10(data), "magnitude [dB]")

    def plot_magnitude_squared(self):
        self._update_plot(np.abs(self.samples)**2, "magnitude^2")

    def plot_magnitude_squared_db(self):
        data = np.abs(self.samples)**2
        data[data < 1e-18] = 1e-18
        self._update_plot(10 * np.log10(data), "magnitude^2 [dB]")

    def plot_inst_freq(self):
        from scipy.signal import hilbert, butter, sosfiltfilt

        samples = self.samples
        # Detect real signal: imaginary part is negligible
        is_real_signal = not np.any(np.iscomplex(samples)) or np.max(np.abs(samples.imag)) < 1e-9 * (np.max(np.abs(samples.real)) + 1e-30)

        if is_real_signal:
            real_part = samples.real.astype(np.float64)
            analytic = hilbert(real_part)
            try:
                sos = butter(2, 0.005, btype='high', output='sos')
                analytic = sosfiltfilt(sos, analytic.real) + 1j * sosfiltfilt(sos, analytic.imag)
            except Exception:
                pass
            samples = analytic

        dphi = np.diff(np.angle(samples))
        wrapped_dphi = (dphi + np.pi) % (2 * np.pi) - np.pi
        freq = wrapped_dphi / (2 * np.pi) * self.rate

        # Apply Moving Median Filter if configured
        filter_len = int(self.settings_mgr.get("core/inst_freq_filter_len", 7)) if self.settings_mgr else 7
        if filter_len > 1:
            from scipy.signal import medfilt
            if filter_len % 2 == 0:
                filter_len += 1
            freq = medfilt(freq, kernel_size=filter_len)

        pad_freq = np.concatenate(([freq[0]], freq)) if len(freq) > 0 else np.array([])
        self._update_plot(pad_freq, "instant frequency")

    def plot_phase(self):
        self._update_plot(np.angle(self.samples), "Phase")

    def plot_unwrapped_phase(self):
        self._update_plot(np.unwrap(np.angle(self.samples)), "Unwrapped phase")

    def _replot_current(self):
        if hasattr(self, 'current_plot_data') and hasattr(self, 'y_label_text'):
            self._update_plot(self.current_plot_data, self.y_label_text)

    def _update_plot(self, data, y_label):
        # 1. Save current view ranges
        old_x_range = None
        if hasattr(self, 'view_box') and self.view_box.viewRect() is not None:
            old_x_range, old_y_range = self.view_box.viewRange()
            self.zoom_y_dict[self.y_label_text] = old_y_range

        # 2. Update state
        self.current_plot_data = data
        self.y_label_text = y_label
        self.marker_panel.update_headers(self.interaction_mode, y_label)

        # Update stats if visible
        if hasattr(self, 'stats_region') and self.stats_region.isVisible():
            self.update_statistics()

        # 3. Clear and Re-plot
        self.plot_item.clear()
        self.stats_markers.clear()

        if getattr(self, 'stats_line', None) is not None:
            self.plot_item.addItem(self.stats_line)
        self.plot_item.addItem(self.stats_region)
        self.plot_item.addItem(self.stats_markers)

        self.plot_item.getAxis('left').setLabel(y_label)

        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)
        pen = pg.mkPen(p.accent, width=1.5)
        self.plot_item.plot(self.time_axis, data, pen=pen)

        # 4. Restore markers
        for m in self.markers_primary:
            m.setPen(pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)

        for m in self.markers_primary_endless:
            m.setPen(pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)

        active_y = self.markers_y_dict.get(y_label, [])
        for m in active_y:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)

        active_y_endless = self.markers_y_endless_dict.get(y_label, [])
        for m in active_y_endless:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)

        # 5. Constraints
        y_min_data, y_max_data = np.min(data), np.max(data)
        y_range_val = y_max_data - y_min_data
        if y_range_val == 0: y_range_val = 1.0
        y_pad = y_range_val * 0.05

        self.view_box.setLimits(xMin=None, xMax=None, yMin=None, yMax=None)

        # 6. Restore Zooms / Initial Auto-Fit
        if not getattr(self, '_first_plot', False):
            if y_label in self.zoom_y_dict:
                y_r = self.zoom_y_dict[y_label]
                self.plot_item.setYRange(y_r[0], y_r[1], padding=0)
            else:
                self.plot_item.setYRange(y_min_data - y_pad, y_max_data + y_pad, padding=0)

            if old_x_range is not None:
                self.plot_item.setXRange(old_x_range[0], old_x_range[1], padding=0)
        else:
            self._first_plot = False
            self.plot_item.setXRange(self.time_axis[0], self.time_axis[-1], padding=0)
            self.plot_item.setYRange(y_min_data - y_pad, y_max_data + y_pad, padding=0)

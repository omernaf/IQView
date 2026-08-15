import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from ..themes import get_palette


class FrequencyDomainPlotsMixin:
    """
    Mixin providing signal preprocessing, FFT, PSD, and plotting routines for FrequencyDomainView.
    """

    def get_processed_samples(self):
        """Applies the selected preprocessing operator to the source samples."""
        src = self._filtered_samples if (getattr(self, '_filtered_samples', None) is not None) else self.samples
        if src is None or len(src) == 0:
            return np.array([], dtype=np.complex64)

        operator = self.operator_combo.currentText()
        if operator == "2nd Power":
            return src ** 2
        elif operator == "4th Power":
            return src ** 4
        elif operator == "Absolute Value":
            return np.abs(src)
        elif operator in ("FM Demod", "2nd Power FM"):
            from scipy.signal import hilbert, butter, sosfiltfilt

            is_real = not np.any(np.iscomplex(src)) or np.max(np.abs(src.imag)) < 1e-9 * (np.max(np.abs(src.real)) + 1e-30)
            if is_real:
                real_part = src.real.astype(np.float64)
                try:
                    analytic = hilbert(real_part)
                    sos = butter(2, 0.005, btype='high', output='sos')
                    analytic = sosfiltfilt(sos, analytic.real) + 1j * sosfiltfilt(sos, analytic.imag)
                    src = analytic
                except Exception:
                    pass

            dphi = np.diff(np.angle(src))
            wrapped_dphi = (dphi + np.pi) % (2 * np.pi) - np.pi
            freq = wrapped_dphi / (2 * np.pi) * self.rate

            filter_len = 1
            if self.settings_mgr:
                filter_len = int(self.settings_mgr.get("core/inst_freq_filter_len", 7))
            if filter_len > 1:
                from scipy.signal import medfilt
                if filter_len % 2 == 0:
                    filter_len += 1
                try:
                    freq = medfilt(freq, kernel_size=filter_len)
                except Exception:
                    pass

            if len(freq) > 0:
                freq = np.concatenate(([freq[0]], freq))

            if operator == "2nd Power FM":
                return freq ** 2
            return freq
        elif operator == "Delay & Multiply":
            if len(src) > 1:
                res = src[1:] * np.conj(src[:-1])
                return np.concatenate(([res[0]], res))
            else:
                return np.array([], dtype=np.complex64)
        return src

    def on_operator_changed(self):
        """Called when the user selects a new preprocessing operator."""
        operator = self.operator_combo.currentText()
        if operator != "Normal":
            if self.interaction_mode == 'FILTER':
                self.set_interaction_mode('FREQ')
                self.marker_panel.update_mode_ui('FREQ')
                self.marker_panel.update_headers('FREQ')
            if hasattr(self, 'filter_region'):
                self.filter_region.hide()
            if hasattr(self, 'filter_line') and self.filter_line:
                self.filter_line.hide()

        self._first_plot = True
        self.zoom_y_dict.clear()
        self.compute_fft()

        saved_mode = getattr(self, '_current_plot_mode_key', 'magnitude')
        available = getattr(self, 'available_modes', {})
        target = saved_mode if saved_mode in available else 'magnitude'
        if target in available:
            available[target]()

    def compute_fft(self):
        """Perform FFT processing on the sample segment using signal length N."""
        src = self.get_processed_samples()
        n = len(src)
        if n == 0: return

        window = np.ones(n)
        fft_res = np.fft.fft(src * window) / n
        self.fft_data = np.fft.fftshift(fft_res)

        operator = self.operator_combo.currentText()
        if operator in ("Absolute Value", "FM Demod", "2nd Power FM", "Delay & Multiply"):
            cf = 0.0
        elif operator == "2nd Power":
            cf = 2 * self.center_freq
        elif operator == "4th Power":
            cf = 4 * self.center_freq
        else:
            cf = self.center_freq

        self.fft_freq_axis = np.fft.fftshift(np.fft.fftfreq(n, 1/self.rate)) + cf
        self.freq_axis = self.fft_freq_axis

        if hasattr(self, 'stats_region'):
            self.stats_region.setBounds([self.freq_axis[0], self.freq_axis[-1]])
        if hasattr(self, 'filter_region'):
            self.filter_region.setBounds([self.freq_axis[0], self.freq_axis[-1]])

        self.current_plot_data = np.nan_to_num(np.abs(self.fft_data), nan=0.0, posinf=1e-15, neginf=0.0)
        self.y_label_text = "magnitude"

    # -------------------------------------------------------------------------
    # Plot Dispatchers
    # -------------------------------------------------------------------------
    def plot_magnitude(self):
        self._update_plot(np.abs(self.fft_data), "magnitude")

    def plot_magnitude_db(self):
        data = np.abs(self.fft_data)
        data = np.nan_to_num(data, nan=1e-15, posinf=1e-15, neginf=1e-15)
        data[data < 1e-15] = 1e-15
        self._update_plot(20 * np.log10(data), "magnitude [dB]")

    def plot_magnitude_squared(self):
        self._update_plot(np.abs(self.fft_data)**2, "magnitude^2")

    def plot_real(self):
        self._update_plot(self.fft_data.real, "real")

    def plot_real_db(self):
        data = np.abs(self.fft_data.real)
        data = np.nan_to_num(data, nan=1e-15, posinf=1e-15, neginf=1e-15)
        data[data < 1e-15] = 1e-15
        self._update_plot(20 * np.log10(data), "real [dB]")

    def plot_imag(self):
        self._update_plot(self.fft_data.imag, "imag")

    def plot_imag_db(self):
        data = np.abs(self.fft_data.imag)
        data = np.nan_to_num(data, nan=1e-15, posinf=1e-15, neginf=1e-15)
        data[data < 1e-15] = 1e-15
        self._update_plot(20 * np.log10(data), "imag [dB]")

    def plot_phase(self):
        self._update_plot(np.angle(self.fft_data), "phase")

    def plot_unwrapped_phase(self):
        self._update_plot(np.unwrap(np.angle(self.fft_data)), "unwrapped phase")

    def plot_psd(self):
        from scipy.signal import welch
        src = self.get_processed_samples()
        n = len(src)
        if n == 0: return

        nperseg = int(self.settings_mgr.get("core/psd_nperseg", 1024)) if self.settings_mgr else 1024
        if nperseg > n: nperseg = n

        operator = self.operator_combo.currentText()
        if operator in ("Absolute Value", "FM Demod", "2nd Power FM", "Delay & Multiply"):
            cf = 0.0
        elif operator == "2nd Power":
            cf = 2 * self.center_freq
        elif operator == "4th Power":
            cf = 4 * self.center_freq
        else:
            cf = self.center_freq

        is_complex = np.iscomplexobj(src)
        freqs, psd = welch(
            src, fs=self.rate, window='hann', nperseg=nperseg,
            return_onesided=not is_complex, scaling='density'
        )

        if is_complex:
            freqs = np.fft.fftshift(freqs)
            psd = np.fft.fftshift(psd)

        freqs += cf
        psd_clean = np.nan_to_num(psd, nan=1e-20, posinf=1e-20, neginf=1e-20)
        psd_clean[psd_clean < 1e-20] = 1e-20
        psd_db = 10 * np.log10(psd_clean)

        self._update_plot_dynamic(freqs, psd_db, "PSD [dB]")

    def _replot_current(self):
        if hasattr(self, 'current_plot_data') and hasattr(self, 'y_label_text'):
            self._update_plot(self.current_plot_data, self.y_label_text)

    def _update_plot_dynamic(self, freqs, data, y_label):
        self.freq_axis = freqs
        if hasattr(self, 'stats_region'):
            self.stats_region.setBounds([self.freq_axis[0], self.freq_axis[-1]])
        if hasattr(self, 'filter_region'):
            self.filter_region.setBounds([self.freq_axis[0], self.freq_axis[-1]])
        self._update_plot(data, y_label)

    def _update_plot(self, data, y_label):
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

        if hasattr(self, 'fft_freq_axis') and len(self.freq_axis) != len(data):
            self.freq_axis = self.fft_freq_axis
            if hasattr(self, 'stats_region'):
                self.stats_region.setBounds([self.freq_axis[0], self.freq_axis[-1]])
            if hasattr(self, 'filter_region'):
                self.filter_region.setBounds([self.freq_axis[0], self.freq_axis[-1]])

        old_x_range = None
        if hasattr(self, 'view_box') and self.view_box.viewRect() is not None:
            old_x_range, old_y_range = self.view_box.viewRange()
            self.zoom_y_dict[self.y_label_text] = old_y_range

        self.current_plot_data = data
        self.y_label_text = y_label
        self.marker_panel.update_headers(self.interaction_mode, y_label)

        if hasattr(self, 'stats_region') and self.stats_region.isVisible():
            self.update_statistics()

        self.plot_item.clear()
        self.stats_markers.clear()

        # Re-add items
        if getattr(self, 'stats_line', None) is not None:
            self.plot_item.addItem(self.stats_line)
        self.plot_item.addItem(self.stats_region)
        self.plot_item.addItem(self.stats_markers)

        if hasattr(self, 'filter_line') and self.filter_line is not None:
            self.plot_item.addItem(self.filter_line)
        if hasattr(self, 'filter_region') and self.filter_region is not None:
            self.plot_item.addItem(self.filter_region)

        self.plot_item.getAxis('left').setLabel(y_label)

        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)
        pen = pg.mkPen(p.accent, width=1.5)
        self.plot_item.plot(self.freq_axis, data, pen=pen)

        # Restore markers
        for m in self.markers_primary:
            m.setPen(pg.mkPen(p.marker_freq, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m)
            m.setZValue(100)

        for m in self.markers_primary_endless:
            m.setPen(pg.mkPen(p.marker_freq, width=2, style=Qt.PenStyle.DashLine))
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

        y_min_data, y_max_data = np.min(data), np.max(data)
        y_range_val = y_max_data - y_min_data
        if y_range_val == 0: y_range_val = 1.0
        y_pad = y_range_val * 0.05

        self.view_box.setLimits(xMin=None, xMax=None, yMin=None, yMax=None)

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
            self.plot_item.setXRange(self.freq_axis[0], self.freq_axis[-1], padding=0)
            self.plot_item.setYRange(y_min_data - y_pad, y_max_data + y_pad, padding=0)

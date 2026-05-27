"""iqview/ui/eye_diagram_dialog.py

Interactive Eye Diagram tab for IQView.
Mirrors the functionality of the MATLAB dynamic_eye_diagram.mlapp:

 - Signal-type selector (Real, Imaginary, Phase, Inst. Freq, Magnitude…)
 - Eye diagram rendered using fractional Nsps (non-integer supported)
 - Three-tier Nsps slider system: Main + Coarse + Fine
 - Offset slider for symbol-timing phase adjustment
 - Mini waveform overview with two draggable range handles
 - Live Baud Rate / Symbol Time info panel
 - Cycling mode: SPS or Baud Rate (Hz)
 - Respects IQView Dark/Light theme
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QButtonGroup, QDoubleSpinBox,
    QFrame, QSizePolicy, QFormLayout, QGroupBox,
    QSlider,
)
from PyQt6.QtGui import QFont

from .themes import get_palette

# ── Constants ────────────────────────────────────────────────────────────────

MAX_EYE_SAMPLES = 500_000   # hard cap to keep rendering fast

# Ordered list of signal modes — matches Time Domain view order
_MODES = [
    "Real",
    "Imaginary",
    "Phase",
    "instant frequency",
    "magnitude",
]

_MODE_LABELS = {
    "Real":              "Real",
    "Imaginary":         "Imaginary",
    "Phase":             "Phase (rad)",
    "instant frequency": "Inst. Freq",
    "magnitude":         "Magnitude",
}

# ── Eye diagram core algorithm ────────────────────────────────────────────────

def _compute_signal(samples: np.ndarray, mode: str, rate: float = 1.0) -> np.ndarray:
    """Convert complex samples to the requested scalar signal."""
    if mode == "Real":
        return samples.real.astype(np.float32)
    elif mode == "Imaginary":
        return samples.imag.astype(np.float32)
    elif mode == "Phase":
        return np.angle(samples).astype(np.float32)
    elif mode == "instant frequency":
        # Same approach as TimeDomainView.plot_inst_freq but lightweight
        sig = samples
        if len(sig) < 2:
            return np.zeros(len(samples), dtype=np.float32)
        is_real = not np.any(np.iscomplex(sig)) or \
                  np.max(np.abs(sig.imag)) < 1e-9 * (np.max(np.abs(sig.real)) + 1e-30)
        if is_real:
            from scipy.signal import hilbert
            sig = hilbert(sig.real.astype(np.float64))
        dphi = np.diff(np.angle(sig))
        wrapped = (dphi + np.pi) % (2 * np.pi) - np.pi
        freq = (wrapped / (2 * np.pi) * rate).astype(np.float32)
        # Pad by repeating first value so output length equals input length
        return np.concatenate(([freq[0]], freq)) if len(freq) > 0 else np.zeros(len(samples), dtype=np.float32)
    elif mode == "magnitude":
        return np.abs(samples).astype(np.float32)
    else:
        return samples.real.astype(np.float32)


def _eye_segments(x: np.ndarray, nsps: float, offset: float = 0.0):
    """
    Compute eye diagram line endpoints — replicates MATLAB eyediag.m.
    Supports fractional (non-integer) nsps.

    Returns (t1, y1, t2, y2) arrays where each entry is one segment
    to draw, x-axis normalised to [-0.5, 0.5].
    """
    n = len(x)
    if n < 2 or nsps < 1.0:
        empty = np.empty(0, dtype=np.float32)
        return empty, empty, empty, empty

    # Time vector: sample indices relative to the offset, wrapped to [0, nsps)
    t = np.mod(-offset + np.arange(n, dtype=np.float64), nsps)

    t1 = t[:-1]
    t2 = t[1:]
    x1 = x[:-1]
    x2 = x[1:]

    # Lines that go backwards mark the start of a new symbol period.
    # MATLAB: invalid_lines = t1 > t2; invalid_lines(end) = false;
    # MATLAB: invalid_lines_prev = [invalid_lines(1:end-1), false];
    # After forcing invalid[-1]=False, invalid_prev == invalid in all cases,
    # so the only effective operation is: t1[invalid] -= nsps  (shift that
    # segment back by one period so it stitches onto the previous trace).
    t1 = t1.copy()
    t2 = t2.copy()
    x1 = x1.copy()
    x2 = x2.copy()

    invalid = t1 > t2
    invalid[-1] = False          # force last entry valid (matches MATLAB)
    t1[invalid] -= nsps          # shift wrap-around segments back one period

    # Normalise time axis to [-0.5, 0.5]
    t1 = (t1 / nsps - 0.5).astype(np.float32)
    t2 = (t2 / nsps - 0.5).astype(np.float32)

    return t1, x1.astype(np.float32), t2, x2.astype(np.float32)


# ── Multi-segment plot helper ─────────────────────────────────────────────────

def _build_multiline_data(t1, y1, t2, y2):
    """
    Pack segment endpoints into the (N,2) x / (N,2) y format expected by
    pg.MultiLine (or the connect='pairs' trick with PlotDataItem).

    We interleave [t1[i], t2[i]] rows so that with connect='pairs'
    pyqtgraph draws one line per pair.
    """
    n = len(t1)
    xs = np.empty(n * 2, dtype=np.float32)
    ys = np.empty(n * 2, dtype=np.float32)
    xs[0::2] = t1
    xs[1::2] = t2
    ys[0::2] = y1
    ys[1::2] = y2
    return xs, ys


# ── Main widget ───────────────────────────────────────────────────────────────

class EyeDiagramView(QWidget):
    """
    Tab widget containing the interactive eye diagram.

    Parameters
    ----------
    samples : np.ndarray  complex (or real) IQ samples
    sample_rate : float   samples per second (used for Inst. Freq and info panel)
    parent_window :       SpectrogramWindow — used for theme
    """

    # Expose for DetachableTabBar ghost preview
    is_spectrogram = False

    def __init__(self, samples: np.ndarray, sample_rate: float,
                 parent_window=None, parent=None):
        super().__init__(parent)
        self.parent_window = parent_window
        self.settings_mgr = parent_window.settings_mgr if parent_window else None

        # ── Data ────────────────────────────────────────────────────────────
        self._raw_samples = samples
        self._rate = float(sample_rate)

        # Truncate to max allowed
        if len(samples) > MAX_EYE_SAMPLES:
            self._raw_samples = samples[:MAX_EYE_SAMPLES]

        self._trunc_samples = self._raw_samples   # range-limited sub-segment
        self._trunc_start = 0                     # index into _raw_samples
        self._trunc_end = len(self._raw_samples)

        # Eye diagram state
        self._nsps = 10.0
        self._offset = 0.0          # fractional offset in [−1, +1] symbols
        self._mode = "Real"

        # Cycling mode: 'sps' or 'baud'
        self._cycle_mode = 'sps'

        # Suppress recursive slider updates
        self._updating = False

        # ── Layout ──────────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Signal-type toolbar ─────────────────────────────────────────────
        self._build_mode_toolbar(root)

        # ── Main eye diagram plot ───────────────────────────────────────────
        self._eye_plot_widget = pg.PlotWidget()
        self._eye_plot_item = self._eye_plot_widget.getPlotItem()
        self._eye_plot_item.setMenuEnabled(False)
        self._eye_plot_item.hideButtons()
        self._eye_plot_item.showGrid(x=True, y=True, alpha=0.2)
        self._eye_plot_item.setLabel('bottom', 'Time (normalised symbols)')
        self._eye_plot_item.setLabel('left', 'Amplitude')
        self._eye_data_item = pg.PlotDataItem(connect='pairs')
        self._eye_plot_item.addItem(self._eye_data_item)
        root.addWidget(self._eye_plot_widget, stretch=3)

        # ── Mini overview plot ──────────────────────────────────────────────
        self._build_mini_overview(root)

        # ── Control sliders + info panel ────────────────────────────────────
        self._build_controls(root)

        # ── Initial render ──────────────────────────────────────────────────
        self.refresh_theme()
        self._update_eye_diagram()

    # ── Mode toolbar ─────────────────────────────────────────────────────────

    def _build_mode_toolbar(self, parent_layout):
        toolbar = QFrame()
        toolbar.setObjectName("td_toolbar")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(8, 4, 8, 4)
        tl.setSpacing(6)

        label = QLabel("Signal:")
        label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        tl.addWidget(label)

        self._mode_group = QButtonGroup(self)
        self._mode_buttons: list[QPushButton] = []

        for i, mode in enumerate(_MODES):
            btn = QPushButton(_MODE_LABELS[mode])
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._mode_group.addButton(btn, i)
            tl.addWidget(btn)
            self._mode_buttons.append(btn)
            btn.clicked.connect(lambda checked, m=mode: self._on_mode_changed(m))

        self._mode_buttons[0].setChecked(True)

        tl.addStretch()

        # Sample count info
        n = len(self._raw_samples)
        was_capped = n >= MAX_EYE_SAMPLES
        info_lbl = QLabel(
            f"{n:,} samples" + (" (capped at 500 k)" if was_capped else "")
        )
        info_lbl.setStyleSheet("color: #888; font-size: 10px; font-family: Consolas;")
        tl.addWidget(info_lbl)

        parent_layout.addWidget(toolbar)

    # ── Mini overview ─────────────────────────────────────────────────────────

    def _build_mini_overview(self, parent_layout):
        self._mini_widget = pg.PlotWidget()
        self._mini_item = self._mini_widget.getPlotItem()
        self._mini_item.setMenuEnabled(False)
        self._mini_item.hideButtons()
        self._mini_item.setMouseEnabled(x=False, y=False)
        self._mini_item.getAxis('left').setStyle(showValues=False)
        self._mini_item.getAxis('left').setWidth(10)
        self._mini_item.setLabel('bottom', 'Sample Index')

        n = len(self._raw_samples)

        # Normalised amplitude
        sig = _compute_signal(self._raw_samples, self._mode, self._rate)
        mx = np.max(np.abs(sig)) if len(sig) else 1.0
        if mx < 1e-12:
            mx = 1.0
        norm = sig / mx

        self._mini_curve = pg.PlotDataItem(
            np.arange(n, dtype=np.float32), norm,
            pen=pg.mkPen('#00aaff', width=1)
        )
        self._mini_item.addItem(self._mini_curve)
        self._mini_item.setXRange(0, n, padding=0)
        self._mini_item.setYRange(-1, 1, padding=0.05)

        # Draggable handles
        self._handle1 = pg.InfiniteLine(pos=0, angle=90, movable=True,
                                        pen=pg.mkPen('#ffffff', width=2))
        self._handle2 = pg.InfiniteLine(pos=n, angle=90, movable=True,
                                        pen=pg.mkPen('#ffffff', width=2))
        self._handle1.setBounds([0, n])
        self._handle2.setBounds([0, n])
        self._mini_item.addItem(self._handle1)
        self._mini_item.addItem(self._handle2)

        # Gray shade patches (LinearRegionItem on each side)
        self._shade_left = pg.LinearRegionItem(
            [0, 0], orientation='vertical',
            brush=pg.mkBrush(128, 128, 128, 100), movable=False
        )
        self._shade_left.lines[0].setPen(pg.mkPen(None))
        self._shade_left.lines[1].setPen(pg.mkPen(None))

        self._shade_right = pg.LinearRegionItem(
            [n, n], orientation='vertical',
            brush=pg.mkBrush(128, 128, 128, 100), movable=False
        )
        self._shade_right.lines[0].setPen(pg.mkPen(None))
        self._shade_right.lines[1].setPen(pg.mkPen(None))

        self._mini_item.addItem(self._shade_left)
        self._mini_item.addItem(self._shade_right)

        self._handle1.sigPositionChanged.connect(self._on_handle_moved)
        self._handle2.sigPositionChanged.connect(self._on_handle_moved)

        self._mini_widget.setFixedHeight(90)
        parent_layout.addWidget(self._mini_widget)

    # ── Controls ──────────────────────────────────────────────────────────────

    def _build_controls(self, parent_layout):
        ctrl = QWidget()
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(10)

        # ── Slider grid (left side) ────────────────────────────────────────
        slider_grp = QGroupBox("Symbol Timing")
        sl = QFormLayout(slider_grp)
        sl.setSpacing(4)

        def _make_slider(lo, hi, init=0.0, decimals=4):
            """Return (QSlider, value getter, value setter) trio."""
            s = QSlider(Qt.Orientation.Horizontal)
            # Map float range to integer ticks
            TICKS = 10000
            s.setRange(0, TICKS)
            s._lo = lo
            s._hi = hi
            s._ticks = TICKS

            def _get():
                return s._lo + (s.value() / s._ticks) * (s._hi - s._lo)

            def _set(v):
                frac = (v - s._lo) / (s._hi - s._lo)
                s.setValue(int(round(frac * s._ticks)))

            _set(init)
            return s, _get, _set

        nsps_init = self._nsps
        nsps_lo = max(2.0, nsps_init - 14)
        nsps_hi = nsps_init + 14

        # Main slider (used for either SPS or Baud Rate depending on _cycle_mode)
        self._sld_main, self._get_main, self._set_main = _make_slider(nsps_lo, nsps_hi, nsps_init)
        # Coarse slider  ±0.2
        self._sld_coarse, self._get_coarse, self._set_coarse = _make_slider(-0.2, 0.2, 0.0)
        # Fine slider  ±0.01
        self._sld_fine, self._get_fine, self._set_fine = _make_slider(-0.01, 0.01, 0.0)
        # Offset slider  ±1 symbol
        self._sld_offset, self._get_offset, self._set_offset = _make_slider(-1.0, 1.0, 0.0)

        # Numeric spinbox (label is updated dynamically by _update_cycle_mode_ui)
        self._spin_nsps = QDoubleSpinBox()
        self._spin_nsps.setRange(1e-6, 1e12)
        self._spin_nsps.setDecimals(6)
        self._spin_nsps.setValue(nsps_init)
        self._spin_nsps.setFixedWidth(110)

        # Cycle-mode toggle button (SPS ⇄ Baud Rate)
        self._btn_cycle_mode = QPushButton("⇄ Baud Rate")
        self._btn_cycle_mode.setCheckable(True)
        self._btn_cycle_mode.setChecked(False)
        self._btn_cycle_mode.setToolTip(
            "Switch between cycling by Samples-Per-Symbol (SPS) "
            "or by Baud Rate (Hz)"
        )
        self._btn_cycle_mode.setFixedWidth(110)
        self._btn_cycle_mode.toggled.connect(self._on_cycle_mode_toggled)

        # Main row: slider + spinbox + mode toggle
        self._main_slider_label = QLabel("Nsps:")
        main_row = QHBoxLayout()
        main_row.addWidget(self._sld_main)
        main_row.addWidget(self._spin_nsps)
        main_row.addWidget(self._btn_cycle_mode)
        sl.addRow(self._main_slider_label, main_row)
        sl.addRow("Coarse:", self._sld_coarse)
        sl.addRow("Fine:", self._sld_fine)
        sl.addRow("Offset:", self._sld_offset)

        # Connect signals
        self._sld_main.valueChanged.connect(self._on_main_slider)
        self._sld_coarse.valueChanged.connect(self._on_coarse_slider)
        self._sld_fine.valueChanged.connect(self._on_fine_slider)
        self._sld_offset.valueChanged.connect(self._on_offset_slider)
        self._spin_nsps.valueChanged.connect(self._on_spin_nsps)

        cl.addWidget(slider_grp, stretch=3)

        # ── Info panel (right side) ────────────────────────────────────────
        info_grp = QGroupBox("Signal Info")
        il = QFormLayout(info_grp)
        il.setSpacing(4)

        def _ro_label():
            lbl = QLabel("—")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet("font-family: Consolas; font-size: 11px;")
            return lbl

        self._lbl_fs  = _ro_label()
        self._lbl_br  = _ro_label()
        self._lbl_ts  = _ro_label()
        self._lbl_sps = _ro_label()   # only visible in Baud Rate mode

        self._row_fs  = il.addRow("Sampling Freq:", self._lbl_fs)
        self._row_br  = il.addRow("Baud Rate:",     self._lbl_br)
        self._row_ts  = il.addRow("Symbol Time:",   self._lbl_ts)
        # "SPS" row — shown only when cycling by Baud Rate
        self._lbl_sps_key = QLabel("SPS:")
        self._lbl_sps_key.setStyleSheet("font-weight: bold; color: #ffaa00;")
        self._lbl_sps.setStyleSheet(
            "font-family: Consolas; font-size: 11px; font-weight: bold; color: #ffaa00;"
        )
        il.addRow(self._lbl_sps_key, self._lbl_sps)
        # Hide SPS row initially (SPS mode is default)
        self._lbl_sps_key.setVisible(False)
        self._lbl_sps.setVisible(False)

        cl.addWidget(info_grp, stretch=1)

        parent_layout.addWidget(ctrl)

        # Initial info update
        self._update_info_panel()

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_mode_changed(self, mode: str):
        self._mode = mode
        # Refresh mini overview curve
        self._refresh_mini_curve()
        self._schedule_update()

    def _on_handle_moved(self):
        n = len(self._raw_samples)
        h1 = max(0, min(n - 1, int(round(self._handle1.value()))))
        h2 = max(1, min(n, int(round(self._handle2.value()))))
        lo, hi = min(h1, h2), max(h1, h2)
        if hi <= lo:
            hi = lo + 1

        self._trunc_start = lo
        self._trunc_end = hi
        self._trunc_samples = self._raw_samples[lo:hi]

        # Update shaded regions
        self._shade_left.setRegion([0, lo])
        self._shade_right.setRegion([hi, n])

        self._schedule_update()

    def _on_main_slider(self):
        if self._updating:
            return
        raw = self._get_main() + self._get_coarse() + self._get_fine()
        if self._cycle_mode == 'baud':
            # raw is a Baud Rate value → convert to nsps
            baud = max(1e-6, raw)
            nsps = self._rate / baud
            self._apply_nsps(nsps, source='main_slider', baud_raw=baud)
        else:
            self._apply_nsps(raw, source='main_slider')

    def _on_coarse_slider(self):
        if self._updating:
            return
        raw = self._get_main() + self._get_coarse() + self._get_fine()
        if self._cycle_mode == 'baud':
            baud = max(1e-6, raw)
            nsps = self._rate / baud
            self._apply_nsps(nsps, source='coarse_slider', baud_raw=baud)
        else:
            self._apply_nsps(raw, source='coarse_slider')

    def _on_fine_slider(self):
        if self._updating:
            return
        raw = self._get_main() + self._get_coarse() + self._get_fine()
        if self._cycle_mode == 'baud':
            baud = max(1e-6, raw)
            nsps = self._rate / baud
            self._apply_nsps(nsps, source='fine_slider', baud_raw=baud)
        else:
            self._apply_nsps(raw, source='fine_slider')

    def _on_spin_nsps(self):
        if self._updating:
            return
        raw = self._spin_nsps.value()
        if self._cycle_mode == 'baud':
            baud = max(1e-6, raw)
            nsps = self._rate / baud
            self._apply_nsps(nsps, source='spinbox', baud_raw=baud)
        else:
            self._apply_nsps(raw, source='spinbox')

    def _on_offset_slider(self):
        if self._updating:
            return
        # Offset in units of symbol periods → actual sample offset
        self._offset = self._get_offset() * self._nsps
        self._schedule_update()

    def _on_cycle_mode_toggled(self, checked: bool):
        """Switch between SPS cycling and Baud Rate cycling."""
        self._cycle_mode = 'baud' if checked else 'sps'
        self._update_cycle_mode_ui()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _update_cycle_mode_ui(self):
        """
        Reconfigure the main slider and spinbox to match the current
        cycle mode (SPS or Baud Rate), without changing the eye diagram.
        """
        self._updating = True
        try:
            if self._cycle_mode == 'baud':
                # Update toggle button appearance
                self._btn_cycle_mode.setText("⇄ SPS")
                self._btn_cycle_mode.setChecked(True)

                # Reconfigure slider label
                self._main_slider_label.setText("Baud Rate:")

                # Compute current baud rate from nsps
                baud = self._rate / max(self._nsps, 1e-9)

                # Reconfigure main slider window around current baud rate
                # Use ±50% of current baud as range (same feel as SPS ±14)
                half = max(baud * 0.5, 1.0)
                lo = max(1e-6, baud - half)
                hi = baud + half
                self._sld_main._lo = lo
                self._sld_main._hi = hi
                self._set_main(baud)

                # Reconfigure coarse/fine sliders proportionally to baud
                coarse_range = max(baud * 0.02, 1.0)   # ±2% of baud rate
                fine_range   = max(baud * 0.001, 0.1)  # ±0.1% of baud rate
                self._sld_coarse._lo = -coarse_range
                self._sld_coarse._hi =  coarse_range
                self._sld_fine._lo   = -fine_range
                self._sld_fine._hi   =  fine_range
                self._set_coarse(0.0)
                self._set_fine(0.0)

                # Update spinbox to show baud rate
                self._spin_nsps.setValue(baud)

                # Show highlighted SPS row in info panel
                self._lbl_sps_key.setVisible(True)
                self._lbl_sps.setVisible(True)

            else:  # 'sps'
                self._btn_cycle_mode.setText("⇄ Baud Rate")
                self._btn_cycle_mode.setChecked(False)

                self._main_slider_label.setText("Nsps:")

                # Reconfigure main slider window around current nsps
                nsps = self._nsps
                lo = max(2.0, round(nsps) - 14)
                hi = round(nsps) + 14
                self._sld_main._lo = lo
                self._sld_main._hi = hi
                self._set_main(nsps)

                # Restore original coarse/fine ranges
                self._sld_coarse._lo = -0.2
                self._sld_coarse._hi =  0.2
                self._sld_fine._lo   = -0.01
                self._sld_fine._hi   =  0.01
                self._set_coarse(0.0)
                self._set_fine(0.0)

                # Update spinbox to show SPS
                self._spin_nsps.setValue(nsps)

                # Hide SPS row (redundant in SPS mode)
                self._lbl_sps_key.setVisible(False)
                self._lbl_sps.setVisible(False)

        finally:
            self._updating = False

        self._update_info_panel()

    def _apply_nsps(self, nsps: float, source: str = 'main_slider',
                    baud_raw: float = None):
        """Update Nsps state and sync all controls, then redraw."""
        nsps = max(2.0, nsps)
        self._nsps = nsps

        self._updating = True
        try:
            if self._cycle_mode == 'baud':
                # baud_raw is the baud rate value the user dialled
                baud = baud_raw if baud_raw is not None else (self._rate / nsps)
                self._spin_nsps.setValue(baud)

                if source == 'spinbox':
                    # Re-center main slider on new baud value and reset coarse/fine
                    half = max(baud * 0.5, 1.0)
                    lo = max(1e-6, baud - half)
                    hi = baud + half
                    self._sld_main._lo = lo
                    self._sld_main._hi = hi
                    coarse_range = max(baud * 0.02, 1.0)
                    fine_range   = max(baud * 0.001, 0.1)
                    self._sld_coarse._lo = -coarse_range
                    self._sld_coarse._hi =  coarse_range
                    self._sld_fine._lo   = -fine_range
                    self._sld_fine._hi   =  fine_range
                    self._set_main(baud)
                    self._set_coarse(0.0)
                    self._set_fine(0.0)
            else:
                # SPS mode — spinbox shows nsps
                self._spin_nsps.setValue(nsps)

                if source == 'spinbox':
                    # Re-center main slider window and reset coarse/fine
                    lo = max(2.0, round(nsps) - 14)
                    hi = round(nsps) + 14
                    self._sld_main._lo = lo
                    self._sld_main._hi = hi
                    self._set_main(nsps)
                    self._set_coarse(0.0)
                    self._set_fine(0.0)
                # For slider sources: no re-centering, just update spin
        finally:
            self._updating = False

        self._update_info_panel()
        self._schedule_update()

    def _update_info_panel(self):
        fs   = self._rate
        nsps = max(self._nsps, 1e-9)
        br   = fs / nsps
        ts   = 1.0 / br if br > 0 else float('inf')

        def _fmt_freq(f):
            if f >= 1e9:   return f"{f/1e9:.4g} GHz"
            if f >= 1e6:   return f"{f/1e6:.4g} MHz"
            if f >= 1e3:   return f"{f/1e3:.4g} kHz"
            return f"{f:.4g} Hz"

        def _fmt_time(t):
            if t == float('inf'): return "∞"
            if t < 1e-6:  return f"{t*1e9:.4g} ns"
            if t < 1e-3:  return f"{t*1e6:.4g} µs"
            if t < 1.0:   return f"{t*1e3:.4g} ms"
            return f"{t:.4g} s"

        self._lbl_fs.setText(_fmt_freq(fs))
        self._lbl_br.setText(_fmt_freq(br))
        self._lbl_ts.setText(_fmt_time(ts))

        # SPS row — shown and highlighted when cycling by Baud Rate
        if self._cycle_mode == 'baud':
            self._lbl_sps.setText(f"{nsps:.6g}")

    def _refresh_mini_curve(self):
        sig = _compute_signal(self._raw_samples, self._mode, self._rate)
        mx = np.max(np.abs(sig)) if len(sig) else 1.0
        if mx < 1e-12:
            mx = 1.0
        norm = sig / mx
        self._mini_curve.setData(
            np.arange(len(norm), dtype=np.float32), norm
        )

    # ── Debounced update ──────────────────────────────────────────────────────

    def _schedule_update(self, delay_ms: int = 30):
        if not hasattr(self, '_update_timer'):
            self._update_timer = QTimer(self)
            self._update_timer.setSingleShot(True)
            self._update_timer.timeout.connect(self._update_eye_diagram)
        self._update_timer.start(delay_ms)

    def _update_eye_diagram(self):
        sig = _compute_signal(self._trunc_samples, self._mode, self._rate)
        if len(sig) < 2:
            self._eye_data_item.setData([], [])
            return

        t1, y1, t2, y2 = _eye_segments(sig, self._nsps, self._offset)
        if len(t1) == 0:
            self._eye_data_item.setData([], [])
            return

        xs, ys = _build_multiline_data(t1, y1, t2, y2)
        self._eye_data_item.setData(xs, ys)

        # Fix X range to [-0.5, 0.5] like the MATLAB app
        self._eye_plot_item.setXRange(-0.5, 0.5, padding=0)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)

        # Background
        self._eye_plot_widget.setBackground(p.plot_bg)
        self._mini_widget.setBackground(p.plot_bg)

        # Eye diagram line colour
        self._eye_data_item.setPen(pg.mkPen(p.accent, width=1))

        # Mini curve colour
        self._mini_curve.setPen(pg.mkPen(p.accent, width=1))

        # Axis pens
        for pi in (self._eye_plot_item, self._mini_item):
            for ax in ('left', 'bottom'):
                pi.getAxis(ax).setPen(p.text_dim)
                pi.getAxis(ax).setTextPen(p.text_dim)

        # Toolbar styling
        toolbar_style = (
            f"QFrame#td_toolbar {{ background-color: {p.bg_sidebar}; "
            f"border-bottom: 1px solid {p.border}; }}"
        )
        self.setStyleSheet(toolbar_style)

        # Group box label colours handled by global stylesheet

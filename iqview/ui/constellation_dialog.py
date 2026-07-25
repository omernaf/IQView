"""iqview/ui/constellation_dialog.py

Interactive Scatter Plot / Constellation tab for IQView.
Allows dynamic tuning of downsampling factor, sample timing offset,
carrier phase, and 3-tier frequency offset for complex IQ signals.

Features:
 - Integer Downsampling Factor N (with Baud Rate info)
 - Dynamic Sample Offset slider ranging from 0 to N-1
 - Two-tier (Coarse + Fine) Carrier Phase sliders centered at 0°
 - Three-tier (Coarse + Medium + Fine) Frequency Offset sliders centered at 0 Hz
 - Mini waveform overview with two draggable range handles
 - Plot controls: Point size, trajectory lines, quadrant crosshairs, unit circle
 - High-contrast Dark/Light theme integration
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QDoubleSpinBox,
    QFrame, QSizePolicy, QFormLayout, QGroupBox,
    QSlider, QCheckBox,
)

from .themes import get_palette

# ── Constants ────────────────────────────────────────────────────────────────

MAX_CONSTELLATION_SAMPLES = 500_000   # hard cap to keep rendering ultra-fast

# ── Constellation DSP Core ───────────────────────────────────────────────────

def _process_constellation(samples: np.ndarray, rate: float,
                           downsample_factor: int, sample_offset: int,
                           phase_deg: float, freq_hz: float) -> np.ndarray:
    """
    Applies frequency offset correction, phase rotation, and downsampling.
    """
    n = len(samples)
    if n == 0 or downsample_factor < 1:
        return np.empty(0, dtype=np.complex64)

    # 1. Frequency Offset Correction: e^(-j 2pi f_offset t)
    if abs(freq_hz) > 1e-9:
        t = np.arange(n, dtype=np.float64) / rate
        cfo_corr = np.exp(-1j * 2.0 * np.pi * freq_hz * t).astype(np.complex64)
        samples = samples * cfo_corr

    # 2. Carrier Phase Rotation: e^(j rad)
    if abs(phase_deg) > 1e-9:
        phase_rad = np.radians(phase_deg)
        samples = samples * np.complex64(np.exp(1j * phase_rad))

    # 3. Downsampling with Sample Offset
    offset = min(max(0, int(sample_offset)), downsample_factor - 1)
    downsampled = samples[offset::downsample_factor]
    return downsampled


# ── Main View Widget ─────────────────────────────────────────────────────────

class ConstellationView(QWidget):
    """
    Tab widget containing the interactive scatter plot / constellation viewer.

    Parameters
    ----------
    samples : np.ndarray  complex (or real) IQ samples
    sample_rate : float   samples per second
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
        self._raw_samples = samples.astype(np.complex64) if np.iscomplexobj(samples) else samples.astype(np.float32) + 0j
        self._rate = float(sample_rate)

        # Truncate to max allowed
        if len(self._raw_samples) > MAX_CONSTELLATION_SAMPLES:
            self._raw_samples = self._raw_samples[:MAX_CONSTELLATION_SAMPLES]

        self._trunc_samples = self._raw_samples   # range-limited sub-segment
        self._trunc_start = 0                     # index into _raw_samples
        self._trunc_end = len(self._raw_samples)

        # DSP parameters
        self._downsample_factor = 1
        self._sample_offset = 0
        self._phase_coarse = 0.0     # [-180, +180] deg
        self._phase_fine = 0.0       # [-5, +5] deg
        self._freq_coarse = 0.0      # [-rate/2, +rate/2] Hz (Coarse / Wide)
        self._freq_medium = 0.0      # [-1000, +1000] Hz (Medium)
        self._freq_fine = 0.0        # [-50, +50] Hz (Fine)

        # Plot customization
        self._point_size = 4
        self._show_trajectory = False
        self._show_crosshairs = True

        # Suppress recursive slider signal loops
        self._updating = False

        # ── Layout ──────────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Options toolbar ─────────────────────────────────────────────────
        self._build_options_toolbar(root)

        # ── Main scatter plot ───────────────────────────────────────────────
        self._plot_widget = pg.PlotWidget()
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.setMenuEnabled(False)
        self._plot_item.hideButtons()
        self._plot_item.showGrid(x=True, y=True, alpha=0.2)
        self._plot_item.setLabel('bottom', 'In-Phase (I)')
        self._plot_item.setLabel('left', 'Quadrature (Q)')
        self._plot_item.setAspectLocked(True, 1.0)

        # Crosshairs at I=0, Q=0
        self._cross_v = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen('#555555', width=1, style=Qt.PenStyle.DashLine))
        self._cross_h = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('#555555', width=1, style=Qt.PenStyle.DashLine))
        self._plot_item.addItem(self._cross_v)
        self._plot_item.addItem(self._cross_h)

        # Unit Circle reference
        t_circle = np.linspace(0, 2 * np.pi, 200)
        self._unit_circle = pg.PlotDataItem(
            np.cos(t_circle), np.sin(t_circle),
            pen=pg.mkPen('#444444', width=1, style=Qt.PenStyle.DotLine)
        )
        self._plot_item.addItem(self._unit_circle)

        # Constellation data item
        self._scatter_item = pg.PlotDataItem(
            pen=None,
            symbol='o',
            symbolSize=self._point_size,
            symbolPen=None,
            symbolBrush=pg.mkBrush('#00aaff')
        )
        self._plot_item.addItem(self._scatter_item)
        root.addWidget(self._plot_widget, stretch=3)

        # ── Mini overview plot ──────────────────────────────────────────────
        self._build_mini_overview(root)

        # ── Control sliders + info panel ────────────────────────────────────
        self._build_controls(root)

        # ── Initial render ──────────────────────────────────────────────────
        self.refresh_theme()
        self._update_constellation()

    # ── Options Toolbar ──────────────────────────────────────────────────────

    def _build_options_toolbar(self, parent_layout):
        toolbar = QFrame()
        toolbar.setObjectName("td_toolbar")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(8, 4, 8, 4)
        tl.setSpacing(12)

        # Point size (adequately sized spinbox)
        lbl_pt = QLabel("Point Size:")
        tl.addWidget(lbl_pt)
        self._spin_point_size = QSpinBox()
        self._spin_point_size.setRange(1, 20)
        self._spin_point_size.setValue(self._point_size)
        self._spin_point_size.setFixedWidth(75)
        self._spin_point_size.setMinimumWidth(75)
        self._spin_point_size.valueChanged.connect(self._on_point_size_changed)
        tl.addWidget(self._spin_point_size)

        # Trajectory
        self._chk_trajectory = QCheckBox("Trajectory Lines")
        self._chk_trajectory.setChecked(self._show_trajectory)
        self._chk_trajectory.toggled.connect(self._on_trajectory_toggled)
        tl.addWidget(self._chk_trajectory)

        # Crosshairs & Circle
        self._chk_crosshairs = QCheckBox("Grid & Crosshairs")
        self._chk_crosshairs.setChecked(self._show_crosshairs)
        self._chk_crosshairs.toggled.connect(self._on_crosshairs_toggled)
        tl.addWidget(self._chk_crosshairs)

        tl.addStretch()

        # Sample count info
        n = len(self._raw_samples)
        was_capped = n >= MAX_CONSTELLATION_SAMPLES
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
        sig_mag = np.abs(self._raw_samples)
        mx = np.max(sig_mag) if len(sig_mag) else 1.0
        if mx < 1e-12:
            mx = 1.0
        norm = sig_mag / mx

        self._mini_curve = pg.PlotDataItem(
            np.arange(n, dtype=np.float32), norm,
            pen=pg.mkPen('#00aaff', width=1)
        )
        self._mini_item.addItem(self._mini_curve)
        self._mini_item.setXRange(0, n, padding=0)
        self._mini_item.setYRange(0, 1.05, padding=0)

        # Draggable handles
        self._handle1 = pg.InfiniteLine(pos=0, angle=90, movable=True,
                                        pen=pg.mkPen('#ffffff', width=2))
        self._handle2 = pg.InfiniteLine(pos=n, angle=90, movable=True,
                                        pen=pg.mkPen('#ffffff', width=2))
        self._handle1.setBounds([0, n])
        self._handle2.setBounds([0, n])
        self._mini_item.addItem(self._handle1)
        self._mini_item.addItem(self._handle2)

        # Gray shade patches
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

        self._mini_widget.setFixedHeight(80)
        parent_layout.addWidget(self._mini_widget)

    # ── Controls Panel ────────────────────────────────────────────────────────

    def _build_controls(self, parent_layout):
        ctrl = QWidget()
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)

        def _make_int_slider(lo, hi, init=0):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            s.setValue(init)
            return s

        def _make_float_slider(lo, hi, init=0.0, ticks=10000):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, ticks)
            s._lo = float(lo)
            s._hi = float(hi)
            s._ticks = ticks

            def _get():
                return s._lo + (s.value() / s._ticks) * (s._hi - s._lo)

            def _set(v):
                frac = (v - s._lo) / (s._hi - s._lo)
                s.setValue(int(round(max(0.0, min(1.0, frac)) * s._ticks)))

            _set(init)
            return s, _get, _set

        # ── 1. Downsampling & Timing Group ──────────────────────────────────
        grp_timing = QGroupBox("Downsampling & Timing")
        fl_timing = QFormLayout(grp_timing)
        fl_timing.setSpacing(4)

        # Downsample Factor N
        self._sld_downsample = _make_int_slider(1, 500, init=1)
        self._spin_downsample = QSpinBox()
        self._spin_downsample.setRange(1, 10000)
        self._spin_downsample.setValue(1)
        self._spin_downsample.setFixedWidth(75)

        row_ds = QHBoxLayout()
        row_ds.addWidget(self._sld_downsample)
        row_ds.addWidget(self._spin_downsample)
        fl_timing.addRow("Downsample (N):", row_ds)

        # Sample Offset (0 to N-1)
        self._sld_offset = _make_int_slider(0, 0, init=0)
        self._spin_offset = QSpinBox()
        self._spin_offset.setRange(0, 0)
        self._spin_offset.setValue(0)
        self._spin_offset.setFixedWidth(75)

        row_off = QHBoxLayout()
        row_off.addWidget(self._sld_offset)
        row_off.addWidget(self._spin_offset)
        fl_timing.addRow("Offset (0..N-1):", row_off)

        self._sld_downsample.valueChanged.connect(self._on_downsample_slider)
        self._spin_downsample.valueChanged.connect(self._on_downsample_spin)
        self._sld_offset.valueChanged.connect(self._on_offset_slider)
        self._spin_offset.valueChanged.connect(self._on_offset_spin)

        cl.addWidget(grp_timing, stretch=2)

        # ── 2. Carrier Phase Group ──────────────────────────────────────────
        grp_phase = QGroupBox("Carrier Phase")
        fl_phase = QFormLayout(grp_phase)
        fl_phase.setSpacing(4)

        self._sld_p_coarse, self._get_p_coarse, self._set_p_coarse = _make_float_slider(-180.0, 180.0, 0.0)
        self._spin_p_coarse = QDoubleSpinBox()
        self._spin_p_coarse.setRange(-180.0, 180.0)
        self._spin_p_coarse.setDecimals(1)
        self._spin_p_coarse.setSuffix("°")
        self._spin_p_coarse.setFixedWidth(75)

        row_pc = QHBoxLayout()
        row_pc.addWidget(self._sld_p_coarse)
        row_pc.addWidget(self._spin_p_coarse)
        fl_phase.addRow("Coarse:", row_pc)

        self._sld_p_fine, self._get_p_fine, self._set_p_fine = _make_float_slider(-5.0, 5.0, 0.0)
        self._spin_p_fine = QDoubleSpinBox()
        self._spin_p_fine.setRange(-5.0, 5.0)
        self._spin_p_fine.setDecimals(2)
        self._spin_p_fine.setSuffix("°")
        self._spin_p_fine.setFixedWidth(75)

        row_pf = QHBoxLayout()
        row_pf.addWidget(self._sld_p_fine)
        row_pf.addWidget(self._spin_p_fine)
        fl_phase.addRow("Fine:", row_pf)

        btn_reset_phase = QPushButton("Reset 0°")
        btn_reset_phase.setFixedWidth(75)
        btn_reset_phase.clicked.connect(self._on_reset_phase)
        fl_phase.addRow("", btn_reset_phase)

        self._sld_p_coarse.valueChanged.connect(self._on_phase_coarse_slider)
        self._spin_p_coarse.valueChanged.connect(self._on_phase_coarse_spin)
        self._sld_p_fine.valueChanged.connect(self._on_phase_fine_slider)
        self._spin_p_fine.valueChanged.connect(self._on_phase_fine_spin)

        cl.addWidget(grp_phase, stretch=2)

        # ── 3. Frequency Offset Group (3 Tiers) ─────────────────────────────
        grp_freq = QGroupBox("Frequency Offset")
        fl_freq = QFormLayout(grp_freq)
        fl_freq.setSpacing(4)

        max_fc = float(self._rate / 2.0)
        # Tier 1: Coarse [-fs/2, +fs/2]
        self._sld_f_coarse, self._get_f_coarse, self._set_f_coarse = _make_float_slider(-max_fc, max_fc, 0.0)
        self._spin_f_coarse = QDoubleSpinBox()
        self._spin_f_coarse.setRange(-max_fc, max_fc)
        self._spin_f_coarse.setDecimals(1)
        self._spin_f_coarse.setSuffix(" Hz")
        self._spin_f_coarse.setFixedWidth(95)

        row_fc = QHBoxLayout()
        row_fc.addWidget(self._sld_f_coarse)
        row_fc.addWidget(self._spin_f_coarse)
        fl_freq.addRow("Coarse:", row_fc)

        # Tier 2: Medium [-1000, +1000] Hz
        self._sld_f_medium, self._get_f_medium, self._set_f_medium = _make_float_slider(-1000.0, 1000.0, 0.0)
        self._spin_f_medium = QDoubleSpinBox()
        self._spin_f_medium.setRange(-1000.0, 1000.0)
        self._spin_f_medium.setDecimals(1)
        self._spin_f_medium.setSuffix(" Hz")
        self._spin_f_medium.setFixedWidth(95)

        row_fm = QHBoxLayout()
        row_fm.addWidget(self._sld_f_medium)
        row_fm.addWidget(self._spin_f_medium)
        fl_freq.addRow("Medium:", row_fm)

        # Tier 3: Fine [-50, +50] Hz
        self._sld_f_fine, self._get_f_fine, self._set_f_fine = _make_float_slider(-50.0, 50.0, 0.0)
        self._spin_f_fine = QDoubleSpinBox()
        self._spin_f_fine.setRange(-50.0, 50.0)
        self._spin_f_fine.setDecimals(2)
        self._spin_f_fine.setSuffix(" Hz")
        self._spin_f_fine.setFixedWidth(95)

        row_ff = QHBoxLayout()
        row_ff.addWidget(self._sld_f_fine)
        row_ff.addWidget(self._spin_f_fine)
        fl_freq.addRow("Fine:", row_ff)

        btn_reset_freq = QPushButton("Reset 0 Hz")
        btn_reset_freq.setFixedWidth(95)
        btn_reset_freq.clicked.connect(self._on_reset_freq)
        fl_freq.addRow("", btn_reset_freq)

        self._sld_f_coarse.valueChanged.connect(self._on_freq_coarse_slider)
        self._spin_f_coarse.valueChanged.connect(self._on_freq_coarse_spin)
        self._sld_f_medium.valueChanged.connect(self._on_freq_medium_slider)
        self._spin_f_medium.valueChanged.connect(self._on_freq_medium_spin)
        self._sld_f_fine.valueChanged.connect(self._on_freq_fine_slider)
        self._spin_f_fine.valueChanged.connect(self._on_freq_fine_spin)

        cl.addWidget(grp_freq, stretch=3)

        # ── 4. Signal Info Panel ────────────────────────────────────────────
        info_grp = QGroupBox("Signal Info")
        il = QFormLayout(info_grp)
        il.setSpacing(4)

        def _ro_label():
            lbl = QLabel("—")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet("font-family: Consolas; font-size: 11px;")
            return lbl

        self._lbl_fs       = _ro_label()
        self._lbl_ds       = _ro_label()
        self._lbl_br       = _ro_label()
        self._lbl_ts       = _ro_label()
        self._lbl_tot_p    = _ro_label()
        self._lbl_tot_f    = _ro_label()
        self._lbl_symbols  = _ro_label()

        il.addRow("Sample Freq:",  self._lbl_fs)
        il.addRow("Downsample:",   self._lbl_ds)
        il.addRow("Baud Rate:",    self._lbl_br)
        il.addRow("Symbol Time:",  self._lbl_ts)
        il.addRow("Total Phase:",  self._lbl_tot_p)
        il.addRow("Total Freq:",   self._lbl_tot_f)
        il.addRow("Symbols:",      self._lbl_symbols)

        cl.addWidget(info_grp, stretch=1)
        parent_layout.addWidget(ctrl)

        self._update_info_panel()

    # ── Dynamic Control Sync Slots ──────────────────────────────────────────

    def _sync_offset_bounds(self):
        """Update maximum allowed sample offset slider/spinbox based on current N."""
        n = max(1, self._downsample_factor)
        max_offset = n - 1
        self._updating = True
        try:
            self._sld_offset.setRange(0, max_offset)
            self._spin_offset.setRange(0, max_offset)
            if self._sample_offset > max_offset:
                self._sample_offset = max_offset
                self._sld_offset.setValue(max_offset)
                self._spin_offset.setValue(max_offset)
        finally:
            self._updating = False

    def _on_downsample_slider(self, val: int):
        if self._updating: return
        self._downsample_factor = max(1, val)
        self._updating = True
        self._spin_downsample.setValue(self._downsample_factor)
        self._updating = False
        self._sync_offset_bounds()
        self._update_info_panel()
        self._schedule_update()

    def _on_downsample_spin(self, val: int):
        if self._updating: return
        self._downsample_factor = max(1, val)
        self._updating = True
        if self._downsample_factor <= self._sld_downsample.maximum():
            self._sld_downsample.setValue(self._downsample_factor)
        self._updating = False
        self._sync_offset_bounds()
        self._update_info_panel()
        self._schedule_update()

    def _on_offset_slider(self, val: int):
        if self._updating: return
        self._sample_offset = max(0, min(val, self._downsample_factor - 1))
        self._updating = True
        self._spin_offset.setValue(self._sample_offset)
        self._updating = False
        self._schedule_update()

    def _on_offset_spin(self, val: int):
        if self._updating: return
        self._sample_offset = max(0, min(val, self._downsample_factor - 1))
        self._updating = True
        self._sld_offset.setValue(self._sample_offset)
        self._updating = False
        self._schedule_update()

    # Phase slots
    def _on_phase_coarse_slider(self):
        if self._updating: return
        self._phase_coarse = self._get_p_coarse()
        self._updating = True
        self._spin_p_coarse.setValue(self._phase_coarse)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_phase_coarse_spin(self, val: float):
        if self._updating: return
        self._phase_coarse = val
        self._updating = True
        self._set_p_coarse(val)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_phase_fine_slider(self):
        if self._updating: return
        self._phase_fine = self._get_p_fine()
        self._updating = True
        self._spin_p_fine.setValue(self._phase_fine)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_phase_fine_spin(self, val: float):
        if self._updating: return
        self._phase_fine = val
        self._updating = True
        self._set_p_fine(val)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_reset_phase(self):
        self._phase_coarse = 0.0
        self._phase_fine = 0.0
        self._updating = True
        self._set_p_coarse(0.0)
        self._spin_p_coarse.setValue(0.0)
        self._set_p_fine(0.0)
        self._spin_p_fine.setValue(0.0)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    # Frequency slots (3 Tiers)
    def _on_freq_coarse_slider(self):
        if self._updating: return
        self._freq_coarse = self._get_f_coarse()
        self._updating = True
        self._spin_f_coarse.setValue(self._freq_coarse)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_freq_coarse_spin(self, val: float):
        if self._updating: return
        self._freq_coarse = val
        self._updating = True
        self._set_f_coarse(val)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_freq_medium_slider(self):
        if self._updating: return
        self._freq_medium = self._get_f_medium()
        self._updating = True
        self._spin_f_medium.setValue(self._freq_medium)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_freq_medium_spin(self, val: float):
        if self._updating: return
        self._freq_medium = val
        self._updating = True
        self._set_f_medium(val)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_freq_fine_slider(self):
        if self._updating: return
        self._freq_fine = self._get_f_fine()
        self._updating = True
        self._spin_f_fine.setValue(self._freq_fine)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_freq_fine_spin(self, val: float):
        if self._updating: return
        self._freq_fine = val
        self._updating = True
        self._set_f_fine(val)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    def _on_reset_freq(self):
        self._freq_coarse = 0.0
        self._freq_medium = 0.0
        self._freq_fine = 0.0
        self._updating = True
        self._set_f_coarse(0.0)
        self._spin_f_coarse.setValue(0.0)
        self._set_f_medium(0.0)
        self._spin_f_medium.setValue(0.0)
        self._set_f_fine(0.0)
        self._spin_f_fine.setValue(0.0)
        self._updating = False
        self._update_info_panel()
        self._schedule_update()

    # Plot option slots
    def _on_point_size_changed(self, val: int):
        self._point_size = val
        self._scatter_item.setSymbolSize(val)

    def _on_trajectory_toggled(self, checked: bool):
        self._show_trajectory = checked
        if checked:
            p = get_palette(self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark")
            self._scatter_item.setPen(pg.mkPen(p.accent, width=1))
        else:
            self._scatter_item.setPen(None)

    def _on_crosshairs_toggled(self, checked: bool):
        self._show_crosshairs = checked
        self._cross_v.setVisible(checked)
        self._cross_h.setVisible(checked)
        self._unit_circle.setVisible(checked)

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

    # ── Info Panel Update ────────────────────────────────────────────────────

    def _update_info_panel(self):
        fs = self._rate
        n = max(1, self._downsample_factor)
        br = fs / n
        ts = 1.0 / br if br > 0 else float('inf')
        tot_phase = self._phase_coarse + self._phase_fine
        tot_freq = self._freq_coarse + self._freq_medium + self._freq_fine
        num_symbols = len(self._trunc_samples) // n

        def _fmt_freq(f):
            if abs(f) >= 1e9:   return f"{f/1e9:.4g} GHz"
            if abs(f) >= 1e6:   return f"{f/1e6:.4g} MHz"
            if abs(f) >= 1e3:   return f"{f/1e3:.4g} kHz"
            return f"{f:.4g} Hz"

        def _fmt_time(t):
            if t == float('inf'): return "∞"
            if t < 1e-6:  return f"{t*1e9:.4g} ns"
            if t < 1e-3:  return f"{t*1e6:.4g} µs"
            if t < 1.0:   return f"{t*1e3:.4g} ms"
            return f"{t:.4g} s"

        self._lbl_fs.setText(_fmt_freq(fs))
        self._lbl_ds.setText(str(n))
        self._lbl_br.setText(_fmt_freq(br))
        self._lbl_ts.setText(_fmt_time(ts))
        self._lbl_tot_p.setText(f"{tot_phase:.2f}°")
        self._lbl_tot_f.setText(_fmt_freq(tot_freq))
        self._lbl_symbols.setText(f"{num_symbols:,}")

    # ── Debounced Render ─────────────────────────────────────────────────────

    def _schedule_update(self, delay_ms: int = 30):
        if not hasattr(self, '_update_timer'):
            self._update_timer = QTimer(self)
            self._update_timer.setSingleShot(True)
            self._update_timer.timeout.connect(self._update_constellation)
        self._update_timer.start(delay_ms)

    def _update_constellation(self):
        tot_phase = self._phase_coarse + self._phase_fine
        tot_freq = self._freq_coarse + self._freq_medium + self._freq_fine

        symbols = _process_constellation(
            self._trunc_samples, self._rate,
            self._downsample_factor, self._sample_offset,
            tot_phase, tot_freq
        )

        if len(symbols) == 0:
            self._scatter_item.setData([], [])
            return

        x = symbols.real.astype(np.float32)
        y = symbols.imag.astype(np.float32)
        self._scatter_item.setData(x, y)

    # ── Theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        theme = self.settings_mgr.get("ui/theme", "Dark") if self.settings_mgr else "Dark"
        p = get_palette(theme)

        # Background
        self._plot_widget.setBackground(p.plot_bg)
        self._mini_widget.setBackground(p.plot_bg)

        # Symbols & trajectory pen
        self._scatter_item.setSymbolBrush(pg.mkBrush(p.accent))
        if self._show_trajectory:
            self._scatter_item.setPen(pg.mkPen(p.accent, width=1))

        # Mini curve colour
        self._mini_curve.setPen(pg.mkPen(p.accent, width=1))

        # Axis pens
        for pi in (self._plot_item, self._mini_item):
            for ax in ('left', 'bottom'):
                pi.getAxis(ax).setPen(p.text_dim)
                pi.getAxis(ax).setTextPen(p.text_dim)

        # High-contrast theme stylesheet for controls and headers
        style = f"""
            QWidget {{
                color: {p.text_main};
                font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
            }}
            QFrame#td_toolbar {{
                background-color: {p.bg_sidebar};
                border-bottom: 1px solid {p.border};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {p.border};
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
                color: {p.text_header};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
                color: {p.text_header};
            }}
            QLabel {{
                color: {p.text_main};
            }}
            QSpinBox, QDoubleSpinBox {{
                background-color: {p.bg_input};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 3px;
                padding: 2px 4px;
            }}
            QPushButton {{
                background-color: {p.bg_widget};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 3px;
                padding: 3px 8px;
            }}
            QPushButton:hover {{
                background-color: {p.accent_dim};
                border-color: {p.accent};
            }}
        """
        self.setStyleSheet(style)

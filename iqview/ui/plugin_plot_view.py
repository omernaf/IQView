import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QButtonGroup, QLabel, QFrame, QScrollBar, QGridLayout, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from .widgets import CustomViewBox, format_tooltip_with_keybind
from .base_1d import Base1DPlotView, Base1DMarkerPanel
from .themes import get_palette, get_scrollbar_stylesheet
from ..dsp.domain_transforms import compute_region_statistics


TRACE_COLORS = [
    "#0072BD",  # Blue
    "#D95319",  # Orange-Red
    "#EDB120",  # Gold
    "#77AC30",  # Green
    "#4DBEEE",  # Cyan
    "#A2142F",  # Crimson
    "#7E2F8E",  # Purple
    "#00E676",  # Bright Mint
]


class PluginPlotMarkerPanel(Base1DMarkerPanel):
    """Marker panel for custom 1D plugin plots (`PluginPlotView`)."""

    def __init__(self, controller):
        super().__init__(
            controller,
            primary_mode="TIME",
            fixed_height=160,
            row_v1_default="Samples",
            row_v2_default="Time (s)",
            row_v3_default="1/T (Hz)",
            delta_v2_readonly=False,
            has_filter_mode=False,
            stats_has_inv_row=True,
            stats_has_integrated=False,
            stats_is_freq=False,
        )

    def _x_row_label(self) -> str:
        x_lbl = getattr(self.controller, "x_label_text", "Time")
        x_unit = getattr(self.controller, "x_units_text", "s")
        return f"{x_lbl} ({x_unit})" if x_unit else str(x_lbl)

    def _inv_row_label(self) -> str:
        x_unit = getattr(self.controller, "x_units_text", "s")
        if x_unit in ("s", "sec"):
            return "1/T (Hz)"
        elif x_unit == "Hz":
            return "1/F (s)"
        return "1/X"

    def update_headers(self, mode, y_axis_label="Amplitude"):
        self.row_v1_label.blockSignals(True)
        self.row_v2_label.blockSignals(True)

        display_mode = self._switch_stacked_page(
            mode, ["TIME", "MAG", "TIME_ENDLESS", "MAG_ENDLESS", "STATS"]
        )

        if display_mode in ["TIME", "TIME_ENDLESS"]:
            s = getattr(self.controller, "settings_mgr", None)
            show_inv = s.get("ui/show_inv_time", False) if s else False
            self.row_v1_label.setText("Samples")
            self.row_v2_label.setText(self._x_row_label())
            self.row_v3_label.setText(self._inv_row_label())
            self.row_v1_label.show()
            self.row_v2_label.show()
            self.row_v3_label.setVisible(show_inv)

            self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row_v2_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(self.row_v3_label, 3, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.m_widgets[i]["v2"], 1, i + 1)
                self.grid.addWidget(self.m_widgets[i]["v1"], 2, i + 1)
                self.grid.addWidget(self.m_widgets[i]["v3"], 3, i + 1)
                self.m_widgets[i]["v1"].show()
                self.m_widgets[i]["v2"].show()
                self.m_widgets[i]["v3"].setVisible(show_inv)
            self.grid.addWidget(self.delta_v2, 1, 3); self.delta_v2.show()
            self.grid.addWidget(self.delta_v1, 2, 3); self.delta_v1.show()
            self.grid.addWidget(self.delta_v3, 3, 3); self.delta_v3.setVisible(show_inv)
            self.grid.addWidget(self.center_v2, 1, 4); self.center_v2.show()
            self.grid.addWidget(self.center_v1, 2, 4); self.center_v1.show()
            self.grid.addWidget(self.center_v3, 3, 4); self.center_v3.setVisible(show_inv)
        else:  # MAG
            self.row_v1_label.setText(y_axis_label)
            self.row_v1_label.show()
            self.row_v2_label.hide()
            self.row_v3_label.hide()

            self.grid.addWidget(self.row_v1_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for i in range(2):
                self.grid.addWidget(self.m_widgets[i]["v1"], 1, i + 1)
                self.m_widgets[i]["v1"].show()
                self.m_widgets[i]["v2"].hide()
                self.m_widgets[i]["v3"].hide()
            self.grid.addWidget(self.delta_v1, 1, 3); self.delta_v1.show()
            self.grid.addWidget(self.center_v1, 1, 4); self.center_v1.show()
            self.delta_v2.hide(); self.delta_v3.hide()
            self.center_v2.hide(); self.center_v3.hide()

        self.row_v1_label.blockSignals(False)
        self.row_v2_label.blockSignals(False)

        self._sync_lock_buttons_for_mode(display_mode)

    def update_endless_list(self, markers, mode):
        is_primary = "TIME" in mode
        x_unit = getattr(self.controller, "x_units_text", "s") or "x"
        unit_main = x_unit if is_primary else self.controller.y_label_text
        unit_sub = "Sam" if is_primary else ""
        self.endless_widget.update_markers(
            markers=markers,
            mode=mode,
            is_primary_axis=is_primary,
            unit_main=unit_main,
            unit_sub=unit_sub,
            pos_suffix="sec",
            sub_suffix="sam",
            prec=(9 if is_primary else 6),
            sub_val_fn=lambda val: int(round(val * self.controller.rate)) + 1,
            on_header_created=self.refresh_theme,
        )

    def _update_domain_tooltips(self, s):
        self.btn_marker_time.setToolTip(format_tooltip_with_keybind(
            "X-Axis Markers (Double-click to clear)", s.get("keybinds/time_markers", "T")
        ))
        self.btn_marker_time_endless.setToolTip(format_tooltip_with_keybind(
            "Endless X-Axis Markers (Double-click to clear)", s.get("keybinds/time_endless_markers", "E")
        ))


class PluginPlotView(Base1DPlotView):
    """
    Interactive 1D plot tab for custom plugin outputs (`result.add_plot(...)`).

    Groups all plots produced by a plugin into a single main tab with:
      - Checkable sub-tab buttons (`F1..F10`) in the toolbar for switching plots
      - Multi-trace support (`dict[str, np.ndarray]`) with legend and active-trace selector
      - Full `Base1DPlotView` marker system ($M_1, M_2, \\Delta, \\text{Center}$, locks, endless markers, shadow grids, Region Statistics, and oversampling)
    """

    primary_mode = "TIME"
    primary_endless_mode = "TIME_ENDLESS"
    primary_kb_key = "keybinds/time_markers"
    primary_kb_default = "T"
    primary_endless_kb_key = "keybinds/time_endless_markers"
    primary_endless_kb_default = "E"

    def __init__(
        self,
        plots: list[dict],
        plugin_name: str = "Plugin",
        tab_title: str | None = None,
        parent=None,
        parent_window=None,
    ):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._plugin_name = plugin_name
        self._custom_tab_title = tab_title or f"{plugin_name} - Plots"
        self.parent_window = parent_window
        self.settings_mgr = parent_window.settings_mgr if parent_window else None
        self.is_spectrogram = False

        self.interaction_mode = "TIME"
        self.zoom_mode = False
        self.active_drag_marker = None
        self.last_move_scene_pos = None
        self.markers_time = []
        self.markers_freq = []
        self.markers_time_endless = []
        self.markers_freq_endless = []
        self._block_signals = False
        self._marker_age = {}
        self._marker_age_counter = 0

        self.markers_y_dict = {}
        self.markers_y_endless_dict = {}
        self.zoom_y_dict = {}

        self.grid_time_enabled = False
        self.grid_time_tracking = True
        self.grid_lines_time = []
        self.grid_freq_enabled = False
        self.grid_freq_tracking = True
        self.grid_lines_freq = []
        self.grid_mag_enabled = False
        self.grid_mag_tracking = True
        self.grid_lines_mag = []

        self.zoom_history = []

        self.x_label_text = "Time"
        self.x_units_text = "s"
        self.y_label_text = "Amplitude"
        self.start_time = 0.0
        self.rate = 1.0
        self.time_axis = np.array([0.0, 1.0])
        self.current_plot_data = np.zeros(2, dtype=np.float64)
        self._active_traces: dict[str, np.ndarray] = {}
        self._active_trace_name: str = ""
        self._active_plot_idx: int = 0
        self.legend = None

        self.plots: list[dict] = []
        self._base_plots: list[dict] = []

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(5)

        # --- Marker Panel ---
        self.marker_panel = PluginPlotMarkerPanel(self)
        self.marker_panel.interactionModeChanged.connect(self.set_interaction_mode)
        self.marker_panel.resetZoomRequested.connect(self.reset_zoom)
        self.marker_panel.markerClearRequested.connect(self.handle_marker_clear)
        self.main_layout.addWidget(self.marker_panel)

        # --- Toolbar ---
        self.toolbar = QFrame()
        self.toolbar.setObjectName("plugin_plot_toolbar")
        self.update_toolbar_style()
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 5, 10, 5)

        self.toolbar_layout.addWidget(QLabel("Plot:"))

        self.plot_buttons_layout = QHBoxLayout()
        self.plot_buttons_layout.setSpacing(5)
        self.toolbar_layout.addLayout(self.plot_buttons_layout)

        self.mode_group = QButtonGroup(self)
        self.plot_buttons: list[QPushButton] = []

        self.toolbar_layout.addSpacing(10)

        # Active Trace Selector (visible only when current sub-plot has multiple traces)
        self.trace_label = QLabel("Active Trace:")
        self.trace_combo = QComboBox()
        self.trace_combo.setMinimumWidth(130)
        self.trace_combo.setToolTip("Select active trace for Region Statistics and marker sampling")
        self.trace_combo.currentTextChanged.connect(self._on_active_trace_changed)
        self.toolbar_layout.addWidget(self.trace_label)
        self.toolbar_layout.addWidget(self.trace_combo)
        self.trace_label.hide()
        self.trace_combo.hide()

        self.toolbar_layout.addStretch()
        self.setup_oversample_controls(self.toolbar_layout)

        self.range_label = QLabel("")
        self.range_label.setStyleSheet("color: #888; font-family: Consolas; font-size: 11px;")
        self.toolbar_layout.addWidget(self.range_label)

        self.main_layout.addWidget(self.toolbar)

        # --- Plot & Scrollbars ---
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)

        self.view_box = CustomViewBox(self)
        self.plot_widget = pg.PlotWidget(viewBox=self.view_box)
        self.plot_item = self.plot_widget.getPlotItem()
        self.refresh_plot_style()

        self.grid_layout.addWidget(self.plot_widget, 0, 1)

        self.x_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.y_scroll = QScrollBar(Qt.Orientation.Vertical)
        scrollbar_style = get_scrollbar_stylesheet(get_palette(self._get_theme_name()))
        self.x_scroll.setStyleSheet(scrollbar_style)
        self.y_scroll.setStyleSheet(scrollbar_style)

        self.grid_layout.addWidget(self.y_scroll, 0, 0)
        self.grid_layout.addWidget(self.x_scroll, 1, 1)
        self.x_scroll.hide()
        self.y_scroll.hide()

        self.main_layout.addWidget(self.grid_container)

        # --- Stats Region Item ---
        self.stats_bounds = []
        self.stats_marker_order = []
        self.stats_line = None

        self.stats_region = pg.LinearRegionItem(orientation="vertical")
        self.stats_region.setZValue(9)
        self.stats_region.hide()
        self.plot_item.addItem(self.stats_region)
        self.stats_region.sigRegionChanged.connect(self.update_statistics)

        self.stats_markers = pg.ScatterPlotItem(
            size=10, pen=pg.mkPen(None), brush=pg.mkBrush(255, 0, 0, 200)
        )
        self.stats_markers.hide()
        self.plot_item.addItem(self.stats_markers)

        self.stats_p10_line = pg.InfiniteLine(
            angle=0, pen=pg.mkPen("#00e676", width=1.5, style=Qt.PenStyle.DotLine), movable=False
        )
        self.stats_p10_line.setZValue(90)
        self.stats_p10_line.hide()
        self.plot_item.addItem(self.stats_p10_line)

        self.stats_p90_line = pg.InfiniteLine(
            angle=0, pen=pg.mkPen("#ff3232", width=1.5, style=Qt.PenStyle.DotLine), movable=False
        )
        self.stats_p90_line.setZValue(90)
        self.stats_p90_line.hide()
        self.plot_item.addItem(self.stats_p90_line)

        # Connect scrollbars & grids
        self.view_box.sigRangeChanged.connect(self.update_scrollbars)
        self.view_box.sigRangeChanged.connect(lambda: self.update_grid("TIME"))
        self.view_box.sigRangeChanged.connect(lambda: self.update_grid("MAG"))
        self.x_scroll.valueChanged.connect(self.scroll_view)
        self.y_scroll.valueChanged.connect(self.scroll_view)

        self.set_plots(plots, tab_title=tab_title)
        self.set_interaction_mode("TIME")

    # ------------------------------------------------------------------
    # Plot Data & Sub-Tab Management
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_plot_spec(spec: dict, index: int) -> dict:
        title = str(spec.get("title") or f"Plot {index + 1}")
        raw_y = spec.get("y", np.zeros(2, dtype=np.float64))
        if isinstance(raw_y, dict):
            traces: dict[str, np.ndarray] = {}
            for k, v in raw_y.items():
                arr = np.asarray(v, dtype=np.float64).ravel()
                if len(arr) > 0:
                    traces[str(k)] = arr
            if not traces:
                traces = {"Trace 1": np.zeros(2, dtype=np.float64)}
        else:
            arr = np.asarray(raw_y, dtype=np.float64).ravel()
            if len(arr) == 0:
                arr = np.zeros(2, dtype=np.float64)
            traces = {title: arr}

        first_arr = next(iter(traces.values()))
        n_pts = len(first_arr)

        # Ensure all traces in a multi-trace dict match length n_pts
        for k, arr in list(traces.items()):
            if len(arr) != n_pts:
                m = min(len(arr), n_pts)
                padded = np.zeros(n_pts, dtype=np.float64)
                padded[:m] = arr[:m]
                traces[k] = padded

        raw_x = spec.get("x")
        raw_fs = spec.get("fs")
        primary_mode = str(spec.get("primary_mode", "TIME")).upper()

        if raw_x is not None:
            x_arr = np.asarray(raw_x, dtype=np.float64).ravel()
            if len(x_arr) != n_pts:
                x_arr = np.linspace(
                    float(x_arr[0]) if len(x_arr) > 0 else 0.0,
                    float(x_arr[-1]) if len(x_arr) > 0 else float(max(1, n_pts - 1)),
                    n_pts,
                )
            if raw_fs is not None and raw_fs > 0:
                fs = float(raw_fs)
            elif n_pts > 1 and abs(x_arr[-1] - x_arr[0]) > 1e-15:
                fs = float(n_pts - 1) / abs(float(x_arr[-1] - x_arr[0]))
            else:
                fs = 1.0
        else:
            if raw_fs is not None and raw_fs > 0:
                fs = float(raw_fs)
                if primary_mode == "FREQ":
                    x_arr = np.linspace(-fs / 2.0, fs / 2.0, n_pts, endpoint=False)
                else:
                    x_arr = np.arange(n_pts, dtype=np.float64) / fs
            else:
                fs = 1.0
                x_arr = np.arange(n_pts, dtype=np.float64)

        if len(x_arr) == 1:
            x_arr = np.array([float(x_arr[0]), float(x_arr[0]) + 1.0 / max(fs, 1.0)])
            for k in traces:
                traces[k] = np.repeat(traces[k], 2)

        raw_regions = spec.get("regions") or []
        norm_regions = []
        for reg in raw_regions:
            if isinstance(reg, dict) and "x_start" in reg and "x_end" in reg:
                norm_regions.append({
                    "x_start": float(reg["x_start"]),
                    "x_end": float(reg["x_end"]),
                    "color": str(reg.get("color", "#888888")),
                    "alpha": float(reg.get("alpha", 0.18)),
                    "label": str(reg.get("label", "")),
                    "text": str(reg.get("text", "")),
                })

        return {
            "title": title,
            "traces": traces,
            "is_multi": isinstance(raw_y, dict) and len(traces) > 1,
            "x": x_arr,
            "fs": fs,
            "x_label": str(spec.get("x_label", "Time")),
            "x_units": str(spec.get("x_units", "s")),
            "y_label": str(spec.get("y_label", "Amplitude")),
            "primary_mode": primary_mode,
            "regions": norm_regions,
        }

    def set_plots(self, plots: list[dict], tab_title: str | None = None) -> None:
        """Replace or update the list of sub-plots and refresh the view."""
        if tab_title:
            self._custom_tab_title = tab_title

        normalized = []
        seen_titles: dict[str, int] = {}
        for i, spec in enumerate(plots or []):
            norm = self._normalize_plot_spec(spec, i)
            base_t = norm["title"]
            if base_t in seen_titles:
                seen_titles[base_t] += 1
                norm["title"] = f"{base_t} ({seen_titles[base_t]})"
            else:
                seen_titles[base_t] = 1
            normalized.append(norm)

        self._base_plots = normalized
        # Deep-copy traces/x for active (potentially oversampled) plots
        self.plots = [
            {
                **p,
                "traces": {k: v.copy() for k, v in p["traces"].items()},
                "x": p["x"].copy(),
            }
            for p in normalized
        ]

        for p in self.plots:
            y_key = p["y_label"]
            self.markers_y_dict.setdefault(y_key, [])
            self.markers_y_endless_dict.setdefault(y_key, [])

        self.zoom_y_dict.clear()
        if hasattr(self, "oversample_spin"):
            self.oversample_spin.blockSignals(True)
            self.oversample_spin.setValue(1.0)
            self.oversample_spin.blockSignals(False)

        self._active_plot_idx = min(self._active_plot_idx, max(0, len(self.plots) - 1))
        self.rebuild_plot_buttons()

    def rebuild_plot_buttons(self) -> None:
        for btn in self.plot_buttons:
            self.mode_group.removeButton(btn)
            self.plot_buttons_layout.removeWidget(btn)
            btn.deleteLater()
        self.plot_buttons.clear()

        for i, p in enumerate(self.plots):
            btn = QPushButton(p["title"])
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.mode_group.addButton(btn, i)
            self.plot_buttons_layout.addWidget(btn)
            btn.clicked.connect(lambda checked, idx=i: self.select_subplot(idx))
            self.plot_buttons.append(btn)
            if i == self._active_plot_idx:
                btn.setChecked(True)

        self.update_button_tooltips()

        if self.plots:
            self.select_subplot(self._active_plot_idx)

    def select_subplot(self, idx: int) -> None:
        if not self.plots or idx < 0 or idx >= len(self.plots):
            return
        self._active_plot_idx = idx
        if idx < len(self.plot_buttons) and not self.plot_buttons[idx].isChecked():
            self.plot_buttons[idx].setChecked(True)

        # Apply current oversampling factor if != 1.0 to this subplot
        factor = self.oversample_spin.value() if hasattr(self, "oversample_spin") else 1.0
        self._apply_oversample_to_subplot(idx, factor)

        spec = self.plots[idx]
        self._active_traces = spec["traces"]
        self._active_regions = spec.get("regions", [])
        trace_names = list(self._active_traces.keys())

        self.trace_combo.blockSignals(True)
        self.trace_combo.clear()
        self.trace_combo.addItems(trace_names)
        if self._active_trace_name in self._active_traces:
            self.trace_combo.setCurrentText(self._active_trace_name)
        else:
            self._active_trace_name = trace_names[0]
            self.trace_combo.setCurrentIndex(0)
        self.trace_combo.blockSignals(False)

        is_multi = len(trace_names) > 1
        self.trace_label.setVisible(is_multi)
        self.trace_combo.setVisible(is_multi)

        self.time_axis = spec["x"]
        self.start_time = float(self.time_axis[0])
        self.rate = float(spec["fs"])
        self.x_label_text = spec["x_label"]
        self.x_units_text = spec["x_units"]
        self.y_label_text = spec["y_label"]

        self.markers_y_dict.setdefault(self.y_label_text, [])
        self.markers_y_endless_dict.setdefault(self.y_label_text, [])

        self.stats_region.setBounds([float(self.time_axis[0]), float(self.time_axis[-1])])
        x_end = float(self.time_axis[-1])
        unit_sfx = f" {self.x_units_text}" if self.x_units_text else ""
        self.range_label.setText(
            f"Range: {self.start_time:,.6f} to {x_end:,.6f}{unit_sfx}  |  Fs: {self.rate:g} Hz"
        )

        self._render_current_subplot()

    def _on_active_trace_changed(self, trace_name: str) -> None:
        if not trace_name or trace_name not in self._active_traces:
            return
        self._active_trace_name = trace_name
        self.current_plot_data = self._active_traces[trace_name]
        if hasattr(self, "stats_region") and self.stats_region.isVisible():
            self.update_statistics()
        self.update_marker_info()

    def _apply_oversample_to_subplot(self, idx: int, factor: float) -> None:
        if idx < 0 or idx >= len(self._base_plots):
            return
        base = self._base_plots[idx]
        target = self.plots[idx]
        factor = max(0.01, float(factor))
        if abs(factor - 1.0) < 1e-6:
            target["traces"] = {k: v.copy() for k, v in base["traces"].items()}
            target["x"] = base["x"].copy()
            target["fs"] = base["fs"]
        else:
            from scipy import signal as sp_signal
            base_x = base["x"]
            num_out = max(2, int(round(len(base_x) * factor)))
            new_traces = {}
            for k, arr in base["traces"].items():
                new_traces[k] = np.asarray(sp_signal.resample(arr, num_out), dtype=np.float64)
            target["traces"] = new_traces
            target["x"] = np.linspace(float(base_x[0]), float(base_x[-1]), num_out)
            target["fs"] = base["fs"] * factor

    def _on_oversample_factor_changed(self, val: float) -> None:
        if not self.plots:
            return
        self.zoom_y_dict.clear()
        self.select_subplot(self._active_plot_idx)

    def _get_y_bounds(self):
        if not self._active_traces:
            return super()._get_y_bounds()
        mins, maxs = [], []
        for arr in self._active_traces.values():
            valid = arr[np.isfinite(arr)]
            if len(valid) > 0:
                mins.append(float(np.min(valid)))
                maxs.append(float(np.max(valid)))
        if not mins:
            return 0.0, 1.0
        return min(mins), max(maxs)

    def _render_current_subplot(self) -> None:
        from PyQt6.QtGui import QColor

        old_x_range = None
        if hasattr(self, "view_box") and self.view_box.viewRect() is not None:
            old_x_range, old_y_range = self.view_box.viewRange()
            self.zoom_y_dict[self.y_label_text] = old_y_range

        active_data = self._active_traces.get(
            self._active_trace_name,
            next(iter(self._active_traces.values())) if self._active_traces else np.zeros(2),
        )
        self.current_plot_data = active_data
        self.marker_panel.update_headers(self.interaction_mode, self.y_label_text)

        if self.legend is not None:
            try:
                if self.legend.scene() is not None:
                    self.legend.scene().removeItem(self.legend)
            except Exception:
                pass
            self.legend = None
            self.plot_item.legend = None

        self.plot_item.clear()
        self.stats_markers.clear()

        if getattr(self, "stats_line", None) is not None:
            self.plot_item.addItem(self.stats_line)
        self.plot_item.addItem(self.stats_region)
        self.plot_item.addItem(self.stats_markers)
        if getattr(self, "stats_p10_line", None) is not None:
            if self.stats_p10_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_p10_line)
            self.stats_p10_line.setZValue(90)
        if getattr(self, "stats_p90_line", None) is not None:
            if self.stats_p90_line not in self.plot_item.items:
                self.plot_item.addItem(self.stats_p90_line)
            self.stats_p90_line.setZValue(90)

        self.plot_item.getAxis("bottom").setLabel(
            self.x_label_text, units=self.x_units_text if self.x_units_text else None
        )
        self.plot_item.getAxis("left").setLabel(self.y_label_text)

        theme = self._get_theme_name()
        p = get_palette(theme)

        active_regions = getattr(self, "_active_regions", [])
        is_multi = len(self._active_traces) > 1 or bool(active_regions)
        if is_multi:
            self.legend = self.plot_item.addLegend(offset=(-15, 15))
            self.legend.setLabelTextColor(p.text_main)

        # Render background X-regions (e.g. INIT=gray, IDLE=red, ACTIVE=green)
        seen_region_labels = set()
        y_lo, y_hi = self._get_y_bounds()
        y_mid = 0.5 * (y_lo + y_hi)
        for reg in active_regions:
            x0, x1 = float(reg["x_start"]), float(reg["x_end"])
            if x1 <= x0:
                continue
            c_hex = reg.get("color", "#888888")
            alpha = float(reg.get("alpha", 0.18))
            qcol = QColor(c_hex)
            qcol.setAlphaF(alpha)
            bcol = QColor(c_hex)
            bcol.setAlphaF(min(1.0, alpha * 1.8))
            lr = pg.LinearRegionItem(
                values=[x0, x1],
                orientation="vertical",
                brush=pg.mkBrush(qcol),
                pen=pg.mkPen(bcol, width=1),
                movable=False,
            )
            lr.setZValue(-10)
            self.plot_item.addItem(lr, ignoreBounds=True)

            r_text = str(reg.get("text") or "")
            if r_text:
                txt = pg.TextItem(
                    r_text,
                    color=c_hex,
                    anchor=(0.5, 0.5),
                    angle=90,
                )
                txt.setFont(QFont("Consolas", 8))
                txt.setPos(0.5 * (x0 + x1), y_mid)
                txt.setZValue(20)
                self.plot_item.addItem(txt, ignoreBounds=True)

            r_label = reg.get("label", "")
            if r_label and r_label not in seen_region_labels and self.legend is not None:
                seen_region_labels.add(r_label)
                swatch = pg.PlotDataItem(pen=pg.mkPen(c_hex, width=6))
                self.legend.addItem(swatch, r_label)

        for i, (t_name, t_arr) in enumerate(self._active_traces.items()):
            color = TRACE_COLORS[i % len(TRACE_COLORS)]
            pen = pg.mkPen(color, width=1.2 if is_multi else 0.8)
            if is_multi:
                self.plot_item.plot(self.time_axis, t_arr, pen=pen, name=t_name)
            else:
                self.plot_item.plot(self.time_axis, t_arr, pen=pen)

        # Restore markers
        for m in self.markers_time:
            m.setPen(pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m, ignoreBounds=True)
            m.setZValue(100)

        active_y = self.markers_y_dict.get(self.y_label_text, [])
        for m in active_y:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m, ignoreBounds=True)
            m.setZValue(100)

        active_y_endless = self.markers_y_endless_dict.get(self.y_label_text, [])
        for m in active_y_endless:
            m.setPen(pg.mkPen(p.marker_mag, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m, ignoreBounds=True)
            m.setZValue(100)

        for m in self.markers_time_endless:
            m.setPen(pg.mkPen(p.marker_time, width=2, style=Qt.PenStyle.DashLine))
            self.plot_item.addItem(m, ignoreBounds=True)
            m.setZValue(100)

        t_start, t_end = float(self.time_axis[0]), float(self.time_axis[-1])
        t_total = max(t_end - t_start, 1e-12)
        t_pad = t_total * 0.01

        y_min_data, y_max_data = self._get_y_bounds()
        y_range_val = y_max_data - y_min_data
        if y_range_val == 0:
            y_range_val = 1.0
        y_pad = y_range_val * 0.05

        self.view_box.setLimits(xMin=None, xMax=None, yMin=None, yMax=None)

        if self.y_label_text in self.zoom_y_dict:
            y_r = self.zoom_y_dict[self.y_label_text]
            self.plot_item.setYRange(y_r[0], y_r[1], padding=0)
        else:
            self.plot_item.setYRange(y_min_data - y_pad, y_max_data + y_pad, padding=0)

        if old_x_range is not None and (
            old_x_range[0] >= t_start - t_pad and old_x_range[1] <= t_end + t_pad
        ):
            self.plot_item.setXRange(old_x_range[0], old_x_range[1], padding=0)
        else:
            self.plot_item.setXRange(t_start, t_end, padding=0)

        self.view_box.setLimits(
            xMin=t_start - t_pad,
            xMax=t_end + t_pad,
            yMin=y_min_data - y_pad,
            yMax=y_max_data + y_pad,
        )

        if hasattr(self, "stats_region") and self.stats_region.isVisible():
            self.update_statistics()

        self.update_marker_info()
        self.update_scrollbars()

    # ------------------------------------------------------------------
    # Interaction Mode, Markers & Statistics
    # ------------------------------------------------------------------

    def set_interaction_mode(self, mode):
        if mode == "Y":
            mode = "MAG"
        self.interaction_mode = mode
        self.zoom_mode = mode == "ZOOM"
        if mode not in ("ZOOM", "MOVE"):
            self._prev_interaction_mode = mode

        if mode == "STATS":
            if len(self.stats_bounds) == 1:
                if self.stats_line:
                    self.stats_line.show()
                self.update_statistics()
            elif len(self.stats_bounds) == 2:
                self.stats_region.show()
                self.stats_markers.show()
                self.update_statistics()
            else:
                self.update_statistics()
        else:
            self.stats_region.hide()
            self.stats_markers.hide()
            if self.stats_line:
                self.stats_line.hide()
            if getattr(self, "stats_p10_line", None):
                self.stats_p10_line.hide()
            if getattr(self, "stats_p90_line", None):
                self.stats_p90_line.hide()

        self.refresh_cursor()
        self.marker_panel.update_mode_ui(mode)
        self.marker_panel.update_headers(mode, self.y_label_text)
        self.update_marker_info()

    def refresh_cursor(self):
        mode = self.interaction_mode
        cursor = Qt.CursorShape.ArrowCursor
        if mode == "ZOOM":
            cursor = Qt.CursorShape.CrossCursor
        elif mode == "MOVE":
            cursor = Qt.CursorShape.SizeAllCursor
        elif mode in ["TIME", "MAG", "Y", "TIME_ENDLESS", "MAG_ENDLESS", "STATS"]:
            cursor = Qt.CursorShape.CrossCursor
        self.plot_widget.setCursor(cursor)

    def update_statistics(self):
        s = self.settings_mgr
        prec1 = int(s.get("ui/label_precision", 9)) if s else 9
        if not self.stats_region.isVisible():
            self.marker_panel.clear_stats_fields()
            if len(self.stats_bounds) == 1:
                self.marker_panel.st_row_v1_lbl.setText("Samples")
                self.marker_panel.st_row_v2_lbl.setText(self.marker_panel._x_row_label())
                self.marker_panel.st_row_v3_lbl.setText(self.marker_panel._inv_row_label())
                val = self.stats_bounds[0]
                w = self.marker_panel.st_widgets[0]
                w["v1"].blockSignals(True); w["v1"].setText(f"{val:.{prec1}f}"); w["v1"].blockSignals(False)
                abs_s = int(round(val * self.rate)) + 1
                w["v2"].blockSignals(True); w["v2"].setText(f"{abs_s}"); w["v2"].blockSignals(False)
                inv_val = (1.0 / val) if abs(val) > 1e-12 else float("inf")
                w["v3"].blockSignals(True); w["v3"].setText(f"{inv_val:.{prec1}f}" if inv_val != float("inf") else "∞"); w["v3"].blockSignals(False)
            return
        if len(self.current_plot_data) == 0:
            return

        r_min, r_max = self.stats_region.getRegion()
        stats = compute_region_statistics(
            self.time_axis,
            self.current_plot_data,
            r_min,
            r_max,
            self.y_label_text,
            is_freq_domain=False,
        )
        if stats is None:
            return

        b1, b2 = stats.b1, stats.b2
        t_max, t_min = stats.x_max, stats.x_min

        self.marker_panel.st_row_v1_lbl.setText("Samples")
        self.marker_panel.st_row_v2_lbl.setText(self.marker_panel._x_row_label())
        self.marker_panel.st_row_v3_lbl.setText(self.marker_panel._inv_row_label())

        for i, val in enumerate([b1, b2]):
            w = self.marker_panel.st_widgets[i]
            w["v1"].blockSignals(True); w["v1"].setText(f"{val:.{prec1}f}"); w["v1"].blockSignals(False)
            abs_s = int(round(val * self.rate)) + 1
            w["v2"].blockSignals(True); w["v2"].setText(f"{abs_s}"); w["v2"].blockSignals(False)
            inv_val = (1.0 / val) if abs(val) > 1e-12 else float("inf")
            w["v3"].blockSignals(True); w["v3"].setText(f"{inv_val:.{prec1}f}" if inv_val != float("inf") else "∞"); w["v3"].blockSignals(False)

        dv = abs(b2 - b1)
        cv = (b1 + b2) / 2
        self.marker_panel.st_delta_v1.blockSignals(True); self.marker_panel.st_delta_v1.setText(f"{dv:.{prec1}f}"); self.marker_panel.st_delta_v1.blockSignals(False)
        self.marker_panel.st_center_v1.blockSignals(True); self.marker_panel.st_center_v1.setText(f"{cv:.{prec1}f}"); self.marker_panel.st_center_v1.blockSignals(False)

        s1, s2 = int(round(b1 * self.rate)) + 1, int(round(b2 * self.rate)) + 1
        self.marker_panel.st_delta_v2.blockSignals(True); self.marker_panel.st_delta_v2.setText(f"{abs(s2-s1)+1}"); self.marker_panel.st_delta_v2.blockSignals(False)
        self.marker_panel.st_center_v2.blockSignals(True); self.marker_panel.st_center_v2.setText(f"{int(round(cv*self.rate))+1}"); self.marker_panel.st_center_v2.blockSignals(False)

        self.marker_panel.st_delta_v3.setText(f"{1.0/dv:.{prec1}f}" if dv > 1e-12 else "∞")
        self.marker_panel.st_center_v3.setText(f"{1.0/cv:.{prec1}f}" if abs(cv) > 1e-12 else "∞")

        unit_str = stats.unit_str
        diff_unit_str = stats.diff_unit_str
        panel = self.marker_panel

        if hasattr(panel, "st_res_lbl_val"):
            panel.st_res_lbl_val.setText(f"Value ({unit_str})" if unit_str else "Value")
        if hasattr(panel, "st_res_lbl_mean"):
            panel.st_res_lbl_mean.setText(f"Mean ({unit_str})" if unit_str else "Mean")
        if hasattr(panel, "st_res_lbl_median"):
            panel.st_res_lbl_median.setText(f"Median ({unit_str})" if unit_str else "Median")
        if hasattr(panel, "st_res_lbl_90th"):
            panel.st_res_lbl_90th.setText(f"90th % ({unit_str})" if unit_str else "90th %")
        if hasattr(panel, "st_res_lbl_10th"):
            panel.st_res_lbl_10th.setText(f"10th % ({unit_str})" if unit_str else "10th %")
        if hasattr(panel, "st_res_lbl_diff"):
            panel.st_res_lbl_diff.setText(f"90-10 Diff ({diff_unit_str})" if diff_unit_str else "90-10 Diff")

        self.marker_panel.stats_max_val.setText(f"{stats.p_max:.6g}")
        self.marker_panel.stats_min_val.setText(f"{stats.p_min:.6g}")
        self.marker_panel.stats_mean_val.setText(f"{stats.p_mean:.6g}")
        self.marker_panel.stats_median_val.setText(f"{stats.p_median:.6g}")
        self.marker_panel.stats_90th_val.setText(f"{stats.p_90:.6g}")
        self.marker_panel.stats_10th_val.setText(f"{stats.p_10:.6g}")
        self.marker_panel.stats_diff_val.setText(f"{stats.p_diff:.6g}")

        self.marker_panel.stats_max_time.setText(f"{t_max:.6f}")
        self.marker_panel.stats_min_time.setText(f"{t_min:.6f}")
        self.marker_panel.stats_max_idx.setText(f"{stats.idx_max}")
        self.marker_panel.stats_min_idx.setText(f"{stats.idx_min}")

        self.stats_markers.setData([
            {"pos": (t_max, stats.p_max), "brush": pg.mkBrush(255, 50, 50), "pen": pg.mkPen("#ff3232", width=2), "symbol": "o"},
            {"pos": (t_min, stats.p_min), "brush": pg.mkBrush(50, 255, 50), "pen": pg.mkPen("#32ff32", width=2), "symbol": "t"},
        ])

        show_p10 = self.marker_panel.cb_p10.isChecked() if hasattr(self.marker_panel, "cb_p10") else True
        show_p90 = self.marker_panel.cb_p90.isChecked() if hasattr(self.marker_panel, "cb_p90") else True
        if hasattr(self, "stats_p10_line"):
            self.stats_p10_line.setPos(stats.p_10)
            self.stats_p10_line.setVisible(show_p10)
        if hasattr(self, "stats_p90_line"):
            self.stats_p90_line.setPos(stats.p_90)
            self.stats_p90_line.setVisible(show_p90)

    def update_marker_info(self):
        display_mode = self.interaction_mode
        if display_mode in ["ZOOM", "MOVE", "STATS"]:
            display_mode = getattr(self.marker_panel, "last_marker_mode", "TIME")

        is_time = display_mode in ["TIME", "TIME_ENDLESS"]
        is_endless = "ENDLESS" in display_mode

        self.markers_y_dict.setdefault(self.y_label_text, [])
        self.markers_y_endless_dict.setdefault(self.y_label_text, [])

        if is_endless:
            active_markers = self.markers_time_endless if is_time else self.markers_y_endless_dict[self.y_label_text]
            self.marker_panel.update_endless_list(active_markers, display_mode)
            for i, m in enumerate(active_markers):
                if hasattr(m, "label"):
                    m.label.setFormat(f"M{i+1}")
            if self.interaction_mode not in ["ZOOM", "MOVE", "STATS"]:
                return
        else:
            active_markers = self.markers_time if is_time else self.markers_y_dict[self.y_label_text]

        sorted_m = sorted(active_markers, key=lambda m: m.value())
        self.marker_panel.update_headers(display_mode, self.y_label_text)

        for widget in self.marker_panel.m_widgets:
            for k in widget:
                widget[k].blockSignals(True); widget[k].clear(); widget[k].blockSignals(False)
        for w in [
            self.marker_panel.delta_v1, self.marker_panel.delta_v2, self.marker_panel.delta_v3,
            self.marker_panel.center_v1, self.marker_panel.center_v2, self.marker_panel.center_v3,
        ]:
            w.blockSignals(True); w.clear(); w.blockSignals(False)

        if not sorted_m:
            return

        s = self.settings_mgr
        prec1 = (
            int(s.get("ui/label_precision", 9)) if is_time else int(s.get("ui/label_precision", 6))
        ) if s else (9 if is_time else 6)

        for i in range(2):
            if i < len(sorted_m):
                m_val = sorted_m[i].value()
                self.marker_panel.m_widgets[i]["v1"].blockSignals(True)
                self.marker_panel.m_widgets[i]["v2"].blockSignals(True)

                self.marker_panel.m_widgets[i]["v1"].setText(f"{m_val:.{prec1}f}")
                if is_time:
                    abs_s = int(round(m_val * self.rate)) + 1
                    self.marker_panel.m_widgets[i]["v2"].setText(f"{abs_s}")
                    inv_val = (1.0 / m_val) if abs(m_val) > 1e-12 else float("inf")
                    self.marker_panel.m_widgets[i]["v3"].setText(
                        "∞" if inv_val == float("inf") else f"{inv_val:.{prec1}f}"
                    )

                self.marker_panel.m_widgets[i]["v1"].blockSignals(False)
                self.marker_panel.m_widgets[i]["v2"].blockSignals(False)

        if len(sorted_m) == 2:
            v1, v2 = sorted_m[0].value(), sorted_m[1].value()
            self.marker_panel.delta_v1.blockSignals(True)
            self.marker_panel.center_v1.blockSignals(True)
            self.marker_panel.delta_v1.setText(f"{abs(v2-v1):.{prec1}f}")
            self.marker_panel.center_v1.setText(f"{(v1+v2)/2:.{prec1}f}")
            self.marker_panel.delta_v1.blockSignals(False)
            self.marker_panel.center_v1.blockSignals(False)

            if is_time:
                s1, s2 = int(round(v1 * self.rate)) + 1, int(round(v2 * self.rate)) + 1
                self.marker_panel.delta_v2.blockSignals(True)
                self.marker_panel.delta_v3.blockSignals(True)
                self.marker_panel.center_v2.blockSignals(True)
                self.marker_panel.center_v3.blockSignals(True)

                self.marker_panel.delta_v2.setText(f"{abs(s2-s1)+1}")
                dt = abs(v2 - v1)
                self.marker_panel.delta_v3.setText(f"{1.0/dt:.{prec1}f}" if dt > 1e-12 else "∞")

                cv = (v1 + v2) / 2
                self.marker_panel.center_v2.setText(f"{int(round(cv*self.rate))+1}")
                self.marker_panel.center_v3.setText(f"{1.0/cv:.{prec1}f}" if abs(cv) > 1e-12 else "∞")

                self.marker_panel.delta_v2.blockSignals(False)
                self.marker_panel.delta_v3.blockSignals(False)
                self.marker_panel.center_v2.blockSignals(False)
                self.marker_panel.center_v3.blockSignals(False)

        if self.interaction_mode in ["ZOOM", "MOVE", "STATS"]:
            pass
        elif not is_endless:
            m1_p, m2_p = (len(sorted_m) >= 1), (len(sorted_m) >= 2)
            self.marker_panel.set_locks_enabled(m1_p, m2_p)

        self.update_grid("TIME")
        self.update_grid("MAG")

    # ------------------------------------------------------------------
    # Theme & Styling
    # ------------------------------------------------------------------

    def refresh_theme(self):
        p = get_palette(self._get_theme_name())
        self.update_toolbar_style()
        self.refresh_plot_style()
        self.marker_panel.refresh_theme()
        self.update_button_tooltips()

        sb_style = get_scrollbar_stylesheet(p)
        self.x_scroll.setStyleSheet(sb_style)
        self.y_scroll.setStyleSheet(sb_style)

        self._render_current_subplot()

    def refresh_plot_style(self):
        p = get_palette(self._get_theme_name())
        self.plot_widget.setBackground(p.plot_bg)

        s = self.settings_mgr
        font = QFont()
        font.setPointSize(int(s.get("ui/axis_font_size", 10)) if s else 10)

        grid_enabled = bool(s.get("ui/grid_enabled", True)) if s else True
        grid_alpha = (int(s.get("ui/grid_alpha", 30)) if s else 30) / 100.0

        self.plot_item.getAxis("left").setTickFont(font)
        self.plot_item.getAxis("bottom").setTickFont(font)
        self.plot_widget.showGrid(x=grid_enabled, y=grid_enabled, alpha=grid_alpha)

        self.plot_item.getAxis("left").setPen(p.text_dim)
        self.plot_item.getAxis("bottom").setPen(p.text_dim)
        if hasattr(self, "view_box") and hasattr(self.view_box, "refresh_theme"):
            self.view_box.refresh_theme()

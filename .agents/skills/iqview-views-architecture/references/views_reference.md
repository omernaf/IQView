# IQView Views API Reference & Architecture Inventory

This document provides the exhaustive architectural and API reference for all visualization and analysis views in IQView.

---

## 1. 2D Spectrogram Engine

### `SpectrogramView`
- **Source**: [`iqview/ui/spectrogram_view.py`](file:///d:/Projects/IQView/iqview/ui/spectrogram_view.py)
- **Class**: `SpectrogramView(QWidget)`
- **Key Attributes**:
  - `self.plot_item`: `pyqtgraph.PlotItem` hosting the image.
  - `self.view_box`: [`CustomViewBox`](file:///d:/Projects/IQView/iqview/ui/widgets.py) managing mouse interactions.
  - `self.img_item`: `pyqtgraph.ImageItem` with OpenGL acceleration.
  - `self.level_region`: `LinearRegionItem` on the colorbar with draggable min/max bounds.
  - `self.colorbar_axis`: `ColorbarAxisItem` providing real-time $\text{dB/Hz}$ tick labels.
  - `self.is_waterfall`: `bool` indicating active orientation.
  - `self._applied_waterfall`: Tracks applied state to avoid unintentional axis flips during settings updates.
  - `self.full_t_range`, `self.full_f_range`: Full recording boundaries for zoom-out clamping.
- **Key Methods**:
  - `display_spectrogram(spectrogram_data, t_start, t_end, f_start, f_end)`: Binds 2D array to `img_item` with window-center coordinate offset.
  - `update_view_limits()`: Enforces hard boundary limits on zoom and pan.
  - `apply_waterfall_mode(enabled)`: Transposes X and Y axes between standard ($X=t, Y=f$) and waterfall ($X=f, Y=t$).

### `MultiRowSpectrogramView`
- **Source**: [`iqview/ui/multi_row_view.py`](file:///d:/Projects/IQView/iqview/ui/multi_row_view.py)
- **Class**: `MultiRowSpectrogramView(QWidget)`
- **Key Attributes**:
  - `self.num_rows`: Number of stacked rows ($N \ge 1$).
  - `self.samples_per_row`: Sample count per row.
  - `self.period`: Cycle period in samples.
  - `self.start_sample`: Alignment offset.
  - `self.views`: List of `pyqtgraph.PlotItem` row canvases.
- **Key Methods**:
  - `set_parameters(rows, samples_per_row, period, start_sample)`: Reconfigures layout and triggers row segmentation.
  - `sync_views()`: Binds all row viewports to identical frequency limits and relative time spans.

---

## 2. 1D Domain Subsystem

### `Base1DPlotView`
- **Source**: [`iqview/ui/base_1d/view.py`](file:///d:/Projects/IQView/iqview/ui/base_1d/view.py)
- **Class**: `Base1DPlotView(QWidget)`
- **Inherited By**: `TimeDomainView`, `FrequencyDomainView`.
- **Key Responsibilities**:
  - Manages primary markers ($M_1, M_2$) and endless markers list.
  - Marker locking state machine (`M1`, `M2`, `Delta`, `Center`).
  - Adaptive boundary clamping via `update_drag()`.
  - Cyclic shadow marker grids (`_do_update_grid` with 50 ms throttle).
  - Synchronized X and Y zoom scrollbars (`update_scrollbars`, `scroll_view`).
  - Zoom history stack (`zoom_history`) for multi-level `Ctrl+Z` undo.

### `TimeDomainView`
- **Source**: [`iqview/ui/time_domain/view.py`](file:///d:/Projects/IQView/iqview/ui/time_domain/view.py)
- **Class**: `TimeDomainView(Base1DPlotView)`
- **Trace Modes Supported**:
  - `magnitude [dB]`: $20 \log_{10}(|x[n]| + \epsilon)$
  - `Real`: $\text{Re}(x[n])$
  - `Imaginary`: $\text{Im}(x[n])$
  - `instant frequency`: Wrapped phase differentiation via Hilbert transform for real signals
  - `Phase`: $[-\pi, \pi]$
  - `Unwrapped phase`: Continuous phase
  - `magnitude`: Linear $|x[n]|$
  - `magnitude^2`: Linear power $|x[n]|^2$
  - `magnitude^2 [dB]`: $10 \log_{10}(|x[n]|^2)$
- **Key Methods**:
  - `update_plot()`: Invokes [`domain_transforms.compute_time_domain_trace()`](file:///d:/Projects/IQView/iqview/dsp/domain_transforms.py).
  - `update_statistics()`: Invokes [`domain_transforms.compute_region_statistics()`](file:///d:/Projects/IQView/iqview/dsp/domain_transforms.py).

### `FrequencyDomainView`
- **Source**: [`iqview/ui/frequency_domain/view.py`](file:///d:/Projects/IQView/iqview/ui/frequency_domain/view.py)
- **Class**: `FrequencyDomainView(Base1DPlotView)`
- **Trace Modes Supported**:
  - `power spectrum density (PSD)`: In true $\text{dB/Hz}$ via Welch or Periodogram.
  - `magnitude [dBFS]`: Full-scale decibels ($20 \log_{10}(|X[k]|/N)$).
- **Preprocessing Operators**:
  - `None (Normal)`, `2nd Power`, `4th Power`, `FM Demod`, `2nd Power FM`, `Delay & Multiply`.
- **Integrated Power**: Computes channel power $\sum S_{xx}(f) \cdot \Delta f$.

---

## 3. Specialized Modulation Views

### `EyeDiagramView`
- **Source**: [`iqview/ui/eye_diagram_dialog.py`](file:///d:/Projects/IQView/iqview/ui/eye_diagram_dialog.py)
- **Class**: `EyeDiagramView(QWidget)`
- **Key Attributes**:
  - `MAX_EYE_SAMPLES = 500_000`: Hard sample processing cap.
  - `self.slider_main`: $\pm 50\%$ range.
  - `self.slider_coarse`: $\pm 2\%$ range.
  - `self.slider_fine`: $\pm 0.1\%$ range.
  - `self.offset_slider`: Symbol strobe timing phase offset.
  - `self.is_baud_mode`: Toggle between SPS and Baud Rate (Hz).
  - `self.overview_curve`: Mini-overview waveform with draggable segment handles.

### `ConstellationView` (Scatter Plot)
- **Source**: [`iqview/ui/constellation_dialog.py`](file:///d:/Projects/IQView/iqview/ui/constellation_dialog.py)
- **Class**: `ConstellationView(QWidget)`
- **Key Attributes**:
  - `MAX_CONSTELLATION_SAMPLES = 500_000`: Hard processing cap.
  - `self.spin_downsample`: Integer downsampling factor $N \ge 1$.
  - `self.slider_offset`: Strobe instant ($0 \dots N-1$).
  - `self.slider_phase_coarse` ($\pm 180^\circ$) & `self.slider_phase_fine` ($\pm 10^\circ$).
  - `self.slider_cfo_coarse` ($\pm f_s/2$), `self.slider_cfo_med` ($\pm f_s/2000$), `self.slider_cfo_fine` ($\pm f_s/2,000,000$).
  - Overlays: Trajectory line tracing, point size control, unit circle, $I/Q$ crosshairs.

---

## 4. Window & Tab Lifecycle

### `ViewControllerMixin`
- **Source**: [`iqview/ui/main_window/view_controller.py`](file:///d:/Projects/IQView/iqview/ui/main_window/view_controller.py)
- **Key Methods**:
  - `open_time_domain_tab()`
  - `open_frequency_domain_tab()`
  - `open_eye_diagram_tab()`
  - `open_constellation_tab()`
  - `_confirm_large_segment(start_t, end_t, tab_name)`: Warns user when $>10,000,000$ samples are requested.

### `DetachedViewWindow`
- **Source**: [`iqview/ui/detached_window.py`](file:///d:/Projects/IQView/iqview/ui/detached_window.py)
- **Class**: `DetachedViewWindow(QMainWindow)`
- **Role**: Standalone window created when tabs are dragged vertically out of `QTabBar`. Includes "Dock Back" toolbar action.

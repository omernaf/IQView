---
name: iqview-views-architecture
description: >-
  ALWAYS load and read this skill before creating, modifying, or debugging any signal analysis
  view, tab, toolbar, marker panel, or window in IQView: 2D Spectrogram, Multi-Row Spectrogram,
  Base1DPlotView, Time Domain, Frequency Domain, Eye Diagram, Constellation/Scatter Plot,
  Plugin Plot tabs, MarkerPanel, and Detached Windows.
---

# IQView Views Architecture Guide

IQView features a multi-domain visualization architecture designed to analyze RF captures across time, frequency, modulation, and symbol domains.

This skill explains the anatomy, data flow, extraction mechanics, coordinate systems, and tab lifecycle for every view in the application.

For complete class signatures, attributes, and method tables, consult:
- [Views API Reference](./references/views_reference.md)

---

## 1. View Architecture Overview

```
                                 ┌─────────────────────────────────┐
                                 │       SpectrogramWindow         │
                                 │   (Main Qt Window Container)    │
                                 └───────────────┬─────────────────┘
                                                 │
          ┌──────────────────────────────────────┼──────────────────────────────────────┐
          │                                      │                                      │
          ▼                                      ▼                                      ▼
┌──────────────────┐                   ┌──────────────────┐                   ┌──────────────────┐
│  SpectrogramView │                   │ MultiRowSpectro- │                   │  Tab Container   │
│  (Primary 2D)    │                   │ gramView         │                   │  (Analysis Tabs) │
└─────────┬────────┘                   └──────────────────┘                   └─────────┬────────┘
          │                                                                             │
          │ [User marks time/freq region or triggers action]                            │
          └───────────────────────────────┬─────────────────────────────────────────────┘
                                          │ extract_iq_segment()
                                          ▼
      ┌──────────────────┬─────────────────┼──────────────────┬──────────────────┐
      ▼                  ▼                 ▼                  ▼                  ▼
┌─────────────┐    ┌─────────────┐   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ TimeDomain  │    │ Frequency-  │   │ EyeDiagram  │    │ Constellat- │    │ PluginPlot  │
│ View (1D)   │    │ DomainView  │   │ View        │    │ ionView     │    │ View (1D)   │
└─────────────┘    └─────────────┘   └─────────────┘    └─────────────┘    └─────────────┘
```

---

## 2. The Views in Detail

### 2.1 Primary Spectrogram View ([`SpectrogramView`](file:///d:/Projects/IQView/iqview/ui/spectrogram_view.py))
- **File**: `iqview/ui/spectrogram_view.py`
- **Role**: Primary 2D time-frequency visualization powered by PyQt6, pyqtgraph, and PyOpenGL.
- **Rendering Modes**:
  - **Lazy Mode (`ViewportAwareReader`)**: Renders only the visible viewport slice at $4 \times \text{canvas\_pixels}$ width. Dynamically recalculates as the user zooms or pans.
  - **Full Mode (`FileReaderThread`)**: Computes an upfront full-file spectrogram cache capped at $\approx 20,000$ rows. When zoomed in past 50%, automatically switches to high-resolution viewport calculation to avoid bitmap pixelation.
- **Orientation Modes**:
  - **Standard**: $X = \text{Time (s)}$, $Y = \text{Frequency (Hz)}$.
  - **Waterfall**: $X = \text{Frequency (Hz)}$, $Y = \text{Time (s)}$ (with $t=0$ at the top and increasing downward).
  - *Gotcha*: When settings change, track `_applied_waterfall` explicitly to avoid accidental axis swaps.
- **Level Region & Colorbar**:
  - Includes draggable min/max level lines with an integrated `ColorbarAxisItem` showing power spectral density in $\text{dB/Hz}$.
  - Shifting normalization (`norm_db`) or sample rate ($f_s$) dynamically shifts the level lines by $\Delta \text{dB}$.
- **Navigation**:
  - `Hold Ctrl` + Left-click drag: Box zoom.
  - `Hold Space` + Left-click drag or Middle-click drag: Pan.
  - Right-click drag: Interactive X/Y scaling.
  - `Ctrl+Z`: Undo zoom/pan step.

---

### 2.2 Multi-Row Stacked Spectrogram ([`MultiRowSpectrogramView`](file:///d:/Projects/IQView/iqview/ui/multi_row_view.py))
- **File**: `iqview/ui/multi_row_view.py`
- **Role**: Visualizes repetitive or pulsed signals by unrolling the time axis across $N$ vertically stacked, synchronized viewports.
- **Key Parameters**:
  - `rows`: Number of stacked spectrogram rows ($N \ge 1$).
  - `samples_per_row`: Number of samples displayed per row.
  - `period`: Cycle period in samples (sample-indexed; e.g. 20,000 samples for a 2 ms pulse at 10 Msps).
  - `start_sample`: Offset to shift the column horizontally.
- **Synchronization**:
  - All rows share identical frequency limits and relative time spans.
  - Zooming or panning any single row instantly synchronizes all rows.
  - Overlays and markers automatically wrap and render across corresponding rows.

---

### 2.3 1D Domain Views & Shared Architecture ([`Base1DPlotView`](file:///d:/Projects/IQView/iqview/ui/base_1d/view.py))
Both Time Domain and Frequency Domain views share a unified architecture under `iqview/ui/base_1d/`:
- [`Base1DPlotView`](file:///d:/Projects/IQView/iqview/ui/base_1d/view.py): Unifies mouse hit-testing (minimum Euclidean distance), marker dragging, Delta/Center locks, shadow continuation grids, endless markers, zoom history, and synchronized X/Y zoom scrollbars.
- [`Base1DMarkerPanel`](file:///d:/Projects/IQView/iqview/ui/base_1d/marker_panel.py): Standardizes toolbar buttons (`[T]`, `[F]`, `[Hold Ctrl]`), fixed marker tables, lock buttons (`1`, `2`, `D`, `C`), and stats definition/results tables.
- [`RegionStatsWidget`](file:///d:/Projects/IQView/iqview/ui/base_1d/region_stats_widget.py): Definition bounds and statistical metrics (Mean, Median, Min, Max, 10th %, 90th %, 90-10 Diff, Integrated Power).
- [`EndlessMarkerListWidget`](file:///d:/Projects/IQView/iqview/ui/base_1d/endless_marker_list.py): Scrollable table for arbitrary numbers of secondary markers.

#### Time Domain View ([`TimeDomainView`](file:///d:/Projects/IQView/iqview/ui/time_domain/view.py))
- **Data Source**: Opened on a selected time slice $[t_{\text{start}}, t_{\text{end}}]$ via `open_time_domain_tab()`.
- **Plot Modes**:
  1. `magnitude [dB]`: $20 \log_{10}(|x[n]| + \epsilon)$
  2. `Real`: $\text{Re}(x[n])$
  3. `Imaginary`: $\text{Im}(x[n])$
  4. `instant frequency`: $f_{\text{inst}}[n] = \frac{\Delta \phi[n]}{2\pi} \cdot f_s$
  5. `Phase`: $\arg(x[n]) \in [-\pi, \pi]$
  6. `Unwrapped phase`: Continuous phase unwrapping
  7. `magnitude`, `magnitude^2`, `magnitude^2 [dB]`
- **Real Signal Handling**: If samples are real-valued, automatically converts to an analytic signal via Hilbert transform + high-pass filter before computing instantaneous frequency.
- **Visual Indicators**: Extrema points (red circle for Max, green triangle for Min) and dotted horizontal lines for 10th and 90th percentiles.

#### Frequency Domain View ([`FrequencyDomainView`](file:///d:/Projects/IQView/iqview/ui/frequency_domain/view.py))
- **Data Source**: Opened via `open_frequency_domain_tab()`.
- **Plot Modes**:
  1. `power spectrum density (PSD)`: Scaled in $\text{dB/Hz}$ via Welch or Periodogram method.
  2. `magnitude [dBFS]`: $20 \log_{10}(|X[k]| / N)$.
- **Preprocessing Operators**:
  - `None (Normal)`
  - `2nd Power` ($x[n]^2$): Isolates symbol-rate harmonics and residual carrier spikes.
  - `4th Power` ($x[n]^4$): Catches carrier frequency offset (CFO) in QPSK signals.
  - `FM Demod`: Computes instantaneous frequency prior to spectral analysis.
  - `2nd Power FM`: Squaring after FM demodulation.
  - `Delay & Multiply` ($x[n] \cdot x^*[n-1]$): Exposes discrete baud rate lines.
- **Integrated Power**: Computes channel power $\sum S_{xx}(f) \cdot \Delta f$ within the selected frequency region.
- **Live Filtering Overlays**: Supports interactive BPF (`[`) and BSF (`]`) directly on the spectrum curve.

---

### 2.4 Eye Diagram View ([`EyeDiagramView`](file:///d:/Projects/IQView/iqview/ui/eye_diagram_dialog.py))
- **File**: `iqview/ui/eye_diagram_dialog.py`
- **Role**: Symbol timing, jitter, and inter-symbol interference (ISI) visualization.
- **Signal Modes**: Real, Imaginary, Phase, Inst. Freq, Magnitude.
- **Core Algorithms**:
  - Fractional $N_{\text{sps}}$ support: Interpolates traces so non-integer samples-per-symbol values render cleanly.
  - Three-tier sliders: Main ($\pm 50\%$), Coarse ($\pm 2\%$), Fine ($\pm 0.1\%$).
  - Dual Mode Cycling: Toggle between **Samples-Per-Symbol (SPS)** and **Baud Rate (Hz)**.
  - Timing offset slider: Shifts the eye horizontally to center the symbol decision point.
- **Safety**: Hard sample cap `MAX_EYE_SAMPLES = 500_000` to maintain responsive 60 FPS slider dragging.
- **Mini Overview**: Interactive waveform overview at the bottom with draggable handles for isolating specific bursts.

---

### 2.5 Scatter Plot / Constellation View ([`ConstellationView`](file:///d:/Projects/IQView/iqview/ui/constellation_dialog.py))
- **File**: `iqview/ui/constellation_dialog.py`
- **Role**: Visualizes the complex $I/Q$ constellation plane and facilitates carrier demodulation tuning.
- **Core Tuning Features**:
  1. **Integer Downsampling ($N$)**: Downsamples by factor $N$ (e.g. 8 for 8 SPS).
  2. **Sub-Symbol Offset Slider ($0 \dots N-1$)**: Scans the optimal symbol strobe instant.
  3. **Carrier Phase Sliders**: Coarse ($\pm 180^\circ$) and Fine ($\pm 10^\circ$) rotation:
     $$x_{\text{rot}}[n] = x[n] \cdot e^{j \phi_{\text{rad}}}$$
  4. **3-Tier Frequency Offset (CFO) Despinning**:
     - Coarse: $\pm f_s / 2$
     - Medium: $\pm f_s / 2000$
     - Fine: $\pm f_s / 2,000,000$
     $$x_{\text{despun}}[n] = x[n] \cdot e^{-j 2\pi f_{\text{CFO}} t[n]}$$
  5. **Visual Aids**: Trajectory line tracing, point size adjustment, unit circle overlay, and $I/Q$ axis crosshairs.

---

### 2.6 Plugin Plot View ([`PluginPlotView`](file:///d:/Projects/IQView/iqview/ui/plugin_plot_view.py))
- **File**: `iqview/ui/plugin_plot_view.py`
- **Role**: Reusable 1D multi-trace plot tab spawned by plugins via `result.add_plot_tab()`.
- **Features**:
  - Arbitrary line traces with custom colors, labels, and styles.
  - Shaded vertical state regions (`X-Region`) for marking protocol states, preamble zones, or payload sections.
  - Interactive markers and region statistics.

---

## 3. Tab Lifecycle & Window Management

Controlled via [`ViewControllerMixin`](file:///d:/Projects/IQView/iqview/ui/main_window/view_controller.py) and [`DetachedViewWindow`](file:///d:/Projects/IQView/iqview/ui/detached_window.py):

1. **Tab Creation Entry Points**:
   ```python
   # In ViewControllerMixin:
   def open_time_domain_tab(self): ...
   def open_frequency_domain_tab(self): ...
   def open_eye_diagram_tab(self): ...
   def open_constellation_tab(self): ...
   ```
2. **Segment Extraction**:
   Uses `extract_iq_segment(t_start, t_end)` which automatically:
   - Clamps to recording boundaries.
   - Applies active normalization `norm_db`.
   - Reads directly from file or cache.
3. **Large Segment Safety**:
   - If marked time range contains $>10,000,000$ samples, `_confirm_large_segment()` prompts the user with a confirmation dialog to prevent accidental UI freezes.
4. **Chrome-Like Tab Undocking**:
   - Dragging any tab vertically out of `QTabBar` spawns a standalone [`DetachedViewWindow`](file:///d:/Projects/IQView/iqview/ui/detached_window.py).
   - Detached windows preserve all interactions, markers, and mini-overview controls.
   - Clicking the **"Dock Back"** toolbar button returns the view to the main window's tab bar.
   - The primary **Spectrogram** tab remains pinned at index 0 and cannot be undocked or reordered.

---

## 4. Verification & Testing Checklist

When adding or modifying an analysis view:
1. **Trace Aesthetic**: Verify 1D traces use MATLAB blue (`#0072BD`, width `0.5`).
2. **Keybind Tooltips**: Ensure all toolbar buttons declare bracketed shortcuts (`[T]`, `[F1]`, etc.).
3. **Detached Behavior**: Test dragging the tab to a second monitor and docking back.
4. **Zoom Sync**: Verify right-click scaling and middle-click panning respect view limits and `Ctrl+Z` undoes zoom history.
5. **Sample Cap**: Verify large segment warnings appear when requesting $>10\text{M}$ samples.

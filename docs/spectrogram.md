# 🌌 Spectrogram View

The Spectrogram View is the primary analysis interface in IQView, providing a high-performance, GPU-accelerated visualization of signal intensity across both time and frequency.

---

## 📐 Mathematical Principles

The spectrogram is a visual representation of the **Short-Time Fourier Transform (STFT)**. It breaks down a long signal into shorter segments and computes the Fourier transform for each.

### 1. Discrete STFT
For a discrete signal $x[n]$, the STFT at time index $m$ and frequency $k$ is:

$$X(m, k) = \sum_{n=0}^{N-1} x[n + mH] \cdot w[n] e^{-j \frac{2\pi}{N} kn}$$

Where:
- $N$ is the **FFT Size** (number of frequency bins).
- $w[n]$ is the **Window Function**.
- $H$ is the **Hop Size**, determined by the overlap percentage ($H = N \times (1 - \text{Overlap}/100)$).

### 2. Windowing Functions
Windowing reduces "spectral leakage" caused by the finite length of segments. IQView supports:
- **Hamming**: Balanced resolution and dynamic range (default).
- **Hann**: Smoother roll-off, lower side-lobes.
- **Blackman**: Very low side-lobes but wider main-lobe (lower frequency resolution).
- **Rectangular**: Highest frequency resolution but severe leakage.

### 3. Logarithmic Scaling (dB)
To visualize signals with massive power differences (e.g., a strong transmitter vs. background noise), IQView maps linear magnitude to decibels:

$$P_{\text{dB}}(m, k) = 20 \log_{10}\left( \frac{|X(m, k)|}{N} + \epsilon \right)$$

*Normalizing by $N$ ensures that the peak level of a full-scale sinusoid is 0 dBFS. $\epsilon$ is a small constant ($10^{-10}$) to prevent $\log(0)$.*

---

## ⚡ High-Performance Rendering & Filtering

To maintain fluid UI interactions on gigabyte-sized files, IQView employs two key performance optimizations:

### 1. Lazy (On-Demand) Rendering Engine
Instead of processing an entire capture into RAM on startup (which causes significant delays and memory crashes), IQView utilizes a viewport-aware background worker (`ViewportAwareReader`):
- It reads only the time segment $[t_{\text{start}}, t_{\text{end}}]$ currently visible in the UI viewport.
- It dynamically calculates the necessary step size to compute exactly $4 \times \text{pixel\_width}$ FFT rows, where `pixel_width` is the horizontal width of the UI canvas in pixels.
- This bounds the computational complexity to $O(W \cdot N \log N)$ where $W \propto \text{pixel\_width}$, making view adjustments nearly instant regardless of file size.
- Zooming in triggers an automatic high-resolution re-render, displaying fine signal details seamlessly.

### 2. Zero-Cost Frequency-Domain BPF/BSF Mask
When a filter is configured for the spectrogram display, instead of applying a computationally heavy time-domain convolution (filter taps) to millions of samples, IQView designs the filter and evaluates its frequency response:
1. The complex response $H(f)$ of the desired filter (Elliptic, Butterworth, etc.) is pre-computed at each FFT bin frequency $f_k$.
2. The absolute response magnitude $|H(f_k)|$ is multiplied directly with each FFT bin of the spectrogram row:
   $$X_{\text{filt}}(m, k) = X(m, k) \cdot |H(f_k)|$$
3. For Band-Stop filtering (BSF), the mask is inverted:
   $$X_{\text{filt}}(m, k) = X(m, k) \cdot (1 - |H(f_k)|)$$
This results in instantaneous filtering without time-domain overhead.

---

## 🎨 Visualization Controls

### 1. Spectrum Envelope (Side Panel)
The right-hand side panel shows the **Min/Max Envelope** of the currently visible spectrogram area.
- **Blue Curve**: Maximum power across time for each frequency bin.
- **Gray Curve**: Minimum power (usually representing the noise floor).

### 2. Level Clipping (Gain Control)
The semi-transparent blue region on the envelope plot controls the **Colormap Mapping**:
- **Top Bound**: Maps to the "hottest" color in the colormap (e.g., White/Yellow). Signals above this level will clip visually.
- **Bottom Bound**: Maps to the "coldest" color (e.g., Dark Blue/Purple). Signals below this are treated as background noise.

### 3. Colormaps
IQView uses perceptually uniform colormaps (like **Turbo** or **Viridis**) to ensure that visual intensity accurately reflects mathematical power. You can reverse the colormap in settings for a "waterfall" print-friendly look.

---

## 📐 Region Overlays & Marker Tools

IQView offers advanced markers and shape overlays for documenting and measuring signals:

### 1. Interactive Overlays
Users can place overlay shapes directly on the spectrogram:
- **X-Region (Time Band)**: Spans the entire frequency axis between two time points.
- **Y-Region (Frequency Band)**: Spans the entire time axis between two frequency points.
- **Rectangle**: Spans specific time and frequency bounds.
- **Ellipse**: Circular or elliptical shapes centered at specific coordinate values.
- **Polygon**: A custom shape defined by multiple coordinate points.

### 2. UI Actions & Manual Creation
- **Shape Selector**: Choose the active shape from the dropdown menu in the Marker Panel.
- **Add / Drag Placement**: A single click places a default-sized region. Clicking and dragging draws custom sizes.
- **Manual Add Button (`+ Manual Add`)**: Allows manual coordinate input for placing precise shapes.
- **Vertex Manipulation**: Polygon overlays render independent resize handles at each vertex, allowing users to stretch and modify complex polygons interactively.
- **Locked Delta / Center**: When adjusting boundaries, users can lock the delta (retaining width) or lock the center (expanding/shrinking symmetrically).

---

## 🖱️ Interactive Navigation

- **Box Zoom**: Hold **Ctrl** and drag a rectangle with the left mouse button to zoom into a specific time-frequency region.
- **Panning**: Use the horizontal and vertical scrollbars that appear when zoomed.
- **Axis-Specific Unzoom**: Right-click the spectrogram view to open the context menu. You can choose to unzoom the time axis (`Unzoom Time`) or frequency axis (`Unzoom Frequency`) independently, or select `Reset View` to zoom out completely.
- **Middle-Click Tab**: Quickly close current analysis tabs from the top bar.

---

## 📤 Exporting

Right-click the spectrogram to access export options:
- **Capture Raw Image**: Saves the spectrogram pixels exactly as rendered, without axes or markers.
- **Capture Full Plot**: Uses a high-quality renderer to export the entire plot area, including frequency/time labels and active markers.

---

## 🥞 Multi-Row Stacked Spectrogram View

IQView features a **Multi-Row Stacked Spectrogram** mode designed for analyzing periodic signals, bursts, and multi-segment captures across vertically stacked viewports.

### 1. Configuration & Parameters
- **Rows Count ($N$)**: Sets the number of vertically stacked spectrogram rows.
- **Samples per Row**: Length of the IQ segment displayed in each individual row.
- **Row Period**: Sample interval between the start of consecutive rows.
- **Zoom Level Preservation**: Transitioning from 1-Row to Multi-Row mode maintains the exact start sample and samples per row (`spr`) zoom window, adjusting only the period. Changing between multi-row counts preserves start sample, `spr`, and period.

### 2. Synchronized Real-Time Navigation
- **Single Source of Truth Axis Sync**: Mouse dragging (panning) updates all row plots' bottom time axes (ticks and seconds labels) and left frequency axes in 1:1 real-time.
- **Synchronized Relative Zoom**: Zooming in or out on any single row automatically updates all other rows' relative time and absolute frequency axes to maintain identical zoom proportions.

### 3. Integrated Marker, Filter & Overlay System
- **Markers & Grid Lines**: Time and frequency markers, as well as shadow grid lines, are rendered across all stacked rows. Double-clicking a marker button clears markers of that type in both 1-row and multi-row modes.
- **BPF / BSF Passband Region**: Placement of 1st and 2nd filter bound markers renders an orange preview line and a highlighted semi-transparent bandpass/bandstop region across all stacked rows. Active filter DSP settings are preserved bi-directionally when toggling between 1-row and multi-row modes.
- **Shape Overlays**: All overlay shapes (`RECT`, `POLYGON`, `ELLIPSE`, `LINE`, `HLINE`, `X_REGION`, `Y_REGION`) and their display tags are rendered on rows covering their time/frequency span.
- **Colormap & Level Controls**: Real-time intensity level clipping and colormap preset adjustments from the side panel instantly update all stacked row images.

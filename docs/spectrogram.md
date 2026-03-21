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
- **Hamming**: Balanced resolution and dynamic range.
- **Hann**: Smoother roll-off, lower side-lobes.
- **Blackman**: Very low side-lobes but wider main-lobe (lower frequency resolution).
- **Rectangular**: Highest frequency resolution but severe leakage (default).

### 3. Logarithmic Scaling (dB)
To visualize signals with massive power differences (e.g., a strong transmitter vs. background noise), IQView maps linear magnitude to decibels:

$$P_{\text{dB}}(m, k) = 20 \log_{10}\left( \frac{|X(m, k)|}{N} + \epsilon \right)$$

*Normalizing by $N$ ensures that the peak level of a full-scale sinusoid is 0 dBFS.*

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

## 🖱️ Interactive Navigation

- **Box Zoom**: Hold **Ctrl** and drag a rectangle with the left mouse button to zoom into a specific time-frequency region.
- **Panning**: Use the horizontal and vertical scrollbars that appear when zoomed.
- **Reset View**: Double-click (or use the button in the side panel) to fit the entire capture to the window.
- **Middle-Click Tab**: Quickly close current analysis tabs from the top bar.

---

## 📤 Exporting
Right-click the spectrogram to access export options:
- **Capture Raw Image**: Saves the spectrogram pixels exactly as rendered, without axes or markers.
- **Capture Full Plot**: Uses a high-quality renderer to export the entire plot area, including frequency/time labels and active markers.

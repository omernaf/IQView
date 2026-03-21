# 📶 Frequency Domain View

The Frequency Domain view in IQView provides a detailed spectral estimate of a selected signal segment using high-resolution FFT and Power Spectral Density (PSD) algorithms.

---

## 📐 Mathematical Principles

Frequency analysis involves transforming time-series samples $x[n]$ into the frequency domain $X[k]$.

### 1. Discrete Fourier Transform (DFT)
IQView uses the **Fast Fourier Transform (FFT)** for efficient computation:

$$X[k] = \sum_{n=0}^{N-1} x[n] \cdot w[n] e^{-j \frac{2\pi}{N} kn}$$

Where $N$ is the number of samples in the segment, and $w[n]$ is a rectangular window (default).

### 2. Power Spectral Density (PSD)
PSD represents the power of a signal as a function of frequency. IQView supports:
- **Welch's Method**: Improves the signal-to-noise ratio (SNR) by dividing the signal into overlapping segments, computing their periodograms, and averaging them:
  $$P_{\text{Welch}}(f) = \frac{1}{K} \sum_{i=0}^{K-1} P_i(f)$$
  *Reduces noise floor variance at the cost of frequency resolution.*
- **Periodogram**: A single FFT-based estimate using the entire segment:
  $$P(f) = \frac{1}{N f_s} |X(f)|^2$$

---

## 📈 Plot Modes

| Mode | Formula / Description |
| :--- | :--- |
| **Magnitude [dB]**| $20 \log_{10}(|X[k]| + \epsilon)$ |
| **Magnitude²** | $|X[k]|^2$ (Linear Power) |
| **PSD [dB]** | $10 \log_{10}(P_{\text{Welch}}(f) + \epsilon)$ |
| **Real / Imag** | $Re\{X[k]\}$ and $Im\{X[k]\}$ components. |
| **Phase** | $\text{atan2}(Im\{X[k]\}, Re\{X[k]\})$ (Spectral phase). |

---

## 🎯 Marker & Analysis Tools

### 1. Interactive Markers
- **Frequency Markers (F)**: Measure center frequency ($f_c$) and bandwidth ($\Delta f$).
- **Magnitude Markers (M)**: Measure absolute power levels (dBFS or linear) at specific bins.
- **Endless Markers (Shift+F/M)**: Rapid placement of multiple spectral markers.

### 2. Statistical Analysis (Selection Box)
Dragging the **STATS** region across the spectrum calculates:
- **Max / Min**: Peak power and spectral noise floor in the selection.
- **Integrated Power**: Total power within the selected bandwidth:
  $$\text{Total Power} = \sum_{k \in \{f_1, f_2\}} |X[k]|^2$$
  *Useful for measuring Channel Power or SNR.*
- **Mean PSD**: Averaged power density across the selected bins.

---

## ⚙️ View Controls
- **Fit to Markers**: Automatically zoom both axes to perfectly encompass the region between $M_1$ and $M_2$.
- **Spectral Mode**: Toggle between static segment analysis and dynamic "live" updates if a file is re-processed.
- **Auto-Range**: Recalculate Y-axis bounds based on the current spectral peaks.

# 📶 Frequency Domain View

The Frequency Domain view in IQView provides a detailed spectral estimate of a selected signal segment using high-resolution Fast Fourier Transform (FFT) and Power Spectral Density (PSD) algorithms.

---

## 📐 Mathematical Principles

Frequency analysis involves transforming time-series samples $x[n]$ into the frequency domain $X[k]$.

### 1. Discrete Fourier Transform (DFT)
IQView uses the **Fast Fourier Transform (FFT)** for efficient computation:

$$X[k] = \sum_{n=0}^{N-1} x[n] \cdot w[n] e^{-j \frac{2\pi}{N} kn}$$

Where $N$ is the number of samples in the segment, and $w[n]$ is the window function.

### 2. Power Spectral Density (PSD)
PSD represents signal power distribution per unit frequency (Hz). IQView supports:
*   **Welch's Method**: Divides the signal into overlapping segments, applies the window and scaling factors to each segment, computes their periodograms, and averages the power spectra:
    $$P_{\text{Welch}}(f) = \frac{1}{K} \sum_{i=0}^{K-1} P_i(f)$$
    *Welch's method reduces the noise floor variance (spectral ripple) at the cost of frequency resolution, making it ideal for checking weak signals.*
*   **Periodogram**: A single FFT-based estimate using the entire signal segment:
    $$P(f) = \frac{1}{N f_s} |X(f)|^2$$
    *Provides maximum frequency resolution but higher noise variance.*

### 3. Window Scaling & Power Recovery
Applying a window function $w[n]$ (e.g. Hamming, Hann) attenuates signal power at the segment edges. To recover the correct signal power and density, IQView scales the outputs using:
*   **Coherent Gain Constraint (CGC)**: Used for preserving peak sinusoidal amplitudes:
    $$S_{\text{CGC}} = \frac{1}{\sum_{n=0}^{N-1} w[n]}$$
*   **Equivalent Noise Bandwidth (ENBW)**: Used for preserving total noise power density:
    $$S_{\text{ENBW}} = \frac{1}{f_s \sum_{n=0}^{N-1} w[n]^2}$$

---

## 📈 Plot Modes

| Mode | Formula / Description |
| :--- | :--- |
| **Magnitude [dB]** | $20 \log_{10}(|X[k]| + \epsilon)$ |
| **Magnitude²** | $|X[k]|^2$ (Linear Power) |
| **PSD [dB]** | $10 \log_{10}(P(f) + \epsilon)$ |
| **Real / Imag** | $Re\{X[k]\}$ and $Im\{X[k]\}$ components. |
| **Phase** | $\text{atan2}(Im\{X[k]\}, Re\{X[k]\})$ (Spectral phase in radians). |

---

## 🛠️ Filter Overlays & Zero-Phase Filtering

Users can interactively design and apply Band-Pass (BPF) and Band-Stop (BSF) filters directly from the Frequency Domain view:

### 1. Interactive Filter Overlay
*   Selecting BPF or BSF mode displays a draggable linear frequency region ($[f_{\text{min}}, f_{\text{max}}]$) overlaying the PSD plot.
*   Dragging the boundaries immediately updates the designed filter specifications.

### 2. Shift-to-Baseband Zero-Phase DSP Approach
For time-domain filtering of selected bands, IQView uses a multi-step DSP pipeline that avoids group delay and phase distortion:
1.  **Shift to DC**: The signal is shifted in frequency so that the center of the target band ($f_{\text{center}} = (f_{\text{min}} + f_{\text{max}})/2$) is moved to $0\text{ Hz}$ (DC):
    $$x_{\text{shifted}}[n] = x[n] \cdot e^{-j 2\pi f_{\text{center}} n / f_s}$$
2.  **Zero-Phase Low-Pass Filter**: A standard low-pass filter (Butterworth, Chebyshev, Elliptic, Bessel, or FIR) is designed with a cutoff corresponding to the half-bandwidth. The filter is applied in **zero-phase** mode using `sosfiltfilt` (for IIR) or `filtfilt` (for FIR):
    - The signal is filtered forward.
    - The filtered sequence is reversed.
    - The reversed sequence is filtered again.
    - The result is reversed back.
    *This doubles the filter order and exactly cancels all phase shifts and group delays.*
3.  **Shift Back**: The filtered baseband signal is shifted back to the original band:
    $$y_{\text{bpf}}[n] = y_{\text{lpf}}[n] \cdot e^{j 2\pi f_{\text{center}} n / f_s}$$
4.  **Band-Stop Subtraction**: In BSF mode, because the phase alignment of $y_{\text{bpf}}[n]$ perfectly matches the input $x[n]$, the stopband is cleanly canceled by simple subtraction:
    $$y_{\text{bsf}}[n] = x[n] - y_{\text{bpf}}[n]$$

---

## 🎯 Marker & Analysis Tools

### 1. Interactive Markers
*   **Frequency Markers (F)**: Measure center frequency ($f_c$) and bandwidth ($\Delta f$).
*   **Magnitude Markers (M)**: Measure absolute power levels (dBFS or linear) at specific bins.
*   **Endless Markers (Shift+F / Shift+M)**: Place multiple frequency or magnitude markers interactively.

### 2. Statistical Analysis & Channel Power
Dragging the **STATS** region across the spectrum calculates:
*   **Max / Min**: Peak power and spectral noise floor in the selected band.
*   **Mean PSD**: Averaged power density across the selected bins.
*   **Integrated Power (Channel Power)**: The true total physical power contained within the selected bandwidth $[f_1, f_2]$:
    $$\text{Total Power} = \sum_{k \in \{f_1, f_2\}} P(f_k) \Delta f$$
    Where $P(f_k)$ is the linear power density at bin $k$, and $\Delta f = f_s / N_{\text{FFT}}$ is the bin resolution bandwidth. For dB plots, this is converted via $10 \log_{10}(\text{Total Power})$ to represent power in dB relative to full scale.

---

## ⚙️ View Controls

*   **Fit to Markers**: Automatically zoom both axes to perfectly encompass the region between $M_1$ and $M_2$.
*   **Spectral Mode**: Toggle between static segment analysis and dynamic "live" updates if a file is re-processed.
*   **Auto-Range**: Recalculate Y-axis bounds based on the current spectral peaks.

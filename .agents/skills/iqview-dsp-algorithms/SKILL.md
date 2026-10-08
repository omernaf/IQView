---
name: iqview-dsp-algorithms
description: >-
  Digital Signal Processing (DSP) algorithms, spectral analysis, zero-phase filtering,
  PSD normalization, and domain transformations in IQView. Use when modifying or adding
  DSP routines, filters, decibel calculations, or modulation math.
---

# IQView DSP Algorithms & Mathematical Foundations

This skill details the signal processing mathematics, spectral representations, filtering pipelines, and numerical safeguards implemented in IQView.

For deep mathematical derivations and automated verification:
- [DSP Mathematics & Formulations Reference](./references/dsp_mathematics.md)
- Helper Script: `python .agents/skills/iqview-dsp-algorithms/scripts/verify_dsp_invariants.py`

---

## 1. Decoupled DSP Architecture

IQView strictly decouples signal processing math from the GUI:
- [`iqview/dsp/dsp.py`](file:///d:/Projects/IQView/iqview/dsp/dsp.py): Core STFT preprocessing, FFT postprocessing, filter design (`design_filter`), and complex filter application (`apply_filter`).
- [`iqview/dsp/domain_transforms.py`](file:///d:/Projects/IQView/iqview/dsp/domain_transforms.py): Pure NumPy/SciPy domain routines (`compute_instantaneous_frequency`, `compute_time_domain_trace`, `apply_signal_operator`, `compute_frequency_domain_fft`, `compute_region_statistics`). Must have **zero dependencies** on PyQt6 or GUI widgets.
- [`iqview/dsp/utils.py`](file:///d:/Projects/IQView/iqview/dsp/utils.py): Multithreaded readers (`FileReaderThread`, `ViewportAwareReader`, `MultiRowProcessor`).

---

## 2. Zero-Phase Filtering Mandate

### 2.1 The Problem with Causal Filters
Standard causal filtering (`scipy.signal.sosfilt` or `lfilter`) introduces non-linear phase distortion and group delay. If applied to RF signals, band-stop filtering cannot be computed by subtracting the band-pass result, because phase differences leave heavy energy residuals.

### 2.2 Zero-Phase Implementation
All time-domain filtering must use forward-backward filtering:
```python
from scipy import signal

# For IIR filters (SOS format):
filtered_data = signal.sosfiltfilt(filter_data, shifted_data)

# For FIR filters:
filtered_data = signal.filtfilt(filter_data, [1.0], shifted_data)
```
**Benefits**:
1. Zero net group delay: Output aligns perfectly with input sample-by-sample.
2. Exact band cancellation: $\text{BSF} = \text{Original} - \text{BPF}$ is mathematically exact.

### 2.3 Fast Frequency-Domain Masking (Main Spectrogram)
For the 2D spectrogram display, time-domain convolution across millions of samples is replaced with pre-evaluating the complex frequency response $H(f_k)$ via `sosfreqz`:
$$X_{\text{filt}}[k] = X[k] \cdot |H(f_k)|$$
$$\text{For BSF: } X_{\text{filt}}[k] = X[k] \cdot (1 - |H(f_k)|)$$
This achieves instantaneous filtering with realistic roll-offs without convolving raw samples.

---

## 3. Spectral Normalization & Units

### 3.1 True Power Spectral Density (PSD in dB/Hz)
To make spectral intensities invariant to window length, window type, and FFT size, normalize raw FFT magnitudes by the window energy and sample rate:
$$\text{PSD}_{\text{dB/Hz}}[k] = 20 \log_{10}(|X[k]|) - 10 \log_{10}\left(f_s \sum_{n=0}^{N-1} w^2[n]\right)$$
Implemented in [`compute_psd_norm_db()`](file:///d:/Projects/IQView/iqview/dsp/dsp.py#L14-L22).

### 3.2 Full-Scale Decibels (dBFS)
In the Frequency Domain view, magnitude spectra are standardized to full-scale decibels:
$$\text{Level}_{\text{dBFS}} = 20 \log_{10}\left(\frac{|X[k]|}{N} + \epsilon\right)$$
A full-scale complex sinusoid with peak amplitude $1.0$ resolves to exactly $0\text{ dBFS}$.

### 3.3 Normalization Factor (`norm_db`)
To compensate for external hardware gains (LNAs, receiver AGCs) or calibrate samples to absolute RF power (e.g. dBm):
$$\text{norm\_factor} = 10^{-\text{norm\_db} / 20}$$
$$x_{\text{calibrated}}[n] = x[n] \cdot \text{norm\_factor}$$
Power drops by $10^{-\text{norm\_db}/10}$. Changing `norm_db` automatically updates colorbar ranges and region statistics.

---

## 4. Coordinate Alignment & Offset Math

Because windowed FFTs evaluate blocks of length $W$ advancing by hop $H$, the physical center of the window does not sit at sample $0$.
The visual bounding box must be offset by:
$$\Delta t_{\text{offset}} = \frac{W/2 - H/2}{f_s}$$
Where $W = \text{window\_size}$ and $H = \text{step\_size}$.
In Maximum Overlap mode (`MAX` or 100%), $H = 1\text{ sample}$.

---

## 5. Instantaneous Frequency & Hilbert Transform

To calculate $f_{\text{inst}}[n]$ reliably across both complex and real-valued captures:
1. **Real-Valued Check**: If $\max |\text{Im}(x)| < 10^{-9} \cdot \max |\text{Re}(x)|$, convert to an analytic signal:
   $$x_a[n] = \text{hilbert}(x[n])$$
   Apply a 2nd-order Butterworth high-pass filter ($f_c \approx 0.005$) to block DC offsets.
2. **Phase Differentiation**:
   $$\Delta \phi[n] = \text{wrap}_{[-\pi, \pi]}\left(\arg(x[n]) - \arg(x[n-1])\right)$$
   $$f_{\text{inst}}[n] = \frac{\Delta \phi[n]}{2\pi} \cdot f_s$$
3. **Median Filtering**: Pass through `scipy.signal.medfilt` with length $L$ (default 7) to suppress phase wrapping singularities in noise.

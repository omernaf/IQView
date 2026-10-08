# IQView DSP Mathematics & Derivations Reference

This document provides mathematical formulations, derivations, and filter equations implemented in IQView.

---

## 1. Short-Time Fourier Transform (STFT)

For a continuous or discrete complex signal $x[n] = I[n] + jQ[n]$, the windowed discrete STFT at time frame $m$ and frequency bin $k$ is:

$$X[m, k] = \sum_{n=0}^{W-1} x[m \cdot H + n] \cdot w[n] e^{-j \frac{2\pi}{N} kn}$$

Where:
- $W$: Window size (`window_size`).
- $N$: FFT bin size (`fft_size`), where $N \ge W$ (zero-padded if $N > W$).
- $H$: Hop / step size (`step_size`), derived from requested overlap percentage:
  $$H = \max\left(1, \lfloor W \cdot (1 - \text{overlap} / 100) \rfloor\right)$$
  When overlap is `MAX` ($100\%$), $H = 1\text{ sample}$.
- $w[n]$: Real-valued window function (Hamming, Hann, Blackman, Bartlett, Rectangular).

---

## 2. Power Spectral Density (PSD) Normalization

The physical power spectral density $S_{xx}(f)$ has units of $\text{V}^2/\text{Hz}$.
To ensure that visual intensity is independent of window type and FFT bin size:

$$\text{Window Energy Factor}: S_2 = \sum_{n=0}^{W-1} w^2[n]$$

$$\text{PSD Offset (dB)}: \text{offset}_{\text{dB}} = 10 \log_{10}\left(\max\left(f_s \cdot S_2, 10^{-30}\right)\right)$$

$$\text{PSD}_{\text{dB/Hz}}[k] = 20 \log_{10}\left(\max\left(|X[k]|, 10^{-12}\right)\right) - \text{offset}_{\text{dB}}$$

---

## 3. Zero-Phase Complex Filtering

### 3.1 Digital Low-Pass Prototype
The target band $[f_{\text{min}}, f_{\text{max}}]$ is defined by:
$$f_c = \frac{f_{\text{min}} + f_{\text{max}}}{2}, \quad B = f_{\text{max}} - f_{\text{min}}$$
A normalized real low-pass prototype is designed with cutoff:
$$f_{\text{cutoff}} = \frac{B / 2}{f_s / 2} = \frac{B}{f_s}$$
Using Second-Order Sections (`output='sos'`) for numerical stability.

### 3.2 Shift-Filter-Unshift
1. Shift target band to 0 Hz:
   $$x_{\text{base}}[n] = x[n] \cdot e^{-j 2\pi f_c n / f_s}$$
2. Zero-phase forward-backward filter:
   $$y_{\text{base}}[n] = \text{sosfiltfilt}(\text{SOS}, x_{\text{base}}[n])$$
3. Shift back to original frequency band:
   $$y_{\text{BPF}}[n] = y_{\text{base}}[n] \cdot e^{+j 2\pi f_c n / f_s}$$
4. Band-Stop Filter (BSF):
   $$y_{\text{BSF}}[n] = x[n] - y_{\text{BPF}}[n]$$

Because $\text{sosfiltfilt}$ has **zero phase shift and zero delay across all frequencies**, the cancellation in step 4 is mathematically exact.

---

## 4. Analytic Signal & Hilbert Transform for Real Captures

When analyzing real-valued captures (e.g. WAV audio files or single ADC real channels):
$$x_a[n] = x_r[n] + j \mathcal{H}\{x_r[n]\}$$
Where $\mathcal{H}\{\cdot\}$ is the Hilbert transform (`scipy.signal.hilbert`).
To eliminate DC bias prior to phase differentiation:
$$x_{\text{analytic}}[n] = \text{sosfiltfilt}(\text{SOS}_{\text{HPF}}, x_a[n])$$
Where $\text{SOS}_{\text{HPF}}$ is a 2nd-order high-pass Butterworth filter with normalized cutoff $0.005$.

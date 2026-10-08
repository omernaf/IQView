---
type: dsp
tags:
  - code/dsp
  - invariant
title: "PSD Normalization"
---

# 📶 PSD Normalization

True continuous Power Spectral Density (PSD) normalization in units of $\text{dB/Hz}$.

---

## 📐 The Normalization Formula

To ensure intensity values in $\text{dB/Hz}$ are invariant to window type, window length, and FFT size, raw FFT magnitudes are shifted by the window energy offset:

$$\text{offset}_{\text{dB}} = 10 \log_{10}\left(f_s \sum_{n=0}^{N-1} w^2[n]\right)$$

$$\text{PSD}_{\text{dB/Hz}}[k] = 20 \log_{10}(|X[k]|) - \text{offset}_{\text{dB}}$$

---

## ⚡ Calibrated RF Power (`norm_db`)
To support calibrated RF measurements (e.g. dBm) or compensate for frontend gains/attenuators:
$$\text{norm\_factor} = 10^{-\text{norm\_db} / 20}$$
$$x_{\text{scaled}}[n] = x[n] \cdot \text{norm\_factor}$$
Integrated across `FileReaderThread`, `ViewportAwareReader`, `MultiRowProcessor`, and `extract_iq_segment`.

---

## 🔗 Related Notes
- [[MOC - DSP Pipeline]]
- [[dsp.py]]
- [[SpectrogramView]]

# ⏳ Time Domain View

The Time Domain view in IQView allows for high-resolution inspection of individual samples, providing deep insight into signal modulation, pulsing, and transient behavior.

---

## 📈 Plot Modes & Mathematics

For complex IQ samples $x[n] = I[n] + jQ[n]$, IQView offers several visualization modes. When a real-valued signal (like a WAV file) is loaded, the imaginary component $Q[n]$ is treated as zero, except in specialized modes like Instantaneous Frequency.

### 1. Amplitude Components
*   **Real**: $Re\{x[n]\} = I[n]$
*   **Imaginary**: $Im\{x[n]\} = Q[n]$ (zero for real-valued signals)
*   **Real [dB]**: $20 \log_{10}(|I[n]| + \epsilon)$
*   **Imaginary [dB]**: $20 \log_{10}(|Q[n]| + \epsilon)$

### 2. Envelope & Power
*   **Magnitude**: $|x[n]| = \sqrt{I[n]^2 + Q[n]^2}$
*   **Magnitude [dB]**: $20 \log_{10}(|x[n]| + \epsilon)$
*   **Magnitude²**: $|x[n]|^2 = I[n]^2 + Q[n]^2$
*   **Magnitude² [dB]**: $10 \log_{10}(|x[n]|^2 + \epsilon)$

*$\epsilon$ is a small constant ($10^{-18}$) to prevent $\log(0)$.*

### 3. Phase & Frequency
*   **Phase**: $\phi[n] = \text{atan2}(Q[n], I[n])$
*   **Unwrapped Phase**: $\Psi[n] = \text{unwrap}(\phi[n])$
*   **Instantaneous Frequency (Complex Signals)**:
    $$f_{\text{inst}}[n] = \frac{\text{wrap}(\phi[n] - \phi[n-1])}{2\pi} \cdot f_s$$
    Where $\text{wrap}(\theta)$ maps phase differences to the range $[-\pi, \pi]$, and $f_s$ is the sample rate.
*   **Instantaneous Frequency (Real Signals - FM Demodulation)**:
    If a real signal is detected (e.g. from a `.wav` file where $Q[n] \approx 0$), a naive phase calculation yields phase values of only $0$ or $\pi$. To support FM demodulation on real signals, IQView dynamically computes the analytic signal $z[n]$ using the **Hilbert transform**:
    
    $$z[n] = I[n] + j \mathcal{H}\{I[n]\}$$
    
    To eliminate low-frequency drift and DC offsets introduced by the Hilbert approximation without altering signal content, the analytic signal is passed through a zero-phase 2nd-order high-pass Butterworth filter:
    
    $$z_{\text{hp}}[n] = \text{ButterworthHPF}(Re\{z[n]\}) + j \text{ButterworthHPF}(Im\{z[n]\})$$
    
    The cutoff frequency is fixed to a very low value ($0.5\%$ of Nyquist, or $0.005$ normalized). The wrapped phase difference is then calculated on $z_{\text{hp}}[n]$, followed by a moving median filter of length $L$ (defined by the `core/inst_freq_filter_len` setting, must be an odd integer) to reject noise transients:
    
    $$f_{\text{inst}}[n] = \text{MedianFilter}\left( \frac{\text{wrap}(\angle z_{\text{hp}}[n] - \angle z_{\text{hp}}[n-1])}{2\pi} \cdot f_s, \; L \right)$$

---

## 🎯 Interactive Markers

Markers in the Time Domain view are designed for precise measurement and comparison.

### 1. Marker Types
*   **Time Markers (T)**: Vertical lines for measuring duration ($\Delta T$).
*   **Magnitude Markers (F)**: Horizontal lines for measuring amplitude/power levels ($\Delta \text{Mag}$).
*   **Endless Markers (Shift+T / Shift+F)**: Toggles Endless Marker mode. You can place up to 100 vertical (`Shift+T`) or horizontal (`Shift+F`) markers, each labeled dynamically (e.g. M1, M2, ...).

### 2. Marker Locking Logic
When two markers are present, you can lock their relationship using the checkbox panel:
*   **Lock M1 / M2**: Fixes the marker to its current value, preventing accidental dragging.
*   **Lock Delta**: Keeps the distance between them constant. Moving one will move the other to maintain the gap.
*   **Lock Center**: Fixes the midpoint. Dragging one marker will move the other in the opposite direction (symmetric expansion/contraction).

---

## 📊 Statistics Selection

By selecting the **STATS** interaction mode, you can drag a shaded region across the plot to compute real-time statistics:
*   **Peak (Max)**: The highest value in the selected slice.
*   **Noise Floor (Min)**: The lowest value in the slice.
*   **Median**: The middle value, robust against outliers like impulsive noise.
*   **Mean (Average)**:
    *   For linear plots (e.g. Magnitude, Real, Imag):
        $$\text{Mean} = \frac{1}{M} \sum_{n=1}^{M} x[n]$$
    *   For logarithmic (dB) plots, averaging directly in dB is mathematically incorrect because dB is a logarithmic representation of power. IQView converts the values back to the linear power domain, averages them, and converts the result back to dB:
        *   **For 20log plots** (Magnitude dB, Real dB, Imag dB):
            $$\text{Mean}_{\text{dB}} = 20 \log_{10}\left( \frac{1}{M} \sum_{n=1}^{M} 10^{x_{\text{dB}}[n]/20.0} \right)$$
        *   **For 10log plots** (Magnitude² dB):
            $$\text{Mean}_{\text{dB}} = 10 \log_{10}\left( \frac{1}{M} \sum_{n=1}^{M} 10^{x_{\text{dB}}[n]/10.0} \right)$$

---

## 🛠️ View Management

*   **Undo Zoom (Ctrl+Z)**: Quickly jump back through your zoom history.
*   **Rebuild Plot Buttons**: Configure which plot modes are visible in the toolbar via the Settings menu.
*   **Auto-Range**: Quickly fit the Y-axis to the currently visible data range.

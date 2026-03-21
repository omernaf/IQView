# ⏳ Time Domain View

The Time Domain view in IQView allows for high-resolution inspection of individual samples, providing deep insight into signal modulation, pulsing, and transient behavior.

---

## 📈 Plot Modes & Mathematics

For complex IQ samples $x[n] = I[n] + jQ[n]$, IQView offers several visualization modes:

### 1. Amplitude Components
- **Real**: $Re\{x[n]\} = I[n]$
- **Imaginary**: $Im\{x[n]\} = Q[n]$
- **Real [dB]**: $20 \log_{10}(|I[n]| + \epsilon)$
- **Imaginary [dB]**: $20 \log_{10}(|Q[n]| + \epsilon)$

### 2. Envelope & Power
- **Magnitude**: $|x[n]| = \sqrt{I[n]^2 + Q[n]^2}$
- **Magnitude [dB]**: $20 \log_{10}(|x[n]| + \epsilon)$
- **Magnitude²**: $|x[n]|^2 = I[n]^2 + Q[n]^2$
- **Magnitude² [dB]**: $10 \log_{10}(|x[n]|^2 + \epsilon)$

### 3. Phase & Frequency
- **Phase**: $\phi[n] = \text{atan2}(Q[n], I[n])$
- **Unwrapped Phase**: $\Psi[n] = \text{unwrap}(\phi[n])$
- **Instantaneous Frequency**: $f_{\text{inst}}[n] = \frac{\Delta \Psi[n]}{2\pi} \cdot f_s$
    - *Commonly used for FSK/MSK demodulation analysis.*

---

## 🎯 Interactive Markers

Markers in the Time Domain view are designed for precise measurement and comparison.

### 1. Marker Types
- **Time Markers (T)**: Vertical lines for measuring duration ($\Delta T$).
- **Magnitude Markers (F)**: Horizontal lines for measuring amplitude/power levels ($\Delta \text{Mag}$).
- **Endless Markers (Shift+T/F)**: Allow placing up to 100 markers, each labeled dynamically (M1, M2, ...).

### 2. Marker Locking Logic
When two markers are present, you can lock their relationship:
- **Lock M1 / M2**: Fixes the marker to its current value, preventing accidental dragging.
- **Lock Delta**: Keeps the distance between them constant. Moving one will teleport the other to maintain the gap.
- **Lock Center**: Fixes the midpoint. Dragging one marker will move the other in the opposite direction (symmetric expansion/contraction).

---

## 📊 Statistics Selection

By selecting the **STATS** interaction mode, you can drag a shaded region across the plot to compute real-time statistics:
- **Peak (Max)**: The highest value in the selected slice.
- **Noise Floor (Min)**: The lowest value in the slice.
- **Mean (Average)**:
    - For linear plots: $\frac{1}{M} \sum x[n]$
    - For dB plots: $20 \log_{10}\left( \frac{1}{M} \sum 10^{x_{\text{dB}}[n]/20} \right)$ (averaging in the power domain).
- **Median**: The middle value, robust against outliers like impulsive noise.

---

## 🛠️ View Management
- **Undo Zoom (Ctrl+Z)**: Quickly jump back through your zoom history.
- **Rebuild Plot Buttons**: Configure which plot modes are visible in the toolbar via the Settings menu.
- **Auto-Range**: Quickly fit the Y-axis to the currently visible data range.

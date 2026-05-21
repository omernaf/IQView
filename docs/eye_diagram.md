# Eye Diagram View

The **Eye Diagram View** provides an interactive environment for visualizing symbol timing, phase alignment, and signal quality of digital modulations.

## 🚀 Opening the View

To open the Eye Diagram:
1. Select a time region in the main **Spectrogram** view by placing two Time Markers (`T`). 
2. **Right-click** anywhere on the spectrogram.
3. Select **"Eye Diagram Popup"**.

If fewer than two markers are placed, the Eye Diagram will extract the currently visible time range on the screen.

> [!NOTE]
> For performance reasons, the Eye Diagram is capped at **500,000 samples**. If the selected region exceeds this limit, the signal is automatically truncated from the beginning, and a "(capped at 500 k)" indicator will appear in the toolbar.

---

## 🎛️ Features and Controls

### 1. Signal Type Selector
Like the Time Domain view, the Eye Diagram can visualize different mathematical representations of the underlying complex IQ data. You can switch between these modes instantaneously using the top toolbar:

- **Real**: In-phase ($I$) component.
- **Imaginary**: Quadrature ($Q$) component.
- **Phase**: Instantaneous phase in radians.
- **Inst. Freq**: Instantaneous frequency. For purely real signals (e.g. WAV audio), the signal is automatically converted to an analytic signal via a Hilbert transform before computing the instantaneous frequency to provide meaningful, continuous phase tracking.
- **Magnitude**: Envelope amplitude ($\sqrt{I^2 + Q^2}$).

### 2. Symbol Timing Sliders (Fractional Nsps)
The core of the Eye Diagram is its ability to wrap the signal at exact symbol boundaries. IQView supports **fractional** Samples Per Symbol (Nsps), controlled by a three-tier slider system for extreme precision:

- **Main**: A coarse integer slider covering `[Nsps - 14, Nsps + 14]`.
- **Coarse**: Fine-tunes the Nsps by `±0.2`.
- **Fine**: Ultra-fine adjustment by `±0.01`.
- **Offset**: Shifts the symbol timing phase (horizontal alignment) by `±1.0` symbol periods.

*Tip: You can also double-click the numeric Nsps box to type an exact value. This will instantly re-center the sliders around your entry.*

### 3. Mini Waveform Overview
At the bottom of the window is a mini "overview" plot displaying the normalized amplitude of the extracted segment. 
- It features two **draggable white handles** (infinite lines).
- Dragging these handles allows you to isolate specific bursts or segments within your extraction without needing to go back to the spectrogram and re-extract. The eye diagram plot updates live as you drag.

### 4. Live Signal Info Panel
The right-side panel provides real-time conversions based on your current Nsps settings and the file's sample rate:
- **Sampling Freq ($f_s$)**: The raw sample rate of the file.
- **Baud Rate**: Calculated as $f_s / \text{Nsps}$.
- **Symbol Time**: Calculated as $1 / \text{Baud Rate}$.

---

## 🧠 Mathematical Background

The eye diagram algorithm relies on modulo arithmetic to determine the relative timing of each sample within a symbol period. The time vector $t$ is calculated as:

$$ t[n] = (- \text{offset} + n) \pmod{\text{Nsps}} $$

Consecutive samples are connected with lines. When $t[n] < t[n-1]$ (meaning the modulo has wrapped around and a new symbol period has started), the rendering engine shifts the new segment back by exactly `Nsps` so that it seamlessly stitches onto the previous trace, preventing horizontal "flyback" lines across the screen.

The horizontal axis is normalized to `[-0.5, 0.5]` symbol periods, standardizing the visual layout regardless of the chosen Nsps.

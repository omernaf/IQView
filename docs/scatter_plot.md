# Scatter Plot View

The **Scatter Plot View** (Constellation view) provides an interactive environment for visualizing, downsampling, and tuning IQ constellation diagrams and scatter plots. It enables real-time symbol timing adjustments, carrier phase rotation, and multi-tier frequency offset despinning without requiring prior knowledge of the exact symbol rate or carrier frequency.

## 🚀 Opening the View

To open the Scatter Plot View:
1. Select a time region in the main **Spectrogram** view by placing two Time Markers (`T`). 
2. **Right-click** anywhere on the spectrogram.
3. Select **"Scatter Plot Popup"**.

If fewer than two markers are placed, the Scatter Plot will extract the currently visible time range on the screen.

> [!NOTE]
> For performance reasons, the Scatter Plot is capped at **500,000 samples**. If the selected region exceeds this limit, a "(capped at 500 k)" indicator will appear in the top toolbar.

---

## 🎛️ Features and Controls

### 1. Integer Downsampling ($N$) & Dynamic Offset ($\tau$)
The Scatter Plot downsamples complex IQ data by an integer factor $N \ge 1$:
- **Downsample (N)**: An integer slider and spinbox ($N \in [1, 10000]$). Setting $N=1$ displays raw un-downsampled IQ samples, while setting $N > 1$ extracts symbol-rate samples.
- **Offset ($\tau$)**: Selects the sub-symbol sampling instant ($0 \le \tau \le N-1$). The offset slider's maximum range automatically updates to $N-1$ whenever $N$ changes.

### 2. Carrier Phase Rotation
Rotates the complex constellation vectors by a fixed phase angle $\phi$:
- **Coarse**: Adjusts phase in a wide range of `[-180.0°, +180.0°]`.
- **Fine**: Fine-tunes phase alignment in a narrow range of `[-5.0°, +5.0°]`.
- **Reset 0°**: Instantly resets both phase sliders back to `0.0°`.

### 3. Three-Tier Frequency Offset Despinning ($f_{\text{offset}}$)
Removes residual carrier frequency offsets to stop constellation rotation. The three tiers dynamically scale with the signal's sample rate ($f_s$):
- **Coarse**: Covers `[-fs/2, +fs/2]` for major carrier frequency alignment.
- **Medium**: 1,000 times finer than Coarse (`±fs / 2000`).
- **Fine**: 1,000 times finer than Medium (`±fs / 2000000`) for high-precision carrier locking.
- **Reset 0 Hz**: Instantly resets all three frequency sliders back to `0.0 Hz`.

### 4. Plot Options
- **Point Size**: Adjusts scatter point diameter (1 to 20 px).
- **Trajectory Lines**: Toggles connecting lines between consecutive constellation points.
- **Grid & Crosshairs**: Toggles background grid, $I/Q$ crosshair axes ($I=0, Q=0$), and reference unit circle overlay (off by default).

### 5. Mini Waveform Overview
Located below the scatter plot, the mini overview shows the normalized amplitude envelope of the extracted segment:
- Features two **draggable white handles** (infinite lines) and shaded region borders.
- Dragging handles dynamically trims the analyzed signal segment in real-time.

### 6. Signal Info Panel
Displays live metrics updated with your current settings:
- **Sample Freq ($f_s$)**: Signal sample rate.
- **Downsample ($N$)**: Active downsampling factor.
- **Baud Rate ($R_b$)**: Calculated as $f_s / N$.
- **Symbol Time ($T_s$)**: Calculated as $N / f_s$.
- **Total Phase**: Sum of coarse and fine phase offsets ($\phi_{\text{total}}$).
- **Total Freq**: Sum of coarse, medium, and fine frequency offsets ($f_{\text{total}}$).
- **Symbols**: Total number of downsampled constellation points displayed.

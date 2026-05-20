# Settings & Configuration Guide

IQView features a comprehensive settings system backed by `QSettings` to allow users to customize DSP behaviors, appearance, keyboard shortcuts, plot layouts, and file type auto-associations. 

This document details the configuration options, default values, and how settings are stored on your system.

---

## 💾 Storage Locations

Settings are persisted across application restarts using the system-native configuration store:
*   **Windows**: Stored in the System Registry under:
    `HKEY_CURRENT_USER\Software\IQViewProject\IQView`
*   **Linux / macOS**: Stored in a standard INI configuration file at:
    `~/.config/IQViewProject/IQView.conf`

---

## ⚙️ Settings Menu Overview

The settings dialog is split into six dedicated tabs, accessible via the menu bar under **Edit -> Settings**.

### 1. General Tab
Controls default signal parameters and high-level performance options:

*   **Default Sample Rate (Hz)**: The fallback sample rate $f_s$ used when opening raw, untyped binary files (Default: `1000000` / 1 MHz).
*   **Default Center Freq (Hz)**: The fallback RF center frequency $f_c$ (Default: `0.0` Hz).
*   **Default File Type**: The default data layout parsed from binary files. Options: `int16`, `float32`, `float64`, `complex64`, `complex128` (Default: `complex64`).
*   **Default FFT Size**: The number of frequency bins (FFT length $N$) for the spectrogram. Higher sizes provide higher frequency resolution but reduce time resolution (Default: `1024`).
*   **Default Overlap (%)**: The percentage of overlap between successive FFT windows (Default: `99.0`%).
*   **Default Window**: The window function applied to each signal segment before FFT processing. Options: `Hamming`, `Hanning`, `Blackman`, `Bartlett`, `Rectangular` (Default: `Hamming`).
*   **Show 1/T (Hz) Row in Markers**: Toggles whether the reciprocal time difference $1/\Delta T$ (often representing frequency spacing or symbol rate) is shown in the Time Domain Marker Panel (Default: `Off`).
*   **Lazy Rendering**: Enables the **Lazy (On-Demand) Rendering Engine**. When turned on, IQView only processes the section of the file currently visible in your viewport. Zooming in triggers an automatic high-resolution re-computation of that region. This is highly recommended for files larger than a few megabytes as it prevents RAM exhaustion and makes files open instantly. Turn off to force full upfront loading (Default: `On`).

---

### 2. Appearance Tab
Allows detailed styling of the plots, grids, and themes:

*   **Theme**: Toggle between `Dark` and `Light` themes. Styles and palettes are updated immediately upon clicking **Apply** or **OK**.
*   **Default Colormap**: The gradient scale used to map power levels (dB) to colors in the spectrogram (e.g. `turbo`, `thermal`, `viridis`, `grey`) (Default: `turbo`).
*   **Reverse Colormap**: Inverts the colors of the chosen colormap.
*   **Grid Visibility**: Toggle the background coordinate grid lines on main views.
*   **Grid Color, Style, & Opacity**: Customize the background axis grid's appearance. Colors are chosen via a dialog, and styles include `SolidLine`, `DashLine`, etc. Opacity ranges from 0% (transparent) to 100% (opaque).
*   **Marker Grid Color, Style, Opacity, & Width**: Customizes the dashed cyclic/continuation grid lines drawn from active time and frequency markers. These are decoupled from the background grid to prevent visual clutter.
*   **Axis Font Size**: Tick mark font size in pixels (Default: `10`).
*   **Label Precision**: The number of decimal places displayed for marker values and statistics (Default: `6`).
*   **Time / Freq Marker & Zoom Box Colors**: Custom color definitions and line styles (`SolidLine`, `DashLine`, `DotLine`) for markers and zoom selection boxes. Managed independently for Dark and Light themes.

---

### 3. Keyboard Tab
Customize hotkeys for active measurement modes:

*   **Time Markers Key**: Pressing this key enters vertical Time Marker placement mode (Default: `T`).
*   **Magnitude/Freq Markers Key**: Pressing this key enters horizontal Frequency/Magnitude Marker placement mode (Default: `F`).
*   **Zoom Pulse Key (Hold)**: Pressing and holding this key temporarily switches the cursor into zoom box mode. Dragging a rectangle zooms the view. Releasing the key returns the cursor to its previous placement mode (Default: `Ctrl`).

---

### 4. Filter Tab
Configure the DSP parameters used for both time-domain and frequency-domain filtering:

*   **Filter Type**: The DSP filter architecture. Options: `Butterworth`, `Chebyshev I`, `Chebyshev II`, `Elliptic`, `Bessel`, and `FIR (Windowed)` (Default: `Elliptic`).
*   **Filter Order**: The order ($N$) of the IIR filter. Higher orders yield steeper roll-off curves but increase computation time and filter transient length (Default: `8`).
*   **Passband Ripple (dB)**: Ripple allowance in the passband. (Applicable to Chebyshev I and Elliptic, Default: `0.1` dB).
*   **Stopband Attenuation (dB)**: Out-of-band rejection level. (Applicable to Chebyshev II and Elliptic, Default: `60.0` dB).
*   **Number of Taps**: The number of coefficients for FIR filters. Higher values yield sharper cutoffs (Applicable to FIR (Windowed), Default: `101`).
*   **FIR Window**: Window function used to design windowed FIR filters. Options: `Hamming`, `Hanning`, `Blackman`, `Bartlett`, `Rectangular` (Default: `Hamming`).
*   **Bessel Norm**: Normalization style for Bessel filter designs. Options: `phase` (delay matches lowpass at DC), `delay` (group delay is normalized), `mag` (magnitude response matches standard filters at 3dB cutoff) (Default: `phase`).

---

### 5. Time / Frequency Plots Tabs
Configure which plot modes are enabled and what order they appear in the Time and Frequency Domain toolbars:

*   **Time Plots**: Enable/disable modes (e.g. `Real`, `Imaginary`, `Magnitude`, `Phase`, `Instant Frequency`). Drag-and-drop rows to reorder them in the GUI.
    *   *Median Filter*: When `instant frequency` is selected, you can specify the window length of a running median filter to smooth phase noise. Must be an odd number (Default: `7` taps).
*   **Frequency Plots**: Enable/disable spectral representations (e.g. `magnitude`, `magnitude [dB]`, `PSD [dB]`, `real`, `imag`, `phase`). Drag-and-drop rows to reorder them in the GUI.
    *   *Algorithm*: For Power Spectral Density (PSD) calculation, choose between:
        *   `Welch`: Computes overlapping windowed segments and averages them, reducing noise variance (default).
        *   `Periodogram`: Computes a direct FFT of the segment, keeping raw spectral spikes intact.

---

### 6. File Types Tab
Automates data-type mapping based on file extensions:

*   **Extension Table**: Correlates file extensions to parsing layouts. For example, a file ending in `.32fc` is auto-mapped to `complex64` (float32 real/imag pairs).
*   **Custom Mappings**: You can add new rows to map custom extensions (e.g., mapping `.raw` to `int16`) or modify/remove existing mappings.
*   **Restore Defaults**: Instantly resets the table to factory defaults:
    *   `.32f` $\rightarrow$ `float32`
    *   `.64f` $\rightarrow$ `float64`
    *   `.16tc` / `.16sc` $\rightarrow$ `int16`
    *   `.64fc` $\rightarrow$ `complex128`
    *   `.32fc` / `.bin` / `.iq` $\rightarrow$ `complex64`

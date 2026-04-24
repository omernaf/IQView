# Changelog

## [0.1.4] - 2026-04-24

### Added
- **Interactive Overlays**: Overlays (Shapes and Lines) can now be interactively dragged, moved, and resized via visual handles directly on the spectrogram.
- **Overlay State Locking**: Added a "Lock" button per item in the Overlays table to freeze specific items into place, preventing accidental modifications while zooming/panning.
- **Python Plugin System**: Introduced a lightweight extension framework allowing users to write simple `run()` scripts to natively process IQ samples and dynamically yield custom overlays safely via isolated background threads.
- **Example Plugins**: Added template `mark_view.py` and peak detection `detect_peaks.py` plugin scripts to demonstrate integration.
- **Overlay JSON Importer**: The Overlays menu now supports importing/merging JSON configuration files with zero collision risk.
- **Chrome-like Tab Undocking**: Drag any analysis tab vertically out of the tab bar to tear it off into a standalone window.
- **Tab Ghost Preview**: Visual feedback during undocking with a semi-transparent preview following the cursor.
- **Movable Tabs**: Tabs can now be reordered horizontally within the tab bar.
- **Spectrogram Tab Pinning**: The primary Spectrogram tab remains fixed at index 0 and cannot be moved or displaced.
- **"Dock Back" Toolbar**: Detached windows now include a dedicated toolbar button for returning views to the main tab bar.
- **Frequency Domain Filtering**: Added real-time Band-Pass (BPF) and Band-Stop (BSF) filter overlays to the Frequency Domain view, identical in function to the Spectrogram filters.

### Changed
- **Marker Value Auto-Select**: Clicking any value in the marker tables now automatically selects the full unformatted text, making it instantly ready for copying or manual entry.
- **Smooth Lazy Scrolling**: The lazy rendering engine now pre-generates an additional screen width of spectrogram data in both directions to eliminate blank edges during panning and scrolling.
- **Unified Circle/Ellipse Handling**: Simplified shape geometries by removing the ambiguous `CIRCLE` type. Circular features are now expressed as `ELLIPSE` types with independent physical units (seconds vs. Hz radii) preventing disproportionate visual scaling.
- **Marker Data Alignment**: Standardized Marker and Overlay table layouts mapping sample/bin values strictly in the top row and metric data (seconds/Hz) immediately below it.

### Fixed
- **OS Theme Visibility Bugs**: Overhauled top menu `QMenuBar` and `QMenu` styling to strictly adhere to dark mode palettes, fixing OS black-on-black text blending bugs.
- **Adaptive Tooltip Engine**: Forced tooltip `QToolTip` backgrounds to explicitly track and invert on light/dark theme toggle, fixing text washout under bright environments.
- **Taskbar Icon Consistency**: Unified the `AppUserModelID` strings and ensured the application icon is set on the `QApplication` instance. This ensures the custom logo consistently appears in the Windows taskbar instead of the default Python icon.
- **DSP Zero-Phase Architecture**: Architecturally corrected `apply_filter()` deep within the DSP engine. It now uses zero-phase forward-backward filtering (`sosfiltfilt`/`filtfilt`) instead of causal filtering, eliminating phase distortion and group-delay time-shifts. This guarantees that `BandStop = Original - BandPass` behaves mathematically correctly and cancels target bands seamlessly.

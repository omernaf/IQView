# Changelog

## [0.1.4] - 2026-04-03

### Added
- **Chrome-like Tab Undocking**: Drag any analysis tab vertically out of the tab bar to tear it off into a standalone window.
- **Tab Ghost Preview**: Visual feedback during undocking with a semi-transparent preview following the cursor.
- **Movable Tabs**: Tabs can now be reordered horizontally within the tab bar.
- **Spectrogram Tab Pinning**: The primary Spectrogram tab remains fixed at index 0 and cannot be moved or displaced.
- **"Dock Back" Toolbar**: Detached windows now include a dedicated toolbar button for returning views to the main tab bar.
- **Frequency Domain Filtering**: Added real-time Band-Pass (BPF) and Band-Stop (BSF) filter overlays to the Frequency Domain view, identical in function to the Spectrogram filters.

### Fixed
- **Taskbar Icon Consistency**: Unified the `AppUserModelID` strings and ensured the application icon is set on the `QApplication` instance. This ensures the custom logo consistently appears in the Windows taskbar instead of the default Python icon.
- **DSP Zero-Phase Architecture**: Architecturally corrected `apply_filter()` deep within the DSP engine. It now uses zero-phase forward-backward filtering (`sosfiltfilt`/`filtfilt`) instead of causal filtering, eliminating phase distortion and group-delay time-shifts. This guarantees that `BandStop = Original - BandPass` behaves mathematically correctly and cancels target bands seamlessly.


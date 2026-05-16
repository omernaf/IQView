# Changelog

## [0.1.5] - 2026-05-16

### Added
- **Marker Grid Customization**: Added dedicated width, color, opacity, and line style settings for the cyclic continuation marker lines, completely decoupling them from the background axis grid appearance.
- **Region Overlays**: Added `X-Region` and `Y-Region` overlay shapes. These act as infinite bands (e.g. spanning the entire frequency range between two time points) and support interactive dragging and resizing.
- **Overlay Shape Selector & Manual Add**: Upgraded the Marker Panel with a shape selection dropdown and a "+ Manual Add" button, letting users easily construct overlays through the UI dialog or place specific geometries directly via mouse interactions.
- **Smart Drag & Click Placement**: Interactions dynamically adapt to the selected shape, meaning single clicks now generate proportional default-sized regions or shapes, and drag actions cleanly bound ellipses, polygons, or band regions.
- **Polygon Vertex Manipulation**: Unlocked Polygon overlays now render independent resize handles at each vertex, allowing users to drag and adjust corners individually.
- **Axis-Specific Unzoom**: Added dedicated context menu actions ("Unzoom Time", "Unzoom Frequency", etc.) that selectively reset only the X or Y axis zoom level independently, dynamically labeled based on the active domain view.
- **Plugin API Developer Guide**: Added a comprehensive `plugin_guide.md` to the repository detailing plugin architecture, threading rules, and providing advanced code examples.

### Changed
- **Plugin Overlay API**: Refactored the plugin rendering engine to support returning strongly-typed Python objects (e.g. `Rect`, `VerticalLine`, `Polygon`) from the `iqview.overlays` module instead of requiring raw dictionaries. Legacy dictionary returns remain fully supported for backwards compatibility.
- **Context Menu Cleanup**: Removed the redundant "Switch to Overlay Mode" from the right-click menu, as it is already cleanly accessible from the main top panel.

### Fixed
- **Settings Live Update**: All marker grids now update their appearance instantly across the spectrogram and all detached domain windows when changes are applied in the settings dialog.
- **Settings Dialog Reset Crash**: Fixed a bug where attempting to use reset buttons within the settings dialog would crash the application due to a missing `QDoubleSpinBox` import.

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
- **Global Hotkey Interference**: Fixed an issue where global keyboard shortcuts (e.g., `Ctrl` for Zoom, `T` for Time mode) would intercept inputs while typing in text boxes, preventing actions like `Ctrl+C` from working correctly inside marker tables.
- **OS Theme Visibility Bugs**: Overhauled top menu `QMenuBar` and `QMenu` styling to strictly adhere to dark mode palettes, fixing OS black-on-black text blending bugs.
- **Adaptive Tooltip Engine**: Forced tooltip `QToolTip` backgrounds to explicitly track and invert on light/dark theme toggle, fixing text washout under bright environments.
- **Taskbar Icon Consistency**: Unified the `AppUserModelID` strings and ensured the application icon is set on the `QApplication` instance. This ensures the custom logo consistently appears in the Windows taskbar instead of the default Python icon.
- **DSP Zero-Phase Architecture**: Architecturally corrected `apply_filter()` deep within the DSP engine. It now uses zero-phase forward-backward filtering (`sosfiltfilt`/`filtfilt`) instead of causal filtering, eliminating phase distortion and group-delay time-shifts. This guarantees that `BandStop = Original - BandPass` behaves mathematically correctly and cancels target bands seamlessly.

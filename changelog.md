# Changelog

## [0.5.1] - 2026-05-27

### Added
- **Eye Diagram Baud Rate Cycling Mode**: Added a **⇄ Baud Rate** toggle button next to the SPS spinbox in the Eye Diagram popup. When active, the main slider, coarse/fine sliders, and numeric spinbox all cycle through **Baud Rate (Hz)** instead of Samples-Per-Symbol. The three-tier slider ranges scale proportionally to the current baud rate (±50% main, ±2% coarse, ±0.1% fine). While in Baud Rate mode, the computed **SPS** is shown as a highlighted row in the Signal Info panel so both values are visible simultaneously.

### Changed
- **Versioning Scheme**: Switched the primary version axis from the third position to the second (e.g. `0.1.x` → `0.5.x`), allowing patch/minor releases to increment the third digit going forward.

### Fixed
- **Debian Package Installation**: Fixed the `.deb` `postinst` script — IQView and all its dependencies are now installed via a plain `pip install iqview=={version}` from the user's default PyPI server into a fresh virtual environment at `/opt/iqview/venv`. The package no longer bundles or installs from a local `.whl` file. The offline build path (`--offline-wheels`) is unchanged.
- **Waterfall Time Axis Direction**: Fixed the Y axis in Waterfall mode so that time `0` (signal start) is at the **top** and the latest time is at the **bottom**, matching the conventional waterfall display convention. Previously the axis was upward, placing the oldest data at the bottom.
- **`iqview.view()` Explicit `fs`/`fc` Ignored at 1 MHz / 0 Hz**: Fixed a bug where calling `iqview.view(file, fs=1e6)` or `iqview.view(file, fc=0.0)` would silently override the caller's explicit value with any sample rate or center frequency auto-detected from the filename. The old code compared `fs == 1e6` to detect "not set", which is indistinguishable from an intentional `1e6` argument. `fs` and `fc` now default to `None` as a proper sentinel so explicit values are always honoured.

---

## [0.5.0] - 2026-05-16

### Added
- **Waterfall Spectrogram Layout**: Added a "Waterfall" checkbox in the settings to transpose the spectrogram axes (X-axis = Frequency, Y-axis = Time).
- **Adaptive Marker UI**: Marker panel icons and tooltips now dynamically swap depending on whether the spectrogram is in Standard or Waterfall orientation to maintain intuitive vertical/horizontal representation.
- **Eye Diagram Popup**: Added an interactive Eye Diagram analysis tab accessible via right-click on the spectrogram. Includes signal-type selectors (Real, Imaginary, Phase, Inst. Freq, Magnitude), fractional Nsps support with three-tier sliders (Main, Coarse, Fine) for precise symbol timing, an offset slider, and a mini waveform overview with draggable range handles for isolating specific signal segments.
- **Marker Grid Customization**: Added dedicated width, color, opacity, and line style settings for the cyclic continuation marker lines, completely decoupling them from the background axis grid appearance.
- **Region Overlays**: Added `X-Region` and `Y-Region` overlay shapes. These act as infinite bands (e.g. spanning the entire frequency range between two time points) and support interactive dragging and resizing.
- **Overlay Shape Selector & Manual Add**: Upgraded the Marker Panel with a shape selection dropdown and a "+ Manual Add" button, letting users easily construct overlays through the UI dialog or place specific geometries directly via mouse interactions.
- **Smart Drag & Click Placement**: Interactions dynamically adapt to the selected shape, meaning single clicks now generate proportional default-sized regions or shapes, and drag actions cleanly bound ellipses, polygons, or band regions.
- **Polygon Vertex Manipulation**: Unlocked Polygon overlays now render independent resize handles at each vertex, allowing users to drag and adjust corners individually.
- **Axis-Specific Unzoom**: Added dedicated context menu actions ("Unzoom Time", "Unzoom Frequency", etc.) that selectively reset only the X or Y axis zoom level independently, dynamically labeled based on the active domain view.
- **Plugin API Developer Guide**: Added a comprehensive `plugin_guide.md` to the repository detailing plugin architecture, threading rules, and providing advanced code examples.
- **Background Update Version Checker**: Added an automatic background version checker that runs `pip index versions` in a non-blocking daemon thread on startup, showing a highlighted update notification directly below the version number in the SidePanel if a newer version is available. It automatically respects local pip repository configurations (e.g. private servers, mirrors, and custom credentials) and handles offline/unreachable conditions gracefully.
- **WAV Audio File Support**: IQView can now load `.wav` audio files as signal data. Multi-channel audio is automatically averaged to mono and integer samples (int8, int16, int32) are normalised to float32 in the range `[-1.0, 1.0]`. The sample rate is read directly from the WAV header with no manual input required. Supported via CLI (`iqview -f audio.wav` or `iqview -f audio.wav -t aud`) and via **File → Open** in the GUI. No new dependencies are required — uses the existing `scipy.io.wavfile` reader.
- **Offline Debian Package Wheels Bundling**: Added `--offline-wheels` support to the build scripts (`build_project.py` and `make_deb.py`) to package pre-downloaded dependency wheels inside the Debian `.deb` archive. The installation process detects the bundle and executes completely offline using local wheel files via `--no-index --find-links`.
- **System Package Dependencies**: Added explicit `python3-pip` and `libxcb-cursor0` package requirements to the Debian package dependencies to guarantee successful virtual environment configuration and GUI execution on X11 targets.
- **Python API & Plugin Debugging**: Added the `iqview.view()` function to launch the application directly from Python scripts. This enables opening files or passing raw NumPy arrays programmatically, making it perfect for setting IDE breakpoints and debugging plugins interactively.

### Changed
- **Adaptive Icon Theming**: Button icons and assets (like marker controls) now dynamically respond to the active Light/Dark theme configuration instead of being hardcoded.
- **Plugin Overlay API**: Completely redesigned the plugin return mechanism. Plugins must now return a `PluginResult` object to express overlay operations (`.add()`, `.update()`, `.remove()`, `.replace()`). This allows plugins to non-destructively modify or remove existing overlays (e.g., snapping rectangles to a grid) rather than just adding new ones. The `info["overlays"]` dictionary now provides safe, deep-copied `Overlay` objects for easy attribute access.
- **Context Menu Cleanup**: Removed the redundant "Switch to Overlay Mode" from the right-click menu, as it is already cleanly accessible from the main top panel.
- **Instantaneous Frequency for Real Signals**: The "instant frequency" plot in the Time Domain popup now produces meaningful output for real-valued signals (e.g. WAV files, real-sampled SDR). Previously, the naive `diff(angle())` approach yielded erratic 0/π phase jumps. The signal is now converted to an analytic signal via a Hilbert transform, followed by a very wide DC-blocking HPF (to remove any Hilbert-induced DC offset), before computing the instantaneous frequency using modulo phase difference wrapping — identical to the path used for complex IQ signals. Complex signals are unaffected.
- **Top Menu Restructure**: Moved the standalone "Overlays" top-level menu into the "File" menu as a dedicated sub-menu.
- **Open Recent Enhancements**: The "Open Recent" files feature now stores and restores the specific Sample Rate (`fs`), Center Frequency (`fc`), and Data Type that were active when the file was last opened, instead of falling back to default or auto-detected settings.


### Fixed
- **Waterfall Overlay Rendering & Interaction**: Completely overhauled `OverlayItem` and drag interactions to correctly render shapes (Rectangles, Ellipses, Polygons, and Bands) and map mouse interactions when the axes are transposed in Waterfall mode.
- **Waterfall Domain Analysis Popups**: Fixed a bug where triggering a Time Domain or Frequency Domain popup in Waterfall mode with no markers placed would attempt to extract an impossibly large number of samples, hitting the sample limit protection.
- **Waterfall Lazy Rendering**: Fixed an issue where the spectrogram lazy-rendering engine would render only a few pixels when in Waterfall mode due to reading bounds from the wrong axis.
- **Settings Live Update**: All marker grids now update their appearance instantly across the spectrogram and all detached domain windows when changes are applied in the settings dialog.
- **Settings Dialog Reset Crash**: Fixed a bug where attempting to use reset buttons within the settings dialog would crash the application due to a missing `QDoubleSpinBox` import.
- **.mat File Window Title and Association**: Fixed a bug where loading a `.mat` file displayed `<stdin>` in the window title instead of the actual file name/path. This also restores proper saving and loading of overlay sidecars (`.mat.overlays`) for MATLAB files.
- **Dynamic .mat Loading & SidePanel Integration**: Enabled opening `.mat` files dynamically via the File menu or Recent Files list, automatically parsing their structures and updating the spectrogram data, sample rate, center frequency, and SidePanel controls.
- **Dynamic Filename Parameter Auto-detection**: Enabled automatic extraction of sample rate and center frequency from the filename (e.g. `_10Msps_433MHz`) when loading any binary files dynamically in the UI.
- **Debian Package Post-Installation Network Hangs**: Removed the unnecessary `pip install --upgrade pip` step from the Debian `postinst` script, preventing installation hangs and timeouts on private, restricted, or offline networks.
- **Open Recent Colormap Scaling**: Fixed a bug where loading a file from the "Open Recent" menu would inherit the colormap bounds and view ranges of the previously open file. It now correctly resets the view as if a fresh file was loaded.
- **Open Recent Missing Files**: Fixed an issue where clicking a missing or deleted file from the "Open Recent" list would silently fail. It now displays a warning message and automatically removes the dead entry from the menu.


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

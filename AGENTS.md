# IQView Agent Guidelines & Project Invariants

Welcome to **IQView** — a high-performance, GPU-accelerated RF Spectrogram Viewer built with Python, PyQt6, pyqtgraph, and PyOpenGL.

When modifying or extending this codebase, adhere strictly to the following architectural rules and invariants:

---

## 0. Mandatory Skill Activation Protocol (Pre-Flight Gate)

Before modifying code, running commands, or implementing features for any non-trivial task:
1. **Identify Applicable Skills**: Check the task domain against the 8 specialized skills in `.agents/skills/`:
   - `iqview-plugin-development`: Any work touching plugins, `PluginManagerMixin`, Plugin Studio, plugin chains, Quick Run, or overlay attachments.
   - `iqview-views-architecture`: Any work touching analysis views, 1D/2D plots, spectrograms, tabs, markers, or detached windows.
   - `iqview-ui-pyqtgraph`: Low-level PyQt6/pyqtgraph widgets, `CustomViewBox`, marker dragging/clamping, themes, signal loops (`blockSignals`), and dialogs.
   - `iqview-dsp-algorithms`: DSP filters, PSD normalization, mathematical calculations, and demodulation math.
   - `iqview-io-formats`: File loading/saving, formats (`.r3f`, `.mat`, audio), byte slicing, and streaming.
   - `iqview-testing-qa`: Headless tests, synthetic datasets, smoke tests, and regression checklists.
   - `iqview-packaging-release`: Packaging, PyPI wheels, Debian packaging (`scripts/make_deb.py`), and release checklists.
   - `code-cartography`: Codebase mapping and updating the Obsidian knowledge graph in `cartography/`.
2. **Mandatory `view_file` Execution**: You **MUST call `view_file` on the relevant `SKILL.md` file(s)** as your very first step before editing code or proceeding with implementation.
3. **No Direct Bypassing**: Never skip consulting the skill guide when a specialized skill exists for that domain.

---

## 1. Digital Signal Processing (DSP) Invariants

1. **Zero-Phase Filtering Mandate**:
   - Time-domain filtering in `iqview/dsp/dsp.py` must **always** use zero-phase forward-backward filtering (`scipy.signal.sosfiltfilt` or `filtfilt`).
   - Never use causal filtering (`sosfilt` / `lfilter`) for time-domain analysis, as causal filters introduce non-linear phase shifts and group delays, breaking the mathematical identity $BSF = \text{Original} - BPF$.
2. **True Power Spectral Density (PSD) Normalization**:
   - All spectrogram and PSD pipelines must include the window power normalization offset:
     $$\text{offset}_{\text{dB}} = 10 \log_{10}\left(f_s \sum w^2[n]\right)$$
   - This ensures intensity values in $\text{dB/Hz}$ are invariant to window type, window length, and FFT size.
3. **Calibrated RF Power Normalization (`norm_db`)**:
   - Normalization factor scales samples by $10^{-\text{norm\_db} / 20}$ (power by $10^{-\text{norm\_db} / 10}$).
   - Any DSP pipeline extracting or processing raw samples (`FileReaderThread`, `ViewportAwareReader`, `MultiRowProcessor`, `extract_iq_segment`) must honor `norm_db`.
4. **Coordinate Alignment Offset**:
   - Spectrogram image bounding boxes must account for the DSP window-center shift:
     $$\Delta t_{\text{offset}} = \frac{\text{window\_size} / 2 - \text{step\_size} / 2}{f_s}$$
   - This keeps the visual center of every FFT pixel aligned with the underlying sample coordinates.
5. **Numerical Stability**:
   - Never compute $\log_{10}(0)$. Always clip magnitude arrays to $\epsilon = 10^{-12}$ (or $10^{-30}$ for power sum checks) before decibel conversion.

---

## 2. Views & UI Architecture Invariants

1. **1D Domain View Hierarchy**:
   - Time Domain and Frequency Domain views must inherit from [`Base1DPlotView`](file:///d:/Projects/IQView/iqview/ui/base_1d/view.py).
   - Marker panels must inherit from [`Base1DMarkerPanel`](file:///d:/Projects/IQView/iqview/ui/base_1d/marker_panel.py).
   - Keep pure DSP calculations inside [`domain_transforms.py`](file:///d:/Projects/IQView/iqview/dsp/domain_transforms.py), keeping the UI classes focused on Qt event management and rendering.
2. **pyqtgraph Interaction Protocol**:
   - **Never** set `movable=True` directly on pyqtgraph `InfiniteLine` instances.
   - All mouse drag events, hit-testing (minimum Euclidean distance), and boundary clamping must pass through [`CustomViewBox`](file:///d:/Projects/IQView/iqview/ui/widgets.py) to keep UI tables and graphics synchronized.
3. **Marker Locking & Boundary Clamping**:
   - When markers are locked (`Delta` or `Center` lock), moving one marker near a boundary must adaptively clamp the entire pair proportionally against the boundary. Never drop the drag event or let markers teleport.
4. **Visual Aesthetics & Shortcuts**:
   - Non-spectrogram 1D trace curves use MATLAB blue (`#0072BD`, line width `0.5`).
   - Every toolbar and panel button must display its active keyboard shortcut in brackets in its tooltip (e.g. `[T]`, `[Hold Ctrl]`, `[F1]`).
   - When programmatically modifying checkboxes or line edits during marker clears or state changes, use `blockSignals(True)` to prevent recursive signal loops.

---

## 3. Plugin Architecture Invariants

1. **Cooperative Cancellation**:
   - `PluginCancelledError` inherits from `BaseException`.
   - **Never** catch `BaseException` or use bare `except:` inside plugins or plugin execution wrappers.
   - Long-running loops inside plugins must regularly inspect `info.is_cancelled()` and exit promptly.
2. **Memory Bounding on Large Recordings**:
   - Set `PLUGIN_NEEDS_WIDEBAND_IQ = False` if the plugin only processes existing overlays or calls `o.get_samples()`.
   - For wideband stream processing, utilize `PLUGIN_BATCH_SECONDS` and `info.iter_batches()` rather than allocating the entire recording in memory.
3. **In-App Documentation**:
   - Every plugin must define `PLUGIN_DOC` as a GitHub-flavored Markdown string describing its algorithm, inputs, and outputs.

---

## 4. File I/O & Packaging Invariants

1. **Cross-Platform Paths**:
   - Always use `os.path.normpath(os.path.abspath(path))` or `pathlib.Path`.
   - Never construct Windows-specific hardcoded backslash paths.
2. **Byte Offset Safety**:
   - When slicing arbitrary byte ranges (`--start-byte`, `--stop-byte`, `--bytes`), safely truncate trailing bytes that do not form a complete sample element or complex pair before passing to `numpy.frombuffer`.
3. **Debian Packaging (`scripts/make_deb.py`)**:
   - Always calculate `TarInfo.size` using the UTF-8 byte length (`len(content.encode('utf-8'))`), not character count `len(content)`.
   - Linux launcher scripts must strip host Qt theme overrides (`QT_QPA_PLATFORMTHEME=""`, `QT_STYLE_OVERRIDE=""`).
4. **Ephemeral Testing Invariant (Zero Clutter)**:
   - **Never** leave or commit one-off test scripts in `testing/` or anywhere in the repository for every feature.
   - When verifying features or bugfixes, agents must create temporary scratch test scripts, execute them to validate behavior, and **immediately delete them**.
   - Permanent test scripts are strictly reserved for core established suites (`testing.py`, `testing2.py`, `test_quick_run_history.py`, `make_iqview_testdata.py`). Never clutter the app with ad-hoc test files.

---

## 5. Skills Reference & Mandatory Runbooks

Specialized procedures and runbooks are available in `.agents/skills/`. Per Section 0, you **MUST call `view_file` on the corresponding `SKILL.md` before starting work**:
- `iqview-views-architecture`: In-depth guide to all analysis views (Spectrogram, Time Domain, Frequency Domain, Eye Diagram, Scatter Plot, Multi-Row, Detached Windows).
- `iqview-ui-pyqtgraph`: pyqtgraph event pipelines, marker locks, themes, and dialog mechanics.
- `iqview-dsp-algorithms`: Pure DSP routines, zero-phase filtering, PSD normalization, and modulation models.
- `iqview-plugin-development`: Plugin API, parameter schemas, overlays, baseband IQ caching, and chains.
- `iqview-io-formats`: Formats, hardware parsers (`.r3f`, `.mat`), audio, streaming, and byte slicing.
- `iqview-testing-qa`: Synthetic signal generation, headless verification, and the 18-step testing walkthrough.
- `iqview-packaging-release`: Release synchronization, `.deb` packaging, and offline distribution kits.
- `code-cartography`: Generating and maintaining the Obsidian knowledge graph vault for codebase topology and visual exploration.

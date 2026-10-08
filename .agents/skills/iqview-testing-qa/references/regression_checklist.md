# IQView Historical Regression Checklist

Derived from 521 git commits and changelog fixes up to v0.7.2. Always review these checkpoints before committing major changes or cutting a release.

---

## 1. DSP & Mathematics Regressions
- [ ] **Zero-Phase Exactness**: Does `apply_filter(mode='bsf')` cancel the target band completely? Confirm no causal `sosfilt` was introduced.
- [ ] **Coordinate Alignment**: When zooming in on a placed marker on a chirp or tone, does the marker stay on the exact physical feature? Confirm `(window_size/2 - step_size/2)/sample_rate` offset is intact.
- [ ] **PSD Window Invariance**: Does switching between Hanning, Hamming, and Blackman windows preserve consistent power spectral density in $\text{dB/Hz}$?
- [ ] **Log10 Epsilon Protection**: Does processing an all-zero IQ buffer run without `-inf` or `RuntimeWarning: divide by zero encountered in log10`?
- [ ] **1 MHz Sentinel Bug**: Does passing explicit `fs=1e6` or `fc=0.0` to `iqview.view()` override filename auto-detection properly instead of treating `1e6` as an unset sentinel?

---

## 2. Views & pyqtgraph Regressions
- [ ] **InfiniteLine Interception**: Are all marker `InfiniteLine` instances set to `movable=False`? Does `CustomViewBox` manage all drag events?
- [ ] **Adaptive Clamping**: When `Delta` or `Center` is locked, does dragging one marker rapidly towards the recording boundary slide the pair smoothly to the boundary without freezing or dropping events?
- [ ] **Waterfall State Tracking**: Does changing settings (such as colormap or plot order) avoid swapping axes when Waterfall mode is not toggled? Confirm `_applied_waterfall` tracking.
- [ ] **PreviewLabel Stability**: In `ExportDialog`, does toggling between "Raw Image" and "Plot with Axes" preserve a completely stable window size without resizing jumps?
- [ ] **Recursive Signal Prevention**: Do marker clearing buttons block signals (`blockSignals(True)`) during state resets to prevent recursive event loops?

---

## 3. Plugins & Multithreading Regressions
- [ ] **Cooperative Cancellation**: Does clicking "Cancel" in the progress dialog stop background execution promptly and allow subsequent plugin runs without stating "A plugin is already running"?
- [ ] **BaseException Integrity**: Confirm no plugin or runner uses bare `except:` or catches `BaseException`, allowing `PluginCancelledError` to propagate cleanly.
- [ ] **Memory Bounding**: Do plugins processing long files declare `PLUGIN_NEEDS_WIDEBAND_IQ = False` or use `info.iter_batches()` to avoid multi-gigabyte memory allocations?
- [ ] **Negative GLONASS Channels**: Does the GNSS detector sort satellite channel IDs before plotting so negative channel numbers do not produce non-monotonic plot streaks?

---

## 4. File I/O & Packaging Regressions
- [ ] **Byte Slicing Truncation**: Does reading `--bytes 17:100000` safely truncate trailing incomplete sample bytes without throwing `numpy.frombuffer` buffer size errors?
- [ ] **Structured Format Dialogs**: Does opening a non-compliant `.mat` file show an informative `MatFileFormatError` dialog instead of calling `sys.exit(1)`?
- [ ] **Debian Package UTF-8 Size**: In `scripts/make_deb.py`, is `TarInfo.size` calculated with `len(content.encode('utf-8'))` rather than character count?
- [ ] **Linux Platform Themes**: Does the packaged Linux launcher unset `QT_QPA_PLATFORMTHEME` and `QT_STYLE_OVERRIDE` to avoid private Qt symbol collisions?

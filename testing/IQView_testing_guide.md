# IQView manual test guide

Use this as a walkthrough, not a dump of every commit. Each section is one sitting. Pass / fail is what you *see*, not what the code claims.

Current tree under test: `omernaf/IQView` @ 0.7.0 (2026-09-29).

---

## 0. What I need from you

Generate these into one folder (default `./iqview_testdata/`) by running [`testing/make_iqview_testdata.py`](make_iqview_testdata.py). If you already have real captures, map them onto the same roles.

| File | Why |
|---|---|
| `tone_10Msps_100MHz.32fc` | Single complex tone at **+1 MHz** IF with a low noise floor. Ground truth for markers, colormap dB/Hz, fit-to-screen, and stats. |
| `twotone_10Msps_100MHz.32fc` | Tones at **−2 MHz** and **+3 MHz** with a low noise floor. Filter isolation and freq-domain integrated power. |
| `chirp_10Msps_100MHz.32fc` | Linear chirp −4→+4 MHz over the whole file. Catches “spectrogram cuts short / chirp never reaches the end”. |
| `bursts_10Msps_100MHz.32fc` | 10 on/off bursts (200 ms total), 5 ms on / 15 ms off, tone at +1.5 MHz over a noise floor. Plugins, time markers, 1/T, multi-row period. |
| `qpsk_2Msps_915MHz.32fc` | Hanning-shaped QPSK, **8 sps**, 200 Hz CFO. Eye diagram + scatter + pre-transform operators. |
| `fm_1Msps_0Hz.32fc` | Complex FM with 1 kHz audio and ±5 kHz deviation. Instant-frequency / FM-detect / median filter. **fs exactly 1e6** — catches the 1 MHz sentinel bug. |
| `fm_real_48kHz.wav` | Real-valued FM wave (10 kHz carrier, 500 Hz audio, ±2 kHz deviation) at 48 kHz. Exercises the Hilbert-transform instantaneous-frequency path. |
| `same_signal.16tc` + `same_signal.32fc` | Identical waveform, two dtypes. Normalization / time-domain magnitude scale. |
| `headerjunk_10Msps_433MHz.bin` | 17-byte garbage header + `tone` payload (auto-detected fc = 433 MHz, ridge at **434 MHz**). Byte-offset CLI. |
| `no_params_in_name.32fc` | Same `tone` payload without `fs`/`fc` in the filename. Verifies fallback to Settings defaults or `-r`/`-c`. |
| `לכידה 10Msps 100MHz.32fc` | Filename with Hebrew characters and spaces. Verifies Unicode path handling in CLI and GUI. |
| `keysight_tone.mat` | Keysight-shaped `Y` (pre-scaled by $1/\sqrt{10}$), `XDelta`, `InputCenter`. |
| `bad.mat` | Random struct, no `Y`. Error-message path. |
| `pulse_period_2ms_10Msps_100MHz.32fc` | Narrow 50 µs pulse every **exactly 2 ms**. Multi-row “samples per row / start period”. |
| `audio_tone.wav` + `audio_tone.flac` | 1 kHz real tone, 48 kHz. Audio path + FLAC. |
| `audio_iq_interleaved.wav` | Interleaved `[I0, Q0, I1, Q1, ...]` mono WAV (`-t caudio` / `-t caud`), tone at **+2 kHz**. |
| `huge_20Msps_2400MHz.32fc` | ≥30 s at 20 Msps (generated with `--huge`, or any file that hurts RAM in full mode). Lazy vs full, large-popup warning. |
| Optional real files | One Tektronix `.r3f` (do not fake a header; the loader parses a 16 KB SignalVu frame). |

Also have ready:
- a second monitor if you have one (dock/undock)
- MATLAB with `matlab/iqview.m` on the path (only for the MATLAB section)
- the example plugins from `examples/plugins/`

---

## 1. Smoke: launch paths

1. `iqview` with no args → empty window, logo in title bar / taskbar, no crash.
2. `iqview -f iqview_testdata/tone_10Msps_100MHz.32fc` → console prints auto-detected **10 MHz** and **100 MHz**. Tone ridge sits at **101 MHz** (fc+1 MHz), not at 1 MHz and not mirrored.
3. Same file as a positional path: `iqview iqview_testdata/tone_10Msps_100MHz.32fc`.
4. Override autodetection: `iqview -f iqview_testdata/tone_10Msps_100MHz.32fc -r 5e6 -c 0` → ridge must move; title/side panel must show the override.
5. `iqview -n "kitchen sink" -f iqview_testdata/tone_10Msps_100MHz.32fc` → window title is that string.
6. Double-click the file in the file manager after `iqview --install-desktop`. App opens on that file, no extra terminal on Linux.
7. Open Recent after closing and reopening. Same file, same fs/fc.

Fail if: fs/fc stay at Settings defaults when the filename clearly encodes them; tone appears at the wrong place; logo missing.

---

## 2. Spectrogram truth tests (use the chirp + tone)

**Tone**
1. Fit to screen. The ridge is a straight horizontal line at 101 MHz.
2. Drag colormap min/max. Colorbar **dB/Hz** numbers move with the lines.
3. Place two frequency markers (`F`) bracketing the ridge: `Delta` reads the bracketed width in Hz/bins, and the right-side spectrum envelope shows the ridge many dB/Hz above the noise floor.
4. Grid on. Grid only dense in the zoomed region. Turn markers off — grid auto-hides if that setting is on.
5. Hold `Ctrl` and left-drag to box-zoom onto the tone, then press `Z` (or `Ctrl+Z`). You are back. Do it three times. History must not collapse.
6. **Right-click + drag** on the spectrogram to dynamically scale/zoom X and Y axes; **Middle-click (wheel button) + drag** to pan around the zoomed spectrogram. Confirm you cannot pan or zoom outside the signal's time/frequency bounds, scrollbars track live, and pressing `Z` undoes the right-drag zoom and middle-drag pan.

**Chirp (this one is mean on purpose)**
1. Open `chirp_10Msps_100MHz.32fc` in **full** mode: `iqview --full -f iqview_testdata/chirp_10Msps_100MHz.32fc`.
2. The chirp must start at the first column and die at the last column, −4 to +4 MHz (96 to 104 MHz). If the last 5–10% is empty, that is the old “cuts short” bug.
3. Switch to **lazy** (`--lazy` or Settings). Zoom the last 50 ms. The chirp is still there, sharp, not a stretched bitmap.
4. Change FFT size while zoomed. Image must recompute, not pixelate.
5. Enable BPF (`B`) around the chirp’s instantaneous band, then zoom. Resolution must survive the filter (old full-mode + filter bug).

**Waterfall**
1. Toggle waterfall. Time/frequency axes swap and stay labelled correctly.
2. Place a time marker and a freq marker before the toggle. They sit on the same signal feature after the toggle.
3. Overlays drawn in normal view still cover the same chirp after waterfall.
4. Right-click + drag scaling and middle-click + drag panning still respect the swapped axes and limits.

---

## 3. Lazy vs full vs huge file

1. Open `huge_20Msps_2400MHz.32fc` with `--full`. Watch RAM. If the machine starts swapping, that is already a finding.
2. Same file with `--lazy`. RAM stays flat-ish. Pan continuously left-right (via `Hold Space` + left-drag or middle-button + drag); sides should already be rendered (lazy prefetches left/right).
3. In lazy, zoom in, then zoom out past the previous view. The newly revealed area must paint, not stay blank.
4. Scrollbars: drag the bar, not the image. Spectrogram follows. (There was a “scrollbars don’t update image” era.)
5. Settings → switch the calculate-once vs calculate-on-view-change option. Repeat step 3 in both modes.

Outside the box: while lazy-panning the huge file, open Time Domain on a 20 ms slice (should be fine) then try a 2 s slice and expect the large-segment warning (>10M samples), not a freeze.

---

## 4. Filters

Use `twotone_10Msps_100MHz.32fc` (−2 MHz and +3 MHz, i.e. 98 MHz and 103 MHz).

1. Press `B` and draw a filter region around only the +3 MHz (103 MHz) tone, then toggle BPF (`[`). The 98 MHz ridge goes dark. Roll-off looks like a real filter, not a brick-wall slice.
2. Switch IIR type and enable FIR in Settings. Same band, different transition width.
3. Turn on BSF (`]`) on the 103 MHz tone instead. That ridge dies, the 98 MHz ridge lives.
4. Drag filter edges. Lock delta (`D`). Drag one edge from far away — the width stays constant, the pair does not teleport.
5. Set a filter center/offset in the table. The passband slides accordingly.
6. Double-click the filter button (or press `Backspace` in Filter mode) to clear the filter markers. Spectrogram returns to both tones.
7. Open Frequency Domain popup. BPF/BSF overlays exist there too (`B`, `[`, `]`) and filter the spectrum live.
8. Apply a filter, then change FFT / window / overlap. Spectrogram stays sharp in the zoomed viewport.

---

## 5. Markers — try to break the locks

1. Press `T` and place two time markers on a burst edge. Table row 1 is **Samples**, row 2 is **Time (sec)**. Click a value: the whole field selects so you can copy.
2. Type a new sample index while you are in zoom mode, not marker mode. Marker moves. (Old “table edit only works in marker mode” bug.)
3. Lock **Delta** (`D`). Drag left marker toward the file start fast. The pair slides until it *hits* the edge, then stops. It must not freeze 20 px early.
4. Lock **Center** (`C`). Drag. They open/close around the midpoint.
5. Lock a single marker (`1` or `2`). The other still moves.
6. Enable grid. Shadow lines are draggable. Delta lock + shadow drag must not teleport the pair.
7. Endless markers (`E` for time, `G` for freq): drop 6+. Drag the 5th. The 5th row updates, not the 1st. Values follow in real time.
8. Right-click → Clear All Markers (or double-click the marker mode button / press `Backspace`). Table empty, locks reset.
9. 1/T: enable 1/T in Settings if hidden, place two time markers 1 ms apart on `bursts_…`. 1/T reads ~1000 Hz.
10. Place markers, change FFT size. Markers stay on the same time/freq, not the same pixel.

Cursor checks: hover a marker → resize cursor; drag → resize cursor; zoom mode (`Hold Ctrl`) → cross cursor; move mode (`Hold Space`) → move cursor.

---

## 6. Stats box (Time & Frequency Domain popups)

1. Open Time Domain on `bursts_10Msps_100MHz.32fc` (or Frequency Domain on `tone_10Msps_100MHz.32fc`). Press `S` (Region Statistics mode) and place two bounds over a burst/tone, then move them over noise.
2. Switch between **Definition** (`Q`) and **Results** (`W`). Mean / median / min / max / 10th / 90th / 90−10 make sense: signal region ≫ noise region.
3. Toggle the 10th and 90th percentile checkboxes. Green/red dotted horizontal lines appear/disappear across the plot.
4. Units on the panel headers match the active plot (`dB` vs linear in Time Domain; `dBFS` vs `dB/Hz` in Frequency Domain).
5. Double-click the Region Statistics button (or press `Backspace` in Stats mode). Both the visual region/lines on the plot **and** all numeric fields in the Definition and Results tables clear completely.

---

## 7. Time domain popup

1. Two time markers around one burst in `bursts_10Msps_100MHz.32fc` → Time Domain popup.
2. Cycle plots using the toolbar buttons or `F1`–`F10` shortcuts: `magnitude [dB]`, `Real`, `Imaginary`, `instant frequency`, etc.
3. Settings → reorder/toggle active Time Domain plots, apply. Next popup follows the new order.
4. Zoom in (via `Hold Ctrl` box zoom or right-click drag); verify both X and Y zoom scrollbars appear and track. Press `Z` / `Ctrl+Z` to undo zoom.
5. Region Stats min/max indicators (red circle / green triangle) land on the true burst extrema.
6. `fm_1Msps_0Hz.32fc`: open Time Domain → `instant frequency`. The trace shows a clean 1 kHz sine wave between −5 kHz and +5 kHz. Adjust the median filter length in Settings; hash quiets down.
7. `fm_real_48kHz.wav`: open in IQView → Time Domain → `instant frequency`. Confirm the Hilbert-transform path recovers the 500 Hz sinusoidal modulation around the 10 kHz carrier.
8. `same_signal.16tc` vs `same_signal.32fc`: magnitude is comparable after normalization (`int16` is normalized to $[-1, 1]$, not left as raw counts up to $\pm 32767$).
9. Tear the tab off, drag to the second monitor, dock back. Spectrogram tab stays pinned at index 0.

---

## 8. Frequency domain / PSD

1. `twotone_10Msps_100MHz.32fc`, whole record → Frequency Domain.
2. Two peaks at 98 MHz (fc−2 MHz) and 103 MHz (fc+3 MHz).
3. Switch `magnitude [dBFS]` vs `PSD [dB/Hz]`. Y-axis label changes. Marker table header units change. The numeric text boxes stay strictly numeric (no embedded unit strings).
4. Zoom in on both X and Y axes; verify both horizontal and vertical zoom scrollbars appear and scroll smoothly.
5. In Region Statistics (`S`), select only the 103 MHz peak. `Integrated (dB)` power is close to that tone’s power and much higher than a noise-only band of the same width.
6. Pre-transform operators on `qpsk_2Msps_915MHz.32fc`:
   - `2nd Power` / `4th Power`: discrete carrier / symbol-rate lines show up (4th power produces a strong carrier spike at $4 \times \text{CFO}$).
   - `FM Demod` / `2nd Power FM`: produces a valid demodulated spectrum without crashing.
   - `Delay & Multiply`: baud-rate harmonic lines at multiples of $2\text{ MHz} / 8 = 250\text{ kHz}$.
7. Right-click export from this view: MAT / NPY / CSV of the *spectrum*, not the IQ. Open the CSV; first column is frequency.
8. Image export preview: “raw image” has no axes/markers; “plot with axes” has them. Dialog does not jump size when you toggle.

---

## 9. Eye diagram (QPSK file)

1. Mark ~20 ms of `qpsk_2Msps_915MHz.32fc` → Eye Diagram.
2. Type **8** in SPS (or toggle to Baud via `A` and type `250000`). Eye opens cleanly.
3. Use coarse/fine sliders. Offset slider walks the crossings left/right.
4. Switch plot modes (`F1`–`F5`: Real / Imag / Mag / Phase / Inst freq). No crash.
5. Drag the mini-overview handles to a narrower slice; the eye updates live.
6. Toggle SPS ↔ Baud (`A`). Baud and symbol-time readouts stay consistent with `fs / Nsps`.
7. Open a huge slice on purpose. Either the large-popup warning or the 500 k sample cap banner appears. App stays alive.

---

## 10. Scatter / constellation

1. Same QPSK slice → Scatter Plot.
2. Downsample **8**, walk the sub-symbol offset. Constellation tightens on the optimal symbol sampling instant and smears on the neighbours.
3. Coarse/fine phase sliders rotate the QPSK square; `Reset` (`A`) zeros phase and CFO.
4. Three-tier CFO sliders: the 200 Hz intentional CFO in `qpsk_2Msps_915MHz.32fc` should freeze into 4 stationary points using the fine/medium CFO sliders.
5. Trajectory on/off (`F2`), unit circle, I/Q crosshairs, point size.
6. Grid crosshairs stay off unless you enable them.
7. Dock / undock. Mini overview handles still work detached.

---

## 11. Multi-row spectrogram

File: `pulse_period_2ms_10Msps_100MHz.32fc` (pulse every 2 ms = 20,000 samples at 10 Msps).

1. Set rows to e.g. `4`, and set `Samples / Row` and `Period` to `20000` (2 ms). Pulses stack as a vertical column across all rows.
2. Change `Start Sample` by `10000` (half a period). The column shifts sideways by half a row.
3. Place time/frequency markers and a BPF. They appear across the rows in the right positions.
4. Zoom one row (via `Hold Ctrl` box-zoom or **Right-click + drag**); frequency and relative time zoom sync across all rows and survive changing the row count.
5. Pan across rows using `Hold Space` + left-drag or **Middle-click + drag**; all rows pan together smoothly.
6. Overlays drawn here survive going back to a single-row spectrogram (`Rows = 1`).

Outside the box: set `Period` to `19900` samples (1.99 ms). The pulse column slants diagonally across rows — confirming the period control is truly sample-indexed.

---

## 12. Overlays + plugins

1. Press `O` (Overlay mode) and draw one of each shape: `RECT`, `POLYGON`, `ELLIPSE`, `X_REGION`, `Y_REGION`, `LINE`, `HLINE`.
2. Hover: hover string shows. Drag handles. Lock one item in the table; it stops moving.
3. Export JSON. Metadata field present if you set one.
4. Clear all (`Backspace` in Overlay mode). Import the JSON. Geometry matches.
5. Press `P` (Plugins mode), load `examples/plugins/mark_view.py` → Run. Green dashed locked rectangle covers the current view.
6. Load `examples/plugins/detect_bursts.py` on `bursts_10Msps_100MHz.32fc` → Run (`mark_bursts`). Green start and red end vertical lines land on burst edges, not mid-noise. Zoom to a window containing 1–2 bursts (keeping burst duty cycle <50% of the visible window so the median stays in the noise floor) and run again: overlays are only added inside the visible slice.
7. Draw a `RECT` overlay spanning e.g. `0.03 s` to `0.17 s`, then load and run `examples/plugins/snap_to_grid.py`. Left/right edges snap to the nearest `0.1 s` grid lines (`0.0 s` and `0.2 s`).
8. Run `examples/plugins/detect_peaks.py` on `twotone_10Msps_100MHz.32fc`. Horizontal dashed lines land on 98 MHz and 103 MHz. Run it twice: you get additional overlays with no ID collision.
9. Load `examples/plugins/detect_bursts_2d.py` (which defines `PLUGIN_PARAMS`). Click **Config**, change `Threshold SNR (dB)` or `Min Duration (s)`, and click **Run**. Bounding-box detections update accordingly.
10. Verify that a plugin calling `result.update()` on another plugin’s overlay works, while `result.remove()` on a *user*-drawn overlay is ignored.
11. Launch from Python with a breakpoint inside a plugin (see §16). Debugger hits, you can inspect `samples` and `info`.

---

## 13. Files and nasty I/O

1. `keysight_tone.mat` — loads, window title uses the file name, ridge at **101 MHz** (`InputCenter + 1 MHz`) with the same power level as `tone_10Msps_100MHz.32fc`.
2. `bad.mat` — clear `MatFileFormatError` dialog / message, no unhandled traceback crash.
3. `audio_tone.wav` and `audio_tone.flac` — 1 kHz line, `fs = 48 kHz` read from the file header, not from Settings.
4. `iqview -t caudio -f iqview_testdata/audio_iq_interleaved.wav` — de-interleaves the mono `[I0, Q0, ...]` stream into complex IQ (`complex64`), showing a single clean tone at **+2 kHz** (not mirrored at −2 kHz).
5. Settings → add a custom extension (e.g. `.iq32` → `complex64`) and rename a `.32fc` file. Auto-type detection works.
6. `headerjunk_10Msps_433MHz.bin`:
   - `iqview -f iqview_testdata/headerjunk_10Msps_433MHz.bin -t complex64` → corrupted spectrum due to 17-byte misalignment (expected).
   - `iqview -f iqview_testdata/headerjunk_10Msps_433MHz.bin -t complex64 --bytes 17:` → clean tone at **434 MHz**.
   - `iqview -f iqview_testdata/headerjunk_10Msps_433MHz.bin -t complex64 --start-byte 0x11` → same clean tone at **434 MHz**.
   - `iqview -f iqview_testdata/headerjunk_10Msps_433MHz.bin -t complex64 --bytes 17:100000` → shorter ~1.25 ms file ($99,983\text{ bytes}$, intentionally not a multiple of 8 bytes), renders cleanly with no `numpy.frombuffer` alignment error.
7. stdin: `cat iqview_testdata/tone_10Msps_100MHz.32fc | iqview --stdin -t complex64 -r 10e6 -c 100e6`. All samples present (old “stdin drops the tail” bug).
8. `.r3f` if you have one: fc/fs come from the header, signal is baseband complex, not raw IF real.
9. `לכידה 10Msps 100MHz.32fc` (Hebrew + spaces): open from GUI and from CLI quoted path; auto-detects 10 MHz and 100 MHz.
10. `no_params_in_name.32fc`: Settings defaults apply unless you pass `-r` / `-c`.

---

## 14. Settings, theme, export, packaging

1. Dark / light toggle. Settings page, tables, scrollbars, plugin dialog all follow.
2. Change default colormap, marker color, zoom-box color, grid color, font scale. Apply. Restore defaults really restores.
3. **Keybinds & Tooltips**:
   - Hover over every toolbar/panel button in Spectrogram, Time Domain, Frequency Domain, Eye Diagram, and Scatter Plot: each tooltip displays its active shortcut in brackets (e.g. `[T]`, `[Hold Ctrl]`, `[Hold Space]`, `[F1]`).
   - Hold `Ctrl` or `Space`: switches to Zoom or Move mode while held, and automatically reverts to your previous marker/tool mode upon release.
   - Rebind a key in Settings → Keyboard and click Apply: the new key triggers the action and the button’s hover tooltip updates immediately.
   - Click **Reset All Keybinds to Default** in Settings → Keyboard: all shortcuts return to defaults.
4. Export marked IQ from the tone file. Reload the export; it is the same tone, same fs/fc if the format carries them.
5. Export image of spectrogram with preview. Logo/icon present on the export menu.
6. Check-for-updates: with network on, it does not hitch the UI at startup. Offline, it fails quietly.
7. `iqview --install-desktop` / `--uninstall-desktop` / `--install-mat`. After uninstall, double-click no longer opens IQView.
8. Linux only: install the `.deb` on a clean VM if you have one. App starts; missing `libxcb-cursor0` is the classic failure mode to watch.
9. Offline wheel path only if you care about air-gapped install this round.

---

## 15. MATLAB

```matlab
fs = 10e6; t = (0:fs*0.05-1)/fs;
x = exp(2j*pi*1e6*t);
iqview(x, fs, 100e6, 1024, Title="from-matlab")
```

1. Window opens, title set, tone at 101 MHz, no truncated stdin.
2. Repeat with `ForceTempFile=true` (lazy-friendly path). Same picture.
3. Batch: call `iqview` twice on two vectors. Two windows, or documented single-instance behaviour — pick it and stick to it.

---

## 16. Python API

 Note: `iqview.view()` blocks in the Qt event loop and exits when the window closes, so run each call separately:

```bash
# 1. Pass a NumPy array directly
python -c "import numpy as np, iqview; fs=10e6; t=np.arange(int(fs*0.05))/fs; x=np.exp(2j*np.pi*1e6*t); iqview.view(x, fs=fs, fc=100e6, name='api-tone')"

# 2. Pass a file path with lazy=True / False override
python -c "import iqview; iqview.view('iqview_testdata/bursts_10Msps_100MHz.32fc', lazy=True)"
```

1. Array path and file path both work.
2. `lazy=True/False` on a file path overrides Settings for that session without altering the saved QSettings default.

---

## 17. Overlap MAX + MATLAB-like traces

1. On the chirp, set overlap `MAX` or `100`. Time resolution jumps; transients look taller.
2. Time/freq/eye/scatter traces are MATLAB blue (`#0072BD`) and thin (`0.5` width). Markers/grids unchanged.

---

## 18. Suggested order for one long evening

1. §1 smoke + generate files.  
2. §2 chirp + §3 huge (the two that find rendering bugs).  
3. §4–6 filters/markers/stats (interaction bugs).  
4. §7–10 popups.  
5. §11–12 multi-row + plugins.  
6. §13 nasty files.  
7. §14–17 polish / API.

Tick the file name and the mode (`lazy`/`full`) on every fail. Most of the old bugs only exist in one mode.

---

## Appendix — Generating the test corpus

Use [`testing/make_iqview_testdata.py`](make_iqview_testdata.py) to generate all synthetic test files:

```bash
# Standard corpus (~50 MB total, writes to ./iqview_testdata)
python testing/make_iqview_testdata.py

# Custom output folder + 30-second 20 Msps huge file (~4.5 GiB)
python testing/make_iqview_testdata.py --out ~/iqview_testdata --huge

# Shorter huge file (e.g. 10 seconds, ~1.5 GiB)
python testing/make_iqview_testdata.py --huge-seconds 10
```

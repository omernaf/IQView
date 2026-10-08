---
name: iqview-testing-qa
description: >-
  Generating synthetic test datasets, running automated test suites, regression checking,
  and executing the 18-step manual testing walkthrough for IQView. Use when writing tests,
  generating testdata in iqview_testdata, or performing pre-release quality assurance.
---

# IQView Testing & Quality Assurance Skill

This skill defines the testing procedures, synthetic signal generation, test corpus roles, and verification protocols for IQView.

---

## 1. Generating the Synthetic Test Corpus

Synthetic test datasets are generated deterministically using [`testing/make_iqview_testdata.py`](file:///d:/Projects/IQView/testing/make_iqview_testdata.py):

```bash
# Standard test corpus (~50 MB total in ./iqview_testdata/)
python testing/make_iqview_testdata.py

# Custom directory + generate huge 30-second 20 Msps file (~4.5 GiB)
python testing/make_iqview_testdata.py --out ./iqview_testdata --huge
```

### 1.1 Test Corpus Roles & Ground Truth
| File | Role / Ground Truth | Verification Target |
| :--- | :--- | :--- |
| `tone_10Msps_100MHz.32fc` | CW tone at **101 MHz** ($f_c + 1\text{ MHz}$) | Marker alignment, dB/Hz colormap calibration, fit-to-screen. |
| `twotone_10Msps_100MHz.32fc` | Tones at **98 MHz** and **103 MHz** | BPF/BSF isolation, integrated channel power. |
| `chirp_10Msps_100MHz.32fc` | Linear sweep 96 to 104 MHz over file | Spectrogram bounds, full vs. lazy rendering continuity. |
| `bursts_10Msps_100MHz.32fc` | 10 bursts (5 ms on / 15 ms off) at 101.5 MHz | Burst energy detection, 1/T period markers, multi-row layout. |
| `qpsk_2Msps_915MHz.32fc` | Hanning-shaped QPSK, 8 SPS, 200 Hz CFO | Eye diagram symbol timing, constellation CFO despinning. |
| `fm_1Msps_0Hz.32fc` | Complex FM, 1 kHz audio, ±5 kHz deviation ($f_s=1\text{ MHz}$) | Instantaneous frequency trace, median filter smoothing. |
| `fm_real_48kHz.wav` | Real-valued 48 kHz FM recording | Hilbert analytic signal conversion + HPF DC blocking. |
| `headerjunk_10Msps_433MHz.bin` | 17-byte unaligned header + tone at 434 MHz | Byte slicing flags (`--bytes 17:` / `--start-byte 0x11`). |
| `keysight_tone.mat` | Keysight `Y`, `XDelta`, `InputCenter` | Dynamic MAT loading, window title, `.mat.overlays`. |
| `bad.mat` | Corrupted MAT struct missing required fields | Structured `MatFileFormatError` message popup. |
| `pulse_period_2ms_10Msps_100MHz.32fc` | 50 µs pulse every exactly 2.0 ms | Multi-row periodic stacking (`Period = 20000`). |

---

## 2. Core Testing Principles

### 2.1 Dual-Mode Mandate: Lazy vs. Full
Historically, critical regressions have manifested in only one mode:
- Always test new features under **Lazy Mode** (`--lazy`) and **Full Mode** (`--full`).
- Specifically verify zooming in and out while filters are active; verify re-calculation resolution.

### 2.2 Headless Automated Testing
For automated CI or script runs without displaying GUI windows:
```powershell
$env:QT_QPA_PLATFORM = "offscreen"
pytest testing/
```

### 2.3 Large Segment Safety Check
Any action opening $>10,000,000$ samples in an analysis tab must prompt a confirmation dialog to protect against out-of-memory crashes.

---

## 3. The 18-Step Manual Test Protocol

When preparing a major release, refer to [`testing/IQView_testing_guide.md`](file:///d:/Projects/IQView/testing/IQView_testing_guide.md):
1. Smoke launch paths & CLI overrides.
2. Spectrogram ground truth (tone + chirp).
3. Lazy vs. Full vs. Huge memory profiling.
4. BPF / BSF zero-phase filter checks.
5. Marker locking (Delta, Center, Boundary slides).
6. Region statistics (10th / 90th percentile indicators).
7. Time domain popup (Instant frequency, real signals).
8. Frequency domain popup (PSD dB/Hz, pre-transforms).
9. Eye diagram (Fractional SPS, Baud Rate toggle).
10. Scatter plot (Downsampling, 3-tier CFO tuning).
11. Multi-row stacked view.
12. Overlays & plugin execution.
13. Formats & byte slicing (`.r3f`, `.mat`, audio, stdin).
14. Settings, themes, keybind tooltips, packaging.
15. MATLAB API interoperability (`matlab/iqview.m`).
16. Python API (`iqview.view()`).
17. Maximum Overlap (`MAX`) resolution & MATLAB blue styling.
18. Clean environment verification.

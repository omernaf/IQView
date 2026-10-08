# IQView File Format & Ingestion Specifications

This document provides exhaustive format specifications, header mappings, and parser algorithms implemented in IQView.

---

## 1. Binary IQ Formats & Mapping

Defined in [`DTYPE_MAP`](file:///d:/Projects/IQView/iqview/utils/helpers.py):
- `.32fc`, `.cf32`, `.iq`, `.bin` $\rightarrow$ `complex64` (8 bytes per sample: 4-byte float I, 4-byte float Q).
- `.16tc`, `.cs16`, `.16sc` $\rightarrow$ `int16` (4 bytes per complex sample: 2-byte signed int I, 2-byte signed int Q).
  - Scaled by $1.0 / 32768.0$ to normalize amplitude to $[-1.0, 1.0]$.
- `.32f` $\rightarrow$ `float32` (4 bytes per real sample).
- `.64fc` $\rightarrow$ `complex128` (16 bytes per complex sample: 8-byte float I, 8-byte float Q).

---

## 2. Dynamic Filename Regex Patterns

Function `detect_params_from_filename(filename)` parses strings using case-insensitive regex:

### Sample Rate Extraction
Matches numbers followed by `ksps`, `msps`, `gsps`, `sps`, `khz`, `mhz`, `ghz`, `hz`:
- Pattern: `r'(?:^|[_\-\s])(\d+(?:\.\d+)?)\s*([kmg]?)(?:sps|hz|sa/s)'`
- Examples:
  - `_10Msps_` $\rightarrow 10 \times 10^6\text{ Hz}$
  - `_500ksps_` $\rightarrow 500 \times 10^3\text{ Hz}$

### Center Frequency Extraction
Matches frequency tags:
- Pattern: `r'(?:^|[_\-\s])(?:fc[_\-\s]*)?(\d+(?:\.\d+)?)\s*([kmg]?)hz'`
- Examples:
  - `_433MHz` $\rightarrow 433 \times 10^6\text{ Hz}$
  - `_2.4GHz` $\rightarrow 2.4 \times 10^9\text{ Hz}$

---

## 3. Tektronix RSA `.r3f` Specification

- **Header Size**: Exactly 16,384 bytes (16 KB) frame header preceding raw ADC data.
- **Header Fields**:
  - `CenterFrequency` ($F_c$): Hardware center frequency (float64).
  - `SampleRate` ($F_{s,\text{real}}$): Real ADC clock rate (float64).
  - `IFCenterFrequency` ($F_{c,\text{IF}}$): Intermediate frequency of downconverted IF analog input (float64).
  - `VoltageScaling`: Factor mapping 16-bit integer ADC counts to true Volts.
- **Baseband Conversion Algorithm**:
  1. Read 16-bit ADC integers: $x_{\text{adc}}[n]$.
  2. Scale by `VoltageScaling`: $x_{\text{real}}[n]$.
  3. Digital Down-Conversion (DDC) to baseband:
     $$x_{\text{ddc}}[n] = x_{\text{real}}[n] \cdot e^{-j 2\pi (F_{c,\text{IF}} / F_{s,\text{real}}) n}$$
  4. Decimate by 2:
     $$x_{\text{baseband}}[m] = x_{\text{ddc}}[2m], \quad F_{s,\text{complex}} = F_{s,\text{real}} / 2$$

---

## 4. Keysight `.mat` Specification

MATLAB v5/v7 MAT-file parsed via `scipy.io.loadmat`:
- **Required Variables**:
  - `Y`: Complex sample vector (dimension $N \times 1$ or $1 \times N$).
  - `XDelta`: Sample interval in seconds ($1/f_s$).
  - `InputCenter`: RF center frequency in Hz ($f_c$).
- **Scaling**:
  - Keysight instruments store sample power scaled relative to $50\,\Omega$. Samples are divided by $\sqrt{10}$ upon ingestion to standardize RMS power.
- **Sidecars**:
  - If `<capture>.mat` has a companion `<capture>.mat.overlays` JSON file, overlays are automatically imported into the Overlays table.

---

## 5. Audio Container Formats (`soundfile`)

Supported formats: `.wav`, `.flac`, `.ogg`, `.aiff`, `.au`, `.w64`, `.rf64`, `.caf`, `.sd2`.
- **Mode 1 (`-t aud` / `-t audio`)**:
  - Multi-channel audio is averaged to mono: $x[n] = \frac{1}{C} \sum_{c=1}^C x_c[n]$.
- **Mode 2 (`-t caudio` / `-t caud` Interleaved Complex IQ)**:
  - Deinterleaved as:
    $$I[m] = x_{\text{mono}}[2m], \quad Q[m] = x_{\text{mono}}[2m + 1]$$
  - Trailing odd samples are dropped safely.

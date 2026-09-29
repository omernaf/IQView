#!/usr/bin/env python3
"""Generate the IQView manual-test corpus.

Writes into ./iqview_testdata by default.

    python testing/make_iqview_testdata.py
    python testing/make_iqview_testdata.py --out ~/iqview_testdata --huge
    python testing/make_iqview_testdata.py --huge-seconds 10

Needs numpy. Optional:
    scipy      -> Keysight-style .mat + bad.mat
    soundfile  -> FLAC (otherwise tries ffmpeg)
    ffmpeg     -> FLAC fallback
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------

def write_interleaved_f32(path: Path, x: np.ndarray) -> None:
    """Interleaved float32 IQ (I0 Q0 I1 Q1 …). IQView complex64 on disk."""
    x = np.asarray(x, dtype=np.complex64).reshape(-1)
    inter = np.empty(x.size * 2, dtype=np.float32)
    inter[0::2] = x.real
    inter[1::2] = x.imag
    path.write_bytes(inter.tobytes())


def write_int16_iq(path: Path, x: np.ndarray, scale: float = 30000.0) -> None:
    x = np.asarray(x, dtype=np.complex64).reshape(-1)
    inter = np.empty(x.size * 2, dtype=np.float32)
    inter[0::2] = x.real
    inter[1::2] = x.imag
    pcm = np.clip(inter * scale, -32767, 32767).astype(np.int16)
    path.write_bytes(pcm.tobytes())


def write_wav_mono_s16(path: Path, x: np.ndarray, fs: int) -> None:
    pcm = np.clip(np.asarray(x, dtype=np.float64) * 32767.0, -32767, 32767).astype(np.int16)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(fs))
        w.writeframes(pcm.tobytes())


def write_wav_interleaved_iq_s16(path: Path, iq: np.ndarray, fs: int) -> None:
    """Write complex IQ as a 1-channel WAV with interleaved [I0, Q0, I1, Q1, ...] samples.

    Matches IQView's `load_audio_file(..., complex_iq=True)` (`-t caudio` / `-t caud`),
    which reads a mono stream and de-interleaves even indices as I and odd indices as Q.
    """
    iq = np.asarray(iq, dtype=np.complex64).reshape(-1)
    inter = np.empty(iq.size * 2, dtype=np.float64)
    inter[0::2] = iq.real
    inter[1::2] = iq.imag
    pcm = np.clip(inter * 32767.0, -32767, 32767).astype(np.int16)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(fs))
        w.writeframes(pcm.tobytes())


def maybe_write_flac(wav_path: Path, flac_path: Path) -> str:
    try:
        import soundfile as sf

        data, fs = sf.read(str(wav_path), always_2d=False)
        sf.write(str(flac_path), data, fs, format="FLAC")
        return "soundfile"
    except Exception:
        pass
    ffmpeg = _which("ffmpeg")
    if ffmpeg:
        r = subprocess.run(
            [ffmpeg, "-y", "-i", str(wav_path), "-c:a", "flac", str(flac_path)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and flac_path.exists():
            return "ffmpeg"
    return ""


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------

def awgn(n: int, std: float, rng: np.random.Generator) -> np.ndarray:
    """Complex circular AWGN with per-component standard deviation `std`."""
    if std <= 0.0:
        return np.zeros(n, dtype=np.complex64)
    return (
        rng.normal(0.0, std, n) + 1j * rng.normal(0.0, std, n)
    ).astype(np.complex64)


def cw(fs: float, n: int, f: float, amp: float = 1.0) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / fs
    return (amp * np.exp(2j * np.pi * f * t)).astype(np.complex64)


def linear_chirp(fs: float, n: int, f0: float, f1: float, amp: float = 1.0) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / fs
    # phase = 2π ∫ f(t) dt  with f(t) = f0 + (f1-f0) t/T
    T = t[-1] if n > 1 else 1.0 / fs
    k = (f1 - f0) / T
    phase = 2.0 * np.pi * (f0 * t + 0.5 * k * t * t)
    return (amp * np.exp(1j * phase)).astype(np.complex64)


def burst_train(
    fs: float,
    n: int,
    f: float,
    on_s: float,
    off_s: float,
    amp: float = 0.7,
    noise_std: float = 1e-3,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    if rng is None:
        rng = np.random.default_rng(42)
    out = awgn(n, noise_std, rng)
    on = int(round(on_s * fs))
    period = int(round((on_s + off_s) * fs))
    if on <= 0 or period <= on:
        raise ValueError("bad burst timing")
    tone = cw(fs, on, f, amp)
    for i in range(0, n - on, period):
        out[i : i + on] += tone
    return out


def pulse_train(fs: float, n: int, f: float, width_s: float, period_s: float, amp: float = 0.8) -> np.ndarray:
    out = np.zeros(n, dtype=np.complex64)
    pw = max(1, int(round(width_s * fs)))
    period = int(round(period_s * fs))
    tone = cw(fs, pw, f, amp)
    for i in range(0, n - pw, period):
        out[i : i + pw] = tone
    return out


def qpsk_rrcish(fs: float, sps: int, nsym: int, cfo_hz: float = 200.0, amp: float = 0.4, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 4, nsym)
    sym = np.exp(1j * (np.pi / 4.0 + bits * np.pi / 2.0)).astype(np.complex64)
    up = np.zeros(nsym * sps, dtype=np.complex64)
    up[::sps] = sym
    # short Hanning pulse — enough to open an eye cleanly
    span = sps * 2
    ker = np.hanning(span).astype(np.float64)
    ker /= ker.sum()
    shaped = np.convolve(up, ker, mode="same").astype(np.complex64)
    n = shaped.size
    t = np.arange(n, dtype=np.float64) / fs
    shaped *= np.exp(2j * np.pi * cfo_hz * t).astype(np.complex64)
    return (amp * shaped).astype(np.complex64)


def fm_complex(fs: float, n: int, audio_hz: float, deviation_hz: float, amp: float = 0.5) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / fs
    audio = np.sin(2.0 * np.pi * audio_hz * t)
    phase = 2.0 * np.pi * np.cumsum(deviation_hz * audio) / fs
    return (amp * np.exp(1j * phase)).astype(np.complex64)


def fm_real(fs: float, n: int, carrier_hz: float, audio_hz: float, deviation_hz: float, amp: float = 0.5) -> np.ndarray:
    """Real-valued FM wave around `carrier_hz` for testing the Hilbert instantaneous-frequency path."""
    t = np.arange(n, dtype=np.float64) / fs
    audio = np.sin(2.0 * np.pi * audio_hz * t)
    inst_freq = carrier_hz + deviation_hz * audio
    phase = 2.0 * np.pi * np.cumsum(inst_freq) / fs
    return amp * np.cos(phase)


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------

def write_keysight_mat(path: Path, y: np.ndarray, fs: float, fc: float) -> None:
    from scipy.io import savemat

    y = np.asarray(y, dtype=np.complex64).reshape(1, -1)
    # IQView's Keysight loader computes: samples = Y * sqrt(10).
    # Divide by sqrt(10) on save so the loaded waveform matches `y` in amplitude.
    savemat(
        str(path),
        {
            "Y": y / np.sqrt(10.0),
            "XDelta": np.array([[1.0 / fs]], dtype=np.float64),
            "InputCenter": np.array([[fc]], dtype=np.float64),
        },
        do_compression=False,
    )


def generate(out: Path, huge_seconds: float | None) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    rng = np.random.default_rng(12345)

    # --- 10 Msps family (200 ms keeps the corpus small) ---
    fs10 = 10e6
    n10 = int(fs10 * 0.2)

    tone = cw(fs10, n10, 1e6, 0.5) + awgn(n10, 1e-3, rng)
    write_interleaved_f32(out / "tone_10Msps_100MHz.32fc", tone)
    notes.append("tone_10Msps_100MHz.32fc  fs=10e6  fc=100e6  IF=+1e6 (+noise floor)")

    twotone = cw(fs10, n10, -2e6, 0.4) + cw(fs10, n10, 3e6, 0.4) + awgn(n10, 1e-3, rng)
    write_interleaved_f32(out / "twotone_10Msps_100MHz.32fc", twotone)
    notes.append("twotone_10Msps_100MHz.32fc  IF=-2e6 and +3e6 (+noise floor)")

    chirp = linear_chirp(fs10, n10, -4e6, 4e6, 0.5)
    write_interleaved_f32(out / "chirp_10Msps_100MHz.32fc", chirp)
    notes.append("chirp_10Msps_100MHz.32fc  IF=-4e6 → +4e6 over the whole file")

    bursts = burst_train(fs10, n10, 1.5e6, on_s=0.005, off_s=0.015, amp=0.7, noise_std=1e-3, rng=rng)
    write_interleaved_f32(out / "bursts_10Msps_100MHz.32fc", bursts)
    notes.append("bursts_10Msps_100MHz.32fc  5 ms on / 15 ms off @ +1.5e6 (+noise floor)")

    pulses = pulse_train(fs10, n10, 0.5e6, width_s=50e-6, period_s=2e-3, amp=0.8)
    write_interleaved_f32(out / "pulse_period_2ms_10Msps_100MHz.32fc", pulses)
    notes.append("pulse_period_2ms_10Msps_100MHz.32fc  50 us pulse every 2 ms")

    # dtype pair (50 ms)
    n_pair = int(fs10 * 0.05)
    pair = cw(fs10, n_pair, 0.5e6, 0.2)
    write_interleaved_f32(out / "same_signal.32fc", pair)
    write_int16_iq(out / "same_signal.16tc", pair)
    notes.append("same_signal.32fc / same_signal.16tc  identical waveform")

    # 17-byte junk header + tone payload
    payload = (out / "tone_10Msps_100MHz.32fc").read_bytes()
    header = b"HEADERJUNK!!!!!!!"[:17]
    assert len(header) == 17
    (out / "headerjunk_10Msps_433MHz.bin").write_bytes(header + payload)
    notes.append("headerjunk_10Msps_433MHz.bin  skip 17 bytes  (--bytes 17: or --start-byte 0x11, tone @ 434 MHz)")

    # file whose name does NOT encode fs/fc
    write_interleaved_f32(out / "no_params_in_name.32fc", tone)
    notes.append("no_params_in_name.32fc  same as tone, no fs/fc in the filename")

    # Hebrew + spaces in the filename
    heb = out / "לכידה 10Msps 100MHz.32fc"
    write_interleaved_f32(heb, tone)
    notes.append(f"{heb.name}  Hebrew + spaces, same as tone")

    # --- QPSK 2 Msps ---
    fs_q, sps = 2e6, 8
    qpsk = qpsk_rrcish(fs_q, sps=sps, nsym=4000, cfo_hz=200.0, amp=0.4)
    write_interleaved_f32(out / "qpsk_2Msps_915MHz.32fc", qpsk)
    notes.append("qpsk_2Msps_915MHz.32fc  fs=2e6  fc=915e6  ~8 sps  CFO=200 Hz")

    # --- FM at exactly 1 MHz (the old 1e6 bug) ---
    fs_fm = 1_000_000
    n_fm = int(fs_fm * 0.2)
    fm = fm_complex(fs_fm, n_fm, audio_hz=1e3, deviation_hz=5e3, amp=0.5)
    write_interleaved_f32(out / "fm_1Msps_0Hz.32fc", fm)
    notes.append("fm_1Msps_0Hz.32fc  fs==1e6 exactly  1 kHz audio  5 kHz deviation (complex FM)")

    # --- audio ---
    sr_a = 48000
    t_a = np.arange(sr_a, dtype=np.float64) / sr_a
    audio_tone = 0.3 * np.sin(2.0 * np.pi * 1000.0 * t_a)
    write_wav_mono_s16(out / "audio_tone.wav", audio_tone, sr_a)
    notes.append("audio_tone.wav  48 kHz mono  1 kHz")

    # Real-valued FM audio WAV for testing Hilbert-transform instantaneous frequency
    real_fm_wav = fm_real(sr_a, sr_a, carrier_hz=10000.0, audio_hz=500.0, deviation_hz=2000.0, amp=0.4)
    write_wav_mono_s16(out / "fm_real_48kHz.wav", real_fm_wav, sr_a)
    notes.append("fm_real_48kHz.wav  48 kHz mono real FM (10 kHz carrier, 500 Hz mod, ±2 kHz dev)")

    # Interleaved [I0, Q0, I1, Q1, ...] in a mono WAV for `-t caudio` / `-t caud`
    iq = 0.3 * np.exp(2j * np.pi * 2000.0 * t_a)
    write_wav_interleaved_iq_s16(out / "audio_iq_interleaved.wav", iq, sr_a)
    notes.append("audio_iq_interleaved.wav  interleaved mono I/Q  open with -t caudio (tone @ +2 kHz)")

    flac_how = maybe_write_flac(out / "audio_tone.wav", out / "audio_tone.flac")
    if flac_how:
        notes.append(f"audio_tone.flac  via {flac_how}")
    else:
        notes.append("audio_tone.flac  SKIPPED (install soundfile or ffmpeg)")

    # --- mat ---
    try:
        write_keysight_mat(out / "keysight_tone.mat", cw(fs10, n_pair, 1e6, 0.5), fs10, 100e6)
        from scipy.io import savemat

        savemat(str(out / "bad.mat"), {"nope": np.arange(10)})
        notes.append("keysight_tone.mat  Y/sqrt(10), XDelta=1/fs, InputCenter=100e6")
        notes.append("bad.mat  no Y — should error cleanly")
    except Exception as exc:
        notes.append(f"keysight_tone.mat / bad.mat  SKIPPED ({exc})")

    # --- huge (optional) ---
    if huge_seconds and huge_seconds > 0:
        fs_h = 20e6
        n_h = int(fs_h * huge_seconds)
        path = out / "huge_20Msps_2400MHz.32fc"
        chunk = 2_000_000
        with path.open("wb") as f:
            done = 0
            while done < n_h:
                m = min(chunk, n_h - done)
                t = (np.arange(m, dtype=np.float64) + done) / fs_h
                x = (0.3 * np.exp(2j * np.pi * 1e6 * t)).astype(np.complex64)
                inter = np.empty(m * 2, dtype=np.float32)
                inter[0::2] = x.real
                inter[1::2] = x.imag
                f.write(inter.tobytes())
                done += m
        mb = path.stat().st_size / (1024 * 1024)
        notes.append(f"huge_20Msps_2400MHz.32fc  {huge_seconds:g}s @ 20 Msps  ({mb:.1f} MiB)  IF=+1e6")
    else:
        notes.append("huge_20Msps_2400MHz.32fc  SKIPPED (pass --huge)")

    notes.append(".r3f  NOT generated — needs a real Tektronix SignalVu capture")
    return notes


def main() -> int:
    p = argparse.ArgumentParser(description="Build IQView manual-test files")
    p.add_argument("--out", type=Path, default=Path("iqview_testdata"), help="output folder")
    p.add_argument("--huge", action="store_true", help="also write a 30 s 20 Msps file (~4.5 GiB)")
    p.add_argument("--huge-seconds", type=float, default=None, help="huge-file length in seconds (implies --huge)")
    args = p.parse_args()

    huge_s = args.huge_seconds
    if huge_s is None and args.huge:
        huge_s = 30.0

    print(f"numpy {np.__version__}")
    print(f"writing → {args.out.resolve()}")
    notes = generate(args.out, huge_s)
    manifest = args.out / "MANIFEST.txt"
    manifest.write_text("\n".join(notes) + "\n", encoding="utf-8")
    print()
    for line in notes:
        print(" ", line)
    print()
    print("open examples:")
    print("  iqview -f", args.out / "tone_10Msps_100MHz.32fc")
    print("  iqview --full -f", args.out / "chirp_10Msps_100MHz.32fc")
    print("  iqview -t complex64 --bytes 17: -f", args.out / "headerjunk_10Msps_433MHz.bin")
    print("  iqview -t caudio -f", args.out / "audio_iq_interleaved.wav")
    return 0


if __name__ == "__main__":
    sys.exit(main())

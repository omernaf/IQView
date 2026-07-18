"""detect_bursts_2d.py — IQView plugin

Detects 2D energy bursts (time and frequency) in the current spectrogram view
and draws rectangular bounding boxes around them.

Usage
-----
In IQView: Plugins → Load Plugin… → select this file → Plugins → ▶ Detect Bursts 2D
"""

from __future__ import annotations
import numpy as np
import scipy.ndimage

# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------
PLUGIN_NAME        = "Detect Bursts 2D"
PLUGIN_DESCRIPTION = "Detects 2D energy bursts (time & frequency) and marks them with rectangular bounding boxes"

# ---------------------------------------------------------------------------
# Configurable UI parameters
# ---------------------------------------------------------------------------
PLUGIN_PARAMS = {
    "threshold_db": {
        "type": "float",
        "default": 15.0,
        "label": "Threshold SNR (dB)",
        "tooltip": "Power threshold in dB above the background noise floor for marking a burst"
    },
    "nfft": {
        "type": "int",
        "default": 512,
        "label": "FFT Size",
        "tooltip": "FFT size for spectrogram calculation"
    },
    "overlap_percent": {
        "type": "float",
        "default": 50.0,
        "label": "Overlap (%)",
        "tooltip": "Overlap between successive FFT windows (0% to 99%)"
    },
    "min_burst_duration": {
        "type": "float",
        "default": 0.0005,
        "label": "Min Duration (s)",
        "tooltip": "Minimum duration of a burst in seconds"
    },
    "min_burst_bandwidth": {
        "type": "float",
        "default": 1000.0,
        "label": "Min Bandwidth (Hz)",
        "tooltip": "Minimum bandwidth of a burst in Hz"
    }
}

# ---------------------------------------------------------------------------
# Tuning fallback parameters (used if run without UI configuration)
# ---------------------------------------------------------------------------
NFFT = 512
OVERLAP_PERCENT = 50.0
THRESHOLD_DB = 15.0
MIN_BURST_DURATION = 0.0005
MIN_BURST_BANDWIDTH = 1000.0
MAX_OVERLAYS = 100

# Morphological filters to group adjacent/close signals together
CLOSE_TIME_BINS = 2          # Dilation/closing width in time-bins
CLOSE_FREQ_BINS = 2          # Dilation/closing width in frequency-bins

# Visual styling
MIN_SNR_COLOR = 10.0         # SNR (dB) for minimum (cool) color coding
MAX_SNR_COLOR = 40.0         # SNR (dB) for maximum (hot) color coding

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
from iqview import PluginResult
from iqview.overlays import Rect

def get_snr_color(snr: float, min_snr: float, max_snr: float) -> str:
    """Map SNR (dB) to a cool neon gradient (cyan -> purple -> pink)."""
    t = (snr - min_snr) / (max_snr - min_snr + 1e-9)
    t = max(0.0, min(1.0, t))
    
    # Cool neon cyan (#00f3ff) -> purple/indigo (#7f79bf) -> hot neon pink/magenta (#ff007f)
    r = int(0 + t * 255)
    g = int(243 * (1.0 - t))
    b = int(255 * (1.0 - t) + t * 127)
    
    return f"#{r:02x}{g:02x}{b:02x}"

def run(samples: np.ndarray, info: dict) -> PluginResult:
    """
    Parameters
    ----------
    samples : np.ndarray (complex64)
        IQ samples for the currently visible time window.
    info : dict
        {sample_rate, center_freq, t_start, t_end, f_start, f_end, overlays, params}
    """
    if samples is None or len(samples) < 16:
        return PluginResult()

    # Safety guard: prevent hanging the app on massive file sections
    if len(samples) > 50_000_000:
        samples = samples[:50_000_000]

    # Read configuration parameters passed from the UI (or fall back to defaults)
    params = info.get("params", {})
    threshold_db = params.get("threshold_db", THRESHOLD_DB)
    nfft_param = int(params.get("nfft", NFFT))
    overlap_param = params.get("overlap_percent", OVERLAP_PERCENT)
    min_burst_duration = params.get("min_burst_duration", MIN_BURST_DURATION)
    min_burst_bandwidth = params.get("min_burst_bandwidth", MIN_BURST_BANDWIDTH)

    sample_rate = info["sample_rate"]
    center_freq = info["center_freq"]
    t_start     = info["t_start"]
    f_start     = info["f_start"]
    f_end       = info["f_end"]

    # 1. Determine NFFT and step size dynamically to keep computation fast
    MAX_SPECTROGRAM_ROWS = 2000
    nfft = nfft_param
    if len(samples) < nfft:
        # Reduce NFFT to a power of 2 smaller than len(samples)
        nfft = 2 ** int(np.log2(len(samples)))
        if nfft < 16:
            return PluginResult()

    overlap = int(nfft * (overlap_param / 100.0))
    step_size = max(1, nfft - overlap)

    num_blocks = (len(samples) - nfft) // step_size + 1
    if num_blocks > MAX_SPECTROGRAM_ROWS:
        # Scale step size up to bound total number of FFT blocks
        step_size = (len(samples) - nfft) // (MAX_SPECTROGRAM_ROWS - 1)
        step_size = max(1, step_size)
        num_blocks = (len(samples) - nfft) // step_size + 1

    # 2. Compute 2D Spectrogram in dB using fast strided view
    itemsize = samples.itemsize
    from numpy.lib.stride_tricks import as_strided
    
    try:
        blocks = as_strided(
            samples,
            shape=(num_blocks, nfft),
            strides=(step_size * itemsize, itemsize),
            writeable=False
        )
    except Exception:
        # Fallback if striding fails for memory alignment or other reasons
        blocks = np.array([samples[i*step_size : i*step_size + nfft] for i in range(num_blocks)])

    window = np.hanning(nfft)
    windowed = blocks * window
    fft_out = np.fft.fft(windowed, n=nfft, axis=1)
    fft_shifted = np.fft.fftshift(fft_out, axes=1)
    
    # Avoid zero logs
    spectrogram_db = 20.0 * np.log10(np.abs(fft_shifted) + 1e-12)

    # 3. Filter bins to only target the visible frequency window
    # Frequencies mapped to fftshifted bins
    bin_freqs = center_freq + (np.arange(nfft) - nfft / 2) * (sample_rate / nfft)
    visible_bins = np.where((bin_freqs >= f_start) & (bin_freqs <= f_end))[0]
    
    if len(visible_bins) == 0:
        return PluginResult()

    first_bin_idx = visible_bins[0]
    last_bin_idx = visible_bins[-1]

    # Slice spectrogram to the visible window
    spectrogram_db_sliced = spectrogram_db[:, first_bin_idx : last_bin_idx + 1]

    # 4. Thresholding relative to noise floor
    noise_floor = np.median(spectrogram_db_sliced)
    threshold = noise_floor + threshold_db
    binary_mask = spectrogram_db_sliced > threshold

    # 5. Morphological Closing to group nearby signals
    if CLOSE_TIME_BINS > 1 or CLOSE_FREQ_BINS > 1:
        struct = np.ones((CLOSE_TIME_BINS, CLOSE_FREQ_BINS))
        binary_mask = scipy.ndimage.binary_closing(binary_mask, structure=struct)

    # 6. Connected component labeling (using 8-connectivity)
    label_struct = np.ones((3, 3), dtype=int)
    labeled_mask, num_features = scipy.ndimage.label(binary_mask, structure=label_struct)

    if num_features == 0:
        return PluginResult()

    # Find bounding boxes for labeled regions
    slices = scipy.ndimage.find_objects(labeled_mask)

    result = PluginResult()

    # Clear old results from THIS plugin before adding fresh ones
    for o in info["overlays"]:
        if o.source == f"plugin:{PLUGIN_NAME}":
            result.remove(o.id)

    detected_bursts = []

    # 7. Analyze each component
    for idx, sl in enumerate(slices):
        if sl is None:
            continue

        slice_time, slice_freq = sl

        # Convert time slices to absolute time coordinates (seconds)
        t_start_burst = t_start + (slice_time.start * step_size) / sample_rate
        t_end_burst = t_start + ((slice_time.stop - 1) * step_size + nfft) / sample_rate
        duration = t_end_burst - t_start_burst

        if duration < min_burst_duration:
            continue

        # Convert frequency slices to absolute frequency coordinates (Hz)
        df = sample_rate / nfft
        f_start_burst = center_freq + (first_bin_idx + slice_freq.start - nfft / 2 - 0.5) * df
        f_end_burst = center_freq + (first_bin_idx + slice_freq.stop - nfft / 2 - 0.5) * df
        bandwidth = f_end_burst - f_start_burst

        if bandwidth < min_burst_bandwidth:
            continue

        # Calculate SNR and power properties
        comp_mask = labeled_mask == (idx + 1)
        comp_db = spectrogram_db_sliced[comp_mask]
        
        peak_db = float(np.max(comp_db))
        mean_db = float(np.mean(comp_db))
        snr = peak_db - noise_floor

        detected_bursts.append({
            "t_start": t_start_burst,
            "t_end": t_end_burst,
            "f_start": f_start_burst,
            "f_end": f_end_burst,
            "duration": duration,
            "bandwidth": bandwidth,
            "peak_db": peak_db,
            "mean_db": mean_db,
            "snr": snr
        })

    # Sort bursts by SNR (loudest first) and limit count
    detected_bursts = sorted(detected_bursts, key=lambda x: x["snr"], reverse=True)[:MAX_OVERLAYS]

    # 8. Create Box (Rect) Overlays
    for burst in detected_bursts:
        color = get_snr_color(burst["snr"], MIN_SNR_COLOR, MAX_SNR_COLOR)
        
        hover_str = (
            f"2D Energy Burst\n"
            f"Time: {burst['t_start']:.5f} s - {burst['t_end']:.5f} s ({burst['duration']*1000:.2f} ms)\n"
            f"Freq: {burst['f_start']/1e6:.4f} MHz - {burst['f_end']/1e6:.4f} MHz ({burst['bandwidth']/1e3:.1f} kHz)\n"
            f"SNR: {burst['snr']:.1f} dB\n"
            f"Peak Power: {burst['peak_db']:.1f} dB\n"
            f"Mean Power: {burst['mean_db']:.1f} dB"
        )
        
        display_str = f"{burst['snr']:.1f} dB SNR"

        rect = Rect(
            t_start=burst["t_start"],
            f_start=burst["f_start"],
            t_end=burst["t_end"],
            f_end=burst["f_end"],
            color=color,
            alpha=0.06,                  # very transparent fill to not obscure data
            border_width=1.5,
            border_color=color,
            border_style="solid",
            display_str=display_str,
            hover_str=hover_str,
            tag_pos="top-left",
            locked=True,
            metadata={
                "snr_db": burst["snr"],
                "peak_db": burst["peak_db"],
                "mean_db": burst["mean_db"],
                "duration_sec": burst["duration"],
                "bandwidth_hz": burst["bandwidth"]
            }
        )
        result.add(rect)

    return result

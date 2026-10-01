"""iqview/plugins/context.py

PluginContext and PluginParams — the object-oriented context (`info`) passed
to IQView plugins:

    def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
        fs = info.sample_rate
        thresh = info.params.threshold_db
        ...

Both classes provide full dictionary backward-compatibility (`info["sample_rate"]`,
`info.get("params", {})`, `"t_start" in info`) so existing plugins written for the
legacy dict interface continue to work without modification.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
import numpy as np


class PluginCancelledError(Exception):
    """Raised when a plugin execution is cancelled by the user."""
    pass


class PluginParams:
    """
    Object- and dict-accessible container for plugin parameters.

    Examples
    --------
    >>> p = PluginParams({"threshold_db": 10.0, "invert": False})
    >>> p.threshold_db
    10.0
    >>> p["threshold_db"]
    10.0
    >>> p.get("missing", 42)
    42
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        object.__setattr__(self, "_data", dict(data) if data else {})

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, "_data")
        if name in data:
            return data[name]
        raise AttributeError(
            f"'PluginParams' object has no parameter {name!r}. "
            f"Available parameters: {list(data.keys())}"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_data":
            object.__setattr__(self, name, value)
        else:
            object.__getattribute__(self, "_data")[name] = value

    def __getitem__(self, key: str) -> Any:
        return object.__getattribute__(self, "_data")[key]

    def __setitem__(self, key: str, value: Any) -> None:
        object.__getattribute__(self, "_data")[key] = value

    def __contains__(self, key: object) -> bool:
        return key in object.__getattribute__(self, "_data")

    def __iter__(self) -> Iterator[str]:
        return iter(object.__getattribute__(self, "_data"))

    def __len__(self) -> int:
        return len(object.__getattribute__(self, "_data"))

    def get(self, key: str, default: Any = None) -> Any:
        return object.__getattribute__(self, "_data").get(key, default)

    def keys(self):
        return object.__getattribute__(self, "_data").keys()

    def values(self):
        return object.__getattribute__(self, "_data").values()

    def items(self):
        return object.__getattribute__(self, "_data").items()

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(object.__getattribute__(self, "_data"))

    def __deepcopy__(self, memo) -> "PluginParams":
        return PluginParams(copy.deepcopy(object.__getattribute__(self, "_data"), memo))

    def __repr__(self) -> str:
        return f"PluginParams({object.__getattribute__(self, '_data')!r})"


class PluginContext:
    """
    Rich execution context (`info`) passed to ``run(samples, info)``.

    Supports both attribute access (`info.sample_rate`, `info.params.threshold_db`)
    and legacy dictionary access (`info["sample_rate"]`, `info.get("params")`).

    Attributes
    ----------
    sample_rate : float
        Sample rate in Hz (`info.fs` is also available as an alias).
    center_freq : float
        Center frequency in Hz (`info.fc` is also available as an alias).
    t_start : float
        Start time of the execution scope in seconds.
    t_end : float
        End time of the execution scope in seconds.
    f_start : float
        Lower frequency bound of the execution scope in Hz.
    f_end : float
        Upper frequency bound of the execution scope in Hz.
    overlays : list[Overlay]
        Snapshot of current overlays on the spectrogram (including any cached
        per-burst `o.iq` and `o.fs`).
    params : PluginParams
        Current parameter values for this plugin (`info.params.<name>` or
        `info.params["<name>"]`).
    time_markers : list[float]
        Sorted list of active time marker positions in seconds (0, 1, or 2 values).
    freq_markers : list[float]
        Sorted list of active frequency marker positions in Hz (0, 1, or 2 values).
    filter_bounds : tuple[float, float] | None
        Active BPF/BSF frequency bounds `(f_min, f_max)` in Hz, or `None`.
    spectrogram : np.ndarray | None
        Currently rendered 2D spectrogram array (dB), if available.
    scope : str
        Execution scope: `'view'`, `'markers'`, or `'full_file'`.
    file_duration : float
        Total duration of the loaded file/buffer in seconds.
    file_path : str | None
        Path to the loaded file on disk, or `None` for in-memory/stdin buffers.
    fft_size : int
        Current spectrogram FFT size.
    """

    def __init__(
        self,
        sample_rate: float,
        center_freq: float,
        t_start: float,
        t_end: float,
        f_start: float,
        f_end: float,
        overlays: Optional[List[Any]] = None,
        params: Optional[Any] = None,
        time_markers: Optional[List[float]] = None,
        freq_markers: Optional[List[float]] = None,
        filter_bounds: Optional[Tuple[float, float]] = None,
        spectrogram: Optional[np.ndarray] = None,
        scope: str = "view",
        file_duration: float = 0.0,
        file_path: Optional[str] = None,
        fft_size: int = 1024,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        extract_iq_cb: Optional[Callable[[float, float], Optional[np.ndarray]]] = None,
        samples_ref: Optional[np.ndarray] = None,
        alerts: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.sample_rate: float = float(sample_rate)
        self.center_freq: float = float(center_freq)
        self.t_start: float = float(t_start)
        self.t_end: float = float(t_end)
        self.f_start: float = float(f_start)
        self.f_end: float = float(f_end)
        self.overlays: List[Any] = list(overlays) if overlays is not None else []
        self.params: PluginParams = (
            params if isinstance(params, PluginParams) else PluginParams(params)
        )
        self.time_markers: List[float] = list(time_markers) if time_markers else []
        self.freq_markers: List[float] = list(freq_markers) if freq_markers else []
        self.filter_bounds: Optional[Tuple[float, float]] = filter_bounds
        self.spectrogram: Optional[np.ndarray] = spectrogram
        self.scope: str = scope
        self.file_duration: float = float(file_duration or max(0.0, t_end - t_start))
        self.file_path: Optional[str] = file_path
        self.fft_size: int = int(fft_size)

        self._progress_cb = progress_cb
        self._cancel_cb = cancel_cb
        self._extract_iq_cb = extract_iq_cb
        self._samples_ref = samples_ref
        self._alerts: List[Dict[str, Any]] = list(alerts) if alerts is not None else []

    # ------------------------------------------------------------------
    # Convenience properties & aliases
    # ------------------------------------------------------------------

    @property
    def fs(self) -> float:
        """Alias for `sample_rate` (Hz)."""
        return self.sample_rate

    @property
    def fc(self) -> float:
        """Alias for `center_freq` (Hz)."""
        return self.center_freq

    @property
    def duration(self) -> float:
        """Duration of the active execution scope in seconds (`t_end - t_start`)."""
        return max(0.0, self.t_end - self.t_start)

    @property
    def bandwidth(self) -> float:
        """Frequency span of the active execution scope in Hz (`f_end - f_start`)."""
        return max(0.0, self.f_end - self.f_start)

    # ------------------------------------------------------------------
    # Progress, Cancellation & Batch Streaming
    # ------------------------------------------------------------------

    def progress(self, pct: float, message: str = "") -> None:
        """
        Report execution progress (0.0 to 100.0) and an optional status message
        to the IQView UI progress dialog.
        """
        if self._progress_cb is not None:
            try:
                self._progress_cb(float(np.clip(pct, 0.0, 100.0)), str(message))
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        """Return True if the user clicked Cancel in the progress dialog."""
        if self._cancel_cb is not None:
            try:
                return bool(self._cancel_cb())
            except Exception:
                return False
        return False

    def alert(
        self,
        message: str,
        title: Optional[str] = None,
        level: str = "warning",
    ) -> "PluginContext":
        """
        Queue a user notification pop-up dialog to be shown on completion.

        Parameters
        ----------
        message : str
            Message text to display in the pop-up dialog.
        title : str, optional
            Custom dialog window title. Defaults to plugin name.
        level : {"warning", "error", "info"}, optional
            Alert severity level. Defaults to "warning".
        """
        lvl = str(level).strip().lower()
        if lvl not in ("info", "warning", "error"):
            lvl = "warning"
        self._alerts.append({
            "message": str(message),
            "title": str(title) if title else None,
            "level": lvl,
        })
        return self

    def info(self, message: str, title: Optional[str] = None) -> "PluginContext":
        """Queue an informational pop-up dialog to be shown on completion."""
        return self.alert(message, title=title, level="info")

    def warning(self, message: str, title: Optional[str] = None) -> "PluginContext":
        """Queue a warning pop-up dialog to be shown on completion."""
        return self.alert(message, title=title, level="warning")

    def error(self, message: str, title: Optional[str] = None) -> "PluginContext":
        """Queue an error pop-up dialog to be shown on completion."""
        return self.alert(message, title=title, level="error")

    @property
    def alerts(self) -> List[Dict[str, Any]]:
        """List of queued UI pop-up alert dictionaries."""
        return self._alerts

    def extract_iq(self, t0: float, t1: float) -> Optional[np.ndarray]:
        """
        Extract complex64 IQ samples for the time window ``[t0, t1]`` (seconds).

        Uses the already-loaded `samples` buffer if ``[t0, t1]`` lies within
        ``[self.t_start, self.t_end]`` and `samples` is populated; otherwise
        reads directly from the underlying file/buffer on demand.
        """
        t_lo, t_hi = min(float(t0), float(t1)), max(float(t0), float(t1))
        if t_hi <= t_lo:
            return np.empty(0, dtype=np.complex64)

        # Check if we can slice from the in-memory samples_ref
        if (
            self._samples_ref is not None
            and len(self._samples_ref) > 0
            and t_lo >= self.t_start - 1e-9
            and t_hi <= self.t_end + 1e-9
        ):
            s0 = max(0, int(round((t_lo - self.t_start) * self.sample_rate)))
            s1 = min(len(self._samples_ref), int(round((t_hi - self.t_start) * self.sample_rate)))
            if s1 > s0:
                return self._samples_ref[s0:s1]

        if self._extract_iq_cb is not None:
            return self._extract_iq_cb(t_lo, t_hi)

        return None

    def iter_batches(
        self,
        duration_s: float = 0.5,
        overlap_s: float = 0.0,
        update_progress: bool = True,
    ) -> Iterator[Tuple[np.ndarray, float, float]]:
        """
        Iterate over ``[self.t_start, self.t_end]`` in memory-safe time batches.

        Yields ``(batch_samples, batch_t_start, batch_t_end)`` for each chunk,
        automatically updating the progress bar and stopping if the user cancels.

        Parameters
        ----------
        duration_s : float
            Duration of each batch in seconds (default 0.5 s).
        overlap_s : float
            Overlap between consecutive batches in seconds (default 0.0 s).
        update_progress : bool
            If True, automatically calls ``self.progress(...)`` on each batch.
        """
        total_span = max(0.0, self.t_end - self.t_start)
        if total_span <= 0.0 or duration_s <= 0.0:
            return

        step_s = max(1.0 / max(self.sample_rate, 1.0), duration_s - max(0.0, overlap_s))
        t_curr = self.t_start
        batch_idx = 0
        total_batches = max(1, int(np.ceil(total_span / step_s)))

        while t_curr < self.t_end - 1e-12:
            if self.is_cancelled():
                break

            t_next = min(self.t_end, t_curr + duration_s)
            if update_progress:
                pct = ((t_curr - self.t_start) / total_span) * 100.0
                self.progress(pct, f"Processing batch {batch_idx + 1}/{total_batches} ({t_curr:.3f}s – {t_next:.3f}s)…")

            chunk = self.extract_iq(t_curr, t_next)
            if chunk is not None and len(chunk) > 0:
                yield chunk, t_curr, t_next

            if t_next >= self.t_end - 1e-12:
                break
            t_curr += step_s
            batch_idx += 1

        if update_progress and not self.is_cancelled():
            self.progress(100.0, "Finishing…")

    # ------------------------------------------------------------------
    # Dictionary backward-compatibility (`info["t_start"]`, `info.get(...)`)
    # ------------------------------------------------------------------

    _DICT_KEYS = (
        "sample_rate",
        "center_freq",
        "t_start",
        "t_end",
        "f_start",
        "f_end",
        "overlays",
        "params",
        "time_markers",
        "freq_markers",
        "filter_bounds",
        "spectrogram",
        "scope",
        "file_duration",
        "file_path",
        "fft_size",
    )

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key) and not key.startswith("_"):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "params" and not isinstance(value, PluginParams):
            self.params = PluginParams(value)
        else:
            setattr(self, key, value)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and not key.startswith("_") and hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        return default

    def keys(self):
        return list(self._DICT_KEYS)

    def values(self):
        return [getattr(self, k) for k in self._DICT_KEYS]

    def items(self):
        return [(k, getattr(self, k)) for k in self._DICT_KEYS]

    def copy_with(self, **overrides) -> "PluginContext":
        """Create a shallow copy of this PluginContext with specific fields overridden."""
        kwargs = {
            "sample_rate": self.sample_rate,
            "center_freq": self.center_freq,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "f_start": self.f_start,
            "f_end": self.f_end,
            "overlays": self.overlays,
            "params": copy.deepcopy(self.params),
            "time_markers": list(self.time_markers),
            "freq_markers": list(self.freq_markers),
            "filter_bounds": self.filter_bounds,
            "spectrogram": self.spectrogram,
            "scope": self.scope,
            "file_duration": self.file_duration,
            "file_path": self.file_path,
            "fft_size": self.fft_size,
            "progress_cb": self._progress_cb,
            "cancel_cb": self._cancel_cb,
            "extract_iq_cb": self._extract_iq_cb,
            "samples_ref": self._samples_ref,
            "alerts": list(self._alerts),
        }
        kwargs.update(overrides)
        return PluginContext(**kwargs)

    def __repr__(self) -> str:
        return (
            f"PluginContext(fs={self.sample_rate:g}, fc={self.center_freq:g}, "
            f"t=[{self.t_start:.4f}, {self.t_end:.4f}], "
            f"f=[{self.f_start:g}, {self.f_end:g}], "
            f"overlays={len(self.overlays)}, scope={self.scope!r}, "
            f"alerts={len(self._alerts)})"
        )

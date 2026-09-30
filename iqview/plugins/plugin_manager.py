"""iqview/plugins/plugin_manager.py

PluginManagerMixin — mixed into SpectrogramWindow.

Plugin contract
---------------
A plugin is a plain .py file that exposes a top-level function:

    def run(samples: np.ndarray, info: PluginContext) -> PluginResult:
        ...

`samples`  — complex64 numpy array of IQ samples for the execution window
             (or empty array if PLUGIN_NEEDS_WIDEBAND_IQ = False or when
             streaming large files via PLUGIN_BATCH_SECONDS).
`info`     — PluginContext object supporting BOTH attribute access
             (`info.sample_rate`, `info.fs`, `info.params.threshold_db`,
             `info.overlays`, `info.progress(50, "Demodulating...")`,
             `info.is_cancelled()`, `info.extract_iq(t0, t1)`,
             `info.iter_batches(duration_s=1.0)`) AND legacy dictionary
             access (`info["sample_rate"]`, `info.get("params")`).
Return     — a PluginResult instance (`from iqview import PluginResult`).

Optional module-level metadata constants:
    PLUGIN_NAME                  = "Human readable name"
    PLUGIN_DESCRIPTION           = "One-liner description shown in the menu tooltip"
    PLUGIN_CATEGORY              = "Detection"  # Optional category
    PLUGIN_PARAMS                = {...}        # Parameter schema
    PLUGIN_RUN_ON_MAIN_THREAD    = False
    PLUGIN_NEEDS_WIDEBAND_IQ     = True         # Set False if plugin only reads info.overlays / o.iq or streams via iter_batches()
    PLUGIN_BATCH_SECONDS         = None         # Optional float (e.g. 2.0) to auto-chunk large scopes
    PLUGIN_BATCH_OVERLAP_SECONDS = 0.0          # Optional overlap (seconds) when PLUGIN_BATCH_SECONDS is used
"""

from __future__ import annotations

import copy
import importlib.util
import os
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from iqview.plugins.context import PluginContext, PluginParams
from iqview.plugins.plugin_result import PluginResult


def _snapshot_overlay_for_thread(o) -> Any:
    """Create a thread-safe copy of an Overlay while sharing read-only `o.iq` memory."""
    saved_iq = getattr(o, "iq", None)
    saved_fs = getattr(o, "fs", None)
    try:
        o.iq = None
        clone = copy.deepcopy(o)
    finally:
        o.iq = saved_iq

    if saved_iq is not None:
        view = np.asarray(saved_iq).view()
        try:
            view.flags.writeable = False
        except Exception:
            pass
        clone.iq = view
    clone.fs = saved_fs
    return clone


def _merge_plugin_results(target: PluginResult, part: PluginResult) -> None:
    """Merge partial `PluginResult` from a batch into `target`."""
    if not isinstance(part, PluginResult):
        return
    target._adds.extend(part._adds)
    target._updates.extend(part._updates)
    target._removes.extend(part._removes)
    target._replaces.extend(part._replaces)
    target._plots.extend(part._plots)
    if part._plot_tab_title:
        target._plot_tab_title = part._plot_tab_title
    target._native_tabs.extend(part._native_tabs)
    target._logs.extend(part._logs)


# ---------------------------------------------------------------------------
# Background worker — runs the plugin's `run()` on a QThread
# ---------------------------------------------------------------------------

class _PluginWorker(QObject):
    finished  = pyqtSignal(object)     # PluginResult — passed straight through
    cancelled = pyqtSignal()           # emitted if cancelled mid-flight
    error     = pyqtSignal(str)        # error message string
    progress  = pyqtSignal(int, str)   # (percent 0..100, status message)

    def __init__(
        self,
        func: Callable,
        samples: Optional[np.ndarray],
        info: PluginContext,
        batch_seconds: Optional[float] = None,
        batch_overlap_seconds: float = 0.0,
        needs_wideband_iq: bool = True,
    ) -> None:
        super().__init__()
        self._func = func
        self._samples = samples
        self._info = info
        self._batch_seconds = batch_seconds
        self._batch_overlap_seconds = batch_overlap_seconds
        self._needs_wideband_iq = needs_wideband_iq
        self._cancelled = False

        # Wire live progress and cancellation callbacks into PluginContext
        self._info._progress_cb = self._emit_progress
        self._info._cancel_cb = self._check_cancelled

    def request_cancel(self) -> None:
        self._cancelled = True

    def _check_cancelled(self) -> bool:
        if self._cancelled:
            return True
        thread = QThread.currentThread()
        if thread is not None and thread.isInterruptionRequested():
            return True
        return False

    def _emit_progress(self, pct: int, msg: str = "") -> None:
        self.progress.emit(max(0, min(100, int(pct))), str(msg or ""))

    def run(self) -> None:
        try:
            total_dur = max(0.0, self._info.t_end - self._info.t_start)
            use_auto_batch = (
                self._batch_seconds is not None
                and self._batch_seconds > 0
                and total_dur > self._batch_seconds * 1.05
            )

            if use_auto_batch:
                merged = PluginResult()
                for batch_samples, b_t0, b_t1 in self._info.iter_batches(
                    duration_s=float(self._batch_seconds),
                    overlap_s=float(self._batch_overlap_seconds or 0.0),
                ):
                    if self._check_cancelled():
                        self.cancelled.emit()
                        return
                    batch_info = self._info.copy_with(
                        t_start=b_t0, t_end=b_t1, samples_ref=batch_samples
                    )
                    part = self._func(batch_samples, batch_info)
                    if not isinstance(part, PluginResult):
                        raise TypeError(
                            f"Plugin returned {type(part).__name__} instead of PluginResult."
                        )
                    _merge_plugin_results(merged, part)
                if self._check_cancelled():
                    self.cancelled.emit()
                    return
                self.finished.emit(merged)
                return

            # Single-invocation path
            samples = self._samples
            if samples is None:
                if self._needs_wideband_iq:
                    samples = self._info.extract_iq(self._info.t_start, self._info.t_end)
                    if samples is None:
                        samples = np.empty(0, dtype=np.complex64)
                    self._info._samples_ref = samples
                else:
                    samples = np.empty(0, dtype=np.complex64)

            result = self._func(samples, self._info)
            if self._check_cancelled():
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except Exception:
            self.error.emit(traceback.format_exc())


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class PluginManagerMixin:
    """
    Manages loading and running IQView plugins.

    Attributes added to the host class
    -----------------------------------
    _loaded_plugins  : dict[str, dict]   name → metadata & callable dict
    _plugins_menu    : QMenu | None
    """

    # ------------------------------------------------------------------
    # Initialisation (call from SpectrogramWindow.__init__)
    # ------------------------------------------------------------------

    def _init_plugins(self) -> None:
        self._loaded_plugins: Dict[str, dict] = {}
        self._plugins_menu = None  # set by component_setup after menu is built
        self._plugin_thread: Optional[QThread] = None
        self._plugin_worker: Optional[_PluginWorker] = None
        # Restore plugins saved from a previous session
        self._load_persisted_plugins()

    # ------------------------------------------------------------------
    # Menu management
    # ------------------------------------------------------------------

    def _rebuild_plugins_menu(self) -> None:
        """Rebuild the dynamic portion of the Plugins menu."""
        menu = self._plugins_menu
        if menu is None:
            return

        menu.clear()

        # Static actions
        load_action = QAction("&Load Plugin(s)…", self)
        load_action.setStatusTip("Load one or more Python plugin files (.py)")
        load_action.triggered.connect(self.load_plugin)
        menu.addAction(load_action)

        menu.addSeparator()

        unload_action = QAction("Unload &All", self)
        unload_action.setStatusTip("Remove all currently loaded plugins")
        unload_action.triggered.connect(self._unload_all_plugins)
        unload_action.setEnabled(bool(self._loaded_plugins))
        menu.addAction(unload_action)

        # Dynamic: one action per loaded plugin
        if self._loaded_plugins:
            menu.addSeparator()
            for name, info in self._loaded_plugins.items():
                action = QAction(f"▶  {name}", self)
                desc = info.get("description", "")
                tip  = f"Run plugin: {name}"
                if desc:
                    tip += f" — {desc}"
                action.setStatusTip(tip)
                action.setToolTip(tip)
                action.triggered.connect(
                    lambda _checked, n=name: self.run_plugin(n)
                )
                menu.addAction(action)

        if hasattr(self, 'marker_panel') and hasattr(self.marker_panel, 'update_plugins_list'):
            self.marker_panel.update_plugins_list(self._loaded_plugins)

    # ------------------------------------------------------------------
    # Load (Single or Multiple .py files)
    # ------------------------------------------------------------------

    def load_plugin(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load Plugin(s)", "", "Python Files (*.py)"
        )
        if not paths:
            return
        loaded_names = []
        for path in paths:
            name = self._load_plugin_from_path(path, _persist=False, _silent=True)
            if name:
                loaded_names.append(name)
        if loaded_names:
            self._save_plugin_paths()
            self._rebuild_plugins_menu()
            if len(loaded_names) == 1:
                self.statusBar().showMessage(f"Plugin loaded: {loaded_names[0]}", 3000)
            else:
                self.statusBar().showMessage(
                    f"Loaded {len(loaded_names)} plugins: {', '.join(loaded_names)}", 4000
                )

    def _load_plugin_from_path(
        self,
        path: str,
        _persist: bool = True,
        _silent: bool = False,
        _preserve_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Dynamically import a plugin file and register it. Returns plugin name on success."""
        path = os.path.normpath(os.path.abspath(path))
        base = os.path.splitext(os.path.basename(path))[0]
        mod_name = f"_iqview_plugin_{base}_{uuid.uuid4().hex[:8]}"

        try:
            spec   = importlib.util.spec_from_file_location(mod_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:
            QMessageBox.critical(
                self, "Plugin Load Error",
                f"Could not load plugin from:\n{path}\n\n{exc}"
            )
            return None

        if not hasattr(module, "run") or not callable(module.run):
            QMessageBox.critical(
                self, "Plugin Load Error",
                f"The file does not contain a callable `run(samples, info)` function:\n{path}"
            )
            return None

        name           = getattr(module, "PLUGIN_NAME",        base)
        description    = getattr(module, "PLUGIN_DESCRIPTION", "")
        category       = getattr(module, "PLUGIN_CATEGORY",    "Custom")
        run_on_main    = bool(getattr(module, "PLUGIN_RUN_ON_MAIN_THREAD", False))
        needs_wideband = bool(getattr(module, "PLUGIN_NEEDS_WIDEBAND_IQ", True))
        batch_seconds  = getattr(module, "PLUGIN_BATCH_SECONDS", None)
        batch_overlap  = float(getattr(module, "PLUGIN_BATCH_OVERLAP_SECONDS", 0.0) or 0.0)

        params_spec = getattr(module, "PLUGIN_PARAMS", {})
        active_params: Dict[str, Any] = {}
        if isinstance(params_spec, dict):
            for k, p_spec in params_spec.items():
                if isinstance(p_spec, dict):
                    active_params[k] = p_spec.get("default")
                else:
                    active_params[k] = p_spec

        # Preserve user-customized parameter values across hot-reloads if keys still exist
        if _preserve_params and isinstance(_preserve_params, dict):
            for k, val in _preserve_params.items():
                if k in active_params:
                    active_params[k] = val

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0

        self._loaded_plugins[name] = {
            "path":                  path,
            "mtime":                 mtime,
            "module":                module,
            "func":                  module.run,
            "description":           description,
            "category":              category,
            "run_on_main":           run_on_main,
            "needs_wideband_iq":     needs_wideband,
            "batch_seconds":         batch_seconds,
            "batch_overlap_seconds": batch_overlap,
            "params_spec":           params_spec,
            "params":                active_params,
        }

        if _persist:
            self._save_plugin_paths()
        self._rebuild_plugins_menu()
        if not _silent:
            self.statusBar().showMessage(f"Plugin loaded: {name}", 3000)
        return name

    def _hot_reload_if_modified(self, name: str) -> Optional[dict]:
        """Check if a loaded plugin's .py file has changed on disk and hot-reload it."""
        info = self._loaded_plugins.get(name)
        if info is None:
            return None
        path = info.get("path")
        if not path or not os.path.isfile(path):
            return info
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            return info

        if current_mtime > info.get("mtime", 0.0):
            new_name = self._load_plugin_from_path(
                path,
                _persist=False,
                _silent=True,
                _preserve_params=info.get("params"),
            )
            if new_name:
                return self._loaded_plugins.get(new_name)
        return self._loaded_plugins.get(name)

    # ------------------------------------------------------------------
    # Unload
    # ------------------------------------------------------------------

    def unload_plugin(self, name: str) -> None:
        if name in self._loaded_plugins:
            del self._loaded_plugins[name]
            self._save_plugin_paths()
            self._rebuild_plugins_menu()
            self.statusBar().showMessage(f"Plugin unloaded: {name}", 3000)

    def _unload_all_plugins(self) -> None:
        self._loaded_plugins.clear()
        self._save_plugin_paths()
        self._rebuild_plugins_menu()
        self.statusBar().showMessage("All plugins unloaded.", 3000)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_plugin_paths(self) -> None:
        """Persist current plugin file paths to settings."""
        if not hasattr(self, 'settings_mgr'):
            return
        paths = ";;".join(
            info["path"] for info in self._loaded_plugins.values() if info.get("path")
        )
        self.settings_mgr.set("plugins/loaded_paths", paths)

    def _load_persisted_plugins(self) -> None:
        """Reload plugin files saved from the previous session."""
        if not hasattr(self, 'settings_mgr'):
            return
        raw = self.settings_mgr.get("plugins/loaded_paths", "")
        if not raw:
            return
        for path in raw.split(";;"):
            path = path.strip()
            if path and os.path.isfile(path):
                self._load_plugin_from_path(path, _persist=False, _silent=True)

    # ------------------------------------------------------------------
    # Execution Scope & Context Builder
    # ------------------------------------------------------------------

    def _get_active_scope(self, scope: Optional[str] = None) -> str:
        if scope in ("view", "markers", "full_file"):
            return scope
        if hasattr(self, 'marker_panel') and hasattr(self.marker_panel, 'cb_plugin_scope'):
            data = self.marker_panel.cb_plugin_scope.currentData()
            if data in ("view", "markers", "full_file"):
                return data
        return "view"

    def _get_execution_bounds(self, scope: str = "view") -> Tuple[float, float, float, float]:
        """
        Compute `(t_start, t_end, f_start, f_end)` accurately across Standard,
        Waterfall, and Multi-Row modes, respecting the requested `scope`.
        """
        fs = float(getattr(self, 'rate', 1.0) or 1.0)
        fc = float(getattr(self, 'fc', 0.0) or 0.0)
        total_samples = self.get_total_samples() if hasattr(self, 'get_total_samples') else 0
        file_dur = (total_samples / fs) if total_samples > 0 else float(getattr(self, 'time_duration', 1.0) or 1.0)
        f_min_bound = fc - fs / 2.0
        f_max_bound = fc + fs / 2.0

        # 1. Determine current viewport bounds (Waterfall & Multi-Row aware)
        t_view_start, t_view_end = 0.0, file_dur
        f_view_start, f_view_end = f_min_bound, f_max_bound

        try:
            is_multirow = (
                hasattr(self, 'spectrogram_stack')
                and self.spectrogram_stack.currentIndex() == 1
                and hasattr(self, 'multi_row_view')
                and len(self.multi_row_view.rows) > 0
            )
            if is_multirow:
                rows = self.multi_row_view.rows
                t_view_start = min(float(r.get('t_vis_start', r['t_start'])) for r in rows)
                t_view_end   = max(float(r.get('t_vis_end',   r['t_end']))   for r in rows)
                f_range = getattr(self.multi_row_view, '_current_freq_range', (f_min_bound, f_max_bound))
                f_view_start, f_view_end = float(min(f_range)), float(max(f_range))
            elif hasattr(self, 'spectrogram_view'):
                xr, yr = self.spectrogram_view.plot_item.viewRange()
                is_waterfall = bool(getattr(self.spectrogram_view, 'is_waterfall', False))
                if is_waterfall:
                    f_view_start, f_view_end = float(min(xr)), float(max(xr))
                    t_view_start, t_view_end = float(min(yr)), float(max(yr))
                else:
                    t_view_start, t_view_end = float(min(xr)), float(max(xr))
                    f_view_start, f_view_end = float(min(yr)), float(max(yr))
        except Exception:
            pass

        # Clamp viewport bounds to recording limits
        t_view_start = max(0.0, min(t_view_start, file_dur))
        t_view_end   = max(t_view_start, min(t_view_end, file_dur))
        f_view_start = max(f_min_bound, min(f_view_start, f_max_bound))
        f_view_end   = max(f_view_start, min(f_view_end, f_max_bound))

        # 2. Apply Scope
        if scope == "full_file":
            return 0.0, file_dur, f_min_bound, f_max_bound

        if scope == "markers":
            t_m = [float(m.value()) for m in getattr(self, 'markers_time', [])]
            f_m = [float(m.value()) for m in getattr(self, 'markers_freq', [])]
            if len(t_m) >= 2:
                t_s, t_e = max(0.0, min(t_m)), min(file_dur, max(t_m))
            else:
                t_s, t_e = t_view_start, t_view_end
            if len(f_m) >= 2:
                f_s, f_e = max(f_min_bound, min(f_m)), min(f_max_bound, max(f_m))
            else:
                f_s, f_e = f_view_start, f_view_end
            return t_s, t_e, f_s, f_e

        return t_view_start, t_view_end, f_view_start, f_view_end

    def _build_plugin_context(
        self,
        plugin_info: Optional[dict] = None,
        scope: str = "view",
        t_start: Optional[float] = None,
        t_end: Optional[float] = None,
        f_start: Optional[float] = None,
        f_end: Optional[float] = None,
        samples_ref: Optional[np.ndarray] = None,
        samples: Optional[np.ndarray] = None,
    ) -> PluginContext:
        """Construct a rich `PluginContext` (`info`) object for plugin execution or overlay inspection."""
        if t_start is None or t_end is None or f_start is None or f_end is None:
            b_t0, b_t1, b_f0, b_f1 = self._get_execution_bounds(scope)
            if t_start is None:
                t_start = b_t0
            if t_end is None:
                t_end = b_t1
            if f_start is None:
                f_start = b_f0
            if f_end is None:
                f_end = b_f1

        if samples_ref is None and samples is not None:
            samples_ref = samples

        fs = float(getattr(self, 'rate', 1.0) or 1.0)
        fc = float(getattr(self, 'fc', 0.0) or 0.0)
        total_samples = self.get_total_samples() if hasattr(self, 'get_total_samples') else 0
        file_dur = (total_samples / fs) if total_samples > 0 else float(getattr(self, 'time_duration', 1.0) or 1.0)

        t_markers = sorted(
            [float(m.value()) for m in getattr(self, 'markers_time', [])]
            + [float(m.value()) for m in getattr(self, 'markers_time_endless', [])]
        )
        f_markers = sorted(
            [float(m.value()) for m in getattr(self, 'markers_freq', [])]
            + [float(m.value()) for m in getattr(self, 'markers_freq_endless', [])]
        )

        f_lo, f_hi = self.get_active_filter_bounds() if hasattr(self, 'get_active_filter_bounds') else (None, None)
        filter_bounds = (float(f_lo), float(f_hi)) if (f_lo is not None and f_hi is not None) else None

        spec_img = None
        try:
            if hasattr(self, 'spectrogram_view') and hasattr(self.spectrogram_view, 'img'):
                img_data = self.spectrogram_view.img.image
                if img_data is not None:
                    spec_img = np.asarray(img_data)
        except Exception:
            spec_img = None

        overlay_snapshots = [
            _snapshot_overlay_for_thread(o) for o in getattr(self, 'overlays', [])
        ]

        params_dict = copy.deepcopy(plugin_info.get("params", {})) if isinstance(plugin_info, dict) else {}

        return PluginContext(
            sample_rate=fs,
            center_freq=fc,
            t_start=float(t_start),
            t_end=float(t_end),
            f_start=float(f_start),
            f_end=float(f_end),
            overlays=overlay_snapshots,
            params=PluginParams(params_dict),
            time_markers=t_markers,
            freq_markers=f_markers,
            filter_bounds=filter_bounds,
            spectrogram=spec_img,
            scope=scope,
            file_duration=file_dur,
            file_path=getattr(self, 'file_path', None),
            fft_size=int(getattr(self, 'fft_size', 1024) or 1024),
            extract_iq_cb=lambda t0, t1: self.extract_iq_segment(t0, t1, _prompt_large=False),
            samples_ref=samples_ref,
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run_plugin(self, name: str, scope: Optional[str] = None) -> None:
        info = self._hot_reload_if_modified(name)
        if info is None:
            return

        if not self._has_data():
            QMessageBox.information(
                self, "No Data",
                "Please open an IQ file before running a plugin."
            )
            return

        active_scope = self._get_active_scope(scope)
        t_start, t_end, f_start, f_end = self._get_execution_bounds(active_scope)
        if t_end <= t_start:
            QMessageBox.warning(
                self, "Plugin Error",
                "Selected execution time range is empty."
            )
            return

        needs_wideband = bool(info.get("needs_wideband_iq", True))
        batch_seconds  = info.get("batch_seconds", None)
        batch_overlap  = float(info.get("batch_overlap_seconds", 0.0) or 0.0)
        total_dur      = t_end - t_start
        will_batch     = (
            batch_seconds is not None
            and float(batch_seconds) > 0
            and total_dur > float(batch_seconds) * 1.05
        )

        # Pre-extract wideband IQ only if needed and not running in chunked batch mode
        samples: Optional[np.ndarray] = None
        if needs_wideband and not will_batch:
            samples = self.extract_iq_segment(t_start, t_end)
            if samples is None or len(samples) == 0:
                QMessageBox.warning(
                    self, "Plugin Error",
                    "Could not extract IQ samples for the selected range.\n"
                    "Make sure a file is loaded and the range contains data."
                )
                return
        elif not needs_wideband:
            samples = np.empty(0, dtype=np.complex64)

        context = self._build_plugin_context(
            plugin_info=info,
            scope=active_scope,
            t_start=t_start,
            t_end=t_end,
            f_start=f_start,
            f_end=f_end,
            samples_ref=samples,
        )

        # Run synchronously on main thread if requested (for GUI/matplotlib debugging)
        if info.get("run_on_main", False):
            try:
                if will_batch:
                    merged = PluginResult()
                    for b_samples, b_t0, b_t1 in context.iter_batches(float(batch_seconds), batch_overlap):
                        b_info = context.copy_with(t_start=b_t0, t_end=b_t1, samples_ref=b_samples)
                        part = info["func"](b_samples, b_info)
                        _merge_plugin_results(merged, part)
                    result = merged
                else:
                    result = info["func"](samples, context)
                self._on_plugin_finished(name, result)
            except Exception:
                self._on_plugin_error(name, traceback.format_exc())
            return

        # Otherwise, run on background thread
        self._run_plugin_async(
            name=name,
            func=info["func"],
            samples=samples,
            context=context,
            batch_seconds=float(batch_seconds) if batch_seconds is not None else None,
            batch_overlap_seconds=batch_overlap,
            needs_wideband_iq=needs_wideband,
        )

    def _run_plugin_async(
        self,
        name: str,
        func: Callable,
        samples: Optional[np.ndarray],
        context: PluginContext,
        batch_seconds: Optional[float] = None,
        batch_overlap_seconds: float = 0.0,
        needs_wideband_iq: bool = True,
    ) -> None:
        # Guard: don't start a second plugin while one is running
        if self._plugin_thread is not None:
            try:
                running = self._plugin_thread.isRunning()
            except RuntimeError:
                running = False
                self._plugin_thread = None
            if running:
                QMessageBox.information(
                    self, "Plugin Busy",
                    "A plugin is already running. Please wait for it to finish."
                )
                return

        self._plugin_progress = QProgressDialog(
            f"Running plugin: {name}…", "Cancel", 0, 0, self
        )
        self._plugin_progress.setWindowTitle(f"Plugin — {name}")
        self._plugin_progress.setMinimumDuration(250)
        self._plugin_progress.setModal(True)

        worker = _PluginWorker(
            func=func,
            samples=samples,
            info=context,
            batch_seconds=batch_seconds,
            batch_overlap_seconds=batch_overlap_seconds,
            needs_wideband_iq=needs_wideband_iq,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        def _on_progress(pct: int, msg: str) -> None:
            if self._plugin_progress is None:
                return
            if self._plugin_progress.maximum() == 0:
                self._plugin_progress.setRange(0, 100)
            self._plugin_progress.setValue(pct)
            if msg:
                self._plugin_progress.setLabelText(f"Running {name}: {msg}")

        def _on_cancel_clicked() -> None:
            worker.request_cancel()
            thread.requestInterruption()

        thread.started.connect(worker.run)
        worker.progress.connect(_on_progress)
        worker.finished.connect(lambda result, n=name: self._on_plugin_finished(n, result))
        worker.cancelled.connect(lambda n=name: self.statusBar().showMessage(f"Plugin '{n}' cancelled.", 3000))
        worker.error.connect(lambda msg, n=name: self._on_plugin_error(n, msg))
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.error.connect(thread.quit)

        def _clear_thread():
            self._plugin_thread = None
            self._plugin_worker = None

        thread.finished.connect(_clear_thread)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._plugin_progress.close)

        self._plugin_progress.canceled.connect(_on_cancel_clicked)

        self._plugin_thread = thread
        self._plugin_worker = worker
        thread.start()

    def _on_plugin_finished(self, name: str, result: object) -> None:
        """Called on the main thread when a plugin completes successfully."""
        if not isinstance(result, PluginResult):
            QMessageBox.critical(
                self, f"Plugin Error — {name}",
                f"Plugin '{name}' did not return a PluginResult object.\n\n"
                f"Got: {type(result).__name__}\n\n"
                f"Make sure your run() function returns a PluginResult:\n"
                f"    from iqview import PluginResult\n"
                f"    def run(samples, info):\n"
                f"        result = PluginResult()\n"
                f"        ...\n"
                f"        return result"
            )
            return

        plugin_source = f"plugin:{name}"
        n_added = n_updated = n_removed = n_replaced = 0

        # 1. Removes — source-restricted: only overlays this plugin owns
        for oid in result._removes:
            existing = self._get_overlay_by_id(oid)
            if existing is None:
                print(f"[IQView Plugin] remove: overlay {oid!r} not found, skipping.")
                continue
            if existing.source != plugin_source:
                print(
                    f"[IQView Plugin] remove: overlay {oid!r} is owned by "
                    f"{existing.source!r}, not {plugin_source!r} — skipping."
                )
                continue
            self.remove_overlay(oid, _refresh_ui=False)
            n_removed += 1

        # 2. Replaces — remove old, add new (inheriting original source & cached IQ if not overwritten)
        for old_id, new_overlay in result._replaces:
            original = self._get_overlay_by_id(old_id)
            original_source = original.source if original is not None else plugin_source
            if original is not None:
                if getattr(new_overlay, "iq", None) is None and getattr(original, "iq", None) is not None:
                    new_overlay.iq = original.iq
                    new_overlay.fs = getattr(original, "fs", None)
                self.remove_overlay(old_id, _refresh_ui=False)
            new_overlay.id     = str(uuid.uuid4())
            new_overlay.source = original_source
            self.add_overlay(new_overlay, _refresh_ui=False)
            n_replaced += 1

        # 3. Updates — patch fields on existing overlays (preserving cached IQ unless updated)
        for oid, fields in result._updates:
            existing = self._get_overlay_by_id(oid)
            if existing is None:
                print(f"[IQView Plugin] update: overlay {oid!r} not found, skipping.")
                continue
            self.update_overlay(oid, _refresh_ui=False, **fields)
            n_updated += 1

        # 4. Adds — always allowed; fresh UUID + plugin source
        for overlay in result._adds:
            try:
                overlay.id     = str(uuid.uuid4())
                overlay.source = plugin_source
                self.add_overlay(overlay, _refresh_ui=False)
                n_added += 1
            except Exception as exc:
                print(f"[IQView Plugin] add: skipping malformed overlay: {exc}")

        # Single O(1) UI sync after all overlay mutations
        if hasattr(self, "refresh_overlays_ui"):
            self.refresh_overlays_ui()

        # 5. Custom 1D Plot Tab (at most one main tab per plugin, updated in-place on re-run)
        n_plots = len(getattr(result, "_plots", []))
        if n_plots > 0 and hasattr(self, "tabs"):
            from ..ui.plugin_plot_view import PluginPlotView

            tab_title = getattr(result, "_plot_tab_title", None) or f"{name} - Plots"
            existing_view = None
            existing_dv = None

            for i in range(1, self.tabs.count()):
                w = self.tabs.widget(i)
                if isinstance(w, PluginPlotView) and getattr(w, "_plugin_name", None) == name:
                    existing_view = w
                    break

            if existing_view is None and hasattr(self, "detached_views"):
                for dv in self.detached_views:
                    w = getattr(dv, "view", None)
                    if isinstance(w, PluginPlotView) and getattr(w, "_plugin_name", None) == name:
                        existing_view = w
                        existing_dv = dv
                        break

            if existing_view is not None:
                existing_view.set_plots(result._plots, tab_title=tab_title)
                if existing_dv is not None:
                    existing_dv.update_title()
                    existing_dv.raise_()
                else:
                    self.tabs.setCurrentWidget(existing_view)
                    if hasattr(self, "update_tab_names"):
                        self.update_tab_names()
            else:
                plot_view = PluginPlotView(
                    result._plots,
                    plugin_name=name,
                    tab_title=tab_title,
                    parent_window=self,
                )
                self.tabs.addTab(plot_view, tab_title)
                self.tabs.setCurrentWidget(plot_view)
                if hasattr(self, "update_tab_names"):
                    self.update_tab_names()

        # 6. Native Analysis Tab Launchers
        n_native_tabs = 0
        for tab_spec in getattr(result, "_native_tabs", []):
            if not hasattr(self, "tabs"):
                break
            samples = tab_spec.get("samples")
            if samples is None or len(samples) == 0:
                continue
            fs = float(tab_spec.get("fs", getattr(self, "rate", 1.0)) or 1.0)
            tab_type = tab_spec.get("type", "time_domain")
            custom_title = tab_spec.get("title")
            view = None
            default_label = "Analysis"

            if tab_type == "time_domain":
                from ..ui.time_domain.view import TimeDomainView
                t_start = float(tab_spec.get("t_start", 0.0))
                view = TimeDomainView(samples, t_start, fs, parent_window=self)
                default_label = f"{name} - Time Domain"
            elif tab_type == "freq_domain":
                from ..ui.frequency_domain.view import FrequencyDomainView
                fc = float(tab_spec.get("fc", 0.0))
                view = FrequencyDomainView(samples, fc, fs, parent_window=self)
                default_label = f"{name} - Freq Domain"
            elif tab_type == "constellation":
                from ..ui.constellation_dialog import ConstellationView
                view = ConstellationView(samples, fs, parent_window=self)
                default_label = f"{name} - Scatter Plot"
            elif tab_type == "eye_diagram":
                from ..ui.eye_diagram_dialog import EyeDiagramView
                view = EyeDiagramView(samples, fs, parent_window=self)
                default_label = f"{name} - Eye Diagram"

            if view is not None:
                title_to_use = custom_title or default_label
                view._custom_tab_title = title_to_use
                self.tabs.addTab(view, title_to_use)
                self.tabs.setCurrentWidget(view)
                n_native_tabs += 1

        if n_native_tabs > 0 and hasattr(self, "update_tab_names"):
            self.update_tab_names()

        # 7. Console & Status Bar Logs
        logs = getattr(result, "_logs", [])
        for msg in logs:
            print(f"[IQView Plugin: {name}] {msg}")

        summary_parts = [
            f"{n_added} added, {n_updated} updated, {n_removed} removed, {n_replaced} replaced"
        ]
        if n_plots > 0:
            summary_parts.append(f"{n_plots} plot(s)")
        if n_native_tabs > 0:
            summary_parts.append(f"{n_native_tabs} tab(s)")
        if logs:
            summary_parts.append(logs[-1])

        self.statusBar().showMessage(
            f"Plugin '{name}' — " + " | ".join(summary_parts),
            5000,
        )

        # Switch to OVERLAY mode so the user immediately sees the results on the spectrogram
        any_change = n_added + n_updated + n_removed + n_replaced
        if any_change > 0 and hasattr(self, 'set_interaction_mode'):
            self.set_interaction_mode('OVERLAY')

    def _on_plugin_error(self, name: str, msg: str) -> None:
        QMessageBox.critical(
            self, f"Plugin Error — {name}",
            f"The plugin raised an exception:\n\n{msg}"
        )

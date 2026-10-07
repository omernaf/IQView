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
import json
import os
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from iqview.plugins.chain import PluginChain
from iqview.plugins.context import PluginCancelledError, PluginContext, PluginParams
from iqview.plugins.plugin_result import PluginResult
from iqview.plugins.format_utils import format_hover_bits
from iqview.utils.helpers import debug_print, is_debug


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
    target._alerts.extend(getattr(part, "_alerts", []))


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
        if self._check_cancelled():
            raise PluginCancelledError("Plugin execution cancelled by user.")
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
                    if self._check_cancelled():
                        self.cancelled.emit()
                        return
                    if not isinstance(part, PluginResult):
                        raise TypeError(
                            f"Plugin returned {type(part).__name__} instead of PluginResult."
                        )
                    if hasattr(batch_info, "_alerts") and batch_info._alerts:
                        for a in batch_info._alerts:
                            if a not in part._alerts:
                                part._alerts.append(a)
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
            if isinstance(result, PluginResult) and hasattr(self._info, "_alerts") and self._info._alerts:
                for a in self._info._alerts:
                    if a not in result._alerts:
                        result._alerts.append(a)
            self.finished.emit(result)
        except PluginCancelledError:
            self.cancelled.emit()
        except Exception:
            if self._check_cancelled():
                self.cancelled.emit()
            else:
                self.error.emit(traceback.format_exc())
        except BaseException as be:
            if self._check_cancelled():
                self.cancelled.emit()
            else:
                self.error.emit(str(be))


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
        self._plugin_progress: Optional[QProgressDialog] = None
        self._plugin_launch_mode: Optional[str] = None
        # Load built-in plugins first, then restore custom plugins saved from previous session
        self._load_builtin_plugins()
        self._load_persisted_plugins()

    def _load_builtin_plugins(self) -> None:
        """Load the modular built-in plugin library shipped with IQView."""
        from iqview.plugins.builtin import get_builtin_plugin_paths
        for path in get_builtin_plugin_paths():
            self._load_plugin_from_path(
                path,
                _persist=False,
                _silent=True,
                _builtin=True,
            )

    def _resolve_plugin_target(self, target: str) -> Optional[dict]:
        """Resolve a plugin step target name against currently loaded plugins."""
        if not target:
            return None
        if target in self._loaded_plugins:
            return self._hot_reload_if_modified(target)
        t_low = str(target).strip().lower()
        for name in list(self._loaded_plugins.keys()):
            if name.lower() == t_low:
                return self._hot_reload_if_modified(name)
        return None

    # ------------------------------------------------------------------
    # Menu management
    # ------------------------------------------------------------------

    def _rebuild_plugins_menu(self) -> None:
        """Rebuild the dynamic portion of the Plugins menu."""
        menu = self._plugins_menu
        if menu is None:
            return

        menu.clear()

        studio_action = QAction("&Plugin Studio…", self)
        studio_action.setStatusTip("Open Plugin Studio (Manage, Chain Builder, Template Generator)")
        studio_action.triggered.connect(lambda: self.open_plugin_studio(initial_tab=0))
        menu.addAction(studio_action)

        chain_action = QAction("&Chain Builder…", self)
        chain_action.setStatusTip("Open the visual Plugin Chain Builder")
        chain_action.triggered.connect(lambda: self.open_plugin_studio(initial_tab=1))
        menu.addAction(chain_action)

        menu.addSeparator()

        # Static actions
        load_action = QAction("&Load Plugin(s)…", self)
        load_action.setStatusTip("Load one or more Python plugin files (.py)")
        load_action.triggered.connect(self.load_plugin)
        menu.addAction(load_action)

        restore_builtin_action = QAction("Restore &Built-In Plugins", self)
        restore_builtin_action.setStatusTip("Reload the built-in IQView plugin library")
        restore_builtin_action.triggered.connect(self._restore_builtin_plugins)
        menu.addAction(restore_builtin_action)

        menu.addSeparator()

        unload_action = QAction("Unload &All Custom", self)
        unload_action.setStatusTip("Remove all custom user-loaded plugins")
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

    def open_plugin_studio(
        self,
        initial_tab: int = 0,
        select_plugin: Optional[str] = None,
        edit_source: bool = False,
    ) -> None:
        """Open the 3-tab `PluginStudioDialog`.

        `edit_source` selects *select_plugin* and opens its `.py` file in the
        studio source editor.
        """
        from iqview.ui.plugin_studio import PluginStudioDialog
        dlg = PluginStudioDialog(
            self,
            initial_tab=initial_tab,
            select_plugin=select_plugin,
            edit_source=edit_source,
            parent=self,
        )
        dlg.exec()

    def get_pinned_plugins(self) -> List[str]:
        """Return list of pinned plugin names."""
        if not hasattr(self, "settings_mgr"):
            return getattr(self, "_pinned_plugins_mem", [])
        raw = str(self.settings_mgr.get("plugins/pinned", "") or "")
        return [p.strip() for p in raw.split(";;") if p.strip()]

    def toggle_pinned_plugin(self, name: str) -> bool:
        """Toggle pinned status for *name* and return new pinned state."""
        pinned = self.get_pinned_plugins()
        if name in pinned:
            pinned.remove(name)
            now_pinned = False
        else:
            pinned.append(name)
            now_pinned = True
        if hasattr(self, "settings_mgr"):
            self.settings_mgr.set("plugins/pinned", ";;".join(pinned))
        else:
            self._pinned_plugins_mem = pinned
        self._rebuild_plugins_menu()
        return now_pinned

    # ------------------------------------------------------------------
    # Parameter Session Persistence
    # ------------------------------------------------------------------

    def _get_all_saved_plugin_params(self) -> Dict[str, Dict[str, Any]]:
        """Return the full dictionary of saved plugin parameters from session settings."""
        if hasattr(self, "settings_mgr") and self.settings_mgr is not None:
            raw = self.settings_mgr.get("plugins/saved_params", "{}")
            if isinstance(raw, dict):
                return copy.deepcopy(raw)
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
        return copy.deepcopy(getattr(self, "_saved_plugin_params_mem", {}))

    def get_saved_plugin_params(self, name: str) -> Dict[str, Any]:
        """Return last-used session parameters for plugin *name*."""
        all_saved = self._get_all_saved_plugin_params()
        entry = all_saved.get(name, {})
        return copy.deepcopy(entry) if isinstance(entry, dict) else {}

    def save_plugin_params(self, name: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Persist active parameter values for plugin *name* into the user's session."""
        if not name:
            return
        info = self._loaded_plugins.get(name)
        if params is None:
            if info is None:
                return
            params = info.get("params", {})
        if not isinstance(params, dict):
            return

        if info is not None:
            info["params"] = copy.deepcopy(params)
            chain_obj = info.get("chain")
            if chain_obj is not None and hasattr(chain_obj, "steps"):
                for step_idx, s_dict in enumerate(chain_obj.steps):
                    prefix = f"step{step_idx}."
                    for k, v in params.items():
                        if str(k).startswith(prefix):
                            raw_k = str(k)[len(prefix):]
                            s_dict.setdefault("params", {})[raw_k] = v

        all_saved = self._get_all_saved_plugin_params()
        all_saved[name] = copy.deepcopy(params)
        self._saved_plugin_params_mem = all_saved
        if hasattr(self, "settings_mgr") and self.settings_mgr is not None:
            try:
                self.settings_mgr.set("plugins/saved_params", json.dumps(all_saved))
            except Exception:
                pass

    def register_chain_plugin(
        self,
        chain: PluginChain,
        path: Optional[str] = None,
        replace_name: Optional[str] = None,
    ) -> str:
        """Register or update a `PluginChain` in memory and refresh the UI."""
        chain.set_resolver(self._resolve_plugin_target)
        name = chain.name or "Custom Chain"

        prev_info = None
        if replace_name and replace_name in self._loaded_plugins:
            prev_info = self._loaded_plugins.get(replace_name)
        elif name in self._loaded_plugins:
            prev_info = self._loaded_plugins.get(name)

        if path is None and prev_info is not None:
            path = prev_info.get("path")

        if replace_name and replace_name != name and replace_name in self._loaded_plugins:
            del self._loaded_plugins[replace_name]
            pinned = self.get_pinned_plugins()
            if replace_name in pinned:
                pinned = [name if p == replace_name else p for p in pinned]
                if hasattr(self, "settings_mgr"):
                    self.settings_mgr.set("plugins/pinned", ";;".join(pinned))
                else:
                    self._pinned_plugins_mem = pinned

        params_spec = chain.get_combined_params_spec()
        active_params = {
            k: (spec.get("default") if isinstance(spec, dict) else spec)
            for k, spec in params_spec.items()
        }

        # Chains explicitly define step parameters in their pipeline definition.
        # Save newly configured chain parameters directly without resurrecting stale session params.
        self.save_plugin_params(name, active_params)
        self._loaded_plugins[name] = {
            "name":                  name,
            "path":                  path,
            "mtime":                 os.path.getmtime(path) if (path and os.path.isfile(path)) else 0.0,
            "module":                prev_info.get("module") if prev_info else None,
            "func":                  lambda s, ctx, _c=chain: _c.run(s, ctx),
            "chain":                 chain,
            "builtin":               bool(prev_info.get("builtin", False)) if prev_info else False,
            "description":           chain.description or "",
            "doc":                   chain.get_doc(),
            "category":              chain.category or "Chains",
            "run_on_main":           bool(prev_info.get("run_on_main", False)) if prev_info else False,
            "needs_wideband_iq":     chain.needs_wideband_iq(),
            "batch_seconds":         None,
            "batch_overlap_seconds": 0.0,
            "params_spec":           params_spec,
            "params":                active_params,
        }
        where = f" from {path}" if path else ""
        debug_print(f"[IQView] Loaded plugin: {name} [chain]{where}")
        if path and os.path.isfile(path):
            self._save_plugin_paths()
        self._rebuild_plugins_menu()
        if hasattr(self, "statusBar"):
            self.statusBar().showMessage(f"Updated chain: {name}", 3000)
        return name

    def _restore_builtin_plugins(self) -> None:
        self._load_builtin_plugins()
        self._rebuild_plugins_menu()
        self.statusBar().showMessage("Built-in plugins restored.", 3000)

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
        _builtin: Optional[bool] = None,
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
            debug_print(f"[IQView] Failed to load plugin from {path}")
            if is_debug():
                traceback.print_exc()
            if not _silent:
                QMessageBox.critical(
                    self, "Plugin Load Error",
                    f"Could not load plugin from:\n{path}\n\n{exc}"
                )
            return None

        chain_obj: Optional[PluginChain] = None
        for attr_name in ("CHAIN", "PLUGIN_CHAIN"):
            cand = getattr(module, attr_name, None)
            if isinstance(cand, PluginChain):
                chain_obj = cand
                break
        if chain_obj is None:
            for val in vars(module).values():
                if isinstance(val, PluginChain):
                    chain_obj = val
                    break
        if chain_obj is not None:
            chain_obj.bind_to_module(
                module,
                module_path=path,
                resolver=self._resolve_plugin_target,
            )

        if not hasattr(module, "run") or not callable(module.run):
            debug_print(
                f"[IQView] Failed to load plugin from {path}: "
                "no callable run() and no PluginChain"
            )
            if not _silent:
                QMessageBox.critical(
                    self, "Plugin Load Error",
                    f"The file does not contain a callable `run(samples, info)` function or `CHAIN = PluginChain(...)`:\n{path}"
                )
            return None

        name           = getattr(module, "PLUGIN_NAME",        base)
        description    = getattr(module, "PLUGIN_DESCRIPTION", "")
        doc            = str(getattr(module, "PLUGIN_DOC",     "") or "")
        category       = getattr(module, "PLUGIN_CATEGORY",    "Chains" if chain_obj else "Custom")
        run_on_main    = bool(getattr(module, "PLUGIN_RUN_ON_MAIN_THREAD", False))
        needs_wideband = bool(getattr(module, "PLUGIN_NEEDS_WIDEBAND_IQ", True))
        batch_seconds  = getattr(module, "PLUGIN_BATCH_SECONDS", None)
        batch_overlap  = float(getattr(module, "PLUGIN_BATCH_OVERLAP_SECONDS", 0.0) or 0.0)

        if _builtin is None:
            from iqview.plugins.builtin import get_builtin_plugin_paths
            prev = self._loaded_plugins.get(name)
            is_builtin = bool(prev.get("builtin", False)) if prev else (path in get_builtin_plugin_paths())
        else:
            is_builtin = bool(_builtin)

        params_spec = getattr(module, "PLUGIN_PARAMS", {})
        active_params: Dict[str, Any] = {}
        if isinstance(params_spec, dict):
            for k, p_spec in params_spec.items():
                if isinstance(p_spec, dict):
                    active_params[k] = p_spec.get("default")
                else:
                    active_params[k] = p_spec

        # Overlay saved session parameters (if any)
        saved_session_params = self.get_saved_plugin_params(name)
        for k, val in saved_session_params.items():
            if k in active_params:
                active_params[k] = val

        # Preserve user-customized parameter values across hot-reloads if keys still exist
        if _preserve_params and isinstance(_preserve_params, dict):
            for k, val in _preserve_params.items():
                if k in active_params:
                    active_params[k] = val

        if chain_obj is not None and hasattr(chain_obj, "steps"):
            # Ensure chain step explicit parameter overrides defined in the chain definition
            # are respected and not clobbered by stale session parameters
            for step_idx, s_dict in enumerate(chain_obj.steps):
                step_overrides = s_dict.get("params", {}) or {}
                prefix = f"step{step_idx}."
                for raw_k, step_val in step_overrides.items():
                    full_k = f"{prefix}{raw_k}"
                    active_params[full_k] = step_val

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0

        self._loaded_plugins[name] = {
            "name":                  name,
            "path":                  path,
            "mtime":                 mtime,
            "module":                module,
            "func":                  module.run,
            "chain":                 chain_obj,
            "builtin":               is_builtin,
            "description":           description,
            "doc":                   doc,
            "category":              category,
            "run_on_main":           run_on_main,
            "needs_wideband_iq":     needs_wideband,
            "batch_seconds":         batch_seconds,
            "batch_overlap_seconds": batch_overlap,
            "params_spec":           params_spec,
            "params":                active_params,
        }
        kind = "built-in" if is_builtin else ("chain" if chain_obj is not None else "custom")
        debug_print(f"[IQView] Loaded plugin: {name} [{kind}] from {path}")

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
                _builtin=info.get("builtin", False),
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
        # Keep built-in plugins loaded; only unload custom user-loaded plugins
        custom_names = [
            k for k, v in self._loaded_plugins.items() if not v.get("builtin", False)
        ]
        if custom_names:
            for k in custom_names:
                del self._loaded_plugins[k]
        else:
            self._loaded_plugins.clear()
        self._save_plugin_paths()
        self._rebuild_plugins_menu()
        self.statusBar().showMessage("Custom plugins unloaded.", 3000)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_plugin_paths(self) -> None:
        """Persist custom (non-builtin) plugin file paths to settings."""
        if not hasattr(self, 'settings_mgr'):
            return
        from iqview.plugins.builtin import get_builtin_plugin_paths
        builtin_set = set(get_builtin_plugin_paths())
        paths = ";;".join(
            info["path"]
            for info in self._loaded_plugins.values()
            if info.get("path") and not info.get("builtin", False) and info["path"] not in builtin_set
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
            elif (
                hasattr(self, 'spectrogram_view')
                and hasattr(self.spectrogram_view, 'img')
                and getattr(self.spectrogram_view.img, 'image', None) is not None
            ):
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

    def run_plugin(
        self,
        name: str,
        scope: Optional[str] = None,
        only_step: Optional[int] = None,
        from_step: int = 0,
    ) -> None:
        launch_mode = getattr(self, "interaction_mode", "")
        if hasattr(self, "marker_panel") and launch_mode in ("ZOOM", "MOVE"):
            launch_mode = getattr(self.marker_panel, "last_marker_mode", launch_mode)
        self._plugin_launch_mode = launch_mode

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

        chain_obj: Optional[PluginChain] = info.get("chain")
        if chain_obj is not None:
            chain_obj.set_resolver(self._resolve_plugin_target)
            needs_wideband = chain_obj.needs_wideband_iq(
                only_step=only_step, from_step=from_step
            )
            exec_func = lambda s, ctx, _c=chain_obj, _os=only_step, _fs=from_step: _c.run(
                s, ctx, only_step=_os, from_step=_fs
            )
        else:
            needs_wideband = bool(info.get("needs_wideband_iq", True))
            exec_func = info["func"]

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
                        part = exec_func(b_samples, b_info)
                        if isinstance(part, PluginResult) and hasattr(b_info, "_alerts") and b_info._alerts:
                            for a in b_info._alerts:
                                if a not in part._alerts:
                                    part._alerts.append(a)
                        _merge_plugin_results(merged, part)
                    result = merged
                else:
                    result = exec_func(samples, context)
                    if isinstance(result, PluginResult) and hasattr(context, "_alerts") and context._alerts:
                        for a in context._alerts:
                            if a not in result._alerts:
                                result._alerts.append(a)
                self._on_plugin_finished(name, result)
            except Exception:
                self._on_plugin_error(name, traceback.format_exc())
            return

        # Otherwise, run on background thread
        self._run_plugin_async(
            name=name,
            func=exec_func,
            samples=samples,
            context=context,
            batch_seconds=float(batch_seconds) if batch_seconds is not None else None,
            batch_overlap_seconds=batch_overlap,
            needs_wideband_iq=needs_wideband,
        )

    def run_plugin_step(
        self,
        name: str,
        step_index: int,
        single_step_only: bool = True,
        scope: Optional[str] = None,
    ) -> None:
        """
        Execute a specific step (or from `step_index` onward) of a `PluginChain`.
        """
        if single_step_only:
            self.run_plugin(name, scope=scope, only_step=int(step_index))
        else:
            self.run_plugin(name, scope=scope, from_step=int(step_index))

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

            # If the previous thread was cancelled, wait briefly or detach it so user is not blocked
            if running and getattr(self._plugin_worker, "_cancelled", False):
                self._plugin_thread.wait(500)
                try:
                    running = self._plugin_thread.isRunning()
                except RuntimeError:
                    running = False
                if not running:
                    self._plugin_thread = None
                    self._plugin_worker = None

            if running:
                if getattr(self._plugin_worker, "_cancelled", False):
                    # Discard lingering cancelled thread so user is never locked out
                    self._plugin_thread = None
                    self._plugin_worker = None
                    running = False
                else:
                    QMessageBox.information(
                        self, "Plugin Busy",
                        "A plugin is already running. Please wait for it to finish."
                    )
                    return

        progress_dialog = QProgressDialog(
            f"Running plugin: {name}…", "Cancel", 0, 0, self
        )
        progress_dialog.setWindowTitle(f"Plugin — {name}")
        progress_dialog.setMinimumDuration(250)
        progress_dialog.setModal(True)
        progress_dialog.setAutoReset(False)
        progress_dialog.setAutoClose(False)
        self._plugin_progress = progress_dialog

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
            if self._plugin_progress is None or getattr(worker, "_cancelled", False):
                return
            if self._plugin_progress.maximum() == 0:
                self._plugin_progress.setRange(0, 100)
            self._plugin_progress.setValue(pct)
            if msg:
                self._plugin_progress.setLabelText(f"Running {name}: {msg}")

        def _on_cancel_clicked() -> None:
            worker.request_cancel()
            thread.requestInterruption()
            if self._plugin_progress is not None:
                try:
                    self._plugin_progress.setLabelText(f"Cancelling {name}…")
                except Exception:
                    pass
            # Wait briefly for thread to exit cleanly
            if not thread.wait(300):
                if self._plugin_progress is not None:
                    try:
                        self._plugin_progress.close()
                    except Exception:
                        pass

        def _on_finished(result: object) -> None:
            if getattr(worker, "_cancelled", False) or thread.isInterruptionRequested():
                return
            self._on_plugin_finished(name, result)

        def _on_cancelled() -> None:
            self.statusBar().showMessage(f"Plugin '{name}' cancelled.", 3000)

        def _on_error(msg: str) -> None:
            if getattr(worker, "_cancelled", False) or thread.isInterruptionRequested():
                return
            self._on_plugin_error(name, msg)

        thread.started.connect(worker.run)
        worker.progress.connect(_on_progress)
        worker.finished.connect(_on_finished)
        worker.cancelled.connect(_on_cancelled)
        worker.error.connect(_on_error)

        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.error.connect(thread.quit)

        def _clear_thread() -> None:
            if self._plugin_thread is thread:
                self._plugin_thread = None
                self._plugin_worker = None
                self._plugin_launch_mode = None
            if self._plugin_progress is progress_dialog:
                try:
                    progress_dialog.close()
                except Exception:
                    pass
                self._plugin_progress = None

        thread.finished.connect(_clear_thread)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(progress_dialog.close)
        progress_dialog.canceled.connect(_on_cancel_clicked)

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
            if isinstance(new_overlay.metadata, dict) and "bits" in new_overlay.metadata and not new_overlay.hover_str:
                new_overlay.hover_str = format_hover_bits(
                    getattr(original, "hover_str", "") if original is not None else "",
                    new_overlay.metadata["bits"],
                    hex_str=new_overlay.metadata.get("hex"),
                )
            self.add_overlay(new_overlay, _refresh_ui=False)
            n_replaced += 1

        # 3. Updates — patch fields on existing overlays (preserving cached IQ unless updated)
        for oid, fields in result._updates:
            existing = self._get_overlay_by_id(oid)
            if existing is None:
                print(f"[IQView Plugin] update: overlay {oid!r} not found, skipping.")
                continue
            new_meta = fields.get("metadata")
            if isinstance(new_meta, dict) and "bits" in new_meta and "hover_str" not in fields:
                fields["hover_str"] = format_hover_bits(
                    getattr(existing, "hover_str", ""),
                    new_meta["bits"],
                    hex_str=new_meta.get("hex"),
                )
            self.update_overlay(oid, _refresh_ui=False, **fields)
            n_updated += 1

        # 4. Adds — always allowed; fresh UUID + plugin source
        for overlay in result._adds:
            try:
                overlay.id     = str(uuid.uuid4())
                overlay.source = plugin_source
                if isinstance(overlay.metadata, dict) and "bits" in overlay.metadata and not overlay.hover_str:
                    overlay.hover_str = format_hover_bits(
                        "",
                        overlay.metadata["bits"],
                        hex_str=overlay.metadata.get("hex"),
                    )
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

        # Switch to OVERLAY mode only if the user was not already in PLUGINS mode (and is not currently in PLUGINS mode),
        # so running a plugin from the Plugins tab keeps the user on the Plugins tab.
        any_change = n_added + n_updated + n_removed + n_replaced
        curr_mode = getattr(self, "interaction_mode", "")
        if hasattr(self, "marker_panel") and curr_mode in ("ZOOM", "MOVE"):
            curr_mode = getattr(self.marker_panel, "last_marker_mode", curr_mode)

        launch_mode = getattr(self, "_plugin_launch_mode", None)
        in_plugins_tab = (
            curr_mode == "PLUGINS"
            or launch_mode == "PLUGINS"
            or (
                hasattr(self, "marker_panel")
                and hasattr(self.marker_panel, "stack")
                and self.marker_panel.stack.currentIndex() == 3
            )
        )
        if any_change > 0 and not in_plugins_tab and hasattr(self, "set_interaction_mode"):
            self.set_interaction_mode("OVERLAY")

        self._plugin_launch_mode = None

        # Auto-persist params into the session
        self.save_plugin_params(name)

        # 8. Pop-up Alerts / Fail-safe Notices
        alerts = getattr(result, "_alerts", [])
        if alerts:
            if len(alerts) == 1:
                alt = alerts[0]
                lvl = alt.get("level", "warning").lower()
                msg = str(alt.get("message", ""))
                title = alt.get("title") or (
                    f"Plugin Error — {name}" if lvl == "error"
                    else (f"Plugin Info — {name}" if lvl == "info" else f"Plugin Warning — {name}")
                )
                if lvl == "error":
                    QMessageBox.critical(self, title, msg)
                elif lvl == "info":
                    QMessageBox.information(self, title, msg)
                else:
                    QMessageBox.warning(self, title, msg)
            else:
                levels = [a.get("level", "warning").lower() for a in alerts]
                if "error" in levels:
                    top_lvl = "error"
                    default_title = f"Plugin Error — {name}"
                elif "warning" in levels:
                    top_lvl = "warning"
                    default_title = f"Plugin Warning — {name}"
                else:
                    top_lvl = "info"
                    default_title = f"Plugin Info — {name}"

                body_lines = []
                for a in alerts:
                    src = a.get("source") or a.get("title") or a.get("level", "warning").capitalize()
                    body_lines.append(f"• [{src}]:\n  {str(a.get('message', '')).replace(chr(10), chr(10) + '  ')}")
                combined_msg = f"Plugin '{name}' reported multiple notices:\n\n" + "\n\n".join(body_lines)

                if top_lvl == "error":
                    QMessageBox.critical(self, default_title, combined_msg)
                elif top_lvl == "info":
                    QMessageBox.information(self, default_title, combined_msg)
                else:
                    QMessageBox.warning(self, default_title, combined_msg)

    def _on_plugin_error(self, name: str, msg: str) -> None:
        self._plugin_launch_mode = None
        QMessageBox.critical(
            self, f"Plugin Error — {name}",
            f"The plugin raised an exception:\n\n{msg}"
        )

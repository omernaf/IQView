"""iqview/plugins/plugin_manager.py

PluginManagerMixin — mixed into SpectrogramWindow.

Plugin contract
---------------
A plugin is a plain .py file that exposes a top-level function:

    def run(samples: np.ndarray, info: dict) -> list[dict]:
        ...

`samples`  — complex64 numpy array of IQ samples for the current view window.
`info`     — dict with keys:
               sample_rate  (Hz)
               center_freq  (Hz)
               t_start      (seconds, start of current view)
               t_end        (seconds, end of current view)
               f_start      (Hz, bottom of current view)
               f_end        (Hz, top of current view)
               overlays     (list of Overlay.to_dict() dicts currently on screen)
Return     — list of Overlay.to_dict()-compatible dicts to *add* to the spectrogram.
             IDs are reassigned automatically so running a plugin twice appends rather
             than collides.

Optional module-level metadata strings:
    PLUGIN_NAME        = "Human readable name"
    PLUGIN_DESCRIPTION = "One-liner description shown in the menu tooltip"
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
import uuid
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog


# ---------------------------------------------------------------------------
# Background worker — runs the plugin's `run()` on a QThread
# ---------------------------------------------------------------------------

class _PluginWorker(QObject):
    finished = pyqtSignal(list)   # list[dict]  — overlay dicts to add
    error    = pyqtSignal(str)    # error message string

    def __init__(self, func, samples: np.ndarray, info: dict) -> None:
        super().__init__()
        self._func    = func
        self._samples = samples
        self._info    = info

    def run(self) -> None:
        try:
            result = self._func(self._samples, self._info)
            if not isinstance(result, list):
                result = list(result) if result is not None else []
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
    _loaded_plugins  : dict[str, dict]   name → {path, module, func, description}
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
        load_action = QAction("&Load Plugin…", self)
        load_action.setStatusTip("Load a Python plugin file (.py)")
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
                # Capture name in closure
                action.triggered.connect(
                    lambda _checked, n=name: self.run_plugin(n)
                )
                menu.addAction(action)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_plugin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Plugin", "", "Python Files (*.py)"
        )
        if not path:
            return
        self._load_plugin_from_path(path)

    def _load_plugin_from_path(self, path: str, _persist: bool = True, _silent: bool = False) -> None:
        """Dynamically import a plugin file and register it."""
        import os
        base  = os.path.splitext(os.path.basename(path))[0]
        # Use a unique module name to avoid namespace collisions with re-loads
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
            return

        if not hasattr(module, "run") or not callable(module.run):
            QMessageBox.critical(
                self, "Plugin Load Error",
                f"The file does not contain a callable `run(samples, info)` function:\n{path}"
            )
            return

        name        = getattr(module, "PLUGIN_NAME",        base)
        description = getattr(module, "PLUGIN_DESCRIPTION", "")

        # If a plugin with the same display name is already loaded, replace it
        self._loaded_plugins[name] = {
            "path":        path,
            "module":      module,
            "func":        module.run,
            "description": description,
        }

        if _persist:
            self._save_plugin_paths()
        self._rebuild_plugins_menu()
        if not _silent:
            self.statusBar().showMessage(f"Plugin loaded: {name}", 3000)

    # ------------------------------------------------------------------
    # Unload
    # ------------------------------------------------------------------

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
            info["path"] for info in self._loaded_plugins.values()
        )
        self.settings_mgr.set("plugins/loaded_paths", paths)

    def _load_persisted_plugins(self) -> None:
        """Reload plugin files saved from the previous session."""
        if not hasattr(self, 'settings_mgr'):
            return
        raw = self.settings_mgr.get("plugins/loaded_paths", "")
        if not raw:
            return
        import os
        for path in raw.split(";;"):
            path = path.strip()
            if path and os.path.isfile(path):
                # _persist=False and _silent=True: don't re-save, don't call statusBar yet
                self._load_plugin_from_path(path, _persist=False, _silent=True)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run_plugin(self, name: str) -> None:
        info = self._loaded_plugins.get(name)
        if info is None:
            return

        if not self._has_data():
            QMessageBox.information(
                self, "No Data",
                "Please open an IQ file before running a plugin."
            )
            return

        # Gather current view range
        try:
            xr, yr = self.spectrogram_view.plot_item.viewRange()
            t_start, t_end = xr[0], xr[1]
            f_start, f_end = yr[0], yr[1]
        except Exception:
            t_start, t_end = 0.0, self.time_duration
            f_start = self.fc - self.rate / 2
            f_end   = self.fc + self.rate / 2

        # Extract IQ samples for the visible time window
        samples = self.extract_iq_segment(t_start, t_end)
        if samples is None or len(samples) == 0:
            QMessageBox.warning(
                self, "Plugin Error",
                "Could not extract IQ samples for the current view.\n"
                "Make sure a file is loaded and the view contains data."
            )
            return

        context = {
            "sample_rate": self.rate,
            "center_freq": self.fc,
            "t_start":     t_start,
            "t_end":       t_end,
            "f_start":     f_start,
            "f_end":       f_end,
            "overlays":    [o.to_dict() for o in self.overlays],
        }

        # Run on background thread
        self._run_plugin_async(name, info["func"], samples, context)

    def _run_plugin_async(
        self,
        name:    str,
        func,
        samples: np.ndarray,
        info:    dict,
    ) -> None:
        # Guard: don't start a second plugin while one is running
        if self._plugin_thread is not None:
            try:
                running = self._plugin_thread.isRunning()
            except RuntimeError:
                running = False      # C++ object already deleted
                self._plugin_thread = None
            if running:
                QMessageBox.information(
                    self, "Plugin Busy",
                    "A plugin is already running. Please wait for it to finish."
                )
                return

        # Progress dialog (indeterminate)
        self._plugin_progress = QProgressDialog(
            f"Running plugin: {name}…", "Cancel", 0, 0, self
        )
        self._plugin_progress.setWindowTitle("Plugin")
        self._plugin_progress.setMinimumDuration(300)
        self._plugin_progress.setModal(True)

        worker = _PluginWorker(func, samples, info)
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(lambda result, n=name: self._on_plugin_finished(n, result))
        worker.error.connect(lambda msg, n=name: self._on_plugin_error(n, msg))
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

        # Clear our reference BEFORE deleteLater fires, so a subsequent
        # isRunning() check never touches a deleted C++ object.
        def _clear_thread():
            self._plugin_thread = None
            self._plugin_worker = None

        thread.finished.connect(_clear_thread)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._plugin_progress.close)

        self._plugin_progress.canceled.connect(thread.requestInterruption)

        self._plugin_thread = thread
        self._plugin_worker = worker
        thread.start()

    def _on_plugin_finished(self, name: str, result: list) -> None:
        """Called on the main thread when a plugin completes successfully."""
        if not isinstance(result, list):
            result = []

        added = 0
        from iqview.ui.overlay import Overlay
        for d in result:
            try:
                o = Overlay.from_dict(d)
                o.id     = str(uuid.uuid4())   # fresh ID — never collide
                o.source = f"plugin:{name}"
                self.add_overlay(o)
                added += 1
            except Exception as exc:
                print(f"[IQView Plugin] Skipping malformed overlay: {exc}")

        self.statusBar().showMessage(
            f"Plugin '{name}' added {added} overlay(s).", 4000
        )

        # Switch to OVERLAY mode so the user immediately sees the results
        if added > 0 and hasattr(self, 'set_interaction_mode'):
            self.set_interaction_mode('OVERLAY')

    def _on_plugin_error(self, name: str, msg: str) -> None:
        QMessageBox.critical(
            self, f"Plugin Error — {name}",
            f"The plugin raised an exception:\n\n{msg}"
        )

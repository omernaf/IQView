#!/usr/bin/env python3
"""Unit tests for Plugin Studio plugin ordering (Favorites on top, alphabetical)."""

import os
import sys

# Ensure headless Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication, QMainWindow
from iqview.plugins.plugin_manager import PluginManagerMixin
from iqview.ui.marker_panel import MarkerPanel
from iqview.ui.plugin_studio import PluginStudioDialog


class MockSettingsManager:
    def __init__(self):
        self._data = {"ui/theme": "Light"}
    def get(self, key, default=None):
        return self._data.get(key, default)
    def set(self, key, value):
        self._data[key] = value


class MockWindow(QMainWindow, PluginManagerMixin):
    def __init__(self):
        super().__init__()
        self.settings_mgr = MockSettingsManager()
        self._loaded_plugins = {}
        self._pinned_plugins_mem = []
        self._plugin_history_mem = []
        self._plugins_menu = None
        self.overlays = []
        self.marker_edit_finished = lambda: None
        self.marker_panel = MarkerPanel(self)


def test_plugin_studio_ordering():
    app = QApplication.instance() or QApplication([])
    win = MockWindow()

    # Populate loaded plugins in arbitrary / non-alphabetical order
    win._loaded_plugins = {
        "Zeta Detector": {"builtin": True, "category": "Detection", "description": ""},
        "Alpha Demod": {"builtin": True, "category": "Demod", "description": ""},
        "Beta Filter": {"builtin": True, "category": "Filter", "description": ""},
        "Gamma Analysis": {"builtin": True, "category": "Analysis", "description": ""},
        "Delta Sync": {"builtin": True, "category": "Sync", "description": ""},
    }

    # Mark "Zeta Detector" and "Gamma Analysis" as favorites
    win.settings_mgr.set("plugins/pinned", "Zeta Detector;;Gamma Analysis")

    dlg = PluginStudioDialog(win)

    from PyQt6.QtCore import Qt

    # Inspect the items in list_manage_plugins
    items = [dlg.list_manage_plugins.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dlg.list_manage_plugins.count())]
    # Expected order:
    # Favorites on top, alphabetical: ["Gamma Analysis", "Zeta Detector"]
    # Non-favorites below, alphabetical: ["Alpha Demod", "Beta Filter", "Delta Sync"]
    expected = [
        "Gamma Analysis",
        "Zeta Detector",
        "Alpha Demod",
        "Beta Filter",
        "Delta Sync",
    ]
    assert items == expected, f"Order mismatch in Plugin Studio: {items} vs {expected}"

    # Also inspect display texts to ensure star prefix
    texts = [dlg.list_manage_plugins.item(i).text() for i in range(dlg.list_manage_plugins.count())]
    assert texts[0].startswith("★ Gamma Analysis")
    assert texts[1].startswith("★ Zeta Detector")
    assert not texts[2].startswith("★")
    assert "Alpha Demod" in texts[2]

    # Test toggling favorite: un-favorite "Gamma Analysis", favorite "Beta Filter"
    win.toggle_pinned_plugin("Gamma Analysis")
    win.toggle_pinned_plugin("Beta Filter")
    dlg._populate_manage_list()

    items_after = [dlg.list_manage_plugins.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dlg.list_manage_plugins.count())]
    expected_after = [
        "Beta Filter",
        "Zeta Detector",
        "Alpha Demod",
        "Delta Sync",
        "Gamma Analysis",
    ]
    assert items_after == expected_after, f"Order after toggle mismatch: {items_after} vs {expected_after}"

    print("[PASS] Plugin Studio manage list ordering (favorites on top, alphabetical) verified!")


if __name__ == "__main__":
    test_plugin_studio_ordering()
    print("All Plugin Studio ordering tests passed successfully!")

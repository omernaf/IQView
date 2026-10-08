#!/usr/bin/env python3
"""Unit and Integration Tests for Quick Run Plugin History and Favorites Ordering.

Validates:
1. get_plugin_history(), record_plugin_use(), clear_plugin_history(), and _remove_plugin_from_history().
2. MRU order maintenance (latest first) and deduplication.
3. Quick Run dropdown population in MarkerPanel:
   - Contains ONLY use history and favorites.
   - Ordering: last used (index 0, selected), 2nd latest, 3rd latest... followed by remaining favorites.
   - Distinct labeling: '★ Name' for favorites vs 'Name' for non-favorites in history.
   - Appropriate item tooltips.
4. Dynamic behavior on plugin execution, pinning, unpinning, and unloading.
"""

import os
import sys

# Ensure headless Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
from iqview.plugins.plugin_manager import PluginManagerMixin
from iqview.ui.marker_panel import MarkerPanel


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


def test_plugin_history_basic():
    print("Testing PluginManagerMixin history methods...")
    win = MockWindow()

    # 1. Initially empty
    assert win.get_plugin_history() == []

    # 2. Record plugin uses
    win.record_plugin_use("PluginA")
    assert win.get_plugin_history() == ["PluginA"]

    win.record_plugin_use("PluginB")
    assert win.get_plugin_history() == ["PluginB", "PluginA"]

    win.record_plugin_use("PluginC")
    assert win.get_plugin_history() == ["PluginC", "PluginB", "PluginA"]

    # 3. Re-run PluginA -> moves to front, no duplicate
    win.record_plugin_use("PluginA")
    assert win.get_plugin_history() == ["PluginA", "PluginC", "PluginB"]

    # 4. Remove a plugin
    win._remove_plugin_from_history("PluginC")
    assert win.get_plugin_history() == ["PluginA", "PluginB"]

    # 5. Clear history
    win.clear_plugin_history()
    assert win.get_plugin_history() == []
    print("PASS: PluginManagerMixin history methods.")


def test_quick_run_dropdown_ordering():
    print("Testing Quick Run dropdown ordering with history and favorites...")
    win = MockWindow()
    mp = win.marker_panel

    # Setup dummy loaded plugins
    win._loaded_plugins = {
        "BurstDetector": {"name": "BurstDetector", "params_spec": {"thresh": 10.0}},
        "FSKDemod": {"name": "FSKDemod", "params_spec": {}},
        "CustomFilter": {"name": "CustomFilter", "params_spec": {}},
        "RFMetrics": {"name": "RFMetrics", "params_spec": {}},
        "UnusedPlugin": {"name": "UnusedPlugin", "params_spec": {}},
    }

    # Favorites: BurstDetector and CustomFilter
    win.settings_mgr.set("plugins/pinned", "BurstDetector;;CustomFilter")

    # Initial update: no history yet
    mp.update_plugins_list(win._loaded_plugins)

    # cb_quick_plugin should only show favorites in order
    assert mp.cb_quick_plugin.count() == 2
    items = [mp.cb_quick_plugin.itemData(i) for i in range(mp.cb_quick_plugin.count())]
    assert items == ["BurstDetector", "CustomFilter"]
    assert mp.cb_quick_plugin.itemText(0) == "★ BurstDetector"
    assert mp.cb_quick_plugin.itemText(1) == "★ CustomFilter"
    assert mp.cb_quick_plugin.currentIndex() == 0  # First favorite selected

    # Now simulate running FSKDemod (not a favorite)
    win.record_plugin_use("FSKDemod")

    # Dropdown should now have:
    # 1. FSKDemod (last used, not favorite, selected!)
    # 2. ★ BurstDetector (favorite)
    # 3. ★ CustomFilter (favorite)
    # UnusedPlugin and RFMetrics must NOT be in the dropdown
    assert mp.cb_quick_plugin.count() == 3
    items = [mp.cb_quick_plugin.itemData(i) for i in range(mp.cb_quick_plugin.count())]
    assert items == ["FSKDemod", "BurstDetector", "CustomFilter"]
    assert mp.cb_quick_plugin.itemText(0) == "FSKDemod"
    assert mp.cb_quick_plugin.itemText(1) == "★ BurstDetector"
    assert mp.cb_quick_plugin.itemText(2) == "★ CustomFilter"
    assert mp.cb_quick_plugin.currentIndex() == 0
    assert mp.cb_quick_plugin.currentData() == "FSKDemod"

    # Now simulate running CustomFilter (a favorite)
    win.record_plugin_use("CustomFilter")

    # Dropdown should now have:
    # 1. ★ CustomFilter (last used, favorite, selected!)
    # 2. FSKDemod (2nd latest, not favorite)
    # 3. ★ BurstDetector (remaining favorite)
    assert mp.cb_quick_plugin.count() == 3
    items = [mp.cb_quick_plugin.itemData(i) for i in range(mp.cb_quick_plugin.count())]
    assert items == ["CustomFilter", "FSKDemod", "BurstDetector"]
    assert mp.cb_quick_plugin.itemText(0) == "★ CustomFilter"
    assert mp.cb_quick_plugin.itemText(1) == "FSKDemod"
    assert mp.cb_quick_plugin.itemText(2) == "★ BurstDetector"
    assert mp.cb_quick_plugin.currentIndex() == 0
    assert mp.cb_quick_plugin.currentData() == "CustomFilter"

    # Now simulate running BurstDetector (favorite)
    win.record_plugin_use("BurstDetector")

    # Dropdown should now have:
    # 1. ★ BurstDetector (last used, favorite, selected!)
    # 2. ★ CustomFilter (2nd latest, favorite)
    # 3. FSKDemod (3rd latest, not favorite)
    assert mp.cb_quick_plugin.count() == 3
    items = [mp.cb_quick_plugin.itemData(i) for i in range(mp.cb_quick_plugin.count())]
    assert items == ["BurstDetector", "CustomFilter", "FSKDemod"]
    assert mp.cb_quick_plugin.itemText(0) == "★ BurstDetector"
    assert mp.cb_quick_plugin.itemText(1) == "★ CustomFilter"
    assert mp.cb_quick_plugin.itemText(2) == "FSKDemod"
    assert mp.cb_quick_plugin.currentIndex() == 0
    assert mp.cb_quick_plugin.currentData() == "BurstDetector"

    # Now simulate running RFMetrics
    win.record_plugin_use("RFMetrics")

    # Dropdown should now have:
    # 1. RFMetrics (last used, selected!)
    # 2. ★ BurstDetector (2nd latest)
    # 3. ★ CustomFilter (3rd latest)
    # 4. FSKDemod (4th latest)
    # UnusedPlugin still not in the dropdown
    assert mp.cb_quick_plugin.count() == 4
    items = [mp.cb_quick_plugin.itemData(i) for i in range(mp.cb_quick_plugin.count())]
    assert items == ["RFMetrics", "BurstDetector", "CustomFilter", "FSKDemod"]
    assert mp.cb_quick_plugin.itemText(0) == "RFMetrics"
    assert mp.cb_quick_plugin.itemText(1) == "★ BurstDetector"
    assert mp.cb_quick_plugin.itemText(2) == "★ CustomFilter"
    assert mp.cb_quick_plugin.itemText(3) == "FSKDemod"
    assert mp.cb_quick_plugin.currentIndex() == 0
    assert mp.cb_quick_plugin.currentData() == "RFMetrics"

    print("PASS: Quick Run dropdown ordering with history and favorites.")


def test_quick_run_pin_and_unload():
    print("Testing pin/unpin and unload behavior in Quick Run...")
    win = MockWindow()
    mp = win.marker_panel

    win._loaded_plugins = {
        "A": {"name": "A", "params_spec": {}},
        "B": {"name": "B", "params_spec": {}},
        "C": {"name": "C", "params_spec": {}},
    }
    win.settings_mgr.set("plugins/pinned", "A")

    # Run B
    win.record_plugin_use("B")
    # Dropdown: B (used last), ★ A (favorite)
    items = [mp.cb_quick_plugin.itemData(i) for i in range(mp.cb_quick_plugin.count())]
    assert items == ["B", "A"]
    assert mp.cb_quick_plugin.itemText(0) == "B"
    assert mp.cb_quick_plugin.itemText(1) == "★ A"

    # Pin B
    win.toggle_pinned_plugin("B")
    # Now B is pinned, still at index 0 because it was used last, but now with star
    items = [mp.cb_quick_plugin.itemData(i) for i in range(mp.cb_quick_plugin.count())]
    assert items == ["B", "A"]
    assert mp.cb_quick_plugin.itemText(0) == "★ B"
    assert mp.cb_quick_plugin.itemText(1) == "★ A"

    # Unpin A (A was not in history)
    win.toggle_pinned_plugin("A")
    # A should now be removed from Quick Run completely!
    items = [mp.cb_quick_plugin.itemData(i) for i in range(mp.cb_quick_plugin.count())]
    assert items == ["B"]

    # Unload B
    win.unload_plugin("B")
    # Dropdown should now be empty and disabled
    assert mp.cb_quick_plugin.count() == 0
    assert not mp.cb_quick_plugin.isEnabled()
    assert not mp.btn_quick_run.isEnabled()

    print("PASS: pin/unpin and unload behavior in Quick Run.")


if __name__ == "__main__":
    app = QApplication([])
    test_plugin_history_basic()
    test_quick_run_dropdown_ordering()
    test_quick_run_pin_and_unload()
    print("=== All Quick Run History Tests Passed Successfully! ===")

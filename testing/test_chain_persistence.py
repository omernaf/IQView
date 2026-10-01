"""
test_chain_persistence.py — Unit tests for chain step parameter updates and persistence

Tests that updating a chain step (e.g. changing FEC decoder preset to Custom G Matrix)
persists cleanly across saves, session settings, re-opening Plugin Studio, and reloading.
"""

import os
import sys
import tempfile
import unittest

from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox

# Ensure non-interactive execution
QMessageBox.information = lambda *a, **k: None
QMessageBox.warning = lambda *a, **k: None
QMessageBox.critical = lambda *a, **k: None

from iqview.plugins.plugin_manager import PluginManagerMixin
from iqview.ui.plugin_studio import PluginStudioDialog


class _DummyMainWindow(QMainWindow, PluginManagerMixin):
    def __init__(self):
        super().__init__()
        self._loaded_plugins = {}
        self._saved_plugin_params_mem = {}
        self._load_builtin_plugins()

    def _rebuild_plugins_menu(self):
        pass

    def _save_plugin_paths(self):
        pass


class TestChainPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.win = _DummyMainWindow()
        self.tmp_files = []

    def tearDown(self):
        for path in self.tmp_files:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _make_temp_py(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".py")
        os.close(fd)
        self.tmp_files.append(path)
        return path

    def test_fec_custom_g_persistence_across_reopen(self):
        """Test creating FEC chain, updating to Custom G, saving, and reopening studio."""
        tmp_py = self._make_temp_py()

        # 1. Create chain with Block FEC Decoder
        dlg = PluginStudioDialog(self.win, initial_tab=1)
        for i in range(dlg.list_available_for_chain.count()):
            item = dlg.list_available_for_chain.item(i)
            if "Block FEC Decoder" in item.text():
                dlg.list_available_for_chain.setCurrentItem(item)
                break
        dlg._on_add_step_to_chain()

        dlg._editing_chain_path = tmp_py
        dlg._on_save_or_update_existing_chain()
        chain_name = dlg._editing_chain_orig_name
        self.assertIsNotNone(chain_name)
        dlg.close()

        # Verify initial save
        initial_params = self.win.get_saved_plugin_params(chain_name)
        self.assertEqual(initial_params.get("step0.code"), "Hamming(7,4)")

        # 2. Reopen and update to Custom G Matrix
        dlg2 = PluginStudioDialog(self.win, initial_tab=1)
        dlg2._load_chain_into_builder(chain_name)
        dlg2._on_chain_step_selected(0)

        custom_g = "10011, 01010"
        dlg2._chain_step_widgets["code"].setCurrentText("Custom G Matrix")
        dlg2._chain_step_widgets["custom_g_matrix"].setText(custom_g)
        dlg2._on_save_or_update_existing_chain()
        dlg2.close()

        # Verify saved parameters updated in session
        updated_params = self.win.get_saved_plugin_params(chain_name)
        self.assertEqual(updated_params.get("step0.code"), "Custom G Matrix")
        self.assertEqual(updated_params.get("step0.custom_g_matrix"), custom_g)

        # 3. Reopen Plugin Studio and verify Chain Builder and Manage tab
        dlg3 = PluginStudioDialog(self.win, initial_tab=1)
        dlg3._load_chain_into_builder(chain_name)
        dlg3._on_chain_step_selected(0)

        self.assertEqual(dlg3._chain_step_widgets["code"].currentText(), "Custom G Matrix")
        self.assertEqual(dlg3._chain_step_widgets["custom_g_matrix"].text(), custom_g)

        # Verify Manage & Run tab
        dlg3.tabs.setCurrentIndex(0)
        dlg3._populate_manage_list(select_plugin=chain_name)
        self.assertEqual(dlg3._manage_param_widgets["step0.code"].currentText(), "Custom G Matrix")
        self.assertEqual(dlg3._manage_param_widgets["step0.custom_g_matrix"].text(), custom_g)
        dlg3.close()

    def test_reload_from_disk_preserves_custom_params(self):
        """Test reload from disk simulates app restart with saved settings."""
        tmp_py = self._make_temp_py()

        dlg = PluginStudioDialog(self.win, initial_tab=1)
        for i in range(dlg.list_available_for_chain.count()):
            item = dlg.list_available_for_chain.item(i)
            if "Block FEC Decoder" in item.text():
                dlg.list_available_for_chain.setCurrentItem(item)
                break
        dlg._on_add_step_to_chain()
        dlg._editing_chain_path = tmp_py
        dlg._on_save_or_update_existing_chain()
        chain_name = dlg._editing_chain_orig_name

        # Update to Custom G Matrix
        dlg._on_chain_step_selected(0)
        dlg._chain_step_widgets["code"].setCurrentText("Custom G Matrix")
        custom_g = "1101, 1011"
        dlg._chain_step_widgets["custom_g_matrix"].setText(custom_g)
        dlg._on_save_or_update_existing_chain()
        dlg.close()

        # Simulate app restart: fresh window with saved QSettings params
        win2 = _DummyMainWindow()
        win2._saved_plugin_params_mem = dict(self.win._saved_plugin_params_mem)
        reloaded = win2._load_plugin_from_path(tmp_py)

        self.assertEqual(reloaded, chain_name)
        self.assertEqual(win2._loaded_plugins[reloaded]["params"].get("step0.code"), "Custom G Matrix")
        self.assertEqual(win2._loaded_plugins[reloaded]["params"].get("step0.custom_g_matrix"), custom_g)

        chain_step_params = win2._loaded_plugins[reloaded]["chain"].steps[0]["params"]
        self.assertEqual(chain_step_params.get("code"), "Custom G Matrix")
        self.assertEqual(chain_step_params.get("custom_g_matrix"), custom_g)

    def test_multi_step_chain_transitions(self):
        """Test multi-step chain with FEC and CRC, switching presets and custom parameters."""
        tmp_py = self._make_temp_py()

        dlg = PluginStudioDialog(self.win, initial_tab=1)
        steps_to_add = ["Sync Word Slicer", "Block FEC Decoder", "CRC Checker"]
        for step_name in steps_to_add:
            for i in range(dlg.list_available_for_chain.count()):
                item = dlg.list_available_for_chain.item(i)
                if step_name.lower() in item.text().lower():
                    dlg.list_available_for_chain.setCurrentItem(item)
                    dlg._on_add_step_to_chain()
                    break

        dlg._editing_chain_path = tmp_py
        dlg._on_save_or_update_existing_chain()
        chain_name = dlg._editing_chain_orig_name
        dlg.close()

        # Edit FEC step to Golay(24,12) and CRC step to CRC-32-IEEE
        dlg = PluginStudioDialog(self.win, initial_tab=1)
        dlg._load_chain_into_builder(chain_name)

        dlg.list_chain_steps.setCurrentRow(1)
        dlg._on_chain_step_selected(1)
        dlg._chain_step_widgets["code"].setCurrentText("Golay(24,12)")

        dlg.list_chain_steps.setCurrentRow(2)
        dlg._on_chain_step_selected(2)
        dlg._chain_step_widgets["preset"].setCurrentText("CRC-32-IEEE")

        dlg._on_save_or_update_existing_chain()
        dlg.close()

        # Reopen and verify
        dlg2 = PluginStudioDialog(self.win, initial_tab=1)
        dlg2._load_chain_into_builder(chain_name)

        dlg2.list_chain_steps.setCurrentRow(1)
        dlg2._on_chain_step_selected(1)
        self.assertEqual(dlg2._chain_step_widgets["code"].currentText(), "Golay(24,12)")

        dlg2.list_chain_steps.setCurrentRow(2)
        dlg2._on_chain_step_selected(2)
        self.assertEqual(dlg2._chain_step_widgets["preset"].currentText(), "CRC-32-IEEE")
        dlg2.close()


if __name__ == "__main__":
    unittest.main()

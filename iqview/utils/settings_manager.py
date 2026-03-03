from PyQt6.QtCore import QSettings

class SettingsManager:
    """
    Manages application settings and persistence using QSettings.
    """
    DEFAULT_SETTINGS = {
        "core/fc": 0.0,
        "core/fft_size": 1024,
        "core/overlap": 99.0,
        "core/window_type": "Hamming",
        "core/type": "complex64",
        "ui/theme": "Light",
        "keybinds/time_markers": "T",
        "keybinds/mag_markers": "F",
        "keybinds/zoom_mode": "Control"
    }

    def __init__(self):
        # Organization and Application names help define where QSettings saves (Registry on Windows)
        self.settings = QSettings("IQViewProject", "IQView")
        self._set_defaults()

    def _set_defaults(self):
        # Only set if they don't exist
        for key, value in self.DEFAULT_SETTINGS.items():
            if not self.settings.contains(key):
                self.settings.setValue(key, value)

    def get_default(self, key):
        """Returns the factory default for a given key."""
        return self.DEFAULT_SETTINGS.get(key)

    def get(self, key, default=None):
        return self.settings.value(key, default)

    def set(self, key, value):
        self.settings.setValue(key, value)
        self.settings.sync() # Ensure it's written to disk

    def all_settings(self):
        """Returns all settings as a nested dictionary."""
        data = {}
        for key in self.settings.allKeys():
            parts = key.split("/")
            curr = data
            for part in parts[:-1]:
                if part not in curr: curr[part] = {}
                curr = curr[part]
            curr[parts[-1]] = self.settings.value(key)
        return data

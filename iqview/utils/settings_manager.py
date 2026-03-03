from PyQt6.QtCore import QSettings

class SettingsManager:
    """
    Manages application settings and persistence using QSettings.
    """
    def __init__(self):
        # Organization and Application names help define where QSettings saves (Registry on Windows)
        self.settings = QSettings("IQViewProject", "IQView")
        self._set_defaults()

    def _set_defaults(self):
        # Only set if they don't exist
        if not self.settings.contains("core/fc"):
            self.settings.setValue("core/fc", 0.0)
        if not self.settings.contains("core/fft_size"):
            self.settings.setValue("core/fft_size", 1024)
        if not self.settings.contains("core/overlap"):
            self.settings.setValue("core/overlap", 99.0)
        if not self.settings.contains("core/window_type"):
            self.settings.setValue("core/window_type", "Hanning")
        if not self.settings.contains("core/type"):
            self.settings.setValue("core/type", "complex64")
        
        if not self.settings.contains("ui/theme"):
            self.settings.setValue("ui/theme", "Dark") # Default
            
        # Keybinds
        if not self.settings.contains("keybinds/time_markers"):
            self.settings.setValue("keybinds/time_markers", "T")
        if not self.settings.contains("keybinds/mag_markers"):
            self.settings.setValue("keybinds/mag_markers", "F")
        if not self.settings.contains("keybinds/zoom_mode"):
            self.settings.setValue("keybinds/zoom_mode", "Control")

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

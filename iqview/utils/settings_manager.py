from PyQt6.QtCore import QSettings

class SettingsManager:
    """
    Manages application settings and persistence using QSettings.
    """
    DEFAULT_SETTINGS = {
        "core/fc": 0.0,
        "core/fs": 1e6,
        "core/fft_size": 1024,
        "core/overlap": 99.0,
        "core/window_type": "Hamming",
        "core/type": "complex64",
        "core/filter_type": "Elliptic",
        "core/filter_order": 8,
        "core/filter_ripple": 0.1,
        "core/filter_stopband": 60.0,
        "core/filter_bessel_norm": "phase",
        "core/time_plots": [
            "instant frequency", 
            "magnitude^2", 
            "Real", 
            "Imaginary"
        ],
        "ui/theme": "Light",
        "ui/colormap": "turbo",
        "ui/colormap_reversed": False,
        
        # Dark Theme Styles
        "ui/dark/time_marker_color": "#00ff00",
        "ui/dark/time_marker_style": "DashLine",
        "ui/dark/freq_marker_color": "#ffaa00",
        "ui/dark/freq_marker_style": "DashLine",
        "ui/dark/zoom_box_color": "#ffffff",
        "ui/dark/zoom_box_style": "DashLine",

        # Light Theme Styles
        "ui/light/time_marker_color": "#008800",
        "ui/light/time_marker_style": "DashLine",
        "ui/light/freq_marker_color": "#cc6600",
        "ui/light/freq_marker_style": "DashLine",
        "ui/light/zoom_box_color": "#000000",
        "ui/light/zoom_box_style": "DashLine",

        # Grid Settings
        "ui/grid_enabled": False,
        "ui/grid_alpha": 30,
        "ui/axis_font_size": 10,
        "ui/label_precision": 6,
        
        # Dark Grid
        "ui/dark/grid_color": "#c8c8ff",
        "ui/dark/grid_style": "SolidLine",
        
        # Light Grid
        "ui/light/grid_color": "#000000",
        "ui/light/grid_style": "SolidLine",

        "keybinds/time_markers": "T",
        "keybinds/mag_markers": "F",
        "keybinds/zoom_mode": "Ctrl"
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
        val = self.settings.value(key, default)
        if isinstance(val, str):
            if val.lower() == "true": return True
            if val.lower() == "false": return False
        return val

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

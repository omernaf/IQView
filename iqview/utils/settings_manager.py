from PyQt6.QtCore import QSettings

class SettingsManager:
    """
    Manages application settings and persistence using QSettings.
    """
    DEFAULT_SETTINGS = {
        "core/fc": 0.0,
        "core/fs": 1e6,
        "core/fft_size": 1024,
        "core/overlap": 100.0,
        "core/window_type": "Hamming",
        "core/type": "complex64",
        "core/filter_type": "Elliptic",
        "core/filter_order": 8,
        "core/filter_ripple": 0.1,
        "core/filter_stopband": 60.0,
        "core/filter_bessel_norm": "phase",
        "core/extension_mapping": {
            '.32f': 'float32',
            '.64f': 'float64',
            '.16tc': 'int16',
            '.16sc': 'int16',
            '.64fc': 'complex128',
            '.32fc': 'complex64',
            '.bin': 'complex64',
            '.iq': 'complex64',
            '.r3f': 'complex64',
            '.mat': 'complex64',
            # Audio formats — loaded via soundfile/scipy, sample rate from header
            '.wav': 'audio',
            '.flac': 'audio',
            '.ogg': 'audio',
            '.oga': 'audio',
            '.aiff': 'audio',
            '.aif': 'audio',
            '.aifc': 'audio',
            '.au': 'audio',
            '.snd': 'audio',
            '.w64': 'audio',
            '.rf64': 'audio',
            '.caf': 'audio',
            '.sd2': 'audio',
        },
        "core/time_plots": [
            "magnitude [dB]",
            "Real",
            "Imaginary",
            "instant frequency"
        ],
        "core/inst_freq_filter_len": 7,
        "core/frequency_plots": [
            "power spectrum density (PSD)",
            "magnitude [dBFS]",
            "magnitude"
        ],
        "core/psd_algorithm": "Welch",
        "core/lazy_rendering": True,
        "ui/theme": "Light",
        "ui/colormap": "turbo",
        "ui/colormap_reversed": False,
        "ui/waterfall": False,
        
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

        # Grid Settings (axis background grid)
        "ui/grid_enabled": False,
        "ui/grid_alpha": 30,
        "ui/axis_font_size": 10,
        "ui/label_precision": 6,
        "ui/show_inv_time": False,
        
        # Dark Axis Grid
        "ui/dark/grid_color": "#c8c8ff",
        "ui/dark/grid_style": "SolidLine",
        
        # Light Axis Grid
        "ui/light/grid_color": "#000000",
        "ui/light/grid_style": "SolidLine",

        # Marker Grid (cyclic continuation lines)
        "ui/marker_grid_alpha": 50,
        "ui/marker_grid_width": 1,

        # Dark Marker Grid
        "ui/dark/marker_grid_color": "#c8c8ff",
        "ui/dark/marker_grid_style": "SolidLine",

        # Light Marker Grid
        "ui/light/marker_grid_color": "#0000cc",
        "ui/light/marker_grid_style": "SolidLine",

        # Keybinds — Navigation & View (Hold / Action)
        "keybinds/zoom_mode": "Ctrl",
        "keybinds/move_mode": "Space",
        "keybinds/reset_zoom": "R",
        "keybinds/undo_zoom": "Z",
        "keybinds/clear_markers": "Backspace",
        "keybinds/open_settings": "I",

        # Keybinds — Marker Modes
        "keybinds/time_markers": "T",
        "keybinds/time_endless_markers": "E",
        "keybinds/freq_markers": "F",
        "keybinds/freq_endless_markers": "G",
        "keybinds/mag_markers": "M",
        "keybinds/mag_endless_markers": "N",

        # Keybinds — Analysis & Tool Modes
        "keybinds/filter_mode": "B",
        "keybinds/stats_mode": "S",
        "keybinds/overlay_mode": "O",
        "keybinds/plugins_mode": "P",

        # Keybinds — Marker Locks & Sub-Controls
        "keybinds/lock_m1": "1",
        "keybinds/lock_m2": "2",
        "keybinds/lock_delta": "D",
        "keybinds/lock_center": "C",
        "keybinds/stats_def": "Q",
        "keybinds/stats_res": "W",
        "keybinds/toggle_bpf": "[",
        "keybinds/toggle_bsf": "]",
        "keybinds/panel_action": "A",

        # Keybinds — Plot Mode Toolbar Buttons
        "keybinds/plot_mode_1": "F1",
        "keybinds/plot_mode_2": "F2",
        "keybinds/plot_mode_3": "F3",
        "keybinds/plot_mode_4": "F4",
        "keybinds/plot_mode_5": "F5",
        "keybinds/plot_mode_6": "F6",
        "keybinds/plot_mode_7": "F7",
        "keybinds/plot_mode_8": "F8",
        "keybinds/plot_mode_9": "F9",
        "keybinds/plot_mode_10": "F10"
    }

    def __init__(self):
        # Organization and Application names help define where QSettings saves (Registry on Windows)
        self.settings = QSettings("IQViewProject", "IQView")
        self._set_defaults()

    def _set_defaults(self):
        # Migrate legacy mag_markers="F" if freq_markers is being introduced for the first time
        if not self.settings.contains("keybinds/freq_markers"):
            if self.settings.value("keybinds/mag_markers") == "F":
                self.settings.setValue("keybinds/mag_markers", "M")

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

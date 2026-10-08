---
type: moc
tags:
  - code/moc
  - architecture
title: "MOC - System Architecture"
---

# 🏛️ MOC - System Architecture

IQView is structured around a composite main window class ([`SpectrogramWindow`](../MainWindow/SpectrogramWindow.md)) composed of multiple modular mixins that decouple UI construction, data handling, markers, overlays, view control, and plugin execution.

```mermaid
classDiagram
    class SpectrogramWindow {
        +apply_current_theme()
        +resize(1280, 800)
    }
    class UIComponentsMixin {
        +init_ui()
        +create_toolbar()
    }
    class MarkerManagerMixin {
        +place_marker()
        +update_marker_info()
    }
    class OverlayManagerMixin {
        +add_overlay()
        +delete_selected()
    }
    class ViewControllerMixin {
        +open_time_domain_tab()
        +open_frequency_domain_tab()
        +open_eye_diagram_tab()
        +open_constellation_tab()
    }
    class DataHandlerMixin {
        +load_data()
        +start_processing()
    }
    class PluginManagerMixin {
        +run_plugin()
        +apply_plugin_result()
    }

    SpectrogramWindow --|> UIComponentsMixin
    SpectrogramWindow --|> MarkerManagerMixin
    SpectrogramWindow --|> OverlayManagerMixin
    SpectrogramWindow --|> ViewControllerMixin
    SpectrogramWindow --|> DataHandlerMixin
    SpectrogramWindow --|> PluginManagerMixin
```

---

## 🧩 Architectural Modules

### Core Window & Mixins
- **[[SpectrogramWindow]]**: Central Qt container and window state orchestrator.
- **[[ViewControllerMixin]]**: Coordinates tab addition, large segment validation, and tab tear-off.
- **[[MarkerManagerMixin]]**: Manages spectrogram 2D markers, Delta/Center locks, and marker tables.
- **[[OverlayManagerMixin]]**: Handles drawing, selecting, locking, and JSON serialization of overlays.
- **[[ComponentSetupMixin]]**: Assembles toolbar actions, menus, shortcuts, and side panels.
- **[[DataHandlerMixin]]**: Manages data ingestion, background thread dispatch, and normalization.

### Subsystem Maps
- **[[MOC - Views Hierarchy]]**: Specialized 1D, 2D, and modulation analysis tabs.
- **[[MOC - DSP Pipeline]]**: Decoupled digital signal processing and spectral routines.
- **[[MOC - Plugin Subsystem]]**: Modular plugin execution, parameters, and in-memory caching.
- **[[MOC - IO and Formats]]**: File formats, streaming, and byte slicing.

---

## 🔗 Related Notes
- [[00 - Index (Map of Content)]]
- [[Flow - Viewport Lazy Spectrogram Rendering]]
- [[Flow - Marker to Analysis Tab Slicing]]

---
type: flow
tags:
  - code/flow
title: "Flow - Plugin Execution and Overlay Ingestion"
---

# 🔄 Flow - Plugin Execution and Overlay Ingestion

Traces the asynchronous execution of plugins and the atomic injection of overlays back into the main UI.

```mermaid
sequenceDiagram
    participant User as User
    participant Studio as PluginStudioDialog
    participant Worker as Background QThread
    participant Plugin as Plugin run()
    participant Overlays as OverlayManagerMixin
    participant Spec as SpectrogramView

    User->>Studio: Select Scope & Click "Run"
    Studio->>Worker: Dispatch with PluginContext (info)
    Worker->>Plugin: run(samples, info)
    loop Each Algorithm Step
        Plugin->>Worker: info.progress(pct, "Status")
        Worker->>User: Update modal progress dialog
        alt User clicked Cancel
            User->>Worker: Cancel requested
            Worker->>Plugin: info.is_cancelled() == True
            Plugin-->>Worker: Exit loop promptly
        end
    end
    Plugin->>Worker: Return PluginResult (result)
    Worker->>Overlays: add_overlays(result.overlays)
    Overlays->>Spec: Draw Rect, Polygon, Ellipse items
    Spec->>User: Overlays appear on canvas (locked by default)
```

---

## 🔗 Related Notes
- [[MOC - Plugin Subsystem]]
- [[Plugin System 2.0]]
- [[PluginContext]]
- [[Overlays Hierarchy]]

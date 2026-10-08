---
type: flow
tags:
  - code/flow
title: "Flow - Marker to Analysis Tab Slicing"
---

# 🔄 Flow - Marker to Analysis Tab Slicing

Traces how user-placed time markers extract calibrated IQ segments into pop-up analysis tabs.

```mermaid
sequenceDiagram
    participant User as User
    participant Markers as MarkerManagerMixin
    participant VC as ViewControllerMixin
    participant Data as DataHandlerMixin
    participant Tab as TimeDomainView / EyeDiagramView

    User->>Markers: Place Time Markers M1, M2 [t1, t2]
    User->>VC: Click "Time Domain" or "Eye Diagram"
    VC->>VC: Check sample count > 10,000,000?
    alt Exceeds 10M Samples
        VC->>User: Prompt confirmation dialog
    end
    VC->>Data: extract_iq_segment(t1, t2)
    Data->>Data: Read disk slice & apply norm_factor
    Data->>VC: Return calibrated complex64 array
    VC->>Tab: Instantiate view(samples, rate, parent)
    VC->>VC: tabs.addTab(view, "Analysis Tab")
    Tab->>User: Display interactive plot with MATLAB blue traces
```

---

## 🔗 Related Notes
- [[MOC - Views Hierarchy]]
- [[ViewControllerMixin]]
- [[TimeDomainView]]
- [[EyeDiagramView]]

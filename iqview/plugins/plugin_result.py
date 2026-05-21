"""iqview/plugins/plugin_result.py

PluginResult — the return type for all IQView plugin run() functions.

Plugin authors import this from the top-level package:

    from iqview import PluginResult

Operations
----------
.add(overlay)              — queue a new overlay to be added to the spectrogram.
.update(id, **fields)      — patch fields on an existing overlay by its id.
.remove(id)                — remove an existing overlay by its id.
                             Restricted to overlays owned by this plugin
                             (source == "plugin:<name>").  Attempting to remove
                             a user- or other-plugin-owned overlay is silently
                             skipped with a console warning.
.replace(id, new_overlay)  — atomically swap an overlay out; the replacement
                             inherits the original overlay's source.

All four methods return self so calls can be chained:

    result = PluginResult().add(r1).add(r2).update(some_id, color="#ff0000")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from iqview.ui.overlay import Overlay


class PluginResult:
    """
    Encapsulates the set of overlay operations that a plugin wishes to perform.

    Returned by a plugin's ``run(samples, info)`` function.  IQView's plugin
    runner processes each operation list in order:
      1. removes
      2. replaces
      3. updates
      4. adds

    Attributes
    ----------
    _adds     : list[Overlay]
    _updates  : list[tuple[str, dict]]   — (overlay_id, field_kwargs)
    _removes  : list[str]                — overlay IDs
    _replaces : list[tuple[str, Overlay]]— (old_overlay_id, new_overlay)
    """

    def __init__(self) -> None:
        self._adds:     List[Any]                    = []
        self._updates:  List[Tuple[str, Dict]]       = []
        self._removes:  List[str]                    = []
        self._replaces: List[Tuple[str, Any]]        = []

    # ------------------------------------------------------------------
    # Builder methods (all return self for chaining)
    # ------------------------------------------------------------------

    def add(self, overlay) -> "PluginResult":
        """
        Queue *overlay* to be added as a new overlay on the spectrogram.

        The runner will assign a fresh UUID and set ``source`` to the
        plugin's name before adding, so IDs returned by ``info["overlays"]``
        are never re-used.

        Parameters
        ----------
        overlay : Overlay
            Any overlay object from ``iqview.overlays`` (Rect, VerticalLine, …).
        """
        self._adds.append(overlay)
        return self

    def update(self, overlay_id: str, **fields) -> "PluginResult":
        """
        Queue a partial update of an existing overlay identified by *overlay_id*.

        Any keyword argument that matches an ``Overlay`` field name will be
        applied via ``setattr``.  Unknown keys are silently ignored.

        ``source`` *can* be changed here — do so intentionally, since changing
        ``source`` away from ``"user"`` will exclude the overlay from sidecar
        saves.

        Parameters
        ----------
        overlay_id : str
            The ``id`` attribute of the overlay to update (from ``info["overlays"]``).
        **fields
            Overlay field names and their new values, e.g.
            ``color="#ff0000"``, ``points=[...]``, ``display_str="label"``.
        """
        self._updates.append((overlay_id, fields))
        return self

    def remove(self, overlay_id: str) -> "PluginResult":
        """
        Queue removal of an overlay by *overlay_id*.

        The runner enforces source-ownership: only overlays whose ``source``
        equals ``"plugin:<plugin_name>"`` can be removed.  Attempts to remove
        user-drawn or other-plugin-owned overlays are silently skipped with a
        console warning.

        Parameters
        ----------
        overlay_id : str
            The ``id`` attribute of the overlay to remove.
        """
        self._removes.append(overlay_id)
        return self

    def replace(self, overlay_id: str, new_overlay) -> "PluginResult":
        """
        Queue an atomic swap: remove *overlay_id* and add *new_overlay* in its
        place.  The replacement inherits the original overlay's ``source`` so
        provenance is preserved.

        Parameters
        ----------
        overlay_id : str
            The ``id`` attribute of the overlay to replace.
        new_overlay : Overlay
            The new overlay object to insert.
        """
        self._replaces.append((overlay_id, new_overlay))
        return self

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"PluginResult("
            f"adds={len(self._adds)}, "
            f"updates={len(self._updates)}, "
            f"removes={len(self._removes)}, "
            f"replaces={len(self._replaces)})"
        )

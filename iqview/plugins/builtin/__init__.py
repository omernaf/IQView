"""iqview/plugins/builtin/__init__.py

Registry of modular built-in IQView plugins that ship with the package and
can be run standalone or composed into a `PluginChain`.
"""

from __future__ import annotations

import os
from types import ModuleType
from typing import Dict, List, Optional

from . import (
    bit_reversal,
    block_fec_decoder,
    burst_energy_detector,
    burst_metrics,
    channelizer_detector,
    crc_checker,
    diff_decoder,
    fsk_demodulator,
    lora_demodulator,
    snap_merge_overlays,
    snap_to_burst,
    uw_sync,
    xor_mask,
)

BUILTIN_MODULES: List[ModuleType] = [
    channelizer_detector,
    burst_energy_detector,
    snap_to_burst,
    fsk_demodulator,
    lora_demodulator,
    uw_sync,
    diff_decoder,
    xor_mask,
    bit_reversal,
    block_fec_decoder,
    crc_checker,
    burst_metrics,
    snap_merge_overlays,
]

# Lookup table by PLUGIN_NAME (and lowercase/stem aliases)
_BUILTIN_MAP: Dict[str, ModuleType] = {}
for _mod in BUILTIN_MODULES:
    _name = getattr(_mod, "PLUGIN_NAME", "")
    _stem = os.path.splitext(os.path.basename(getattr(_mod, "__file__", "")))[0]
    if _name:
        _BUILTIN_MAP[_name] = _mod
        _BUILTIN_MAP[_name.lower()] = _mod
    if _stem:
        _BUILTIN_MAP[_stem] = _mod
        _BUILTIN_MAP[_stem.lower()] = _mod

# Common alias for examples/plugins/channelizer_energy_detector.py
_BUILTIN_MAP["channelizer_energy_detector"] = channelizer_detector


def get_builtin_plugin(name_or_id: str) -> Optional[ModuleType]:
    """Return a built-in plugin module by its `PLUGIN_NAME` or module stem, or `None`."""
    if not name_or_id:
        return None
    key = str(name_or_id).strip()
    return _BUILTIN_MAP.get(key) or _BUILTIN_MAP.get(key.lower())


def get_builtin_plugin_paths() -> List[str]:
    """Return the absolute `.py` file paths of all built-in plugins in display order."""
    paths = []
    for mod in BUILTIN_MODULES:
        f = getattr(mod, "__file__", None)
        if f and os.path.isfile(f):
            paths.append(os.path.normpath(os.path.abspath(f)))
    return paths

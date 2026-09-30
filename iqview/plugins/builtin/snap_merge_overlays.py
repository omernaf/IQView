"""iqview/plugins/builtin/snap_merge_overlays.py

Built-in IQView Plugin: Snap & Merge Overlays.

Cleans up `Rect` overlays by merging fragmented/overlapping burst detections
that share a frequency channel and optionally snapping time/frequency bounds
to a regular grid.
"""

from __future__ import annotations

import copy
import numpy as np

from iqview import PluginResult


PLUGIN_NAME              = "Snap & Merge Overlays"
PLUGIN_DESCRIPTION       = (
    "Merges overlapping or closely-spaced Rect burst detections on the same "
    "frequency band and optionally snaps time/frequency edges to a grid."
)
PLUGIN_CATEGORY          = "Post-Processing"
PLUGIN_NEEDS_WIDEBAND_IQ = False


PLUGIN_PARAMS = {
    "merge_time_gap_ms": {
        "type": "float",
        "default": 1.0,
        "label": "Max Time Gap to Merge (ms)",
        "tooltip": (
            "Merge two Rect overlays on the same frequency band if the time gap "
            "between them is less than or equal to this value (ms). Set < 0 to disable merging."
        ),
    },
    "min_freq_overlap": {
        "type": "float",
        "default": 0.5,
        "label": "Min Frequency Overlap (0–1)",
        "tooltip": (
            "Minimum fractional frequency overlap (relative to the narrower Rect) "
            "required to merge two bursts."
        ),
    },
    "snap_time_ms": {
        "type": "float",
        "default": 0.0,
        "label": "Snap Time Grid (ms, 0 = Off)",
        "tooltip": "When > 0, snaps t_start and t_end to multiples of this step (in ms).",
    },
    "snap_freq_hz": {
        "type": "float",
        "default": 0.0,
        "label": "Snap Frequency Grid (Hz, 0 = Off)",
        "tooltip": "When > 0, snaps f_start and f_end to multiples of this step (in Hz).",
    },
    "min_duration_ms": {
        "type": "float",
        "default": 0.0,
        "label": "Min Duration Filter (ms, 0 = Off)",
        "tooltip": "When > 0, removes Rect overlays shorter than this duration (after merging).",
    },
}


def _freq_overlap_ratio(f0_a: float, f1_a: float, f0_b: float, f1_b: float) -> float:
    inter = max(0.0, min(f1_a, f1_b) - max(f0_a, f0_b))
    min_bw = min(max(1e-9, f1_a - f0_a), max(1e-9, f1_b - f0_b))
    return inter / min_bw


def _concat_cached_iq(o_a, t0_a: float, t1_a: float, o_b, t0_b: float, t1_b: float):
    """If both overlays have cached IQ at matching sample rate and frequency center, stitch them."""
    iq_a = getattr(o_a, "iq", None)
    iq_b = getattr(o_b, "iq", None)
    fs_a = getattr(o_a, "fs", None)
    fs_b = getattr(o_b, "fs", None)
    if iq_a is None or iq_b is None or fs_a is None or fs_b is None:
        return None, None
    if fs_a <= 0 or abs(fs_a - fs_b) / max(fs_a, fs_b) > 1e-2:
        return None, None
    fc_a = 0.5 * (o_a.f_start + o_a.f_end)
    fc_b = 0.5 * (o_b.f_start + o_b.f_end)
    if abs(fc_a - fc_b) > 0.05 * fs_a:
        return None, None

    if t0_b >= t1_a:
        gap_s = t0_b - t1_a
        gap_n = max(0, int(round(gap_s * fs_a)))
        if gap_n > 0:
            zeros = np.zeros(gap_n, dtype=np.complex64)
            stitched = np.concatenate([np.asarray(iq_a, dtype=np.complex64), zeros, np.asarray(iq_b, dtype=np.complex64)])
        else:
            stitched = np.concatenate([np.asarray(iq_a, dtype=np.complex64), np.asarray(iq_b, dtype=np.complex64)])
        return stitched, float(fs_a)
    elif t1_b > t1_a:
        # Partial time overlap
        overlap_s = t1_a - t0_b
        skip_n = min(len(iq_b), max(0, int(round(overlap_s * fs_a))))
        stitched = np.concatenate([np.asarray(iq_a, dtype=np.complex64), np.asarray(iq_b[skip_n:], dtype=np.complex64)])
        return stitched, float(fs_a)
    return np.asarray(iq_a, dtype=np.complex64), float(fs_a)


def run(samples: np.ndarray, info) -> PluginResult:
    result = PluginResult()

    params = info.params
    merge_gap_s      = float(params.get("merge_time_gap_ms", 1.0)) * 1e-3
    min_freq_overlap = float(np.clip(params.get("min_freq_overlap", 0.5), 0.0, 1.0))
    snap_time_s      = float(params.get("snap_time_ms", 0.0)) * 1e-3
    snap_freq_hz     = float(params.get("snap_freq_hz", 0.0))
    min_dur_s        = float(params.get("min_duration_ms", 0.0)) * 1e-3

    t_start_scope = float(info.t_start)
    t_end_scope   = float(info.t_end)
    f_start_scope = float(info.f_start)
    f_end_scope   = float(info.f_end)

    rects = []
    for o in info.overlays:
        sh = o.shape.value if hasattr(o.shape, "value") else str(o.shape)
        if sh != "RECT":
            continue
        if o.t_end < t_start_scope or o.t_start > t_end_scope:
            continue
        if o.f_end < f_start_scope or o.f_start > f_end_scope:
            continue
        rects.append(o)

    if not rects:
        result.log("No Rect overlays in active scope.")
        return result

    # Sort by t_start
    rects.sort(key=lambda r: (float(r.t_start), float(r.f_start)))

    # Working records: [overlay_obj, t0, t1, f0, f1, iq, fs, merged_count, changed]
    working = [
        {
            "o": r,
            "t0": float(r.t_start),
            "t1": float(r.t_end),
            "f0": float(r.f_start),
            "f1": float(r.f_end),
            "iq": getattr(r, "iq", None),
            "fs": getattr(r, "fs", None),
            "merged": 1,
            "changed": False,
        }
        for r in rects
    ]
    removed_ids = []

    if merge_gap_s >= 0.0 and len(working) > 1:
        kept = []
        for item in working:
            merged_into_existing = False
            for target in reversed(kept):
                if (item["t0"] - target["t1"]) > merge_gap_s:
                    # Since sorted by t0, earlier items with t1 too far back might not match,
                    # but another channel could still have a later t1, so check all active
                    continue
                ov_ratio = _freq_overlap_ratio(
                    target["f0"], target["f1"], item["f0"], item["f1"]
                )
                if ov_ratio >= min_freq_overlap and (item["t0"] - target["t1"]) <= merge_gap_s:
                    stitched_iq, stitched_fs = _concat_cached_iq(
                        target["o"], target["t0"], target["t1"],
                        item["o"], item["t0"], item["t1"],
                    )
                    target["t0"] = min(target["t0"], item["t0"])
                    target["t1"] = max(target["t1"], item["t1"])
                    target["f0"] = min(target["f0"], item["f0"])
                    target["f1"] = max(target["f1"], item["f1"])
                    target["iq"] = stitched_iq
                    target["fs"] = stitched_fs
                    target["merged"] += 1
                    target["changed"] = True
                    removed_ids.append(item["o"].id)
                    merged_into_existing = True
                    break
            if not merged_into_existing:
                kept.append(item)
        working = kept

    n_updated = 0
    for item in working:
        t0, t1 = item["t0"], item["t1"]
        f0, f1 = item["f0"], item["f1"]

        if snap_time_s > 0:
            new_t0 = np.floor(t0 / snap_time_s) * snap_time_s
            new_t1 = np.ceil(t1 / snap_time_s) * snap_time_s
            if new_t1 <= new_t0:
                new_t1 = new_t0 + snap_time_s
            if abs(new_t0 - t0) > 1e-12 or abs(new_t1 - t1) > 1e-12:
                t0, t1 = float(new_t0), float(new_t1)
                item["changed"] = True

        if snap_freq_hz > 0:
            new_f0 = np.floor(f0 / snap_freq_hz) * snap_freq_hz
            new_f1 = np.ceil(f1 / snap_freq_hz) * snap_freq_hz
            if new_f1 <= new_f0:
                new_f1 = new_f0 + snap_freq_hz
            if abs(new_f0 - f0) > 1e-6 or abs(new_f1 - f1) > 1e-6:
                f0, f1 = float(new_f0), float(new_f1)
                item["changed"] = True

        if min_dur_s > 0 and (t1 - t0) < min_dur_s:
            removed_ids.append(item["o"].id)
            continue

        if item["changed"]:
            o = item["o"]
            new_meta = copy.deepcopy(getattr(o, "metadata", {}) or {})
            new_meta["duration_ms"] = round((t1 - t0) * 1e3, 4)
            if item["merged"] > 1:
                new_meta["merged_bursts"] = int(item["merged"])

            update_fields = {
                "points": [(t0, f0), (t1, f1)],
                "metadata": new_meta,
                "iq": item["iq"],
                "fs": item["fs"],
            }
            result.update(o.id, **update_fields)
            n_updated += 1

    for oid in removed_ids:
        result.remove(oid)

    result.log(f"Updated {n_updated} overlay(s), removed/merged {len(removed_ids)} overlay(s)")
    info.progress(100, "Done")
    return result

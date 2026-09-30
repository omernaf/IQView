"""iqview/plugins/chain.py

PluginChain — declarative & programmatic multi-step plugin pipeline engine,
single-step re-execution runner, and `.py` chain code generator.

Example usage in a `.py` plugin file:

    from iqview import PluginChain

    PLUGIN_NAME = "Channelize + FSK Demod"
    PLUGIN_DESCRIPTION = "Channelizer energy detector followed by 2-FSK demodulation"
    PLUGIN_CATEGORY = "Chains"

    CHAIN = PluginChain([
        ("Channelizer + Energy Detector", {"channel_spacing": 25e3, "threshold_db": 6.0}),
        ("FSK Demodulator", {"baud_rate": 0.0, "debug_plots": True}),
    ])
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import os
import pprint
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from iqview.plugins.context import PluginContext, PluginParams
from iqview.plugins.plugin_result import PluginResult


class PluginChain:
    """
    Defines an ordered pipeline of IQView plugins with baked-in default parameters
    per step, propagating `info.overlays` (including cached per-burst `o.iq` and
    `o.fs`) in memory from step to step.

    Supports running:
      * the full chain (`chain.run(samples, info)`)
      * a single step (`chain.run(samples, info, only_step=k)`)
      * from step `k` onward (`chain.run(samples, info, from_step=k)`)
    """

    def __init__(
        self,
        steps: Sequence[Any],
        name: Optional[str] = None,
        description: str = "",
        category: str = "Chains",
        base_dir: Optional[str] = None,
    ) -> None:
        self.name = name
        self.description = description
        self.category = category
        self._base_dir = base_dir
        self._resolver: Optional[Callable[[Any], Optional[Dict[str, Any]]]] = None
        self._file_module_cache: Dict[str, Any] = {}

        self.steps: List[Dict[str, Any]] = []
        for idx, item in enumerate(steps):
            self.steps.append(self._normalize_step_spec(idx, item))

    @staticmethod
    def _normalize_step_spec(idx: int, item: Any) -> Dict[str, Any]:
        if isinstance(item, dict):
            target = item.get("plugin") or item.get("target") or item.get("name")
            params = dict(item.get("params") or {})
            label = item.get("label")
        elif isinstance(item, (tuple, list)):
            target = item[0]
            params = dict(item[1]) if len(item) > 1 and isinstance(item[1], dict) else {}
            label = str(item[2]) if len(item) > 2 and item[2] else None
        else:
            target = item
            params = {}
            label = None

        return {
            "index": idx,
            "target": target,
            "params": params,
            "label": label,
        }

    def set_resolver(self, resolver: Optional[Callable[[Any], Optional[Dict[str, Any]]]]) -> None:
        """Set a callback `resolver(target) -> plugin_info_dict` used to look up loaded plugins."""
        self._resolver = resolver

    def set_base_dir(self, base_dir: Optional[str]) -> None:
        self._base_dir = base_dir

    # ------------------------------------------------------------------
    # Step Target Resolution
    # ------------------------------------------------------------------

    def _load_module_from_file(self, path: str) -> Optional[Any]:
        norm = os.path.normpath(os.path.abspath(path))
        mtime = os.path.getmtime(norm) if os.path.isfile(norm) else 0.0
        cached = self._file_module_cache.get(norm)
        if cached is not None and cached[0] >= mtime:
            return cached[1]
        if not os.path.isfile(norm):
            return None
        stem = os.path.splitext(os.path.basename(norm))[0]
        mod_name = f"_iqview_chain_step_{stem}_{uuid.uuid4().hex[:6]}"
        spec = importlib.util.spec_from_file_location(mod_name, norm)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "CHAIN") and isinstance(mod.CHAIN, PluginChain) and not hasattr(mod, "run"):
            mod.CHAIN.bind_to_module(mod, module_path=norm)
        self._file_module_cache[norm] = (mtime, mod)
        return mod

    def resolve_step(self, step_index: int) -> Dict[str, Any]:
        """
        Resolve step `step_index` to a dictionary with keys:
          `name`, `func`, `params_spec`, `needs_wideband_iq`, `path`, `step_overrides`
        """
        step = self.steps[step_index]
        target = step["target"]
        overrides = step["params"]

        # 1. Custom resolver (e.g. PluginManagerMixin._loaded_plugins)
        if self._resolver is not None and isinstance(target, str):
            resolved = self._resolver(target)
            if isinstance(resolved, dict) and callable(resolved.get("func")):
                return {
                    "name": step["label"] or resolved.get("name") or target,
                    "func": resolved["func"],
                    "params_spec": copy.deepcopy(resolved.get("params_spec") or {}),
                    "needs_wideband_iq": bool(resolved.get("needs_wideband_iq", True)),
                    "path": resolved.get("path"),
                    "step_overrides": overrides,
                }

        # 2. Module object with .run
        if hasattr(target, "run") and callable(target.run):
            mod = target
            name = step["label"] or getattr(mod, "PLUGIN_NAME", getattr(mod, "__name__", f"Step {step_index + 1}"))
            return {
                "name": str(name),
                "func": mod.run,
                "params_spec": copy.deepcopy(getattr(mod, "PLUGIN_PARAMS", {}) or {}),
                "needs_wideband_iq": bool(getattr(mod, "PLUGIN_NEEDS_WIDEBAND_IQ", True)),
                "path": getattr(mod, "__file__", None),
                "step_overrides": overrides,
            }

        # 3. Direct callable
        if callable(target):
            name = step["label"] or getattr(target, "__name__", f"Step {step_index + 1}")
            return {
                "name": str(name),
                "func": target,
                "params_spec": copy.deepcopy(getattr(target, "PLUGIN_PARAMS", {}) or {}),
                "needs_wideband_iq": bool(getattr(target, "PLUGIN_NEEDS_WIDEBAND_IQ", True)),
                "path": None,
                "step_overrides": overrides,
            }

        # 4. String: check built-in registry or file path
        if isinstance(target, str):
            from iqview.plugins.builtin import get_builtin_plugin
            builtin_mod = get_builtin_plugin(target)
            if builtin_mod is not None:
                name = step["label"] or getattr(builtin_mod, "PLUGIN_NAME", target)
                return {
                    "name": str(name),
                    "func": builtin_mod.run,
                    "params_spec": copy.deepcopy(getattr(builtin_mod, "PLUGIN_PARAMS", {}) or {}),
                    "needs_wideband_iq": bool(getattr(builtin_mod, "PLUGIN_NEEDS_WIDEBAND_IQ", True)),
                    "path": getattr(builtin_mod, "__file__", None),
                    "step_overrides": overrides,
                }

            # Try file paths (direct, relative to chain's base_dir, or examples/plugins)
            candidate_paths = [target]
            if not target.endswith(".py"):
                candidate_paths.append(target + ".py")
            if self._base_dir:
                candidate_paths.append(os.path.join(self._base_dir, target))
                if not target.endswith(".py"):
                    candidate_paths.append(os.path.join(self._base_dir, target + ".py"))

            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            examples_dir = os.path.join(repo_root, "examples", "plugins")
            candidate_paths.append(os.path.join(examples_dir, target))
            if not target.endswith(".py"):
                candidate_paths.append(os.path.join(examples_dir, target + ".py"))

            for cp in candidate_paths:
                if os.path.isfile(cp):
                    mod = self._load_module_from_file(cp)
                    if mod is not None and hasattr(mod, "run") and callable(mod.run):
                        name = step["label"] or getattr(mod, "PLUGIN_NAME", os.path.splitext(os.path.basename(cp))[0])
                        return {
                            "name": str(name),
                            "func": mod.run,
                            "params_spec": copy.deepcopy(getattr(mod, "PLUGIN_PARAMS", {}) or {}),
                            "needs_wideband_iq": bool(getattr(mod, "PLUGIN_NEEDS_WIDEBAND_IQ", True)),
                            "path": os.path.normpath(os.path.abspath(cp)),
                            "step_overrides": overrides,
                        }

        raise ValueError(
            f"PluginChain step {step_index + 1} could not resolve plugin target: {target!r}"
        )

    # ------------------------------------------------------------------
    # Combined Schema & Metadata Synthesis
    # ------------------------------------------------------------------

    def get_params_spec(self) -> Dict[str, Dict[str, Any]]:
        """
        Build the combined `PLUGIN_PARAMS` dictionary for all steps in the chain.
        Keys are namespaced as `step{i}.{param_key}` and annotated with `step_index`,
        `step_name`, `step_title`, and `raw_key` so UI dialogs can group them by step.
        """
        combined: Dict[str, Dict[str, Any]] = {}
        for idx in range(len(self.steps)):
            try:
                resolved = self.resolve_step(idx)
                step_name = resolved["name"]
                base_spec = resolved["params_spec"]
                overrides = resolved["step_overrides"]
            except Exception:
                step_name = str(self.steps[idx]["target"])
                base_spec = {}
                overrides = self.steps[idx]["params"]

            step_title = f"Step {idx + 1}: {step_name}"

            # Include all parameters from the step's base schema
            seen_keys = set()
            for raw_key, spec in base_spec.items():
                seen_keys.add(raw_key)
                if not isinstance(spec, dict):
                    spec = {"type": type(spec).__name__, "default": spec, "label": raw_key}
                else:
                    spec = copy.deepcopy(spec)

                if raw_key in overrides:
                    spec["default"] = overrides[raw_key]

                spec["step_index"] = idx
                spec["step_name"] = step_name
                spec["step_title"] = step_title
                spec["raw_key"] = raw_key
                combined[f"step{idx}.{raw_key}"] = spec

            # Also include any override keys that weren't in base_spec
            for raw_key, val in overrides.items():
                if raw_key in seen_keys:
                    continue
                t_name = "bool" if isinstance(val, bool) else ("int" if isinstance(val, int) else ("float" if isinstance(val, float) else "str"))
                combined[f"step{idx}.{raw_key}"] = {
                    "type": t_name,
                    "default": val,
                    "label": raw_key,
                    "step_index": idx,
                    "step_name": step_name,
                    "step_title": step_title,
                    "raw_key": raw_key,
                }

        return combined

    def get_step_metadata(self) -> List[Dict[str, Any]]:
        """Return a summary list of steps (`index`, `name`, `title`, `needs_wideband_iq`)."""
        meta = []
        for idx in range(len(self.steps)):
            try:
                r = self.resolve_step(idx)
                meta.append({
                    "index": idx,
                    "name": r["name"],
                    "title": f"Step {idx + 1}: {r['name']}",
                    "needs_wideband_iq": r["needs_wideband_iq"],
                    "path": r.get("path"),
                })
            except Exception:
                t = str(self.steps[idx]["target"])
                meta.append({
                    "index": idx,
                    "name": t,
                    "title": f"Step {idx + 1}: {t}",
                    "needs_wideband_iq": True,
                    "path": None,
                })
        return meta

    def needs_wideband_iq(
        self,
        only_step: Optional[int] = None,
        from_step: int = 0,
    ) -> bool:
        """Return True if any step in the requested execution subset requires wideband IQ."""
        indices = (
            [int(only_step)]
            if only_step is not None
            else list(range(max(0, int(from_step)), len(self.steps)))
        )
        for idx in indices:
            if 0 <= idx < len(self.steps):
                try:
                    if self.resolve_step(idx)["needs_wideband_iq"]:
                        return True
                except Exception:
                    return True
        return False

    def _build_step_params(self, step_index: int, resolved: Dict[str, Any], chain_params: Any) -> PluginParams:
        """Construct the un-prefixed `PluginParams` for `step_index`."""
        step_dict: Dict[str, Any] = {}
        for k, spec in resolved["params_spec"].items():
            if isinstance(spec, dict):
                step_dict[k] = spec.get("default")
            else:
                step_dict[k] = spec

        # Apply baked-in step overrides from chain definition
        for k, v in resolved["step_overrides"].items():
            step_dict[k] = v

        # Apply runtime parameter overrides from `info.params`
        if chain_params is not None:
            if hasattr(chain_params, "to_dict"):
                raw_map = chain_params.to_dict()
            elif hasattr(chain_params, "items"):
                raw_map = dict(chain_params.items())
            elif isinstance(chain_params, dict):
                raw_map = dict(chain_params)
            else:
                raw_map = {}

            prefix = f"step{step_index}."
            # First allow unprefixed overrides if present
            for k in list(step_dict.keys()):
                if k in raw_map:
                    step_dict[k] = raw_map[k]
            # Then apply explicit step-prefixed overrides (highest priority)
            for full_k, val in raw_map.items():
                if str(full_k).startswith(prefix):
                    short_k = str(full_k)[len(prefix):]
                    step_dict[short_k] = val

        return PluginParams(step_dict)

    # ------------------------------------------------------------------
    # Execution Engine (Full Chain, Single Step, or From Step k)
    # ------------------------------------------------------------------

    def run(
        self,
        samples: np.ndarray,
        info: PluginContext,
        only_step: Optional[int] = None,
        from_step: int = 0,
    ) -> PluginResult:
        """
        Execute the chain (or a single step / subset of steps) and return a
        consolidated `PluginResult`.
        """
        final_result = PluginResult()
        if not self.steps:
            return final_result

        if only_step is not None:
            step_indices = [int(only_step)]
        else:
            step_indices = list(range(max(0, int(from_step)), len(self.steps)))

        step_indices = [i for i in step_indices if 0 <= i < len(self.steps)]
        if not step_indices:
            return final_result

        # Prepare working overlay list and track pre-existing vs in-chain-added overlays
        working_overlays: List[Any] = []
        preexisting_ids = set()
        chain_added_map: Dict[str, Any] = {}

        chain_source = f"plugin:{self.name}" if self.name else None
        is_full_run = (only_step is None and int(from_step) == 0)

        t_start_scope = float(info.t_start)
        t_end_scope   = float(info.t_end)

        for o in info.overlays:
            # On a full chain re-run from Step 0, automatically remove stale overlays
            # previously created by this same chain inside the active time scope so
            # re-running a chain cleanly replaces its previous detections.
            if (
                is_full_run
                and chain_source
                and getattr(o, "source", None) == chain_source
                and o.t_end >= t_start_scope
                and o.t_start <= t_end_scope
            ):
                final_result.remove(o.id)
                continue
            working_overlays.append(o)
            preexisting_ids.add(o.id)

        num_to_run = len(step_indices)

        for run_pos, step_idx in enumerate(step_indices):
            if info.is_cancelled():
                break

            resolved = self.resolve_step(step_idx)
            step_name = resolved["name"]
            step_func = resolved["func"]
            step_params = self._build_step_params(step_idx, resolved, info.params)

            # Create a scoped progress reporter for this step
            base_pct = int((run_pos / max(1, num_to_run)) * 100)
            span_pct = max(1, int(100 / max(1, num_to_run)))

            step_info = info.copy_with(
                overlays=list(working_overlays),
                params=step_params,
            )

            def _step_progress(pct: int, msg: str = "", _b=base_pct, _s=span_pct, _sn=step_name):
                scaled = min(99, _b + int((max(0, min(100, int(pct))) * _s) / 100))
                prefix = f"[{_sn}] {msg}" if msg else f"Running {_sn}…"
                info.progress(scaled, prefix)

            step_info._progress_cb = _step_progress
            _step_progress(0, "Starting…")

            step_res = step_func(samples, step_info)
            if not isinstance(step_res, PluginResult):
                raise TypeError(
                    f"Chain step {step_idx + 1} ('{step_name}') returned "
                    f"{type(step_res).__name__} instead of PluginResult."
                )

            # --- Apply step_res overlay operations to working_overlays in memory ---

            # 1. Removes
            for oid in step_res._removes:
                working_overlays = [w for w in working_overlays if w.id != oid]
                if oid in chain_added_map:
                    del chain_added_map[oid]
                elif oid in preexisting_ids:
                    final_result.remove(oid)

            # 2. Replaces
            for old_id, new_ov in step_res._replaces:
                orig = next((w for w in working_overlays if w.id == old_id), None)
                if orig is not None:
                    if getattr(new_ov, "iq", None) is None and getattr(orig, "iq", None) is not None:
                        new_ov.iq = orig.iq
                        new_ov.fs = getattr(orig, "fs", None)
                if old_id in chain_added_map:
                    new_ov.id = old_id
                    chain_added_map[old_id] = new_ov
                    working_overlays = [new_ov if w.id == old_id else w for w in working_overlays]
                else:
                    if not getattr(new_ov, "id", None) or new_ov.id == old_id:
                        new_ov.id = str(uuid.uuid4())
                    working_overlays = [new_ov if w.id == old_id else w for w in working_overlays]
                    final_result.replace(old_id, new_ov)

            # 3. Updates
            for oid, fields in step_res._updates:
                target_ov = next((w for w in working_overlays if w.id == oid), None)
                if target_ov is not None:
                    for fk, fv in fields.items():
                        setattr(target_ov, fk, fv)
                if oid not in chain_added_map:
                    final_result.update(oid, **fields)

            # 4. Adds
            for new_ov in step_res._adds:
                if not getattr(new_ov, "id", None) or new_ov.id in preexisting_ids or new_ov.id in chain_added_map:
                    new_ov.id = str(uuid.uuid4())
                working_overlays.append(new_ov)
                chain_added_map[new_ov.id] = new_ov

            # 5. Plots, Native Tabs & Logs
            for plot_spec in step_res._plots:
                p_copy = dict(plot_spec)
                if num_to_run > 1:
                    p_copy["title"] = f"{step_name}: {p_copy.get('title', 'Plot')}"
                final_result._plots.append(p_copy)

            if step_res._plot_tab_title and not final_result._plot_tab_title:
                final_result._plot_tab_title = (
                    f"{self.name} - Plots" if (self.name and num_to_run > 1) else step_res._plot_tab_title
                )

            final_result._native_tabs.extend(step_res._native_tabs)
            for msg in step_res._logs:
                final_result.log(f"[{step_name}] {msg}")

        # Emit all surviving chain-added overlays into final_result._adds
        for ov in working_overlays:
            if ov.id in chain_added_map:
                final_result.add(ov)

        info.progress(100, "Done")
        return final_result

    # ------------------------------------------------------------------
    # Module Binding (when CHAIN = PluginChain(...) is defined in a .py file)
    # ------------------------------------------------------------------

    def bind_to_module(
        self,
        module: Any,
        module_path: Optional[str] = None,
        resolver: Optional[Callable[[Any], Optional[Dict[str, Any]]]] = None,
    ) -> None:
        """
        Attach `run`, `PLUGIN_PARAMS`, and `PLUGIN_NEEDS_WIDEBAND_IQ` to `module`
        so any `.py` file defining `CHAIN = PluginChain(...)` works as a first-class plugin.
        """
        if module_path:
            self.set_base_dir(os.path.dirname(os.path.abspath(module_path)))
        if resolver is not None:
            self.set_resolver(resolver)

        mod_plugin_name = getattr(module, "PLUGIN_NAME", None)
        if mod_plugin_name:
            self.name = str(mod_plugin_name)
        elif self.name:
            setattr(module, "PLUGIN_NAME", self.name)
        elif module_path:
            self.name = os.path.splitext(os.path.basename(module_path))[0]
            setattr(module, "PLUGIN_NAME", self.name)

        if not hasattr(module, "PLUGIN_CATEGORY"):
            setattr(module, "PLUGIN_CATEGORY", self.category or "Chains")

        if not hasattr(module, "PLUGIN_DESCRIPTION") and self.description:
            setattr(module, "PLUGIN_DESCRIPTION", self.description)

        setattr(module, "PLUGIN_PARAMS", self.get_params_spec())
        setattr(module, "PLUGIN_NEEDS_WIDEBAND_IQ", self.needs_wideband_iq())

        if not hasattr(module, "run") or getattr(module, "_iqview_chain_bound", False):
            def _chain_run(samples: np.ndarray, info: PluginContext) -> PluginResult:
                return self.run(samples, info)

            setattr(module, "run", _chain_run)
            setattr(module, "_iqview_chain_bound", True)


# ---------------------------------------------------------------------------
# Code Generation & `.py` Default Parameter Persistence Utilities
# ---------------------------------------------------------------------------

def generate_chain_py(
    chain_name: str,
    steps: Sequence[Tuple[str, Dict[str, Any]]],
    description: str = "",
    category: str = "Chains",
    standalone: bool = False,
    plugin_resolver: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
) -> str:
    """
    Generate a clean, editable Python plugin file (`.py`) for a `PluginChain`.

    Parameters
    ----------
    chain_name : str
        Human-readable `PLUGIN_NAME` for the chain.
    steps : sequence of (plugin_name, params_dict)
        Ordered list of steps and their baked-in default parameter dicts.
    description : str
        One-line `PLUGIN_DESCRIPTION`.
    category : str
        `PLUGIN_CATEGORY` (defaults to `"Chains"`).
    standalone : bool, default False
        When False, generates a concise `PluginChain([...])` `.py` file that
        references the step plugins by name.
        When True, embeds the source code of each step plugin directly into
        the generated `.py` file so it has zero external plugin dependencies.
    """
    if not description:
        step_names = [str(s[0]) for s in steps]
        description = " → ".join(step_names)

    lines = [
        f'"""{chain_name} — IQView Plugin Chain',
        "",
        f"Pipeline: {description}",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from iqview import PluginChain",
        "",
        f"PLUGIN_NAME        = {chain_name!r}",
        f"PLUGIN_DESCRIPTION = {description!r}",
        f"PLUGIN_CATEGORY    = {category!r}",
        "",
    ]

    if standalone:
        lines.append("# --- Embedded Step Implementations (Standalone Bundle) ---")
        step_var_names = []
        for idx, (step_target, _) in enumerate(steps):
            src_code = None
            if plugin_resolver is not None:
                info = plugin_resolver(step_target)
                if isinstance(info, dict) and info.get("path") and os.path.isfile(info["path"]):
                    with open(info["path"], "r", encoding="utf-8") as fh:
                        src_code = fh.read()
            if src_code is None:
                from iqview.plugins.builtin import get_builtin_plugin
                mod = get_builtin_plugin(step_target)
                if mod is not None and getattr(mod, "__file__", None) and os.path.isfile(mod.__file__):
                    with open(mod.__file__, "r", encoding="utf-8") as fh:
                        src_code = fh.read()

            if src_code is not None:
                var_name = f"_STEP_{idx}_MODULE"
                lines.append(f"import types as _types")
                lines.append(f"{var_name} = _types.ModuleType({f'_step_{idx}'!r})")
                lines.append(f"exec({src_code!r}, {var_name}.__dict__)")
                lines.append("")
                step_var_names.append((var_name, step_target))
            else:
                step_var_names.append((repr(step_target), step_target))

        lines.append("CHAIN = PluginChain([")
        for (target_expr, label_str), (_, step_params) in zip(step_var_names, steps):
            lines.append("    (")
            lines.append(f"        {target_expr},")
            lines.append("        {")
            for k, v in (step_params or {}).items():
                lines.append(f"            {k!r}: {v!r},")
            lines.append("        },")
            lines.append(f"        {label_str!r},")
            lines.append("    ),")
        lines.append("])")
        lines.append("")
        return "\n".join(lines)

    # Standard concise PluginChain definition
    lines.append("CHAIN = PluginChain([")
    for step_target, step_params in steps:
        if not step_params:
            lines.append(f"    ({step_target!r}, {{}}),")
        else:
            lines.append(f"    ({step_target!r}, {{")
            for k, v in step_params.items():
                lines.append(f"        {k!r}: {v!r},")
            lines.append("    }),")
    lines.append("])")
    lines.append("")
    return "\n".join(lines)


def _node_offset_span(source_lines: List[str], node: ast.AST) -> Optional[Tuple[int, int]]:
    """Convert an AST node's (lineno, col_offset, end_lineno, end_col_offset) to a byte/char slice."""
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        return None
    if node.lineno is None or node.end_lineno is None:
        return None

    line_starts = [0]
    for ln in source_lines:
        line_starts.append(line_starts[-1] + len(ln))

    start_idx = line_starts[node.lineno - 1] + (node.col_offset or 0)
    end_idx = line_starts[node.end_lineno - 1] + (node.end_col_offset or 0)
    return start_idx, end_idx


def save_defaults_to_py(py_path: str, new_params: Dict[str, Any]) -> bool:
    """
    Update the default parameter values directly inside a `.py` plugin or chain file,
    preserving all comments, formatting, and surrounding code.

    Supports both:
      1. Standard plugins defining `PLUGIN_PARAMS = { "key": {"default": ..., ...} }`
      2. Chain files defining `CHAIN = PluginChain([ ("Step", {"key": ...}), ... ])`

    Returns True if the file was updated on disk.
    """
    if not py_path or not os.path.isfile(py_path) or not new_params:
        return False

    try:
        with open(py_path, "r", encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return False

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False

    src_lines = src.splitlines(keepends=True)
    replacements: List[Tuple[int, int, str]] = []

    for node in tree.body:
        # Check assignments to PLUGIN_PARAMS or CHAIN
        targets = []
        val_node = None
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            val_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            val_node = node.value

        # Case 1: PLUGIN_PARAMS = { ... }
        if "PLUGIN_PARAMS" in targets and isinstance(val_node, ast.Dict):
            for k_node, v_node in zip(val_node.keys, val_node.values):
                if not isinstance(k_node, ast.Constant) or not isinstance(k_node.value, str):
                    continue
                param_key = k_node.value
                if param_key not in new_params:
                    continue
                new_val_repr = repr(new_params[param_key])

                if isinstance(v_node, ast.Dict):
                    for sub_k, sub_v in zip(v_node.keys, v_node.values):
                        if (
                            isinstance(sub_k, ast.Constant)
                            and sub_k.value == "default"
                            and sub_v is not None
                        ):
                            span = _node_offset_span(src_lines, sub_v)
                            if span is not None:
                                replacements.append((span[0], span[1], new_val_repr))
                elif v_node is not None:
                    span = _node_offset_span(src_lines, v_node)
                    if span is not None:
                        replacements.append((span[0], span[1], new_val_repr))

        # Case 2: CHAIN = PluginChain([ ... ])
        if "CHAIN" in targets and isinstance(val_node, ast.Call):
            if val_node.args and isinstance(val_node.args[0], (ast.List, ast.Tuple)):
                step_elts = val_node.args[0].elts
                for step_idx, elt in enumerate(step_elts):
                    prefix = f"step{step_idx}."
                    step_updates = {
                        k[len(prefix):]: v
                        for k, v in new_params.items()
                        if str(k).startswith(prefix)
                    }
                    if not step_updates:
                        continue

                    if isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) >= 2:
                        dict_node = elt.elts[1]
                        if isinstance(dict_node, ast.Dict):
                            existing_keys = set()
                            for dk, dv in zip(dict_node.keys, dict_node.values):
                                if isinstance(dk, ast.Constant) and isinstance(dk.value, str):
                                    raw_k = dk.value
                                    existing_keys.add(raw_k)
                                    if raw_k in step_updates and dv is not None:
                                        span = _node_offset_span(src_lines, dv)
                                        if span is not None:
                                            replacements.append((span[0], span[1], repr(step_updates[raw_k])))

                            missing_keys = {
                                k: v for k, v in step_updates.items() if k not in existing_keys
                            }
                            if missing_keys:
                                dict_span = _node_offset_span(src_lines, dict_node)
                                if dict_span is not None:
                                    # Build updated dict literal
                                    merged_dict = {}
                                    for dk, dv in zip(dict_node.keys, dict_node.values):
                                        if isinstance(dk, ast.Constant) and isinstance(dk.value, str):
                                            try:
                                                merged_dict[dk.value] = ast.literal_eval(dv)
                                            except Exception:
                                                pass
                                    merged_dict.update(step_updates)
                                    formatted = "{\n" + "".join(
                                        f"        {mk!r}: {mv!r},\n" for mk, mv in merged_dict.items()
                                    ) + "    }"
                                    replacements = [
                                        r for r in replacements
                                        if not (dict_span[0] <= r[0] and r[1] <= dict_span[1])
                                    ]
                                    replacements.append((dict_span[0], dict_span[1], formatted))

    if not replacements:
        return False

    # Apply replacements in reverse character order so offsets stay valid
    replacements.sort(key=lambda r: r[0], reverse=True)
    new_src = src
    for s_idx, e_idx, text in replacements:
        new_src = new_src[:s_idx] + text + new_src[e_idx:]

    try:
        with open(py_path, "w", encoding="utf-8") as fh:
            fh.write(new_src)
        return True
    except OSError:
        return False

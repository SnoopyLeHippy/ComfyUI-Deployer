"""Inspect ComfyUI workflows to learn which nodes and models they need.

Workflow sources can be ``.json`` exports or ComfyUI-generated images that
carry the workflow in their metadata; both are loaded via
:func:`deployer.core.workflow_io.load_workflow_graph`.
"""

import os

from deployer.core.workflow_io import (
    collect_subgraph_ids,
    iter_graph_nodes,
    load_workflow_graph,
)


# File extensions that identify a model file in workflow widget values.
MODEL_EXTENSIONS = {
    ".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".ggml", ".pkl", ".sft",
}

# Widget values commonly used by built-in nodes that look like identifiers but
# are not models: samplers, schedulers, control_after_generate modes, common
# enums. Filtering these out drastically cuts down the "Model not found: euler"
# noise during bundle creation.
_NON_MODEL_VALUES = frozenset({
    # Samplers
    "euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp",
    "heun", "heunpp2", "dpm_2", "dpm_2_ancestral", "lms",
    "dpm_fast", "dpm_adaptive",
    "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu",
    "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu",
    "dpmpp_3m_sde", "dpmpp_3m_sde_gpu",
    "ddpm", "lcm", "ddim", "uni_pc", "uni_pc_bh2",
    "ipndm", "ipndm_v", "deis", "res_multistep", "gradient_estimation",
    # Schedulers
    "normal", "karras", "exponential", "sgm_uniform", "simple",
    "ddim_uniform", "beta", "linear_quadratic",
    # control_after_generate
    "fixed", "increment", "decrement", "randomize",
    # Common toggles / enums
    "enable", "disable", "none", "default", "auto", "true", "false",
})


def _looks_like_model_dir(val: str) -> bool:
    """True if *val* plausibly names a HuggingFace-style model directory.

    Catches strings like ``Qwen2.5-VL-3B-Instruct`` while excluding sampler /
    scheduler / enum names (``euler``, ``karras``, ``randomize``, …).
    """
    if "/" in val or "\\" in val or " " in val or len(val) <= 3:
        return False
    if val.lower() in _NON_MODEL_VALUES:
        return False
    # Real model dir names mix case or contain a digit / dash / dot. Plain
    # lowercase identifiers are almost always enum values.
    return any(ch.isdigit() or ch in "-." for ch in val) or not val.islower()


def extract_workflow_info(workflow_paths: list[str]) -> tuple[set[str], set[str]]:
    """Parse workflow JSONs and return ``(node_types, model_refs)``.

    ``model_refs`` is a set of filename / dirname strings extracted from
    widget values that look like model references — either a known file
    extension (``.safetensors``, etc.) or a HuggingFace-style identifier
    (``Qwen2.5-VL-3B-Instruct``). Sampler / scheduler / enum values are
    filtered out via :func:`_looks_like_model_dir`.
    """
    node_types: set[str] = set()
    model_refs: set[str] = set()

    for wf_path in workflow_paths:
        data = load_workflow_graph(wf_path)
        subgraph_ids = collect_subgraph_ids(data)
        for node in iter_graph_nodes(data):
            ntype = node.get("type")
            if isinstance(ntype, str) and ntype and ntype not in subgraph_ids:
                node_types.add(ntype)
            for val in node.get("widgets_values", []):
                if not isinstance(val, str) or not val.strip():
                    continue
                ext = os.path.splitext(val)[1].lower()
                if ext in MODEL_EXTENSIONS:
                    model_refs.add(val)
                elif ext == "" and _looks_like_model_dir(val):
                    model_refs.add(val)
    return node_types, model_refs


def find_custom_node_dirs_for_types(node_types: set[str], custom_nodes_dir: str) -> set[str]:
    """Return the set of ``custom_nodes`` directory names that provide any of *node_types*.

    Each subdirectory's Python sources are scanned for the literal node-type
    string (quoted) — a coarse but effective way of identifying which package
    registered the node in its ``NODE_CLASS_MAPPINGS``.
    """
    needed_dirs: set[str] = set()
    if not os.path.isdir(custom_nodes_dir):
        return needed_dirs

    for entry in os.listdir(custom_nodes_dir):
        entry_path = os.path.join(custom_nodes_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        for dirpath, _, filenames in os.walk(entry_path):
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                try:
                    with open(os.path.join(dirpath, fname), "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                except OSError:
                    continue
                for ntype in node_types:
                    if f'"{ntype}"' in content or f"'{ntype}'" in content:
                        needed_dirs.add(entry)
                        break
            if entry in needed_dirs:
                break
    return needed_dirs

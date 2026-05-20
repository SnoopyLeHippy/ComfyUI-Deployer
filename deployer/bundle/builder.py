"""Top-level orchestrator for building a portable ComfyUI bundle."""

import os
import shutil

from deployer.bundle.comfyui_archive import (
    download_and_extract_comfyui,
    get_comfyui_version,
)
from deployer.bundle.model_copier import copy_models_for_bundle
from deployer.bundle.node_cloner import (
    clone_node_into_bundle,
    install_bundle_requirements,
)
from deployer.bundle.project_copier import copy_debugger_to_bundle
from deployer.bundle.workflow_parser import (
    extract_workflow_info,
    find_custom_node_dirs_for_types,
)
from deployer.config import (
    CUSTOM_NODES_DIR,
    EXTRA_MODEL_PATHS_YAML,
    MODELS_DIR,
)
from deployer.core.filesystem import force_remove_readonly
from deployer.core.junctions import read_junction_target
from deployer.settings import UserSettings


def _resolve_junction(path: str) -> str:
    """Return *path*'s junction target (cleaned), or *path* itself if not a junction."""
    return read_junction_target(path) or path


def create_bundle(
    dest_dir: str,
    workflow_paths: list[str],
    include_debugger: bool = False,
    extra_repos: list[tuple[str, str]] | None = None,
) -> None:
    """Create a clean portable ComfyUI bundle at *dest_dir*.

    When *workflow_paths* is non-empty the bundle is trimmed to just the
    custom nodes and models referenced by those workflows. Otherwise the
    full set of installed nodes is included and the default empty
    ``models/`` folder from a fresh ComfyUI install is kept.

    *extra_repos* is a list of ``(repo_url, ref)`` pairs to clone into the
    bundle's ``custom_nodes/`` in addition to the installed ones — used
    when a workflow needs nodes that aren't installed locally and have
    been resolved against the ComfyUI-Manager DB.
    """
    src_custom_nodes = CUSTOM_NODES_DIR
    src_models = _resolve_junction(MODELS_DIR)

    node_types: set[str] = set()
    model_refs: set[str] = set()
    needed_cn_dirs: set[str] | None = None
    if workflow_paths:
        node_types, model_refs = extract_workflow_info(workflow_paths)
        print(f"Found {len(node_types)} node types, {len(model_refs)} model references in workflows.")
        needed_cn_dirs = find_custom_node_dirs_for_types(node_types, src_custom_nodes)
        print(f"Custom node dirs to include: {needed_cn_dirs or 'none'}")

    # --- Step 1: Download and extract a clean ComfyUI ---
    version = get_comfyui_version()
    download_and_extract_comfyui(dest_dir, version)

    dst_portable = os.path.join(dest_dir, "ComfyUI_windows_portable")
    dst_comfyui = os.path.join(dst_portable, "ComfyUI")
    dst_cn = os.path.join(dst_comfyui, "custom_nodes")
    dst_python = os.path.join(dst_portable, "python_embeded", "python.exe")

    # --- Step 2: Copy extra_model_paths.yaml if present ---
    if os.path.exists(EXTRA_MODEL_PATHS_YAML):
        shutil.copy2(EXTRA_MODEL_PATHS_YAML, os.path.join(dst_comfyui, "extra_model_paths.yaml"))
        print("Copied extra_model_paths.yaml")

    # --- Step 3: Clone selected custom nodes ---
    os.makedirs(dst_cn, exist_ok=True)

    node_lookup: dict[str, tuple[str, str]] = {
        os.path.basename(entry["repo"]): (entry["repo"], entry.get("ref", "main"))
        for entry in UserSettings.load_nodes()
    }

    cloned_dirs: list[str] = []
    if os.path.isdir(src_custom_nodes):
        for entry in os.listdir(src_custom_nodes):
            if not os.path.isdir(os.path.join(src_custom_nodes, entry)):
                continue
            if needed_cn_dirs is not None and entry not in needed_cn_dirs:
                continue
            repo, ref = node_lookup.get(entry, (None, None))
            if repo:
                clone_node_into_bundle(repo, ref, dst_cn)
                cloned_dirs.append(entry)
            else:
                # Fallback: copy the directory as-is, resolving junctions.
                real_src = _resolve_junction(os.path.join(src_custom_nodes, entry))
                print(f"  Copying custom node: {entry}")
                shutil.copytree(real_src, os.path.join(dst_cn, entry), dirs_exist_ok=True)
                cloned_dirs.append(entry)

    # --- Step 3b: Clone workflow-resolved nodes not installed locally ---
    if extra_repos:
        print(f"Cloning {len(extra_repos)} workflow-resolved node(s) into bundle...")
        for repo, ref in extra_repos:
            norm_repo = repo.rstrip("/").removesuffix(".git")
            name = os.path.basename(norm_repo)
            if not name or name in cloned_dirs:
                continue
            clone_node_into_bundle(norm_repo, ref, dst_cn)
            cloned_dirs.append(name)

    # --- Step 4: Install requirements for cloned nodes ---
    if cloned_dirs and os.path.exists(dst_python):
        print("Installing node requirements...")
        install_bundle_requirements(dst_python, dst_cn, cloned_dirs)

    # --- Step 5: Replace output and input with empty dirs ---
    for folder in ("output", "input"):
        folder_path = os.path.join(dst_comfyui, folder)
        if os.path.isdir(folder_path):
            shutil.rmtree(folder_path, onerror=force_remove_readonly)
        os.makedirs(folder_path, exist_ok=True)

    # --- Step 6: Handle models ---
    dst_models = os.path.join(dst_comfyui, "models")
    if model_refs:
        if os.path.isdir(dst_models):
            shutil.rmtree(dst_models, onerror=force_remove_readonly)
        os.makedirs(dst_models, exist_ok=True)
        print("Copying referenced models...")
        copy_models_for_bundle(src_models, dst_models, model_refs)
    # If no workflows were given, keep the default (empty) models dir.

    # --- Step 7: Copy ComfyUI Deployer project ---
    if include_debugger:
        copy_debugger_to_bundle(dst_cn)

    print(f"Bundle created at {dst_portable}")

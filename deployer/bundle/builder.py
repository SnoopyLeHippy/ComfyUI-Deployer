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
from deployer.bundle.project_copier import (
    clone_deployer_into_bundle,
    write_bundle_user_settings,
)
from deployer.bundle.workflow_parser import (
    extract_workflow_info,
    find_custom_node_dirs_for_types,
)
from deployer.config import (
    CUSTOM_NODES_DIR,
    EXTRA_MODEL_PATHS_YAML,
    MODELS_DIR,
    PROJECT_ROOT,
)
from deployer.plugins import BundleFormat, StepContext, StepPhase, load_plugins, run_steps
from deployer.core.filesystem import force_remove_readonly
from deployer.core.junctions import read_junction_target
from deployer.settings import UserSettings


def _resolve_junction(path: str) -> str:
    """Return *path*'s junction target (cleaned), or *path* itself if not a junction."""
    return read_junction_target(path) or path


def _clone_remote_plugins(dest_dir: str, plugin_repos: list[dict]) -> None:
    """Clone selected remote plugin repos into ``dest_dir/plugins/remote/``.

    Mirrors what ``sync_remote_plugins`` does at install time, but runs on the
    author's machine during folder-bundle creation so the bundled deployer has
    the plugin code available without a network connection on first launch.
    """
    if not plugin_repos:
        return
    from deployer.core import git_ops
    remote_dir = os.path.join(dest_dir, "plugins", "remote")
    os.makedirs(remote_dir, exist_ok=True)
    for entry in plugin_repos:
        repo = entry.get("repo", "").strip()
        ref = entry.get("ref", "main").strip() or "main"
        if not repo:
            continue
        name = os.path.basename(repo.rstrip("/").removesuffix(".git"))
        if not name:
            continue
        dest = os.path.join(remote_dir, name)
        if os.path.isdir(dest):
            print(f"  Remote plugin already present: {name}")
            continue
        print(f"  Cloning remote plugin: {name} ({repo}@{ref})")
        try:
            git_ops.clone(repo, dest, cwd=remote_dir, recursive=False)
            if ref and ref not in ("main", "HEAD"):
                git_ops.checkout(ref, cwd=dest, check=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  Warning: failed to clone plugin '{name}': {exc}")


def _copy_local_plugins(dest_dir: str) -> None:
    """Copy user plugin .py files from the local plugins/ dir into the bundle.

    plugins/ is gitignored, so the deployer clone (Step 0) won't include it.
    Copying explicitly lets the bundled deployer load these plugins and replay
    their INSTALL-phase steps on the recipient's machine.
    Skips silently when the source directory is absent or empty.
    """
    src = os.path.join(PROJECT_ROOT, "plugins")
    if not os.path.isdir(src):
        return
    files = [f for f in os.listdir(src) if f.endswith(".py") and not f.startswith("_")]
    if not files:
        return
    dst = os.path.join(dest_dir, "plugins")
    os.makedirs(dst, exist_ok=True)
    for name in sorted(files):
        shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
        print(f"  Copied local plugin: {name}")


def create_bundle(
    dest_dir: str,
    workflow_paths: list[str],
    include_debugger: bool = False,
    extra_repos: list[tuple[str, str]] | None = None,
    include_models: bool = False,
    *,
    include_workflows: bool = False,
    steps: list[dict] | None = None,
    plugin_repos: list[dict] | None = None,
) -> None:
    """Create a clean portable ComfyUI bundle at *dest_dir*.

    When *workflow_paths* is non-empty the bundle is trimmed to just the
    custom nodes referenced by those workflows. Otherwise the full set of
    installed nodes is included.

    Models are only copied when *include_models* is set: with workflows, just
    the referenced models; without workflows, the entire ``models/`` tree.
    When it's unset the default empty ``models/`` folder from a fresh ComfyUI
    install is kept.

    *extra_repos* is a list of ``(repo_url, ref)`` pairs to clone into the
    bundle's ``custom_nodes/`` in addition to the installed ones — used
    when a workflow needs nodes that aren't installed locally and have
    been resolved against the ComfyUI-Manager DB.

    When *include_workflows* is set, the files in *workflow_paths* are copied
    into a ``workflows/`` folder at the export root.

    *steps* is the list of configured bundle-step plugins
    (``{"id", "config"}`` entries). Their ``CREATE``-phase steps run here against
    the freshly built bundle; the full list is persisted into the bundle's
    ``user_settings.json`` (when the deployer is included) so install-phase
    steps can be replayed on the recipient's machine.
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

    # --- Step 0: Clone the ComfyUI Deployer into the still-empty destination ---
    # Done before downloading ComfyUI so ``git clone`` targets an empty dir
    # (it refuses a non-empty one) and no temporary folder is needed. The
    # matching user_settings.json is written at the very end (Step 7).
    if include_debugger:
        clone_deployer_into_bundle(dest_dir)
        # --- Step 0b: Copy local plugins (gitignored, not in the clone) ---
        _copy_local_plugins(dest_dir)
        # --- Step 0c: Clone selected remote plugins into the bundle ---
        if plugin_repos:
            print(f"Cloning {len(plugin_repos)} remote plugin(s) into bundle...")
            _clone_remote_plugins(dest_dir, plugin_repos)

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

    # --- Step 6: Handle models (only when explicitly requested) ---
    dst_models = os.path.join(dst_comfyui, "models")
    if include_models:
        if model_refs:
            if os.path.isdir(dst_models):
                shutil.rmtree(dst_models, onerror=force_remove_readonly)
            os.makedirs(dst_models, exist_ok=True)
            print("Copying referenced models...")
            copy_models_for_bundle(src_models, dst_models, model_refs)
        elif os.path.isdir(src_models):
            print("Copying all models (this can be large)...")
            shutil.copytree(src_models, dst_models, dirs_exist_ok=True)
    # Otherwise keep the default (empty) models dir from the fresh download.

    # --- Step 6b: Run CREATE-phase bundle steps (plugins) ---
    # These act on the freshly built bundle on the author's machine (e.g. copy
    # extra models in now). INSTALL-phase steps are skipped here and replayed
    # later on the recipient via the persisted user_settings.json.
    if steps:
        load_plugins()
        ctx = StepContext(
            bundle_root=dest_dir,
            comfyui_dir=dst_comfyui,
            models_dir=dst_models,
            custom_nodes_dir=dst_cn,
            input_dir=os.path.join(dst_comfyui, "input"),
            output_dir=os.path.join(dst_comfyui, "output"),
            phase=StepPhase.CREATE,
            bundle_format=BundleFormat.FOLDER,
            workflow_paths=workflow_paths,
            model_refs=model_refs,
        )
        run_steps(steps, ctx)

    # --- Step 7: Generate the bundle's user_settings.json ---
    # The deployer itself was cloned in Step 0; now that the custom nodes are in
    # place we can record them (and the configured steps for install-time replay).
    if include_debugger:
        write_bundle_user_settings(dest_dir, dst_cn, steps, plugin_repos)

    # --- Step 8: Copy selected workflows next to the bundle root ---
    if include_workflows and workflow_paths:
        workflows_dir = os.path.join(dest_dir, "workflows")
        os.makedirs(workflows_dir, exist_ok=True)
        for wf in workflow_paths:
            try:
                shutil.copy2(wf, os.path.join(workflows_dir, os.path.basename(wf)))
            except OSError as exc:
                print(f"  Warning: could not copy workflow '{wf}': {exc}")
        print(f"Copied {len(workflow_paths)} workflow(s) into {workflows_dir}")

    print(f"Bundle created at {dst_portable}")

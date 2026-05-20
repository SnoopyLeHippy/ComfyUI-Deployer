"""Copy the ComfyUI Deployer project itself into a generated bundle.

This lets the bundle ship with the deployer UI alongside the portable ComfyUI
install, so end users can re-run installs/updates against the bundled tree.
"""

import fnmatch
import json
import os
import shutil

from deployer.core import git_ops
from deployer.settings import UserSettings


def _project_root() -> str:
    """Return the absolute path of the ComfyUI Deployer project root."""
    # bundle/project_copier.py → deployer/bundle → deployer → <project root>
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _gitignore_patterns(project_root: str) -> list[str]:
    path = os.path.join(project_root, ".gitignore")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]


def _make_should_ignore(patterns: list[str]):
    def _should_ignore(rel_path: str) -> bool:
        name = os.path.basename(rel_path)
        if name == "download_comfy.bat":
            return True
        rel_unix = rel_path.replace("\\", "/")
        for pat in patterns:
            pat_clean = pat.rstrip("/")
            if fnmatch.fnmatch(name, pat_clean):
                return True
            if fnmatch.fnmatch(rel_unix, pat_clean):
                return True
            if fnmatch.fnmatch(rel_unix, pat_clean + "/*"):
                return True
        return False
    return _should_ignore


def _bundle_node_metadata(bundle_cn_dir: str) -> list[dict]:
    """Return a node-entry list for every git-backed dir under *bundle_cn_dir*.

    Metadata is reused from the main ``user_settings.json`` when the folder
    name is known, otherwise it's read live from the cloned repo's git
    config (matching the orphan-discovery behaviour).
    """
    original_lookup = {
        os.path.basename(entry["repo"]): entry for entry in UserSettings.load_nodes()
    }

    bundle_nodes: list[dict] = []
    if not os.path.isdir(bundle_cn_dir):
        return bundle_nodes

    for entry in sorted(os.scandir(bundle_cn_dir), key=lambda e: e.name):
        if not entry.is_dir(follow_symlinks=True):
            continue
        if not os.path.exists(os.path.join(entry.path, ".git")):
            continue
        name = entry.name
        if name in original_lookup:
            bundle_nodes.append(dict(original_lookup[name]))
            continue

        repo = git_ops.get_remote_url(entry.path)
        if not repo:
            continue
        ref = git_ops.describe_head(entry.path, fallback="HEAD")
        bundle_nodes.append({"repo": repo, "ref": ref, "description": name})

    return bundle_nodes


def copy_debugger_to_bundle(bundle_cn_dir: str) -> None:
    """Copy the ComfyUI Deployer project files into the bundle destination folder.

    Rules:

    * Exclude ``download_comfy.bat`` and anything matched by ``.gitignore``.
    * Generate a fresh ``user_settings.json`` containing only the nodes
      whose clone folder exists inside *bundle_cn_dir*.
    """
    project_root = _project_root()
    # bundle_cn_dir = …/<dest>/ComfyUI_windows_portable/ComfyUI/custom_nodes
    bundle_root = os.path.dirname(os.path.dirname(bundle_cn_dir))  # …/ComfyUI_windows_portable
    dst_root = os.path.dirname(bundle_root)                         # the user-chosen dest

    print(f"Copying ComfyUI Deployer project to {dst_root}...")

    should_ignore = _make_should_ignore(_gitignore_patterns(project_root))

    for dirpath, dirnames, filenames in os.walk(project_root):
        rel_dir = os.path.relpath(dirpath, project_root)
        if rel_dir == ".":
            rel_dir = ""
        if rel_dir and should_ignore(rel_dir):
            dirnames.clear()
            continue

        # Prune ignored subdirs in-place so os.walk doesn't descend into them
        dirnames[:] = [
            d for d in dirnames
            if not should_ignore(os.path.join(rel_dir, d) if rel_dir else d)
        ]

        dst_dir = os.path.join(dst_root, rel_dir) if rel_dir else dst_root
        os.makedirs(dst_dir, exist_ok=True)

        for fname in filenames:
            rel_file = os.path.join(rel_dir, fname) if rel_dir else fname
            if should_ignore(rel_file):
                continue
            # user_settings.json is generated separately below
            if fname == "user_settings.json":
                continue
            src_file = os.path.join(dirpath, fname)
            shutil.copy2(src_file, os.path.join(dst_dir, fname))

    bundle_nodes = _bundle_node_metadata(bundle_cn_dir)
    dst_settings = os.path.join(dst_root, "user_settings.json")
    with open(dst_settings, "w", encoding="utf-8") as fh:
        json.dump({"nodes": bundle_nodes}, fh, indent=4, ensure_ascii=False)
    print(f"Wrote user_settings.json with {len(bundle_nodes)} node(s) to {dst_root}")

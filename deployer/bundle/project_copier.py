"""Clone the ComfyUI Deployer project into a generated bundle.

The bundle ships the deployer alongside the portable ComfyUI install so end
users can re-run installs/updates against the bundled tree. We *clone* the
project's ``origin`` remote (current branch) rather than copying the working
tree: the bundle gets a clean checkout with git history and without
local/uncommitted or git-ignored files.

The clone runs *before* ComfyUI is downloaded, while the destination is still
empty — that way ``git clone`` targets an empty directory (it refuses a
non-empty one) and no temporary folder is needed. The matching
``user_settings.json`` is generated at the end, once the custom nodes have been
cloned (it is git-ignored, so it never comes from the clone).
"""

import json
import os

from deployer.core import git_ops
from deployer.settings import UserSettings


def _project_root() -> str:
    """Return the absolute path of the ComfyUI Deployer project root."""
    # bundle/project_copier.py → deployer/bundle → deployer → <project root>
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def clone_deployer_into_bundle(dest_dir: str) -> None:
    """Clone the ComfyUI Deployer ``origin`` remote into *dest_dir*.

    Checks out the current branch (best-effort — falls back to the remote's
    default branch) and drops ``download_comfy.bat`` (never shipped in bundles).
    Must run while *dest_dir* is still empty.
    """
    if os.path.isdir(dest_dir) and os.listdir(dest_dir):
        raise RuntimeError(
            f"Destination '{dest_dir}' is not empty. The ComfyUI Deployer is cloned "
            "first, so the destination must be an empty folder. Empty it (or pick "
            "another) and try again."
        )

    project_root = _project_root()
    repo_url = git_ops.get_remote_url(project_root)
    if not repo_url:
        raise RuntimeError(
            "Cannot add ComfyUI Deployer to the bundle: no 'origin' remote found "
            f"in {project_root}."
        )
    branch = git_ops.get_current_branch(project_root)

    print(f"Cloning ComfyUI Deployer ({repo_url}) into {dest_dir}...")
    git_ops.clone(repo_url, dest_dir, cwd=os.path.dirname(dest_dir) or ".")
    if branch and branch != "HEAD":
        git_ops.checkout(branch, cwd=dest_dir, check=False)

    stray_bat = os.path.join(dest_dir, "download_comfy.bat")
    if os.path.exists(stray_bat):
        os.remove(stray_bat)


def collect_node_metadata(
    cn_dir: str, only_dirs: set[str] | None = None
) -> list[dict]:
    """Return a node-entry list for every git-backed dir under *cn_dir*.

    Metadata is reused from the main ``user_settings.json`` when the folder
    name is known, otherwise it's read live from the cloned repo's git
    config (matching the orphan-discovery behaviour). When *only_dirs* is
    given, directories whose name isn't in the set are skipped — used to trim
    the list to the custom nodes referenced by a set of workflows.

    Works on any custom_nodes tree: the bundle's (to write its
    ``user_settings.json``) or the live install's (to seed the node list for a
    sharable-bat export).
    """
    original_lookup = {
        os.path.basename(entry["repo"]): entry for entry in UserSettings.load_nodes()
    }

    nodes: list[dict] = []
    if not os.path.isdir(cn_dir):
        return nodes

    for entry in sorted(os.scandir(cn_dir), key=lambda e: e.name):
        if not entry.is_dir(follow_symlinks=True):
            continue
        if only_dirs is not None and entry.name not in only_dirs:
            continue
        if not os.path.exists(os.path.join(entry.path, ".git")):
            continue
        name = entry.name
        if name in original_lookup:
            nodes.append(dict(original_lookup[name]))
            continue

        repo = git_ops.get_remote_url(entry.path)
        if not repo:
            continue
        ref = git_ops.describe_head(entry.path, fallback="HEAD")
        nodes.append({"repo": repo, "ref": ref, "description": name})

    return nodes


def write_bundle_user_settings(
    dest_dir: str, bundle_cn_dir: str, steps: list[dict] | None = None
) -> None:
    """Generate the bundle's ``user_settings.json`` at *dest_dir*.

    Contains only the nodes whose clone folder exists inside *bundle_cn_dir*.
    Run after the custom nodes have been cloned into the bundle. When *steps*
    is given, the configured bundle steps are persisted too so the bundled
    deployer can replay the install-phase ones on the recipient's machine.
    """
    bundle_nodes = collect_node_metadata(bundle_cn_dir)
    data: dict = {"nodes": bundle_nodes}
    if steps:
        data["steps"] = steps
    dst_settings = os.path.join(dest_dir, "user_settings.json")
    with open(dst_settings, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4, ensure_ascii=False)
    print(f"Wrote user_settings.json with {len(bundle_nodes)} node(s) to {dest_dir}")

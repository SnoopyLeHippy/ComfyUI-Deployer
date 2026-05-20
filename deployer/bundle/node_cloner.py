"""Clone custom nodes into a bundle and install their pip requirements."""

import os

from deployer.core import git_ops
from deployer.core.pip_runner import find_requirement_files, install_requirement_files


_REQUIREMENTS_MAX_DEPTH = 2


def clone_node_into_bundle(repo_url: str, ref: str, custom_nodes_dir: str) -> None:
    """Clone *repo_url* into *custom_nodes_dir* and check out *ref*.

    No-op if a directory with the same basename already exists. The ref
    checkout is best-effort — some upstream repos don't have the exact ref
    locally, and that shouldn't abort the whole bundle.
    """
    name = os.path.basename(repo_url)
    dest = os.path.join(custom_nodes_dir, name)
    if os.path.exists(dest):
        return

    print(f"  Cloning {name} (ref: {ref})...")
    git_ops.clone(repo_url, name, cwd=custom_nodes_dir)
    git_ops.checkout(ref, cwd=dest, check=False)


def install_bundle_requirements(python_exe: str, custom_nodes_dir: str, node_dirs: list[str]) -> None:
    """Install pip requirements for *node_dirs* using the bundle's *python_exe*."""
    req_files: list[str] = []
    for node_name in node_dirs:
        req_files.extend(find_requirement_files(
            os.path.join(custom_nodes_dir, node_name),
            _REQUIREMENTS_MAX_DEPTH,
        ))

    install_requirement_files(python_exe, req_files, stream_output=False)

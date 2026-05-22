"""Headless node install for sharable-bat bundles.

Run by the generated install ``.bat`` (``python -s -m
deployer.bundle.headless_install``) after the deployer has been cloned and the
portable ComfyUI extracted next to it. It reproduces the node side of a normal
bundle, but on the recipient's machine:

* clones every node listed in ``user_settings.json`` into the local
  ``custom_nodes/`` at its recorded ref,
* installs their pip requirements with the bundle's embedded python,
* applies the folder junctions from the optional ``settings`` subdict.

``extra_model_paths.yaml`` is written directly by the .bat (its content is
embedded there), so it is intentionally *not* handled here — that keeps the
"don't ship models" promise while still wiring up the external model paths.
"""

import os

from deployer.bundle.node_cloner import (
    clone_node_into_bundle,
    install_bundle_requirements,
)
from deployer.config import CUSTOM_NODES_DIR, PYTHON_EXE
from deployer.settings import UserSettings


def run() -> None:
    """Clone all configured nodes, install requirements, apply junctions."""
    os.makedirs(CUSTOM_NODES_DIR, exist_ok=True)

    nodes = UserSettings.load_nodes()
    print(f"Installing {len(nodes)} custom node(s) into {CUSTOM_NODES_DIR}...")

    cloned_dirs: list[str] = []
    for entry in nodes:
        repo = entry.get("repo")
        if not repo:
            continue
        ref = entry.get("ref", "main")
        clone_node_into_bundle(repo, ref, CUSTOM_NODES_DIR)
        cloned_dirs.append(os.path.basename(repo.rstrip("/").removesuffix(".git")))

    if cloned_dirs and os.path.exists(PYTHON_EXE):
        print("Installing node requirements...")
        install_bundle_requirements(PYTHON_EXE, CUSTOM_NODES_DIR, cloned_dirs)

    settings = UserSettings.load_settings()
    if settings:
        # Imported lazily: pulls in PyQt6, which the .bat installs before this
        # runs but which we don't want as a hard import for the no-settings path.
        from deployer.ui.dialogs import apply_folder_junctions

        print("Applying folder settings...")
        apply_folder_junctions(settings)

    print("Headless install complete.")


if __name__ == "__main__":
    run()

"""Installation logic for ComfyUI custom nodes and their dependencies."""

import json
import os

from deployer.config import (
    INSIGHTFACE_WHL,
    LOCAL_NODES_JSON,
    PYTHON_EXE,
    SOURCE_NODES_JSON,
)
from deployer.core.node import CustomNode
from deployer.core.pip_runner import (
    find_requirement_files,
    install_packages,
    install_requirement_files,
)
from deployer.settings import UserSettings


# ---------------------------------------------------------------------------
# Loading node definitions
# ---------------------------------------------------------------------------

def load_custom_nodes() -> list[CustomNode]:
    """Load custom node definitions, using ``user_settings.json`` when available."""

    def _entries_from_path(json_path: str) -> list[dict]:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # user_settings stores {"nodes": [...]} ; plain manifests store [...]
        if isinstance(data, dict):
            return data.get("nodes", [])
        return data

    # If user_settings.json exists and is non-empty, use it exclusively
    if UserSettings.exists():
        entries = UserSettings.load_nodes()
        if entries:
            return [CustomNode(e["repo"], e["ref"], e["description"]) for e in entries]

    # Otherwise build from the default manifests and persist to user_settings.json
    raw_entries: list[dict] = []
    seen: set[str] = set()
    for json_path in (SOURCE_NODES_JSON, LOCAL_NODES_JSON):
        if not os.path.exists(json_path):
            continue
        for entry in _entries_from_path(json_path):
            if entry["repo"] not in seen:
                seen.add(entry["repo"])
                raw_entries.append(entry)

    UserSettings.save_nodes(raw_entries)

    return [CustomNode(e["repo"], e["ref"], e["description"]) for e in raw_entries]


# ---------------------------------------------------------------------------
# Node installation
# ---------------------------------------------------------------------------

def install_nodes(nodes: list[CustomNode]) -> None:
    """Clone and link the given custom nodes into ComfyUI."""
    if not nodes:
        return
    print("Installing custom nodes...")
    for node in nodes:
        node.clone()
        node.link()
        node.is_installed = True


# ---------------------------------------------------------------------------
# Pip requirements
# ---------------------------------------------------------------------------

def install_requirements(nodes: list[CustomNode], max_depth: int = 4) -> None:
    """Install pip requirements for the given nodes.

    Walks each node directory up to *max_depth* levels, collects every
    ``requirements.txt`` found and installs them in a single resolver pass
    (via :func:`install_requirement_files`).
    """
    if not nodes:
        return

    print("Installing requirements...")

    # Pre-built wheel for insightface (Windows compatibility)
    if os.path.exists(INSIGHTFACE_WHL):
        install_packages(PYTHON_EXE, [INSIGHTFACE_WHL])

    req_files: list[str] = []
    for node in nodes:
        req_files.extend(find_requirement_files(node.comfyui_path, max_depth))

    install_requirement_files(PYTHON_EXE, req_files)


# ---------------------------------------------------------------------------
# Full install orchestration
# ---------------------------------------------------------------------------

def install(
    nodes_to_install: list[CustomNode],
    nodes_with_requirements: list[CustomNode],
) -> None:
    """Run the complete installation pipeline in the correct order."""
    install_nodes(nodes_to_install)
    install_requirements(nodes_with_requirements)

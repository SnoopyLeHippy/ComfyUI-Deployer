"""Installation logic for ComfyUI custom nodes and their dependencies."""

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Callable

from deployer.config import (
    CUSTOM_NODES_DIR,
    INSIGHTFACE_WHL,
    LOCAL_NODES_JSON,
    PYTHON_EXE,
    SOURCE_NODES_JSON,
)
from deployer.core.node import CustomNode, repo_folder_name, repo_identity
from deployer.core.pip_runner import (
    ensure_uv,
    find_requirement_files,
    install_packages,
    install_requirement_files,
)
from deployer.settings import UserSettings


# Share of the overall progress spent cloning; requirements take the rest.
_CLONE_SHARE = 0.7


# ---------------------------------------------------------------------------
# Loading node definitions
# ---------------------------------------------------------------------------

def _has_repo(entry) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("repo"), str) and bool(entry["repo"].strip())


def _node_from_entry(entry: dict) -> CustomNode:
    """Build a node from a list entry; ``ref`` and ``description`` are optional."""
    return CustomNode(entry["repo"], entry.get("ref") or "main", entry.get("description") or "")


def read_node_list(json_path: str) -> list[dict]:
    """The entries of a node list file: ``[...]`` (a manifest) or ``{"nodes": [...]}``.

    Entries without a ``repo`` are dropped. Raises ``OSError`` when the file
    cannot be read, ``ValueError`` when it is not JSON or holds no list.
    """
    with open(json_path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("nodes", [])
    if not isinstance(data, list):
        raise ValueError("it holds no list of nodes")
    return [entry for entry in data if _has_repo(entry)]


def load_custom_nodes() -> list[CustomNode]:
    """Load custom node definitions, using ``user_settings.json`` when available.

    On a fresh clone (no ``user_settings.json``, or one without nodes) the list
    is seeded from the manifests — the legacy GitLab one, then the tracked
    ``custom_nodes.json`` — and persisted to ``user_settings.json``. Entries
    without a ``repo`` are skipped; ``ref`` defaults to ``"main"``.
    """
    # If user_settings.json exists and is non-empty, use it exclusively
    if UserSettings.exists():
        entries = UserSettings.load_nodes()
        if entries:
            return [_node_from_entry(e) for e in entries if _has_repo(e)]

    # Otherwise build from the default manifests and persist to user_settings.json
    raw_entries: list[dict] = []
    seen: set[str] = set()
    for json_path in (SOURCE_NODES_JSON, LOCAL_NODES_JSON):
        if not os.path.exists(json_path):
            continue
        for entry in read_node_list(json_path):
            if entry["repo"] not in seen:
                seen.add(entry["repo"])
                raw_entries.append(entry)

    UserSettings.save_nodes(raw_entries)

    return [_node_from_entry(e) for e in raw_entries]


def add_listed_nodes(entries: list[dict]) -> list[dict]:
    """Make *entries* part of the tracked list (``cli.py install-nodes --nodes-file``).

    With no list yet — no ``user_settings.json``, or one without nodes — they
    **are** the list: the manifests (``custom_nodes.json``) are not read. With
    one, the entries it does not track are appended; a tracked node — same
    repository (:func:`repo_identity`) or same folder name
    (:func:`repo_folder_name`, compared without case: one folder on Windows)
    — keeps its ref and description, the user's own choice. Duplicates inside
    *entries* are added once. Only ``repo`` (trimmed), ``ref`` and
    ``description`` are written; the file's other keys are preserved.

    Returns the entries added.
    """
    existing = UserSettings.load_nodes()
    if not isinstance(existing, list):
        existing = []
    tracked = [entry for entry in existing if _has_repo(entry)]
    if not tracked:
        existing = []
    identities = {repo_identity(entry["repo"].strip()) for entry in tracked}
    folders = {repo_folder_name(entry["repo"].strip()).lower() for entry in tracked}
    added: list[dict] = []
    for entry in entries:
        if not _has_repo(entry):
            continue
        repo = entry["repo"].strip()
        identity, folder = repo_identity(repo), repo_folder_name(repo).lower()
        if identity in identities or folder in folders:
            continue
        identities.add(identity)
        folders.add(folder)
        node = {"repo": repo}
        for key in ("ref", "description"):
            if isinstance(entry.get(key), str):
                node[key] = entry[key]
        added.append(node)
    if added:
        UserSettings.save_nodes(existing + added)
    return added


# ---------------------------------------------------------------------------
# Node installation
# ---------------------------------------------------------------------------

def install_nodes(nodes: list[CustomNode]) -> None:
    """Clone the given custom nodes into ComfyUI."""
    if not nodes:
        return
    print("Installing custom nodes...")
    for node in nodes:
        node.clone()
        node.is_installed = True


# ---------------------------------------------------------------------------
# Pip requirements
# ---------------------------------------------------------------------------

def install_requirements(nodes: list[CustomNode], max_depth: int = 4) -> list[str]:
    """Install pip requirements for the given nodes.

    Walks each node directory up to *max_depth* levels, collects every
    ``requirements.txt`` found and installs them in a single resolver pass
    (via :func:`install_requirement_files`). Returns the requirements files
    that failed to install.
    """
    if not nodes:
        return []

    print("Installing requirements...")

    # Pre-built wheel for insightface (Windows compatibility)
    if os.path.exists(INSIGHTFACE_WHL):
        install_packages(PYTHON_EXE, [INSIGHTFACE_WHL])

    req_files: list[str] = []
    for node in nodes:
        req_files.extend(find_requirement_files(node.comfyui_path, max_depth))

    return install_requirement_files(PYTHON_EXE, req_files)


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


# ---------------------------------------------------------------------------
# Headless install of the whole list (``cli.py install-nodes``)
# ---------------------------------------------------------------------------

@dataclass
class NodeInstallReport:
    """What :func:`install_configured_nodes` did, by node folder name."""

    added: list[str] = field(default_factory=list)  # added to the list (a --nodes-file)
    installed: list[str] = field(default_factory=list)  # cloned by this run
    present: list[str] = field(default_factory=list)  # already on disk, left as is
    failed: list[dict] = field(default_factory=list)  # {"name", "repo", "error"}
    requirements_failed: list[str] = field(default_factory=list)  # requirements.txt paths

    def as_dict(self) -> dict:
        return asdict(self)


def install_configured_nodes(
    progress: Callable[[str, float], None] = lambda message, fraction: None,
    warn: Callable[[str], None] = lambda message: None,
    listed: list[dict] | None = None,
) -> NodeInstallReport:
    """Make every node of the configured list present in ComfyUI, with its requirements.

    The headless counterpart of the window's *Install*, with no selection: the
    whole list (:func:`load_custom_nodes` — ``user_settings.json``, seeded from
    ``custom_nodes.json`` on a fresh clone). *listed* (an installer's own list)
    goes into it first (:func:`add_listed_nodes`): the list itself on a fresh
    clone, added to it otherwise. A node already on disk is left as
    it is — no update, no ref change, that stays the window's call; the others
    are cloned at their ref. Then the requirements of **every** listed node on
    disk are installed in one pass: re-running converges, so a run interrupted
    between its clones and its requirements still ends with working nodes.

    A node that fails to clone is reported in ``failed`` and never stops the
    others. *progress* receives ``(message, fraction 0..1)``, *warn* a message
    for each failure; git's and pip's own output is printed.

    Only ``git`` and ``python -m uv|pip`` are started, with direct argument
    lists — no shell, no PowerShell, no ``.bat``.
    """
    report = NodeInstallReport()
    if listed:
        report.added = [repo_folder_name(entry["repo"]) for entry in add_listed_nodes(listed)]
    nodes = load_custom_nodes()
    os.makedirs(CUSTOM_NODES_DIR, exist_ok=True)

    total = len(nodes)
    for index, node in enumerate(nodes):
        # Checked here, not through node.is_installed (computed at construction):
        # two entries sharing a folder name must not clone twice.
        if os.path.exists(node.local_path):
            report.present.append(node.name)
            continue
        progress(f"Installing {node.name} ({index + 1}/{total})", _CLONE_SHARE * index / total)
        try:
            node.clone()
        except (subprocess.CalledProcessError, OSError) as exc:
            report.failed.append({"name": node.name, "repo": node.repo, "error": str(exc)})
            warn(f"{node.name} could not be installed from {node.repo}: {exc}")
            continue
        report.installed.append(node.name)

    on_disk = [node for node in nodes if os.path.isdir(node.local_path)]
    req_files: list[str] = []
    for node in on_disk:
        req_files.extend(find_requirement_files(node.local_path, 4))
    if req_files or (on_disk and os.path.exists(INSIGHTFACE_WHL)):
        progress("Installing the custom nodes' requirements...", _CLONE_SHARE)
        # The portable archive ships without uv; pip's fallback (-U) could
        # replace its CUDA torch build — see ensure_uv.
        if not ensure_uv(PYTHON_EXE):
            warn("uv could not be installed; the requirements go through pip.")
        report.requirements_failed = install_requirements(on_disk)
        for path in report.requirements_failed:
            warn(f"Some requirements could not be installed: {path}")

    progress("Custom nodes installed.", 1.0)
    return report

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
from deployer.core import git_ops
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
    """What :func:`install_configured_nodes` / :func:`install_selected_nodes` did, by folder name."""

    added: list[str] = field(default_factory=list)  # added to the list (a --nodes-file, a --repo)
    installed: list[str] = field(default_factory=list)  # cloned by this run
    updated: list[str] = field(default_factory=list)  # pulled by this run (--update)
    present: list[str] = field(default_factory=list)  # already on disk, left as is
    failed: list[dict] = field(default_factory=list)  # {"name", "repo", "error"}
    requirements_failed: list[str] = field(default_factory=list)  # requirements.txt paths

    def as_dict(self) -> dict:
        return asdict(self)


def _install_requirements_of(paths: list[str], report: NodeInstallReport, progress, warn,
                             start: float) -> None:
    """Every ``requirements.txt`` under *paths* (4 levels deep), in one pass; failures reported."""
    req_files: list[str] = []
    for path in paths:
        req_files.extend(find_requirement_files(path, 4))
    if not (req_files or (paths and os.path.exists(INSIGHTFACE_WHL))):
        return
    progress("Installing the custom nodes' requirements...", start)
    # The portable archive ships without uv; pip's fallback (-U) could
    # replace its CUDA torch build — see ensure_uv.
    if not ensure_uv(PYTHON_EXE):
        warn("uv could not be installed; the requirements go through pip.")
    if os.path.exists(INSIGHTFACE_WHL):
        install_packages(PYTHON_EXE, [INSIGHTFACE_WHL])
    report.requirements_failed = install_requirement_files(PYTHON_EXE, req_files)
    for path in report.requirements_failed:
        warn(f"Some requirements could not be installed: {path}")


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

    on_disk = [node.local_path for node in nodes if os.path.isdir(node.local_path)]
    _install_requirements_of(on_disk, report, progress, warn, _CLONE_SHARE)

    progress("Custom nodes installed.", 1.0)
    return report


# ---------------------------------------------------------------------------
# Targeted install (``cli.py install-nodes --repo / --update / --repair``)
# ---------------------------------------------------------------------------

def folder_of_repo(repo: str) -> str | None:
    """The ``custom_nodes/`` folder holding *repo*: by git origin, else by folder name.

    ``None`` when there is none. A folder named like *repo* whose origin is
    another repository is not *repo*'s (a fork, a namesake): raises
    ``ValueError``, since cloning there is impossible and updating it wrong.
    """
    identity = repo_identity(repo)
    name = repo_folder_name(repo).lower()
    named = None
    if not os.path.isdir(CUSTOM_NODES_DIR):
        return None
    for entry in os.scandir(CUSTOM_NODES_DIR):
        if not entry.is_dir(follow_symlinks=True) or entry.name.endswith(".disabled"):
            continue
        origin = git_ops.get_remote_url(entry.path) if git_ops.is_repo_root(entry.path) else ""
        if origin and repo_identity(origin) == identity:
            return entry.path
        if entry.name.lower() == name:
            named = (entry.path, origin)
    if named is None:
        return None
    path, origin = named
    if origin:
        raise ValueError(f"{os.path.basename(path)} holds another repository ({origin})")
    return path


def install_selected_nodes(
    install: list[str] = (),
    update: list[str] = (),
    repair: list[str] = (),
    progress: Callable[[str, float], None] = lambda message, fraction: None,
    warn: Callable[[str], None] = lambda message: None,
) -> NodeInstallReport:
    """Make these packs usable — and only these: what a workflow's resolution asked for.

    Each repository is added to the tracked list first (an added pack is one
    a workflow relies on). Then:

    * *install* — cloned at its default branch when absent; one already on
      disk is left as it is (``present``);
    * *update* — ``git pull --ff-only`` of its clone: refused (``failed``) when
      it is not a clone, has local changes, or is on no branch (pinned);
    * *repair* — nothing on the git side.

    Then the requirements of every one of them on disk, in one pass: a pack
    whose import failed for a missing dependency loads at ComfyUI's next start.
    A failure is reported and never stops the others. Only ``git`` and
    ``python -m uv|pip`` are started, with direct argument lists.
    """
    report = NodeInstallReport()
    wanted = [r.strip() for r in [*install, *update, *repair] if isinstance(r, str) and r.strip()]
    report.added = [repo_folder_name(e["repo"]) for e in add_listed_nodes([{"repo": r} for r in wanted])]
    os.makedirs(CUSTOM_NODES_DIR, exist_ok=True)

    targets: list[str] = []
    jobs = [("install", r) for r in install] + [("update", r) for r in update] + [("repair", r) for r in repair]
    total = max(len(jobs), 1)
    for index, (kind, repo) in enumerate(jobs):
        repo = repo.strip()
        name = repo_folder_name(repo)
        progress(f"{kind.capitalize()} {name} ({index + 1}/{len(jobs)})", _CLONE_SHARE * index / total)
        try:
            path = folder_of_repo(repo)
            if kind == "install":
                if path is not None:
                    report.present.append(os.path.basename(path))
                else:
                    node = CustomNode(repo, "main", "")
                    node.clone()
                    path = node.local_path
                    report.installed.append(name)
            elif path is None:
                raise ValueError("it is not installed")
            elif kind == "update":
                _update_clone(path)
                report.updated.append(os.path.basename(path))
        except (subprocess.CalledProcessError, OSError, ValueError) as exc:
            report.failed.append({"name": name, "repo": repo, "error": str(exc)})
            warn(f"{name} could not be {'installed' if kind == 'install' else kind + 'd'} "
                 f"from {repo}: {exc}")
            continue
        if path not in targets:
            targets.append(path)

    _install_requirements_of(targets, report, progress, warn, _CLONE_SHARE)
    progress("Custom nodes ready.", 1.0)
    return report


def _update_clone(path: str) -> None:
    """Fast-forward a pack's clone to its upstream; ``ValueError`` when it must not be touched."""
    if not git_ops.is_repo_root(path):
        raise ValueError("it is not a git clone")
    if git_ops.is_dirty(path):
        raise ValueError("it has local changes")
    branch = git_ops.get_current_branch(path)
    if not branch or branch == "HEAD":
        raise ValueError("it is pinned to a commit (no branch to update)")
    git_ops.pull_fast_forward(path)

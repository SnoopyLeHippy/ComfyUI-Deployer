"""Resolve a workflow's node types to the custom-node packs this ComfyUI still needs.

The classification itself is pure (:mod:`deployer.core.node_resolution`); this
module gathers the facts it needs on this machine and hands them over:

* what ComfyUI loaded — its ``/object_info`` when the caller has it (the
  ground truth), else the **static scan**: the ``NODE_CLASS_MAPPINGS`` keys and
  V3 ``node_id`` values found by regex in ComfyUI's ``nodes.py``,
  ``comfy_extras/`` and ``comfy_api_nodes/`` (recursively) and in every
  ``custom_nodes/`` folder;
* the pack folders in ``custom_nodes/`` with their git origin;
* the tracked list (``user_settings.json``);
* the Manager DB (:mod:`deployer.core.node_db`, cached a day) and the Comfy
  registry.

:func:`resolve_nodes` is what ``cli.py resolve-nodes`` runs;
:func:`resolve_workflow_nodes` keeps the window's older result shape.
"""

import http.client
import json
import os
import re
import urllib.parse

from deployer.config import (
    COMFY_EXTRAS_DIR,
    COMFYUI_DIR,
    COMFYUI_NODES_PY,
    CUSTOM_NODES_DIR,
)
from deployer.core import git_ops
from deployer.core.node import repo_identity
from deployer.core.node_db import NodeDbUnavailable, load_node_db, registry_repository
from deployer.core.node_resolution import (
    Folder,
    Resolution,
    loaded_from_object_info,
    loaded_from_scan,
    resolve,
    wanted_from_workflow,
)
from deployer.core.workflow_io import load_workflow_graph

COMFY_API_NODES_DIR = os.path.join(COMFYUI_DIR, "comfy_api_nodes")

_NODE_CLASS_MAPPINGS_RE = re.compile(
    r'NODE_CLASS_MAPPINGS\s*(?:\[\s*["\']([^"\']+)["\']\s*\]\s*=|\.update\s*\(\s*\{([^}]*)\})'
)
_DICT_KEY_RE = re.compile(r'["\']([^"\']+)["\']\s*:')

# Newer comfy_extras / comfy_api_nodes modules register nodes via io.Schema(node_id="...").
_NODE_ID_RE = re.compile(r'node_id\s*=\s*["\']([^"\']+)["\']')


# ---------------------------------------------------------------------------
# Static scan (no running ComfyUI)
# ---------------------------------------------------------------------------

def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _extract_mapping_keys(source: str) -> set[str]:
    """Pull keys out of ``NODE_CLASS_MAPPINGS = {...}`` literals in *source*.

    Handles the dict literal form, ``NODE_CLASS_MAPPINGS["x"] = ...``,
    ``.update({...})``, and the ``io.Schema(node_id="...")`` pattern of V3
    nodes. A key computed at run time (``MAPPINGS[Node.NAME] = Node``) is
    invisible here — what ``/object_info`` exists for.
    """
    keys: set[str] = set()

    for m in re.finditer(r"NODE_CLASS_MAPPINGS\s*=\s*\{", source):
        start = m.end()
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        block = source[start : i - 1]
        keys.update(_DICT_KEY_RE.findall(block))

    for m in _NODE_CLASS_MAPPINGS_RE.finditer(source):
        single, block = m.group(1), m.group(2)
        if single:
            keys.add(single)
        if block:
            keys.update(_DICT_KEY_RE.findall(block))

    keys.update(_NODE_ID_RE.findall(source))
    return keys


def _scan_python_tree(root: str, *, followlinks: bool = False) -> set[str]:
    types: set[str] = set()
    if not os.path.isdir(root):
        return types
    for dirpath, dirnames, filenames in os.walk(root, followlinks=followlinks):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", "node_modules")]
        for fname in filenames:
            if fname.endswith(".py"):
                try:
                    types.update(_extract_mapping_keys(_read_text(os.path.join(dirpath, fname))))
                except OSError:
                    continue
    return types


def load_builtin_node_types() -> set[str]:
    """Node types of ComfyUI itself: ``nodes.py``, ``comfy_extras/``, ``comfy_api_nodes/``."""
    print("Scanning ComfyUI builtin node types...")
    builtins: set[str] = set()
    if os.path.exists(COMFYUI_NODES_PY):
        builtins.update(_extract_mapping_keys(_read_text(COMFYUI_NODES_PY)))
    builtins |= _scan_python_tree(COMFY_EXTRAS_DIR)
    builtins |= _scan_python_tree(COMFY_API_NODES_DIR)
    return builtins


def extract_types_from_node_dir(node_dir: str) -> set[str]:
    """``NODE_CLASS_MAPPINGS`` keys declared by Python files under *node_dir* (junctions followed)."""
    return _scan_python_tree(node_dir, followlinks=True)


def _pack_dirs() -> list[str]:
    """The folders of ``custom_nodes/`` ComfyUI would load (no ``.disabled``, no dot folder)."""
    if not os.path.isdir(CUSTOM_NODES_DIR):
        return []
    names = []
    for entry in os.scandir(CUSTOM_NODES_DIR):
        if entry.name.startswith((".", "__")) or entry.name.endswith(".disabled"):
            continue
        if entry.is_dir(follow_symlinks=True):
            names.append(entry.name)
    return sorted(names, key=str.lower)


def load_installed_custom_node_types() -> set[str]:
    """Node types the sources in ``custom_nodes/`` declare (static scan)."""
    print("Scanning installed custom nodes...")
    types: set[str] = set()
    for name in _pack_dirs():
        types |= extract_types_from_node_dir(os.path.join(CUSTOM_NODES_DIR, name))
    return types


# ---------------------------------------------------------------------------
# Facts about this machine
# ---------------------------------------------------------------------------

def pack_folders(*, with_declared: bool) -> list[Folder]:
    """``custom_nodes/``'s pack folders, each with its git origin (and declared types)."""
    folders = []
    for name in _pack_dirs():
        path = os.path.join(CUSTOM_NODES_DIR, name)
        origin = git_ops.get_remote_url(path) if git_ops.is_repo_root(path) else ""
        declared = extract_types_from_node_dir(path) if with_declared else set()
        folders.append(Folder(name, origin, declared))
    return folders


def tracked_identities() -> set[str]:
    """Identities of the repositories in ``user_settings.json``'s node list."""
    from deployer.settings import UserSettings

    nodes = UserSettings.load_nodes()
    return {repo_identity(n["repo"]) for n in nodes if isinstance(n, dict) and isinstance(n.get("repo"), str)}


def fetch_object_info(comfy_url: str, *, timeout: int = 30) -> dict:
    """``GET <comfy_url>/object_info`` from a ComfyUI on this machine or the LAN (no proxy).

    ``http.client`` with a kept-alive connection the client closes once the
    body is read — not ``urllib``, which asks ``Connection: close``: then the
    server closes first, and on some Windows machines (an endpoint filter on
    loopback) the 2 MB answer stalls ~20 s and ends in a reset (WinError 10054).
    """
    parsed = urllib.parse.urlsplit(comfy_url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{comfy_url!r} is no http(s) URL")
    connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(parsed.hostname, parsed.port, timeout=timeout)
    path = parsed.path.rstrip("/") + "/object_info"
    try:
        connection.request("GET", path, headers={"User-Agent": "ComfyUI-Deployer", "Accept": "application/json"})
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    if response.status != 200:
        raise ValueError(f"{comfy_url} answered HTTP {response.status} for /object_info")
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{comfy_url}/object_info returned no object")
    return data


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def resolve_nodes(wanted, *, object_info: dict | None = None, refresh_db: bool = False,
                  use_registry: bool = True, tracked: set[str] | None = None,
                  warn=print) -> Resolution:
    """Resolve *wanted* (:mod:`node_resolution`'s ``WantedNode`` map) on this ComfyUI.

    With *object_info*, what ComfyUI loaded is exact; without it, the static
    scan stands in. A Manager DB that cannot be had (offline, no cache) is a
    warning: the workflow's own ``aux_id`` / ``cnr_id`` still resolve.
    """
    if object_info is not None:
        loaded = loaded_from_object_info(object_info)
        folders = pack_folders(with_declared=False)
    else:
        folders = pack_folders(with_declared=True)
        types = load_builtin_node_types()
        for folder in folders:
            types |= folder.declared
        loaded = loaded_from_scan(types)

    missing = [name for name in wanted if name not in loaded.types]
    db = None
    if missing:
        try:
            db = load_node_db(refresh=refresh_db)
        except NodeDbUnavailable as exc:
            warn(f"The custom node database is unavailable ({exc}); only the workflow's own "
                 "pack ids can be resolved.")
    registry = registry_repository if use_registry else None
    return resolve(wanted, loaded, db, folders,
                   tracked if tracked is not None else tracked_identities(), registry)


# ---------------------------------------------------------------------------
# The window's "Add from workflow" / "Create Bundle from workflow"
# ---------------------------------------------------------------------------

def extract_workflow_node_types(workflow_path: str) -> set[str]:
    """Every node type a workflow (``.json`` or a generated image) uses, muted ones included."""
    return set(wanted_from_workflow(load_workflow_graph(workflow_path), executable_only=False))


class ResolvedRepo:
    """A repo that unambiguously provides one or more missing workflow node types."""

    __slots__ = ("repo", "description", "node_types")

    def __init__(self, repo: str, description: str, node_types: list[str]):
        self.repo = repo
        self.description = description
        self.node_types = node_types

    def __repr__(self) -> str:
        return f"ResolvedRepo({self.repo!r}, types={self.node_types!r})"


class ConflictEntry:
    """Node type(s) that more than one repo could provide; the user picks."""

    __slots__ = ("node_types", "repo_options")

    def __init__(self, node_types: list[str], repo_options: list[str]):
        self.node_types = node_types
        self.repo_options = repo_options

    def __repr__(self) -> str:
        return f"ConflictEntry(types={self.node_types!r}, options={self.repo_options!r})"


def resolve_workflow_nodes(
    workflow_path: str,
    known_repos: set[str],
) -> tuple[list[ResolvedRepo], list[ConflictEntry], list[str], dict[str, str]]:
    """The window's view of :func:`resolve_nodes` (static scan, every node).

    Returns ``(resolved, conflicts, unresolved, repo_to_desc)``: the packs to
    install (``install``), the ambiguous types, and the types nothing installs
    (``unknown``, ``core``, ``blocked``). A pack on disk that lacks a type
    (``update`` / ``repair``) is printed — the window's cards update it.
    *known_repos* are the repos the window already shows as installed.
    """
    wanted = wanted_from_workflow(load_workflow_graph(workflow_path), executable_only=False)
    tracked = {repo_identity(r) for r in known_repos} | tracked_identities()
    result = resolve_nodes(wanted, tracked=tracked)
    if result.is_empty():
        print("All node types are already available.")
        return ([], [], [], {})

    resolved, repo_to_desc = [], {}
    for pack in result.packs:
        repo_to_desc[pack["repo"]] = pack["description"]
        if pack["action"] == "install":
            resolved.append(ResolvedRepo(pack["repo"], pack["description"], pack["types"]))
        elif pack["action"] == "update":
            print(f"'{pack['folder']}' is installed but lacks {', '.join(pack['types'])}: update it.")
        else:
            print(f"'{pack['folder']}' declares {', '.join(pack['types'])} but ComfyUI may not load "
                  "it: install its requirements.")
    conflicts = []
    for entry in result.ambiguous:
        options = [o["repo"] for o in entry["options"]]
        for option in entry["options"]:
            repo_to_desc[option["repo"]] = option["description"]
        conflicts.append(ConflictEntry(entry["types"], options))
    unresolved = sorted(result.unknown + result.core + [t for b in result.blocked for t in b["types"]])
    for ntype in result.core:
        print(f"{ntype} is a ComfyUI node this ComfyUI lacks: update ComfyUI.")
    return (resolved, conflicts, unresolved, repo_to_desc)

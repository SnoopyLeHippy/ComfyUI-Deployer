"""Resolve workflow node types to the git repositories that provide them.

Given a ComfyUI workflow JSON, this module returns the set of custom-node
git repos required to load it. Built-in nodes (registered in ComfyUI's own
``nodes.py`` / ``comfy_extras``) and already-installed custom nodes are
filtered out; the remaining types are matched against the ComfyUI-Manager
extension node map (fetched fresh on every call, falling back to a local
cache if the network is unavailable).
"""

import json
import os
import re

from deployer.config import (
    CACHE_DIR,
    COMFY_EXTRAS_DIR,
    COMFYUI_NODES_PY,
    CUSTOM_NODE_LIST_URL,
    CUSTOM_NODES_DIR,
    EXTENSION_NODE_MAP_URL,
)
from deployer.core.http import download_file
from deployer.core.workflow_io import load_workflow_graph


# Node types handled by the ComfyUI frontend — never in NODE_CLASS_MAPPINGS.
_FRONTEND_ONLY_TYPES = {
    "Note",
    "MarkdownNote",
    "Reroute",
    "PrimitiveNode",
    "Primitive",
}

_NODE_CLASS_MAPPINGS_RE = re.compile(
    r'NODE_CLASS_MAPPINGS\s*(?:\[\s*["\']([^"\']+)["\']\s*\]\s*=|\.update\s*\(\s*\{([^}]*)\})'
)
_DICT_KEY_RE = re.compile(r'["\']([^"\']+)["\']\s*:')

# Newer comfy_extras modules register nodes via io.Schema(node_id="...").
_NODE_ID_RE = re.compile(r'node_id\s*=\s*["\']([^"\']+)["\']')


# ---------------------------------------------------------------------------
# Python source parsing helpers
# ---------------------------------------------------------------------------

def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _extract_mapping_keys(source: str) -> set[str]:
    """Pull keys out of ``NODE_CLASS_MAPPINGS = {...}`` literals in *source*.

    Handles the dict literal form, ``NODE_CLASS_MAPPINGS["x"] = ...``,
    ``.update({...})``, and the newer ``io.Schema(node_id="...")`` pattern
    used by comfy_extras.
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


def load_builtin_node_types() -> set[str]:
    """Node types registered by ComfyUI core (``nodes.py`` + ``comfy_extras``)."""
    builtins: set[str] = set()
    if os.path.exists(COMFYUI_NODES_PY):
        builtins.update(_extract_mapping_keys(_read_text(COMFYUI_NODES_PY)))

    if os.path.isdir(COMFY_EXTRAS_DIR):
        for entry in os.scandir(COMFY_EXTRAS_DIR):
            if entry.is_file() and entry.name.endswith(".py"):
                builtins.update(_extract_mapping_keys(_read_text(entry.path)))

    return builtins


def load_installed_custom_node_types() -> set[str]:
    """Node types registered by custom nodes already on disk in ``custom_nodes/``.

    Walks every Python file under ``CUSTOM_NODES_DIR`` (following junctions
    for GitLab-linked nodes) and extracts their ``NODE_CLASS_MAPPINGS`` keys.
    This lets us skip workflow types that are already satisfied by an
    installed-but-untracked (orphan) custom node.
    """
    types: set[str] = set()
    if not os.path.isdir(CUSTOM_NODES_DIR):
        return types

    for entry in os.scandir(CUSTOM_NODES_DIR):
        if not entry.is_dir(follow_symlinks=True):
            continue
        for dirpath, _, filenames in os.walk(entry.path, followlinks=True):
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                try:
                    source = _read_text(os.path.join(dirpath, fname))
                    types.update(_extract_mapping_keys(source))
                except OSError:
                    continue
    return types


# ---------------------------------------------------------------------------
# Workflow JSON parsing
# ---------------------------------------------------------------------------

def extract_workflow_node_types(workflow_path: str) -> set[str]:
    """Return the set of ``node.type`` values used by a workflow.

    *workflow_path* may be a ``.json`` export or a ComfyUI-generated image
    with the workflow embedded in its metadata.
    """
    data = load_workflow_graph(workflow_path)
    types: set[str] = set()
    for node in data.get("nodes", []):
        ntype = node.get("type")
        if isinstance(ntype, str) and ntype:
            types.add(ntype)
    return types


# ---------------------------------------------------------------------------
# Network helpers — always fetch fresh, fall back to cache on error
# ---------------------------------------------------------------------------

def _cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, name)


def _load_fresh_json(name: str, url: str) -> dict:
    """Always download *url* to the local cache file, return parsed JSON.

    If the download fails, the existing cached copy is used as a fallback
    so the feature degrades gracefully when offline.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(name)
    try:
        download_file(url, path, timeout=30)
    except Exception as exc:  # noqa: BLE001
        if not os.path.exists(path):
            raise RuntimeError(
                f"Failed to download {url} and no local cache available: {exc}"
            ) from exc
        print(f"Warning: could not refresh {name} ({exc}); using cached copy")

    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# DB index builders
# ---------------------------------------------------------------------------

def _build_type_to_repos_index(extension_map: dict) -> dict[str, list[str]]:
    """``{node_type: [repo_url, ...]}`` — all repos that declare a type."""
    index: dict[str, list[str]] = {}
    for repo_url, entry in extension_map.items():
        if not isinstance(entry, list) or not entry:
            continue
        node_types = entry[0]
        if not isinstance(node_types, list):
            continue
        for ntype in node_types:
            if isinstance(ntype, str):
                index.setdefault(ntype, []).append(repo_url)
    return index


def _build_nodename_patterns(extension_map: dict) -> list[tuple[re.Pattern[str], str]]:
    """Regexes that match display-name suffixes like ``Image Comparer (rgthree)``."""
    patterns: list[tuple[re.Pattern[str], str]] = []
    for repo_url, entry in extension_map.items():
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        meta = entry[1]
        if not isinstance(meta, dict):
            continue
        pattern = meta.get("nodename_pattern")
        if not isinstance(pattern, str) or not pattern:
            continue
        try:
            patterns.append((re.compile(pattern), repo_url))
        except re.error:
            continue
    return patterns


def _build_repo_to_description(custom_node_list: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in custom_node_list.get("custom_nodes", []):
        ref = entry.get("reference", "")
        desc = entry.get("description", "") or ""
        if ref:
            out[ref] = desc
        for f in entry.get("files", []) or []:
            if isinstance(f, str) and f not in out:
                out[f] = desc
    return out


# ---------------------------------------------------------------------------
# URL normalisation helpers
# ---------------------------------------------------------------------------

def _normalize_repo_url(url: str) -> str:
    return url.strip().rstrip("/").removesuffix(".git")


def _repo_basename(url: str) -> str:
    return _normalize_repo_url(url).rsplit("/", 1)[-1].lower()


# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------

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
    """Node type(s) that can be satisfied by more than one non-tracked repo.

    The user must pick which repo (if any) to install.
    Types with the same set of candidate repos are grouped into one entry.
    """

    __slots__ = ("node_types", "repo_options")

    def __init__(self, node_types: list[str], repo_options: list[str]):
        self.node_types = node_types      # e.g. ["TypeA", "TypeB"]
        self.repo_options = repo_options  # e.g. ["https://github.com/x/foo", ...]

    def __repr__(self) -> str:
        return f"ConflictEntry(types={self.node_types!r}, options={self.repo_options!r})"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def resolve_workflow_nodes(
    workflow_path: str,
    known_repos: set[str],
) -> tuple[list[ResolvedRepo], list[ConflictEntry], list[str], dict[str, str]]:
    """Resolve a workflow's missing nodes to git repositories.

    *known_repos* is the set of repo URLs tracked in ``user_settings.json``.
    Already-installed custom nodes on disk are also checked.

    Returns ``(resolved, conflicts, unresolved, repo_to_desc)``:

    * ``resolved``     — repos with exactly one candidate; safe to auto-add.
    * ``conflicts``    — node type groups where 2+ repos could provide them;
                         the user must choose.
    * ``unresolved``   — node types not found in the DB at all.
    * ``repo_to_desc`` — ``{repo_url: description}`` for any repo surfaced.
    """
    workflow_types = extract_workflow_node_types(workflow_path)
    builtins = load_builtin_node_types()
    installed = load_installed_custom_node_types()

    candidates = sorted(workflow_types - builtins - installed - _FRONTEND_ONLY_TYPES)
    if not candidates:
        return ([], [], [], {})

    extension_map = _load_fresh_json("extension-node-map.json", EXTENSION_NODE_MAP_URL)
    custom_node_list = _load_fresh_json("custom-node-list.json", CUSTOM_NODE_LIST_URL)

    type_to_repos = _build_type_to_repos_index(extension_map)
    nodename_patterns = _build_nodename_patterns(extension_map)
    repo_to_desc = _build_repo_to_description(custom_node_list)

    known_normalized = {_normalize_repo_url(r) for r in known_repos}
    known_basenames = {_repo_basename(r) for r in known_repos}

    def _is_known(repo: str) -> bool:
        return (
            _normalize_repo_url(repo) in known_normalized
            or _repo_basename(repo) in known_basenames
        )

    def _candidate_repos(ntype: str) -> list[str]:
        repos = list(type_to_repos.get(ntype, []))
        for pattern, repo in nodename_patterns:
            if pattern.search(ntype) and repo not in repos:
                repos.append(repo)
        return repos

    auto_by_repo: dict[str, list[str]] = {}        # repo → [types] (single candidate)
    conflict_groups: dict[tuple[str, ...], list[str]] = {}  # (repos…) → [types]
    unresolved: list[str] = []

    for ntype in candidates:
        all_repos = _candidate_repos(ntype)
        if not all_repos:
            unresolved.append(ntype)
            continue
        if any(_is_known(r) for r in all_repos):
            continue

        non_known = [r for r in all_repos if not _is_known(r)]
        if len(non_known) == 1:
            auto_by_repo.setdefault(non_known[0], []).append(ntype)
        else:
            key = tuple(sorted(non_known))
            conflict_groups.setdefault(key, []).append(ntype)

    resolved = [
        ResolvedRepo(repo, repo_to_desc.get(repo, ""), sorted(types))
        for repo, types in sorted(auto_by_repo.items())
    ]
    conflicts = [
        ConflictEntry(sorted(types), list(repos_key))
        for repos_key, types in sorted(conflict_groups.items())
    ]
    return (resolved, conflicts, unresolved, repo_to_desc)

"""Which custom-node packs a workflow still needs here, and what to do with each.

Pure: no network, no git, no ``deployer.config``. The callers gather the facts
(the workflow, what ComfyUI loaded, the folders in ``custom_nodes/``, the
tracked list, the DB) and :func:`resolve` classifies every missing node type:

* ``install`` — the pack is not on disk: clone it;
* ``update`` — the pack is loaded but lacks the type (it came in a later
  version): pull it;
* ``repair`` — the pack is on disk but ComfyUI loaded none of its types (its
  import failed — a missing pip dependency, typically): install its
  requirements;
* ``ambiguous`` — several repositories declare the type and nothing tells
  them apart: the user picks;
* ``core`` — a ComfyUI node this ComfyUI lacks: update ComfyUI itself;
* ``blocked`` — the pack's folder holds another repository, or the DB entry
  is no git repository;
* ``unknown`` — no source knows the type.

**What ComfyUI loaded** is best read from its ``/object_info``
(:func:`loaded_from_object_info`): each type carries ``python_module``, so a
``custom_nodes/`` folder that provides none failed its import. Without a
running ComfyUI, :func:`loaded_from_scan` takes the static scan instead
(regexes over the sources) — then a failed import cannot be told apart, and
``repair`` is only guessed from the folder's own sources.

**Which pack provides a type**, strongest first: the node's own
``properties.aux_id`` (``owner/repo``, written by ComfyUI's frontend for a
pack outside the registry), its ``properties.cnr_id`` (a registry id: the
Manager DB's id or folder name, else the Comfy registry), then the Manager
DB's type map (a single candidate, or the one already tracked / on disk).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from deployer.core.node import repo_folder_name, repo_identity

#: Node types only ComfyUI's frontend knows, whatever the packs installed.
FRONTEND_TYPES = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "Primitive", "Label"}

#: Frontend-only node types a pack brings: in no ``/object_info``, even installed.
FRONTEND_PACK_TYPES = {
    "SetNode": "https://github.com/kijai/ComfyUI-KJNodes",
    "GetNode": "https://github.com/kijai/ComfyUI-KJNodes",
}

#: Litegraph node modes that never execute: 2 muted ("never"), 4 bypassed.
_SILENT_MODES = {2, 4}

_AUX_ID = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CORE_CNR = "comfy-core"


# ---------------------------------------------------------------------------
# What the workflow wants
# ---------------------------------------------------------------------------

@dataclass
class WantedNode:
    """A node type the workflow uses, with what its nodes say about their pack."""

    type: str
    cnr_id: str = ""
    aux_id: str = ""
    versions: list[str] = field(default_factory=list)

    def note(self, cnr_id, aux_id, ver) -> None:
        if isinstance(cnr_id, str) and cnr_id.strip() and not self.cnr_id:
            self.cnr_id = cnr_id.strip()
        if isinstance(aux_id, str) and aux_id.strip() and not self.aux_id:
            self.aux_id = aux_id.strip()
        if isinstance(ver, str) and ver.strip() and ver.strip() not in self.versions:
            self.versions.append(ver.strip())


def _subgraph_ids(graph: dict) -> set[str]:
    ids: set[str] = set()
    definitions = graph.get("definitions") if isinstance(graph, dict) else None
    for sub in (definitions.get("subgraphs") or []) if isinstance(definitions, dict) else []:
        if isinstance(sub, dict):
            if isinstance(sub.get("id"), str):
                ids.add(sub["id"])
            ids |= _subgraph_ids(sub)
    return ids


def _graph_nodes(graph: dict, executable_only: bool):
    """Every node of *graph*, subgraph definitions and legacy group nodes included."""
    if not isinstance(graph, dict):
        return
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if executable_only and node.get("mode") in _SILENT_MODES:
            continue
        yield node
    definitions = graph.get("definitions")
    for sub in (definitions.get("subgraphs") or []) if isinstance(definitions, dict) else []:
        yield from _graph_nodes(sub, executable_only)
    # Legacy group nodes (type "workflow>Name"): their inner nodes live in extra.groupNodes.
    extra = graph.get("extra")
    groups = extra.get("groupNodes") if isinstance(extra, dict) else None
    for group in groups.values() if isinstance(groups, dict) else []:
        if isinstance(group, dict):
            yield from _graph_nodes({"nodes": group.get("nodes")}, executable_only)


def wanted_from_workflow(data, *, executable_only: bool = True) -> dict[str, WantedNode]:
    """The node types of a workflow graph (``{"nodes": [...]}``) or an API prompt.

    Subgraph instances (their type is a definition's UUID), legacy group
    nodes (``workflow>…`` / ``workflow/…``) and frontend types are left out.
    *executable_only* also drops muted and bypassed nodes: what a run needs,
    while loading the workflow in ComfyUI's window wants them all.
    """
    wanted: dict[str, WantedNode] = {}

    def add(ntype, props=None) -> None:
        if not isinstance(ntype, str) or not ntype.strip() or ntype in FRONTEND_TYPES:
            return
        if ntype.startswith(("workflow>", "workflow/")):
            return
        entry = wanted.setdefault(ntype, WantedNode(ntype))
        if isinstance(props, dict):
            entry.note(props.get("cnr_id"), props.get("aux_id"), props.get("ver"))

    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        skip = _subgraph_ids(data)
        for node in _graph_nodes(data, executable_only):
            if node.get("type") not in skip:
                add(node.get("type"), node.get("properties"))
    elif isinstance(data, dict):  # API prompt: {id: {"class_type", "inputs"}}
        for node in data.values():
            if isinstance(node, dict):
                add(node.get("class_type"))
    return wanted


def wanted_from_list(items) -> dict[str, WantedNode]:
    """``["Type", …]`` or ``[{"type", "cnr_id"?, "aux_id"?, "ver"?}, …]`` (camelCase accepted)."""
    wanted: dict[str, WantedNode] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            item = {"type": item}
        if not isinstance(item, dict):
            continue
        ntype = item.get("type")
        if not isinstance(ntype, str) or not ntype.strip() or ntype in FRONTEND_TYPES:
            continue
        entry = wanted.setdefault(ntype.strip(), WantedNode(ntype.strip()))
        entry.note(item.get("cnr_id", item.get("cnrId")), item.get("aux_id", item.get("auxId")),
                   item.get("ver"))
    return wanted


# ---------------------------------------------------------------------------
# What ComfyUI has
# ---------------------------------------------------------------------------

@dataclass
class Loaded:
    """The node types available, and the ``custom_nodes/`` folders that loaded (lower case)."""

    types: set[str]
    folders: set[str] | None  # None: unknown (static scan)
    source: str  # "object_info" | "static"


def loaded_from_object_info(object_info: dict) -> Loaded:
    """From ComfyUI's ``/object_info``: every type, and each loaded folder by ``python_module``."""
    types: set[str] = set()
    folders: set[str] = set()
    for ntype, definition in (object_info.items() if isinstance(object_info, dict) else ()):
        if not isinstance(ntype, str):
            continue
        types.add(ntype)
        module = definition.get("python_module") if isinstance(definition, dict) else None
        if isinstance(module, str) and module.startswith("custom_nodes."):
            folders.add(module[len("custom_nodes."):].lower())
    return Loaded(types, folders, "object_info")


def loaded_from_scan(types: set[str]) -> Loaded:
    """From the static scan of ComfyUI's and ``custom_nodes/``'s sources."""
    return Loaded(set(types), None, "static")


@dataclass
class Folder:
    """A pack folder in ``custom_nodes/``."""

    name: str
    origin: str = ""  # its git origin URL, "" when not a clone (or unreadable)
    declared: set[str] = field(default_factory=set)  # types its sources declare (static scan)

    @property
    def identity(self) -> str:
        return repo_identity(self.origin) if self.origin else ""


# ---------------------------------------------------------------------------
# The resolution
# ---------------------------------------------------------------------------

@dataclass
class Resolution:
    packs: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)
    core: list[str] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    frontend: list[str] = field(default_factory=list)  # pack-provided frontend types, satisfied
    ground_truth: str = "static"

    def is_empty(self) -> bool:
        return not (self.packs or self.ambiguous or self.core or self.blocked or self.unknown)

    def as_dict(self) -> dict:
        return {
            "ground_truth": self.ground_truth,
            "packs": self.packs,
            "ambiguous": self.ambiguous,
            "core": self.core,
            "blocked": self.blocked,
            "unknown": self.unknown,
            "frontend": self.frontend,
        }


def _aux_repo(aux_id: str) -> str:
    return f"https://github.com/{aux_id}" if _AUX_ID.match(aux_id or "") else ""


def resolve(wanted: dict[str, WantedNode], loaded: Loaded, db, folders: list[Folder],
            tracked: set[str] = frozenset(), registry=None) -> Resolution:
    """Classify each wanted type *loaded* lacks (see the module docstring).

    *db* is a :class:`deployer.core.node_db.NodeDb` (or ``None``: then only
    the workflow's ``aux_id`` and the registry can name a pack); *tracked* the
    identities (:func:`repo_identity`) of the tracked list; *registry(cnr_id)* the Comfy registry's
    repository URL or ``None`` (``None``: not asked).
    """
    result = Resolution(ground_truth=loaded.source)
    tracked = set(tracked)
    by_identity = {f.identity: f for f in folders if f.identity}
    by_name = {f.name.lower(): f for f in folders}
    packs: dict[str, dict] = {}
    ambiguous: dict[tuple[str, ...], list[str]] = {}

    def info(identity: str) -> dict:
        return (db.info(identity) if db is not None else None) or {}

    def folder_of(identity: str, repo: str) -> Folder | None:
        return by_identity.get(identity) or by_name.get(repo_folder_name(repo).lower())

    def on_disk(identity: str) -> bool:
        folder = folder_of(identity, info(identity).get("repo") or identity)
        return folder is not None and folder.identity in ("", identity)

    def pick(url: str, source: str) -> tuple[str, str, str]:
        """(identity, clone URL, source) of *url* — the DB's clone URL when it knows the repository."""
        repo = info(repo_identity(url)).get("repo") or url
        return repo_identity(repo), repo, source

    def choose(want: WantedNode) -> tuple[str, str, str] | str:
        """(identity, clone URL, source), or the outcome "core" / "unknown" / "ambiguous:…"."""
        aux = _aux_repo(want.aux_id)
        if aux:
            return pick(aux, "workflow")
        candidates = db.candidates(want.type) if db is not None else []
        if want.cnr_id and want.cnr_id.lower() != _CORE_CNR:
            named = db.by_registry_id(want.cnr_id) if db is not None else []
            narrowed = [c for c in named if c in candidates] or named
            if len(narrowed) == 1:
                return pick(info(narrowed[0]).get("repo") or narrowed[0], "workflow")
            url = registry(want.cnr_id) if registry is not None else None
            if url:
                return pick(url, "registry")
        if want.cnr_id.lower() == _CORE_CNR or (db is not None and want.type in db.core_types):
            return "core"
        if not candidates and want.type in FRONTEND_PACK_TYPES:
            return pick(FRONTEND_PACK_TYPES[want.type], "builtin")
        if len(candidates) == 1:
            return pick(info(candidates[0]).get("repo") or candidates[0], "db")
        if candidates:
            known = [c for c in candidates if c in tracked or on_disk(c)]
            if len(known) == 1:
                return pick(info(known[0]).get("repo") or known[0], "db")
            return "ambiguous:" + "\n".join(sorted(candidates))
        return "unknown"

    for ntype in sorted(wanted):
        want = wanted[ntype]
        if ntype in loaded.types:
            continue
        choice = choose(want)
        if choice == "core":
            result.core.append(ntype)
            continue
        if choice == "unknown":
            result.unknown.append(ntype)
            continue
        if isinstance(choice, str):  # ambiguous
            key = tuple(choice.split(":", 1)[1].split("\n"))
            ambiguous.setdefault(key, []).append(ntype)
            continue

        identity, repo, source = choice
        details = info(identity)
        if details and not details.get("installable", True):
            result.blocked.append({"repo": repo, "folder": "", "origin": "",
                                   "reason": "not a git repository", "types": [ntype]})
            continue
        folder = folder_of(identity, repo)
        if folder is not None and folder.identity and folder.identity != identity:
            result.blocked.append({"repo": repo, "folder": folder.name, "origin": folder.origin,
                                   "reason": "the folder holds another repository", "types": [ntype]})
            continue

        # A pack's frontend-only type (in no /object_info, even installed): a known one, or a
        # name only the pack's nodename_pattern claims (rgthree's "… (rgthree)" panels).
        frontend_only = ntype in FRONTEND_PACK_TYPES or (
            source == "db" and db is not None and not db.declares(identity, ntype))
        loads = folder is not None and (loaded.folders is None or folder.name.lower() in loaded.folders)
        if folder is None:
            action = "install"
        elif frontend_only and loads:
            result.frontend.append(ntype)
            continue
        elif loaded.folders is not None:
            # Loaded, yet the type is missing: it came in a later version. Not loaded at all:
            # its import failed.
            action = "update" if loads else "repair"
        else:
            action = "repair" if ntype in folder.declared else "update"

        pack = packs.get(identity)
        if pack is None:
            pack = packs[identity] = {
                "repo": repo,
                "identity": identity,
                "folder": folder.name if folder else repo_folder_name(repo),
                "action": action,
                "types": [],
                "source": source,
                "tracked": identity in tracked,
                "title": details.get("title", ""),
                "description": details.get("description", ""),
                "versions": [],
            }
        pack["types"].append(ntype)
        for ver in want.versions:
            if ver not in pack["versions"]:
                pack["versions"].append(ver)

    result.packs = sorted(packs.values(), key=lambda p: p["folder"].lower())
    for options, types in sorted(ambiguous.items()):
        result.ambiguous.append({
            "types": sorted(types),
            "options": [{
                "repo": info(o).get("repo") or o,
                "identity": o,
                "title": info(o).get("title", ""),
                "description": info(o).get("description", ""),
                "tracked": o in tracked,
                "installed": on_disk(o),
            } for o in options],
        })
    return result

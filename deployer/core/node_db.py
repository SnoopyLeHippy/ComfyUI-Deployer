"""The public custom-node databases, cached: which repository provides a node type.

Two sources, both read-only lookups (nothing here installs anything):

* **ComfyUI-Manager's DB** — ``extension-node-map.json`` (``{repo: [[types], {meta}]}``)
  and ``custom-node-list.json`` (``{"custom_nodes": [{reference, files, id?,
  install_type, title, description}]}``). Downloaded into ``CACHE_DIR`` and
  reused while younger than ``max_age`` (a day by default): a run's
  resolution must not wait on GitHub every time. A failed refresh falls back
  on the cached copy, however old; no copy at all is an error.
* **The Comfy registry** (``api.comfy.org/nodes/<id>``) — the repository of a
  registry id, the ``cnr_id`` a workflow's node carries. Answers (a found
  repository, or "no such id") are cached in ``registry.json``; a network
  failure is not cached and answers ``None``.

:class:`NodeDb` indexes the Manager DB once. The entries it trusts for a
clone are ``git-clone`` ones, cloned from ``files[0]`` — 47 entries have a
``reference`` that differs (a typo, a raw ``.py`` file), and the
``copy`` / ``unzip`` ones (a gist, a zip) are never installable by git.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse

from deployer.core.node import repo_folder_name, repo_identity

EXTENSION_NODE_MAP = "extension-node-map.json"
CUSTOM_NODE_LIST = "custom-node-list.json"
REGISTRY_CACHE = "registry.json"
REGISTRY_URL = "https://api.comfy.org/nodes/{id}"

#: How long a downloaded DB is used before a refresh is attempted.
DEFAULT_MAX_AGE = 24 * 3600

#: The repositories the Manager DB lists ComfyUI's own nodes under.
CORE_REPOS = {"github.com/comfyanonymous/comfyui", "github.com/comfy-org/comfyui"}

_REGISTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class NodeDbUnavailable(RuntimeError):
    """Neither a download nor a cached copy of the DB."""


# ---------------------------------------------------------------------------
# Downloads, with a cache
# ---------------------------------------------------------------------------

def _download(url: str, dest: str, timeout: int) -> None:
    """Download into *dest* atomically (a cut download never replaces a good copy)."""
    from deployer.core.http import download_file

    tmp = dest + ".part"
    try:
        download_file(url, tmp, timeout=timeout)
        with open(tmp, "r", encoding="utf-8") as fh:
            json.load(fh)  # an HTML error page must not become the cache
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def cached_json(name: str, url: str, *, cache_dir: str, max_age: float = DEFAULT_MAX_AGE,
                refresh: bool = False, timeout: int = 30, now=time.time) -> dict:
    """The JSON at *url*, from ``cache_dir/name`` while it is younger than *max_age*.

    *refresh* forces a download. A failed download keeps the cached copy
    (printing why); without one, :class:`NodeDbUnavailable`.
    """
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, name)
    fresh = os.path.isfile(path) and now() - os.path.getmtime(path) < max_age
    if refresh or not fresh:
        try:
            _download(url, path, timeout)
        except Exception as exc:  # noqa: BLE001 - any failure falls back on the cache
            if not os.path.isfile(path):
                raise NodeDbUnavailable(f"cannot download {url} and no cached copy: {exc}") from exc
            print(f"Warning: could not refresh {name} ({exc}); using the cached copy")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise NodeDbUnavailable(f"the cached {name} cannot be read: {exc}") from exc


def load_node_db(*, cache_dir: str | None = None, max_age: float = DEFAULT_MAX_AGE,
                 refresh: bool = False) -> "NodeDb":
    """The Manager DB, indexed (see :func:`cached_json`)."""
    from deployer.config import CUSTOM_NODE_LIST_URL, EXTENSION_NODE_MAP_URL

    if cache_dir is None:
        from deployer.config import CACHE_DIR as cache_dir
    extension_map = cached_json(EXTENSION_NODE_MAP, EXTENSION_NODE_MAP_URL, cache_dir=cache_dir,
                                max_age=max_age, refresh=refresh)
    node_list = cached_json(CUSTOM_NODE_LIST, CUSTOM_NODE_LIST_URL, cache_dir=cache_dir,
                            max_age=max_age, refresh=refresh)
    return NodeDb(extension_map, node_list)


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------

class NodeDb:
    """Indexes over the Manager DB; built from the two parsed files."""

    def __init__(self, extension_map: dict, node_list: dict) -> None:
        #: identity → {"repo" (clone URL), "title", "description", "id", "installable"}
        self.repos: dict[str, dict] = {}
        #: node type → [identity, ...] (custom repositories only, DB order)
        self.type_repos: dict[str, list[str]] = {}
        #: node types the DB lists under ComfyUI's own repository
        self.core_types: set[str] = set()
        #: (compiled nodename_pattern, identity)
        self.patterns: list[tuple[re.Pattern[str], str]] = []
        #: Manager id → identity
        self._by_manager_id: dict[str, str] = {}

        entries = node_list.get("custom_nodes") if isinstance(node_list, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            files = [f for f in entry.get("files") or [] if isinstance(f, str) and f.strip()]
            if not files:
                continue
            installable = entry.get("install_type", "git-clone") == "git-clone"
            info = {
                "repo": files[0].strip(),
                "title": entry.get("title") or "",
                "description": entry.get("description") or "",
                "id": entry.get("id") or "",
                "installable": installable,
            }
            identity = repo_identity(info["repo"])
            self.repos.setdefault(identity, info)
            reference = entry.get("reference")
            if isinstance(reference, str) and reference.strip():
                # Map keys may be the reference: alias it to the same clone URL.
                self.repos.setdefault(repo_identity(reference), info)
            if isinstance(info["id"], str) and info["id"] and installable:
                self._by_manager_id.setdefault(info["id"].lower(), identity)

        for repo, value in (extension_map.items() if isinstance(extension_map, dict) else ()):
            if not isinstance(repo, str) or not isinstance(value, list) or not value:
                continue
            identity = repo_identity(repo)
            types = [t for t in value[0] if isinstance(t, str)] if isinstance(value[0], list) else []
            if identity in CORE_REPOS:
                self.core_types.update(types)
                continue
            if identity not in self.repos:
                # In the map but not the list: a plain git repository, no description.
                self.repos[identity] = {"repo": repo, "title": "", "description": "", "id": "",
                                        "installable": repo.startswith(("https://", "http://", "git@"))
                                        and not repo.endswith(".py")}
            # Everything is keyed by the repository actually cloned (a map key may be the
            # list entry's `reference`, not its `files[0]`): that is what a clone's origin says.
            identity = repo_identity(self.repos[identity]["repo"])
            self.repos.setdefault(identity, self.repos[repo_identity(repo)])
            for ntype in types:
                self.type_repos.setdefault(ntype, []).append(identity)
            meta = value[1] if len(value) > 1 and isinstance(value[1], dict) else {}
            pattern = meta.get("nodename_pattern")
            if isinstance(pattern, str) and pattern:
                try:
                    self.patterns.append((re.compile(pattern), identity))
                except re.error:
                    pass

    def candidates(self, ntype: str) -> list[str]:
        """Identities of the repositories declaring *ntype*, then those whose pattern matches it."""
        found = list(self.type_repos.get(ntype, []))
        for pattern, identity in self.patterns:
            if identity not in found and pattern.search(ntype):
                found.append(identity)
        return found

    def declares(self, identity: str, ntype: str) -> bool:
        """True when the DB lists *ntype* among *identity*'s node types (not a pattern)."""
        return identity in self.type_repos.get(ntype, [])

    def by_registry_id(self, cnr_id: str) -> list[str]:
        """Repositories a registry id may name: the Manager id, else the folder name, matched."""
        key = cnr_id.strip().lower()
        if not key:
            return []
        if key in self._by_manager_id:
            return [self._by_manager_id[key]]
        found: list[str] = []
        for info in self.repos.values():
            if info["installable"] and repo_folder_name(info["repo"]).lower() == key:
                identity = repo_identity(info["repo"])  # aliases share one clone URL
                if identity not in found:
                    found.append(identity)
        return found

    def info(self, identity: str) -> dict | None:
        return self.repos.get(identity)


# ---------------------------------------------------------------------------
# The Comfy registry
# ---------------------------------------------------------------------------

def _read_registry_cache(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def registry_repository(cnr_id: str, *, cache_dir: str | None = None, timeout: int = 15,
                        fetch=None) -> str | None:
    """The repository the Comfy registry gives for *cnr_id*, or ``None``.

    ``None`` both for an unknown id (cached) and for a network failure (not
    cached, asked again next time). *fetch(url)* returns the parsed JSON body
    or raises — injectable for tests.
    """
    if not isinstance(cnr_id, str) or not _REGISTRY_ID.match(cnr_id.strip()):
        return None
    cnr_id = cnr_id.strip().lower()
    if cache_dir is None:
        from deployer.config import CACHE_DIR as cache_dir
    path = os.path.join(cache_dir, REGISTRY_CACHE)
    cache = _read_registry_cache(path)
    if cnr_id in cache:
        return cache[cnr_id] or None

    url = REGISTRY_URL.format(id=urllib.parse.quote(cnr_id, safe=""))
    try:
        body = (fetch or _fetch_json)(url, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            print(f"Warning: the Comfy registry answered HTTP {exc.code} for {cnr_id}")
            return None
        body = None
    except Exception as exc:  # noqa: BLE001 - offline: unknown, not cached
        print(f"Warning: the Comfy registry cannot be reached ({exc})")
        return None
    repo = body.get("repository") if isinstance(body, dict) else None
    repo = repo.strip() if isinstance(repo, str) and repo.strip().startswith("https://") else ""
    cache[cnr_id] = repo
    try:
        os.makedirs(cache_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"Warning: could not cache the registry answer ({exc})")
    return repo or None


def _fetch_json(url: str, timeout: int):
    import ssl
    import urllib.request

    from deployer.core.http import _contexts

    last: Exception | None = None
    for context in _contexts():
        request = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Deployer"})
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ssl.SSLError, OSError) as exc:
            last = exc
    raise last if last else OSError("no TLS context")

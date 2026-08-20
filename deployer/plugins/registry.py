"""Discovery and storage of plugins.

A single process-wide :class:`PluginRegistry` holds everything plugins
contribute: :class:`~deployer.plugins.api.BundleStep` objects (bundle
lifecycle) and :class:`~deployer.plugins.actions.UiAction` objects (main-window
buttons and menu entries). :func:`load_plugins` discovers plugin modules on
disk and lets each register its contributions via a module-level
``register(registry)`` entry point (or, as a fallback, by auto-registering any
``BundleStep`` / ``UiAction`` subclass the module defines).

Plugins are looked up in three locations, in order:

* ``deployer/plugins/builtin/`` — steps shipped with the deployer.
* ``<PROJECT_ROOT>/plugins/`` — drop-in local user plugins (gitignored), including
  top-level ``.py`` files and any subdirectory packages.
* ``<PROJECT_ROOT>/plugins/remote/<name>/`` — remote plugin repos cloned by
  :func:`sync_remote_plugins`. Each subdirectory is scanned for top-level
  ``.py`` files the same way as a local plugin directory.

Use :func:`sync_remote_plugins` to clone or update remote repos before calling
:func:`load_plugins` (or pass ``force=True`` to reload after a sync).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from typing import Callable

from deployer.config import PROJECT_ROOT
from deployer.plugins.actions import UiAction
from deployer.plugins.api import BundleStep


class PluginRegistry:
    """In-memory collection of what plugins contribute, keyed by ``id``.

    Two independent collections: **bundle steps** (work inserted into the
    bundle lifecycle) and **UI actions** (buttons / menu entries added to the
    main window). A plugin may contribute either or both.
    """

    def __init__(self) -> None:
        self._steps: dict[str, BundleStep] = {}
        self._actions: dict[str, UiAction] = {}

    def register(self, step: BundleStep) -> None:
        """Add *step*. A later registration with the same id replaces it."""
        if not getattr(step, "id", ""):
            raise ValueError(f"BundleStep {step!r} has no 'id'; cannot register.")
        self._steps[step.id] = step

    def get(self, step_id: str) -> BundleStep | None:
        return self._steps.get(step_id)

    def all(self) -> list[BundleStep]:
        """Return registered steps sorted by display name."""
        return sorted(self._steps.values(), key=lambda s: (s.name or s.id).lower())

    # -- UI actions --------------------------------------------------------

    def register_action(self, action: UiAction) -> None:
        """Add *action*. A later registration with the same id replaces it."""
        if not getattr(action, "id", ""):
            raise ValueError(f"UiAction {action!r} has no 'id'; cannot register.")
        self._actions[action.id] = action

    def get_action(self, action_id: str) -> UiAction | None:
        return self._actions.get(action_id)

    def actions(self) -> list[UiAction]:
        """Return registered UI actions sorted by ``order`` then label."""
        return sorted(
            self._actions.values(),
            key=lambda a: (a.order, (a.label or a.id).lower()),
        )

    def clear(self) -> None:
        self._steps.clear()
        self._actions.clear()


#: Process-wide registry shared by the dialog, builder, and headless install.
registry = PluginRegistry()

# Default discovery locations.
_BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin")
_USER_DIR = os.path.join(PROJECT_ROOT, "plugins")
_REMOTE_DIR = os.path.join(_USER_DIR, "remote")

_loaded = False


def _import_plugin_file(path: str) -> object | None:
    """Import a single plugin ``.py`` *path* under a unique module name."""
    mod_name = "deployer_plugin_" + str(abs(hash(os.path.normcase(path))))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses / relative lookups behave.
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _register_from_module(module: object) -> None:
    """Let *module* contribute its steps and UI actions.

    Prefers an explicit ``register(registry)`` entry point; otherwise
    auto-registers any concrete ``BundleStep`` / ``UiAction`` subclass defined
    in the module (identified by carrying a non-empty ``id``).
    """
    entry = getattr(module, "register", None)
    if callable(entry):
        entry(registry)
        return

    for value in vars(module).values():
        if not (isinstance(value, type) and getattr(value, "id", "")):
            continue
        if issubclass(value, BundleStep) and value is not BundleStep:
            registry.register(value())
        elif issubclass(value, UiAction) and value is not UiAction:
            registry.register_action(value())


def _discover_dir(directory: str) -> None:
    """Import and register every ``*.py`` plugin in *directory* (non-recursive)."""
    if not os.path.isdir(directory):
        return
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        path = os.path.join(directory, name)
        try:
            module = _import_plugin_file(path)
            if module is not None:
                _register_from_module(module)
        except Exception:  # noqa: BLE001 — a bad plugin must not break the app.
            print(f"Failed to load plugin '{path}':\n{traceback.format_exc()}")


def repo_dir_name(repo: str) -> str:
    """Return the folder name for a remote plugin repo URL (same logic as custom nodes)."""
    return os.path.basename(repo.rstrip("/").removesuffix(".git"))


def sync_remote_plugins(
    repos: list[dict],
    *,
    log: Callable[[str], None] = print,
) -> dict[str, str]:
    """Clone any remote plugin repos that are not yet present on disk.

    *repos* is a list of ``{"repo": <url>, "ref": <branch/tag>}`` dicts as
    stored in ``user_settings.json["plugins"]["remote"]``.

    Each repo is cloned into ``plugins/remote/<name>/`` (relative to the
    project root). Already-present directories are skipped (no pull — the user
    controls updates via the management dialog). Returns a status dict
    ``{name: "ok" | "skipped" | "error: <msg>"}``.

    This function imports ``git_ops`` lazily to avoid pulling the subprocess
    import on the cold path where no remote plugins exist.
    """
    from deployer.core import git_ops  # lazy — not needed when repos is empty

    statuses: dict[str, str] = {}
    if not repos:
        return statuses

    os.makedirs(_REMOTE_DIR, exist_ok=True)

    for entry in repos:
        repo = (entry or {}).get("repo", "").strip()
        ref = (entry or {}).get("ref", "main").strip() or "main"
        if not repo:
            continue
        name = repo_dir_name(repo)
        if not name:
            continue
        dest = os.path.join(_REMOTE_DIR, name)
        if os.path.isdir(dest):
            statuses[name] = "skipped"
            continue
        log(f"Cloning remote plugin '{name}' from {repo}...")
        try:
            git_ops.clone(repo, dest, cwd=_REMOTE_DIR, recursive=False)
            if ref and ref not in ("main", "HEAD"):
                git_ops.checkout(ref, cwd=dest, check=False)
            statuses[name] = "ok"
            log(f"  Plugin '{name}' installed.")
        except Exception as exc:  # noqa: BLE001
            statuses[name] = f"error: {exc}"
            log(f"  Failed to clone plugin '{name}': {exc}")

    return statuses


def load_plugins(force: bool = False) -> PluginRegistry:
    """Discover and register all plugins. Idempotent unless *force* is set.

    Scans three locations:
    1. ``deployer/plugins/builtin/`` (built-in steps)
    2. ``plugins/`` at the project root (local user plugins)
    3. ``plugins/remote/*/`` (remote repos cloned by :func:`sync_remote_plugins`)

    Call :func:`sync_remote_plugins` first to ensure remote repos are present,
    then call this with ``force=True`` to reload after a sync.
    """
    global _loaded
    if _loaded and not force:
        return registry
    if force:
        registry.clear()
    _discover_dir(_BUILTIN_DIR)
    _discover_dir(_USER_DIR)
    # Each subdirectory of plugins/ (excluding remote/) is a local plugin package.
    if os.path.isdir(_USER_DIR):
        for name in sorted(os.listdir(_USER_DIR)):
            subdir = os.path.join(_USER_DIR, name)
            if os.path.isdir(subdir) and subdir != _REMOTE_DIR:
                _discover_dir(subdir)
    # Scan .py files placed directly in plugins/remote/ (not inside a repo subdir).
    _discover_dir(_REMOTE_DIR)
    # Each subdirectory of plugins/remote/ is itself a plugin repo — scan it.
    if os.path.isdir(_REMOTE_DIR):
        for name in sorted(os.listdir(_REMOTE_DIR)):
            subdir = os.path.join(_REMOTE_DIR, name)
            if os.path.isdir(subdir):
                _discover_dir(subdir)
    _loaded = True
    return registry

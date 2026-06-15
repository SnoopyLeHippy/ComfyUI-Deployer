"""Discovery and storage of bundle-step plugins.

A single process-wide :class:`PluginRegistry` holds every registered
:class:`~deployer.plugins.api.BundleStep`. :func:`load_plugins` discovers
plugin modules on disk and lets each register its steps via a module-level
``register(registry)`` entry point (or, as a fallback, by auto-registering any
``BundleStep`` subclass the module defines).

Plugins are looked up in two locations:

* ``deployer/plugins/builtin/`` — steps shipped with the deployer.
* ``<PROJECT_ROOT>/plugins/`` — drop-in user plugins. These are picked up in a
  bundle too, since the bundled deployer is a clone of the repo: commit a
  plugin here and it ships with every bundle and runs at install time.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback

from deployer.config import PROJECT_ROOT
from deployer.plugins.api import BundleStep


class PluginRegistry:
    """In-memory collection of registered bundle steps, keyed by ``id``."""

    def __init__(self) -> None:
        self._steps: dict[str, BundleStep] = {}

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

    def clear(self) -> None:
        self._steps.clear()


#: Process-wide registry shared by the dialog, builder, and headless install.
registry = PluginRegistry()

# Default discovery locations.
_BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin")
_USER_DIR = os.path.join(PROJECT_ROOT, "plugins")

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
    """Let *module* contribute its steps.

    Prefers an explicit ``register(registry)`` entry point; otherwise
    auto-registers any concrete ``BundleStep`` subclass defined in the module.
    """
    entry = getattr(module, "register", None)
    if callable(entry):
        entry(registry)
        return

    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, BundleStep)
            and value is not BundleStep
            and getattr(value, "id", "")
        ):
            registry.register(value())


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


def load_plugins(force: bool = False) -> PluginRegistry:
    """Discover and register all plugins. Idempotent unless *force* is set."""
    global _loaded
    if _loaded and not force:
        return registry
    if force:
        registry.clear()
    _discover_dir(_BUILTIN_DIR)
    _discover_dir(_USER_DIR)
    _loaded = True
    return registry

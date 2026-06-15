"""Public contract for ComfyUI Deployer bundle-step plugins.

A *plugin* contributes one or more **bundle steps**: a unit of work the bundle
author can add to a bundle and that runs at a well-defined point of the bundle
lifecycle. Two phases exist:

* :attr:`StepPhase.CREATE` — runs on the **author's** machine while a folder
  bundle is being built (e.g. copy some models into the bundle now).
* :attr:`StepPhase.INSTALL` — runs on the **recipient's** machine when a
  sharable ``.bat`` installs the bundle, or when the bundled deployer replays
  the install (e.g. copy models from a path that exists on the target PC).

A step declares which phase(s) it supports via :attr:`BundleStep.phases`; the
runner only invokes a step for a phase it opted into.

This module is intentionally **free of any PyQt import** so it can be loaded by
the headless install path (which may run before PyQt is available). Concrete
plugins that build a configuration widget must import PyQt *lazily* inside
:meth:`BundleStep.build_widget`, never at module top level.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable


class StepPhase(enum.Flag):
    """When a bundle step runs.

    ``CREATE`` and ``INSTALL`` can be combined (``CREATE | INSTALL``, aliased
    as :attr:`BOTH`) for steps that are meaningful in both contexts.
    """

    CREATE = enum.auto()
    INSTALL = enum.auto()
    BOTH = CREATE | INSTALL


@dataclass
class StepContext:
    """Runtime paths and helpers handed to :meth:`BundleStep.run`.

    The paths always point at the ComfyUI tree the step should act on: the
    freshly built bundle during :attr:`StepPhase.CREATE`, or the recipient's
    live install during :attr:`StepPhase.INSTALL`.
    """

    bundle_root: str
    comfyui_dir: str
    models_dir: str
    custom_nodes_dir: str
    input_dir: str
    output_dir: str
    phase: StepPhase
    workflow_paths: list[str] = field(default_factory=list)
    log: Callable[[str], None] = print


class BundleStep:
    """Base class for a bundle-step plugin.

    Subclass this, set the class attributes, implement :meth:`run`, and (when
    the step needs per-bundle configuration) the widget hooks. Register the
    instance from your plugin module's ``register(registry)`` entry point::

        from deployer.plugins import BundleStep, StepPhase

        class MyStep(BundleStep):
            id = "my_step"
            name = "My step"
            description = "What it does, shown in the Add-step menu."
            phases = StepPhase.INSTALL

            def run(self, ctx, config):
                ...

        def register(registry):
            registry.register(MyStep())

    The ``id`` must be globally unique and stable: it is what gets persisted in
    the bundle's ``user_settings.json`` and looked up at install time.
    """

    #: Unique, stable identifier persisted in the bundle. Required.
    id: str = ""
    #: Human label shown in the Add-step menu and step header.
    name: str = ""
    #: One-line description shown as a tooltip / subtitle.
    description: str = ""
    #: Phase(s) the step opts into.
    phases: StepPhase = StepPhase.INSTALL

    # -- Configuration UI (optional) ---------------------------------------
    # These run only inside the Create Bundle dialog, where PyQt is loaded.
    # Import PyQt lazily *inside* build_widget so this plugin module stays
    # importable on the headless install path.

    def build_widget(self, parent: Any = None) -> Any:
        """Return a ``QWidget`` editing this step's config, or ``None``.

        Return ``None`` for a step that takes no configuration.
        """
        return None

    def read_config(self, widget: Any) -> dict:
        """Read the current configuration out of the widget built above."""
        return {}

    def load_config(self, widget: Any, config: dict) -> None:
        """Populate *widget* from a previously saved *config* (optional)."""

    # -- Validation & execution --------------------------------------------
    def validate(self, config: dict) -> str | None:
        """Return an error message if *config* is invalid, else ``None``.

        Called in the dialog before the bundle is created and again before the
        step runs. An empty/valid config should return ``None``.
        """
        return None

    def run(self, ctx: StepContext, config: dict) -> None:
        """Perform the step against *ctx* using *config*.

        Raising is caught by the runner and reported; it does not abort the
        other steps.
        """
        raise NotImplementedError(
            f"BundleStep '{self.id or type(self).__name__}' does not implement run()."
        )

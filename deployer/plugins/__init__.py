"""Plugin system: bundle install steps and main-window UI actions.

Public API for plugin authors and for the deployer internals:

* :class:`BundleStep`, :class:`StepContext`, :class:`StepPhase` — the bundle
  lifecycle contract.
* :class:`UiAction`, :class:`CommandAction`, :class:`ActionContext`,
  :class:`ActionLocation`, :class:`ActionStyle` — the main-window contract
  (buttons / menu entries running custom commands).
* :data:`registry` / :func:`load_plugins` — discovery and lookup.
* :func:`run_steps` — execution.

See :mod:`deployer.plugins.api` for how to write a bundle step,
:mod:`deployer.plugins.actions` for how to write a UI action, and
``deployer/plugins/examples/`` for worked references.
"""

from deployer.plugins.actions import (  # noqa: F401
    ActionContext,
    ActionLocation,
    ActionStyle,
    CommandAction,
    UiAction,
)
from deployer.plugins.api import BundleFormat, BundleStep, StepContext, StepPhase  # noqa: F401
from deployer.plugins.registry import (  # noqa: F401
    PluginRegistry,
    load_plugins,
    registry,
    repo_dir_name,
    sync_remote_plugins,
)
from deployer.plugins.runner import run_steps  # noqa: F401

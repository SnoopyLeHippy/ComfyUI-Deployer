"""Plugin system for bundle install steps.

Public API for plugin authors and for the deployer internals:

* :class:`BundleStep`, :class:`StepContext`, :class:`StepPhase` — the contract.
* :data:`registry` / :func:`load_plugins` — discovery and lookup.
* :func:`run_steps` — execution.

See :mod:`deployer.plugins.api` for how to write a plugin, and
``deployer/plugins/examples/`` for a worked reference.
"""

from deployer.plugins.api import BundleFormat, BundleStep, StepContext, StepPhase  # noqa: F401
from deployer.plugins.registry import (  # noqa: F401
    PluginRegistry,
    load_plugins,
    registry,
    repo_dir_name,
    sync_remote_plugins,
)
from deployer.plugins.runner import run_steps  # noqa: F401

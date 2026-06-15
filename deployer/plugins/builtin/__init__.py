"""Built-in bundle-step plugins shipped with the deployer.

Drop a ``*.py`` module here that exposes a ``register(registry)`` entry point
(or defines ``BundleStep`` subclasses) and it is auto-discovered by
:func:`deployer.plugins.load_plugins`. This package ships empty by design —
the deployer provides the plugin *infrastructure*, not opinionated steps.
"""

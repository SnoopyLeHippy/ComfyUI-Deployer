"""Non-Qt orchestration helpers used by the main window.

Splitting the bulky :class:`CustomNodeDeployerApp` into thin controllers keeps
``app.py`` focused on UI wiring (signals, layout, lifecycle) and makes the
underlying business logic testable without spinning up a ``QApplication``.
"""

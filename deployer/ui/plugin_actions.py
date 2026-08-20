"""Renders the :class:`~deployer.plugins.actions.UiAction` objects plugins contribute.

The main window owns one :class:`PluginActionBar`. It turns whatever is in the
plugin registry into real widgets — a button in the bottom action row, or an
entry appended to the hamburger menu — and owns their whole lifecycle: click
handling (optional confirmation, execution on a worker thread, error reporting
to the console) and enabled state (an action already running, or blocked by the
window's busy state, is greyed out).

This is the *only* place that knows both the plugin action contract and Qt:
``deployer/plugins/actions.py`` stays Qt-free so plugin modules remain
importable on the headless install path.
"""

from __future__ import annotations

import sys
import threading
import traceback
from typing import Callable

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QMessageBox, QPushButton, QWidget

from deployer.config import (
    COMFYUI_DIR,
    CUSTOM_NODES_DIR,
    INPUT_DIR,
    MODELS_DIR,
    OUTPUT_DIR,
    PORTABLE_DIR,
    PROJECT_ROOT,
    PYTHON_EXE,
)
from deployer.plugins import ActionContext, ActionLocation, ActionStyle, UiAction, registry
from deployer.ui import theme


#: Semantic style -> concrete stylesheet. Keeps colours in the theme package.
_BUTTON_STYLES = {
    ActionStyle.NEUTRAL: theme.PLUGIN_ACTION_BUTTON_STYLE,
    ActionStyle.PRIMARY: theme.INSTALL_BUTTON_ACTIVE_STYLE,
    ActionStyle.SUCCESS: theme.RUN_COMFY_BUTTON_STYLE,
    ActionStyle.WARNING: theme.PLUGIN_ACTION_WARNING_BUTTON_STYLE,
    ActionStyle.DANGER: theme.STOP_COMFY_BUTTON_STYLE,
}


class PluginActionBar:
    """Builds, owns and runs the widgets contributed by plugin UI actions.

    Args:
        window:         The main window (parents dialogs, passed to actions).
        button_layout:  The bottom action row's ``QHBoxLayout``; a container
                        holding the plugin buttons is inserted at *insert_index*.
        menu:           The hamburger ``QMenu``; ``MENU`` actions are appended.
        run_on_ui:      Schedules a callable on the UI thread (the window's
                        ``_ui_call.emit``). Worker threads must not touch Qt.
        refresh_nodes:  Re-reads the node cards from disk; exposed to actions.
        insert_index:   Where the button container goes in *button_layout*.
    """

    def __init__(
        self,
        window: QWidget,
        button_layout: QHBoxLayout,
        menu: QMenu,
        *,
        run_on_ui: Callable[[Callable[[], None]], None],
        refresh_nodes: Callable[[], None],
        insert_index: int = 0,
    ) -> None:
        self._window = window
        self._menu = menu
        self._run_on_ui = run_on_ui
        self._refresh_nodes = refresh_nodes

        self._container = QWidget()
        self._container.setObjectName("transparentRow")
        self._row = QHBoxLayout(self._container)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(10)
        button_layout.insertWidget(insert_index, self._container)

        self._menu_separator: QAction | None = None
        self._menu_actions: list[QAction] = []
        self._widgets: dict[str, QWidget | QAction] = {}  # action id -> button or menu entry
        self._actions: dict[str, UiAction] = {}  # action id -> the action itself
        self._running: set[str] = set()
        self._busy = False

    # ------------------------------------------------------------------ Build

    def rebuild(self) -> None:
        """Discard the current widgets and rebuild them from the registry.

        Called at startup and again after a remote-plugin sync or a change in
        the Manage Plugins dialog, since either can add or remove actions.
        """
        self._clear()
        ctx = self._context()

        for action in registry.actions():
            try:
                if not action.is_available(ctx):
                    continue
            except Exception:  # noqa: BLE001 — a bad plugin must not break the window.
                print(f"Plugin action '{action.id}' is_available() failed:\n{traceback.format_exc()}")
                continue
            if action.location is ActionLocation.MENU:
                self._add_menu_action(action)
            else:
                self._add_button(action)

        self._container.setVisible(bool(self._row.count()))

    def _clear(self) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for qaction in self._menu_actions:
            self._menu.removeAction(qaction)
        self._menu_actions.clear()
        if self._menu_separator is not None:
            self._menu.removeAction(self._menu_separator)
            self._menu_separator = None
        self._widgets.clear()
        self._actions.clear()

    def _add_button(self, action: UiAction) -> None:
        button = QPushButton(action.label or action.id)
        button.setStyleSheet(_BUTTON_STYLES.get(action.style, theme.PLUGIN_ACTION_BUTTON_STYLE))
        button.setFixedHeight(40)
        button.setMinimumWidth(110)
        if action.description:
            button.setToolTip(action.description)
        button.clicked.connect(lambda _=False, a=action: self.trigger(a))
        self._row.addWidget(button)
        self._register_widget(action, button)

    def _add_menu_action(self, action: UiAction) -> None:
        if self._menu_separator is None:
            self._menu_separator = self._menu.addSeparator()
        qaction = QAction(action.label or action.id, self._window)
        if action.description:
            qaction.setStatusTip(action.description)
            qaction.setToolTip(action.description)
        qaction.triggered.connect(lambda _=False, a=action: self.trigger(a))
        self._menu.addAction(qaction)
        self._menu_actions.append(qaction)
        self._register_widget(action, qaction)

    def _register_widget(self, action: UiAction, widget: QWidget | QAction) -> None:
        self._widgets[action.id] = widget
        self._actions[action.id] = action
        self._apply_enabled(action.id)

    # ------------------------------------------------------------------ State

    def set_busy(self, busy: bool) -> None:
        """Follow the window's busy state (install / bundle / ComfyUI update).

        Only actions declaring ``blocked_when_busy`` (the default) are greyed
        out — one that opts out, typically because it just opens a folder or
        reads a file, stays clickable. An action currently running is always
        disabled, busy or not.
        """
        self._busy = busy
        for action_id in self._widgets:
            self._apply_enabled(action_id)

    def _apply_enabled(self, action_id: str) -> None:
        """Push the computed enabled state onto one action's widget."""
        widget = self._widgets.get(action_id)
        if widget is None:
            return
        action = self._actions.get(action_id)
        blocked = self._busy and (action is None or action.blocked_when_busy)
        widget.setEnabled(not blocked and action_id not in self._running)

    # ------------------------------------------------------------------ Run

    def trigger(self, action: UiAction) -> None:
        """Confirm if needed, then run *action* (on a worker thread by default)."""
        if action.confirm:
            answer = QMessageBox.question(
                self._window,
                action.label or action.id,
                action.confirm,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        print(f"Running action: {action.label or action.id}...")
        if not action.background:
            self._execute(action)
            return

        self._running.add(action.id)
        self._apply_enabled(action.id)
        threading.Thread(
            target=self._execute_bg, args=(action,), daemon=True,
        ).start()

    def _execute_bg(self, action: UiAction) -> None:
        try:
            self._execute(action)
        finally:
            self._run_on_ui(lambda a=action: self._on_finished(a))

    def _on_finished(self, action: UiAction) -> None:
        self._running.discard(action.id)
        self._apply_enabled(action.id)

    def _execute(self, action: UiAction) -> None:
        """Run the action, keeping a faulty plugin from taking the app down."""
        try:
            action.run(self._context())
        except Exception:  # noqa: BLE001
            # stderr so the traceback renders red in the console panel.
            print(
                f"Action '{action.label or action.id}' failed:\n{traceback.format_exc()}",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------ Context

    def _context(self) -> ActionContext:
        """Build the context handed to actions (paths + host callbacks)."""
        return ActionContext(
            project_root=PROJECT_ROOT,
            portable_dir=PORTABLE_DIR,
            comfyui_dir=COMFYUI_DIR,
            custom_nodes_dir=CUSTOM_NODES_DIR,
            models_dir=MODELS_DIR,
            input_dir=INPUT_DIR,
            output_dir=OUTPUT_DIR,
            python_exe=PYTHON_EXE,
            log=print,  # stdout is redirected to the console panel
            refresh_nodes=lambda: self._run_on_ui(self._refresh_nodes),
            window=self._window,
        )

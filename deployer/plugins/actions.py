"""Public contract for plugins that extend the deployer's **main window**.

Where :mod:`deployer.plugins.api` lets a plugin add work to the *bundle*
lifecycle, this module lets it add work to the *application*: a plugin
contributes one or more :class:`UiAction`, each rendered by the main window as
a button in the bottom action row or as an entry in the hamburger menu.
Clicking it runs the action's :meth:`UiAction.run` — typically an external
command against the local ComfyUI install.

The simplest case — a button that runs a command — needs no ``run()`` at all:
subclass :class:`CommandAction` and set ``command``::

    from deployer.plugins import CommandAction

    class OpenModelsFolder(CommandAction):
        id = "open_models_folder"
        label = "Models folder"
        description = "Open ComfyUI/models in Explorer."
        command = "explorer ."
        cwd_key = "models_dir"

    def register(registry):
        registry.register_action(OpenModelsFolder())

Like every other part of the plugin surface this module is **free of any PyQt
import**, so a plugin module defining actions stays importable on the headless
install path (which loads plugins without Qt). UI actions are simply ignored
there — the headless installer has no window.
"""

from __future__ import annotations

import enum
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Sequence


class ActionLocation(enum.Enum):
    """Where the main window renders an action.

    * ``TOOLBAR`` — a button in the bottom row, left of Update / Run Comfy.
    * ``MENU``    — an entry appended to the hamburger menu.
    """

    TOOLBAR = "toolbar"
    MENU = "menu"


class ActionStyle(enum.Enum):
    """Colour intent for a ``TOOLBAR`` action, resolved by the UI theme.

    Semantic rather than literal so plugins never hardcode a colour (the
    palette lives in ``deployer/ui/theme/``). Ignored for ``MENU`` actions.
    """

    NEUTRAL = "neutral"  # grey — the default
    PRIMARY = "primary"  # blue
    SUCCESS = "success"  # green
    WARNING = "warning"  # orange
    DANGER = "danger"    # red


@dataclass
class ActionContext:
    """Paths and helpers handed to :meth:`UiAction.run`.

    Every path points at the **local** install the deployer manages (not at a
    bundle under construction — that is what
    :class:`~deployer.plugins.api.StepContext` is for).

    Attributes:
        project_root:     Deployer root (holds ``user_settings.json``, ``plugins/``).
        portable_dir:     ``ComfyUI_windows_portable/``.
        comfyui_dir:      ``ComfyUI_windows_portable/ComfyUI/``.
        custom_nodes_dir: ``ComfyUI/custom_nodes/``.
        models_dir:       ``ComfyUI/models/`` (usually a junction to an external drive).
        input_dir:        ``ComfyUI/input/``.
        output_dir:       ``ComfyUI/output/``.
        python_exe:       The embedded interpreter ComfyUI itself runs on.
        log:              Emit one line to the console panel.
        refresh_nodes:    Ask the main window to re-read the node cards from
                          disk. Safe to call from the action's worker thread.
        window:           The main window, as an opaque object, to parent a Qt
                          dialog on. **Only touch it from an action declaring
                          ``background = False``** — Qt widgets must not be
                          created off the UI thread.
    """

    project_root: str
    portable_dir: str
    comfyui_dir: str
    custom_nodes_dir: str
    models_dir: str
    input_dir: str
    output_dir: str
    python_exe: str
    log: Callable[[str], None] = print
    refresh_nodes: Callable[[], None] = lambda: None
    window: Any = None

    def path(self, key: str) -> str:
        """Return the path attribute named *key*, or ``""`` when unknown.

        Lets a declarative action name its working directory
        (``cwd_key = "models_dir"``) instead of hardcoding an absolute path.
        """
        value = getattr(self, key, "")
        return value if isinstance(value, str) else ""

    def run_command(
        self,
        command: Sequence[str] | str,
        *,
        cwd: str | None = None,
        shell: bool | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
    ) -> int:
        """Run *command*, streaming its output to the console, return its exit code.

        A ``str`` command runs through the shell — so ``.bat`` files,
        ``explorer``, pipes and redirections all work; a list runs directly.
        Pass *shell* explicitly to override that default. *env* is merged over
        the current environment. With *check*, a non-zero exit raises
        ``subprocess.CalledProcessError``.
        """
        from deployer.core.command_runner import stream_command

        use_shell = isinstance(command, str) if shell is None else shell
        workdir = cwd or self.project_root
        returncode = stream_command(
            command,
            cwd=workdir if os.path.isdir(workdir) else None,
            shell=use_shell,
            env=env,
            log=self.log,
        )
        if check and returncode != 0:
            raise subprocess.CalledProcessError(returncode, command)
        return returncode


class UiAction:
    """Base class for a main-window action contributed by a plugin.

    Subclass, set the class attributes, implement :meth:`run`, and register the
    instance from the plugin's ``register(registry)`` entry point::

        def register(registry):
            registry.register_action(MyAction())

    ``id`` must be unique: registering a second action with the same id
    replaces the first.
    """

    #: Unique, stable identifier. Required.
    id: str = ""
    #: Text shown on the button / menu entry.
    label: str = ""
    #: Tooltip (button) or status tip (menu entry).
    description: str = ""
    #: Button in the action row, or entry in the hamburger menu.
    location: ActionLocation = ActionLocation.TOOLBAR
    #: Colour intent for a toolbar button.
    style: ActionStyle = ActionStyle.NEUTRAL
    #: Sort key among plugin actions (ties broken by label).
    order: int = 100
    #: Run :meth:`run` on a worker thread so the window stays responsive.
    #: Set ``False`` only for a short action that must touch Qt.
    background: bool = True
    #: When non-empty, shown in a Yes/No confirmation dialog before running.
    confirm: str = ""
    #: Grey the action out while the deployer is busy (installing, bundling,
    #: updating ComfyUI). Set ``False`` for an action that cannot interfere —
    #: opening a folder, tailing a log, showing a report. An action that
    #: touches ``custom_nodes/``, ``python_embeded/`` or the ComfyUI process
    #: must keep the default.
    blocked_when_busy: bool = True

    def is_available(self, ctx: "ActionContext") -> bool:
        """Return ``False`` to hide this action.

        Checked once when the window builds its actions — useful to require an
        external tool, or a path, to be present.
        """
        return True

    def run(self, ctx: "ActionContext") -> None:
        """Perform the action. Raising is caught and reported in the console."""
        raise NotImplementedError(
            f"UiAction '{self.id or type(self).__name__}' does not implement run()."
        )


class CommandAction(UiAction):
    """A :class:`UiAction` that just runs a command — no ``run()`` to write.

    Set :attr:`command` to a string (executed through the shell, so ``.bat``
    files and Explorer calls work) or to an argument list. The working
    directory comes from :attr:`cwd` when set, otherwise from the
    :class:`ActionContext` path named by :attr:`cwd_key`.
    """

    #: Command line, or argument list. Required.
    command: Sequence[str] | str = ""
    #: Absolute working directory. Takes precedence over :attr:`cwd_key`.
    cwd: str = ""
    #: Name of the :class:`ActionContext` path to run in ("comfyui_dir",
    #: "models_dir", "custom_nodes_dir", ...). Defaults to the deployer root.
    cwd_key: str = "project_root"
    #: Extra environment variables, merged over the current environment.
    #: Treated as read-only — never mutate it in place.
    env: dict[str, str] | None = None
    #: Report a non-zero exit code as an error line in the console.
    report_failure: bool = True

    def run(self, ctx: "ActionContext") -> None:
        if not self.command:
            ctx.log(f"  Action '{self.id}' has no command to run.")
            return
        workdir = self.cwd or ctx.path(self.cwd_key) or ctx.project_root
        code = ctx.run_command(self.command, cwd=workdir, env=self.env)
        if code != 0 and self.report_failure:
            ctx.log(f"  Command failed with exit code {code}: {self.command}")

"""Reference plugin: extend the main window with custom command buttons.

This file is a **worked example** of the UI-action plugin API. It is NOT
auto-loaded — it lives under ``deployer/plugins/examples/`` rather than
``deployer/plugins/builtin/`` or ``<PROJECT_ROOT>/plugins/``. To try it, copy
it into one of those directories.

It shows the three ways to contribute a button:

1. :class:`CommandAction` — declarative: a label and a command, no code.
2. :class:`UiAction` with a ``run()`` — arbitrary Python plus
   ``ctx.run_command`` for the subprocess parts, running on a worker thread so
   the window stays responsive.
3. ``location = ActionLocation.MENU`` — the same thing as a hamburger-menu
   entry instead of a button, for actions that don't deserve the screen space.

No PyQt import here, at module level or anywhere else: the headless install
path loads plugin modules without Qt, and UI actions are simply ignored there.
"""

from __future__ import annotations

import os

from deployer.plugins import (
    ActionContext,
    ActionLocation,
    ActionStyle,
    CommandAction,
    UiAction,
)


class OpenOutputFolder(CommandAction):
    """Simplest possible action: a button that runs one command."""

    id = "example_open_output_folder"
    label = "Output folder"
    description = "Open ComfyUI/output in Explorer."
    command = "explorer ."           # a str runs through the shell
    cwd_key = "output_dir"           # any ActionContext path name
    order = 10                       # sorts before the actions below
    blocked_when_busy = False        # harmless — stays clickable during an install


class ClearComfyCache(UiAction):
    """A scripted action: confirmation, real Python, then a command."""

    id = "example_clear_cache"
    label = "Clear cache"
    description = "Delete the deployer's downloaded node-database cache."
    style = ActionStyle.WARNING
    order = 20
    confirm = "Delete the cached ComfyUI-Manager node database?"

    def run(self, ctx: ActionContext) -> None:
        cache = os.path.join(ctx.project_root, ".cache")
        if not os.path.isdir(cache):
            ctx.log("  Nothing to clear — no cache directory.")
            return
        for name in os.listdir(cache):
            os.remove(os.path.join(cache, name))
            ctx.log(f"  Removed {name}")
        ctx.log("  Cache cleared.")


class PipList(UiAction):
    """A menu entry that shells out and streams the output to the console."""

    id = "example_pip_list"
    label = "List installed packages"
    description = "Run 'pip list' against ComfyUI's embedded Python."
    location = ActionLocation.MENU
    order = 30
    blocked_when_busy = False        # read-only — safe while something installs

    def is_available(self, ctx: ActionContext) -> bool:
        # Hide the entry when the portable install isn't there yet.
        return os.path.isfile(ctx.python_exe)

    def run(self, ctx: ActionContext) -> None:
        # An argument list bypasses the shell — safest for paths with spaces.
        ctx.run_command([ctx.python_exe, "-m", "pip", "list"])


class ReinstallNodeRequirements(UiAction):
    """Shows ``ctx.refresh_nodes``: re-read the cards once the work is done."""

    id = "example_reinstall_requirements"
    label = "Reinstall requirements"
    description = "Re-run every custom node's requirements.txt."
    style = ActionStyle.PRIMARY
    order = 40
    confirm = "Reinstall the requirements of every installed custom node?"
    # blocked_when_busy stays True (the default): this writes into
    # python_embeded and must not race the install pipeline.

    def run(self, ctx: ActionContext) -> None:
        for name in sorted(os.listdir(ctx.custom_nodes_dir)):
            req = os.path.join(ctx.custom_nodes_dir, name, "requirements.txt")
            if not os.path.isfile(req):
                continue
            ctx.log(f"  Installing requirements for {name}...")
            ctx.run_command([ctx.python_exe, "-m", "pip", "install", "-r", req])
        ctx.refresh_nodes()  # safe from the worker thread


def register(registry):
    registry.register_action(OpenOutputFolder())
    registry.register_action(ClearComfyCache())
    registry.register_action(PipList())
    registry.register_action(ReinstallNodeRequirements())

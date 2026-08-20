# =====================================================================
#  EXAMPLE UI-ACTION PLUGIN  (disabled — everything below is commented)
# =====================================================================
#
#  A UI action adds a **button to the main window's bottom row** (or an entry
#  to the ☰ menu) that runs whatever you want: a .bat, a git command, a
#  Python script, some Explorer call...
#
#  Drop a real ``.py`` file in this folder (or uncomment the code below) and
#  it is auto-discovered at startup — the button appears next to Update /
#  Run Comfy. Everything the command prints is streamed to the console panel.
#
#  This folder is gitignored (only this example, the bundle-step example and
#  the README are tracked), so a plugin you drop here stays private. It still
#  ships with every bundle you export, so the recipient gets your buttons too.
#
#  IMPORTANT: never import PyQt6 in a plugin module at top level — the
#  headless install path imports it without Qt. UI actions never need Qt
#  anyway; see deployer/plugins/actions.py for the full contract.
#
#  To enable this example: remove the leading "# " on the lines below.
# ---------------------------------------------------------------------
#
# import os
#
# from deployer.plugins import (
#     ActionContext,
#     ActionLocation,
#     ActionStyle,
#     CommandAction,
#     UiAction,
# )
#
#
# class OpenOutputFolder(CommandAction):
#     """Declarative button: just a label and a command."""
#
#     id = "open_output_folder"        # unique, stable
#     label = "Output folder"          # button text
#     description = "Open ComfyUI/output in Explorer."   # tooltip
#     command = "explorer ."           # str -> runs through the shell
#     cwd_key = "output_dir"           # project_root | comfyui_dir | models_dir
#                                      # custom_nodes_dir | input_dir | output_dir
#                                      # portable_dir  (or set cwd="D:/somewhere")
#     order = 10                       # sort key among plugin buttons
#     blocked_when_busy = False        # harmless -> stays clickable during an install
#
#
# class RunMyScript(UiAction):
#     """Scripted button: confirmation, Python, and streamed subprocess output."""
#
#     id = "run_my_script"
#     label = "My script"
#     description = "Run my maintenance script against the local install."
#     style = ActionStyle.WARNING      # NEUTRAL | PRIMARY | SUCCESS | WARNING | DANGER
#     location = ActionLocation.TOOLBAR  # or ActionLocation.MENU (☰ entry)
#     order = 20
#     confirm = "Run the maintenance script?"   # omit for no confirmation
#     background = True                # False only for a short, Qt-touching action
#     blocked_when_busy = True         # default: greyed out while the deployer
#                                      # installs / bundles / updates ComfyUI.
#                                      # False for a read-only action that can't interfere.
#
#     def is_available(self, ctx: ActionContext) -> bool:
#         # Return False to hide the button entirely.
#         return os.path.isfile(ctx.python_exe)
#
#     def run(self, ctx: ActionContext) -> None:
#         ctx.log("Starting...")                       # -> console panel
#         ctx.run_command([ctx.python_exe, "-m", "pip", "list"])  # list -> no shell
#         ctx.run_command("git status", cwd=ctx.comfyui_dir)      # str  -> shell
#         ctx.refresh_nodes()          # re-read the node cards (thread-safe)
#
#
# def register(registry):
#     registry.register_action(OpenOutputFolder())
#     registry.register_action(RunMyScript())

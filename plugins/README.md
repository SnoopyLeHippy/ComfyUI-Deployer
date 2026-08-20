# Plugins

Drop-in plugins. Each `.py` here is auto-discovered by the deployer at startup
and can contribute two kinds of thing — a file may contribute either or both:

- **Bundle steps** — they appear in the Create Bundle dialog under
  **Install steps → ＋ Add step**. A step runs at bundle **creation** (author
  machine) and/or **install** (the recipient's machine, via the sharable
  `.bat`) — the plugin declares which via `phases` (`StepPhase.CREATE`,
  `StepPhase.INSTALL`, or `StepPhase.BOTH`).
- **UI actions** — buttons added to the main window's bottom row (or entries in
  the ☰ menu) that run a custom command against your local install.

This folder is **gitignored** — only this README and the disabled examples are
tracked, so anything you drop here stays private to your machine and is never
pushed.

Your plugins still travel with every bundle you export, but through an explicit
copy rather than the git clone: a folder bundle gets them copied into
`<bundle>/plugins/`, and a sharable `.bat` embeds them as a base64 tar that is
unpacked into `plugins/` before the headless install runs. Their install-phase
steps then run on the recipient's machine.

To share a plugin with other people instead of keeping it local, publish it as a
git repo and add it under **☰ → Manage Plugins...** (remote plugins are cloned
into `plugins/remote/`).

## Writing a bundle step

A plugin module exposes a `register(registry)` entry point (or defines a
`BundleStep` subclass). See [`example_copy_models_from_root.py`](example_copy_models_from_root.py)
for a fully commented template, and `deployer/plugins/api.py` for the contract.

```python
from deployer.plugins import BundleStep, StepPhase

class MyStep(BundleStep):
    id = "my_step"            # unique, stable — persisted in the bundle
    name = "My step"
    description = "Shown in the Add-step menu."
    phases = StepPhase.INSTALL

    def run(self, ctx, config):
        ...                   # ctx.models_dir, ctx.comfyui_dir, ctx.log, ...

def register(registry):
    registry.register(MyStep())
```

> **Important:** if your step has a config UI, import PyQt6 **lazily inside
> `build_widget`**, never at module top level — the headless install path
> imports plugin modules without Qt.

## Writing a custom button

A UI action becomes a button in the main window's bottom row (or an entry in
the ☰ menu). Everything the command prints lands in the console panel. See
[`example_ui_actions.py`](example_ui_actions.py) for a fully commented
template, and `deployer/plugins/actions.py` for the contract.

```python
from deployer.plugins import CommandAction

class OpenModelsFolder(CommandAction):
    id = "open_models_folder"     # unique, stable
    label = "Models"              # button text
    description = "Open the models folder."   # tooltip
    command = "explorer ."        # str -> shell; list -> direct
    cwd_key = "models_dir"        # any ActionContext path name

def register(registry):
    registry.register_action(OpenModelsFolder())
```

Subclass `UiAction` and write `run(ctx)` instead when the action needs real
logic — `ctx.run_command()`, `ctx.log()`, `ctx.refresh_nodes()` and every local
path are available. Actions run on a worker thread by default, so a long
command never freezes the window.

By default an action is greyed out while the deployer is busy (install, bundle,
ComfyUI update). Set `blocked_when_busy = False` on one that can't interfere —
opening a folder, reading a log — and it stays clickable throughout.

> **Important:** a UI action must **never** import PyQt6 — not even lazily.
> It doesn't need it, and the module still has to import cleanly on the
> headless install path (where UI actions are simply ignored).

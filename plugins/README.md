# Plugins

Drop-in **bundle-step plugins**. Each `.py` here is auto-discovered by the
deployer and its steps appear in the Create Bundle dialog under
**Install steps → ＋ Add step**.

A step runs at bundle **creation** (author machine) and/or **install** (the
recipient's machine, via the sharable `.bat`) — the plugin declares which via
`phases` (`StepPhase.CREATE`, `StepPhase.INSTALL`, or `StepPhase.BOTH`).

This folder is **gitignored** — only this README and the disabled example are
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

## Writing one

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

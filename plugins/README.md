# Plugins

Drop-in **bundle-step plugins**. Each `.py` here is auto-discovered by the
deployer and its steps appear in the Create Bundle dialog under
**Install steps → ＋ Add step**.

A step runs at bundle **creation** (author machine) and/or **install** (the
recipient's machine, via the sharable `.bat`) — the plugin declares which via
`phases` (`StepPhase.CREATE`, `StepPhase.INSTALL`, or `StepPhase.BOTH`).

This folder is committed to the repo, so a plugin here ships inside every
bundle (the bundled deployer is a clone) and its install-phase steps run on the
recipient's machine.

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

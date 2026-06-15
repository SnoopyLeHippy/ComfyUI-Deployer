"""Execute a list of configured bundle steps for a given phase.

Shared by the builder (``CREATE`` phase, author machine) and the headless
install (``INSTALL`` phase, recipient machine). A step list is the serialized
form persisted in ``user_settings.json``::

    [
        {"id": "copy_models_from_root", "config": {"root": "D:/models"}},
        ...
    ]

Each entry is looked up in the registry, skipped when it does not opt into the
context's phase, validated, then run. A failing step is reported but never
aborts the remaining steps.
"""

from __future__ import annotations

import traceback

from deployer.plugins.api import StepContext
from deployer.plugins.registry import registry


def run_steps(steps: list[dict], ctx: StepContext) -> None:
    """Run every entry in *steps* applicable to ``ctx.phase``."""
    if not steps:
        return

    log = ctx.log
    for entry in steps:
        step_id = (entry or {}).get("id", "")
        config = (entry or {}).get("config", {}) or {}

        step = registry.get(step_id)
        if step is None:
            log(f"  Skipping unknown bundle step '{step_id}' (no plugin registered).")
            continue
        if not (step.phases & ctx.phase):
            continue
        if not (step.bundle_formats & ctx.bundle_format):
            continue

        error = step.validate(config)
        if error:
            log(f"  Skipping step '{step.name}': {error}")
            continue

        log(f"Running bundle step: {step.name}...")
        try:
            step.run(ctx, config)
        except Exception:  # noqa: BLE001 — isolate a faulty step from the rest.
            log(f"  Step '{step.name}' failed:\n{traceback.format_exc()}")

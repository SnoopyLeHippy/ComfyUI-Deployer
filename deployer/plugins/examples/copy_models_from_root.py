"""Reference plugin: copy models from a root folder into the bundle/install.

This file is a **worked example** of the bundle-step plugin API. It is NOT
auto-loaded — it lives under ``deployer/plugins/examples/`` rather than
``deployer/plugins/builtin/`` or ``<PROJECT_ROOT>/plugins/``. To try it, copy
it into one of those directories.

It demonstrates the full contract:

* class attributes (``id``, ``name``, ``description``, ``phases``),
* a configuration widget built with PyQt (imported lazily, never at module
  top level, so the plugin stays importable on the headless install path),
* ``read_config`` / ``load_config`` to (de)serialize that widget,
* ``validate`` to gate a bad config,
* ``run`` to do the work against a :class:`StepContext`.

The step declares ``phases = StepPhase.BOTH``: at CREATE time it copies from a
root on the author's machine into the freshly built bundle; at INSTALL time it
copies from a root on the recipient's machine into their install.
"""

from __future__ import annotations

import os
import shutil

from deployer.plugins import BundleStep, StepContext, StepPhase


class CopyModelsFromRootStep(BundleStep):
    id = "copy_models_from_root"
    name = "Copy models from a root folder"
    description = "Recursively copy a folder's contents into the bundle's models/ directory."
    phases = StepPhase.BOTH

    # -- Configuration UI --------------------------------------------------
    def build_widget(self, parent=None):
        # Lazy import: PyQt is only available in the Create Bundle dialog.
        from PyQt6.QtWidgets import (
            QFileDialog,
            QHBoxLayout,
            QLineEdit,
            QPushButton,
            QWidget,
        )

        widget = QWidget(parent)
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        edit.setPlaceholderText("Root folder to copy models from...")
        browse = QPushButton("Browse...")

        def pick():
            path = QFileDialog.getExistingDirectory(widget, "Select models root")
            if path:
                edit.setText(os.path.normpath(path))

        browse.clicked.connect(pick)
        row.addWidget(edit)
        row.addWidget(browse)
        widget._edit = edit  # stash for read/load_config
        return widget

    def read_config(self, widget) -> dict:
        return {"root": widget._edit.text().strip()}

    def load_config(self, widget, config: dict) -> None:
        widget._edit.setText(config.get("root", ""))

    # -- Validation & execution -------------------------------------------
    def validate(self, config: dict) -> str | None:
        if not config.get("root"):
            return "Choose a root folder to copy models from."
        return None

    def run(self, ctx: StepContext, config: dict) -> None:
        root = config["root"]
        if not os.path.isdir(root):
            ctx.log(f"  Root folder does not exist, skipping: {root}")
            return
        os.makedirs(ctx.models_dir, exist_ok=True)
        ctx.log(f"  Copying models from {root} -> {ctx.models_dir}")
        shutil.copytree(root, ctx.models_dir, dirs_exist_ok=True)


def register(registry):
    registry.register(CopyModelsFromRootStep())

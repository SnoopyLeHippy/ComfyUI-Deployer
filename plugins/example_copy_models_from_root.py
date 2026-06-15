# =====================================================================
#  EXAMPLE BUNDLE-STEP PLUGIN  (disabled — everything below is commented)
# =====================================================================
#
#  Drop a real ``.py`` file in this folder (or uncomment the code below)
#  and it is auto-discovered by the deployer: it appears in the Create
#  Bundle dialog under "Install steps" → "＋ Add step".
#
#  This folder is part of the repo, so a committed plugin ships with every
#  bundle (the bundled deployer is a clone) and its INSTALL-phase steps run
#  on the recipient's machine.
#
#  A plugin must define a ``register(registry)`` entry point (or a
#  ``BundleStep`` subclass). See deployer/plugins/api.py for the full
#  contract. IMPORTANT: import PyQt6 *lazily* inside ``build_widget`` only,
#  never at module top level — the headless install path imports this module
#  without Qt.
#
#  To enable this example: remove the leading "# " on the lines below.
# ---------------------------------------------------------------------
#
# import os
# import shutil
#
# from deployer.plugins import BundleStep, StepContext, StepPhase
#
#
# class CopyModelsFromRootStep(BundleStep):
#     id = "copy_models_from_root"
#     name = "Copy models from a root folder"
#     description = "Recursively copy a folder's contents into the bundle's models/ directory."
#     phases = StepPhase.BOTH  # CREATE (author machine) and INSTALL (recipient machine)
#
#     # -- Configuration UI ---------------------------------------------
#     def build_widget(self, parent=None):
#         # Lazy import: PyQt is only available in the Create Bundle dialog.
#         from PyQt6.QtWidgets import (
#             QFileDialog,
#             QHBoxLayout,
#             QLineEdit,
#             QPushButton,
#             QWidget,
#         )
#
#         widget = QWidget(parent)
#         row = QHBoxLayout(widget)
#         row.setContentsMargins(0, 0, 0, 0)
#         edit = QLineEdit()
#         edit.setPlaceholderText("Root folder to copy models from...")
#         browse = QPushButton("Browse...")
#
#         def pick():
#             path = QFileDialog.getExistingDirectory(widget, "Select models root")
#             if path:
#                 edit.setText(os.path.normpath(path))
#
#         browse.clicked.connect(pick)
#         row.addWidget(edit)
#         row.addWidget(browse)
#         widget._edit = edit  # stash for read/load_config
#         return widget
#
#     def read_config(self, widget) -> dict:
#         return {"root": widget._edit.text().strip()}
#
#     def load_config(self, widget, config: dict) -> None:
#         widget._edit.setText(config.get("root", ""))
#
#     # -- Validation & execution ---------------------------------------
#     def validate(self, config: dict) -> str | None:
#         if not config.get("root"):
#             return "Choose a root folder to copy models from."
#         return None
#
#     def run(self, ctx: StepContext, config: dict) -> None:
#         root = config["root"]
#         if not os.path.isdir(root):
#             ctx.log(f"  Root folder does not exist, skipping: {root}")
#             return
#         os.makedirs(ctx.models_dir, exist_ok=True)
#         ctx.log(f"  Copying models from {root} -> {ctx.models_dir}")
#         shutil.copytree(root, ctx.models_dir, dirs_exist_ok=True)
#
#
# def register(registry):
#     registry.register(CopyModelsFromRootStep())

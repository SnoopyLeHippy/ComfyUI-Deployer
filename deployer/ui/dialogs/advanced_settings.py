"""Advanced settings dialog: extra model paths and folder junctions."""

import os
import shutil

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from deployer.config import (
    EXTRA_MODEL_PATHS_YAML,
    INPUT_DIR,
    MODELS_DIR,
    OUTPUT_DIR,
)
from deployer.core.junctions import (
    apply_folder_junction,
    read_junction_target,
    remove_folder_junction,
)
from deployer.ui import theme
from deployer.ui.dialogs.path_picker import PathPickerRow


# Ordered: (settings key, target dir under ComfyUI, backup-name for the
# pre-junction contents). Used by both the dialog and the import flow.
_FOLDER_JUNCTIONS = (
    ("model_folder",  MODELS_DIR, "_models"),
    ("output_folder", OUTPUT_DIR, "_output"),
    ("input_folder",  INPUT_DIR,  "_input"),
)


def apply_advanced_settings(settings: dict) -> None:
    """Apply a settings dict to disk (extra model paths + folder junctions).

    ``settings`` matches the on-disk schema stored under the ``settings`` key
    of ``user_settings.json``:

    * ``extra_model_path`` — path to a YAML file copied to
      ``COMFYUI/extra_model_paths.yaml``. Empty string removes it.
    * ``model_folder`` / ``output_folder`` / ``input_folder`` — directory
      paths a junction is created at. Empty string removes the junction.

    Errors on individual entries are logged but don't abort the rest of the
    apply pass, so a missing source path can't block applying the others.
    """
    extra_path = settings.get("extra_model_path", "")
    if extra_path:
        try:
            shutil.copy(extra_path, EXTRA_MODEL_PATHS_YAML)
            print(f"Copied extra model path: {extra_path} → {EXTRA_MODEL_PATHS_YAML}")
        except Exception as exc:
            print(f"Error copying extra model path: {exc}")
    elif os.path.exists(EXTRA_MODEL_PATHS_YAML):
        try:
            os.remove(EXTRA_MODEL_PATHS_YAML)
            print(f"Removed {EXTRA_MODEL_PATHS_YAML}")
        except Exception as exc:
            print(f"Error removing extra model path: {exc}")

    apply_folder_junctions(settings)


def apply_folder_junctions(settings: dict) -> None:
    """Apply only the ``model_folder`` / ``output_folder`` / ``input_folder``
    junctions from *settings*, ignoring ``extra_model_path``.

    Split out from :func:`apply_advanced_settings` so headless callers (the
    sharable-bat installer) can apply the folder junctions without touching
    ``extra_model_paths.yaml`` — that file is written directly by the .bat.

    Errors on individual entries are logged but don't abort the rest of the
    apply pass.
    """
    for key, target_dir, backup_name in _FOLDER_JUNCTIONS:
        backup_dir = os.path.join(os.path.dirname(target_dir), backup_name)
        selected = settings.get(key, "")
        try:
            if selected:
                apply_folder_junction(target_dir, backup_dir, selected)
            else:
                remove_folder_junction(target_dir, backup_dir)
        except Exception as exc:
            print(f"Error applying junction for {key}: {exc}")


class AdvancedSettingsDialog(QDialog):
    """Dialog for advanced ComfyUI settings (folder junctions, extra model paths…)."""

    def __init__(self, saved_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Advanced Settings")
        self.setMinimumWidth(600)
        self.setStyleSheet(theme.APP_STYLE)
        self._new_settings: dict = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(2)

        # --- Extra model path ---
        extra_path = saved_settings.get("extra_model_path", "")
        if extra_path and not os.path.exists(EXTRA_MODEL_PATHS_YAML):
            extra_path = ""  # file was removed externally
        self._extra_row = PathPickerRow(
            "Extra model path",
            "Add or Replace the extra model path file",
            pick_type="file",
            current_path=extra_path,
        )
        layout.addWidget(self._extra_row)
        layout.addWidget(self._separator())

        # --- Model folder ---
        self._model_row = PathPickerRow(
            "Model folder",
            "Pick a model folder to use",
            pick_type="folder",
            current_path=read_junction_target(MODELS_DIR),
        )
        layout.addWidget(self._model_row)
        layout.addWidget(self._separator())

        # --- Output folder ---
        self._output_row = PathPickerRow(
            "Output folder",
            "Pick an output folder to use",
            pick_type="folder",
            current_path=read_junction_target(OUTPUT_DIR),
        )
        layout.addWidget(self._output_row)
        layout.addWidget(self._separator())

        # --- Input folder ---
        self._input_row = PathPickerRow(
            "Input folder",
            "Pick an input folder to use",
            pick_type="folder",
            current_path=read_junction_target(INPUT_DIR),
        )
        layout.addWidget(self._input_row)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        cancel_btn.setMinimumWidth(90)
        cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cancel_btn.setFixedHeight(34)
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(theme.RUN_COMFY_BUTTON_STYLE)
        ok_btn.setMinimumWidth(90)
        ok_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        ok_btn.setFixedHeight(34)
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    @staticmethod
    def _separator() -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(theme.SEPARATOR_STYLE)
        return line

    def _on_ok(self):
        self._apply()
        self.accept()

    def _apply(self):
        settings = {
            "extra_model_path": self._extra_row.path,
            "model_folder":  self._model_row.path,
            "output_folder": self._output_row.path,
            "input_folder":  self._input_row.path,
        }
        apply_advanced_settings(settings)
        self._new_settings = settings

    def applied_settings(self) -> dict:
        return self._new_settings

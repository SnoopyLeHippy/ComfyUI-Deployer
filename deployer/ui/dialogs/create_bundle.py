"""Dialog to configure and create a portable ComfyUI bundle."""

import os

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from deployer.ui import theme


class CreateBundleDialog(QDialog):
    """Dialog to configure and create a portable ComfyUI bundle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Bundle")
        self.setMinimumWidth(550)
        self.setStyleSheet(theme.APP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # --- Destination folder ---
        layout.addWidget(QLabel("Destination folder:"))
        dest_row = QHBoxLayout()
        dest_row.setSpacing(6)
        self._dest_edit = QLineEdit()
        self._dest_edit.setReadOnly(True)
        self._dest_edit.setPlaceholderText("Select a destination folder...")
        self._dest_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        dest_row.addWidget(self._dest_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(90)
        browse_btn.setStyleSheet(theme.BROWSE_BUTTON_STYLE)
        browse_btn.clicked.connect(self._pick_dest)
        dest_row.addWidget(browse_btn)
        layout.addLayout(dest_row)

        # --- Workflow files (optional) ---
        layout.addWidget(QLabel("From workflow(s): (optional)"))
        wf_row = QHBoxLayout()
        wf_row.setSpacing(6)
        self._wf_edit = QLineEdit()
        self._wf_edit.setReadOnly(True)
        self._wf_edit.setPlaceholderText("No workflows selected — all nodes & models will be included")
        self._wf_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        wf_row.addWidget(self._wf_edit)
        wf_browse = QPushButton("Browse...")
        wf_browse.setFixedWidth(90)
        wf_browse.setStyleSheet(theme.BROWSE_BUTTON_STYLE)
        wf_browse.clicked.connect(self._pick_workflows)
        wf_row.addWidget(wf_browse)
        wf_clear = QPushButton("✕")
        wf_clear.setFixedWidth(30)
        wf_clear.setStyleSheet(theme.CLEAR_BUTTON_NO_DISABLED_STYLE)
        wf_clear.clicked.connect(self._clear_workflows)
        wf_row.addWidget(wf_clear)
        layout.addLayout(wf_row)

        help_lbl = QLabel(
            "When workflows are provided, only the custom nodes (and, when \"Add models\" "
            "is enabled, the models) used in those workflows are included."
        )
        help_lbl.setStyleSheet(theme.HELP_TEXT_STYLE)
        help_lbl.setWordWrap(True)
        layout.addWidget(help_lbl)

        # --- Include workflows in the export ---
        self._include_workflows_cb = QCheckBox("Include selected workflows in the export")
        self._include_workflows_cb.setStyleSheet(theme.CHECKBOX_STYLE)
        self._include_workflows_cb.setChecked(False)
        self._include_workflows_cb.setEnabled(False)
        self._include_workflows_cb.setToolTip(
            "Copy the selected workflow files alongside the export. In a regular "
            "bundle they go into a 'workflows/' folder at the export root; in the "
            "sharable .bat they are embedded and extracted next to the .bat at install time."
        )
        layout.addWidget(self._include_workflows_cb)

        # --- Add models checkbox ---
        self._add_models_cb = QCheckBox("Add models")
        self._add_models_cb.setStyleSheet(theme.CHECKBOX_STYLE)
        self._add_models_cb.setChecked(False)
        self._add_models_cb.setToolTip(
            "Copy model files into the bundle. With workflow(s) selected only the "
            "referenced models are copied; otherwise the entire models/ folder is "
            "copied (can be very large). Not available for the sharable .bat."
        )
        layout.addWidget(self._add_models_cb)

        # --- Add ComfyUI Deployer checkbox ---
        self._add_debugger_cb = QCheckBox("Add ComfyUI Deployer")
        self._add_debugger_cb.setStyleSheet(theme.CHECKBOX_STYLE)
        self._add_debugger_cb.setChecked(False)
        self._add_debugger_cb.setToolTip(
            "Clone this tool into the bundle destination "
        )
        layout.addWidget(self._add_debugger_cb)

        # --- Export as sharable .bat file ---
        self._bat_cb = QCheckBox("Export as sharable .bat file")
        self._bat_cb.setStyleSheet(theme.CHECKBOX_STYLE)
        self._bat_cb.setChecked(False)
        self._bat_cb.setToolTip(
            "Write a single self-contained .bat instead of a full bundle. When run on "
            "another machine it clones ComfyUI Deployer, downloads the matching ComfyUI, "
            "and installs the selected nodes & requirements. Models are NOT included."
        )
        self._bat_cb.toggled.connect(self._on_bat_toggled)
        layout.addWidget(self._bat_cb)

        # --- Include advanced settings (only meaningful in .bat mode) ---
        self._adv_settings_cb = QCheckBox("Include advanced settings")
        self._adv_settings_cb.setStyleSheet(theme.CHECKBOX_STYLE)
        self._adv_settings_cb.setChecked(False)
        self._adv_settings_cb.setEnabled(False)
        self._adv_settings_cb.setToolTip(
            "Embed extra_model_paths.yaml and the advanced folder settings "
            "(model / output / input) into the generated .bat."
        )
        layout.addWidget(self._adv_settings_cb)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        cancel_btn.setMinimumWidth(90)
        cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cancel_btn.setFixedHeight(34)
        cancel_btn.clicked.connect(self.reject)
        self._create_btn = QPushButton("Create")
        self._create_btn.setStyleSheet(theme.RUN_COMFY_BUTTON_STYLE)
        self._create_btn.setMinimumWidth(90)
        self._create_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._create_btn.setFixedHeight(34)
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._on_create)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self._create_btn)
        layout.addLayout(btn_layout)

        self._dest_path = ""
        self._wf_paths: list[str] = []

    def _on_bat_toggled(self, checked: bool):
        """Toggle .bat-only mode.

        The .bat always clones the ComfyUI Deployer (it's needed to install the
        nodes), so "Add ComfyUI Deployer" is forced on and disabled. The .bat
        never ships models, so "Add models" is forced off and disabled. The
        advanced-settings export only applies to the .bat.
        """
        self._adv_settings_cb.setEnabled(checked)
        if checked:
            self._add_debugger_cb.setChecked(True)
            self._add_models_cb.setChecked(False)
        self._add_debugger_cb.setEnabled(not checked)
        self._add_models_cb.setEnabled(not checked)

    def _pick_dest(self):
        path = QFileDialog.getExistingDirectory(self, "Select destination folder", os.path.expanduser("~"))
        if path:
            self._dest_path = os.path.normpath(path)
            self._dest_edit.setText(self._dest_path)
            self._create_btn.setEnabled(True)

    def _pick_workflows(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select workflow files",
            os.path.expanduser("~"),
            "ComfyUI Workflows (*.json *.png *.webp *.jpg *.jpeg);;All Files (*)",
        )
        if paths:
            self._wf_paths = [os.path.normpath(p) for p in paths]
            self._wf_edit.setText("; ".join(os.path.basename(p) for p in self._wf_paths))
            self._include_workflows_cb.setEnabled(True)

    def _clear_workflows(self):
        self._wf_paths = []
        self._wf_edit.setText("")
        self._include_workflows_cb.setChecked(False)
        self._include_workflows_cb.setEnabled(False)

    def _on_create(self):
        if self._dest_path:
            self.accept()

    def dest_path(self) -> str:
        return self._dest_path

    def workflow_paths(self) -> list[str]:
        return list(self._wf_paths)

    def include_debugger(self) -> bool:
        return self._add_debugger_cb.isChecked()

    def include_models(self) -> bool:
        return self._add_models_cb.isChecked()

    def export_as_bat(self) -> bool:
        return self._bat_cb.isChecked()

    def export_advanced_settings(self) -> bool:
        return self._adv_settings_cb.isChecked()

    def include_workflows(self) -> bool:
        return bool(self._wf_paths) and self._include_workflows_cb.isChecked()

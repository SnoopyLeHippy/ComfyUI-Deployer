"""Dialog to configure and create a portable ComfyUI bundle.

The dialog is a 4-step wizard:

    1. Type        — .bat (default) vs folder
    2. Destination — required, gates the Next button
    3. Scope       — optional workflow filter
    4. Options     — content adapts to the chosen Type

Public accessors (``dest_path``, ``workflow_paths``, ``include_debugger``,
``include_models``, ``include_workflows``, ``export_as_bat``,
``export_advanced_settings``) keep the same contract as before, including
the .bat-mode forcing (Deployer always on, models never embedded).
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from deployer.ui import theme


_STEP_TITLES = ["What do you want to create?", "Destination", "Scope (optional)", "Options"]
_NUM_STEPS = len(_STEP_TITLES)

# Local +2px overrides on shared theme styles, so this dialog's typography
# can grow without changing how other dialogs/widgets render.
_CHECKBOX_STYLE_PLUS2 = theme.CHECKBOX_STYLE + " QCheckBox { font-size: 13px; }"
_TEXTBOX_STYLE_PLUS2 = theme.DIALOG_TEXTBOX_STYLE + " QLineEdit { font-size: 14px; }"


class CreateBundleDialog(QDialog):
    """4-step wizard to configure and create a portable ComfyUI bundle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Bundle")
        self.setMinimumWidth(560)
        self.setMinimumHeight(380)
        self.setStyleSheet(theme.APP_STYLE)

        self._dest_path = ""
        self._wf_paths: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(0)

        # Section 1 — dots (the "knot")
        outer.addWidget(self._build_dots())
        outer.addSpacing(10)

        # Section 2 — title block (STEP X OF N + page title, tightly grouped)
        outer.addLayout(self._build_title_block())
        outer.addSpacing(10)

        # Section 3 — content
        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_type_page())
        self._pages.addWidget(self._build_destination_page())
        self._pages.addWidget(self._build_scope_page())
        self._pages.addWidget(self._build_options_page())
        outer.addWidget(self._pages, 1)

        outer.addSpacing(10)
        outer.addLayout(self._build_footer())

        self._bat_radio.setChecked(True)  # default = .bat
        self._refresh_options_visibility()
        self._refresh_workflow_dependent_widgets()
        self._goto(0)

    # ------------------------------------------------------------- Header
    def _build_dots(self) -> QLabel:
        self._dots_lbl = QLabel()
        self._dots_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._dots_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        return self._dots_lbl

    def _build_title_block(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(2)
        self._step_lbl = QLabel()
        self._step_lbl.setStyleSheet(theme.RADIO_SUBTITLE_STYLE)
        v.addWidget(self._step_lbl)

        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(theme.SECTION_TITLE_STYLE)
        v.addWidget(self._title_lbl)
        return v

    def _render_dots(self, current: int) -> str:
        parts = []
        for i in range(_NUM_STEPS):
            color = theme.BLUE_BADGE if i <= current else theme.TEXT_SUBTLE
            glyph = "●" if i <= current else "○"
            parts.append(f'<span style="color:{color}; font-size:16px">{glyph}</span>')
        return "&nbsp;&nbsp;&nbsp;".join(parts)

    # ------------------------------------------------------------- Pages
    def _build_type_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)

        self._bat_radio = QRadioButton("A single .bat file you can share")
        self._bat_radio.setStyleSheet(theme.RADIO_STYLE)
        self._folder_radio = QRadioButton("A folder with everything inside")
        self._folder_radio.setStyleSheet(theme.RADIO_STYLE)

        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self._bat_radio)
        self._type_group.addButton(self._folder_radio)
        self._bat_radio.toggled.connect(self._refresh_options_visibility)

        v.addWidget(self._bat_radio)
        v.addWidget(self._radio_subtitle(
            "small · self-installs on the target PC · models can't be embedded"
        ))
        v.addSpacing(4)
        v.addWidget(self._folder_radio)
        v.addWidget(self._radio_subtitle(
            "portable · runs in place · can include models"
        ))
        v.addStretch()
        return page

    def _build_destination_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(8)

        v.addWidget(self._help_label("Where the bundle will be written:"))
        dest_row = QHBoxLayout()
        dest_row.setSpacing(6)
        self._dest_edit = QLineEdit()
        self._dest_edit.setReadOnly(True)
        self._dest_edit.setPlaceholderText("Select a destination folder...")
        self._dest_edit.setStyleSheet(_TEXTBOX_STYLE_PLUS2)
        dest_row.addWidget(self._dest_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(90)
        browse_btn.setStyleSheet(theme.BROWSE_BUTTON_STYLE)
        browse_btn.clicked.connect(self._pick_dest)
        dest_row.addWidget(browse_btn)
        v.addLayout(dest_row)
        v.addStretch()
        return page

    def _build_scope_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(8)

        v.addWidget(self._help_label("Limit the bundle to specific workflows:"))
        wf_row = QHBoxLayout()
        wf_row.setSpacing(6)
        self._wf_edit = QLineEdit()
        self._wf_edit.setReadOnly(True)
        self._wf_edit.setPlaceholderText("No workflows — full ComfyUI is bundled")
        self._wf_edit.setStyleSheet(_TEXTBOX_STYLE_PLUS2)
        wf_row.addWidget(self._wf_edit)
        wf_browse = QPushButton("Browse...")
        wf_browse.setFixedWidth(90)
        wf_browse.setStyleSheet(theme.BROWSE_BUTTON_STYLE)
        wf_browse.clicked.connect(self._pick_workflows)
        wf_row.addWidget(wf_browse)
        self._wf_clear = QPushButton("✕")
        self._wf_clear.setFixedWidth(30)
        self._wf_clear.setStyleSheet(theme.CLEAR_BUTTON_NO_DISABLED_STYLE)
        self._wf_clear.clicked.connect(self._clear_workflows)
        wf_row.addWidget(self._wf_clear)
        v.addLayout(wf_row)

        scope_help = QLabel(
            "ℹ When workflows are set, only the custom nodes (and models, if "
            "enabled) used by those workflows are included. Skip this step "
            "to bundle the full ComfyUI install."
        )
        scope_help.setStyleSheet(theme.HELP_TEXT_STYLE)
        scope_help.setWordWrap(True)
        v.addWidget(scope_help)
        v.addStretch()
        return page

    def _build_options_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)

        self._add_models_cb = QCheckBox("Include models")
        self._add_models_cb.setStyleSheet(_CHECKBOX_STYLE_PLUS2)
        self._add_models_cb.setToolTip(
            "Copy model files into the bundle. With workflow(s) selected only "
            "the referenced models are copied; otherwise the entire models/ "
            "folder is copied (can be very large)."
        )
        v.addWidget(self._add_models_cb)

        self._add_debugger_cb = QCheckBox("Include the ComfyUI Deployer tool")
        self._add_debugger_cb.setStyleSheet(_CHECKBOX_STYLE_PLUS2)
        self._add_debugger_cb.setToolTip(
            "Clone this tool into the bundle destination."
        )
        v.addWidget(self._add_debugger_cb)

        self._adv_settings_cb = QCheckBox(
            "Embed advanced settings (extra_model_paths.yaml, model/output/input)"
        )
        self._adv_settings_cb.setStyleSheet(_CHECKBOX_STYLE_PLUS2)
        self._adv_settings_cb.setToolTip(
            "Embed extra_model_paths.yaml and the advanced folder settings "
            "into the generated .bat."
        )
        v.addWidget(self._adv_settings_cb)

        self._include_workflows_cb = QCheckBox("Copy the workflow files into the bundle")
        self._include_workflows_cb.setStyleSheet(_CHECKBOX_STYLE_PLUS2)
        self._include_workflows_cb.setToolTip(
            "Copy the selected workflow files alongside the export. In a "
            "regular bundle they go into a 'workflows/' folder at the export "
            "root; in the sharable .bat they are embedded and extracted next "
            "to the .bat at install time."
        )
        v.addWidget(self._include_workflows_cb)

        self._bat_info = QLabel(
            "ⓘ ComfyUI Deployer is always included in a .bat."
        )
        self._bat_info.setStyleSheet(theme.HELP_TEXT_STYLE)
        self._bat_info.setWordWrap(True)
        v.addWidget(self._bat_info)

        v.addStretch()
        return page

    # ------------------------------------------------------------- Footer
    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        cancel_btn.setMinimumWidth(90)
        cancel_btn.setFixedHeight(34)
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)

        row.addStretch()

        self._back_btn = QPushButton("← Back")
        self._back_btn.setStyleSheet(theme.BROWSE_BUTTON_STYLE)
        self._back_btn.setMinimumWidth(90)
        self._back_btn.setFixedHeight(34)
        self._back_btn.clicked.connect(self._on_back)
        row.addWidget(self._back_btn)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setStyleSheet(theme.RUN_COMFY_BUTTON_STYLE)
        self._next_btn.setMinimumWidth(110)
        self._next_btn.setFixedHeight(34)
        self._next_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._next_btn.clicked.connect(self._on_next)
        row.addWidget(self._next_btn)
        return row

    # ------------------------------------------------------------- Helpers
    def _radio_subtitle(self, text: str) -> QWidget:
        wrap = QWidget()
        r = QHBoxLayout(wrap)
        r.setContentsMargins(24, 0, 0, 0)
        r.setSpacing(0)
        lbl = QLabel(text)
        lbl.setStyleSheet(theme.RADIO_SUBTITLE_STYLE)
        r.addWidget(lbl)
        r.addStretch()
        return wrap

    def _help_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(theme.HELP_TEXT_STYLE)
        lbl.setWordWrap(True)
        return lbl

    # ------------------------------------------------------------- Dynamic
    def _refresh_options_visibility(self):
        bat = self._bat_radio.isChecked()
        self._add_models_cb.setVisible(not bat)
        self._add_debugger_cb.setVisible(not bat)
        self._adv_settings_cb.setVisible(bat)
        self._bat_info.setVisible(bat)
        if bat:
            self._include_workflows_cb.setText("Embed the workflow files into the .bat")
        else:
            self._include_workflows_cb.setText("Copy the workflow files into the bundle")

    def _refresh_workflow_dependent_widgets(self):
        has_wf = bool(self._wf_paths)
        self._include_workflows_cb.setVisible(has_wf)
        self._wf_clear.setVisible(has_wf)

    # ------------------------------------------------------------- Navigation
    def _goto(self, index: int):
        self._pages.setCurrentIndex(index)
        self._dots_lbl.setText(self._render_dots(index))
        self._step_lbl.setText(f"STEP {index + 1} OF {_NUM_STEPS}")
        self._title_lbl.setText(_STEP_TITLES[index])
        self._back_btn.setEnabled(index > 0)
        last = index == _NUM_STEPS - 1
        self._next_btn.setText("Create" if last else "Next →")
        # When landing on Options, re-evaluate dynamic visibility (safe even
        # though the same hooks have already fired on widget changes).
        if last:
            self._refresh_options_visibility()
            self._refresh_workflow_dependent_widgets()
        self._update_next_enabled()

    def _update_next_enabled(self):
        idx = self._pages.currentIndex()
        if idx == 1:  # Destination is the only gating step
            self._next_btn.setEnabled(bool(self._dest_path))
        else:
            self._next_btn.setEnabled(True)

    def _on_next(self):
        idx = self._pages.currentIndex()
        if idx == _NUM_STEPS - 1:
            if self._dest_path:
                self.accept()
        else:
            self._goto(idx + 1)

    def _on_back(self):
        idx = self._pages.currentIndex()
        if idx > 0:
            self._goto(idx - 1)

    # ------------------------------------------------------------- Pickers
    def _pick_dest(self):
        path = QFileDialog.getExistingDirectory(self, "Select destination folder", os.path.expanduser("~"))
        if path:
            self._dest_path = os.path.normpath(path)
            self._dest_edit.setText(self._dest_path)
            self._update_next_enabled()

    def _pick_workflows(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select workflow files",
            os.path.expanduser("~"),
            "ComfyUI Workflows (*.json *.png *.webp *.jpg *.jpeg);;All Files (*)",
        )
        if paths:
            self._wf_paths = [os.path.normpath(p) for p in paths]
            self._wf_edit.setText("; ".join(os.path.basename(p) for p in self._wf_paths))
            # Helpful default: a scoped bundle should ship the (now small)
            # referenced models.
            self._add_models_cb.setChecked(True)
            self._refresh_workflow_dependent_widgets()

    def _clear_workflows(self):
        self._wf_paths = []
        self._wf_edit.setText("")
        self._include_workflows_cb.setChecked(False)
        # Reset the helpful default — without a scope, "Include models" copies
        # the whole models/ folder, which is rarely what the user wants.
        self._add_models_cb.setChecked(False)
        self._refresh_workflow_dependent_widgets()

    # ------------------------------------------------------------- Result
    def dest_path(self) -> str:
        return self._dest_path

    def workflow_paths(self) -> list[str]:
        return list(self._wf_paths)

    def include_debugger(self) -> bool:
        # The .bat always clones the Deployer (it runs the install step).
        if self._bat_radio.isChecked():
            return True
        return self._add_debugger_cb.isChecked()

    def include_models(self) -> bool:
        # Models are never embedded in a .bat.
        if self._bat_radio.isChecked():
            return False
        return self._add_models_cb.isChecked()

    def export_as_bat(self) -> bool:
        return self._bat_radio.isChecked()

    def export_advanced_settings(self) -> bool:
        return self._adv_settings_cb.isChecked()

    def include_workflows(self) -> bool:
        return bool(self._wf_paths) and self._include_workflows_cb.isChecked()

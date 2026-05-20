"""Reusable labelled path-picker row with Browse and Clear buttons."""

import os

from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from deployer.ui import theme


class PathPickerRow(QWidget):
    """A labelled row with a read-only path display, Browse and Clear buttons."""

    def __init__(
        self,
        label: str,
        help_text: str,
        pick_type: str = "file",
        current_path: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._pick_type = pick_type
        self._path = current_path

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(4)

        lbl = QLabel(label)
        lbl.setStyleSheet(theme.PATH_PICKER_LABEL_STYLE)
        outer.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(6)

        self.path_edit = QLineEdit(current_path)
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Not set")
        self.path_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        row.addWidget(self.path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(90)
        browse_btn.setStyleSheet(theme.BROWSE_BUTTON_STYLE)
        browse_btn.clicked.connect(self._pick)
        row.addWidget(browse_btn)

        self.clear_btn = QPushButton("✕")
        self.clear_btn.setFixedWidth(30)
        self.clear_btn.setEnabled(bool(current_path))
        self.clear_btn.setStyleSheet(theme.CLEAR_BUTTON_STYLE)
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.clear_btn)

        outer.addLayout(row)

        help_lbl = QLabel(help_text)
        help_lbl.setStyleSheet(theme.HELP_TEXT_STYLE)
        help_lbl.setWordWrap(True)
        outer.addWidget(help_lbl)

    def _pick(self):
        start_dir = self._path or os.path.expanduser("~")
        if self._pick_type == "file":
            path, _ = QFileDialog.getOpenFileName(
                self, "Select file", start_dir,
                "YAML Files (*.yaml *.yml);;All Files (*)",
            )
        else:
            path = QFileDialog.getExistingDirectory(self, "Select folder", start_dir)
        if path:
            self._path = os.path.normpath(path)
            self.path_edit.setText(self._path)
            self.clear_btn.setEnabled(True)

    def _clear(self):
        self._path = ""
        self.path_edit.setText("")
        self.clear_btn.setEnabled(False)

    @property
    def path(self) -> str:
        return self._path

"""Dialog for manually installing a Python package via uv pip."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from deployer.ui import theme


class InstallPackageDialog(QDialog):
    """Simple dialog to install a package by typing its spec (e.g. ``numpy==1.24.0``)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Install package")
        self.setMinimumWidth(440)
        self.setStyleSheet(theme.APP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Package spec (same syntax as uv pip install):"))
        self.spec_edit = QLineEdit()
        self.spec_edit.setPlaceholderText("e.g.  numpy==1.26.4  or  torch>=2.0")
        self.spec_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        layout.addWidget(self.spec_edit)

        hint = QLabel("You can include extras, version pins, or flags just as you would in a terminal.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        cancel_btn.setFixedSize(80, 34)
        cancel_btn.clicked.connect(self.reject)
        self.install_btn = QPushButton("Install")
        self.install_btn.setStyleSheet(theme.ADD_NODE_BUTTON_STYLE)
        self.install_btn.setFixedSize(80, 34)
        self.install_btn.clicked.connect(self._on_install)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.install_btn)
        layout.addLayout(btn_layout)

        self.spec_edit.textChanged.connect(self._validate)
        self.spec_edit.returnPressed.connect(self._on_install)
        self._validate()

    def _validate(self):
        self.install_btn.setEnabled(bool(self.spec_edit.text().strip()))

    def _on_install(self):
        if self.spec_edit.text().strip():
            self.accept()

    def package_spec(self) -> str:
        return self.spec_edit.text().strip()

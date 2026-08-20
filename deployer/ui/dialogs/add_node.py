"""Dialog for adding a new custom-node entry to the user's settings."""

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


class AddNodeDialog(QDialog):
    """Dialog to add a new custom node entry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Custom Node")
        self.setMinimumWidth(420)
        self.setStyleSheet(theme.APP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Git Repository URL:"))
        self.repo_edit = QLineEdit()
        self.repo_edit.setPlaceholderText("https://github.com/author/repo")
        self.repo_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        layout.addWidget(self.repo_edit)

        layout.addWidget(QLabel("Ref:"))
        self.ref_edit = QLineEdit("main")
        self.ref_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        layout.addWidget(self.ref_edit)

        layout.addWidget(QLabel("Description (optional):"))
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Short description of this node")
        self.desc_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        layout.addWidget(self.desc_edit)

        link_label = QLabel(
            f'<a href="https://ltdrdata.github.io/" style="color:{theme.LINK_ACCENT};">'
            "Browse available nodes on ComfyUI Registry</a>"
        )
        link_label.setOpenExternalLinks(True)
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(link_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        cancel_btn.setFixedSize(80, 34)
        cancel_btn.clicked.connect(self.reject)
        self.add_btn = QPushButton("Add")
        self.add_btn.setStyleSheet(theme.ADD_NODE_BUTTON_STYLE)
        self.add_btn.setFixedSize(80, 34)
        self.add_btn.clicked.connect(self._on_add)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.add_btn)
        layout.addLayout(btn_layout)

        self.repo_edit.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        self.add_btn.setEnabled(bool(self.repo_edit.text().strip()))

    def _on_add(self):
        if self.repo_edit.text().strip():
            self.accept()

    def values(self) -> tuple[str, str, str]:
        return (
            self.repo_edit.text().strip(),
            self.ref_edit.text().strip() or "main",
            self.desc_edit.text().strip(),
        )

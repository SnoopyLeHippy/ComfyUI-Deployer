"""Info dialog shown when a loaded configuration is missing locally tracked nodes."""

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from deployer.ui import theme


class MissingNodesDialog(QDialog):
    """Lists nodes tracked locally but absent from the loaded configuration."""

    def __init__(self, node_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nodes not in loaded configuration")
        self.setMinimumWidth(460)
        self.setStyleSheet(theme.APP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        msg = QLabel(
            "The following nodes are <b>not present</b> in the loaded configuration "
            "and have been marked <b>To remove</b>:"
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        node_list = QListWidget()
        node_list.setStyleSheet(theme.MISSING_NODES_LIST_STYLE)
        node_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for name in node_names:
            node_list.addItem(QListWidgetItem(name))
        layout.addWidget(node_list)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        ok_btn.setFixedSize(80, 34)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

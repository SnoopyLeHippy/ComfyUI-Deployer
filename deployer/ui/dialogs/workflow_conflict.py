"""Dialog to resolve ambiguous node-to-repo mappings found during workflow import."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from deployer.ui import theme


class WorkflowConflictDialog(QDialog):
    """Let the user choose which repo to install for each ambiguous node type.

    A *conflict* arises when 2+ repos in the ComfyUI-Manager DB all claim
    to provide the same node type and none of them are already tracked.
    """

    def __init__(self, conflicts, parent=None):
        """
        Parameters
        ----------
        conflicts : list[ConflictEntry]
            Each entry has ``.node_types`` (list[str]) and
            ``.repo_options`` (list[str]).
        """
        super().__init__(parent)
        self.setWindowTitle("Ambiguous node sources")
        self.setMinimumWidth(640)
        self.setMinimumHeight(280)
        self.setStyleSheet(theme.APP_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        intro = QLabel(
            "Multiple repositories provide the following node type(s).\n"
            "Choose which one to install, or leave at \"— Skip —\" to ignore."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.SUBTITLE_STYLE)
        root.addWidget(intro)

        # Scrollable conflict rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL_AREA_STYLE)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        rows_layout = QVBoxLayout(container)
        rows_layout.setContentsMargins(0, 4, 0, 4)
        rows_layout.setSpacing(8)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # Each item: (combo, node_types list)
        self._entries: list[tuple[QComboBox, list[str]]] = []

        for entry in conflicts:
            combo = self._add_row(rows_layout, entry)
            self._entries.append((combo, list(entry.node_types)))

        rows_layout.addStretch()

        # Button row
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        cancel_btn.setFixedSize(90, 34)
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Import")
        ok_btn.setStyleSheet(theme.RUN_COMFY_BUTTON_STYLE)
        ok_btn.setFixedSize(90, 34)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _add_row(layout: QVBoxLayout, entry) -> QComboBox:
        row = QWidget()
        row.setStyleSheet(
            f"QWidget {{ background: {theme.PALETTE['surface_input']}; "
            f"border-radius: 6px; border: 1px solid {theme.PALETTE['surface_border']}; }}"
        )
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.setSpacing(12)

        types_label = QLabel("\n".join(entry.node_types))
        types_label.setStyleSheet(
            f"QLabel {{ background: transparent; color: {theme.PALETTE['text_heading']}; "
            f"font-size: 12px; border: none; }}"
        )
        types_label.setWordWrap(True)
        types_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row_layout.addWidget(types_label, 1)

        combo = QComboBox()
        combo.setStyleSheet(
            f"QComboBox {{ background: {theme.PALETTE['surface_button']}; "
            f"color: {theme.PALETTE['text_primary']}; "
            f"border: 1px solid {theme.PALETTE['surface_neutral']}; "
            f"border-radius: 4px; padding: 4px 8px; font-size: 12px; min-width: 220px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background: {theme.PALETTE['surface_input']}; "
            f"  color: {theme.PALETTE['text_primary']}; "
            f"  selection-background-color: {theme.PALETTE['surface_button']}; }}"
        )

        combo.addItem("— Skip —", userData=None)
        for repo in entry.repo_options:
            name = os.path.basename(repo.rstrip("/").removesuffix(".git"))
            combo.addItem(name, userData=repo)
            combo.setItemData(combo.count() - 1, repo, Qt.ItemDataRole.ToolTipRole)

        row_layout.addWidget(combo)
        layout.addWidget(row)
        return combo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selections(self) -> list[tuple[str, list[str]]]:
        """Return ``[(repo_url, [node_types]), ...]`` for rows where a repo was chosen.

        Rows left at "— Skip —" are omitted.
        """
        result: list[tuple[str, list[str]]] = []
        for combo, node_types in self._entries:
            repo = combo.currentData()
            if repo is not None:
                result.append((repo, node_types))
        return result

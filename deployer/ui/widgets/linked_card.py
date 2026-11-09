"""Card for a linked node in custom_nodes: another program put it there and keeps it."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from deployer.ui import theme
from deployer.ui.widgets.base_card import BaseCard
from deployer.ui.widgets.card_state import CardState


class LinkedNodeCard(BaseCard):
    """Read-only card for a linked node (``orphans.UntrackedNodes.linked``).

    A junction, or a link folder (``linked-node.json``) whose code lives at
    *target*. Never selectable, no requirements checkbox: it cannot be added
    to the configuration — tracking it would let an install remove the link,
    and with it the program that linked itself into ComfyUI (MoodMiner's
    ``ComfyUI-MoodMiner``). Whoever made the link keeps it. The window pins it
    at the top of the grid.
    """

    _MAX_INFO = 70

    def __init__(self, name: str, target: str, parent=None):
        self.name = name
        self.target = target
        super().__init__(name, parent=parent)
        self.req_checkbox.hide()
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.setToolTip(f"Linked to {target or 'an unknown folder'}, managed outside "
                        "ComfyUI Deployer: it is never removed from here.")
        self.refresh()

    def _build_body(self, layout: QVBoxLayout) -> None:
        self.name_label.setStyleSheet(theme.ORPHAN_CARD_NAME_LABEL_STYLE)

        target = self.target or "?"
        if len(target) > self._MAX_INFO:
            target = "…" + target[-(self._MAX_INFO - 1):]
        target_label = QLabel(f"→ {target}")
        target_label.setStyleSheet(theme.ORPHAN_CARD_REPO_LABEL_STYLE)
        target_label.setWordWrap(True)
        target_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(target_label)

        note = QLabel("Managed outside the Deployer")
        note.setStyleSheet(theme.CARD_REF_LABEL_STYLE)
        note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(note)

    def _current_state(self) -> CardState:
        return CardState.LINKED

    def _can_toggle_selection(self) -> bool:
        return False

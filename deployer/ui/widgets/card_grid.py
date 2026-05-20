"""Responsive grid that flows fixed-size cards based on viewport width."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QGridLayout, QSizePolicy, QWidget


class ResponsiveCardGrid(QWidget):
    """Grid that reflows fixed-size cards based on available viewport width."""

    CARD_WIDTH = 320
    CARD_MAX_WIDTH = 400
    CARD_HEIGHT = 160
    CARD_SPACING = 15

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardGrid")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(self.CARD_SPACING)
        self._cards: list[QWidget] = []
        self._cols = 1
        self._add_btn: QWidget | None = None
        self._stretch_row: int = -1
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def add_card(self, card: QWidget):
        self._cards.append(card)
        self._relayout()

    def set_add_button(self, btn: QWidget):
        self._add_btn = btn
        self._relayout()

    def remove_card(self, card: QWidget):
        if card in self._cards:
            self._cards.remove(card)
            card.setParent(None)
            self._relayout()

    def update_cols(self, viewport_width: int):
        """Recompute columns from the viewport width and relayout if changed."""
        new_cols = max(1, (viewport_width + self.CARD_SPACING) // (self.CARD_WIDTH + self.CARD_SPACING))
        if new_cols != self._cols:
            self._cols = new_cols
            self._relayout()

    def _relayout(self):
        while self._grid.count():
            self._grid.takeAt(0)
        for c in range(self._grid.columnCount() + 1):
            self._grid.setColumnStretch(c, 0)
        for r in range(self._grid.rowCount() + 1):
            self._grid.setRowStretch(r, 0)
        if self._stretch_row >= 0:
            self._grid.setRowStretch(self._stretch_row, 0)
            self._stretch_row = -1
        all_items = list(self._cards)
        if self._add_btn is not None:
            all_items.append(self._add_btn)
        for i, item in enumerate(all_items):
            alignment = (
                Qt.AlignmentFlag.AlignLeft
                if item is self._add_btn
                else Qt.AlignmentFlag.AlignTop
            )
            self._grid.addWidget(item, i // self._cols, i % self._cols, alignment)
        for c in range(self._cols):
            self._grid.setColumnStretch(c, 1)
        if all_items:
            self._stretch_row = (len(all_items) - 1) // self._cols + 1
            self._grid.setRowStretch(self._stretch_row, 1)
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        total = len(self._cards) + (1 if self._add_btn else 0)
        if not total:
            return QSize(0, 0)
        num_rows = (total + self._cols - 1) // self._cols
        h = num_rows * self.CARD_HEIGHT + max(0, num_rows - 1) * self.CARD_SPACING
        return QSize(self._cols * (self.CARD_WIDTH + self.CARD_SPACING), h)

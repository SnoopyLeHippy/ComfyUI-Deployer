"""Circular '+' button shown at the end of the card grid."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QWidget

from deployer.ui import theme


class AddNodeButton(QWidget):
    """Circular '+' button shown at the end of the card grid."""

    SIZE = 100

    def __init__(self, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Add a new node")
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.SURFACE_NEUTRAL) if self._hovered else QColor(theme.SURFACE_BUTTON)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, self.SIZE - 4, self.SIZE - 4)
        font = QFont("Segoe UI", 36, QFont.Weight.Thin)
        painter.setFont(font)
        fm = QFontMetrics(font)
        text = "+"
        bounding = fm.boundingRect(text)
        x = (self.SIZE - bounding.width()) // 2 - bounding.x()
        y = (self.SIZE - bounding.height()) // 2 - bounding.y() - 4
        painter.setPen(QColor(theme.ICON_MUTED))
        painter.drawText(x, y, text)

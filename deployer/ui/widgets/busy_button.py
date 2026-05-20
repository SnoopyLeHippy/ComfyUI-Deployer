"""QPushButton that swaps its label for an animated spinner while busy."""

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QPushButton

from deployer.ui import theme


class BusyButton(QPushButton):
    """QPushButton that shows a rotating arc (replacing its text) when busy."""

    _INTERVAL_MS = 25  # ~40 fps
    _ARC_SPAN    = 270 * 16
    _STEP_DEG    = 8

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._busy        = False
        self._angle       = 0
        self._normal_text = text
        self._timer       = QTimer(self)
        self._timer.setInterval(self._INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    def set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        self._busy = busy
        if busy:
            self._angle = 0
            self.setText("")
            self._timer.start()
        else:
            self._timer.stop()
            self.setText(self._normal_text)
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle - self._STEP_DEG) % 360
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._busy:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.height() - 14
        x    = (self.width()  - size) // 2
        y    = (self.height() - size) // 2
        pen  = QPen(QColor(theme.TEXT_PRIMARY), 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRect(x, y, size, size), self._angle * 16, self._ARC_SPAN)
        painter.end()

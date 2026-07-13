"""Small rotating-arc spinner overlaid on a card while it awaits a refresh."""

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from deployer.ui import theme


class Spinner(QWidget):
    """Rotating arc, hidden by default — toggle with :meth:`set_active`."""

    _INTERVAL_MS = 25  # ~40 fps
    _ARC_SPAN    = 270 * 16
    _STEP_DEG    = 8
    _SIZE        = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_active(self, active: bool) -> None:
        if active == self._timer.isActive():
            return
        if active:
            self._angle = 0
            self.show()
            self.raise_()
            self._timer.start()
        else:
            self._timer.stop()
            self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle - self._STEP_DEG) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.TEXT_BODY), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRect(1, 1, self._SIZE - 2, self._SIZE - 2), self._angle * 16, self._ARC_SPAN)
        painter.end()

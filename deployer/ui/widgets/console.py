"""Read-only console panel that displays redirected stdout/stderr.

Lines are colourised on insertion: anything written to stderr, plus stdout
lines that look like errors or warnings, are shown in red so failures stand
out in the otherwise grey log.
"""

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

from deployer.ui import theme


# Substrings (matched case-insensitively) that mark a stdout line as a problem.
_ERROR_MARKERS = (
    "error", "failed", "exception", "traceback",
    "unresolved", "not found", "cannot", "could not",
    "warning",
)


def _looks_like_error(line: str) -> bool:
    low = line.lower()
    return any(marker in low for marker in _ERROR_MARKERS)


class ConsoleOutput(QWidget):
    """Read-only console panel that auto-scrolls while the user is at the bottom."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(theme.CONSOLE_PANEL_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)

        title_row = QWidget()
        title_row.setStyleSheet("background: transparent;")
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)

        title = QLabel("Console")
        title.setStyleSheet(theme.CONSOLE_TITLE_STYLE)

        title_line = QFrame()
        title_line.setFrameShape(QFrame.Shape.NoFrame)
        title_line.setFixedHeight(1)
        title_line.setStyleSheet(theme.CONSOLE_TITLE_LINE_STYLE)

        title_layout.addWidget(title)
        title_layout.addWidget(title_line, 1)
        layout.addWidget(title_row)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(theme.CONSOLE_OUTPUT_STYLE)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.text_edit)

        self._normal_color = QColor(theme.TEXT_BODY)
        self._error_color = QColor(theme.CONSOLE_ERROR)

        self._auto_scroll = True
        vbar = self.text_edit.verticalScrollBar()
        vbar.rangeChanged.connect(self._on_range_changed)
        vbar.valueChanged.connect(self._on_scroll_value_changed)

    @pyqtSlot(str, bool)
    def append_line(self, text: str, force_error: bool):
        """Append one line of output (queued from a worker thread).

        *force_error* is set for everything coming from stderr; stdout lines
        are classified by :func:`_looks_like_error`.
        """
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        is_error = force_error or _looks_like_error(text)
        fmt.setForeground(self._error_color if is_error else self._normal_color)
        cursor.insertText(text, fmt)

    def _on_scroll_value_changed(self, value: int):
        vbar = self.text_edit.verticalScrollBar()
        at_bottom = value >= vbar.maximum() - 4
        self._auto_scroll = at_bottom

    def _on_range_changed(self, _min: int, _max: int):
        if self._auto_scroll:
            self.text_edit.verticalScrollBar().setValue(_max)

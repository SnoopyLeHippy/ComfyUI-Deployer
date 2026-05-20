"""Forward writes from ``sys.stdout`` / ``sys.stderr`` to the console widget."""

import io

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt


class StdoutRedirector(io.TextIOBase):
    """File-like object that forwards complete lines to a :class:`ConsoleOutput`.

    Background threads (installs, the ComfyUI subprocess pump, workflow scans)
    freely ``print`` here. Writes are buffered until a newline so each line is
    classified and coloured as a whole, then dispatched to the widget on the
    GUI thread via a queued ``invokeMethod`` call (painting must stay on the
    main thread).

    *is_error* marks a stream whose every line should render as an error —
    used for ``sys.stderr`` so tracebacks show up red regardless of content.
    """

    def __init__(self, console, *, is_error: bool = False):
        super().__init__()
        self._console = console
        self._is_error = is_error
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while True:
            idx = self._buffer.find("\n")
            if idx == -1:
                break
            line, self._buffer = self._buffer[: idx + 1], self._buffer[idx + 1:]
            self._emit(line)
        return len(text)

    def _emit(self, line: str) -> None:
        QMetaObject.invokeMethod(
            self._console, "append_line",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, line),
            Q_ARG(bool, self._is_error),
        )

    def flush(self) -> None:
        # Flush any trailing partial line (e.g. a prompt with no newline).
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""

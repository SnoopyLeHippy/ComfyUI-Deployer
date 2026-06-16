"""Forward writes from ``sys.stdout`` / ``sys.stderr`` to the console widget."""

import io
import re
import threading
from typing import IO, Optional

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt


# ANSI escape sequences (colours, cursor moves, ...). ComfyUI and some custom
# nodes emit coloured output that the Qt console can't render, so it would show
# up as literal noise like "[32m[INFO][0m". Strip it before display/logging.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class StdoutRedirector(io.TextIOBase):
    """File-like object that forwards complete lines to a :class:`ConsoleOutput`.

    Background threads (installs, the ComfyUI subprocess pump, workflow scans)
    freely ``print`` here. Writes are buffered until a newline so each line is
    classified and coloured as a whole, then dispatched to the widget on the
    GUI thread via a queued ``invokeMethod`` call (painting must stay on the
    main thread).

    *is_error* marks a stream whose every line should render as an error —
    used for ``sys.stderr`` so tracebacks show up red regardless of content.

    *log_file* is an open text-mode file handle (shared across redirectors so
    stdout and stderr land in the same file). Each line is written there
    immediately and flushed so a hard crash still leaves the bytes on disk.
    Guarded by a class-level lock since both redirectors write to the same
    file from multiple threads.
    """

    _LOG_LOCK = threading.Lock()

    def __init__(
        self,
        console,
        *,
        is_error: bool = False,
        log_file: Optional[IO[str]] = None,
    ):
        super().__init__()
        self._console = console
        self._is_error = is_error
        self._buffer = ""
        self._log_file = log_file

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while True:
            idx = self._buffer.find("\n")
            if idx == -1:
                break
            line, self._buffer = self._buffer[: idx + 1], self._buffer[idx + 1:]
            line = _strip_ansi(line)
            self._emit(line)
            self._log(line)
        return len(text)

    def _emit(self, line: str) -> None:
        QMetaObject.invokeMethod(
            self._console, "append_line",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, line),
            Q_ARG(bool, self._is_error),
        )

    def _log(self, line: str) -> None:
        if self._log_file is None:
            return
        prefix = "[ERR] " if self._is_error else ""
        with self._LOG_LOCK:
            try:
                self._log_file.write(prefix + line)
                self._log_file.flush()
            except (OSError, ValueError):
                # File may have been closed during shutdown; swallow rather
                # than throw on the way out.
                pass

    def flush(self) -> None:
        # Flush any trailing partial line (e.g. a prompt with no newline).
        if self._buffer:
            line = _strip_ansi(self._buffer)
            self._emit(line)
            self._log(line)
            self._buffer = ""

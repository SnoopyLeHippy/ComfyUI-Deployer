"""Run an external command and stream its merged output line by line.

Centralises the reading loop shared by :mod:`deployer.core.git_ops` (git
progress bars) and by plugin UI actions (arbitrary user commands): the
``\r`` handling that turns a progress bar into readable console lines, the
decoding fallback, and the environment merge all live here rather than being
re-implemented per call site.

No Qt import — this is core logic, usable from the headless path.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Sequence


def stream_command(
    cmd: Sequence[str] | str,
    *,
    cwd: str | None = None,
    shell: bool = False,
    env: dict[str, str] | None = None,
    log: Callable[[str], None] | None = None,
) -> int:
    """Run *cmd* and forward its stdout+stderr as it comes, returning the exit code.

    Args:
        cmd:   Argument list, or a command string when *shell* is set.
        cwd:   Working directory (defaults to the current one).
        shell: Run through ``cmd.exe`` — required for shell builtins, ``.bat``
               files invoked by bare name, and redirections.
        env:   Extra environment variables, **merged over** ``os.environ``.
        log:   Line sink. Defaults to ``print`` (the UI redirects stdout to the
               console panel, so printing is what makes output visible there).

    stderr is merged into stdout so a tool that reports progress on stderr
    (git, pip) still shows up in order.
    """
    emit = log or (lambda line: print(line, flush=True))
    run_env = {**os.environ, **env} if env else None

    with subprocess.Popen(
        cmd,
        cwd=cwd,
        shell=shell,
        env=run_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge so progress written to stderr is caught
        bufsize=0,
    ) as proc:
        buf = b""
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            buf += chunk
            # Flush every complete segment delimited by \r\n, \n, or \r
            while buf:
                for sep in (b"\r\n", b"\n", b"\r"):
                    pos = buf.find(sep)
                    if pos != -1:
                        line = buf[:pos].decode("utf-8", errors="replace").rstrip()
                        if line:
                            emit(line)
                        buf = buf[pos + len(sep):]
                        break
                else:
                    break  # no separator found yet — wait for more data
        if buf:
            line = buf.decode("utf-8", errors="replace").rstrip()
            if line:
                emit(line)

    return proc.returncode

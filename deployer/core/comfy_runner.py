"""Lifecycle management for the ComfyUI subprocess.

Exposed as a tiny class so the UI doesn't have to know about ``Popen``,
threads, or stdout pumping. Output goes through ``print``, which the UI
redirects to its console widget.
"""

import os
import subprocess
import threading
from typing import Callable

from deployer.config import COMFYUI_DIR, PORTABLE_DIR, PYTHON_EXE


_Callback = Callable[[], None]


class ComfyRunner:
    """Start, stop, and monitor a ComfyUI subprocess."""

    def __init__(
        self,
        *,
        on_started: _Callback | None = None,
        on_stopped: _Callback | None = None,
    ):
        self._on_started: _Callback = on_started or (lambda: None)
        self._on_stopped: _Callback = on_stopped or (lambda: None)
        self._proc: subprocess.Popen | None = None

    def is_running(self) -> bool:
        """Return ``True`` while the ComfyUI process is alive."""
        return self._proc is not None and self._proc.poll() is None

    def toggle(self) -> None:
        """Kill the process if running, otherwise launch it in a worker thread."""
        if self.is_running():
            assert self._proc is not None
            self._proc.kill()
            return
        self._proc = None
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        """Kill the process if it is running. No-op otherwise."""
        if self.is_running():
            assert self._proc is not None
            self._proc.kill()

    # -- internals ----------------------------------------------------------

    def _run(self) -> None:
        main_py = os.path.join(COMFYUI_DIR, "main.py")
        cmd = [PYTHON_EXE, "-s", main_py, "--windows-standalone-build"]
        print(f"Starting ComfyUI: {' '.join(cmd)}")
        # Force the child's stdout/stderr to UTF-8. When ComfyUI's output is
        # redirected to our pipe (not a real console), Python otherwise picks
        # the Windows locale codec (cp1252), which crashes on the emoji some
        # custom nodes (e.g. rgthree-comfy) print at startup.
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=PORTABLE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            self._on_started()
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                print(line, end="")
            self._proc.wait()
            print(f"ComfyUI exited (code {self._proc.returncode}).")
        except Exception as exc:
            print(f"Failed to start ComfyUI: {exc}")
        finally:
            self._on_stopped()

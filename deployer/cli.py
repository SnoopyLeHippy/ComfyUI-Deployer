"""Command line of the Deployer — the same jobs as the window, without one.

Run through the ``cli.py`` launcher at the project root (the embedded python
ignores the working directory, so ``python -m deployer.cli`` can't find the
package)::

    python -s cli.py install-nodes [--portable DIR]
    python -s cli.py install-deps
    python -s cli.py gui [--portable DIR]

``--portable`` points the Deployer at another ComfyUI portable folder (the one
holding ``ComfyUI\\`` and ``python_embeded\\``); default: ``DEPLOYER_PORTABLE_DIR``,
else the project's own ``ComfyUI_windows_portable``. It is turned into that
environment variable **before** :mod:`deployer.config` is first imported, which
is why this module imports nothing from the package at the top.

Output of ``install-nodes`` / ``install-deps``: stdout carries **only** JSON
lines — ``{"message", "progress": 0..1}``, ``{"warning"}``, then one
``{"result"}`` — for a caller to relay. Everything else (git, pip, this
package's prints, and what child processes write to the stdout they inherit)
goes to stderr; on failure its last line says why. Exit codes: 0 done, 1 the
job failed (``install-nodes``: a listed node is still missing), 2 usage error or
not a ComfyUI portable folder.

No Qt outside ``gui``; no shell, no PowerShell, no ``.bat`` anywhere here —
only ``git`` and ``python -m uv|pip``, with direct argument lists.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import sys

from deployer import PORTABLE_DIR_ENV


#: (import name, pip package) the window needs on top of the standard library;
#: what ``Launch.bat`` installs.
DEPLOYER_PACKAGES = (("PyQt6", "PyQt6"), ("yaml", "pyyaml"), ("uv", "uv"))


class EventChannel:
    """JSON events on the real stdout; the process's stdout is moved to stderr.

    Duplicates file descriptor 1 for the events, then points descriptor 1 (and
    ``sys.stdout``) at stderr, so free text — this package's prints, and child
    processes inheriting the stdout handle (``git checkout`` writes there) —
    can't corrupt the JSON stream.
    """

    def __init__(self) -> None:
        sys.stdout.flush()
        self._stream = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
        os.dup2(2, 1)
        sys.stdout = sys.stderr

    def emit(self, **payload) -> None:
        self._stream.write(json.dumps(payload) + "\n")
        self._stream.flush()

    def message(self, text: str, progress: float | None = None) -> None:
        if progress is None:
            self.emit(message=text)
        else:
            self.emit(message=text, progress=round(max(0.0, min(1.0, progress)), 3))

    def warning(self, text: str) -> None:
        self.emit(warning=text)

    def result(self, value: dict) -> None:
        self.emit(result=value)


class UsageError(Exception):
    """Bad arguments or environment: exit code 2."""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _require_portable() -> None:
    """Refuse a portable folder without ``ComfyUI\\`` or ``python_embeded\\python.exe``."""
    from deployer import config

    if not os.path.isdir(config.COMFYUI_DIR) or not os.path.isfile(config.PYTHON_EXE):
        raise UsageError(
            f"{config.PORTABLE_DIR} is not a ComfyUI portable folder "
            "(expected ComfyUI\\ and python_embeded\\python.exe inside)."
        )


def install_nodes(channel: EventChannel) -> int:
    """Clone the configured nodes missing from ComfyUI and install their requirements."""
    _require_portable()
    from deployer.core.installer import install_configured_nodes

    report = install_configured_nodes(progress=channel.message, warn=channel.warning)
    channel.result(report.as_dict())
    if report.failed:
        names = ", ".join(entry["name"] for entry in report.failed)
        print(f"Not installed: {names}.", file=sys.stderr, flush=True)
        return 1
    return 0


def install_deps(channel: EventChannel) -> int:
    """Install the Deployer's own packages into the interpreter running it, if missing."""
    from deployer.core.pip_runner import run_command

    def missing() -> list[str]:
        importlib.invalidate_caches()
        return [package for module, package in DEPLOYER_PACKAGES if importlib.util.find_spec(module) is None]

    to_install = missing()
    if to_install:
        channel.message(f"Installing {', '.join(to_install)}...", 0.0)
        code = run_command([sys.executable, "-m", "pip", "install", *to_install], stream_output=True)
        still_missing = missing()
        if code != 0 or still_missing:
            channel.result({"installed": [p for p in to_install if p not in still_missing], "missing": still_missing})
            print(f"pip could not install {', '.join(still_missing) or 'the packages'} (exit code {code}).",
                  file=sys.stderr, flush=True)
            return 1
        channel.message("Dependencies installed.", 1.0)
    channel.result({"installed": to_install, "missing": []})
    return 0


def gui() -> int:
    """Open the window on the selected portable (blocks until it closes)."""
    _require_portable()
    try:
        from deployer.ui import run
    except ImportError as exc:
        print(f"The window cannot start ({exc}); run 'cli.py install-deps' first.", file=sys.stderr)
        return 1
    run()  # sys.exit()s with the Qt event loop's code
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    portable = argparse.ArgumentParser(add_help=False)
    portable.add_argument(
        "--portable",
        metavar="DIR",
        help="ComfyUI portable folder to work on (default: $%s, else ComfyUI_windows_portable)" % PORTABLE_DIR_ENV,
    )
    parser = argparse.ArgumentParser(prog="cli.py", description="ComfyUI Deployer without its window.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "install-nodes", parents=[portable],
        help="clone the configured custom nodes missing from ComfyUI, then install their requirements",
    )
    commands.add_parser("install-deps", help="install the Deployer's own packages (PyQt6, pyyaml, uv) if missing")
    commands.add_parser("gui", parents=[portable], help="open the Deployer's window on that ComfyUI")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    portable = getattr(args, "portable", None)
    if portable:
        if "deployer.config" in sys.modules:
            raise RuntimeError("deployer.config was imported before --portable could be applied")
        os.environ[PORTABLE_DIR_ENV] = os.path.abspath(portable)
    # No console here: a credential prompt would wait forever (a credential
    # manager's own window still shows).
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")

    try:
        if args.command == "gui":
            return gui()
        channel = EventChannel()
        if args.command == "install-nodes":
            return install_nodes(channel)
        return install_deps(channel)
    except UsageError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 2

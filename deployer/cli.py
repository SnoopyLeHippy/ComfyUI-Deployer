"""Command line of the Deployer — the same jobs as the window, without one.

Run through the ``cli.py`` launcher at the project root (the embedded python
ignores the working directory, so ``python -m deployer.cli`` can't find the
package)::

    python -s cli.py install-nodes [--portable DIR] [--nodes-file FILE]
    python -s cli.py install-nodes [--portable DIR] [--repo URL]… [--update URL]… [--repair URL]…
    python -s cli.py resolve-nodes [--portable DIR] (--workflow FILE | --types JSON | --types-file FILE)
                                   [--object-info FILE | --comfy-url URL] [--all-nodes]
                                   [--refresh-db] [--no-registry]
    python -s cli.py install-deps
    python -s cli.py gui [--portable DIR]

``resolve-nodes`` installs nothing: its ``result`` is
:meth:`deployer.core.node_resolution.Resolution.as_dict` — the packs to
``install`` / ``update`` / ``repair``, the ``ambiguous`` types (with their
options), ``core`` (update ComfyUI), ``blocked`` and ``unknown``. The caller
picks, then runs ``install-nodes --repo / --update / --repair`` with them.

``--portable`` points the Deployer at another ComfyUI portable folder (the one
holding ``ComfyUI\\`` and ``python_embeded\\``); default: ``DEPLOYER_PORTABLE_DIR``,
else the project's own ``ComfyUI_windows_portable``. It is turned into that
environment variable **before** :mod:`deployer.config` is first imported, which
is why this module imports nothing from the package at the top.

``--nodes-file`` is an installer's own node list (``[{"repo", "ref"?,
"description"?}]``, or ``{"nodes": [...]}``): the tracked list on a fresh clone
— instead of ``custom_nodes.json`` — and added to an existing one
(``installer.add_listed_nodes``). A file that cannot be read, or that lists no
node, is a usage error.

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


def _read_nodes_file(path: str) -> list[dict]:
    """The entries of ``--nodes-file``; unreadable or empty is a usage error."""
    from deployer.core.installer import read_node_list

    try:
        entries = read_node_list(path)
    except (OSError, ValueError) as exc:
        raise UsageError(f"{path} cannot be read as a node list: {exc}") from exc
    if not entries:
        raise UsageError(f"{path} lists no custom node (an entry needs a \"repo\").")
    return entries


def install_nodes(channel: EventChannel, nodes_file: str | None = None, *, install: list[str] = (),
                  update: list[str] = (), repair: list[str] = ()) -> int:
    """Clone the configured nodes missing from ComfyUI and install their requirements.

    *nodes_file* (``--nodes-file``) goes into the configured list first. With
    *install* / *update* / *repair* (``--repo`` / ``--update`` / ``--repair``),
    only those packs (:func:`installer.install_selected_nodes`).
    """
    _require_portable()
    from deployer.core.installer import install_configured_nodes, install_selected_nodes

    if install or update or repair:
        if nodes_file is not None:
            raise UsageError("--nodes-file cannot be combined with --repo / --update / --repair.")
        for repo in [*install, *update, *repair]:
            if not _is_repo_url(repo):
                raise UsageError(f"{repo!r} is not a git repository URL (https://… or git@…).")
        report = install_selected_nodes(install, update, repair, progress=channel.message,
                                        warn=channel.warning)
    else:
        listed = _read_nodes_file(nodes_file) if nodes_file is not None else None
        report = install_configured_nodes(progress=channel.message, warn=channel.warning, listed=listed)
    channel.result(report.as_dict())
    if report.failed:
        names = ", ".join(entry["name"] for entry in report.failed)
        print(f"Not installed: {names}.", file=sys.stderr, flush=True)
        return 1
    return 0


def _is_repo_url(value: str) -> bool:
    value = value.strip()
    if value.startswith("-"):
        return False  # never an option git would parse
    return value.startswith(("https://", "http://", "git@")) or os.path.isabs(value)


def _read_json_file(path: str, what: str):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise UsageError(f"{path} cannot be read as {what}: {exc}") from exc


def resolve_nodes(channel: EventChannel, *, workflow: str | None, types: str | None,
                  types_file: str | None, object_info_file: str | None, comfy_url: str | None,
                  all_nodes: bool, refresh_db: bool, no_registry: bool) -> int:
    """Which packs the workflow (or the listed types) still needs here — nothing is installed."""
    _require_portable()
    from deployer.core.node_resolution import wanted_from_list, wanted_from_workflow
    from deployer.core.workflow_io import load_workflow_graph
    from deployer.core.workflow_resolver import fetch_object_info, resolve_nodes as resolve

    sources = [s for s in (workflow, types, types_file) if s is not None]
    if len(sources) != 1:
        raise UsageError("give exactly one of --workflow, --types, --types-file.")
    if object_info_file is not None and comfy_url is not None:
        raise UsageError("give --object-info or --comfy-url, not both.")

    if workflow is not None:
        try:
            graph = load_workflow_graph(workflow)
        except (OSError, ValueError) as exc:
            raise UsageError(f"{workflow} cannot be read as a workflow: {exc}") from exc
        wanted = wanted_from_workflow(graph, executable_only=not all_nodes)
    else:
        if types is not None:
            try:
                items = json.loads(types)
            except ValueError as exc:
                raise UsageError(f"--types is not JSON: {exc}") from exc
        else:
            items = _read_json_file(types_file, "a node type list")
        if not isinstance(items, list):
            raise UsageError("the node types must be a JSON list.")
        wanted = wanted_from_list(items)

    object_info = None
    if object_info_file is not None:
        object_info = _read_json_file(object_info_file, "an /object_info answer")
        if not isinstance(object_info, dict):
            raise UsageError(f"{object_info_file} holds no /object_info object.")
    elif comfy_url is not None:
        channel.message("Reading the node types ComfyUI loaded...", 0.1)
        try:
            object_info = fetch_object_info(comfy_url)
        except Exception as exc:  # noqa: BLE001 - static scan instead
            channel.warning(f"ComfyUI's /object_info cannot be read at {comfy_url} ({exc}); "
                            "using a scan of the sources instead.")

    channel.message("Resolving the node types...", 0.3)
    result = resolve(wanted, object_info=object_info, refresh_db=refresh_db,
                     use_registry=not no_registry, warn=channel.warning)
    channel.message("Node types resolved.", 1.0)
    channel.result(result.as_dict())
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
    install = commands.add_parser(
        "install-nodes", parents=[portable],
        help="clone the configured custom nodes missing from ComfyUI, then install their requirements",
    )
    install.add_argument(
        "--nodes-file",
        metavar="FILE",
        help="a JSON node list: the list on a fresh clone (instead of custom_nodes.json), "
             "added to the existing list otherwise",
    )
    for flag, what in (("--repo", "clone this pack when absent"),
                       ("--update", "fast-forward this pack's clone"),
                       ("--repair", "reinstall this pack's requirements")):
        install.add_argument(flag, metavar="URL", action="append", default=[],
                             help=f"{what} (repeatable); only the packs given are touched")
    resolve = commands.add_parser(
        "resolve-nodes", parents=[portable],
        help="which custom node packs a workflow still needs on that ComfyUI (installs nothing)",
    )
    resolve.add_argument("--workflow", metavar="FILE", help="a workflow .json, or an image embedding one")
    resolve.add_argument("--types", metavar="JSON",
                         help='node types: ["Type", …] or [{"type", "cnr_id"?, "aux_id"?, "ver"?}, …]')
    resolve.add_argument("--types-file", metavar="FILE", help="the same list, in a file")
    resolve.add_argument("--object-info", metavar="FILE", dest="object_info",
                         help="ComfyUI's /object_info answer, saved: what it loaded")
    resolve.add_argument("--comfy-url", metavar="URL", help="read /object_info from this running ComfyUI")
    resolve.add_argument("--all-nodes", action="store_true",
                         help="count muted and bypassed nodes too (what loading it in ComfyUI needs)")
    resolve.add_argument("--refresh-db", action="store_true", help="download the node database even if cached")
    resolve.add_argument("--no-registry", action="store_true", help="never ask the Comfy registry")
    commands.add_parser("install-deps", help="install the Deployer's own packages (PyQt6, pyyaml, uv) if missing")
    commands.add_parser("gui", parents=[portable], help="open the Deployer's window on that ComfyUI")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Free text goes out as UTF-8 whatever the console's code page: a caller
    # reading a pipe on Windows otherwise got cp1252 ("…" as 0x85) and failed
    # to decode it.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
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
            return install_nodes(channel, args.nodes_file, install=args.repo, update=args.update,
                                 repair=args.repair)
        if args.command == "resolve-nodes":
            return resolve_nodes(
                channel, workflow=args.workflow, types=args.types, types_file=args.types_file,
                object_info_file=args.object_info, comfy_url=args.comfy_url, all_nodes=args.all_nodes,
                refresh_db=args.refresh_db, no_registry=args.no_registry,
            )
        return install_deps(channel)
    except UsageError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 2

"""Shared test setup: import path, a throwaway ComfyUI portable, git and process helpers.

Import it **first** in every test module: it points ``DEPLOYER_PORTABLE_DIR`` at a
temporary fake portable before anything imports ``deployer.config`` (which reads
it once, at import), so no test can touch a real ComfyUI. The fake portable has
``ComfyUI/custom_nodes/`` and an empty ``python_embeded/python.exe``: nothing may
run it — :class:`ProcessSpy` stands in for it.
"""

import atexit
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    # The embedded python puts ComfyUI/ first on sys.path and ignores the script's folder.
    sys.path.insert(0, REPO_ROOT)

from deployer import PORTABLE_DIR_ENV  # noqa: E402  (the package root imports nothing else)

assert "deployer.config" not in sys.modules, "import _support before any deployer module"


def rmtree(path: str) -> None:
    """``shutil.rmtree`` that also removes git's read-only object files."""

    def _writable_retry(func, failed_path, _exc):
        os.chmod(failed_path, stat.S_IWRITE)
        func(failed_path)

    if os.path.exists(path):
        shutil.rmtree(path, onexc=_writable_retry)


SANDBOX = tempfile.mkdtemp(prefix="deployer-tests-")
atexit.register(rmtree, SANDBOX)


def make_portable(root: str) -> str:
    """Create the bare shape of a ComfyUI portable folder under *root*."""
    os.makedirs(os.path.join(root, "ComfyUI", "custom_nodes"), exist_ok=True)
    os.makedirs(os.path.join(root, "python_embeded"), exist_ok=True)
    open(os.path.join(root, "python_embeded", "python.exe"), "wb").close()
    return root


PORTABLE_DIR = make_portable(os.path.join(SANDBOX, "portable"))
os.environ[PORTABLE_DIR_ENV] = PORTABLE_DIR


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

_GIT_IDENTITY = [
    "-c", "user.name=Deployer Tests",
    "-c", "user.email=tests@example.invalid",
    "-c", "commit.gpgsign=false",
    "-c", "tag.gpgsign=false",
]


def git(*args: str, cwd: str) -> str:
    """Run git in *cwd* and return its stripped stdout; raises on failure."""
    return subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: str, files: dict[str, str], message: str = "change") -> str:
    """Write *files* (relative path → content) into *repo*, commit, return the commit hash."""
    for relative, content in files.items():
        path = os.path.join(repo, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", message, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def make_repo(path: str, files: dict[str, str] | None = None, *, branch: str = "main") -> str:
    """Create a git repository at *path* with one commit on *branch*; return *path*."""
    os.makedirs(path)
    git("init", "-q", "-b", branch, cwd=path)
    commit(path, files or {"__init__.py": ""}, "first")
    return path


def head(path: str) -> str:
    return git("rev-parse", "HEAD", cwd=path)


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

#: Programs that mean a shell or a script host: the headless path must never start them.
SHELL_PROGRAMS = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}


class ProcessSpy:
    """Record every process started; stand in for the given python executables.

    Patches ``subprocess.Popen`` (``subprocess.run`` goes through it). Anything
    whose program is one of *fake* is replaced by the test interpreter exiting
    with ``exit_code(argv)`` (default 0); everything else — git — really runs.
    """

    def __init__(self, fake: list[str], exit_code=lambda argv: 0) -> None:
        self.fake = {os.path.normcase(os.path.abspath(path)) for path in fake}
        self.exit_code = exit_code
        self.calls: list[dict] = []

    def __enter__(self) -> "ProcessSpy":
        spy = self
        real = subprocess.Popen

        class SpyPopen(real):
            def __init__(self, args, *pargs, **kwargs):
                argv = args if isinstance(args, str) else [str(part) for part in args]
                spy.calls.append({"argv": argv, "shell": bool(kwargs.get("shell")), "cwd": kwargs.get("cwd")})
                if not isinstance(argv, str) and argv and spy._is_fake(argv[0]):
                    args = [sys.executable, "-c", f"import sys; sys.exit({int(spy.exit_code(argv))})"]
                super().__init__(args, *pargs, **kwargs)

        self._patch = mock.patch.object(subprocess, "Popen", SpyPopen)
        self._patch.start()
        return self

    def __exit__(self, *exc) -> None:
        self._patch.stop()

    def _is_fake(self, program: str) -> bool:
        return os.path.normcase(os.path.abspath(program)) in self.fake

    def faked(self) -> list[list[str]]:
        """argv of the calls that went to a faked program."""
        return [call["argv"] for call in self.calls if not isinstance(call["argv"], str) and self._is_fake(call["argv"][0])]

    def assert_no_shell(self, test: unittest.TestCase) -> None:
        """Every process got a direct argument list, and none is a shell or a script."""
        for call in self.calls:
            argv = call["argv"]
            test.assertFalse(call["shell"], f"shell=True: {argv}")
            test.assertIsInstance(argv, list, f"command string: {argv}")
            program = os.path.basename(argv[0]).lower()
            test.assertNotIn(program, SHELL_PROGRAMS, f"shell started: {argv}")
            test.assertFalse(program.endswith((".bat", ".cmd", ".ps1")), f"script started: {argv}")


# ---------------------------------------------------------------------------
# A sandboxed node list
# ---------------------------------------------------------------------------

class SandboxTestCase(unittest.TestCase):
    """Empty ``custom_nodes/``, and a node list of the test's own.

    ``user_settings.json`` and ``custom_nodes.json`` move to a per-test folder
    (never the project's real ones), the legacy GitLab manifest and the
    insightface wheel point nowhere, and ``self.repos`` is a folder to create
    source repositories in.
    """

    def setUp(self) -> None:
        from deployer import config
        from deployer.core import installer, pip_runner
        from deployer.settings import UserSettings

        self.custom_nodes = config.CUSTOM_NODES_DIR
        rmtree(self.custom_nodes)
        os.makedirs(self.custom_nodes)

        self.work = tempfile.mkdtemp(dir=SANDBOX)
        self.repos = os.path.join(self.work, "repos")
        os.makedirs(self.repos)
        self.settings_path = os.path.join(self.work, "user_settings.json")
        self.manifest_path = os.path.join(self.work, "custom_nodes.json")
        nowhere = os.path.join(self.work, "missing")
        for patch in (
            mock.patch.object(UserSettings, "PATH", self.settings_path),
            mock.patch.object(installer, "LOCAL_NODES_JSON", self.manifest_path),
            mock.patch.object(installer, "SOURCE_NODES_JSON", os.path.join(nowhere, "custom_nodes.json")),
            mock.patch.object(installer, "INSIGHTFACE_WHL", os.path.join(nowhere, "insightface.whl")),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        pip_runner.uv_available.cache_clear()
        self.addCleanup(pip_runner.uv_available.cache_clear)

    def node_path(self, name: str) -> str:
        return os.path.join(self.custom_nodes, name)

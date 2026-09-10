"""Thin wrappers around the git CLI.

Centralising these calls keeps every git invocation in one place: timeout
defaults, error swallowing, encoding, and ``check`` semantics live here
rather than being scattered across the data model and the UI layer.
"""

import os
import subprocess
import sys

from deployer.core.command_runner import stream_command


_DEFAULT_TIMEOUT = 5  # seconds, for read-only git queries


def _stream_cmd(cmd: list, cwd: str, check: bool = True) -> None:
    """Run *cmd* and forward merged stdout+stderr to sys.stdout in real-time.

    Delegates the reading loop to :func:`deployer.core.command_runner.stream_command`
    (which splits on carriage returns too, so git progress bars each land on
    their own console line); only the ``check`` semantics are added on top.
    """
    returncode = stream_command(cmd, cwd=cwd)
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)


def clone(url: str, dest: str, cwd: str, *, recursive: bool = True, check: bool = True) -> None:
    """Run ``git clone --progress [--recursive] <url> <dest>`` from *cwd*."""
    cmd = ["git", "clone", "--progress"]
    if recursive:
        cmd.append("--recursive")
    cmd.extend([url, dest])
    _stream_cmd(cmd, cwd=cwd, check=check)


def checkout(ref: str, cwd: str, *, check: bool = True) -> None:
    """Run ``git checkout <ref>`` inside *cwd*."""
    subprocess.run(["git", "checkout", ref], cwd=cwd, check=check)


def rev_parse(ref: str, cwd: str) -> str:
    """Return the resolved commit hash for *ref* in *cwd*. Raises on error."""
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def get_remote_url(cwd: str) -> str:
    """Return the ``origin`` remote URL, or ``""`` if it can't be read."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            check=False,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def get_current_tag(cwd: str) -> str:
    """Return the exact tag name pointing at HEAD, or ``""`` if there is none."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            check=False,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def get_current_branch(cwd: str) -> str:
    """Return the current branch name, ``"HEAD"`` for detached, or ``""`` on error."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            check=False,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def get_short_commit(cwd: str) -> str:
    """Return the short HEAD commit hash, or ``""`` if it can't be read."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            check=False,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def is_dirty(cwd: str) -> bool:
    """Return ``True`` if the working tree in *cwd* has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            check=False,
        )
    except Exception:
        return False
    return bool(result.stdout.strip())


def is_repo_root(cwd: str) -> bool:
    """Return ``True`` if *cwd* is the top level of its own git repository.

    git looks for a repository in the parent directories too, so inside a
    folder that isn't a clone itself (or whose ``.git`` is broken) every
    command silently acts on the enclosing repo — for a custom node, that is
    ComfyUI's own checkout. Guard anything destructive with this. A junction
    passes whether git reports its own path or its target's.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            timeout=_DEFAULT_TIMEOUT,
            check=False,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    toplevel = os.path.normcase(os.path.normpath(result.stdout.strip()))
    candidates = (os.path.abspath(cwd), os.path.realpath(cwd))
    return toplevel in {os.path.normcase(os.path.normpath(path)) for path in candidates}


def list_changes(cwd: str) -> list[tuple[str, str]]:
    """Return ``(status, path)`` for each uncommitted change in *cwd*.

    *status* is the two-letter ``git status --porcelain`` code, ``"??"`` for
    an untracked entry (a wholly untracked directory is a single ``dir/``
    entry). Gitignored files are not listed. Raises on error, so a failure
    can't pass for a clean tree.
    """
    output = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_DEFAULT_TIMEOUT,
        check=True,
    ).stdout
    # No strip(): the status column may start with a space (" M file").
    return [(line[:2], line[3:]) for line in output.splitlines() if line]


def fetch(cwd: str, *, timeout: int = 30) -> bool:
    """Run ``git fetch`` in *cwd* to refresh remote-tracking refs.

    Returns ``True`` on success, ``False`` on any error or timeout. Touches
    the network, so call this off the UI thread.
    """
    try:
        result = subprocess.run(
            ["git", "fetch", "--quiet"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def is_behind_upstream(cwd: str) -> bool:
    """Return ``True`` if HEAD is behind its upstream branch (commits to pull).

    Counts commits reachable from ``@{upstream}`` but not from ``HEAD``. Run
    :func:`fetch` first so the comparison reflects the remote. Returns
    ``False`` when there is no upstream tracking branch, HEAD is detached, or
    git errors out — so a transient failure never spuriously flags a node.
    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..@{upstream}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            check=False,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    count = result.stdout.strip()
    return count.isdigit() and int(count) > 0


def pull(cwd: str, *, check: bool = True) -> None:
    """Run ``git pull`` inside *cwd*, streaming output."""
    _stream_cmd(["git", "pull"], cwd=cwd, check=check)


def discard_changes(cwd: str, *, remove_untracked: bool = False) -> None:
    """Throw away the uncommitted changes in *cwd*, streaming git's output.

    Resets tracked files, staged or not, to ``HEAD`` (which itself doesn't
    move); with *remove_untracked*, also deletes untracked files and
    directories — gitignored ones are kept. Raises ``ValueError`` unless
    *cwd* is a repository root (see :func:`is_repo_root`): run from anywhere
    else, ``reset --hard`` would wipe the enclosing repo.
    """
    if not is_repo_root(cwd):
        raise ValueError(f"{cwd} is not the root of a git repository")
    _stream_cmd(["git", "reset", "--hard", "HEAD"], cwd=cwd)
    if remove_untracked:
        _stream_cmd(["git", "clean", "-fd"], cwd=cwd)


def describe_head(cwd: str, *, fallback: str = "HEAD") -> str:
    """Return the most descriptive label for HEAD (tag, then branch, then *fallback*)."""
    return get_current_tag(cwd) or get_current_branch(cwd) or fallback

"""Thin wrappers around the git CLI.

Centralising these calls keeps every git invocation in one place: timeout
defaults, error swallowing, encoding, and ``check`` semantics live here
rather than being scattered across the data model and the UI layer.
"""

import subprocess
import sys


_DEFAULT_TIMEOUT = 5  # seconds, for read-only git queries


def _stream_cmd(cmd: list, cwd: str, check: bool = True) -> None:
    """Run *cmd* and forward merged stdout+stderr to sys.stdout in real-time.

    Handles both \\n and \\r line endings so git progress bars ("Receiving
    objects: 34%\\r") each print as a separate line in the console widget.
    """
    with subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge so we catch git's progress on stderr
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
                            print(line, flush=True)
                        buf = buf[pos + len(sep):]
                        break
                else:
                    break  # no separator found yet — wait for more data
        if buf:
            line = buf.decode("utf-8", errors="replace").rstrip()
            if line:
                print(line, flush=True)

    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


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


def describe_head(cwd: str, *, fallback: str = "HEAD") -> str:
    """Return the most descriptive label for HEAD (tag, then branch, then *fallback*)."""
    return get_current_tag(cwd) or get_current_branch(cwd) or fallback

"""Pip / uv installation helpers.

Prefers ``uv`` when available — installing every requirements file in a single
resolver pass so conflicts are detected once and shared dependencies aren't
re-downloaded between nodes. Falls back to plain pip when uv isn't installed,
and to per-file installation when the grouped pass fails.
"""

import functools
import os
import subprocess


def find_requirement_files(base: str, max_depth: int) -> list[str]:
    """Return every ``requirements.txt`` under *base* up to *max_depth* levels.

    Depth 0 == *base* itself; depth 1 == its direct subdirectories. Pruning is
    done by mutating ``dirnames`` in-place so ``os.walk`` does not descend
    past the depth budget (e.g. into ``.git`` or vendored ``node_modules``).
    """
    if not os.path.isdir(base):
        return []
    base_sep_count = base.count(os.sep)
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=True):
        depth = dirpath.count(os.sep) - base_sep_count
        if "requirements.txt" in filenames:
            found.append(os.path.join(dirpath, "requirements.txt"))
        if depth >= max_depth:
            dirnames[:] = []
    return found


@functools.lru_cache(maxsize=8)
def _uv_available(python_exe: str) -> bool:
    """Return True if *python_exe* can import the ``uv`` module."""
    try:
        proc = subprocess.run(
            [python_exe, "-c", "import uv"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0


def ensure_uv(python_exe: str, *, stream_output: bool = True) -> bool:
    """Make sure the ``uv`` module is importable by *python_exe*.

    This matters for freshly downloaded bundle pythons: the ComfyUI portable
    archive does not ship ``uv``, so without it :func:`_base_cmd` falls back to
    ``pip install -U`` — which upgrades a directly-listed ``torch`` to the CPU
    wheel from PyPI and clobbers the bundle's CUDA build ("Torch not compiled
    with CUDA enabled"). Installing uv keeps the install path identical to the
    main tool's. Returns True if uv is available afterwards.
    """
    if _uv_available(python_exe):
        return True
    print("  uv not found in bundle python; installing uv...")
    rc = _run([python_exe, "-m", "pip", "install", "uv"], stream_output=stream_output)
    _uv_available.cache_clear()
    if rc != 0:
        print(f"  uv install exited with code {rc}; falling back to pip.")
    return _uv_available(python_exe)


def _base_cmd(python_exe: str) -> tuple[list[str], str]:
    """Return (command prefix, human label) for the preferred installer."""
    if _uv_available(python_exe):
        return (
            [python_exe, "-m", "uv", "pip", "install", "--python", python_exe, "--no-build-isolation"],
            "uv pip install",
        )
    return (
        [python_exe, "-m", "pip", "install", "-U", "--upgrade-strategy=only-if-needed"],
        "pip install",
    )


def _display_path(path: str) -> str:
    """Best-effort short display path. Falls back to *path* on Windows cross-drive."""
    try:
        return os.path.relpath(path)
    except ValueError:
        # Raised when *path* and cwd live on different mounts (e.g. C:\ vs D:\).
        return path


def _run(cmd: list[str], *, stream_output: bool) -> int:
    if not stream_output:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return proc.returncode

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
    proc.wait()
    return proc.returncode


def install_requirement_files(
    python_exe: str,
    req_files: list[str],
    *,
    stream_output: bool = True,
) -> None:
    """Install one or more requirements.txt files in a single resolver pass.

    On failure, retries each file individually so a single bad node doesn't
    block the rest.
    """
    if not req_files:
        return

    base, label = _base_cmd(python_exe)
    flat: list[str] = []
    for req in req_files:
        flat.extend(["-r", req])

    pretty = " ".join(f"-r {_display_path(r)}" for r in req_files)
    print(f"  {label} {pretty}")
    rc = _run(base + flat, stream_output=stream_output)
    if rc == 0:
        return

    print(f"  Grouped install exited with code {rc}; retrying per file...")
    for req in req_files:
        print(f"  {label} -r {_display_path(req)}")
        rc_one = _run(base + ["-r", req], stream_output=stream_output)
        if rc_one != 0:
            print(f"  exited with code {rc_one} for {req}")


def install_packages(
    python_exe: str,
    args: list[str],
    *,
    stream_output: bool = True,
) -> int:
    """Run ``(uv) pip install`` with arbitrary *args* (e.g. a local wheel)."""
    base, label = _base_cmd(python_exe)
    print(f"  {label} {' '.join(args)}")
    return _run(base + args, stream_output=stream_output)

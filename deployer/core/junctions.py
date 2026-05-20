"""Windows directory-junction helpers.

A junction is a Windows reparse point that makes a folder transparently
appear at another location. Junctions don't require admin elevation, which
is why ComfyUI Deployer uses them to share custom-node and model folders
between the GitLab clone roots and ComfyUI's expected layout.
"""

import os
import shutil
import subprocess


# Win32 namespace marker prepended by os.readlink to junction targets.
_WIN32_NAMESPACE_PREFIX = "\\\\?\\"


def get_junction_target(path: str) -> str:
    """Return the target path of a junction, or ``""`` if *path* isn't one."""
    try:
        return os.readlink(path)
    except (OSError, ValueError):
        return ""


def read_junction_target(path: str) -> str:
    """Return *path*'s junction target with the Win32 namespace prefix stripped.

    Empty string if *path* isn't a junction. Use this anywhere the human-
    readable destination is needed — ``get_junction_target`` returns the raw
    readlink output, which on Windows is prefixed with ``\\\\?\\``.
    """
    if not is_junction(path):
        return ""
    return get_junction_target(path).removeprefix(_WIN32_NAMESPACE_PREFIX)


def is_junction(path: str) -> bool:
    """Return ``True`` if *path* is a Windows directory junction."""
    result = subprocess.run(
        ["fsutil", "reparsepoint", "query", path],
        capture_output=True,
    )
    return result.returncode == 0


def create_junction(link: str, target: str) -> None:
    """Create a junction at *link* pointing to *target* (no admin required)."""
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", link, target],
        check=True,
    )


def replace_with_junction(path: str, target: str) -> None:
    """Replace the directory at *path* with a junction to *target*.

    No-op if *path* is already a junction.
    """
    if is_junction(path):
        return
    if os.path.isdir(path):
        shutil.rmtree(path)
    create_junction(path, target)


def apply_folder_junction(target_dir: str, backup_dir: str, selected: str) -> None:
    """Point *target_dir* at *selected* via a junction.

    If *target_dir* is currently a real directory, it is renamed to
    *backup_dir* first so its contents are preserved.
    """
    if is_junction(target_dir):
        os.rmdir(target_dir)
    elif os.path.isdir(target_dir):
        os.rename(target_dir, backup_dir)
    create_junction(target_dir, selected)
    print(f"Junction: {target_dir} → {selected}")


def remove_folder_junction(target_dir: str, backup_dir: str) -> None:
    """Remove the junction at *target_dir* and restore the backed-up directory.

    If no backup exists, recreate an empty directory at *target_dir* so that
    ComfyUI keeps finding the folder it expects.
    """
    if is_junction(target_dir):
        os.rmdir(target_dir)
        print(f"Junction removed: {target_dir}")
    if os.path.isdir(backup_dir) and not os.path.exists(target_dir):
        os.rename(backup_dir, target_dir)
        print(f"Restored: {backup_dir} → {target_dir}")
    elif not os.path.exists(target_dir):
        os.makedirs(target_dir)
        print(f"Recreated: {target_dir}")

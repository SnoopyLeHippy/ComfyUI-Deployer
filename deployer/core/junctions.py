"""Windows directory-junction helpers.

A junction is a Windows reparse point that makes a folder transparently
appear at another location. Junctions don't require admin elevation, which
is why ComfyUI Deployer uses them to share custom-node and model folders
between the GitLab clone roots and ComfyUI's expected layout.

No process is started here: junctions are read with ``os.lstat`` and created
through the Windows API (``_winapi.CreateJunction``), never ``fsutil`` nor
``cmd /c mklink`` — endpoint security flags script-host → shell chains, and
the window checks every ``custom_nodes`` folder as it opens.

A **link folder** is the other way a program puts a node of its own into
``custom_nodes``: a real folder holding :data:`LINK_FILE`, its code living at
the target the file names. MoodMiner writes one instead of a junction, which
the processes it starts (under Windows' RedirectionTrust mitigation) cannot
cross when it was made without admin rights. :func:`read_link_file` reads it.
"""

import json
import os
import shutil
import stat

from deployer.core.filesystem import force_remove_readonly


# Win32 namespace marker prepended by os.readlink to junction targets.
_WIN32_NAMESPACE_PREFIX = "\\\\?\\"

#: A folder holding this file is a *linked* node:
#: ``{"target": "<absolute path>", "by": "<program>"}`` — its code lives at
#: ``target`` and the program ``by`` owns it. Contract written by MoodMiner.
LINK_FILE = "linked-node.json"


def read_link_file(path: str) -> str | None:
    """Return the target named by *path*'s :data:`LINK_FILE`, or ``None``.

    ``None`` when the file is absent, unreadable, not a JSON object, or names
    no absolute ``target`` (MoodMiner refuses the same) — the folder is then
    an ordinary one. The target need not exist: a link whose program is gone
    still says where it led. A byte-order mark is accepted.
    """
    try:
        with open(os.path.join(path, LINK_FILE), encoding="utf-8-sig") as fh:
            target = json.load(fh).get("target")
    except (OSError, ValueError, AttributeError):  # ValueError: bad JSON or encoding
        return None
    if not isinstance(target, str) or not os.path.isabs(target):
        return None
    return os.path.normpath(target)


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
    """Return ``True`` if *path* is a Windows directory junction.

    Any reparse point counts (a directory symlink too), as ``fsutil reparsepoint
    query`` answered before: callers remove such a path with ``os.rmdir`` — the
    link only, never what it points at. A missing path is ``False``.
    """
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except (OSError, ValueError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def create_junction(link: str, target: str) -> None:
    """Create a junction at *link* pointing to *target* (no admin required).

    *target* must exist (``OSError`` otherwise); *link* must not.
    """
    import _winapi  # Windows only, like junctions themselves

    if not os.path.isdir(target):
        raise FileNotFoundError(f"junction target is not a folder: {target}")
    _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))


def replace_with_junction(path: str, target: str) -> None:
    """Replace whatever is at *path* with a junction to *target*.

    Works whether *path* is currently a real directory or an existing
    junction (re-pointing it at the new *target*).
    """
    if is_junction(path):
        os.rmdir(path)
    elif os.path.isdir(path):
        shutil.rmtree(path, onerror=force_remove_readonly)
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

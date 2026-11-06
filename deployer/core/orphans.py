"""Discovery of custom-node directories that exist on disk but aren't tracked.

A node is an *orphan* when its folder lives under ``CUSTOM_NODES_DIR`` and
contains a ``.git`` directory, yet neither its origin nor its folder name is
known to the user's node list. The user can then promote orphans into their
settings from the UI.

Both comparisons are needed, and neither alone is enough:

* **origin**, through :func:`~deployer.core.node.repo_identity` rather than the
  raw remote URL — GitLab nodes are stored as HTTPS in the configuration but
  cloned over SSH, so a string compare would report every one of them as an
  orphan.
* **folder name**, because a directory is the install location of exactly one
  tracked node. A repo renamed upstream (say ``owner/Node`` to
  ``owner/ComfyUI-Node``) leaves the old URL in the clone's ``origin`` while
  the configuration carries the new one; the URLs no longer match, yet the
  folder is plainly that node's. Without this pass it shows up twice — once
  *Installed*, once *Missing*.

An untracked folder that is a **junction** is not an orphan but a *linked*
node: another program put it there and keeps it (MoodMiner links its own
clone as ``custom_nodes/ComfyUI-MoodMiner``). It is listed apart, so the window
can show it without offering to track it — tracking it would let an install
remove it, and removing a junction takes the other program out of ComfyUI.
"""

import os
from typing import NamedTuple

from deployer.config import CUSTOM_NODES_DIR
from deployer.core import git_ops
from deployer.core.junctions import is_junction, read_junction_target
from deployer.core.node import repo_identity


OrphanNode = tuple[str, str, str]  # (folder_name, remote_url, ref)
LinkedNode = tuple[str, str]  # (folder_name, junction_target)


class UntrackedNodes(NamedTuple):
    orphans: list[OrphanNode]
    linked: list[LinkedNode]


def discover_untracked_nodes(
    known_repo_identities: set[str],
    known_folder_names: set[str],
) -> UntrackedNodes:
    """Return the git-backed subdirectories of ``CUSTOM_NODES_DIR`` nothing tracks.

    A directory is skipped when its origin is in *known_repo_identities* or its
    name is in *known_folder_names* (compared case-insensitively, NTFS being
    case-insensitive itself).

    ``orphans`` are ``(folder_name, remote_url, ref)``; entries whose origin
    URL can't be read are skipped — there's nothing the user could do with
    them. ``linked`` are the junctions among them, ``(folder_name, target)``.
    """
    known_folder_names = {name.lower() for name in known_folder_names}
    if not os.path.isdir(CUSTOM_NODES_DIR):
        return UntrackedNodes([], [])
    try:
        entries = list(os.scandir(CUSTOM_NODES_DIR))
    except OSError:
        return UntrackedNodes([], [])

    orphans: list[OrphanNode] = []
    linked: list[LinkedNode] = []
    for entry in entries:
        if not entry.is_dir(follow_symlinks=True):
            continue
        if not os.path.exists(os.path.join(entry.path, ".git")):
            continue
        if entry.name.lower() in known_folder_names:
            continue

        url = git_ops.get_remote_url(entry.path)
        if not url:
            continue
        if repo_identity(url) in known_repo_identities:
            continue
        if is_junction(entry.path):
            linked.append((entry.name, read_junction_target(entry.path)))
            continue
        ref = git_ops.describe_head(entry.path, fallback="HEAD")
        orphans.append((entry.name, url, ref))
    return UntrackedNodes(orphans, linked)

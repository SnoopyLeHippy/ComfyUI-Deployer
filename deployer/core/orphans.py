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
"""

import os

from deployer.config import CUSTOM_NODES_DIR
from deployer.core import git_ops
from deployer.core.node import repo_identity


OrphanNode = tuple[str, str, str]  # (folder_name, remote_url, ref)


def discover_orphan_nodes(
    known_repo_identities: set[str],
    known_folder_names: set[str],
) -> list[OrphanNode]:
    """Return the git-backed subdirectories of ``CUSTOM_NODES_DIR`` nothing tracks.

    A directory is skipped when its origin is in *known_repo_identities* or its
    name is in *known_folder_names* (compared case-insensitively, NTFS being
    case-insensitive itself).

    Each tuple is ``(folder_name, remote_url, ref)``. Entries whose origin
    URL can't be read are skipped — there's nothing the user could do with
    them.
    """
    known_folder_names = {name.lower() for name in known_folder_names}
    if not os.path.isdir(CUSTOM_NODES_DIR):
        return []
    try:
        entries = list(os.scandir(CUSTOM_NODES_DIR))
    except OSError:
        return []

    orphans: list[OrphanNode] = []
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
        ref = git_ops.describe_head(entry.path, fallback="HEAD")
        orphans.append((entry.name, url, ref))
    return orphans

"""Discovery of custom-node directories that exist on disk but aren't tracked.

A node is an *orphan* when its folder lives under ``CUSTOM_NODES_DIR`` and
contains a ``.git`` directory, yet its name is missing from the user's
known-nodes list. The user can then promote orphans into their settings
from the UI.
"""

import os

from deployer.config import CUSTOM_NODES_DIR
from deployer.core import git_ops


OrphanNode = tuple[str, str, str]  # (folder_name, remote_url, ref)


def _canonical_url(url: str) -> str:
    return url.strip().rstrip("/").removesuffix(".git").lower()


def discover_orphan_nodes(known_canonical_urls: set[str]) -> list[OrphanNode]:
    """Return git-backed subdirectories of ``CUSTOM_NODES_DIR`` not in *known_canonical_urls*.

    Each tuple is ``(folder_name, remote_url, ref)``. Entries whose origin
    URL can't be read are skipped — there's nothing the user could do with
    them.
    """
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

        url = git_ops.get_remote_url(entry.path)
        if not url:
            continue
        if _canonical_url(url) in known_canonical_urls:
            continue
        ref = git_ops.describe_head(entry.path, fallback="HEAD")
        orphans.append((entry.name, url, ref))
    return orphans

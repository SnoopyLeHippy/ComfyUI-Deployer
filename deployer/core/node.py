"""Data model for a ComfyUI custom node."""

import os
import subprocess
from urllib.parse import urlparse

from deployer.config import (
    CUSTOM_NODES_DIR,
    GITLAB_SSH,
    GITLAB_URL,
)
from deployer.core import git_ops


def _strip_git_suffix(path: str) -> str:
    return path.removesuffix(".git").strip("/\\")


def _repo_host(repo: str) -> str:
    repo = repo.strip()
    if repo.startswith("git@"):
        return repo.split(":", 1)[0].split("@", 1)[-1]
    return urlparse(repo).netloc


def _repo_relative_path(repo: str) -> str:
    repo = repo.strip()
    if GITLAB_URL and repo.startswith(GITLAB_URL):
        return _strip_git_suffix(repo[len(GITLAB_URL):])
    if GITLAB_SSH and repo.startswith(GITLAB_SSH):
        return _strip_git_suffix(repo[len(GITLAB_SSH):])
    if repo.startswith("git@") and ":" in repo:
        return _strip_git_suffix(repo.split(":", 1)[1])

    parsed = urlparse(repo)
    if parsed.scheme and parsed.netloc:
        return _strip_git_suffix(parsed.path.lstrip("/"))

    return _strip_git_suffix(os.path.basename(repo))


def repo_identity(repo: str) -> str:
    """Host + path key identifying a repository across its spellings.

    ``git@gitlab.example.com:grp/Node.git`` and
    ``https://gitlab.example.com/grp/Node`` are one repository; comparing the
    raw strings would not say so, and that matters here because
    :attr:`CustomNode.clone_url` deliberately clones GitLab remotes over SSH
    while the configuration usually stores them as HTTPS. Case, ``.git`` and
    trailing slashes are normalised away too.
    """
    return f"{_repo_host(repo)}/{_repo_relative_path(repo)}".strip("/").lower()


def repo_folder_name(repo: str) -> str:
    """The ``custom_nodes/`` directory *repo* clones into.

    This is a node's real primary key: two repo URLs yielding the same folder
    name cannot coexist on disk, whatever their remotes are. Public because
    config merging needs it without building a :class:`CustomNode` (whose
    constructor hits the filesystem).
    """
    return os.path.basename(_repo_relative_path(repo)) or os.path.basename(repo.rstrip("/\\"))


def _repo_looks_like_gitlab(repo: str) -> bool:
    if GITLAB_URL and repo.startswith(GITLAB_URL):
        return True
    if GITLAB_SSH and repo.startswith(GITLAB_SSH):
        return True
    return "gitlab" in _repo_host(repo).lower()


def _repo_local_path(root_dir: str, repo_path: str) -> str:
    parts = [part for part in repo_path.replace("\\", "/").split("/") if part]
    return os.path.join(root_dir, *parts) if parts else root_dir


def _gitlab_prefix_hints(repo: str) -> tuple[str, str]:
    host = _repo_host(repo)
    if host:
        return (f"https://{host}/", f"git@{host}:")
    return ("https://your-gitlab.example.org/", "git@your-gitlab.example.org:")


class CustomNode:
    """A single ComfyUI custom node that can be cloned, checked out, and linked."""

    def __init__(self, repo: str, ref: str, description: str):
        self.repo = repo
        self.ref = ref
        self.description = description
        self._git_path = _repo_relative_path(repo)
        self._is_gitlab_repo = _repo_looks_like_gitlab(repo)
        self.name = repo_folder_name(repo)
        self.is_selected = False
        self.is_install_requirements = False

        # All nodes are cloned directly into ComfyUI's custom_nodes.
        self.local_path = os.path.join(CUSTOM_NODES_DIR, self.name)
        self.comfyui_path = self.local_path
        self.is_installed = os.path.exists(self.comfyui_path)

    # -- Properties ---------------------------------------------------------

    @property
    def is_gitlab_repo(self) -> bool:
        return self._is_gitlab_repo

    @property
    def is_gitlab(self) -> bool:
        return self.is_gitlab_repo and bool(GITLAB_SSH)

    @property
    def clone_url(self) -> str:
        """The URL git-clone should use (SSH for GitLab, HTTPS otherwise)."""
        if self.is_gitlab:
            return f"{GITLAB_SSH}{self._git_path}"
        return self.repo

    @property
    def web_url(self) -> str:
        """Browser-friendly URL for this node's repo.

        Converts SSH forms (``git@host:owner/repo[.git]`` or a configured
        ``GITLAB_SSH`` prefix) into an HTTPS URL; HTTPS URLs are passed
        through untouched. The trailing ``.git`` suffix is stripped so the
        browser lands on the project page rather than the git endpoint.
        """
        repo = self.repo.strip()
        if repo.startswith(("http://", "https://")):
            return repo.removesuffix(".git")
        if GITLAB_SSH and repo.startswith(GITLAB_SSH) and GITLAB_URL:
            return GITLAB_URL + repo[len(GITLAB_SSH):].removesuffix(".git")
        if repo.startswith("git@") and ":" in repo:
            host, path = repo[len("git@"):].split(":", 1)
            return f"https://{host}/{path.removesuffix('.git')}"
        return repo

    # -- Actions ------------------------------------------------------------

    def clone(self) -> None:
        """Clone the repo if absent, then checkout the configured ref."""
        just_cloned = not os.path.exists(self.local_path)
        if just_cloned:
            print(f"Cloning {self.repo}...")
            git_ops.clone(self.clone_url, self.name, cwd=CUSTOM_NODES_DIR)

        # After a fresh clone git already checked out the default branch.
        # Detect the actual branch so we don't fail when self.ref ("main") differs
        # from the repo's real default branch ("master", etc.).
        if just_cloned:
            actual = git_ops.get_current_branch(self.local_path)
            if actual and actual not in ("HEAD",) and actual != self.ref:
                print(f"Default branch is '{actual}'; using it instead of '{self.ref}'.")
                self.ref = actual
                return  # already on the correct branch, no checkout needed

        print(f"Checking out {self.ref}...")
        git_ops.checkout(self.ref, cwd=self.local_path)

    def update(self) -> None:
        """Bring an installed node up to date with its configured ref.

        Checks out ``self.ref`` and, when that ref resolves to a branch (not a
        detached tag / pinned commit), pulls the latest commits from origin.
        Falls back to a full clone if the repo isn't on disk yet.
        """
        if not os.path.exists(self.local_path):
            self.clone()
            return

        print(f"Checking out {self.ref}...")
        git_ops.checkout(self.ref, cwd=self.local_path)

        # Only pull when we're on a branch — pulling a detached tag/commit is
        # meaningless and would error out.
        branch = git_ops.get_current_branch(self.local_path)
        if branch and branch != "HEAD":
            print(f"Pulling latest changes on '{branch}'...")
            git_ops.pull(self.local_path)

    def is_ref_current(self) -> bool:
        """Return ``True`` if the local HEAD matches the configured ref.

        Returns ``True`` on any error (e.g. git unavailable) so a transient
        failure never spuriously marks a node as needing an update.
        """
        if not os.path.exists(self.local_path):
            return True
        try:
            head = git_ops.rev_parse("HEAD", cwd=self.local_path)
            target_ref = self.ref if self.ref.startswith("^") else f"{self.ref}^{{}}"
            target = git_ops.rev_parse(target_ref, cwd=self.local_path)
            return head == target
        except subprocess.CalledProcessError:
            return True

    def is_behind_remote(self) -> bool:
        """Return ``True`` if the checked-out branch is behind its remote.

        Fetches from origin and compares the local branch with its upstream;
        a positive result means new commits are available to pull. Only
        meaningful for nodes on a branch — tags, detached HEADs and pinned
        commits are treated as always up to date.

        Touches the network (fetch), so call this off the UI thread. Returns
        ``False`` on any error so a transient failure never spuriously flags
        a node as needing an update.
        """
        if not os.path.exists(self.local_path):
            return False
        branch = git_ops.get_current_branch(self.local_path)
        if not branch or branch == "HEAD":
            return False  # detached / tag / pinned commit — nothing to track
        if not git_ops.fetch(self.local_path):
            return False
        return git_ops.is_behind_upstream(self.local_path)

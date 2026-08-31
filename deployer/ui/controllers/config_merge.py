"""Merge a loaded configuration into the cards currently on the grid.

Loading a configuration *replaces* what is displayed, it never adds to it: the
grid after a load is the loaded configuration, plus whatever the user chooses
to keep among the nodes that configuration doesn't mention.

Matching an incoming entry against an existing card happens in two passes,
most specific first:

1. **By repo identity** (:func:`~deployer.core.node.repo_identity`) — host +
   path, so an SSH and an HTTPS spelling of one GitLab remote match.
2. **By folder name** — the directory the repo clones into under
   ``custom_nodes/``. This is the node's real primary key: two URLs producing
   the same folder name cannot coexist on disk, so this pass catches a genuine
   remote change (two forks of the same node).

Pass 2 is deliberately not restricted to GitLab: a GitHub fork swap hits the
exact same on-disk collision, and letting it through would leave two cards
fighting over one directory.

Kept free of Qt (and of :class:`~deployer.core.node.CustomNode`, whose
constructor touches the filesystem) so the whole classification is unit
testable.
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from deployer.core.node import repo_folder_name, repo_identity


class MergeAction(Enum):
    """What loading the configuration should do to one of its entries."""

    KEEP = auto()       # already installed at the requested ref — nothing to do
    INSTALL = auto()    # absent from disk — clone it
    UPDATE = auto()     # installed from the same remote at another ref — checkout + pull
    REINSTALL = auto()  # installed from a *different* remote — wipe the folder and re-clone


@dataclass(frozen=True)
class ExistingCard:
    """A card already on the grid, reduced to what merging needs.

    ``handle`` is the opaque card object the caller passed in; it is carried
    through untouched so the caller can act on the right widget.
    """

    handle: object
    repo: str
    ref: str
    is_installed: bool
    is_orphan: bool = False

    @property
    def name(self) -> str:
        return repo_folder_name(self.repo)


@dataclass
class MergedEntry:
    """One entry of the loaded configuration, resolved against the grid."""

    repo: str
    ref: str
    description: str
    action: MergeAction
    existing: ExistingCard | None = None
    #: True when *existing* was matched on its folder name rather than its URL,
    #: i.e. the remote itself changed.
    repo_changed: bool = False


@dataclass
class ConfigMergePlan:
    """Result of merging a loaded configuration into the current cards."""

    entries: list[MergedEntry] = field(default_factory=list)
    #: Tracked cards the loaded configuration doesn't mention. Orphans are
    #: never listed here — they were never part of the configuration.
    extras: list[ExistingCard] = field(default_factory=list)
    #: Repo URLs skipped because an earlier entry already claimed the same
    #: node (same URL, or same folder name) within the loaded file itself.
    dropped_duplicates: list[str] = field(default_factory=list)

    def count(self, action: MergeAction) -> int:
        return sum(1 for entry in self.entries if entry.action is action)


def _classify(entry_ref: str, existing: ExistingCard | None, repo_changed: bool) -> MergeAction:
    if existing is None or not existing.is_installed:
        return MergeAction.INSTALL
    if repo_changed:
        # Same folder, different remote: `git pull` would fetch from the *old*
        # origin, so the only honest action is to drop the folder and re-clone.
        return MergeAction.REINSTALL
    return MergeAction.KEEP if entry_ref == existing.ref else MergeAction.UPDATE


def merge_config(loaded_entries: list[dict], existing: list[ExistingCard]) -> ConfigMergePlan:
    """Resolve *loaded_entries* against *existing* cards.

    *loaded_entries* are the raw ``{"repo", "ref", "description"}`` dicts of a
    configuration file, in file order; entries without a ``repo`` are ignored.
    Tracked cards take precedence over orphans when both would match, so a
    node already in the configuration is never shadowed by a stray folder.
    """
    by_identity: dict[str, ExistingCard] = {}
    by_name: dict[str, ExistingCard] = {}
    # Orphans first so tracked cards overwrite them on a key collision.
    for card in sorted(existing, key=lambda c: not c.is_orphan):
        by_identity[repo_identity(card.repo)] = card
        by_name[card.name] = card

    plan = ConfigMergePlan()
    consumed: set[int] = set()
    seen_identities: set[str] = set()
    seen_names: set[str] = set()

    for raw in loaded_entries:
        repo = (raw.get("repo") or "").strip()
        if not repo:
            continue
        identity_key = repo_identity(repo)
        name_key = repo_folder_name(repo)
        if identity_key in seen_identities or name_key in seen_names:
            plan.dropped_duplicates.append(repo)
            continue
        seen_identities.add(identity_key)
        seen_names.add(name_key)

        match = by_identity.get(identity_key)
        repo_changed = False
        if match is None:
            match = by_name.get(name_key)
            repo_changed = match is not None
        # A card can only back one entry: the second entry aiming at it is
        # treated as brand new (its folder name already differed, or it was
        # dropped as a duplicate above).
        if match is not None and id(match.handle) in consumed:
            match, repo_changed = None, False
        if match is not None:
            consumed.add(id(match.handle))

        ref = raw.get("ref") or "main"
        plan.entries.append(
            MergedEntry(
                repo=repo,
                ref=ref,
                description=raw.get("description", ""),
                action=_classify(ref, match, repo_changed),
                existing=match,
                repo_changed=repo_changed,
            )
        )

    plan.extras = [
        card for card in existing
        if not card.is_orphan and id(card.handle) not in consumed
    ]
    return plan

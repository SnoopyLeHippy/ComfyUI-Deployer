"""Aggregate workflow-resolution results across one or more workflow files.

Both "Add from workflow" and "Create Bundle from workflow" call
:func:`deployer.core.workflow_resolver.resolve_workflow_nodes` and need to
fold the per-workflow results into a single view. Centralising that here
removes the parallel implementations that used to live on
:class:`CustomNodeDeployerApp`.
"""

from dataclasses import dataclass, field

from deployer.core.workflow_resolver import (
    ConflictEntry,
    ResolvedRepo,
    resolve_workflow_nodes,
)


@dataclass
class WorkflowResolution:
    """Merged result of resolving one or more workflow JSONs."""

    resolved: list[ResolvedRepo] = field(default_factory=list)
    conflicts: list[ConflictEntry] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    repo_to_desc: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.resolved or self.conflicts or self.unresolved)


def known_repos_from_cards(node_cards, orphan_cards, *, installed_only: bool = True) -> set[str]:
    """Collect the repo URLs currently known to the app.

    When *installed_only* is True (the default for "Add from workflow"),
    tracked-but-not-installed nodes are intentionally excluded so the UI can
    re-surface them as actionable cards. For bundle resolution, callers pass
    ``installed_only=True`` as well — the orphan-card union below keeps
    workflow-imported orphans in the known set.
    """
    nodes = (card.node for card in node_cards if not installed_only or card.node.is_installed)
    known = {node.repo for node in nodes}
    known.update(card.repo for card in orphan_cards)
    return known


def resolve_workflows(workflow_paths: list[str], known_repos: set[str]) -> WorkflowResolution:
    """Resolve every workflow in *workflow_paths* and merge the results.

    A repo that is auto-resolved in one workflow and conflicting in another is
    folded by ``resolve_workflow_nodes``'s own logic per call; cross-workflow
    deduplication is by repo URL for ``resolved`` and by content for the rest.
    """
    merged = WorkflowResolution()
    seen_resolved: set[str] = set()

    for wf_path in workflow_paths:
        resolved, conflicts, unresolved, repo_to_desc = resolve_workflow_nodes(wf_path, known_repos)
        for entry in resolved:
            if entry.repo in seen_resolved:
                continue
            seen_resolved.add(entry.repo)
            merged.resolved.append(entry)
        merged.conflicts.extend(conflicts)
        for ntype in unresolved:
            if ntype not in merged.unresolved:
                merged.unresolved.append(ntype)
        merged.repo_to_desc.update(repo_to_desc)

    return merged

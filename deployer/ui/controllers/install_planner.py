"""Classify the current card grid into an actionable install plan.

The UI tracks node state with several booleans on each card; the install
button needs to translate that into "what should actually happen?". Pulling
the classification out of :class:`CustomNodeDeployerApp` keeps the install
flow scriptable and unit-testable.
"""

from dataclasses import dataclass, field

from deployer.core.node import CustomNode


@dataclass
class InstallPlan:
    """Concrete set of actions derived from the current card states."""

    to_install: list[CustomNode] = field(default_factory=list)
    to_uninstall: list[CustomNode] = field(default_factory=list)
    to_update: list = field(default_factory=list)        # NodeCard — needs ref change before clone
    invalid_gitlab: list[CustomNode] = field(default_factory=list)
    with_requirements: list[CustomNode] = field(default_factory=list)
    selected_orphans: list = field(default_factory=list)  # OrphanNodeCard

    def is_empty(self) -> bool:
        """True if nothing would happen if this plan ran."""
        return not (
            self.to_install
            or self.to_uninstall
            or self.to_update
            or self.with_requirements
            or self.selected_orphans
        )


def plan_install(node_cards, orphan_cards) -> InstallPlan:
    """Translate the current card states into an :class:`InstallPlan`.

    Mirrors the legacy ``_run_install`` classification: a selected installed
    node is queued for removal; a selected uninstalled node, for install; a
    card marked as pending-update keeps its install and re-clones at the new
    ref. Nodes with a GitLab config error are routed to ``invalid_gitlab``
    when they would have triggered an action.
    """
    plan = InstallPlan()
    to_install_set: set[CustomNode] = set()

    for card in node_cards:
        node = card.node
        if node.has_gitlab_config_error:
            if card.is_selected or card.is_pending_update or (node.is_install_requirements and node.is_installed):
                plan.invalid_gitlab.append(node)
            continue
        if card.is_selected and node.is_installed:
            plan.to_uninstall.append(node)
        elif card.is_selected and not node.is_installed:
            plan.to_install.append(node)
            to_install_set.add(node)
        elif card.is_pending_update and node.is_installed:
            plan.to_update.append(card)

    # Requirements are installed in a single resolver pass that includes both
    # already-installed nodes whose checkbox is on AND freshly-cloned ones.
    for card in node_cards:
        node = card.node
        if node.has_gitlab_config_error or not node.is_install_requirements:
            continue
        if node.is_installed or node in to_install_set:
            plan.with_requirements.append(node)

    plan.selected_orphans = [c for c in orphan_cards if c.is_selected]
    return plan

"""Visual states shared by :class:`NodeCard` and :class:`OrphanNodeCard`.

A card's appearance is a function of one of nine discrete states — keeping
that mapping in a single table lets both card subclasses share their styling
logic and removes the cascade of ``if is_selected and is_installed: ...``
branches that used to live in each ``_update_style`` method.
"""

from enum import Enum, auto

from deployer.ui import theme


class CardState(Enum):
    """All possible visual states for a card in the grid."""

    DEFAULT = auto()           # NodeCard, not installed, not selected
    INSTALLED = auto()         # NodeCard, on disk and ref current
    TO_INSTALL = auto()        # NodeCard selected, not yet installed
    TO_UPDATE = auto()         # NodeCard installed, ref drift detected
    NEED_UPDATE = auto()       # NodeCard installed, branch behind its remote
    TO_REMOVE = auto()         # NodeCard selected, currently installed
    IMPORT = auto()            # Card pulled in from a workflow import
    ERROR = auto()             # NodeCard with GitLab config error
    MISSING = auto()           # OrphanNodeCard, default appearance
    ADD_TO_CONFIG = auto()     # OrphanNodeCard selected for promotion


# (stylesheet, badge_text, badge_stylesheet)
_STATE_PRESENTATION: dict[CardState, tuple[str, str, str]] = {
    CardState.DEFAULT: (
        theme.NODE_CARD_DEFAULT_STYLE,
        "Not installed",
        theme.NOT_INSTALLED_BADGE_STYLE,
    ),
    CardState.INSTALLED: (
        theme.NODE_CARD_INSTALLED_STYLE,
        "Installed",
        theme.INSTALLED_BADGE_STYLE,
    ),
    CardState.TO_INSTALL: (
        theme.NODE_CARD_SELECTED_STYLE,
        "To install",
        theme.BADGE_TO_INSTALL_STYLE,
    ),
    CardState.TO_UPDATE: (
        theme.NODE_CARD_TO_UPDATE_STYLE,
        "To update",
        theme.BADGE_TO_UPDATE_STYLE,
    ),
    CardState.NEED_UPDATE: (
        theme.NODE_CARD_NEED_UPDATE_STYLE,
        "Need update",
        theme.BADGE_NEED_UPDATE_STYLE,
    ),
    CardState.TO_REMOVE: (
        theme.NODE_CARD_SELECTED_INSTALLED_STYLE,
        "To remove",
        theme.BADGE_TO_REMOVE_STYLE,
    ),
    CardState.IMPORT: (
        theme.NODE_CARD_IMPORT_STYLE,
        "Import",
        theme.BADGE_IMPORT_STYLE,
    ),
    CardState.ERROR: (
        theme.NODE_CARD_ERROR_STYLE,
        "error",
        theme.BADGE_ERROR_STYLE,
    ),
    CardState.MISSING: (
        theme.NODE_CARD_ORPHAN_STYLE,
        "Missing",
        theme.BADGE_MISSING_STYLE,
    ),
    CardState.ADD_TO_CONFIG: (
        theme.NODE_CARD_ORPHAN_SELECTED_STYLE,
        "Add to config",
        theme.BADGE_ADD_TO_CONFIG_STYLE,
    ),
}


def presentation_for(state: CardState) -> tuple[str, str, str]:
    """Return ``(card_stylesheet, badge_text, badge_stylesheet)`` for *state*."""
    return _STATE_PRESENTATION[state]

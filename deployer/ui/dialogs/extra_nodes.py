"""Dialog asking what to do with nodes a loaded configuration doesn't mention.

Loading a configuration replaces the grid, so every tracked node absent from
the loaded file needs a decision. Three are offered because "delete" is
ambiguous here:

* :attr:`ExtraNodesDecision.UNINSTALL` — mark them *To remove*; the next
  Install wipes their folder from ``custom_nodes/`` and drops the card.
* :attr:`ExtraNodesDecision.UNTRACK` — drop them from the configuration only.
  The folder stays on disk and the node reappears as a *Missing* orphan card,
  so the choice is reversible.
* :attr:`ExtraNodesDecision.KEEP` — leave them in the configuration untouched.

Nothing is applied here: the dialog only reports the decision and the rows the
user left checked, so the main window stays the single place that mutates cards.
"""

from enum import Enum, auto

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from deployer.ui import theme


class ExtraNodesDecision(Enum):
    """What the user chose to do with the nodes absent from the configuration."""

    KEEP = auto()
    UNINSTALL = auto()
    UNTRACK = auto()


class ExtraNodesDialog(QDialog):
    """Let the user pick which unmentioned nodes to drop, and how."""

    def __init__(self, nodes: list[tuple[str, bool]], parent=None):
        """*nodes* is a list of ``(name, is_installed)``, in grid order."""
        super().__init__(parent)
        self.setWindowTitle("Nodes not in loaded configuration")
        self.setMinimumWidth(520)
        self.setMinimumHeight(360)
        self.setStyleSheet(theme.APP_STYLE)

        self._decision = ExtraNodesDecision.KEEP
        # Rows are kept alive here: a QCheckBox whose only reference lives in a
        # local would be collected by CPython and deleted under Qt before we
        # read it back (same trap as PackageRepairDialog._build_row).
        self._boxes: list[QCheckBox] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        msg = QLabel(
            f"<b>{len(nodes)}</b> node(s) of your current configuration are "
            "<b>not present</b> in the loaded one.<br>"
            "Uncheck the ones you want to keep, then choose what to do with the rest."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet(theme.SUBTITLE_STYLE)
        root.addWidget(msg)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL_AREA_STYLE)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        rows = QVBoxLayout(container)
        rows.setContentsMargins(4, 4, 4, 4)
        rows.setSpacing(4)
        for name, is_installed in nodes:
            box = QCheckBox(f"{name}   —   {'installed' if is_installed else 'not installed'}")
            box.setChecked(True)
            box.setStyleSheet(theme.CHECKBOX_STYLE)
            self._boxes.append(box)
            rows.addWidget(box)
        rows.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        hint = QLabel(
            "<b>Uninstall</b> deletes their folder from custom_nodes on the next Install, "
            "then drops the card. <b>Untrack</b> only removes them from the configuration — "
            "they stay on disk and come back as <i>Missing</i> cards."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.HELP_TEXT_STYLE)
        root.addWidget(hint)

        btn_row = QHBoxLayout()
        keep_btn = QPushButton("Keep all")
        keep_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        keep_btn.setFixedSize(110, 34)
        keep_btn.clicked.connect(self.reject)
        btn_row.addWidget(keep_btn)
        btn_row.addStretch()

        untrack_btn = QPushButton("Untrack selected")
        untrack_btn.setStyleSheet(theme.PLUGIN_ACTION_WARNING_BUTTON_STYLE)
        untrack_btn.setFixedSize(160, 34)
        untrack_btn.clicked.connect(lambda: self._finish(ExtraNodesDecision.UNTRACK))
        btn_row.addWidget(untrack_btn)

        uninstall_btn = QPushButton("Uninstall selected")
        uninstall_btn.setStyleSheet(theme.DANGER_BUTTON_STYLE)
        uninstall_btn.setFixedSize(170, 34)
        uninstall_btn.clicked.connect(lambda: self._finish(ExtraNodesDecision.UNINSTALL))
        btn_row.addWidget(uninstall_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decision(self) -> ExtraNodesDecision:
        """What to do with :meth:`selected_indexes`. ``KEEP`` if dismissed."""
        return self._decision

    def selected_indexes(self) -> list[int]:
        """Indexes (into the ``nodes`` list passed in) still checked."""
        if self._decision is ExtraNodesDecision.KEEP:
            return []
        return [i for i, box in enumerate(self._boxes) if box.isChecked()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _finish(self, decision: ExtraNodesDecision) -> None:
        self._decision = decision
        self.accept()

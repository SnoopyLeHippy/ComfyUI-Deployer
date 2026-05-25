"""Card for a custom node installed in ComfyUI but absent from user_settings."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from deployer.ui import theme
from deployer.ui.widgets.base_card import BaseCard
from deployer.ui.widgets.card_state import CardState


class OrphanNodeCard(BaseCard):
    """Card for a custom node on disk that isn't tracked in user_settings."""

    _MAX_INFO = 70

    def __init__(
        self,
        name: str,
        repo: str,
        ref: str,
        description: str = "",
        on_selection_changed=None,
        from_workflow: bool = False,
        parent=None,
    ):
        self.name = name
        self.repo = repo
        self.ref = ref
        self.description = description

        super().__init__(name, on_selection_changed=on_selection_changed, parent=parent)

        # Workflow-imported orphans are auto-armed: selected (so they're picked
        # up at install) and with their requirements pre-checked.
        self.is_from_workflow = from_workflow
        self.is_selected = from_workflow
        self.is_install_requirements = from_workflow

        self.req_checkbox.setChecked(self.is_install_requirements)
        self.refresh()

    # ------------------------------------------------------------------
    # BaseCard hooks
    # ------------------------------------------------------------------

    def _build_body(self, layout: QVBoxLayout) -> None:
        self.name_label.setStyleSheet(theme.ORPHAN_CARD_NAME_LABEL_STYLE)

        ref_label = QLabel(f"ref: {self.ref}")
        ref_label.setStyleSheet(theme.CARD_REF_LABEL_STYLE)
        ref_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(ref_label)

        if self.description:
            text = self.description
            style = theme.CARD_DESC_LABEL_STYLE
        else:
            text = self.repo if len(self.repo) <= self._MAX_INFO else "…" + self.repo[-(self._MAX_INFO - 1):]
            style = theme.ORPHAN_CARD_REPO_LABEL_STYLE
        if len(text) > self._MAX_INFO and self.description:
            text = text[: self._MAX_INFO - 3] + "..."

        self.repo_label = QLabel(text)
        self.repo_label.setStyleSheet(style)
        self.repo_label.setWordWrap(True)
        self.repo_label.setToolTip(self.repo)
        self.repo_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.repo_label)

    def _current_state(self) -> CardState:
        if self.is_selected and self.is_from_workflow:
            return CardState.IMPORT
        if self.is_selected:
            return CardState.ADD_TO_CONFIG
        return CardState.MISSING

    def _on_requirements_toggled(self, checked: bool) -> None:
        self.is_install_requirements = checked

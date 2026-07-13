"""Selectable card representing a single ComfyUI custom node."""

import os
import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QLabel, QLineEdit, QMenu, QMessageBox, QVBoxLayout

from deployer.core.junctions import replace_with_junction
from deployer.core.node import CustomNode
from deployer.ui import theme
from deployer.ui.widgets.base_card import BaseCard
from deployer.ui.widgets.card_state import CardState


class NodeCard(BaseCard):
    """Selectable card for a custom node tracked in ``user_settings.json``."""

    _MAX_DESC = 60

    def __init__(
        self,
        node: CustomNode,
        on_ref_saved=None,
        on_remove=None,
        on_selection_changed=None,
        parent=None,
    ):
        self.node = node
        self.is_pending_update = False
        self.is_needs_update = False
        self._on_ref_saved = on_ref_saved
        self._on_remove = on_remove

        super().__init__(node.name, on_selection_changed=on_selection_changed, parent=parent)

        self.is_selected = node.is_selected
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.req_checkbox.setChecked(node.is_install_requirements)

        self.refresh()

    # ------------------------------------------------------------------
    # BaseCard hooks
    # ------------------------------------------------------------------

    def _build_body(self, layout: QVBoxLayout) -> None:
        self.name_label.setStyleSheet(theme.CARD_NAME_LABEL_STYLE)

        # Ref label + inline editor (overlay)
        self.ref_label = QLabel(f"ref: {self.node.ref}")
        self.ref_label.setStyleSheet(theme.CARD_REF_LABEL_STYLE)
        self.ref_label.setToolTip("Double-click to edit")
        self.ref_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.ref_label)

        self.ref_edit = QLineEdit(self.node.ref, self)
        self.ref_edit.setStyleSheet(theme.CARD_REF_EDIT_STYLE)
        self.ref_edit.hide()
        self.ref_edit.returnPressed.connect(self._commit_ref)
        self.ref_edit.editingFinished.connect(self._commit_ref)

        # Description
        self.desc_label = QLabel()
        self.desc_label.setStyleSheet(theme.CARD_DESC_LABEL_STYLE)
        self.desc_label.setWordWrap(True)
        self.desc_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.desc_label)

        self.desc_edit = QLineEdit(self.node.description, self)
        self.desc_edit.setStyleSheet(theme.CARD_DESC_EDIT_STYLE)
        self.desc_edit.hide()
        self.desc_edit.returnPressed.connect(self._commit_desc)
        self.desc_edit.editingFinished.connect(self._commit_desc)

        self._refresh_text()

    def _current_state(self) -> CardState:
        node = self.node
        if self.is_selected and node.is_installed:
            return CardState.TO_REMOVE
        if self.is_selected and self.is_from_workflow:
            return CardState.IMPORT
        if self.is_selected:
            return CardState.TO_INSTALL
        if self.is_pending_update and node.is_installed:
            return CardState.TO_UPDATE
        if self.is_needs_update and node.is_installed:
            return CardState.NEED_UPDATE
        if node.is_installed:
            return CardState.INSTALLED
        return CardState.DEFAULT

    def _can_toggle_selection(self) -> bool:
        return True

    def _on_selection_toggled(self) -> None:
        # Clicking a "Need update" card arms it for update rather than
        # selecting the installed node for removal: flip it straight into the
        # "To update" state and swallow the selection toggle.
        if self.is_selected and self.is_needs_update and self.node.is_installed:
            self.is_selected = False
            self.is_needs_update = False
            self.is_pending_update = True
            return
        self.node.is_selected = self.is_selected
        # Entering / leaving "To install" auto-syncs the requirements checkbox
        # (only for not-yet-installed nodes; for installed nodes the checkbox
        # stays independent of selection by design).
        if not self.node.is_installed:
            self.node.is_install_requirements = self.is_selected
            self.req_checkbox.blockSignals(True)
            self.req_checkbox.setChecked(self.is_selected)
            self.req_checkbox.blockSignals(False)

    def _on_requirements_toggled(self, checked: bool) -> None:
        self.node.is_install_requirements = checked

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_text()
        super().refresh()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _refresh_text(self) -> None:
        """Resync ref + description labels and their tooltips with ``self.node``."""
        self.ref_label.setText(f"ref: {self.node.ref}")
        self.ref_label.setStyleSheet(
            theme.CARD_REF_LABEL_PENDING_STYLE
            if self.is_pending_update
            else theme.CARD_REF_LABEL_STYLE
        )

        desc = self.node.description
        truncated = len(desc) > self._MAX_DESC
        self.desc_label.setText(desc[: self._MAX_DESC - 3] + "..." if truncated else desc)
        self._apply_tooltips(truncated)

    def _apply_tooltips(self, desc_is_truncated: bool) -> None:
        self.name_label.setToolTip("")
        self.badge.setToolTip("")
        self.req_checkbox.setToolTip("")
        self.ref_label.setToolTip("Double-click to edit")

        # Labels have WA_TransparentForMouseEvents, so tooltip events bubble up
        # to the card itself — mirror the description tooltip there.
        if desc_is_truncated:
            self.desc_label.setToolTip(self.node.description)
            self.setToolTip(self.node.description)
        else:
            self.desc_label.setToolTip("Double-click to edit")
            self.setToolTip("")

    def _start_ref_edit(self) -> None:
        self.ref_edit.setText(self.node.ref)
        geo = self.ref_label.geometry()
        self.ref_edit.setGeometry(geo.x(), geo.y() - 2, max(geo.width(), 160), geo.height() + 4)
        self.ref_label.hide()
        self.ref_edit.show()
        self.ref_edit.raise_()
        self.ref_edit.setFocus()
        self.ref_edit.selectAll()

    def _commit_ref(self) -> None:
        if not self.ref_edit.isVisible():
            return
        new_ref = self.ref_edit.text().strip()
        self.ref_edit.hide()
        self.ref_label.show()
        if new_ref and new_ref != self.node.ref:
            self.node.ref = new_ref
            if self.node.is_installed:
                self.is_pending_update = True
        self.refresh()
        if self._on_ref_saved:
            self._on_ref_saved()

    def _start_desc_edit(self) -> None:
        self.desc_edit.setText(self.node.description)
        geo = self.desc_label.geometry()
        self.desc_edit.setGeometry(geo.x(), geo.y() - 2, max(geo.width(), 200), geo.height() + 4)
        self.desc_label.hide()
        self.desc_edit.show()
        self.desc_edit.raise_()
        self.desc_edit.setFocus()
        self.desc_edit.selectAll()

    def _commit_desc(self) -> None:
        if not self.desc_edit.isVisible():
            return
        new_desc = self.desc_edit.text().strip()
        self.desc_edit.hide()
        self.desc_label.show()
        if new_desc != self.node.description:
            self.node.description = new_desc
        self._refresh_text()
        if self._on_ref_saved:
            self._on_ref_saved()

    # ------------------------------------------------------------------
    # Qt event overrides (additions on top of BaseCard's)
    # ------------------------------------------------------------------

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Undo the selection toggle fired by the preceding mousePressEvent.
            def _undo_select():
                self.is_selected = not self.is_selected
                self.node.is_selected = self.is_selected
                self.refresh()
            if self.ref_label.geometry().contains(event.pos()):
                _undo_select()
                self._start_ref_edit()
                return
            if self.desc_label.geometry().contains(event.pos()):
                _undo_select()
                self._start_desc_edit()
                return
        super().mouseDoubleClickEvent(event)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(theme.HAMBURGER_MENU_STYLE)
        open_repo_action = QAction("Open repository...", self)
        junction_action = QAction("Replace by junction...", self)
        junction_action.setEnabled(self.node.is_installed)
        remove_action = QAction("Remove from config", self)
        menu.addAction(open_repo_action)
        menu.addAction(junction_action)
        menu.addAction(remove_action)
        action = menu.exec(self.mapToGlobal(pos))
        if action == open_repo_action:
            webbrowser.open(self.node.web_url)
        elif action == junction_action:
            self._replace_by_junction()
        elif action == remove_action and self._on_remove:
            self._on_remove(self)

    def _replace_by_junction(self) -> None:
        """Delete the node's folder in custom_nodes and re-link it via a junction
        to a folder the user picks (e.g. a checkout kept elsewhere on disk)."""
        path = self.node.comfyui_path
        target = QFileDialog.getExistingDirectory(self, "Select folder to link to")
        if not target:
            return
        target = os.path.normpath(target)
        if os.path.normpath(path) == target:
            QMessageBox.warning(self, "Replace by junction", "Target can't be the node's own folder.")
            return
        replace_with_junction(path, target)
        self.node.is_installed = os.path.exists(path)
        print(f"{self.node.name}: replaced by junction -> {target}")
        self.refresh()

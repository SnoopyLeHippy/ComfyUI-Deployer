"""Main window for the ComfyUI Deployer."""

import json
import os
import shutil
import sys
import threading

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSplitterHandle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from deployer.bundle import create_bundle, create_sharable_bat
from deployer.config import CUSTOM_NODES_DIR
from deployer.core.comfy_runner import ComfyRunner
from deployer.core.filesystem import force_remove_readonly
from deployer.core.installer import (
    install,
    install_requirements,
    load_custom_nodes,
)
from deployer.core.junctions import is_junction
from deployer.core.node import CustomNode
from deployer.core.orphans import discover_orphan_nodes
from deployer.core.workflow_resolver import (
    extract_types_from_node_dir,
    extract_workflow_node_types,
)
from deployer.settings import UserSettings
from deployer.ui import theme
from deployer.ui.controllers.install_planner import InstallPlan, plan_install
from deployer.ui.controllers.workflow_resolution import (
    known_repos_from_cards,
    resolve_workflows,
)
from deployer.ui.dialogs import (
    AddNodeDialog,
    AdvancedSettingsDialog,
    CreateBundleDialog,
    MissingNodesDialog,
    WorkflowConflictDialog,
    apply_advanced_settings,
)
from deployer.ui.stdout_redirect import StdoutRedirector
from deployer.ui.widgets import (
    AddNodeButton,
    BusyButton,
    ConsoleOutput,
    NodeCard,
    OrphanNodeCard,
    ResponsiveCardGrid,
)


class _ResizeHandle(QSplitterHandle):
    """Splitter handle drawn as a centered, rounded light-gray bar."""

    BAR_WIDTH = 100
    BAR_HEIGHT = 4
    MARGIN = 4

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setStyleSheet("background: transparent;")
        # Lock the handle's thickness so painting math centers reliably,
        # regardless of QStyleSheetStyle overriding handleWidth.
        if orientation == Qt.Orientation.Vertical:
            self.setFixedHeight(self.BAR_HEIGHT + 2 * self.MARGIN)
        else:
            self.setFixedWidth(self.BAR_HEIGHT + 2 * self.MARGIN)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(
            (self.width() - self.BAR_WIDTH) / 2,
            (self.height() - self.BAR_HEIGHT) / 2,
            self.BAR_WIDTH,
            self.BAR_HEIGHT,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.TEXT_BODY))
        painter.drawRoundedRect(bar, self.BAR_HEIGHT / 2, self.BAR_HEIGHT / 2)


class _BodySplitter(QSplitter):
    """QSplitter that emits _ResizeHandle widgets for its drag handles."""

    def createHandle(self):
        return _ResizeHandle(self.orientation(), self)


class CustomNodeDeployerApp(QMainWindow):
    """PyQt6 application window for managing ComfyUI custom nodes."""

    _comfy_started = pyqtSignal()
    _comfy_stopped = pyqtSignal()
    _orphan_found = pyqtSignal(str, str, str, str, bool)  # name, repo, ref, description, from_workflow
    _workflow_done = pyqtSignal(object)          # dict with resolved/conflicts/unresolved
    _bundle_workflow_resolved = pyqtSignal(object)  # dict for bundle creation path
    _ui_call = pyqtSignal(object)  # marshals a callable onto the UI thread from worker threads

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComfyUI Deployer")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(theme.APP_STYLE)

        central = QWidget()
        central.setObjectName("mainContent")
        self.setCentralWidget(central)
        central.setStyleSheet(theme.MAIN_CONTENT_STYLE)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # -- Header row (50px) -------------------------------------------------
        header_widget = QWidget()
        header_widget.setObjectName("transparentRow")
        header_widget.setFixedHeight(50)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 5, 0, 5)
        header_layout.setSpacing(10)

        # Hamburger menu (left)
        self.menu_btn = QToolButton()
        self.menu_btn.setText("☰")  # ☰
        self.menu_btn.setStyleSheet(theme.HAMBURGER_BUTTON_STYLE)
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.hamburger_menu = QMenu(self.menu_btn)
        self.hamburger_menu.setStyleSheet(theme.HAMBURGER_MENU_STYLE)
        self.action_settings = QAction("Advanced settings...", self)
        self.action_load_config = QAction("Load Configuration...", self)
        self.action_export_config = QAction("Export Configuration...", self)
        self.action_create_bundle = QAction("Create Bundle...", self)
        self.hamburger_menu.addAction(self.action_settings)
        self.hamburger_menu.addSeparator()
        self.hamburger_menu.addAction(self.action_load_config)
        self.hamburger_menu.addAction(self.action_export_config)
        self.hamburger_menu.addSeparator()
        self.hamburger_menu.addAction(self.action_create_bundle)
        self.action_settings.triggered.connect(self._on_advanced_settings)
        self.action_export_config.triggered.connect(self._on_export_config)
        self.action_load_config.triggered.connect(self._on_load_config)
        self.action_create_bundle.triggered.connect(self._on_create_bundle)
        self.menu_btn.setMenu(self.hamburger_menu)

        subtitle = QLabel("Select nodes to install or update")
        subtitle.setStyleSheet(theme.SUBTITLE_STYLE)

        header_layout.addWidget(self.menu_btn)
        header_layout.addStretch()
        header_layout.addWidget(subtitle)
        main_layout.addWidget(header_widget)

        # -- Scrollable node grid + console (resizable, default 75% / 25%) -----
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(theme.SCROLL_AREA_STYLE)

        self.card_grid = ResponsiveCardGrid()
        self.scroll_area.setWidget(self.card_grid)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Listen to viewport resizes to reliably reflow the card grid
        self.scroll_area.viewport().installEventFilter(self)

        self.console = ConsoleOutput()

        self.body_splitter = _BodySplitter(Qt.Orientation.Vertical)
        self.body_splitter.setStyleSheet("QSplitter { background: transparent; }")
        # Total handle height = 4 px margin + 4 px bar + 4 px margin = 12 px
        self.body_splitter.setHandleWidth(12)
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.addWidget(self.scroll_area)
        self.body_splitter.addWidget(self.console)
        self.body_splitter.setStretchFactor(0, 3)
        self.body_splitter.setStretchFactor(1, 1)
        self._splitter_sized = False
        main_layout.addWidget(self.body_splitter, 1)

        # -- Install button row (60px) -----------------------------------------
        btn_row = QWidget()
        btn_row.setObjectName("transparentRow")
        btn_row.setFixedHeight(60)
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 10, 0, 0)
        btn_layout.setSpacing(10)
        self.install_btn = BusyButton("Update")
        self.install_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        self.install_btn.setFixedSize(100, 40)
        self.install_btn.setDisabled(True)
        self.install_btn.clicked.connect(self._on_install)
        self.run_comfy_btn = QPushButton("Run Comfy")
        self.run_comfy_btn.setStyleSheet(theme.RUN_COMFY_BUTTON_STYLE)
        self.run_comfy_btn.setFixedSize(120, 40)
        self.run_comfy_btn.clicked.connect(self._on_run_comfy)
        btn_layout.addStretch()
        btn_layout.addWidget(self.install_btn)
        btn_layout.addWidget(self.run_comfy_btn)
        main_layout.addWidget(btn_row)

        # Redirect stdout/stderr — stderr lines render as errors (red).
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = StdoutRedirector(self.console)
        sys.stderr = StdoutRedirector(self.console, is_error=True)

        # Comfy process state signals
        self._comfy_started.connect(self._on_comfy_started)
        self._comfy_stopped.connect(self._on_comfy_stopped)
        self._orphan_found.connect(self._add_orphan_card)
        self._workflow_done.connect(self._on_workflow_done)
        self._bundle_workflow_resolved.connect(self._on_bundle_workflow_resolved)
        # Queued (cross-thread) connection: emitting from a worker thread runs the
        # callable on the UI thread. QTimer.singleShot does NOT work here because
        # worker threads have no Qt event loop.
        self._ui_call.connect(lambda fn: fn())

        # ComfyUI subprocess runner: callbacks emit signals so they run on the UI thread
        self._comfy_runner = ComfyRunner(
            on_started=self._comfy_started.emit,
            on_stopped=self._comfy_stopped.emit,
        )

        # -- Load nodes -----------------------------------------------------
        self._node_cards: list[NodeCard] = []
        self._orphan_cards: list[OrphanNodeCard] = []
        self._pending_orphan_promotions: list = []
        self._load_nodes()

    def _load_nodes(self):
        nodes = load_custom_nodes()
        for node in nodes:
            card = NodeCard(
                node,
                on_ref_saved=self._save_user_settings,
                on_remove=self._on_remove_card,
                on_selection_changed=self._refresh_install_btn,
            )
            self.card_grid.add_card(card)
            self._node_cards.append(card)
        # Add '+' button at the end of the grid
        self.add_node_btn = AddNodeButton(self._on_add_node)
        self.card_grid.set_add_button(self.add_node_btn)
        # Trigger an initial layout based on the actual viewport width
        self.card_grid.update_cols(self.scroll_area.viewport().width())
        # Check installed refs and discover orphan nodes in background
        threading.Thread(target=self._check_refs, daemon=True).start()
        threading.Thread(target=self._discover_orphans, daemon=True).start()

    def _discover_orphans(self):
        """Background thread: find nodes installed in ComfyUI but not in user_settings."""
        known_names = {os.path.basename(card.node.repo) for card in self._node_cards}
        orphans = discover_orphan_nodes(known_names)
        for name, repo, ref in orphans:
            self._orphan_found.emit(name, repo, ref, "", False)

    def _add_orphan_card(self, name: str, repo: str, ref: str, description: str, from_workflow: bool):
        """UI-thread: create and register an OrphanNodeCard."""
        card = OrphanNodeCard(
            name, repo, ref, description,
            on_selection_changed=self._refresh_install_btn,
            from_workflow=from_workflow,
        )
        self.card_grid.add_card(card)
        self._orphan_cards.append(card)
        if from_workflow:
            self._refresh_install_btn()

    def _check_refs(self):
        """Background thread: mark installed nodes whose ref has drifted as pending update."""
        for card in list(self._node_cards):
            if card.node.has_gitlab_config_error or not card.node.is_installed:
                continue
            if not card.node.is_ref_current():
                def _mark(c=card):
                    c.is_pending_update = True
                    c.refresh()
                    self._refresh_install_btn()
                self._ui_call.emit(_mark)

    def eventFilter(self, obj, event):
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            self.card_grid.update_cols(event.size().width())
        return super().eventFilter(obj, event)

    def _set_busy(self, busy: bool) -> None:
        """Toggle the global "long task in progress" state.

        Disables Update, Run Comfy, and the Create Bundle menu action, and
        animates the Update button's spinner. Shared by the install pipeline
        and the bundle pipeline so the two can't be triggered concurrently.
        """
        self.install_btn.set_busy(busy)
        self.install_btn.setDisabled(busy)
        self.run_comfy_btn.setDisabled(busy)
        self.action_create_bundle.setEnabled(not busy)
        if not busy:
            # Re-derive Update button state from the current card selection.
            self._refresh_install_btn()

    def _on_install(self):
        self._set_busy(True)
        threading.Thread(target=self._run_install, daemon=True).start()

    def _run_install(self):
        try:
            plan = plan_install(self._node_cards, self._orphan_cards)
            self._execute_plan(plan)
            print("Done!")
        finally:
            self._ui_call.emit(self._refresh_cards)

    def _execute_plan(self, plan: InstallPlan) -> None:
        """Run an :class:`InstallPlan`. Order matters: errors → uninstall →
        ref-bump → install (with requirements) → orphan promotion."""
        for node in plan.invalid_gitlab:
            print(f"Error: {node.gitlab_config_error_message}")

        for node in plan.to_uninstall:
            self._uninstall_node(node)

        for card in plan.to_update:
            print(f"Updating {card.node.name} to ref '{card.node.ref}'...")
            card.node.clone()

        install(plan.to_install, plan.with_requirements)

        if plan.selected_orphans:
            self._promote_selected_orphans(plan.selected_orphans)

    def _promote_selected_orphans(self, selected_orphans) -> None:
        """Clone+link each selected orphan and queue it for the post-install promotion."""
        promotions = []
        for orphan in selected_orphans:
            node = CustomNode(orphan.repo, orphan.ref, orphan.name)
            if not os.path.exists(node.comfyui_path):
                node.clone()
                node.link()
            node.is_installed = True
            promotions.append((orphan, node))
            if orphan.is_install_requirements:
                install_requirements([node])
            print(f"Adding '{orphan.name}' to settings...")
        self._pending_orphan_promotions = promotions

    def _refresh_cards(self):
        """Resync each card's state from disk and redraw."""
        # Promote any orphan cards that were just added to settings
        if self._pending_orphan_promotions:
            for orphan_card, node in self._pending_orphan_promotions:
                self.card_grid.remove_card(orphan_card)
                if orphan_card in self._orphan_cards:
                    self._orphan_cards.remove(orphan_card)
                card = NodeCard(
                    node,
                    on_ref_saved=self._save_user_settings,
                    on_remove=self._on_remove_card,
                    on_selection_changed=self._refresh_install_btn,
                )
                self.card_grid.add_card(card)
                self._node_cards.append(card)
            self._pending_orphan_promotions = []
            self._save_user_settings()

        for card in self._node_cards:
            card.node.is_installed = os.path.exists(card.node.comfyui_path)
            card.is_selected = False
            card.node.is_selected = False
            card.is_pending_update = False
            card.is_from_workflow = False
            card.node.is_install_requirements = False
            card.req_checkbox.setChecked(False)
            card.refresh()
        self._set_busy(False)

    def _on_advanced_settings(self):
        """Open the Advanced Settings dialog and apply changes on OK."""
        dialog = AdvancedSettingsDialog(UserSettings.load_settings(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            UserSettings.save_settings(dialog.applied_settings())

    def _on_create_bundle(self):
        """Open the Create Bundle dialog and run bundle creation in a background thread.

        When workflows are provided, missing custom nodes are resolved against
        the ComfyUI-Manager DB first so the bundle is self-contained even if
        some workflow nodes aren't installed locally.
        """
        dialog = CreateBundleDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dest = dialog.dest_path()
        wf_paths = dialog.workflow_paths()
        include_debugger = dialog.include_debugger()
        include_models = dialog.include_models()
        include_workflows = dialog.include_workflows()
        export_as_bat = dialog.export_as_bat()
        export_advanced = dialog.export_advanced_settings()

        # Lock the UI for the whole pipeline: resolution → conflict dialog →
        # actual build. Every exit path below must call ``_clear_busy``.
        self._set_busy(True)

        if wf_paths:
            # Resolve regardless of output type: even the .bat needs the extra
            # repos for workflow nodes that aren't installed locally.
            print("Resolving workflow nodes for bundle...")
            threading.Thread(
                target=self._resolve_workflows_for_bundle,
                args=(dest, wf_paths, include_debugger, export_as_bat, export_advanced, include_models, include_workflows),
                daemon=True,
            ).start()
        elif export_as_bat:
            print(f"Exporting sharable installer to {dest}...")
            threading.Thread(
                target=self._run_create_sharable_bat,
                args=(dest, wf_paths, export_advanced, [], False),
                daemon=True,
            ).start()
        else:
            print(f"Creating bundle at {dest}...")
            threading.Thread(
                target=self._run_create_bundle,
                args=(dest, wf_paths, include_debugger, [], include_models, False),
                daemon=True,
            ).start()

    def _clear_busy(self) -> None:
        """Marshall a busy-state reset onto the UI thread (call from any thread)."""
        self._ui_call.emit(lambda: self._set_busy(False))

    def _resolve_workflows_for_bundle(
        self,
        dest: str,
        wf_paths: list[str],
        include_debugger: bool,
        export_as_bat: bool = False,
        export_advanced: bool = False,
        include_models: bool = False,
        include_workflows: bool = False,
    ):
        """Background thread: resolve workflow node types across all selected workflows."""
        try:
            known_repos = known_repos_from_cards(self._node_cards, self._orphan_cards)
            merged = resolve_workflows(wf_paths, known_repos)
        except Exception as exc:
            print(f"Error resolving workflow for bundle: {exc}")
            self._clear_busy()
            return

        self._bundle_workflow_resolved.emit({
            "dest": dest,
            "wf_paths": wf_paths,
            "include_debugger": include_debugger,
            "export_as_bat": export_as_bat,
            "export_advanced": export_advanced,
            "include_models": include_models,
            "include_workflows": include_workflows,
            # Bundle flow only needs the {repo: description} mapping for cloning.
            "resolved": {entry.repo: entry.description for entry in merged.resolved},
            "conflicts": merged.conflicts,
            "unresolved": sorted(merged.unresolved),
            "repo_to_desc": merged.repo_to_desc,
        })

    def _on_bundle_workflow_resolved(self, data: dict):
        """UI thread: resolve conflicts if any, then kick off the bundle build with extras."""
        dest = data["dest"]
        wf_paths = data["wf_paths"]
        include_debugger = data["include_debugger"]
        export_as_bat = data.get("export_as_bat", False)
        export_advanced = data.get("export_advanced", False)
        include_models = data.get("include_models", False)
        include_workflows = data.get("include_workflows", False)
        resolved: dict[str, str] = data["resolved"]
        conflicts = data["conflicts"]
        unresolved = data["unresolved"]

        for u in unresolved:
            print(f"Warning: unresolved workflow node type (not in DB, will be missing from bundle): {u}")

        extra_repos: list[tuple[str, str]] = [(repo, "main") for repo in resolved]

        if conflicts:
            dialog = WorkflowConflictDialog(conflicts, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                print("Bundle creation cancelled (workflow conflicts not resolved).")
                self._set_busy(False)
                return
            for repo, _ in dialog.selections():
                extra_repos.append((repo, "main"))

        if extra_repos:
            print(f"Workflow resolution: {len(extra_repos)} extra node(s) will be cloned into the bundle.")

        if export_as_bat:
            print(f"Exporting sharable installer to {dest}...")
            threading.Thread(
                target=self._run_create_sharable_bat,
                args=(dest, wf_paths, export_advanced, extra_repos, include_workflows),
                daemon=True,
            ).start()
            return

        print(f"Creating bundle at {dest}...")
        threading.Thread(
            target=self._run_create_bundle,
            args=(dest, wf_paths, include_debugger, extra_repos, include_models, include_workflows),
            daemon=True,
        ).start()

    def _run_create_bundle(
        self,
        dest: str,
        wf_paths: list[str],
        include_debugger: bool = False,
        extra_repos: list[tuple[str, str]] | None = None,
        include_models: bool = False,
        include_workflows: bool = False,
    ):
        try:
            create_bundle(
                dest,
                wf_paths,
                include_debugger,
                extra_repos or [],
                include_models,
                include_workflows=include_workflows,
            )
            print("Bundle created.")
        except Exception as exc:
            print(f"Error creating bundle: {exc}")
        finally:
            self._clear_busy()

    def _run_create_sharable_bat(
        self,
        dest: str,
        wf_paths: list[str],
        export_advanced: bool = False,
        extra_repos: list[tuple[str, str]] | None = None,
        include_workflows: bool = False,
    ):
        try:
            bat_path = create_sharable_bat(
                dest,
                wf_paths,
                export_advanced=export_advanced,
                extra_repos=extra_repos or [],
                include_workflows=include_workflows,
            )
            print(f"Sharable installer created: {bat_path}")
        except Exception as exc:
            print(f"Error creating sharable installer: {exc}")
        finally:
            self._clear_busy()

    def _ask_yes_no(self, title: str, text: str) -> bool:
        """Themed Yes/No confirmation. Returns True on Yes."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Question)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setStyleSheet(theme.APP_STYLE)
        return box.exec() == QMessageBox.StandardButton.Yes

    @staticmethod
    def _canonical_repo(url: str) -> str:
        """Tolerant key for comparing repo URLs across case / trailing slash / .git."""
        return url.strip().rstrip("/").removesuffix(".git").lower()

    def _on_export_config(self):
        """Open a Save dialog and write the current configuration to a JSON file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Configuration",
            os.path.expanduser("~"),
            "JSON Files (*.json)",
        )
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"

        include_settings = self._ask_yes_no(
            "Export Configuration",
            "Include advanced settings (model / output / input folders, "
            "extra model paths) in the exported file?",
        )

        config: dict = {
            "nodes": [
                {"repo": card.node.repo, "ref": card.node.ref, "description": card.node.description}
                for card in self._node_cards
            ],
        }
        if include_settings:
            config["settings"] = UserSettings.load_settings()

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=4, ensure_ascii=False)
        print(
            f"Configuration exported to {path}"
            f"{' (with advanced settings)' if include_settings else ''}"
        )

    def _on_load_config(self):
        """Open a file dialog and load node configuration from a JSON file.

        Classification per loaded entry (matched against existing cards by
        canonical repo URL):

        * Existing + installed + ref changed → marked "To update".
        * Existing + not installed → marked "To install" with requirements on.
        * Not present locally → a new "To install" card is created.

        Locally tracked nodes absent from the loaded config are marked for
        removal (the existing behaviour), and surfaced via
        :class:`MissingNodesDialog`.

        If the loaded JSON has a ``settings`` subdict, the user is prompted
        about importing it via :func:`apply_advanced_settings`.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Configuration",
            os.path.expanduser("~"),
            "JSON Files (*.json)",
        )
        if not path:
            return

        with open(path, "r", encoding="utf-8") as fh:
            config = json.load(fh)

        loaded_entries = config.get("nodes", [])
        existing_by_repo = {self._canonical_repo(c.node.repo): c for c in self._node_cards}
        loaded_keys: set[str] = set()

        update_count = 0
        install_count = 0

        for entry in loaded_entries:
            repo = entry.get("repo")
            if not repo:
                continue
            key = self._canonical_repo(repo)
            loaded_keys.add(key)
            new_ref = entry.get("ref", "main")
            new_desc = entry.get("description", "")

            card = existing_by_repo.get(key)
            if card is None:
                # Not tracked locally → create a fresh "To install" card.
                self._add_imported_node(repo, new_ref, new_desc)
                install_count += 1
                continue

            # Existing card: refresh metadata, then decide install vs update.
            if card.node.is_installed:
                if new_ref != card.node.ref:
                    card.is_pending_update = True
                    update_count += 1
            else:
                # Tracked but not on disk → arm it for install.
                card.is_selected = True
                card.node.is_selected = True
                card.node.is_install_requirements = True
                card.req_checkbox.blockSignals(True)
                card.req_checkbox.setChecked(True)
                card.req_checkbox.blockSignals(False)
                install_count += 1
            card.node.ref = new_ref
            card.node.description = new_desc
            card.refresh()

        # Cards present locally but absent from the loaded config → "To remove".
        extra_cards = [c for c in self._node_cards if self._canonical_repo(c.node.repo) not in loaded_keys]
        for card in extra_cards:
            card.is_selected = True
            card.node.is_selected = True
            card.refresh()
        if extra_cards:
            MissingNodesDialog([c.node.name for c in extra_cards], self).exec()

        self._save_user_settings()
        self._refresh_install_btn()

        print(
            f"Configuration loaded from {path} "
            f"({update_count} to update, {install_count} to install, "
            f"{len(extra_cards)} marked to remove)."
        )

        # Offer to apply imported advanced settings, if any.
        loaded_settings = config.get("settings")
        if loaded_settings and self._ask_yes_no(
            "Import advanced settings",
            "This configuration includes advanced settings "
            "(folder junctions, extra model paths).\n\nApply them now?",
        ):
            apply_advanced_settings(loaded_settings)
            UserSettings.save_settings(loaded_settings)
            print("Advanced settings imported.")

    def _add_imported_node(self, repo: str, ref: str, description: str) -> None:
        """Create a new NodeCard pre-armed for install. Used by load-config."""
        node = CustomNode(repo, ref, description)
        node.is_selected = True
        node.is_install_requirements = True
        card = NodeCard(
            node,
            on_ref_saved=self._save_user_settings,
            on_remove=self._on_remove_card,
            on_selection_changed=self._refresh_install_btn,
        )
        card.is_selected = True
        card.req_checkbox.blockSignals(True)
        card.req_checkbox.setChecked(True)
        card.req_checkbox.blockSignals(False)
        card.refresh()
        self.card_grid.add_card(card)
        self._node_cards.append(card)

    def _on_add_from_workflow(self):
        """Open one or more workflows (JSON or ComfyUI image) and create orphan cards for unknown nodes."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add from workflow",
            os.path.expanduser("~"),
            "ComfyUI Workflows (*.json *.png *.webp *.jpg *.jpeg);;All Files (*)",
        )
        if not paths:
            return
        if len(paths) == 1:
            print(f"Scanning workflow: {paths[0]}")
        else:
            print(f"Scanning {len(paths)} workflows:")
            for p in paths:
                print(f"  - {p}")
        # Lock the UI while the scan runs; cleared in _on_workflow_done or on error.
        self._set_busy(True)
        threading.Thread(
            target=self._resolve_workflow,
            args=(paths,),
            daemon=True,
        ).start()

    def _resolve_workflow(self, workflow_paths: list[str]):
        """Background thread: resolve workflow nodes against the ltdrdata DB."""
        try:
            # Only treat installed repos as "known" so that tracked-but-not-installed
            # nodes are returned in resolved/conflicts for the UI to handle.
            known_repos = known_repos_from_cards(self._node_cards, self._orphan_cards)
            merged = resolve_workflows(workflow_paths, known_repos)
            referenced_orphans = self._orphans_referenced_by_workflows(workflow_paths)
        except Exception as exc:
            print(f"Error scanning workflow: {exc}")
            self._clear_busy()
            return
        self._workflow_done.emit({
            "resolved": merged.resolved,
            "conflicts": merged.conflicts,
            "unresolved": merged.unresolved,
            "repo_to_desc": merged.repo_to_desc,
            "referenced_orphans": referenced_orphans,
        })

    def _orphans_referenced_by_workflows(self, workflow_paths: list[str]) -> list[str]:
        """Names of orphan cards whose on-disk nodes are used by any of the workflows.

        Lets the workflow scan flip already-installed-but-untracked nodes into
        the ADD_TO_CONFIG state alongside the regular resolve/conflict pass.
        """
        if not self._orphan_cards:
            return []
        workflow_types: set[str] = set()
        for wf in workflow_paths:
            try:
                workflow_types |= extract_workflow_node_types(wf)
            except Exception as exc:  # noqa: BLE001
                print(f"Warning: could not parse '{wf}' for orphan matching: {exc}")
        if not workflow_types:
            return []

        referenced: list[str] = []
        for card in self._orphan_cards:
            node_dir = os.path.join(CUSTOM_NODES_DIR, card.name)
            if extract_types_from_node_dir(node_dir) & workflow_types:
                referenced.append(card.name)
        return referenced

    def _on_workflow_done(self, result: dict):
        """UI thread: add orphan cards for resolved repos, prompt for conflicts."""
        try:
            self._apply_workflow_result(result)
        finally:
            self._set_busy(False)

    def _apply_workflow_result(self, result: dict) -> None:
        resolved = result["resolved"]
        conflicts = result["conflicts"]
        unresolved = result["unresolved"]
        repo_to_desc: dict[str, str] = result.get("repo_to_desc", {})
        referenced_orphans: list[str] = result.get("referenced_orphans", [])

        # Orphan cards (installed-but-not-tracked nodes) referenced by the
        # workflow are flipped into ADD_TO_CONFIG — the node is already on
        # disk, so install isn't needed, only adding it to user_settings.
        orphan_by_name = {card.name: card for card in self._orphan_cards}
        promoted_orphans = 0
        for orphan_name in referenced_orphans:
            card = orphan_by_name.get(orphan_name)
            if card is None or card.is_selected:
                continue
            card.is_selected = True
            card.is_from_workflow = False
            card.refresh()
            print(f"'{orphan_name}' is installed but not tracked — marking for 'Add to config'.")
            promoted_orphans += 1
        if promoted_orphans:
            self._refresh_install_btn()

        if not resolved and not conflicts and not unresolved:
            if promoted_orphans == 0:
                print("Workflow only uses nodes already tracked — nothing to add.")
            return

        # Build a lookup of uninstalled tracked cards by normalised repo URL / basename
        uninstalled_cards: dict[str, "NodeCard"] = {}
        for card in self._node_cards:
            if not card.node.is_installed:
                key = card.node.repo.rstrip("/").removesuffix(".git").lower()
                uninstalled_cards[key] = card
                basename = key.rsplit("/", 1)[-1]
                uninstalled_cards.setdefault(basename, card)

        def _handle_repo(repo: str, node_types: list[str], description: str = "") -> None:
            """Select an existing uninstalled card, or create a new orphan card."""
            key = repo.rstrip("/").removesuffix(".git").lower()
            basename = key.rsplit("/", 1)[-1]
            card = uninstalled_cards.get(key) or uninstalled_cards.get(basename)
            if card is not None:
                print(
                    f"'{card.node.name}' is tracked but not installed — "
                    f"selecting for install: {', '.join(node_types)}"
                )
                card.is_selected = True
                card.node.is_selected = True
                card.is_from_workflow = True
                card.node.is_install_requirements = True
                card.req_checkbox.blockSignals(True)
                card.req_checkbox.setChecked(True)
                card.req_checkbox.blockSignals(False)
                card.refresh()
                self._refresh_install_btn()
            else:
                name = os.path.basename(repo.rstrip("/").removesuffix(".git"))
                print(f"Found '{name}': {', '.join(node_types)}")
                self._orphan_found.emit(name, repo, "main", description, True)

        for entry in resolved:
            _handle_repo(entry.repo, entry.node_types, entry.description)

        if conflicts:
            dialog = WorkflowConflictDialog(conflicts, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                for repo, node_types in dialog.selections():
                    _handle_repo(repo, node_types, repo_to_desc.get(repo, ""))

        for ntype in unresolved:
            print(f"Unresolved node type (not found in DB): {ntype}")

        print(
            f"Workflow scan complete: {len(resolved)} auto-resolved, "
            f"{len(conflicts)} conflict(s), {len(unresolved)} unresolved, "
            f"{promoted_orphans} orphan(s) to add to config."
        )

    def _refresh_install_btn(self):
        """Enable Install (blue) if any card is selected, pending update, or has requirements to install."""
        active = any(
            not c.node.has_gitlab_config_error and (
                c.is_selected or c.is_pending_update
                or (c.node.is_install_requirements and c.node.is_installed)
            )
            for c in self._node_cards
        ) or any(c.is_selected or c.is_install_requirements for c in self._orphan_cards)
        self.install_btn.setEnabled(active)
        if active:
            self.install_btn.setStyleSheet(theme.INSTALL_BUTTON_ACTIVE_STYLE)
        else:
            self.install_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)

    def _save_user_settings(self):
        """Persist current node list to user_settings.json.

        Note: this overwrites the file with only the ``nodes`` key, dropping
        any existing ``settings`` subdict — see :meth:`UserSettings.save_nodes`.
        """
        UserSettings.save_nodes([
            {"repo": card.node.repo, "ref": card.node.ref, "description": card.node.description}
            for card in self._node_cards
        ])

    def _on_remove_card(self, card):
        """Remove a card from the config.

        If the node is installed on disk, demote it to a 'Missing' orphan card
        (still visible, can be re-added later). Otherwise drop it from the grid.
        Either way, persist user_settings without this node.
        """
        node = card.node
        self.card_grid.remove_card(card)
        if card in self._node_cards:
            self._node_cards.remove(card)
        if node.is_installed:
            self._add_orphan_card(node.name, node.repo, node.ref, node.description, False)
            print(f"{node.name} removed from config (still installed — now 'Missing').")
        else:
            print(f"{node.name} removed from config.")
        self._save_user_settings()

    def _on_add_node(self):
        """Show a popup menu with the two ways of adding a node."""
        menu = QMenu(self)
        menu.setStyleSheet(theme.HAMBURGER_MENU_STYLE)
        action_from_url = QAction("Add from URL...", self)
        action_from_workflow = QAction("Add from workflow(s)...", self)
        menu.addAction(action_from_url)
        menu.addAction(action_from_workflow)
        action_from_url.triggered.connect(self._on_add_from_url)
        action_from_workflow.triggered.connect(self._on_add_from_workflow)
        pos = self.add_node_btn.mapToGlobal(self.add_node_btn.rect().bottomLeft())
        menu.exec(pos)

    def _on_add_from_url(self):
        """Open the Add Node dialog and create a card for the new node."""
        dialog = AddNodeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        repo, ref, description = dialog.values()
        node = CustomNode(repo, ref, description)
        card = NodeCard(
            node,
            on_ref_saved=self._save_user_settings,
            on_remove=self._on_remove_card,
            on_selection_changed=self._refresh_install_btn,
        )
        # Pre-select it as 'To install'
        card.is_selected = True
        node.is_selected = True
        card.refresh()
        self.card_grid.add_card(card)
        self._node_cards.append(card)
        self._save_user_settings()
        print(f"Added node: {node.name} (ref: {ref})")

    @staticmethod
    def _uninstall_node(node: CustomNode):
        """Remove the node's ComfyUI path: delete junction or full directory."""
        path = node.comfyui_path
        if not os.path.exists(path):
            print(f"{node.name}: path not found, nothing to remove.")
            return
        if is_junction(path):
            print(f"Removing junction: {path}")
            os.rmdir(path)
        else:
            print(f"Removing directory: {path}")
            shutil.rmtree(path, onerror=force_remove_readonly)
        print(f"{node.name} removed.")

    def _on_comfy_started(self):
        self.run_comfy_btn.setText("Stop Comfy")
        self.run_comfy_btn.setStyleSheet(theme.STOP_COMFY_BUTTON_STYLE)

    def _on_comfy_stopped(self):
        self.run_comfy_btn.setText("Run Comfy")
        self.run_comfy_btn.setStyleSheet(theme.RUN_COMFY_BUTTON_STYLE)

    def _on_run_comfy(self):
        self._comfy_runner.toggle()

    def showEvent(self, event):
        super().showEvent(event)
        # Defer once: setStretchFactor doesn't control initial sizes, so set the
        # 75/25 split after the splitter has its actual height.
        if not self._splitter_sized:
            self._splitter_sized = True
            QTimer.singleShot(0, self._apply_splitter_ratio)

    def _apply_splitter_ratio(self):
        h = self.body_splitter.height()
        if h > 0:
            self.body_splitter.setSizes([int(h * 0.75), int(h * 0.25)])

    def closeEvent(self, event):
        self._comfy_runner.stop()
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        event.accept()


def run():
    """Launch the application."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = CustomNodeDeployerApp()
    window.showMaximized()
    sys.exit(app.exec())

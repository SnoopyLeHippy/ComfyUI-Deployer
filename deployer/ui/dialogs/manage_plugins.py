"""Dialog for managing bundle-step plugins (local and remote)."""

import os
import shutil

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from deployer.config import PROJECT_ROOT
from deployer.plugins import load_plugins, repo_dir_name
from deployer.settings import UserSettings
from deployer.ui import theme

_LOCAL_DIR = os.path.join(PROJECT_ROOT, "plugins")
_REMOTE_DIR = os.path.join(_LOCAL_DIR, "remote")


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _CloneWorker(QThread):
    done = pyqtSignal(str)  # "ok" or "error: <message>"

    def __init__(self, repo: str, ref: str, dest: str):
        super().__init__()
        self._repo, self._ref, self._dest = repo, ref, dest

    def run(self):
        from deployer.core import git_ops
        try:
            git_ops.clone(
                self._repo, self._dest,
                cwd=os.path.dirname(self._dest),
                recursive=False,
            )
            if self._ref and self._ref not in ("main", "HEAD"):
                git_ops.checkout(self._ref, cwd=self._dest, check=False)
            self.done.emit("ok")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(f"error: {exc}")


class _UpdateWorker(QThread):
    done = pyqtSignal(str)  # "ok" or "error: <message>"

    def __init__(self, cwd: str):
        super().__init__()
        self._cwd = cwd

    def run(self):
        from deployer.core import git_ops
        try:
            git_ops.pull(self._cwd)
            self.done.emit("ok")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(f"error: {exc}")


# ---------------------------------------------------------------------------
# Add-plugin sub-dialog
# ---------------------------------------------------------------------------

class _AddPluginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Remote Plugin")
        self.setMinimumWidth(460)
        self.setStyleSheet(theme.APP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        lbl = QLabel("Git Repository URL")
        lbl.setStyleSheet(theme.SECTION_TITLE_STYLE)
        layout.addWidget(lbl)
        self._repo_edit = QLineEdit()
        self._repo_edit.setPlaceholderText("https://github.com/author/my-comfy-plugin")
        self._repo_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        layout.addWidget(self._repo_edit)

        lbl2 = QLabel("Branch / tag / commit")
        lbl2.setStyleSheet(theme.SECTION_TITLE_STYLE)
        layout.addWidget(lbl2)
        self._ref_edit = QLineEdit("main")
        self._ref_edit.setStyleSheet(theme.DIALOG_TEXTBOX_STYLE)
        layout.addWidget(self._ref_edit)

        layout.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        cancel.setFixedSize(90, 34)
        cancel.clicked.connect(self.reject)
        self._add_btn = QPushButton("Add")
        self._add_btn.setStyleSheet(theme.RUN_COMFY_BUTTON_STYLE)
        self._add_btn.setFixedSize(90, 34)
        self._add_btn.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self._add_btn)
        layout.addLayout(row)

        self._repo_edit.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        self._add_btn.setEnabled(bool(self._repo_edit.text().strip()))

    def values(self) -> tuple[str, str]:
        return (
            self._repo_edit.text().strip(),
            self._ref_edit.text().strip() or "main",
        )


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class ManagePluginsDialog(QDialog):
    """Dialog to add, update, and remove bundle-step plugins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Plugins")
        self.setMinimumWidth(580)
        self.setMinimumHeight(420)
        self.setStyleSheet(theme.APP_STYLE)

        self._workers: list[QThread] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)

        # --- Header ---
        title = QLabel("Manage Plugins")
        title.setStyleSheet(theme.MAIN_TITLE_STYLE)
        outer.addWidget(title)

        desc = QLabel(
            "Local plugins: .py files in the plugins/ folder (gitignored, private). "
            "Remote plugins: git repos cloned into plugins/remote/."
        )
        desc.setStyleSheet(theme.HELP_TEXT_STYLE)
        desc.setWordWrap(True)
        outer.addWidget(desc)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(theme.SEPARATOR_STYLE)
        outer.addWidget(sep)

        # --- Add button + status ---
        add_row = QHBoxLayout()
        self._add_btn = QPushButton("＋ Add remote plugin")
        self._add_btn.setStyleSheet(theme.BROWSE_BUTTON_STYLE)
        self._add_btn.setFixedHeight(32)
        self._add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._add_btn)
        add_row.addStretch()
        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(theme.HELP_TEXT_STYLE)
        add_row.addWidget(self._status_lbl)
        outer.addLayout(add_row)

        # --- Scrollable list ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_container = QWidget()
        self._list_vbox = QVBoxLayout(self._list_container)
        self._list_vbox.setContentsMargins(0, 0, 4, 0)
        self._list_vbox.setSpacing(8)
        scroll.setWidget(self._list_container)
        outer.addWidget(scroll, 1)

        # --- Footer ---
        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        close_btn.setFixedSize(90, 34)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

        self._rebuild_list()

    # ------------------------------------------------------------------ List

    def _rebuild_list(self):
        """Clear and repopulate the plugin list from disk and settings."""
        while self._list_vbox.count():
            item = self._list_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        local_files = self._local_plugin_files()
        remote_entries = self._remote_plugin_entries()

        if local_files:
            self._list_vbox.addWidget(self._section_label("Local plugins"))
            for fname in local_files:
                self._list_vbox.addWidget(self._local_card(fname))

        if remote_entries:
            self._list_vbox.addWidget(self._section_label("Remote plugins"))
            for name, repo, ref, present in remote_entries:
                self._list_vbox.addWidget(self._remote_card(name, repo, ref, present))

        if not local_files and not remote_entries:
            empty = QLabel(
                "No plugins installed yet.\n"
                "Add a remote plugin with the button above, or drop a .py file in plugins/."
            )
            empty.setStyleSheet(theme.HELP_TEXT_STYLE)
            empty.setWordWrap(True)
            self._list_vbox.addWidget(empty)

        self._list_vbox.addStretch()

    def _local_plugin_files(self) -> list[str]:
        if not os.path.isdir(_LOCAL_DIR):
            return []
        return sorted(
            f for f in os.listdir(_LOCAL_DIR)
            if f.endswith(".py") and not f.startswith("_")
        )

    def _remote_plugin_entries(self) -> list[tuple[str, str, str, bool]]:
        """Return (name, repo, ref, on_disk) for every known remote plugin."""
        saved = {
            repo_dir_name(r["repo"]): r
            for r in UserSettings.load_plugin_repos()
            if r.get("repo")
        }
        on_disk: set[str] = set()
        if os.path.isdir(_REMOTE_DIR):
            on_disk = {
                n for n in os.listdir(_REMOTE_DIR)
                if os.path.isdir(os.path.join(_REMOTE_DIR, n))
            }
        all_names = sorted(on_disk | set(saved.keys()))
        result = []
        for name in all_names:
            entry = saved.get(name, {})
            result.append((name, entry.get("repo", ""), entry.get("ref", "main"), name in on_disk))
        return result

    # ------------------------------------------------------------------ Cards

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(theme.RADIO_SUBTITLE_STYLE)
        return lbl

    def _local_card(self, fname: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("stepCard")
        frame.setStyleSheet(theme.STEP_CARD_STYLE)
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 10, 12, 10)

        name_lbl = QLabel(fname)
        name_lbl.setStyleSheet(theme.CARD_NAME_LABEL_STYLE)
        row.addWidget(name_lbl)
        row.addStretch()
        row.addWidget(self._badge("local", theme.TEXT_SUBTLE))
        return frame

    def _remote_card(self, name: str, repo: str, ref: str, present: bool) -> QFrame:
        frame = QFrame()
        frame.setObjectName("stepCard")
        frame.setStyleSheet(theme.STEP_CARD_STYLE)
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(4)

        top = QHBoxLayout()
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(theme.CARD_NAME_LABEL_STYLE)
        top.addWidget(name_lbl)
        top.addStretch()
        badge_color = theme.BLUE_BADGE if present else theme.AMBER_BADGE
        badge_text = f"remote · {ref}" if present else f"remote · {ref} · not cloned"
        top.addWidget(self._badge(badge_text, badge_color))
        box.addLayout(top)

        if repo:
            repo_lbl = QLabel(repo)
            repo_lbl.setStyleSheet(theme.CARD_DESC_LABEL_STYLE)
            box.addWidget(repo_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if present:
            upd_btn = QPushButton("Update")
            upd_btn.setStyleSheet(theme.BROWSE_BUTTON_STYLE)
            upd_btn.setFixedHeight(28)
            upd_btn.clicked.connect(lambda _=False, n=name: self._on_update(n))
            btn_row.addWidget(upd_btn)
        rm_btn = QPushButton("✕ Remove")
        rm_btn.setStyleSheet(theme.CLEAR_BUTTON_NO_DISABLED_STYLE)
        rm_btn.setFixedHeight(28)
        rm_btn.clicked.connect(lambda _=False, n=name, r=repo: self._on_remove(n, r))
        btn_row.addWidget(rm_btn)
        box.addLayout(btn_row)

        return frame

    def _badge(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-style: italic;")
        return lbl

    # ------------------------------------------------------------------ Actions

    def _on_add(self):
        dlg = _AddPluginDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        repo, ref = dlg.values()
        name = repo_dir_name(repo)
        if not name:
            return

        # Persist immediately so the entry appears as "not cloned" if the dialog
        # is re-opened while a clone is in progress.
        repos = UserSettings.load_plugin_repos()
        if not any(r.get("repo") == repo for r in repos):
            repos.append({"repo": repo, "ref": ref})
            UserSettings.save_plugin_repos(repos)

        os.makedirs(_REMOTE_DIR, exist_ok=True)
        dest = os.path.join(_REMOTE_DIR, name)
        self._set_busy(True, f"Cloning {name}…")
        self._rebuild_list()

        worker = _CloneWorker(repo, ref, dest)
        worker.done.connect(lambda status, n=name, r=repo: self._on_clone_done(n, r, status))
        self._workers.append(worker)
        worker.start()

    def _on_clone_done(self, name: str, repo: str, status: str):
        self._set_busy(False)
        if status == "ok":
            load_plugins(force=True)
        else:
            # Roll back persisted entry — clone failed.
            repos = [r for r in UserSettings.load_plugin_repos() if r.get("repo") != repo]
            UserSettings.save_plugin_repos(repos)
            QMessageBox.critical(
                self, f"Clone failed — {name}",
                status.removeprefix("error: "),
            )
        self._rebuild_list()

    def _on_remove(self, name: str, repo: str):
        dest = os.path.join(_REMOTE_DIR, name)
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
        if repo:
            repos = [r for r in UserSettings.load_plugin_repos() if r.get("repo") != repo]
            UserSettings.save_plugin_repos(repos)
        load_plugins(force=True)
        self._rebuild_list()

    def _on_update(self, name: str):
        dest = os.path.join(_REMOTE_DIR, name)
        self._set_busy(True, f"Updating {name}…")
        worker = _UpdateWorker(dest)
        worker.done.connect(lambda status, n=name: self._on_update_done(n, status))
        self._workers.append(worker)
        worker.start()

    def _on_update_done(self, name: str, status: str):
        self._set_busy(False)
        if status == "ok":
            load_plugins(force=True)
        else:
            QMessageBox.critical(
                self, f"Update failed — {name}",
                status.removeprefix("error: "),
            )
        self._rebuild_list()

    # ------------------------------------------------------------------ Helpers

    def _set_busy(self, busy: bool, msg: str = ""):
        self._add_btn.setEnabled(not busy)
        self._status_lbl.setText(msg)

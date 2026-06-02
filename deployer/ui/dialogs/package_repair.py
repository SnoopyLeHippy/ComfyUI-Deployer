"""Dialog to detect and reinstall broken Python packages.

Runs two passes against the bundled python_embeded:

1. ``uv pip check`` — surfaces missing deps and version conflicts.
2. File-integrity check — verifies every wheel's RECORD against on-disk
   files so we catch corrupted/half-extracted packages (e.g. a missing
   ``pydantic_core`` ``.pyd``) that pip's metadata still considers installed.

Selected packages are returned via :meth:`selected_packages`; the caller is
responsible for actually running the reinstall (so the main window's busy
state stays the source of truth for long-running operations).
"""

import threading
import traceback

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from deployer.config import PYTHON_EXE
from deployer.core.package_repair import (
    BrokenPackage,
    merge_results,
    run_file_integrity_check,
    run_import_probe,
    run_pip_check,
    run_shadow_scan,
    run_startup_probe,
)
from deployer.ui import theme
from deployer.ui.widgets.busy_button import BusyButton


class PackageRepairDialog(QDialog):
    """Check Python packages for issues and let the user pick which to reinstall."""

    _check_done = pyqtSignal(object)  # emits list[BrokenPackage]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Repair packages")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self.setStyleSheet(theme.APP_STYLE)

        # Each row keeps a reference to (frame, checkbox, package). Storing the
        # frame here is load-bearing: without a live Python reference, CPython
        # collects the QFrame as soon as ``_build_row`` returns, which deletes
        # its child checkbox under Qt and produces a
        # ``RuntimeError: wrapped C/C++ object of type QCheckBox has been deleted``
        # the moment ``_on_check_done`` tries to read it back.
        self._rows: list[tuple[QFrame, QCheckBox, BrokenPackage]] = []
        self._selected: list[BrokenPackage] = []
        self._cancelled = False
        self._deep_check_enabled = True

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        intro = QLabel(
            "Detects broken Python packages in the bundled python_embeded "
            "and reinstalls only the ones you select.<br>"
            "<b>Pass 1</b>: <code>uv pip check</code> (dependency conflicts).<br>"
            "<b>Pass 2</b>: file-integrity check (corrupted / missing files).<br>"
            "<b>Pass 3</b>: import probe (namespace shadowing inside site-packages).<br>"
            "<b>Pass 4</b>: shadow scan in <code>ComfyUI/</code> &amp; <code>custom_nodes/</code> "
            "(stray dirs visible to a static scan).<br>"
            "<b>Pass 5</b>: startup probe (reproduces ComfyUI's runtime "
            "<code>sys.path</code> after prestart scripts — catches shadows injected at runtime).<br>"
            "<b>Torch and other CUDA-tied packages are unchecked by default</b> "
            "to avoid breaking the bundle's GPU build."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.SUBTITLE_STYLE)
        root.addWidget(intro)

        # Options row: deep-check toggle + Run button + status label
        options_row = QHBoxLayout()
        options_row.setSpacing(10)
        self._deep_cbox = QCheckBox("Deep check (file integrity + import probe)")
        self._deep_cbox.setChecked(True)
        self._deep_cbox.setStyleSheet(theme.CHECKBOX_STYLE)
        self._deep_cbox.setToolTip(
            "Runs passes 2 through 5:\n"
            " • file integrity — every wheel's RECORD vs on-disk files\n"
            " • import probe — actually try to import each package; catches\n"
            "   namespace-package shadowing inside site-packages\n"
            " • shadow scan — filesystem walk of ComfyUI/ and custom_nodes/\n"
            "   for stray empty dirs that ComfyUI's runtime sys.path would\n"
            "   find BEFORE the real install\n"
            " • startup probe — runs every custom_node's prestartup_script.py\n"
            "   in a sandbox, then asks Python where each package actually\n"
            "   resolves. Catches shadows added at runtime by prestart\n"
            "   scripts (e.g. comfy-env / pixi envs)."
        )
        options_row.addWidget(self._deep_cbox)

        self._run_btn = BusyButton("Run check")
        self._run_btn.setStyleSheet(theme.RUN_COMFY_BUTTON_STYLE)
        self._run_btn.setFixedSize(110, 32)
        self._run_btn.clicked.connect(self._on_run_check)
        options_row.addWidget(self._run_btn)

        self._status_label = QLabel("Idle — click 'Run check' to scan packages.")
        self._status_label.setStyleSheet(theme.SUBTITLE_STYLE)
        self._status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        options_row.addWidget(self._status_label, 1)
        root.addLayout(options_row)

        # Scrollable list of issue rows
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(theme.SCROLL_AREA_STYLE)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 4, 0, 4)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch()
        self._scroll.setWidget(self._rows_container)
        root.addWidget(self._scroll, 1)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet(theme.INSTALL_BUTTON_STYLE)
        self._cancel_btn.setFixedSize(110, 34)
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._reinstall_btn = QPushButton("Reinstall selected")
        self._reinstall_btn.setStyleSheet(theme.INSTALL_BUTTON_ACTIVE_STYLE)
        self._reinstall_btn.setFixedSize(160, 34)
        self._reinstall_btn.setEnabled(False)
        self._reinstall_btn.clicked.connect(self._on_reinstall)
        btn_row.addWidget(self._reinstall_btn)
        root.addLayout(btn_row)

        self._check_done.connect(self._on_check_done)

    # ------------------------------------------------------------------
    # Check pipeline
    # ------------------------------------------------------------------

    def _on_run_check(self):
        self._deep_check_enabled = self._deep_cbox.isChecked()
        self._clear_rows()
        self._run_btn.set_busy(True)
        self._run_btn.setDisabled(True)
        self._deep_cbox.setDisabled(True)
        self._reinstall_btn.setEnabled(False)
        self._status_label.setText("Running checks...")
        threading.Thread(target=self._run_check_worker, daemon=True).start()

    def _run_check_worker(self):
        """Background thread: run all enabled passes and emit the merged result."""
        try:
            print("Repair: running 'uv pip check'...")
            pip_results = run_pip_check(PYTHON_EXE)
            print(f"  uv pip check: {len(pip_results)} issue(s).")

            integrity_results: list[BrokenPackage] = []
            probe_results: list[BrokenPackage] = []
            shadow_results: list[BrokenPackage] = []
            startup_results: list[BrokenPackage] = []
            if self._deep_check_enabled:
                print("Repair: running file-integrity check...")
                integrity_results = run_file_integrity_check(PYTHON_EXE)
                print(f"  File integrity: {len(integrity_results)} issue(s).")

                print("Repair: running import probe (this can take a minute)...")
                probe_results = run_import_probe(PYTHON_EXE)
                print(f"  Import probe: {len(probe_results)} issue(s).")

                print("Repair: scanning ComfyUI/ and custom_nodes/ for shadowing dirs...")
                shadow_results = run_shadow_scan(PYTHON_EXE)
                print(f"  Shadow scan: {len(shadow_results)} issue(s).")

                print("Repair: reproducing ComfyUI startup to capture runtime sys.path...")
                startup_results = run_startup_probe(PYTHON_EXE)
                print(f"  Startup probe: {len(startup_results)} issue(s).")

            merged = merge_results(
                pip_results,
                integrity_results,
                probe_results,
                shadow_results,
                startup_results,
            )
        except BaseException as exc:  # noqa: BLE001
            # Log the full traceback (not just the message) so the user can
            # ship the .log back to us when something blows up that
            # isn't already covered by the per-pass logging.
            print(f"Repair: error during check: {exc}")
            for line in traceback.format_exc().rstrip().splitlines():
                print(f"  {line}")
            merged = []
        self._check_done.emit(merged)

    def _on_check_done(self, results: list[BrokenPackage]):
        if self._cancelled:
            return
        self._run_btn.set_busy(False)
        self._run_btn.setDisabled(False)
        self._deep_cbox.setDisabled(False)

        if not results:
            self._status_label.setText("No issues detected.")
            return

        critical = sum(1 for p in results if p.is_critical)
        actionable = len(results) - critical
        self._status_label.setText(
            f"Found {len(results)} package(s) with issues "
            f"({actionable} actionable, {critical} critical/excluded)."
        )

        # Insert rows just before the trailing stretch.
        stretch_index = self._rows_layout.count() - 1
        for pkg in results:
            row = self._build_row(pkg)
            self._rows_layout.insertWidget(stretch_index, row)
            stretch_index += 1

        self._update_reinstall_button()

    def _build_row(self, pkg: BrokenPackage) -> QFrame:
        """Build the row widget for *pkg* and return its containing QFrame.

        The frame, its checkbox, and the package are kept together in
        ``self._rows`` so neither the Python wrapper nor the underlying
        Qt object is collected before the row makes it into the layout.
        """
        row = QFrame()
        row.setObjectName("repairRow")
        if pkg.is_critical:
            border = theme.PALETTE["error_surface_border"]
            bg = theme.PALETTE["error_surface_mid"]
        else:
            border = theme.PALETTE["surface_border"]
            bg = theme.PALETTE["surface_input"]
        row.setStyleSheet(
            f"QFrame#repairRow {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: 6px; }} "
            f"QFrame#repairRow QLabel {{ background: transparent; border: none; }} "
            f"QFrame#repairRow QCheckBox {{ background: transparent; border: none; }}"
        )
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.setSpacing(10)

        cbox = QCheckBox(row)
        cbox.setStyleSheet(theme.CHECKBOX_STYLE)
        cbox.setChecked(not pkg.is_critical)
        cbox.stateChanged.connect(self._update_reinstall_button)
        row_layout.addWidget(cbox)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        name_text = pkg.name
        if pkg.is_critical:
            name_text = f"{pkg.name}  ⚠ critical (CUDA-tied, opt-in only)"
        name_label = QLabel(name_text)
        name_label.setStyleSheet(
            "color: %s; font-size: 13px; font-weight: bold;" % (
                theme.PALETTE["error_badge"] if pkg.is_critical
                else theme.PALETTE["text_heading"]
            )
        )
        text_col.addWidget(name_label)

        reason_label = QLabel("  •  " + "\n  •  ".join(pkg.reasons))
        reason_label.setStyleSheet(
            f"color: {theme.PALETTE['text_body']}; font-size: 11px;"
        )
        reason_label.setWordWrap(True)
        text_col.addWidget(reason_label)

        row_layout.addLayout(text_col, 1)
        self._rows.append((row, cbox, pkg))
        return row

    def _clear_rows(self):
        """Remove every issue row so a new check starts from a clean slate."""
        for row, _cbox, _pkg in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

    def _update_reinstall_button(self, *_):
        any_checked = any(cbox.isChecked() for _row, cbox, _pkg in self._rows)
        self._reinstall_btn.setEnabled(any_checked)

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def _on_reinstall(self):
        self._selected = [pkg for _row, cbox, pkg in self._rows if cbox.isChecked()]
        if not self._selected:
            return
        self.accept()

    def selected_packages(self) -> list[BrokenPackage]:
        """Return the BrokenPackage objects the user picked.

        Returning the full objects (not just names) lets the caller delete
        each package's ``stray_dirs`` before kicking off the reinstall, which
        is the only way to fix the namespace-shadowing failure mode.
        """
        return list(self._selected)

    def closeEvent(self, event):
        # Late check results emitted after close land in a destroyed dialog;
        # the flag lets _on_check_done bail out before touching widgets.
        self._cancelled = True
        super().closeEvent(event)

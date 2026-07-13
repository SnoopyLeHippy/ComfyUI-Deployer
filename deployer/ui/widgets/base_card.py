"""Shared base for selectable node cards.

:class:`NodeCard` and :class:`OrphanNodeCard` differ in the data they carry
and in a few subclass-specific affordances (inline ref/desc editing on
``NodeCard``, the missing-on-disk badge on ``OrphanNodeCard``). Everything
else — the fixed card geometry, the header layout, the requirements
checkbox, hover/select event handling, the stylesheet-driven paint — is
identical and lives here.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)

from deployer.ui import theme
from deployer.ui.widgets.card_state import CardState, presentation_for
from deployer.ui.widgets.spinner import Spinner


# Insert a zero-width space after each underscore so Qt can wrap on them.
def _wrappable(name: str) -> str:
    return name.replace("_", "_​")


class BaseCard(QWidget):
    """Common geometry, event handling and styling for grid cards.

    Subclasses must implement :meth:`_current_state` and call
    :meth:`refresh` whenever observable state changes.
    """

    CARD_MIN_WIDTH = 320
    CARD_MAX_WIDTH = 400
    CARD_HEIGHT = 160

    def __init__(self, name: str, on_selection_changed=None, parent=None):
        super().__init__(parent)
        self._on_selection_changed = on_selection_changed
        self.is_selected = False
        self.is_from_workflow = False

        self.setObjectName("nodeCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(self.CARD_MIN_WIDTH)
        self.setMaximumWidth(self.CARD_MAX_WIDTH)
        self.setFixedHeight(self.CARD_HEIGHT)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(15, 12, 15, 12)
        self._root.setSpacing(6)

        # Header row: name + status badge
        self.name_label = QLabel(_wrappable(name))
        self.name_label.setWordWrap(True)
        self.badge = QLabel()
        self.badge.setFixedHeight(20)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._build_header()

        # Create the requirements checkbox up front so subclasses' _build_body
        # can reference ``self.req_checkbox`` (e.g. to set tooltips) — it is
        # only added to the layout afterwards so it stays at the bottom of
        # the card.
        self.req_checkbox = QCheckBox("Install requirements")
        self.req_checkbox.setStyleSheet(theme.CHECKBOX_STYLE)
        self.req_checkbox.toggled.connect(self._on_req_toggled)

        self._build_body(self._root)
        self._root.addStretch()
        self._root.addWidget(self.req_checkbox)

        # Floats above the layout (not added to it) so it can sit in the
        # bottom-right corner regardless of body content; repositioned on resize.
        self._pending_checks = 0
        self.spinner = Spinner(self)
        self._position_spinner()

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def _build_body(self, layout: QVBoxLayout) -> None:
        """Add subclass-specific body widgets to *layout*."""
        raise NotImplementedError

    def _current_state(self) -> CardState:
        """Return the visual state the card should currently display."""
        raise NotImplementedError

    def _can_toggle_selection(self) -> bool:
        """Whether a left-click on the card should toggle ``is_selected``."""
        return True

    def _on_selection_toggled(self) -> None:
        """Hook fired after ``is_selected`` flips, before :meth:`refresh`."""

    def _on_requirements_toggled(self, checked: bool) -> None:
        """Hook fired by the Install Requirements checkbox."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Resync the card's appearance with its current state."""
        card_style, badge_text, badge_style = presentation_for(self._current_state())
        self.setStyleSheet(card_style)
        self.badge.setText(badge_text)
        self.badge.setStyleSheet(badge_style)
        self.update()

    def begin_checking(self, count: int = 1) -> None:
        """Show the corner spinner; *count* background checks must call
        :meth:`check_done` before it hides again."""
        self._pending_checks += count
        self.spinner.set_active(True)

    def check_done(self) -> None:
        """Signal that one of the checks registered via :meth:`begin_checking`
        has finished; hides the spinner once all of them have."""
        self._pending_checks = max(0, self._pending_checks - 1)
        if self._pending_checks == 0:
            self.spinner.set_active(False)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _position_spinner(self) -> None:
        margin = 10
        self.spinner.move(
            self.width() - self.spinner.width() - margin,
            self.height() - self.spinner.height() - margin,
        )

    def _build_header(self) -> None:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.name_label)
        header.addStretch()
        header.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        self._root.addLayout(header)

        # The card itself is the click target — labels and badge pass mouse
        # events through so the whole card is clickable.
        self.name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _on_req_toggled(self, checked: bool) -> None:
        self._on_requirements_toggled(checked)
        if self._on_selection_changed:
            self._on_selection_changed()

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        # Required for a plain QWidget to honour background/border stylesheets.
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_spinner()

    def enterEvent(self, event):
        if self._can_toggle_selection():
            self.setStyleSheet(self.styleSheet() + theme.NODE_CARD_HOVER_EXTRA)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.refresh()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._can_toggle_selection():
            self.is_selected = not self.is_selected
            self._on_selection_toggled()
            self.refresh()
            if self._on_selection_changed:
                self._on_selection_changed()
        super().mousePressEvent(event)

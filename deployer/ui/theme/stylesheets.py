"""Qt Style Sheets for the ComfyUI Custom Node Deployer.

All style strings used by widgets and dialogs live here so the colour palette
in :mod:`deployer.ui.theme.palette` remains the single source of truth.

The :func:`_qss` helper resolves ``"%(name)s"`` placeholders against
``PALETTE``.
"""

from deployer.ui.theme.palette import PALETTE


def _qss(style_sheet: str) -> str:
    """Resolve ``"%(name)s"`` palette placeholders inside a stylesheet template."""
    return style_sheet % PALETTE


# ---------------------------------------------------------------------------
# Application chrome
# ---------------------------------------------------------------------------

APP_STYLE = _qss("""
QWidget {
    background-color: %(surface_panel)s;
    color: %(text_primary)s;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    font-size: 13px;
}
QScrollBar:vertical {
    background: %(surface_input)s;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: %(scrollbar_handle)s;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    background: none;
    border: none;
}
QScrollBar:horizontal {
    background: %(surface_input)s;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: %(scrollbar_handle)s;
    border-radius: 4px;
    min-width: 20px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    background: none;
    border: none;
}
""")

MAIN_CONTENT_STYLE  = _qss("""
QWidget#mainContent {
    background: qradialgradient(
        cx:0.5, cy:0, radius:0.8, fx:0.5, fy:0,
        stop:0 %(bg_radial_inner)s,
        stop:1 %(bg_radial_outer)s);
}
QWidget#mainContent > QWidget#transparentRow,
QWidget#mainContent QScrollArea,
QWidget#mainContent QScrollArea > QWidget,
QWidget#mainContent QWidget#cardGrid,
QWidget#mainContent > QWidget#transparentRow QLabel,
QWidget#mainContent > QWidget#transparentRow QToolButton {
    background: transparent;
}
""")
MAIN_TITLE_STYLE    = _qss("QLabel { color: %(text_primary)s; font-size: 20px; font-weight: bold; }")
SUBTITLE_STYLE      = _qss("QLabel { color: %(text_body)s; font-size: 13px; }")
SCROLL_AREA_STYLE   = "QScrollArea { background-color: transparent; border: none; }"
SEPARATOR_STYLE     = _qss("background-color: %(surface_border)s;")

DIALOG_TEXTBOX_STYLE = _qss(
    "QLineEdit { background: %(surface_panel)s; color: %(text_muted)s; border: 1px solid %(surface_divider)s; "
    "border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
)


# ---------------------------------------------------------------------------
# Node cards
# ---------------------------------------------------------------------------

NODE_CARD_DEFAULT_STYLE = _qss("""
QWidget#nodeCard {
    background-color: %(surface_input)s;
    border-radius: 8px;
    border: 1px solid %(surface_border)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_INSTALLED_STYLE = _qss("""
QWidget#nodeCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 %(green_surface_end)s,
        stop:1 %(green_surface_mid)s);
    border-radius: 8px;
    border: 1px solid %(green_surface_border)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_SELECTED_STYLE = _qss("""
QWidget#nodeCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 %(surface_input)s,
        stop:0.5 %(blue_surface_mid)s,
        stop:1 %(blue_surface_end)s);
    border-radius: 8px;
    border: 1px solid %(blue_surface_border)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_SELECTED_INSTALLED_STYLE = _qss("""
QWidget#nodeCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 %(surface_input)s,
        stop:0.5 %(red_surface_mid)s,
        stop:1 %(red_surface_end)s);
    border-radius: 8px;
    border: 1px solid %(red_surface_border)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_TO_UPDATE_STYLE = _qss("""
QWidget#nodeCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 %(surface_input)s,
        stop:0.5 %(amber_surface_mid)s,
        stop:1 %(amber_surface_end)s);
    border-radius: 8px;
    border: 1px solid %(amber_surface_border)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_IMPORT_STYLE = _qss("""
QWidget#nodeCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 %(surface_input)s,
        stop:0.5 %(purple_surface_mid)s,
        stop:1 %(purple_surface_end)s);
    border-radius: 8px;
    border: 1px solid %(purple_surface_border)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_ERROR_STYLE = _qss("""
QWidget#nodeCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 %(surface_input)s,
        stop:0.45 %(error_surface_mid)s,
        stop:1 %(error_surface_end)s);
    border-radius: 8px;
    border: 1px solid %(error_surface_border)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_ORPHAN_STYLE = _qss("""
QWidget#nodeCard {
    background-color: %(surface_button)s;
    border-radius: 8px;
    border: 1px solid %(surface_outline)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_ORPHAN_SELECTED_STYLE = _qss("""
QWidget#nodeCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 %(surface_button)s,
        stop:0.5 %(magenta_surface_mid)s,
        stop:1 %(magenta_surface_end)s);
    border-radius: 8px;
    border: 1px solid %(magenta_surface_border)s;
}
QWidget#nodeCard QLabel {
    background-color: transparent;
}
QWidget#nodeCard QCheckBox {
    background-color: transparent;
}
""")

NODE_CARD_HOVER_EXTRA = _qss("QWidget#nodeCard { border-color: %(text_primary)s; }")


# Card inner labels / inline editors
CARD_NAME_LABEL_STYLE        = _qss("color: %(text_primary)s; font-size: 14px; font-weight: bold;")
CARD_REF_LABEL_STYLE         = _qss("color: %(text_subtle)s; font-size: 10px; font-style: italic;")
CARD_REF_LABEL_PENDING_STYLE = _qss("color: %(amber_badge)s; font-size: 10px; font-style: italic;")
CARD_REF_EDIT_STYLE          = _qss(
    "QLineEdit { background: %(surface_input)s; color: %(text_heading)s; "
    "font-size: 10px; font-style: italic; "
    "border: 1px solid %(surface_neutral)s; border-radius: 3px; padding: 0px 4px; }"
)
CARD_DESC_LABEL_STYLE        = _qss("color: %(text_body)s; font-size: 12px;")
CARD_DESC_EDIT_STYLE         = _qss(
    "QLineEdit { background: %(surface_input)s; color: %(text_body)s; "
    "font-size: 12px; "
    "border: 1px solid %(surface_neutral)s; border-radius: 3px; padding: 0px 4px; }"
)
ORPHAN_CARD_NAME_LABEL_STYLE = _qss("color: %(text_heading)s; font-size: 14px; font-weight: bold;")
ORPHAN_CARD_REPO_LABEL_STYLE = _qss("color: %(text_muted)s; font-size: 12px;")


# ---------------------------------------------------------------------------
# Badges
# ---------------------------------------------------------------------------

INSTALLED_BADGE_STYLE = _qss("""
QLabel {
    background-color: %(green_action)s;
    color: %(text_primary)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")

NOT_INSTALLED_BADGE_STYLE = _qss("""
QLabel {
    background-color: %(surface_neutral)s;
    color: %(text_body)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")

BADGE_TO_INSTALL_STYLE = _qss("""
QLabel {
    background-color: %(blue_badge)s;
    color: %(text_primary)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")

BADGE_TO_UPDATE_STYLE = _qss("""
QLabel {
    background-color: %(amber_badge)s;
    color: %(text_primary)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")

BADGE_MISSING_STYLE = _qss("""
QLabel {
    background-color: %(red_badge)s;
    color: %(text_primary)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")

BADGE_TO_REMOVE_STYLE = _qss("""
QLabel {
    background-color: %(red_remove_badge)s;
    color: %(text_primary)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")

BADGE_ERROR_STYLE = _qss("""
QLabel {
    background-color: %(error_badge)s;
    color: %(text_primary)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")

BADGE_ADD_TO_CONFIG_STYLE = _qss("""
QLabel {
    background-color: %(magenta_badge)s;
    color: %(text_primary)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")

BADGE_IMPORT_STYLE = _qss("""
QLabel {
    background-color: %(purple_badge)s;
    color: %(text_primary)s;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: bold;
}
""")


# ---------------------------------------------------------------------------
# Form controls
# ---------------------------------------------------------------------------

CHECKBOX_STYLE = _qss("""
QCheckBox {
    color: %(text_body)s;
    font-size: 11px;
    spacing: 5px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid %(surface_neutral)s;
    border-radius: 3px;
    background-color: %(surface_input)s;
}
QCheckBox::indicator:checked {
    background-color: %(blue_badge)s;
    border: 1px solid %(blue_badge)s;
}
QCheckBox::indicator:hover {
    border: 1px solid %(text_muted)s;
}
QCheckBox:disabled {
    color: %(text_muted)s;
}
QCheckBox::indicator:disabled {
    border: 1px solid %(surface_border)s;
    background-color: %(surface_neutral)s;
}
QCheckBox::indicator:checked:disabled {
    background-color: %(text_muted)s;
    border: 1px solid %(text_muted)s;
}
""")

RADIO_STYLE = _qss("""
QRadioButton {
    color: %(text_heading)s;
    font-size: 14px;
    spacing: 6px;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid %(surface_neutral)s;
    border-radius: 7px;
    background-color: %(surface_input)s;
}
QRadioButton::indicator:checked {
    background-color: %(blue_badge)s;
    border: 1px solid %(blue_badge)s;
}
QRadioButton::indicator:hover {
    border: 1px solid %(text_muted)s;
}
""")

SECTION_TITLE_STYLE = _qss(
    "QLabel { color: %(text_heading)s; font-weight: bold; font-size: 14px; "
    "text-transform: uppercase; letter-spacing: 1px; }"
)

RADIO_SUBTITLE_STYLE = _qss(
    "QLabel { color: %(text_muted)s; font-size: 13px; }"
)

# Framed container for a single configured bundle step in the Create Bundle dialog.
STEP_CARD_STYLE = _qss("""
QFrame#stepCard {
    background-color: %(surface_input)s;
    border-radius: 8px;
    border: 1px solid %(surface_border)s;
}
QFrame#stepCard QLabel {
    background-color: transparent;
}
""")


# ---------------------------------------------------------------------------
# Console / Logs
# ---------------------------------------------------------------------------

CONSOLE_PANEL_STYLE = "QWidget { background: transparent; border: none; }"
CONSOLE_TITLE_STYLE = _qss("color: %(text_primary)s; font-size: 14px; font-weight: bold; background: transparent;")
CONSOLE_TITLE_LINE_STYLE = _qss("background-color: %(text_primary)s; border: none;")
CONSOLE_OUTPUT_STYLE = _qss("""
QTextEdit {
    background-color: %(surface_input)s;
    color: %(text_body)s;
    border: 1px solid %(surface_border)s;
    border-radius: 4px;
    padding: 5px;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 12px;
}
""")


# ---------------------------------------------------------------------------
# Buttons (top-level actions)
# ---------------------------------------------------------------------------

INSTALL_BUTTON_STYLE = _qss("""
QPushButton {
    background-color: %(install_action)s;
    color: %(text_primary)s;
    border: none;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: bold;
    border-radius: 4px;
}
QPushButton:hover {
    background-color: %(install_action_hover)s;
}
QPushButton:pressed {
    background-color: %(install_action_pressed)s;
}
QPushButton:disabled {
    background-color: %(surface_disabled)s;
    color: %(text_body)s;
}
""")

INSTALL_BUTTON_ACTIVE_STYLE = _qss("""
QPushButton {
    background-color: %(blue_action)s;
    color: %(text_primary)s;
    border: none;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: bold;
    border-radius: 4px;
}
QPushButton:hover {
    background-color: %(blue_action_hover)s;
}
QPushButton:pressed {
    background-color: %(blue_action_pressed)s;
}
QPushButton:disabled {
    background-color: %(surface_disabled)s;
    color: %(text_body)s;
}
""")

RUN_COMFY_BUTTON_STYLE = _qss("""
QPushButton {
    background-color: %(green_action)s;
    color: %(text_primary)s;
    border: none;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: bold;
    border-radius: 4px;
}
QPushButton:hover {
    background-color: %(green_action_hover)s;
}
QPushButton:pressed {
    background-color: %(green_action_pressed)s;
}
QPushButton:disabled {
    background-color: %(surface_disabled)s;
    color: %(text_body)s;
}
""")

STOP_COMFY_BUTTON_STYLE = _qss("""
QPushButton {
    background-color: %(stop_action)s;
    color: %(text_primary)s;
    border: none;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: bold;
    border-radius: 4px;
}
QPushButton:hover {
    background-color: %(stop_action_hover)s;
}
QPushButton:pressed {
    background-color: %(stop_action_pressed)s;
}
""")

ADD_NODE_BUTTON_STYLE = _qss("""
QPushButton {
    background-color: %(green_action_alt)s;
    color: %(text_primary)s;
    border: none;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: bold;
    border-radius: 4px;
}
QPushButton:hover {
    background-color: %(green_action_alt_hover)s;
}
QPushButton:pressed {
    background-color: %(green_action_alt_pressed)s;
}
QPushButton:disabled {
    background-color: %(surface_disabled)s;
    color: %(text_body)s;
}
""")


# ---------------------------------------------------------------------------
# Hamburger menu
# ---------------------------------------------------------------------------

HAMBURGER_BUTTON_STYLE = _qss("""
QToolButton {
    background-color: transparent;
    color: %(text_primary)s;
    border: none;
    font-size: 20px;
    padding: 4px 8px;
    border-radius: 4px;
}
QToolButton:hover {
    background-color: %(surface_button)s;
}
QToolButton:pressed {
    background-color: %(surface_input)s;
}
QToolButton::menu-indicator {
    image: none;
}
""")

HAMBURGER_MENU_STYLE = _qss("""
QMenu {
    background-color: %(surface_input)s;
    color: %(text_primary)s;
    border: 1px solid %(surface_divider)s;
    border-radius: 4px;
    padding: 4px 0px;
}
QMenu::item {
    padding: 6px 20px;
}
QMenu::item:selected {
    background-color: %(surface_button)s;
}
QMenu::separator {
    height: 1px;
    background: %(surface_divider)s;
    margin: 4px 8px;
}
""")


# ---------------------------------------------------------------------------
# Dialog-specific styles (path picker, settings, bundle, missing nodes)
# ---------------------------------------------------------------------------

PATH_PICKER_LABEL_STYLE = _qss("color: %(text_heading)s; font-weight: bold; font-size: 13px;")

HELP_TEXT_STYLE = _qss("color: %(surface_neutral)s; font-size: 11px; font-style: italic;")

BROWSE_BUTTON_STYLE = _qss(
    "QPushButton { background: %(surface_button)s; color: %(text_heading)s; border: 1px solid %(surface_neutral)s; "
    "border-radius: 4px; padding: 4px 8px; } "
    "QPushButton:hover { background: %(surface_disabled)s; }"
)

CLEAR_BUTTON_STYLE = _qss(
    "QPushButton { background: %(surface_button)s; color: %(text_muted)s; border: 1px solid %(surface_neutral)s; "
    "border-radius: 4px; padding: 4px; } "
    "QPushButton:hover { background: %(stop_action)s; color: %(text_primary)s; } "
    "QPushButton:disabled { color: %(surface_divider)s; border-color: %(surface_button)s; }"
)

CLEAR_BUTTON_NO_DISABLED_STYLE = _qss(
    "QPushButton { background: %(surface_button)s; color: %(text_muted)s; border: 1px solid %(surface_neutral)s; "
    "border-radius: 4px; padding: 4px; } "
    "QPushButton:hover { background: %(stop_action)s; color: %(text_primary)s; }"
)

MISSING_NODES_LIST_STYLE = _qss(
    "QListWidget { background-color: %(surface_panel)s; border: 1px solid %(surface_border)s; "
    "border-radius: 4px; padding: 4px; } "
    "QListWidget::item { color: %(text_heading)s; padding: 3px 6px; }"
)

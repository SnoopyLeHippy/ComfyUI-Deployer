"""Color palette for the UI.

``PALETTE`` is auto-built from this module's globals so any string constant
defined here becomes available to ``"%(name)s"``-style template substitution.
"""

# ---------------------------------------------------------------------------
# Surface scale (dark → light)
# ---------------------------------------------------------------------------
SURFACE_BG       = "#121212"  # main window background
SURFACE_PANEL    = "#1e1e1e"  # app panels, console, dialogs
SURFACE_INPUT    = "#2a2a2a"  # input fields, cards (collapses old SURFACE_CARD)
SURFACE_BORDER   = "#333333"  # card / panel borders (collapses old BORDER_CARD)
SURFACE_BUTTON   = "#3a3a3a"  # buttons, orphan card body (collapses old SURFACE_ORPHAN)
SURFACE_DIVIDER  = "#444444"
SURFACE_DISABLED = "#4a4a4a"
SURFACE_NEUTRAL  = "#555555"
SURFACE_OUTLINE  = "#606060"

# ---------------------------------------------------------------------------
# Text scale (light → dark)
# ---------------------------------------------------------------------------
TEXT_PRIMARY = "#fdfdf6"
TEXT_HEADING = "#dddddd"  # collapses old TEXT_PRIMARY_SOFT
TEXT_BODY    = "#a0a0a0"  # collapses old ICON_MUTED
TEXT_MUTED   = "#888888"
TEXT_SUBTLE  = "#666666"

# ---------------------------------------------------------------------------
# Window background — radial gradient (top-center) endpoints
# ---------------------------------------------------------------------------
BG_RADIAL_INNER = "#103329"
BG_RADIAL_OUTER = "#070e0d"

# ---------------------------------------------------------------------------
# Accent — green (run-comfy button, installed card / badge)
# ---------------------------------------------------------------------------
GREEN_ACTION             = "#077f3b"
GREEN_ACTION_HOVER       = "#0a9c48"
GREEN_ACTION_PRESSED     = "#055e2c"
GREEN_ACTION_ALT         = "#077f3b"
GREEN_ACTION_ALT_HOVER   = "#0a9c48"
GREEN_ACTION_ALT_PRESSED = "#055e2c"
GREEN_SURFACE_MID        = "rgba(7, 127, 59, 0.5)"
GREEN_SURFACE_END        = "rgba(7, 127, 59, 0)"
GREEN_SURFACE_BORDER     = "#38ee7d"

# ---------------------------------------------------------------------------
# Accent — magenta
# ---------------------------------------------------------------------------
MAGENTA_BADGE          = "#E91E8C"
MAGENTA_SURFACE_MID    = "#3d2035"
MAGENTA_SURFACE_END    = "#5a1545"
MAGENTA_SURFACE_BORDER = "#FF1493"

# ---------------------------------------------------------------------------
# Accent — blue
# ---------------------------------------------------------------------------
BLUE_BADGE          = "#2196F3"
BLUE_ACTION         = "#1565c0"
BLUE_ACTION_HOVER   = "#0d47a1"
BLUE_ACTION_PRESSED = "#0a2f6b"
BLUE_SURFACE_MID    = "#232c37"
BLUE_SURFACE_END    = "#203754"
BLUE_SURFACE_BORDER = "#237CC0"

# ---------------------------------------------------------------------------
# Accent — amber
# ---------------------------------------------------------------------------
AMBER_BADGE          = "#FF9800"
AMBER_SURFACE_MID    = "#312b20"
AMBER_SURFACE_END    = "#463315"
AMBER_SURFACE_BORDER = "#CA7C0A"

# ---------------------------------------------------------------------------
# Accent — purple (workflow import)
# ---------------------------------------------------------------------------
PURPLE_BADGE          = "#9c27b0"
PURPLE_SURFACE_MID    = "#2a1f3d"
PURPLE_SURFACE_END    = "#3d1f5c"
PURPLE_SURFACE_BORDER = "#7c3ab0"

# ---------------------------------------------------------------------------
# Accent — install (orange)
# ---------------------------------------------------------------------------
INSTALL_ACTION         = "#d45e3d"
INSTALL_ACTION_HOVER   = "#b84e33"
INSTALL_ACTION_PRESSED = "#a04029"

# ---------------------------------------------------------------------------
# Accent — red / stop / error
# ---------------------------------------------------------------------------
RED_BADGE          = "#EF5350"
RED_REMOVE_BADGE   = "#F44336"
RED_SURFACE_MID    = "#332323"
RED_SURFACE_END    = "#502020"
RED_SURFACE_BORDER = "#C13D33"

STOP_ACTION         = "#c62828"
STOP_ACTION_HOVER   = "#b71c1c"
STOP_ACTION_PRESSED = "#7f0000"

ERROR_BADGE          = "#ff3b30"
ERROR_SURFACE_MID    = "#4f1717"
ERROR_SURFACE_END    = "#7b1717"
ERROR_SURFACE_BORDER = ERROR_BADGE

# ---------------------------------------------------------------------------
# Misc accents
# ---------------------------------------------------------------------------
LINK_ACCENT = "#4FC3F7"
CONSOLE_ERROR = "#ff6b66"  # error / warning lines in the console output (theme.CONSOLE_ERROR)

# ---------------------------------------------------------------------------
# Aliases used by code that references these names directly.
# ---------------------------------------------------------------------------
ICON_MUTED       = TEXT_BODY      # used in add_button.py painter
SCROLLBAR_HANDLE = SURFACE_NEUTRAL  # used as %(scrollbar_handle)s in APP_STYLE


# ---------------------------------------------------------------------------
# PALETTE: lowercase-keyed dict for ``"%(name)s" % PALETTE`` substitution.
# ---------------------------------------------------------------------------
PALETTE = {
    name.lower(): value
    for name, value in globals().items()
    if name.isupper() and isinstance(value, str)
}

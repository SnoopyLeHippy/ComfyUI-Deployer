"""ComfyUI custom node management package."""

#: Environment variable (or ``.env`` key) naming the ComfyUI portable folder the
#: Deployer operates on. Read once by :mod:`deployer.config` at import time, so it
#: must be set before the first ``deployer.config`` import — :mod:`deployer.cli`
#: sets it from ``--portable``. Kept here, not in ``config``, so the CLI can name
#: it without importing ``config`` too early.
PORTABLE_DIR_ENV = "DEPLOYER_PORTABLE_DIR"

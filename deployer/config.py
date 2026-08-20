"""Centralized path constants and configuration for ComfyUI node management."""

import configparser
import os


# Project root directory (parent of the deployer package)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")


def _load_env_file(env_path: str) -> dict[str, str]:
    """Read a minimal .env file into a dictionary.

    Supports lines in the form ``KEY=value`` and ignores blank lines,
    comments, and optional ``export`` prefixes.
    """
    values: dict[str, str] = {}
    if not os.path.exists(env_path):
        return values

    with open(env_path, "r", encoding="utf-8-sig") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()

            key, sep, value = line.partition("=")
            if not sep:
                continue

            key = key.strip()
            value = value.strip()
            if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
                value = value[1:-1]
            values[key] = value

    return values


_ENV_VALUES = _load_env_file(ENV_FILE)


def _get_optional_env(name: str) -> str:
    """Return an optional environment value, defaulting to an empty string."""
    return os.getenv(name, _ENV_VALUES.get(name, "")).strip()


def _normalize_gitlab_url(value: str) -> str:
    """Ensure configured GitLab HTTPS prefixes end with a slash."""
    if value and not value.endswith("/"):
        return value + "/"
    return value


def _normalize_gitlab_ssh(value: str) -> str:
    """Ensure configured GitLab SSH prefixes end with a colon."""
    if value and not value.endswith(":"):
        return value + ":"
    return value


def _resolve_gitlab_root() -> str:
    """Return the GitLab clone directory.

    Resolution order:
    1. ``GITLAB_ROOT`` env var — direct override (simplest setup).
    2. A gitconfig-style ini file: reads ``GITCONFIG_KEY``
       from section ``GITCONFIG_SECTION`` in ``GITCONFIG_PATH``. Useful when the
       clone directory is already declared in ``~/.gitconfig`` for other tooling.
    3. Fallback to ``CUSTOM_NODES_DIR``.

    Example ``~/.gitconfig`` entry::

        [MySection]
            gitroot = D:/Gitlab
    """
    # 1. Direct override
    direct = _get_optional_env("GITLAB_ROOT")
    if direct:
        return os.path.normpath(direct)

    # 2. Gitconfig-style ini lookup
    gitconfig_path = _get_optional_env("GITCONFIG_PATH") or os.path.join(os.path.expanduser("~"), ".gitconfig")
    gitconfig_section = _get_optional_env("GITCONFIG_SECTION")
    gitconfig_key = _get_optional_env("GITCONFIG_KEY")

    if gitconfig_path and gitconfig_section and os.path.exists(gitconfig_path):
        parser = configparser.ConfigParser(strict=False)
        parser.read(gitconfig_path, encoding="utf-8")
        clone_dir = parser.get(gitconfig_section, gitconfig_key, fallback=None)
        if clone_dir:
            return os.path.normpath(clone_dir)

    # 3. Fallback
    return CUSTOM_NODES_DIR


# -- Gitlab -----------------------------------------------------------------
GITLAB_URL = _normalize_gitlab_url(_get_optional_env("GITLAB_URL"))
GITLAB_SSH = _normalize_gitlab_ssh(_get_optional_env("GITLAB_SSH"))

# -- ComfyUI portable paths ------------------------------------------------
PORTABLE_DIR = os.path.join(PROJECT_ROOT, "ComfyUI_windows_portable")
COMFYUI_DIR = os.path.join(PORTABLE_DIR, "ComfyUI")
PYTHON_EXE = os.path.join(PORTABLE_DIR, "python_embeded", "python.exe")
CUSTOM_NODES_DIR = os.path.join(COMFYUI_DIR, "custom_nodes")
EXTRA_MODEL_PATHS_YAML = os.path.join(COMFYUI_DIR, "extra_model_paths.yaml")
MODELS_DIR = os.path.join(COMFYUI_DIR, "models")
OUTPUT_DIR = os.path.join(COMFYUI_DIR, "output")
INPUT_DIR = os.path.join(COMFYUI_DIR, "input")
UPDATE_DIR = os.path.join(PORTABLE_DIR, "update")
UPDATE_COMFYUI_BAT = os.path.join(UPDATE_DIR, "update_comfyui.bat")

# -- Gitlab workspace layout -----------------------------------------------
# Parent directory of the git repo — all sibling repos live here
GITLAB_ROOT = _resolve_gitlab_root()
COMFY_UI_SOURCE_DIR = os.path.join(GITLAB_ROOT, "comfy-ui", "ComfyUI")

# -- Custom-node JSON manifests --------------------------------------------
SOURCE_NODES_JSON = os.path.join(COMFY_UI_SOURCE_DIR, "custom_nodes.json")
LOCAL_NODES_JSON = os.path.join(PROJECT_ROOT, "custom_nodes.json")
USER_SETTINGS_JSON = os.path.join(PROJECT_ROOT, "user_settings.json")

# -- Built-in node mappings -------------------------------------------------
COMFYUI_NODES_PY = os.path.join(COMFYUI_DIR, "nodes.py")
COMFY_EXTRAS_DIR = os.path.join(COMFYUI_DIR, "comfy_extras")

# -- Cache directory for downloaded node DBs --------------------------------
CACHE_DIR = os.path.join(PROJECT_ROOT, ".cache")
EXTENSION_NODE_MAP_URL = (
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/extension-node-map.json"
)
CUSTOM_NODE_LIST_URL = (
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json"
)

# -- Pre-built wheels shipped with the project ------------------------------
INSIGHTFACE_WHL = os.path.join(
    PROJECT_ROOT, "insightface-0.7.3-cp313-cp313-win_amd64.whl"
)

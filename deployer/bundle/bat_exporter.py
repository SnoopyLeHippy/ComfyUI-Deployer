"""Generate a single self-contained ``.bat`` that rebuilds a bundle on the
recipient's machine instead of shipping a heavy local build.

Running the generated script clones the ComfyUI Deployer, downloads the pinned
ComfyUI portable, installs PyQt6 / pyyaml / uv into its embedded python, writes
the ``user_settings.json`` (and optionally ``extra_model_paths.yaml``), then
runs :mod:`deployer.bundle.headless_install` to clone every configured custom
node and install its requirements.

Models are deliberately never embedded — they're far too heavy. Only the
external ``extra_model_paths.yaml`` (and the rest of the advanced ``settings``
subdict) is carried over, and only when the user opts in.

File payloads (``user_settings.json``, ``extra_model_paths.yaml``) are embedded
as base64 and decoded at runtime by the freshly extracted python. base64 dodges
all batch-escaping pitfalls, and chunking the blob keeps every ``echo`` line
well under cmd's ~8191-char limit.
"""

import base64
import io
import json
import os
import tarfile

from deployer.bundle.comfyui_archive import get_comfyui_version
from deployer.bundle.workflow_parser import (
    extract_workflow_info,
    find_custom_node_dirs_for_types,
)
from deployer.bundle.project_copier import collect_node_metadata
from deployer.config import (
    CUSTOM_NODES_DIR,
    EXTRA_MODEL_PATHS_YAML,
    PROJECT_ROOT,
)
from deployer.core import git_ops
from deployer.settings import UserSettings


BAT_FILENAME = "install_comfyui_bundle.bat"
_LOCAL_PLUGINS_DIR = os.path.join(PROJECT_ROOT, "plugins")

# Comfy-Org ships a versioned portable archive per release; fall back to the
# upstream "latest" asset when we can't read a concrete version on disk.
_PINNED_URL_FMT = (
    "https://github.com/Comfy-Org/ComfyUI/releases/download/v{version}/"
    "ComfyUI_windows_portable_nvidia.7z"
)
_LATEST_URL = (
    "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/"
    "ComfyUI_windows_portable_nvidia.7z"
)

# echo chunk size for embedded base64 — comfortably under cmd's line limit.
_CHUNK = 4000


def _archive_url(version: str) -> str:
    return _LATEST_URL if version == "latest" else _PINNED_URL_FMT.format(version=version)


def _build_node_list(
    workflow_paths: list[str],
    extra_repos: list[tuple[str, str]] | None,
) -> list[dict]:
    """Resolve the node entries to embed in the bat.

    Mirrors the builder: when workflows are given the list is trimmed to the
    custom-node dirs they reference; otherwise every git-backed installed node
    is included. *extra_repos* (workflow-resolved nodes not installed locally)
    are appended, skipping any already present by folder name.
    """
    only_dirs: set[str] | None = None
    if workflow_paths:
        node_types, _ = extract_workflow_info(workflow_paths)
        only_dirs = find_custom_node_dirs_for_types(node_types, CUSTOM_NODES_DIR)
        print(f"Bundle .bat: {len(node_types)} node types → {len(only_dirs)} node dir(s).")

    nodes = collect_node_metadata(CUSTOM_NODES_DIR, only_dirs)
    seen = {os.path.basename(n["repo"].rstrip("/").removesuffix(".git")) for n in nodes}

    for repo, ref in extra_repos or []:
        name = os.path.basename(repo.rstrip("/").removesuffix(".git"))
        if not name or name in seen:
            continue
        nodes.append({"repo": repo, "ref": ref, "description": name})
        seen.add(name)

    return nodes


def _collect_local_plugins(plugin_dir: str) -> list[str]:
    """Return sorted paths of user plugin ``.py`` files in *plugin_dir*.

    Skips ``__init__.py`` and any file starting with ``_``.
    Returns an empty list when the directory is absent or empty.
    """
    if not os.path.isdir(plugin_dir):
        return []
    return sorted(
        os.path.join(plugin_dir, f)
        for f in os.listdir(plugin_dir)
        if f.endswith(".py") and not f.startswith("_")
    )


def _build_plugins_tarball_b64(plugin_paths: list[str]) -> str | None:
    """Pack *plugin_paths* into an uncompressed in-memory tar, base64-encoded.

    The tar is extracted into ``plugins/`` by the .bat at install time.
    Returns ``None`` when *plugin_paths* is empty.
    """
    if not plugin_paths:
        return None
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path in plugin_paths:
            tar.add(path, arcname=os.path.basename(path))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _build_workflows_tarball_b64(workflow_paths: list[str]) -> str:
    """Pack workflow files into an uncompressed in-memory tar, base64-encoded.

    The tar is extracted into a ``workflows/`` folder by the .bat at install
    time. Using a tarball avoids per-file batch-escaping pitfalls for filenames
    with spaces or unicode characters.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for wf in workflow_paths:
            tar.add(wf, arcname=os.path.basename(wf))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _emit_b64(lines: list[str], blob: str, tmp_name: str, out_literal: str) -> None:
    """Append batch lines that rebuild a base64 *blob* into the file *out_literal*.

    *out_literal* is a python string literal (already quoted) naming the target,
    e.g. ``"'user_settings.json'"``. b64decode discards the CRLFs echo inserts.
    """
    lines.append(f"del {tmp_name} 2>nul")
    for i in range(0, len(blob), _CHUNK):
        lines.append(f">>{tmp_name} echo {blob[i:i + _CHUNK]}")
    lines.append(
        f'%PYTHON_EXEC% -c "import base64;'
        f"open({out_literal},'wb').write(base64.b64decode(open('{tmp_name}','rb').read()))\""
    )
    lines.append(f"del {tmp_name}")


def _render_bat(
    *,
    deployer_repo: str,
    deployer_branch: str,
    archive_url: str,
    settings_b64: str,
    extra_yaml_b64: str | None,
    workflows_b64: str | None = None,
    plugins_b64: str | None = None,
) -> str:
    """Return the full CRLF-joined contents of the install .bat."""
    branch_flag = (
        f"-b {deployer_branch} " if deployer_branch and deployer_branch != "HEAD" else ""
    )

    lines: list[str] = [
        "@echo off",
        "setlocal",
        "cd /d \"%~dp0\"",
        "",
        "REM ============================================================",
        "REM  Self-contained ComfyUI bundle installer",
        "REM  Generated by ComfyUI Deployer. Models are NOT included.",
        "REM ============================================================",
        "",
        "REM --- Require git ---",
        "where git >nul 2>&1",
        "if %ERRORLEVEL% NEQ 0 (",
        "    echo git not found. Please install Git and add it to your PATH.",
        "    pause",
        "    exit /b 1",
        ")",
        "",
        "REM --- Locate 7z ---",
        "set \"SEVENZIP=7z\"",
        "where 7z >nul 2>&1",
        "if %ERRORLEVEL% NEQ 0 (",
        "    if exist \"C:\\Program Files\\7-Zip\\7z.exe\" (",
        "        set \"SEVENZIP=C:\\Program Files\\7-Zip\\7z.exe\"",
        "    ) else if exist \"C:\\Program Files (x86)\\7-Zip\\7z.exe\" (",
        "        set \"SEVENZIP=C:\\Program Files (x86)\\7-Zip\\7z.exe\"",
        "    ) else (",
        "        echo 7z not found. Please install 7-Zip or add it to your PATH.",
        "        pause",
        "        exit /b 1",
        "    )",
        ")",
        "",
        "REM --- Clone the ComfyUI Deployer into the export root ---",
        "REM git refuses a non-empty target, so clone into a temp folder then",
        "REM move everything (incl. .git) up to the root next to this .bat.",
        "if not exist \"main.py\" (",
        "    echo Cloning ComfyUI Deployer...",
        f"    git clone --recursive {branch_flag}{deployer_repo} \"_deployer_clone\"",
        "    if errorlevel 1 (",
        "        echo Failed to clone the ComfyUI Deployer.",
        "        pause",
        "        exit /b 1",
        "    )",
        "    echo Moving files to the export root...",
        "    robocopy \"_deployer_clone\" \".\" /E /MOVE /NFL /NDL /NJH /NJS /NC /NS >nul",
        "    rmdir /s /q \"_deployer_clone\" 2>nul",
        "    if not exist \"main.py\" (",
        "        echo Failed to move the ComfyUI Deployer to the export root.",
        "        pause",
        "        exit /b 1",
        "    )",
        ") else (",
        "    echo ComfyUI Deployer already present, skipping clone.",
        ")",
        "",
        "set PYTHON_EXEC=.\\ComfyUI_windows_portable\\python_embeded\\python.exe",
        "",
        "REM --- Download ComfyUI portable if needed ---",
        "if not exist ComfyUI_windows_portable_nvidia.7z if not exist ComfyUI_windows_portable (",
        "    echo Downloading ComfyUI archive...",
        f"    powershell -Command \"(New-Object System.Net.WebClient).DownloadFile('{archive_url}', 'ComfyUI_windows_portable_nvidia.7z')\"",
        ")",
        "",
        "REM --- Extract ComfyUI if needed ---",
        "if not exist ComfyUI_windows_portable if exist ComfyUI_windows_portable_nvidia.7z (",
        "    echo Extracting ComfyUI archive...",
        "    \"%SEVENZIP%\" x ComfyUI_windows_portable_nvidia.7z -y",
        ")",
        "if exist ComfyUI_windows_portable_nvidia.7z (",
        "    echo Removing archive...",
        "    del ComfyUI_windows_portable_nvidia.7z",
        ")",
        "",
        "REM --- Install python dependencies into the embedded python ---",
        "echo Checking dependencies...",
        "%PYTHON_EXEC% -c \"import PyQt6\" 2>nul",
        "if errorlevel 1 %PYTHON_EXEC% -m pip install PyQt6",
        "%PYTHON_EXEC% -c \"import yaml\" 2>nul",
        "if errorlevel 1 %PYTHON_EXEC% -m pip install pyyaml",
        "%PYTHON_EXEC% -c \"import uv\" 2>nul",
        "if errorlevel 1 %PYTHON_EXEC% -m pip install uv",
        "",
        "REM --- Write user_settings.json (embedded) ---",
        "echo Writing user_settings.json...",
    ]

    _emit_b64(lines, settings_b64, "user_settings.b64", "'user_settings.json'")

    if extra_yaml_b64:
        lines += [
            "",
            "REM --- Write extra_model_paths.yaml (embedded) ---",
            "echo Writing extra_model_paths.yaml...",
        ]
        _emit_b64(
            lines,
            extra_yaml_b64,
            "extra_model_paths.b64",
            "'ComfyUI_windows_portable/ComfyUI/extra_model_paths.yaml'",
        )

    if workflows_b64:
        lines += [
            "",
            "REM --- Extract embedded workflows into workflows/ ---",
            "echo Extracting workflows...",
        ]
        # Write the tarball as a temp .b64 file, then decode + extract via python.
        _emit_b64(lines, workflows_b64, "workflows.b64", "'workflows.tar'")
        lines.append(
            "%PYTHON_EXEC% -c \"import tarfile,os;os.makedirs('workflows',exist_ok=True);"
            "tarfile.open('workflows.tar').extractall('workflows')\""
        )
        lines.append("del workflows.tar 2>nul")

    if plugins_b64:
        lines += [
            "",
            "REM --- Extract embedded local plugins into plugins/ ---",
            "echo Installing local plugins...",
        ]
        _emit_b64(lines, plugins_b64, "plugins.b64", "'plugins.tar'")
        lines.append(
            "%PYTHON_EXEC% -c \"import tarfile,os;os.makedirs('plugins',exist_ok=True);"
            "tarfile.open('plugins.tar').extractall('plugins')\""
        )
        lines.append("del plugins.tar 2>nul")

    lines += [
        "",
        "REM --- Clone custom nodes and install their requirements ---",
        "REM ComfyUI's embedded python uses a ._pth file that drops the cwd from",
        "REM sys.path, so we add it back explicitly (like main.py) instead of -m.",
        "echo Installing custom nodes...",
        '%PYTHON_EXEC% -s -c "import sys,os;sys.path.insert(0,os.getcwd());from deployer.bundle.headless_install import run;run()"',
        "",
        "echo.",
        "echo Done. Run Launch.bat to start the ComfyUI Deployer.",
        "pause",
        "",
    ]

    return "\r\n".join(lines)


def create_sharable_bat(
    dest_dir: str,
    workflow_paths: list[str],
    *,
    export_advanced: bool = False,
    extra_repos: list[tuple[str, str]] | None = None,
    include_workflows: bool = False,
    steps: list[dict] | None = None,
    plugin_repos: list[dict] | None = None,
) -> str:
    """Generate the sharable install ``.bat`` at *dest_dir*; return its path.

    No heavy local build happens — only the small script is written. The node
    list is derived from the live install (trimmed by *workflow_paths* when
    given, plus *extra_repos* resolved from those workflows). When
    *export_advanced* is set, the whole ``settings`` subdict and the current
    ``extra_model_paths.yaml`` are embedded. When *include_workflows* is set,
    the *workflow_paths* files are tarred and embedded; the .bat extracts them
    into a ``workflows/`` folder next to itself at install time.

    *steps* (configured bundle-step plugins) are embedded in the
    ``user_settings.json``; the headless install replays the INSTALL-phase ones
    on the recipient's machine.
    """
    repo_url = git_ops.get_remote_url(PROJECT_ROOT)
    if not repo_url:
        raise RuntimeError(
            "Cannot export a sharable .bat: no 'origin' remote found in "
            f"{PROJECT_ROOT}. The recipient needs a clonable Deployer repo URL."
        )
    branch = git_ops.get_current_branch(PROJECT_ROOT)

    nodes = _build_node_list(workflow_paths, extra_repos)

    data: dict = {"nodes": nodes}
    if steps:
        # Persisted as-is; the headless install replays the INSTALL-phase ones
        # on the recipient's machine (plugin modules ship with the cloned deployer).
        data["steps"] = steps
    if plugin_repos:
        data["plugins"] = {"remote": plugin_repos}
    extra_yaml_b64: str | None = None
    if export_advanced:
        settings = UserSettings.load_settings()
        if settings:
            data["settings"] = settings
        if os.path.exists(EXTRA_MODEL_PATHS_YAML):
            with open(EXTRA_MODEL_PATHS_YAML, "rb") as fh:
                extra_yaml_b64 = base64.b64encode(fh.read()).decode("ascii")

    settings_b64 = base64.b64encode(
        json.dumps(data, indent=4, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")

    workflows_b64: str | None = None
    if include_workflows and workflow_paths:
        workflows_b64 = _build_workflows_tarball_b64(workflow_paths)
        print(f"Embedded {len(workflow_paths)} workflow(s) into the .bat")

    local_plugin_paths = _collect_local_plugins(_LOCAL_PLUGINS_DIR)
    plugins_b64 = _build_plugins_tarball_b64(local_plugin_paths)
    if plugins_b64:
        print(f"Embedded {len(local_plugin_paths)} local plugin(s) into the .bat")

    content = _render_bat(
        deployer_repo=repo_url,
        deployer_branch=branch,
        archive_url=_archive_url(get_comfyui_version()),
        settings_b64=settings_b64,
        extra_yaml_b64=extra_yaml_b64,
        workflows_b64=workflows_b64,
        plugins_b64=plugins_b64,
    )

    os.makedirs(dest_dir, exist_ok=True)
    bat_path = os.path.join(dest_dir, BAT_FILENAME)
    with open(bat_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)

    print(f"Wrote sharable installer with {len(nodes)} node(s) to {bat_path}")
    return bat_path

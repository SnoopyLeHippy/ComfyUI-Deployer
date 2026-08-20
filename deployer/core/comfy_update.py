"""Runs ComfyUI's own updater while preserving the Deployer's junctions.

``ComfyUI_windows_portable/update/update_comfyui.bat`` stashes the working
tree and checks ``master`` back out. ``models/``, ``output/`` and ``input/``
are *tracked* directories in the ComfyUI repo, so that checkout wipes the
junctions the Deployer creates there (see
:mod:`deployer.ui.dialogs.advanced_settings`) and — worse, while they are
still in place — writes ComfyUI's ``put_*_here`` placeholders straight into
the user's external folders.

:func:`update_comfyui` therefore detaches the junctions *before* handing
control to the .bat and re-creates them afterwards, whatever the updater's
exit code.

No Qt here: this is plain business logic, callable from a worker thread.
"""

import os

from deployer.config import (
    INPUT_DIR,
    MODELS_DIR,
    OUTPUT_DIR,
    UPDATE_COMFYUI_BAT,
    UPDATE_DIR,
)
from deployer.core.junctions import (
    is_junction,
    read_junction_target,
    replace_with_junction,
)
from deployer.core.pip_runner import run_command


# The ComfyUI folders the Deployer may have turned into junctions. Same set as
# ``advanced_settings._FOLDER_JUNCTIONS``, minus the settings-key plumbing.
JUNCTIONED_DIRS = (MODELS_DIR, OUTPUT_DIR, INPUT_DIR)


def snapshot_junctions(paths: tuple[str, ...] = JUNCTIONED_DIRS) -> dict[str, str]:
    """Return ``{path: junction target}`` for every *path* that is a junction.

    Read from disk rather than from ``user_settings.json`` so a junction
    created by hand is restored too.
    """
    return {path: target for path in paths if (target := read_junction_target(path))}


def detach_junctions(snapshot: dict[str, str]) -> None:
    """Remove the junctions listed in *snapshot*, leaving nothing behind.

    ``os.rmdir`` on a junction deletes only the reparse point — the target
    folder and its contents are untouched. Failures are logged, never raised:
    a junction we cannot detach must not abort the update.
    """
    for path in snapshot:
        try:
            if is_junction(path):
                os.rmdir(path)
                print(f"Detached junction: {path}")
        except OSError as exc:
            print(f"Could not detach junction {path}: {exc}")


def restore_junctions(snapshot: dict[str, str]) -> None:
    """Re-create every junction in *snapshot*, replacing whatever sits there.

    The updater's checkout recreates ``models/`` & co. as real directories
    holding only ComfyUI's tracked placeholders, so replacing them wholesale
    is safe. Failures are logged per entry so one bad target can't leave the
    remaining junctions unrestored.
    """
    for path, target in snapshot.items():
        try:
            if read_junction_target(path) == target:
                continue  # already pointing where it should
            replace_with_junction(path, target)
            print(f"Restored junction: {path} -> {target}")
        except Exception as exc:  # noqa: BLE001
            print(f"Could not restore junction {path} -> {target}: {exc}")


def update_comfyui(*, stream_output: bool = True) -> int:
    """Run ``update_comfyui.bat`` with the junctions detached, then restore them.

    Returns the updater's exit code, or ``-1`` if the .bat is missing.
    The restore pass runs in a ``finally`` block, so an updater crash still
    leaves the junctions in place.
    """
    if not os.path.isfile(UPDATE_COMFYUI_BAT):
        print(f"ComfyUI updater not found: {UPDATE_COMFYUI_BAT}")
        return -1

    snapshot = snapshot_junctions()
    if snapshot:
        print(f"Preserving {len(snapshot)} junction(s) across the update:")
        for path, target in snapshot.items():
            print(f"  {path} -> {target}")
    detach_junctions(snapshot)

    try:
        print(f"Running {UPDATE_COMFYUI_BAT}...")
        # The trailing argument only has to be non-empty: the .bat ends with
        # ``if "%~1"=="" pause``, which would otherwise block on a headless
        # console forever.
        return run_command(
            ["cmd", "/c", UPDATE_COMFYUI_BAT, "nopause"],
            stream_output=stream_output,
            cwd=UPDATE_DIR,
        )
    finally:
        restore_junctions(snapshot)

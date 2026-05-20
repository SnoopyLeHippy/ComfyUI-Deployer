"""Read the installed ComfyUI version and download a clean bundle archive."""

import os
import shutil
import subprocess

from deployer.config import COMFYUI_DIR, PORTABLE_DIR
from deployer.core.http import download_file


_ARCHIVE_NAME = "ComfyUI_windows_portable_nvidia.7z"
_RELEASE_URL_FMT = "https://github.com/Comfy-Org/ComfyUI/releases/download/v{version}/" + _ARCHIVE_NAME

_SEVENZIP_FALLBACK_PATHS = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
)


def _find_7z() -> str:
    """Locate the 7z executable in PATH or common install locations."""
    exe = shutil.which("7z") or shutil.which("7z.exe")
    if exe:
        return exe
    for candidate in _SEVENZIP_FALLBACK_PATHS:
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        "7z executable not found. Install 7-Zip from https://www.7-zip.org/ "
        "or add 7z to your PATH."
    )


def get_comfyui_version() -> str:
    """Return the installed ComfyUI version, or ``"latest"`` if it can't be read."""
    ver_file = os.path.join(COMFYUI_DIR, "comfyui_version.py")
    try:
        with open(ver_file, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("__version__"):
                    return line.split("=")[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return "latest"


def download_and_extract_comfyui(dest_dir: str, version: str) -> None:
    """Download the ComfyUI portable archive for *version* and extract to *dest_dir*."""
    archive_path = os.path.join(dest_dir, _ARCHIVE_NAME)
    url = _RELEASE_URL_FMT.format(version=version)

    print(f"Downloading ComfyUI v{version}...")
    # GitHub release archives are several gigabytes — give the download a
    # generous ceiling so a slow link doesn't time out mid-transfer.
    download_file(url, archive_path, timeout=3600)

    print("Extracting archive...")
    seven_zip = _find_7z()
    subprocess.run([seven_zip, "x", archive_path, f"-o{dest_dir}", "-y"], check=True)

    if os.path.exists(archive_path):
        os.remove(archive_path)

    print("ComfyUI base installation ready.")


# Re-exported for callers that want to know where the archive comes from.
PORTABLE_SOURCE_DIR = PORTABLE_DIR

"""HTTP download helpers with a PowerShell fallback for broken SSL stores.

Some Windows installs ship the embedded Python with a stale CA bundle, which
makes ``urllib`` fail on HTTPS even when ``certifi`` is present. PowerShell's
``Invoke-WebRequest`` uses the OS trust store and consistently works in those
cases, so we keep it as a fallback.

The URL and destination path are passed to PowerShell via **environment
variables** rather than interpolated into the command string. This prevents
quote / single-quote / backtick characters in user-provided paths from
breaking out of the script.
"""

import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _download_urllib(url: str, dest_path: str, *, timeout: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Deployer"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        payload = resp.read()
    with open(dest_path, "wb") as fh:
        fh.write(payload)


def _download_powershell(url: str, dest_path: str, *, timeout: int) -> None:
    """Fallback for Windows machines with a broken Python SSL trust store.

    Passes URL/dest via env vars so values containing apostrophes, dollar
    signs or backticks can't break out of the PS script.
    """
    if sys.platform != "win32":
        raise RuntimeError("PowerShell fallback only available on Windows")
    env = os.environ.copy()
    env["DL_URL"] = url
    env["DL_DEST"] = dest_path
    script = (
        "$ProgressPreference = 'SilentlyContinue'; "
        "Invoke-WebRequest -Uri $env:DL_URL -OutFile $env:DL_DEST -UseBasicParsing"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def download_file(url: str, dest_path: str, *, timeout: int = 60) -> None:
    """Download *url* to *dest_path*. urllib first, PowerShell fallback on SSL/URL errors.

    Raises whatever PowerShell raised if both attempts fail.
    """
    print(f"Downloading {url}...")
    try:
        _download_urllib(url, dest_path, timeout=timeout)
        return
    except (urllib.error.URLError, ssl.SSLError) as exc:
        print(f"  urllib failed ({exc.__class__.__name__}); trying PowerShell fallback...")
    _download_powershell(url, dest_path, timeout=timeout)

"""HTTP download helper: ``urllib`` with certifi, then with Windows' own trust store.

Some Windows installs ship the embedded Python with a stale CA bundle, which
makes ``urllib`` fail on HTTPS even when ``certifi`` is present — and a
company proxy that inspects TLS signs with a root only Windows' certificate
store holds. So a failed attempt with certifi is retried once with the
system's default context, which on Windows loads the machine's ROOT and CA
stores: what a PowerShell ``Invoke-WebRequest`` used to be started for here.

No process is started: endpoint security flags a script host launching
PowerShell, and the window reaches this path (workflow resolution).
"""

import ssl
import urllib.error
import urllib.request


def _certifi_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def _contexts() -> list[ssl.SSLContext]:
    """certifi's bundle first when installed, then the system's trust store."""
    certifi_context = _certifi_context()
    system = ssl.create_default_context()
    return [certifi_context, system] if certifi_context is not None else [system]


def _download_urllib(url: str, dest_path: str, *, timeout: int, context: ssl.SSLContext) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Deployer"})
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        payload = resp.read()
    with open(dest_path, "wb") as fh:
        fh.write(payload)


def download_file(url: str, dest_path: str, *, timeout: int = 60) -> None:
    """Download *url* to *dest_path*; a failure with certifi is retried with the system store.

    Raises the last attempt's error (``urllib.error.URLError``, ``ssl.SSLError``,
    ``OSError``) when every attempt fails. An HTTP error status is not retried.
    """
    print(f"Downloading {url}...")
    contexts = _contexts()
    for attempt, context in enumerate(contexts, start=1):
        try:
            _download_urllib(url, dest_path, timeout=timeout, context=context)
            return
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ssl.SSLError, OSError) as exc:
            if attempt == len(contexts):
                raise
            print(f"  download failed ({exc.__class__.__name__}); retrying with the system's "
                  "certificate store...")

"""Small filesystem utilities shared across the project."""

import os
import stat


def force_remove_readonly(func, path, _exc_info):
    """``shutil.rmtree`` ``onerror`` handler: clear the read-only flag and retry.

    Git pack files are checked out read-only on Windows, which makes
    ``shutil.rmtree`` fail with ``PermissionError`` unless we re-enable write
    access first.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)

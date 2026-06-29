"""Persistence layer for ``user_settings.json``.

All read/write access to the project's user settings file lives here so the
on-disk schema is owned by a single module. The file format is::

    {
        "nodes": [
            {"repo": ..., "ref": ..., "description": ...},
            ...
        ],
        "settings": {                # optional, written by Advanced Settings
            "extra_model_path": ...,
            "model_folder": ...,
            "output_folder": ...,
            "input_folder": ...
        },
        "steps": [                   # optional, configured bundle-step plugins
            {"id": ..., "config": {...}},
            ...
        ],
        "plugins": {                 # optional, remote plugin repos
            "remote": [
                {"repo": ..., "ref": "main"},
                ...
            ]
        }
    }

Two write modes, both of which preserve all other keys:

* :meth:`UserSettings.save_nodes` reads the existing file, updates only the
  ``nodes`` key, and writes it back so the ``settings`` subdict is preserved.
* :meth:`UserSettings.save_settings` reads the existing file, updates only
  the ``settings`` subdict, and writes it back so the node list is preserved.
"""

import json
import os

from deployer.config import USER_SETTINGS_JSON


class UserSettings:
    """Repository for the persisted node list and folder settings."""

    PATH: str = USER_SETTINGS_JSON

    @classmethod
    def exists(cls) -> bool:
        return os.path.exists(cls.PATH)

    @classmethod
    def load_raw(cls) -> dict:
        """Return the full file as a dict, or an empty dict if missing/invalid."""
        try:
            with open(cls.PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def load_nodes(cls) -> list[dict]:
        """Return the node entries, or ``[]`` if the file is missing or empty."""
        return cls.load_raw().get("nodes", [])

    @classmethod
    def save_nodes(cls, nodes: list[dict]) -> None:
        """Update the ``nodes`` key, preserving all other keys (settings, steps, plugins)."""
        data = cls.load_raw() or {}
        data["nodes"] = nodes
        with open(cls.PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False)

    @classmethod
    def load_steps(cls) -> list[dict]:
        """Return the configured bundle steps, or ``[]`` if absent.

        Each entry is ``{"id": <plugin id>, "config": {...}}``. Written into a
        bundle's ``user_settings.json`` at creation time and replayed by the
        plugin runner during the install phase.
        """
        return cls.load_raw().get("steps", [])

    @classmethod
    def load_plugin_repos(cls) -> list[dict]:
        """Return the remote plugin repo entries, or ``[]`` if absent.

        Each entry is ``{"repo": <url>, "ref": <branch/tag/commit>}``.
        """
        return cls.load_raw().get("plugins", {}).get("remote", [])

    @classmethod
    def save_plugin_repos(cls, repos: list[dict]) -> None:
        """Update the remote plugin repo list, preserving all other keys."""
        data = cls.load_raw() or {"nodes": []}
        if repos:
            data.setdefault("plugins", {})["remote"] = repos
        else:
            data.get("plugins", {}).pop("remote", None)
            if not data.get("plugins"):
                data.pop("plugins", None)
        with open(cls.PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False)

    @classmethod
    def load_settings(cls) -> dict:
        """Return the ``settings`` subdict, or ``{}`` if absent."""
        return cls.load_raw().get("settings", {})

    @classmethod
    def save_settings(cls, settings: dict) -> None:
        """Update the ``settings`` subdict, preserving the existing node list."""
        data = cls.load_raw() or {"nodes": []}
        data["settings"] = settings
        with open(cls.PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False)

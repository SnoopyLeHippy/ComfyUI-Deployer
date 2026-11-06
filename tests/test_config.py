"""deployer.config: DEPLOYER_PORTABLE_DIR moves every ComfyUI path, the default stays.

config reads the variable once, at import — each case imports it in a fresh
interpreter. Run: python tests/test_config.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402  (first: sandbox + import path)

import json  # noqa: E402
import subprocess  # noqa: E402
import unittest  # noqa: E402

from deployer import PORTABLE_DIR_ENV

_PROBE = (
    "import json, sys; sys.path.insert(0, sys.argv[1]); from deployer import config as c; "
    "print(json.dumps({k: getattr(c, k) for k in ('PORTABLE_DIR', 'COMFYUI_DIR', 'PYTHON_EXE', "
    "'CUSTOM_NODES_DIR', 'UPDATE_COMFYUI_BAT', 'USER_SETTINGS_JSON')}))"
)


def _config_with(value: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k != PORTABLE_DIR_ENV}
    if value is not None:
        env[PORTABLE_DIR_ENV] = value
    out = subprocess.run(
        [sys.executable, "-c", _PROBE, _support.REPO_ROOT],
        env=env, capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class PortableDirTest(unittest.TestCase):
    def test_an_absolute_folder_moves_every_comfyui_path(self):
        target = os.path.join(_support.SANDBOX, "elsewhere", "ComfyUI")
        paths = _config_with(target)
        self.assertTrue(_same(paths["PORTABLE_DIR"], target))
        self.assertTrue(_same(paths["COMFYUI_DIR"], os.path.join(target, "ComfyUI")))
        self.assertTrue(_same(paths["PYTHON_EXE"], os.path.join(target, "python_embeded", "python.exe")))
        self.assertTrue(_same(paths["CUSTOM_NODES_DIR"], os.path.join(target, "ComfyUI", "custom_nodes")))
        self.assertTrue(_same(paths["UPDATE_COMFYUI_BAT"], os.path.join(target, "update", "update_comfyui.bat")))

    def test_the_node_list_stays_in_the_project(self):
        paths = _config_with(os.path.join(_support.SANDBOX, "elsewhere"))
        self.assertTrue(_same(paths["USER_SETTINGS_JSON"], os.path.join(_support.REPO_ROOT, "user_settings.json")))

    def test_a_relative_folder_is_read_from_the_project_root(self):
        paths = _config_with(os.path.join("..", "SharedComfy"))
        expected = os.path.join(os.path.dirname(_support.REPO_ROOT), "SharedComfy")
        self.assertTrue(_same(paths["PORTABLE_DIR"], expected))

    def _skip_if_dot_env_sets_it(self):
        env_file = os.path.join(_support.REPO_ROOT, ".env")
        if os.path.exists(env_file):
            with open(env_file, encoding="utf-8-sig") as fh:
                if PORTABLE_DIR_ENV in fh.read():
                    self.skipTest(f"this clone's .env sets {PORTABLE_DIR_ENV}")

    def test_without_it_the_projects_own_portable_is_used(self):
        self._skip_if_dot_env_sets_it()
        paths = _config_with(None)
        self.assertTrue(_same(paths["PORTABLE_DIR"], os.path.join(_support.REPO_ROOT, "ComfyUI_windows_portable")))

    def test_a_blank_value_keeps_the_default(self):
        self._skip_if_dot_env_sets_it()
        paths = _config_with("   ")
        self.assertTrue(_same(paths["PORTABLE_DIR"], os.path.join(_support.REPO_ROOT, "ComfyUI_windows_portable")))


if __name__ == "__main__":
    unittest.main()

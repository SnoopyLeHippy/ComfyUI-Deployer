"""cli.py — the Deployer's command line, end to end and per command.

The end-to-end cases run ``cli.py`` in a child process from a **copy** of the
project (its own ``custom_nodes.json`` / ``user_settings.json``, never this
clone's), on a throwaway portable. Run: python tests/test_cli.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402  (first: sandbox + import path)

import importlib.util  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from _support import ProcessSpy, git, make_portable, make_repo  # noqa: E402
from deployer import PORTABLE_DIR_ENV, cli  # noqa: E402


def _copy_project(dest: str) -> str:
    """The launcher and the package — what a clone needs to run cli.py."""
    os.makedirs(dest)
    shutil.copy2(os.path.join(_support.REPO_ROOT, "cli.py"), dest)
    shutil.copytree(
        os.path.join(_support.REPO_ROOT, "deployer"),
        os.path.join(dest, "deployer"),
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return dest


class CommandLineTest(unittest.TestCase):
    """cli.py in a child process."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(dir=_support.SANDBOX)
        cls.project = _copy_project(os.path.join(cls.root, "ComfyUI-Deployer"))

    def setUp(self):
        self.work = tempfile.mkdtemp(dir=self.root)
        self.portable = make_portable(os.path.join(self.work, "ComfyUI"))
        self.repos = os.path.join(self.work, "repos")
        for name in ("user_settings.json", "custom_nodes.json"):
            path = os.path.join(self.project, name)
            if os.path.exists(path):
                os.remove(path)

    def write_manifest(self, entries: list[dict]) -> None:
        with open(os.path.join(self.project, "custom_nodes.json"), "w", encoding="utf-8") as fh:
            json.dump(entries, fh)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != PORTABLE_DIR_ENV}
        return subprocess.run(
            [sys.executable, "-s", os.path.join(self.project, "cli.py"), *args],
            cwd=self.work, env=env, capture_output=True, text=True, encoding="utf-8",
            stdin=subprocess.DEVNULL, timeout=120,
        )

    def events(self, proc: subprocess.CompletedProcess) -> list[dict]:
        """Every stdout line, each of which must be a JSON object."""
        events = []
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                self.fail(f"stdout line is not JSON: {line!r}\n--- stderr:\n{proc.stderr}")
            self.assertIsInstance(event, dict)
            events.append(event)
        return events

    def test_install_nodes_reports_on_stdout_in_json_only(self):
        a = make_repo(os.path.join(self.repos, "NodeA"))
        b = make_repo(os.path.join(self.repos, "NodeB"))
        git("branch", "dev", cwd=b)  # checking it out writes to git's stdout
        self.write_manifest([{"repo": a, "ref": "main", "description": ""}, {"repo": b, "ref": "dev"}])

        proc = self.run_cli("install-nodes", "--portable", self.portable)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        events = self.events(proc)
        self.assertEqual(events[-1], {"result": {
            "added": [], "installed": ["NodeA", "NodeB"], "present": [], "failed": [], "requirements_failed": [],
        }})
        progress = [e for e in events if "progress" in e]
        self.assertTrue(progress and all("message" in e for e in progress))
        self.assertEqual(progress[-1]["progress"], 1.0)
        self.assertIn("set up to track", proc.stderr)  # git's stdout went to stderr
        nodes = os.path.join(self.portable, "ComfyUI", "custom_nodes")
        self.assertEqual(sorted(os.listdir(nodes)), ["NodeA", "NodeB"])
        with open(os.path.join(self.project, "user_settings.json"), encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)["nodes"]), 2)

    def test_a_node_that_cannot_be_cloned_fails_with_exit_code_1(self):
        a = make_repo(os.path.join(self.repos, "NodeA"))
        self.write_manifest([{"repo": os.path.join(self.repos, "Gone")}, {"repo": a}])

        proc = self.run_cli("install-nodes", "--portable", self.portable)

        self.assertEqual(proc.returncode, 1)
        events = self.events(proc)
        result = events[-1]["result"]
        self.assertEqual(result["installed"], ["NodeA"])
        self.assertEqual([f["name"] for f in result["failed"]], ["Gone"])
        self.assertTrue(any("Gone" in e.get("warning", "") for e in events))
        self.assertEqual(proc.stderr.strip().splitlines()[-1], "Not installed: Gone.")

    def test_a_nodes_file_is_the_list_of_a_fresh_clone(self):
        a = make_repo(os.path.join(self.repos, "NodeA"))
        b = make_repo(os.path.join(self.repos, "NodeB"))
        self.write_manifest([{"repo": a}])
        listed = os.path.join(self.work, "studio nodes.json")
        with open(listed, "w", encoding="utf-8") as fh:
            json.dump([{"repo": b, "ref": "main", "description": "the studio's"}], fh)

        proc = self.run_cli("install-nodes", "--portable", self.portable, "--nodes-file", listed)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = self.events(proc)[-1]["result"]
        self.assertEqual((result["added"], result["installed"]), (["NodeB"], ["NodeB"]))
        self.assertEqual(os.listdir(os.path.join(self.portable, "ComfyUI", "custom_nodes")), ["NodeB"])
        with open(os.path.join(self.project, "user_settings.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["nodes"], [{"repo": b, "ref": "main", "description": "the studio's"}])

    def test_a_nodes_file_that_cannot_be_used_is_a_usage_error(self):
        a = make_repo(os.path.join(self.repos, "NodeA"))
        self.write_manifest([{"repo": a}])
        listed = os.path.join(self.work, "nodes.json")
        for content, reason in (
                (None, "cannot be read as a node list"),
                ("{ not json", "cannot be read as a node list"),
                ('"a string"', "cannot be read as a node list"),
                ("[]", "lists no custom node"),
                ('[{"ref": "main"}]', "lists no custom node"),
        ):
            with self.subTest(content=content):
                if content is None:
                    if os.path.exists(listed):
                        os.remove(listed)
                else:
                    with open(listed, "w", encoding="utf-8") as fh:
                        fh.write(content)
                proc = self.run_cli("install-nodes", "--portable", self.portable, "--nodes-file", listed)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, "")
                self.assertIn(reason, proc.stderr)
        # Nothing installed, no list written: the default list was never read in its place.
        self.assertEqual(os.listdir(os.path.join(self.portable, "ComfyUI", "custom_nodes")), [])
        self.assertFalse(os.path.exists(os.path.join(self.project, "user_settings.json")))

    def test_a_folder_that_is_not_a_portable_is_refused_with_exit_code_2(self):
        empty = os.path.join(self.work, "not-comfy")
        os.makedirs(empty)
        for command in ("install-nodes", "gui"):
            with self.subTest(command=command):
                proc = self.run_cli(command, "--portable", empty)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, "")
                self.assertIn("not a ComfyUI portable folder", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(empty, "ComfyUI")))  # nothing created there

    def test_without_portable_the_projects_own_folder_is_used(self):
        proc = self.run_cli("install-nodes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn(os.path.join(self.project, "ComfyUI_windows_portable"), proc.stderr)

    def test_an_unknown_command_is_a_usage_error(self):
        proc = self.run_cli("update-everything")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")


class RecordingChannel:
    def __init__(self):
        self.events: list[dict] = []

    def message(self, text, progress=None):
        self.events.append({"message": text, "progress": progress})

    def warning(self, text):
        self.events.append({"warning": text})

    def result(self, value):
        self.events.append({"result": value})


class InstallDepsTest(unittest.TestCase):
    """install-deps against a faked interpreter: which packages, how pip is started."""

    def run_deps(self, missing: set[str], pip_exit: int = 0):
        installed: set[str] = set()
        real_find_spec = importlib.util.find_spec

        def find_spec(name, *args):
            if name in missing and name not in installed:
                return None
            return real_find_spec(name, *args) or object()

        def exit_code(argv):
            if pip_exit == 0:
                installed.update(module for module, package in cli.DEPLOYER_PACKAGES if package in argv)
            return pip_exit

        channel = RecordingChannel()
        with mock.patch.object(importlib.util, "find_spec", find_spec), \
                ProcessSpy([sys.executable], exit_code) as spy:
            code = cli.install_deps(channel)
        spy.assert_no_shell(self)
        return code, channel.events, spy

    def test_missing_packages_are_installed_with_pip_in_this_interpreter(self):
        code, events, spy = self.run_deps({"PyQt6", "uv"})
        self.assertEqual(code, 0)
        self.assertEqual(spy.faked(), [[sys.executable, "-m", "pip", "install", "PyQt6", "uv"]])
        self.assertEqual(events[-1], {"result": {"installed": ["PyQt6", "uv"], "missing": []}})

    def test_nothing_missing_starts_nothing(self):
        code, events, spy = self.run_deps(set())
        self.assertEqual(code, 0)
        self.assertEqual(spy.calls, [])
        self.assertEqual(events, [{"result": {"installed": [], "missing": []}}])

    def test_a_pip_failure_exits_1_and_says_what_is_missing(self):
        code, events, _ = self.run_deps({"yaml"}, pip_exit=1)
        self.assertEqual(code, 1)
        self.assertEqual(events[-1], {"result": {"installed": [], "missing": ["pyyaml"]}})


if __name__ == "__main__":
    unittest.main()

"""core.junctions: real junctions on disk, made and read without starting any process.

The window checks every ``custom_nodes`` folder as it opens: ``fsutil`` and
``cmd /c mklink`` used to start there (a console each, and a shell chain
endpoint security flags).

And: the junctioned ``models`` / ``output`` / ``input`` folders reach ComfyUI as
``--models-directory`` / ``--output-directory`` / ``--input-directory``. Started
from MoodMiner, under Windows' RedirectionTrust, ComfyUI could not cross them
(``FolderArgumentsTest`` runs that case under the policy, in a child).

Run: python tests/test_junctions.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import json  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

from _support import REPO_ROOT, SANDBOX, ProcessSpy, rmtree  # noqa: E402
from deployer import config  # noqa: E402
from deployer.core import comfy_runner  # noqa: E402
from deployer.core.junctions import (  # noqa: E402
    create_junction,
    folder_arguments,
    is_junction,
    read_junction_target,
    replace_with_junction,
)

ALL_FLAGS = ("--models-directory", "--output-directory", "--input-directory")


def deployer_folders(comfy_dir: str, resources: str, flags=ALL_FLAGS) -> dict[str, str]:
    """``models`` / ``output`` / ``input`` junctioned into *resources*, as the Advanced settings do.

    *flags*: the folder arguments this ComfyUI's ``comfy/cli_args.py`` declares.
    Returns each folder's target.
    """
    os.makedirs(os.path.join(comfy_dir, "comfy"), exist_ok=True)
    with open(os.path.join(comfy_dir, "comfy", "cli_args.py"), "w", encoding="utf-8") as fh:
        fh.write("".join(f'parser.add_argument("{flag}", type=str)\n' for flag in flags))
    targets = {}
    for folder in ("models", "output", "input"):
        targets[folder] = os.path.join(resources, folder.title())
        os.makedirs(targets[folder])
        create_junction(os.path.join(comfy_dir, folder), targets[folder])
    return targets


def flags_for(targets: dict[str, str], *folders: str) -> list[str]:
    flag = dict(zip(("models", "output", "input"), ALL_FLAGS))
    return [part for folder in folders for part in (flag[folder], targets[folder])]


#: ``folder_arguments`` in a child under Windows' RedirectionTrust — what this window and the
#: ComfyUI it starts run under when MoodMiner started them (the policy is inherited and cannot
#: be turned off in a process). argv: the project root, the ComfyUI folder.
POLICY_PROBE = r'''
import ctypes, json, os, sys
from ctypes import wintypes
sys.path.insert(0, sys.argv[1])
from deployer.core.junctions import folder_arguments


def enforce_redirection_trust() -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Without it, the pseudo-handle (-1) is truncated to 32 bits and the read below reports 0.
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetProcessMitigationPolicy.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
    kernel32.SetProcessMitigationPolicy.restype = wintypes.BOOL
    kernel32.GetProcessMitigationPolicy.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
    kernel32.GetProcessMitigationPolicy.restype = wintypes.BOOL
    redirection_trust = 16  # ProcessRedirectionTrustPolicy
    enforce = wintypes.DWORD(1)  # EnforceRedirectionTrust
    if not kernel32.SetProcessMitigationPolicy(redirection_trust, ctypes.byref(enforce), 4):
        return False
    read = wintypes.DWORD(0)
    if not kernel32.GetProcessMitigationPolicy(
            kernel32.GetCurrentProcess(), redirection_trust, ctypes.byref(read), 4):
        return False
    return bool(read.value & 1)


comfy = sys.argv[2]
if not enforce_redirection_trust():
    print(json.dumps({"policy": False}))
    sys.exit(0)
try:
    os.listdir(os.path.join(comfy, "models"))
    seen = True
except OSError:
    seen = False
print(json.dumps({"policy": True, "models_seen": seen, "arguments": folder_arguments(comfy)}))
'''


def elevated() -> bool:
    """An elevated process makes trusted junctions, which RedirectionTrust lets through."""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (ImportError, AttributeError, OSError):
        return False


@unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
class JunctionTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(dir=SANDBOX)
        self.target = os.path.join(self.work, "target")
        os.makedirs(self.target)
        with open(os.path.join(self.target, "marker.txt"), "w", encoding="utf-8") as fh:
            fh.write("kept")
        self.link = os.path.join(self.work, "link")

    def test_a_junction_is_created_and_read_without_any_process(self):
        with ProcessSpy([]) as spy:
            create_junction(self.link, self.target)
            self.assertTrue(is_junction(self.link))
            self.assertTrue(os.path.samefile(read_junction_target(self.link), self.target))
        self.assertEqual(spy.calls, [])
        self.assertTrue(os.path.isfile(os.path.join(self.link, "marker.txt")))

    def test_a_plain_folder_a_file_and_nothing_are_not_junctions(self):
        path = os.path.join(self.work, "file.txt")
        open(path, "w").close()
        with ProcessSpy([]) as spy:
            self.assertFalse(is_junction(self.target))
            self.assertFalse(is_junction(path))
            self.assertFalse(is_junction(os.path.join(self.work, "missing")))
        self.assertEqual(spy.calls, [])
        self.assertEqual(read_junction_target(self.target), "")

    def test_a_dangling_junction_is_still_one(self):
        other = os.path.join(self.work, "other")
        os.makedirs(other)
        create_junction(self.link, other)
        os.rmdir(other)
        self.assertTrue(is_junction(self.link))

    def test_a_missing_target_is_refused_and_leaves_nothing(self):
        with self.assertRaises(OSError):
            create_junction(self.link, os.path.join(self.work, "missing"))
        self.assertFalse(os.path.lexists(self.link))

    def test_replacing_a_junction_removes_the_link_only(self):
        create_junction(self.link, self.target)
        other = os.path.join(self.work, "other")
        os.makedirs(other)
        replace_with_junction(self.link, other)
        self.assertTrue(os.path.samefile(read_junction_target(self.link), other))
        self.assertTrue(os.path.isfile(os.path.join(self.target, "marker.txt")))


@unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
class FolderArgumentsTest(unittest.TestCase):
    """Junctioned ``models`` / ``output`` / ``input`` reach ComfyUI as its own arguments."""

    def setUp(self):
        self.work = tempfile.mkdtemp(dir=SANDBOX)
        self.comfy = os.path.join(self.work, "ComfyUI")
        os.makedirs(self.comfy)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for folder in ("models", "output", "input"):
            path = os.path.join(self.comfy, folder)
            if is_junction(path):
                os.rmdir(path)  # the link only, before the recursive delete
        rmtree(self.work)

    def test_every_junctioned_folder_is_named(self):
        targets = deployer_folders(self.comfy, os.path.join(self.work, "ComfyRessources"))
        with ProcessSpy([]) as spy:
            arguments = folder_arguments(self.comfy)
        self.assertEqual(spy.calls, [])
        self.assertEqual(arguments, flags_for(targets, "models", "output", "input"))

    def test_real_folders_add_nothing(self):
        deployer_folders(self.comfy, os.path.join(self.work, "ComfyRessources"))
        for folder in ("models", "output", "input"):
            os.rmdir(os.path.join(self.comfy, folder))
            os.makedirs(os.path.join(self.comfy, folder))
        self.assertEqual(folder_arguments(self.comfy), [])

    def test_an_argument_this_comfyui_does_not_know_is_never_passed(self):
        # Before ComfyUI 0.40 there is no ``--models-directory``, and argparse stops on it.
        targets = deployer_folders(self.comfy, os.path.join(self.work, "ComfyRessources"),
                                   flags=("--output-directory", "--input-directory"))
        self.assertEqual(folder_arguments(self.comfy), flags_for(targets, "output", "input"))
        os.remove(os.path.join(self.comfy, "comfy", "cli_args.py"))  # unreadable: none at all
        self.assertEqual(folder_arguments(self.comfy), [])

    def test_a_junction_to_a_vanished_folder_is_skipped(self):
        targets = deployer_folders(self.comfy, os.path.join(self.work, "ComfyRessources"))
        os.rmdir(targets["models"])
        self.assertEqual(folder_arguments(self.comfy), flags_for(targets, "output", "input"))

    def test_under_redirection_trust_the_targets_still_come(self):
        # The regression: started from MoodMiner, ComfyUI found the junctioned folders empty.
        targets = deployer_folders(self.comfy, os.path.join(self.work, "ComfyRessources"))
        done = subprocess.run([sys.executable, "-c", POLICY_PROBE, REPO_ROOT, self.comfy],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        seen = json.loads(done.stdout.strip().splitlines()[-1])
        if not seen["policy"]:
            self.skipTest("Windows refused the RedirectionTrust policy")
        if not elevated():
            self.assertFalse(seen["models_seen"], "the policy let the junction through")
        self.assertEqual(seen["arguments"], flags_for(targets, "models", "output", "input"))


@unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
class RunComfyCommandTest(unittest.TestCase):
    """The window's *Run ComfyUI* names the junctioned folders (the sandboxed portable)."""

    def tearDown(self):
        for folder in ("models", "output", "input"):
            path = os.path.join(config.COMFYUI_DIR, folder)
            if is_junction(path):
                os.rmdir(path)
        rmtree(os.path.join(config.COMFYUI_DIR, "comfy"))

    def test_the_command_ends_with_the_folder_arguments(self):
        resources = tempfile.mkdtemp(dir=SANDBOX)
        targets = deployer_folders(config.COMFYUI_DIR, resources)
        self.assertEqual(comfy_runner.launch_command(), [
            config.PYTHON_EXE, "-s", os.path.join(config.COMFYUI_DIR, "main.py"),
            "--windows-standalone-build", "--enable-cors-header",
            *flags_for(targets, "models", "output", "input")])

    def test_without_junctions_the_command_is_unchanged(self):
        self.assertEqual(comfy_runner.launch_command()[3:],
                         ["--windows-standalone-build", "--enable-cors-header"])


if __name__ == "__main__":
    unittest.main()

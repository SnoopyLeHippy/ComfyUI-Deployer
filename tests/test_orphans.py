"""core.orphans.discover_untracked_nodes: orphans to track, junctions only shown.

A junction another program keeps in ``custom_nodes`` (MoodMiner links its
clone as ``ComfyUI-MoodMiner``) used to be an orphan: added to the list, then
removed by an install, it took that program out of ComfyUI. It is now listed
apart, as *linked*. Real git on local repositories.
Run: python tests/test_orphans.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import unittest  # noqa: E402

from _support import SandboxTestCase, git, make_repo  # noqa: E402
from deployer.core.junctions import create_junction  # noqa: E402
from deployer.core.node import repo_identity  # noqa: E402
from deployer.core.orphans import discover_untracked_nodes  # noqa: E402


class UntrackedNodesTest(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.source = make_repo(os.path.join(self.repos, "NodeA"))
        git("clone", "-q", self.source, self.node_path("NodeA"), cwd=self.work)
        # A clone kept outside ComfyUI, linked into custom_nodes by someone else.
        self.app_source = make_repo(os.path.join(self.repos, "App"))
        self.app_clone = os.path.join(self.work, "App")
        git("clone", "-q", self.app_source, self.app_clone, cwd=self.work)
        self.linked_name = "ComfyUI-App"
        if sys.platform == "win32":
            create_junction(self.node_path(self.linked_name), self.app_clone)
        else:
            os.symlink(self.app_clone, self.node_path(self.linked_name), target_is_directory=True)

    def test_a_junction_is_linked_not_an_orphan(self):
        untracked = discover_untracked_nodes(set(), set())
        self.assertEqual([name for name, _repo, _ref in untracked.orphans], ["NodeA"])
        self.assertEqual(len(untracked.linked), 1)
        name, target = untracked.linked[0]
        self.assertEqual(name, self.linked_name)
        self.assertTrue(os.path.samefile(target, self.app_clone))

    def test_a_tracked_folder_is_neither(self):
        untracked = discover_untracked_nodes(set(), {"nodea", self.linked_name.upper()})
        self.assertEqual(untracked.orphans, [])
        self.assertEqual(untracked.linked, [])

    def test_a_tracked_origin_is_neither(self):
        known = {repo_identity(self.source), repo_identity(self.app_source)}
        untracked = discover_untracked_nodes(known, set())
        self.assertEqual(untracked.orphans, [])
        self.assertEqual(untracked.linked, [])

    def test_a_folder_without_git_is_skipped(self):
        os.makedirs(self.node_path("loose"))
        untracked = discover_untracked_nodes(set(), {"NodeA", self.linked_name})
        self.assertEqual(untracked, ([], []))


if __name__ == "__main__":
    unittest.main()

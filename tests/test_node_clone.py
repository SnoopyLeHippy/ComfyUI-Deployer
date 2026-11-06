"""CustomNode.clone: a fresh clone lands on the configured ref, not on the default branch.

Real git, on local repositories. Run: python tests/test_node_clone.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import subprocess  # noqa: E402
import unittest  # noqa: E402

from _support import SandboxTestCase, commit, git, head, make_repo  # noqa: E402
from deployer.core.node import CustomNode  # noqa: E402


class FreshCloneRefTest(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(os.path.join(self.repos, "NodeA"))
        self.first = head(self.repo)
        git("tag", "v1", cwd=self.repo)
        git("branch", "dev", cwd=self.repo)
        self.tip = commit(self.repo, {"later.py": ""}, "second")

    def clone(self, ref: str) -> CustomNode:
        node = CustomNode(self.repo, ref, "")
        node.clone()
        return node

    def test_a_pinned_tag_is_checked_out(self):
        node = self.clone("v1")
        self.assertEqual(head(self.node_path("NodeA")), self.first)
        self.assertEqual(node.ref, "v1")

    def test_a_pinned_commit_is_checked_out(self):
        node = self.clone(self.first)
        self.assertEqual(head(self.node_path("NodeA")), self.first)
        self.assertEqual(node.ref, self.first)

    def test_another_branch_is_checked_out(self):
        self.clone("dev")
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.node_path("NodeA")), "dev")

    def test_the_default_branch_stays_checked_out(self):
        node = self.clone("main")
        self.assertEqual(head(self.node_path("NodeA")), self.tip)
        self.assertEqual(node.ref, "main")

    def test_a_ref_the_repo_lacks_falls_back_to_its_default_branch(self):
        master = make_repo(os.path.join(self.repos, "OldNode"), branch="master")
        node = CustomNode(master, "main", "")
        node.clone()
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.node_path("OldNode")), "master")
        self.assertEqual(node.ref, "master")

    def test_an_existing_clone_is_checked_out_in_place(self):
        self.clone("main")
        node = CustomNode(self.repo, "v1", "")
        node.clone()
        self.assertEqual(head(self.node_path("NodeA")), self.first)

    def test_an_unreachable_repo_raises(self):
        node = CustomNode(os.path.join(self.repos, "Nowhere"), "main", "")
        with self.assertRaises(subprocess.CalledProcessError):
            node.clone()
        self.assertFalse(os.path.exists(self.node_path("Nowhere")))


if __name__ == "__main__":
    unittest.main()

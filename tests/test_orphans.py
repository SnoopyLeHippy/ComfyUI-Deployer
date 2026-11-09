"""core.orphans.discover_untracked_nodes: orphans to track, linked nodes only shown.

A junction another program keeps in ``custom_nodes`` (MoodMiner links its
clone as ``ComfyUI-MoodMiner``) used to be an orphan: added to the list, then
removed by an install, it took that program out of ComfyUI. It is now listed
apart, as *linked*. So is a **link folder** — a real folder holding
``linked-node.json`` (``{"target": <absolute path>, "by": <program>}``), what
MoodMiner writes instead of a junction its own processes could not cross: it
has no ``.git``, and used to vanish without a word. Real git on local
repositories.
Run: python tests/test_orphans.py
"""

import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import unittest  # noqa: E402

from _support import SandboxTestCase, git, make_repo  # noqa: E402
from deployer.core.junctions import create_junction  # noqa: E402
from deployer.core.node import repo_identity  # noqa: E402
from deployer.core.orphans import discover_untracked_nodes  # noqa: E402

#: The contract's file name, spelled out: MoodMiner writes this very name.
LINK_FILE = "linked-node.json"


class LinkFolderTest(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.source = make_repo(os.path.join(self.repos, "NodeA"))
        git("clone", "-q", self.source, self.node_path("NodeA"), cwd=self.work)
        self.checkout = make_repo(os.path.join(self.work, "MoodMiner"))
        self.name = "ComfyUI-MoodMiner"

    def link_folder(self, name, content, *, encoding="utf-8"):
        """A real ``custom_nodes/<name>`` holding *content* as its link file, and no ``.git``."""
        folder = self.node_path(name)
        os.makedirs(folder)
        with open(os.path.join(folder, "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write("# runs the linked checkout\n")
        if not isinstance(content, str):
            content = json.dumps(content)
        with open(os.path.join(folder, LINK_FILE), "w", encoding=encoding) as fh:
            fh.write(content)
        return folder

    def test_a_link_folder_is_linked_not_an_orphan(self):
        self.link_folder(self.name, {"target": self.checkout, "by": "MoodMiner"})
        untracked = discover_untracked_nodes(set(), set())
        self.assertEqual(untracked.linked, [(self.name, os.path.normpath(self.checkout))])
        self.assertEqual([name for name, _repo, _ref in untracked.orphans], ["NodeA"])

    def test_a_missing_target_is_still_listed(self):
        gone = os.path.join(self.work, "uninstalled", "MoodMiner")
        self.link_folder(self.name, {"target": gone, "by": "MoodMiner"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            untracked = discover_untracked_nodes(set(), {"NodeA"})
        self.assertEqual(untracked.linked, [(self.name, os.path.normpath(gone))])
        self.assertIn(f"Linked: {self.name} -> {os.path.normpath(gone)} (missing)", out.getvalue())

    def test_a_tracked_name_is_ignored(self):
        self.link_folder(self.name, {"target": self.checkout, "by": "MoodMiner"})
        untracked = discover_untracked_nodes(set(), {"NodeA", self.name.lower()})
        self.assertEqual(untracked, ([], []))

    def test_a_byte_order_mark_is_read(self):
        self.link_folder(self.name, {"target": self.checkout, "by": "MoodMiner"}, encoding="utf-8-sig")
        untracked = discover_untracked_nodes(set(), {"NodeA"})
        self.assertEqual(untracked.linked, [(self.name, os.path.normpath(self.checkout))])

    def test_an_unreadable_link_file_makes_an_ordinary_folder(self):
        unreadable = {
            "not json": "{target: nowhere",
            "no target": {"by": "MoodMiner"},
            "a relative target": {"target": "MoodMiner", "by": "MoodMiner"},
            "a target that is no string": {"target": 42},
            "not an object": [self.checkout],
        }
        for label, content in unreadable.items():
            with self.subTest(label):
                _support.rmtree(self.node_path(self.name))
                self.link_folder(self.name, content)
                # No .git: skipped, as any other loose folder.
                self.assertEqual(discover_untracked_nodes(set(), {"NodeA"}), ([], []))

    def test_a_clone_with_an_unreadable_link_file_is_an_orphan(self):
        clone = self.node_path("NodeB")
        git("clone", "-q", make_repo(os.path.join(self.repos, "NodeB")), clone, cwd=self.work)
        with open(os.path.join(clone, LINK_FILE), "w", encoding="utf-8") as fh:
            fh.write("{broken")
        untracked = discover_untracked_nodes(set(), {"NodeA"})
        self.assertEqual([name for name, _repo, _ref in untracked.orphans], ["NodeB"])
        self.assertEqual(untracked.linked, [])


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

"""core.junctions: real junctions on disk, made and read without starting any process.

The window checks every ``custom_nodes`` folder as it opens: ``fsutil`` and
``cmd /c mklink`` used to start there (a console each, and a shell chain
endpoint security flags). Run: python tests/test_junctions.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import tempfile  # noqa: E402
import unittest  # noqa: E402

from _support import SANDBOX, ProcessSpy  # noqa: E402
from deployer.core.junctions import (  # noqa: E402
    create_junction,
    is_junction,
    read_junction_target,
    replace_with_junction,
)


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


if __name__ == "__main__":
    unittest.main()

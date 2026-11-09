"""core.package_repair.run_shadow_scan: a link folder is never a stray directory.

The shadow scan flags a ``custom_nodes`` folder named like an installed pip
module and holding no Python file, and "Repair packages" deletes it. A link
folder (``linked-node.json``, its code living at the target) needs no Python
file of its own: it belongs to another program and is never deleted from here.
Run: python tests/test_package_repair.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from _support import SandboxTestCase  # noqa: E402
from deployer.core import package_repair  # noqa: E402


class ShadowScanTest(SandboxTestCase):
    def setUp(self):
        super().setUp()
        # Stands in for the embedded interpreter's packages_distributions().
        installed = {"linkedmod": "linkedmod", "straymod": "straymod"}
        patch = mock.patch.object(package_repair, "_list_installed_top_levels", return_value=installed)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_link_folder_is_not_a_stray_directory(self):
        link = self.node_path("linkedmod")
        os.makedirs(link)
        with open(os.path.join(link, "linked-node.json"), "w", encoding="utf-8") as fh:
            json.dump({"target": os.path.join(self.work, "elsewhere"), "by": "SomeApp"}, fh)
        stray = self.node_path("straymod")
        os.makedirs(stray)

        broken = package_repair.run_shadow_scan(python_exe="python.exe")

        stray_dirs = [path for pkg in broken for path in pkg.stray_dirs]
        self.assertEqual(stray_dirs, [stray])


if __name__ == "__main__":
    unittest.main()

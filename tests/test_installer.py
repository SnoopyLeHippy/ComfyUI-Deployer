"""installer.install_configured_nodes — what ``cli.py install-nodes`` does.

Real git on local repositories; the portable's python is faked by ProcessSpy,
which also checks that nothing but git and python starts, and never through a
shell. Run: python tests/test_installer.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import json  # noqa: E402
import unittest  # noqa: E402

from _support import ProcessSpy, SandboxTestCase, git, head, make_repo  # noqa: E402
from deployer import config  # noqa: E402
from deployer.core.installer import install_configured_nodes, load_custom_nodes  # noqa: E402


class InstallConfiguredNodesTest(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.progress: list[tuple[str, float]] = []
        self.warnings: list[str] = []

    # -- helpers ------------------------------------------------------------

    def repo(self, name: str, files: dict[str, str] | None = None, **kwargs) -> str:
        return make_repo(os.path.join(self.repos, name), files, **kwargs)

    def write_manifest(self, entries: list[dict]) -> None:
        with open(self.manifest_path, "w", encoding="utf-8") as fh:
            json.dump(entries, fh)

    def write_settings(self, nodes: list[dict], **other) -> None:
        with open(self.settings_path, "w", encoding="utf-8") as fh:
            json.dump({"nodes": nodes, **other}, fh)

    def read_settings(self) -> dict:
        with open(self.settings_path, encoding="utf-8") as fh:
            return json.load(fh)

    def run_install(self, exit_code=lambda argv: 0):
        with ProcessSpy([config.PYTHON_EXE], exit_code) as spy:
            report = install_configured_nodes(
                progress=lambda message, fraction: self.progress.append((message, fraction)),
                warn=self.warnings.append,
            )
        spy.assert_no_shell(self)
        return report, spy

    @staticmethod
    def requirement_args(spy: ProcessSpy) -> list[list[str]]:
        """The ``-r`` files of each requirements install the spy saw."""
        installs = [argv for argv in spy.faked() if "install" in argv and "-r" in argv]
        return [[argv[i + 1] for i, part in enumerate(argv) if part == "-r"] for argv in installs]

    # -- the list -----------------------------------------------------------

    def test_a_fresh_clone_seeds_the_list_from_custom_nodes_json_and_installs_it(self):
        a, b = self.repo("NodeA"), self.repo("NodeB")
        self.write_manifest([
            {"repo": a, "ref": "main", "description": "A"},
            {"repo": b, "ref": "main", "description": "B"},
        ])
        report, _ = self.run_install()
        self.assertEqual(report.installed, ["NodeA", "NodeB"])
        self.assertEqual((report.present, report.failed), ([], []))
        self.assertTrue(os.path.isdir(os.path.join(self.node_path("NodeA"), ".git")))
        self.assertTrue(os.path.isdir(os.path.join(self.node_path("NodeB"), ".git")))
        self.assertEqual([n["repo"] for n in self.read_settings()["nodes"]], [a, b])

    def test_user_settings_wins_over_custom_nodes_json(self):
        a, b = self.repo("NodeA"), self.repo("NodeB")
        self.write_manifest([{"repo": a, "ref": "main", "description": ""}])
        self.write_settings([{"repo": b, "ref": "main", "description": ""}], settings={"model_folder": "M:/models"})
        report, _ = self.run_install()
        self.assertEqual(report.installed, ["NodeB"])
        self.assertFalse(os.path.exists(self.node_path("NodeA")))
        self.assertEqual(self.read_settings()["settings"], {"model_folder": "M:/models"})

    def test_entries_without_ref_or_description_install_and_those_without_repo_are_skipped(self):
        a = self.repo("NodeA")
        self.write_manifest([{"repo": a}, {"ref": "main"}, {"repo": "  "}, "not an entry"])
        report, _ = self.run_install()
        self.assertEqual(report.installed, ["NodeA"])
        self.assertEqual([node.ref for node in load_custom_nodes()], ["main"])

    def test_an_empty_list_installs_nothing_and_still_ends(self):
        report, spy = self.run_install()
        self.assertEqual(report.as_dict(), {"installed": [], "present": [], "failed": [], "requirements_failed": []})
        self.assertEqual(spy.calls, [])
        self.assertEqual(self.progress[-1][1], 1.0)

    # -- nodes on disk ------------------------------------------------------

    def test_a_node_already_on_disk_is_left_as_it_is(self):
        a = self.repo("NodeA")
        git("clone", "-q", a, self.node_path("NodeA"), cwd=self.work)
        git("checkout", "-q", "-b", "local-work", cwd=self.node_path("NodeA"))
        self.write_manifest([{"repo": a, "ref": "main", "description": ""}])
        report, spy = self.run_install()
        self.assertEqual((report.present, report.installed), (["NodeA"], []))
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.node_path("NodeA")), "local-work")
        self.assertEqual([c for c in spy.calls if c["argv"][0] == "git"], [])

    def test_a_pinned_ref_is_honoured_on_a_fresh_clone(self):
        a = self.repo("NodeA")
        pinned = head(a)
        git("tag", "v1", cwd=a)
        _support.commit(a, {"later.py": ""})
        self.write_manifest([{"repo": a, "ref": "v1", "description": ""}])
        self.run_install()
        self.assertEqual(head(self.node_path("NodeA")), pinned)

    def test_two_entries_sharing_a_folder_name_clone_once(self):
        a = self.repo("NodeA")
        fork = make_repo(os.path.join(self.repos, "fork", "NodeA"))
        self.write_manifest([{"repo": a, "ref": "main"}, {"repo": fork, "ref": "main"}])
        report, _ = self.run_install()
        self.assertEqual((report.installed, report.present, report.failed), (["NodeA"], ["NodeA"], []))

    # -- failures -----------------------------------------------------------

    def test_a_node_that_fails_to_clone_is_reported_and_the_others_still_install(self):
        a = self.repo("NodeA")
        missing = os.path.join(self.repos, "Gone")
        self.write_manifest([{"repo": missing, "ref": "main"}, {"repo": a, "ref": "main"}])
        report, _ = self.run_install()
        self.assertEqual(report.installed, ["NodeA"])
        self.assertEqual([(f["name"], f["repo"]) for f in report.failed], [("Gone", missing)])
        self.assertTrue(report.failed[0]["error"])
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("Gone", self.warnings[0])
        self.assertFalse(os.path.exists(self.node_path("Gone")))

    # -- requirements -------------------------------------------------------

    def test_requirements_of_every_listed_node_on_disk_go_in_one_pass(self):
        a = self.repo("NodeA", {"requirements.txt": "six\n"})
        b = self.repo("NodeB", {"__init__.py": "", "sub/requirements.txt": "idna\n"})
        c = self.repo("NodeC")
        git("clone", "-q", b, self.node_path("NodeB"), cwd=self.work)  # present: its requirements still run
        os.makedirs(os.path.join(self.node_path("Unlisted")))
        with open(os.path.join(self.node_path("Unlisted"), "requirements.txt"), "w") as fh:
            fh.write("never\n")
        self.write_manifest([{"repo": r, "ref": "main"} for r in (a, b, c)])

        report, spy = self.run_install()

        self.assertEqual((report.installed, report.present), (["NodeA", "NodeC"], ["NodeB"]))
        passes = self.requirement_args(spy)
        self.assertEqual(len(passes), 1)
        self.assertEqual(
            sorted(os.path.normcase(p) for p in passes[0]),
            sorted(os.path.normcase(p) for p in (
                os.path.join(self.node_path("NodeA"), "requirements.txt"),
                os.path.join(self.node_path("NodeB"), "sub", "requirements.txt"),
            )),
        )
        install = next(argv for argv in spy.faked() if "-r" in argv)
        self.assertEqual(install[1:5], ["-m", "uv", "pip", "install"])
        self.assertEqual(report.requirements_failed, [])
        self.assertEqual(self.warnings, [])

    def test_uv_is_bootstrapped_when_the_portable_lacks_it(self):
        a = self.repo("NodeA", {"requirements.txt": "six\n"})
        self.write_manifest([{"repo": a, "ref": "main"}])
        installed = []

        def exit_code(argv):
            if argv[1:] == ["-m", "pip", "install", "uv"]:
                installed.append("uv")
                return 0
            if argv[1:] == ["-c", "import uv"]:
                return 0 if installed else 1
            return 0

        _, spy = self.run_install(exit_code)
        pip_uv = [argv[1:] for argv in spy.faked()].index(["-m", "pip", "install", "uv"])
        first_requirements = next(i for i, argv in enumerate(spy.faked()) if "-r" in argv)
        self.assertLess(pip_uv, first_requirements)
        self.assertEqual(spy.faked()[first_requirements][1:5], ["-m", "uv", "pip", "install"])

    def test_failed_requirements_are_reported_as_warnings(self):
        a = self.repo("NodeA", {"requirements.txt": "six\n"})
        b = self.repo("NodeB", {"requirements.txt": "broken\n"})
        self.write_manifest([{"repo": a, "ref": "main"}, {"repo": b, "ref": "main"}])
        broken = os.path.join(self.node_path("NodeB"), "requirements.txt")

        def exit_code(argv):
            # The grouped pass fails (it holds NodeB's file), then only NodeB's retry.
            return 1 if broken in argv else 0

        report, _ = self.run_install(exit_code)
        self.assertEqual(report.installed, ["NodeA", "NodeB"])
        self.assertEqual(report.requirements_failed, [broken])
        self.assertEqual(len(self.warnings), 1)
        self.assertIn(broken, self.warnings[0])

    def test_nodes_without_requirements_start_no_python(self):
        a = self.repo("NodeA")
        self.write_manifest([{"repo": a, "ref": "main"}])
        _, spy = self.run_install()
        self.assertEqual(spy.faked(), [])

    # -- progress and processes --------------------------------------------

    def test_progress_rises_and_ends_at_one(self):
        repos = [self.repo(f"Node{i}", {"requirements.txt": "six\n"}) for i in range(3)]
        self.write_manifest([{"repo": r, "ref": "main"} for r in repos])
        self.run_install()
        fractions = [fraction for _, fraction in self.progress]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)
        self.assertTrue(all(0.0 <= f <= 1.0 for f in fractions))
        self.assertIn("Node1 (2/3)", self.progress[1][0])

    def test_only_git_and_the_portables_python_start_with_direct_argv(self):
        a = self.repo("NodeA", {"requirements.txt": "six\n"})
        b = self.repo("NodeB")
        git("branch", "dev", cwd=b)
        gone = os.path.join(self.repos, "NodeC")
        self.write_manifest([{"repo": a, "ref": "main"}, {"repo": b, "ref": "dev"}, {"repo": gone}])
        _, spy = self.run_install()  # assert_no_shell runs inside
        programs = {os.path.normcase(call["argv"][0]) for call in spy.calls}
        self.assertEqual(programs, {"git", os.path.normcase(config.PYTHON_EXE)})


if __name__ == "__main__":
    unittest.main()

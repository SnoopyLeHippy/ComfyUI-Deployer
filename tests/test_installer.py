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
from deployer.core.installer import (  # noqa: E402
    add_listed_nodes,
    install_configured_nodes,
    install_selected_nodes,
    load_custom_nodes,
    read_node_list,
)


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

    def run_install(self, exit_code=lambda argv: 0, listed=None):
        with ProcessSpy([config.PYTHON_EXE], exit_code) as spy:
            report = install_configured_nodes(
                progress=lambda message, fraction: self.progress.append((message, fraction)),
                warn=self.warnings.append,
                listed=listed,
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
        self.assertEqual(report.as_dict(), {
            "added": [], "installed": [], "updated": [], "present": [], "failed": [],
            "requirements_failed": [],
        })
        self.assertEqual(spy.calls, [])
        self.assertEqual(self.progress[-1][1], 1.0)

    # -- an installer's own list (--nodes-file) ------------------------------

    def test_a_listed_set_is_the_list_of_a_fresh_clone_instead_of_custom_nodes_json(self):
        a, b, c = self.repo("NodeA"), self.repo("NodeB"), self.repo("NodeC")
        self.write_manifest([{"repo": a, "ref": "main", "description": "default"}])
        report, _ = self.run_install(listed=[{"repo": b, "description": "B"}, {"repo": c, "ref": "main"}])
        self.assertEqual((report.added, report.installed), (["NodeB", "NodeC"], ["NodeB", "NodeC"]))
        self.assertFalse(os.path.exists(self.node_path("NodeA")))
        self.assertEqual(self.read_settings()["nodes"], [{"repo": b, "description": "B"}, {"repo": c, "ref": "main"}])

    def test_a_listed_set_is_added_to_an_existing_list_whose_nodes_keep_their_ref(self):
        a, b = self.repo("NodeA"), self.repo("NodeB")
        git("branch", "dev", cwd=a)
        self.write_settings([{"repo": a, "ref": "dev", "description": "mine"}], settings={"model_folder": "M:/models"})
        report, _ = self.run_install(listed=[{"repo": a, "ref": "main", "description": "theirs"}, {"repo": b}])
        self.assertEqual((report.added, report.installed), (["NodeB"], ["NodeA", "NodeB"]))
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.node_path("NodeA")), "dev")
        settings = self.read_settings()
        self.assertEqual(settings["nodes"], [{"repo": a, "ref": "dev", "description": "mine"}, {"repo": b}])
        self.assertEqual(settings["settings"], {"model_folder": "M:/models"})

    def test_a_list_file_holding_no_node_counts_as_a_fresh_clone(self):
        b = self.repo("NodeB")
        self.write_settings([], settings={"output_folder": "O:/out"})
        report, _ = self.run_install(listed=[{"repo": b}])
        self.assertEqual(report.installed, ["NodeB"])
        self.assertEqual(self.read_settings(), {"nodes": [{"repo": b}], "settings": {"output_folder": "O:/out"}})

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


class InstallSelectedNodesTest(SandboxTestCase):
    """install_selected_nodes — ``install-nodes --repo / --update / --repair``: only those packs."""

    def setUp(self):
        super().setUp()
        self.warnings: list[str] = []

    def repo(self, name: str, files: dict[str, str] | None = None) -> str:
        return make_repo(os.path.join(self.repos, name), files)

    def run_selected(self, install=(), update=(), repair=(), exit_code=lambda argv: 0):
        with ProcessSpy([config.PYTHON_EXE], exit_code) as spy:
            report = install_selected_nodes(list(install), list(update), list(repair),
                                            warn=self.warnings.append)
        spy.assert_no_shell(self)
        return report, spy

    def tracked(self) -> list[str]:
        with open(self.settings_path, encoding="utf-8") as fh:
            return [n["repo"] for n in json.load(fh)["nodes"]]

    def test_install_clones_only_the_given_packs_and_tracks_them(self):
        a, b = self.repo("NodeA", {"requirements.txt": "six\n"}), self.repo("NodeB")
        with open(self.settings_path, "w", encoding="utf-8") as fh:
            json.dump({"nodes": [{"repo": b, "ref": "main"}]}, fh)  # tracked, not asked for
        report, spy = self.run_selected(install=[a])
        self.assertEqual((report.added, report.installed, report.failed), (["NodeA"], ["NodeA"], []))
        self.assertEqual(os.listdir(self.custom_nodes), ["NodeA"])
        self.assertEqual(self.tracked(), [b, a])
        self.assertEqual(InstallConfiguredNodesTest.requirement_args(spy),
                         [[os.path.join(self.node_path("NodeA"), "requirements.txt")]])

    def test_install_leaves_a_pack_already_there_alone(self):
        a = self.repo("NodeA")
        git("clone", "-q", a, self.node_path("NodeA"), cwd=self.work)
        git("checkout", "-q", "-b", "mine", cwd=self.node_path("NodeA"))
        report, _ = self.run_selected(install=[a])
        self.assertEqual((report.present, report.installed), (["NodeA"], []))
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.node_path("NodeA")), "mine")

    def test_update_fast_forwards_the_clone_found_by_its_origin(self):
        a = self.repo("NodeA")
        git("clone", "-q", a, self.node_path("Renamed"), cwd=self.work)  # another folder name
        later = _support.commit(a, {"new_node.py": ""})
        report, _ = self.run_selected(update=[a])
        self.assertEqual((report.updated, report.failed), (["Renamed"], []))
        self.assertEqual(head(self.node_path("Renamed")), later)

    def test_update_refuses_local_changes_a_pinned_commit_and_an_absent_pack(self):
        a, b, c = self.repo("NodeA"), self.repo("NodeB"), self.repo("NodeC")
        for repo, name in ((a, "NodeA"), (b, "NodeB")):
            git("clone", "-q", repo, self.node_path(name), cwd=self.work)
        with open(os.path.join(self.node_path("NodeA"), "__init__.py"), "w") as fh:
            fh.write("# edited\n")
        git("checkout", "-q", "--detach", cwd=self.node_path("NodeB"))
        _support.commit(a, {"x.py": ""})
        before = head(self.node_path("NodeA"))
        report, _ = self.run_selected(update=[a, b, c])
        self.assertEqual(report.updated, [])
        errors = {f["name"]: f["error"] for f in report.failed}
        self.assertIn("local changes", errors["NodeA"])
        self.assertIn("pinned", errors["NodeB"])
        self.assertIn("not installed", errors["NodeC"])
        self.assertEqual(head(self.node_path("NodeA")), before)
        self.assertEqual(len(self.warnings), 3)

    def test_repair_reinstalls_the_requirements_and_touches_no_git(self):
        a = self.repo("NodeA", {"requirements.txt": "six\n"})
        git("clone", "-q", a, self.node_path("NodeA"), cwd=self.work)
        report, spy = self.run_selected(repair=[a])
        self.assertEqual(report.failed, [])
        self.assertEqual(InstallConfiguredNodesTest.requirement_args(spy),
                         [[os.path.join(self.node_path("NodeA"), "requirements.txt")]])
        self.assertFalse([c for c in spy.calls if c["argv"][0] == "git" and "pull" in c["argv"]])

    def test_a_folder_holding_a_namesake_is_never_cloned_over_nor_updated(self):
        # Local paths all share one identity (their basename): the origins are URLs here.
        fork = make_repo(os.path.join(self.repos, "fork", "NodeA"))
        git("clone", "-q", fork, self.node_path("NodeA"), cwd=self.work)
        git("remote", "set-url", "origin", "https://github.com/fork/NodeA", cwd=self.node_path("NodeA"))
        wanted = "https://github.com/owner/NodeA"
        report, spy = self.run_selected(install=[wanted], update=[wanted])
        self.assertEqual([f["name"] for f in report.failed], ["NodeA", "NodeA"])
        self.assertIn("another repository", report.failed[0]["error"])
        self.assertFalse([c for c in spy.calls if c["argv"][:2] in (["git", "clone"], ["git", "pull"])])
        self.assertEqual(git("remote", "get-url", "origin", cwd=self.node_path("NodeA")),
                         "https://github.com/fork/NodeA")


class AddListedNodesTest(SandboxTestCase):
    """add_listed_nodes and read_node_list alone: the list, no clone."""

    def nodes(self) -> list[dict]:
        with open(self.settings_path, encoding="utf-8") as fh:
            return json.load(fh)["nodes"]

    def write_settings(self, nodes: list[dict]) -> None:
        with open(self.settings_path, "w", encoding="utf-8") as fh:
            json.dump({"nodes": nodes}, fh)

    def test_a_tracked_repository_is_never_added_again_whatever_its_spelling(self):
        self.write_settings([
            {"repo": "https://github.com/owner/NodeA", "ref": "v1"},
            {"repo": "https://github.com/owner/ComfyUI-Renamed", "ref": "main"},
        ])
        added = add_listed_nodes([
            {"repo": "git@github.com:Owner/NodeA.git", "ref": "main"},  # same repository
            {"repo": "https://github.com/fork/comfyui-renamed/"},  # same folder name
            {"repo": "  https://github.com/owner/NodeB.git  ", "ref": "main", "extra": True},
            {"repo": "https://github.com/OWNER/nodeb"},  # twice in the list itself
            {"description": "no repo"},
            "not an entry",
        ])
        self.assertEqual(added, [{"repo": "https://github.com/owner/NodeB.git", "ref": "main"}])
        self.assertEqual([n["repo"] for n in self.nodes()], [
            "https://github.com/owner/NodeA",
            "https://github.com/owner/ComfyUI-Renamed",
            "https://github.com/owner/NodeB.git",
        ])
        self.assertEqual(self.nodes()[0]["ref"], "v1")

    def test_nothing_new_writes_nothing(self):
        self.write_settings([{"repo": "https://github.com/owner/NodeA"}])
        before = os.path.getmtime(self.settings_path)
        os.utime(self.settings_path, (before - 10, before - 10))
        stamp = os.path.getmtime(self.settings_path)
        self.assertEqual(add_listed_nodes([{"repo": "https://github.com/owner/NodeA.git"}]), [])
        self.assertEqual(os.path.getmtime(self.settings_path), stamp)

    def test_without_user_settings_the_entries_are_the_list(self):
        self.assertFalse(os.path.exists(self.settings_path))
        add_listed_nodes([{"repo": "https://github.com/owner/NodeA", "description": "A"}])
        self.assertEqual(self.nodes(), [{"repo": "https://github.com/owner/NodeA", "description": "A"}])

    def test_reading_a_node_list_file(self):
        path = os.path.join(self.work, "list.json")
        for content, expected in (
                ('[{"repo": "r1"}, {"ref": "main"}]', [{"repo": "r1"}]),
                ('﻿{"nodes": [{"repo": "r2", "ref": "v2"}]}', [{"repo": "r2", "ref": "v2"}]),
                ('{"settings": {}}', []),
        ):
            with self.subTest(content=content):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
                self.assertEqual(read_node_list(path), expected)
        for content in ("{ not json", '"a string"', '{"nodes": 3}'):
            with self.subTest(content=content):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
                with self.assertRaises(ValueError):
                    read_node_list(path)
        with self.assertRaises(OSError):
            read_node_list(os.path.join(self.work, "missing.json"))


if __name__ == "__main__":
    unittest.main()

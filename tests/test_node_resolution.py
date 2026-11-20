"""Custom node resolution: the workflow's types, the DB, the classification, the cache.

Pure parts (node_resolution, NodeDb) on hand-made inputs; the cache and the
registry against a temp folder and an injected fetch — no network. Run:
python tests/test_node_resolution.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402  (first: sandbox + import path)

import json  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
import urllib.error  # noqa: E402
from unittest import mock  # noqa: E402

from deployer.core import node_db, workflow_resolver  # noqa: E402
from deployer.core.node import repo_identity  # noqa: E402
from deployer.core.node_db import NodeDb, NodeDbUnavailable, cached_json, registry_repository  # noqa: E402
from deployer.core.node_resolution import (  # noqa: E402
    Folder,
    loaded_from_object_info,
    loaded_from_scan,
    resolve,
    wanted_from_list,
    wanted_from_workflow,
)

KJ = "https://github.com/kijai/ComfyUI-KJNodes"
RG = "https://github.com/rgthree/rgthree-comfy"
IPA = "https://github.com/cubiq/ComfyUI_IPAdapter_plus"
FORK = "https://github.com/someone/ComfyUI_IPAdapter_plus"
GIST = "https://gist.githubusercontent.com/x/abc/raw/nodes.py"


def manager_db() -> NodeDb:
    """A small Manager DB shaped like the real files."""
    extension_map = {
        "https://github.com/comfyanonymous/ComfyUI": [["KSampler", "NewCoreNode"], {}],
        KJ: [["INTConstant", "KJFuture"], {"title_aux": "KJNodes"}],
        RG: [["Power Lora Loader (rgthree)"], {"nodename_pattern": " \\(rgthree\\)$"}],
        IPA: [["IPAdapterAdvanced", "SharedType"], {}],
        FORK: [["SharedType"], {}],
        GIST: [["GistNode"], {}],
        "https://github.com/typo/Reference-Name": [["AliasedType"], {}],
    }
    node_list = {"custom_nodes": [
        {"id": "kjnodes", "reference": KJ, "files": [KJ], "install_type": "git-clone",
         "title": "KJNodes", "description": "QoL"},
        {"id": "rgthree", "reference": RG, "files": [RG], "install_type": "git-clone", "title": "rgthree"},
        {"reference": IPA, "files": [IPA], "install_type": "git-clone", "title": "IPAdapter plus"},
        {"reference": FORK, "files": [FORK], "install_type": "git-clone", "title": "fork"},
        {"reference": "https://github.com/x/abc", "files": [GIST], "install_type": "copy"},
        {"reference": "https://github.com/typo/Reference-Name",
         "files": ["https://github.com/real/Real-Name"], "install_type": "git-clone"},
    ]}
    return NodeDb(extension_map, node_list)


def object_info(**modules) -> dict:
    """``{type: {"python_module": module}}``; ``nodes`` for the core types given as True."""
    return {t: {"python_module": m if isinstance(m, str) else "nodes"} for t, m in modules.items()}


class WantedTest(unittest.TestCase):
    def test_a_graph_gives_its_types_with_what_their_nodes_say_about_their_pack(self):
        graph = {
            "nodes": [
                {"type": "KSampler", "properties": {"cnr_id": "comfy-core", "ver": "0.3"}},
                {"type": "INTConstant", "properties": {"cnr_id": "comfyui-kjnodes", "ver": "abc"}},
                {"type": "INTConstant", "properties": {"ver": "def"}},
                {"type": "Thing", "properties": {"aux_id": "owner/Repo"}},
                {"type": "Muted", "mode": 2},
                {"type": "Bypassed", "mode": 4},
                {"type": "Note"}, {"type": "Reroute"}, {"type": "PrimitiveNode"},
                {"type": "workflow>Group"},
                {"type": "1b2c-uuid"},
            ],
            "definitions": {"subgraphs": [{"id": "1b2c-uuid", "nodes": [{"type": "Inner"}]}]},
            "extra": {"groupNodes": {"Group": {"nodes": [{"type": "InGroup"}]}}},
        }
        wanted = wanted_from_workflow(graph)
        self.assertEqual(sorted(wanted), ["INTConstant", "InGroup", "Inner", "KSampler", "Thing"])
        self.assertEqual((wanted["INTConstant"].cnr_id, wanted["INTConstant"].versions),
                         ("comfyui-kjnodes", ["abc", "def"]))
        self.assertEqual(wanted["Thing"].aux_id, "owner/Repo")
        everything = wanted_from_workflow(graph, executable_only=False)
        self.assertIn("Muted", everything)
        self.assertIn("Bypassed", everything)

    def test_an_api_prompt_gives_its_class_types(self):
        prompt = {"3": {"class_type": "KSampler", "inputs": {}}, "4": {"class_type": "Note"}, "x": 3}
        self.assertEqual(sorted(wanted_from_workflow(prompt)), ["KSampler"])

    def test_a_list_takes_names_or_entries_in_either_case(self):
        wanted = wanted_from_list(["A", {"type": "B", "cnrId": "pack", "auxId": "o/r", "ver": "1"},
                                   {"type": " "}, {"cnr_id": "x"}, 3, "Note"])
        self.assertEqual(sorted(wanted), ["A", "B"])
        self.assertEqual((wanted["B"].cnr_id, wanted["B"].aux_id, wanted["B"].versions), ("pack", "o/r", ["1"]))
        self.assertEqual(wanted_from_list("not a list"), {})


class LoadedTest(unittest.TestCase):
    def test_object_info_names_each_loaded_folder(self):
        loaded = loaded_from_object_info({
            "KSampler": {"python_module": "nodes"},
            "Api": {"python_module": "comfy_api_nodes.nodes_x"},
            "INTConstant": {"python_module": "custom_nodes.ComfyUI-KJNodes"},
            "Dotted": {"python_module": "custom_nodes.pack.with.dots"},
            "Bare": {},
        })
        self.assertEqual(loaded.types, {"KSampler", "Api", "INTConstant", "Dotted", "Bare"})
        self.assertEqual(loaded.folders, {"comfyui-kjnodes", "pack.with.dots"})
        self.assertEqual(loaded.source, "object_info")


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.db = manager_db()

    def run_resolve(self, wanted, loaded, folders=(), tracked=(), registry=None, db=True):
        if isinstance(wanted, list):
            wanted = wanted_from_list(wanted)
        return resolve(wanted, loaded, self.db if db else None, list(folders),
                       {repo_identity(r) for r in tracked}, registry)

    def packs(self, result):
        return {p["folder"]: (p["action"], p["types"], p["source"]) for p in result.packs}

    def test_a_loaded_type_needs_nothing(self):
        result = self.run_resolve(["KSampler", "INTConstant"], loaded_from_object_info(
            object_info(KSampler=True, INTConstant="custom_nodes.ComfyUI-KJNodes")))
        self.assertTrue(result.is_empty())

    def test_an_absent_pack_is_installed(self):
        result = self.run_resolve(["IPAdapterAdvanced"], loaded_from_object_info({}))
        self.assertEqual(self.packs(result), {"ComfyUI_IPAdapter_plus": ("install", ["IPAdapterAdvanced"], "db")})
        self.assertEqual(result.packs[0]["repo"], IPA)
        self.assertEqual(result.packs[0]["title"], "IPAdapter plus")

    def test_a_loaded_pack_lacking_the_type_is_updated(self):
        # The old resolver skipped it: a known repository declared the type, so "nothing to do".
        loaded = loaded_from_object_info(object_info(INTConstant="custom_nodes.ComfyUI-KJNodes"))
        result = self.run_resolve(["KJFuture"], loaded, [Folder("ComfyUI-KJNodes", KJ + ".git")], tracked=[KJ])
        self.assertEqual(self.packs(result), {"ComfyUI-KJNodes": ("update", ["KJFuture"], "db")})
        self.assertTrue(result.packs[0]["tracked"])

    def test_a_pack_on_disk_that_loaded_nothing_is_repaired(self):
        # Its sources declare the type, so the old resolver called it installed: the
        # commonest real failure (a missing pip dependency) went unreported.
        result = self.run_resolve(["IPAdapterAdvanced"], loaded_from_object_info(object_info(KSampler=True)),
                                  [Folder("ComfyUI_IPAdapter_plus", IPA, {"IPAdapterAdvanced"})])
        self.assertEqual(self.packs(result), {"ComfyUI_IPAdapter_plus": ("repair", ["IPAdapterAdvanced"], "db")})

    def test_without_object_info_the_folders_sources_decide(self):
        folders = [Folder("ComfyUI-KJNodes", KJ, {"INTConstant", "KJFuture"})]
        result = self.run_resolve(["KJFuture"], loaded_from_scan({"KSampler"}), folders)
        self.assertEqual(self.packs(result)["ComfyUI-KJNodes"][0], "repair")
        folders = [Folder("ComfyUI-KJNodes", KJ, {"INTConstant"})]
        result = self.run_resolve(["KJFuture"], loaded_from_scan({"KSampler", "INTConstant"}), folders)
        self.assertEqual(self.packs(result)["ComfyUI-KJNodes"][0], "update")
        self.assertEqual(result.ground_truth, "static")

    def test_the_workflows_aux_id_names_the_pack_first(self):
        wanted = wanted_from_list([{"type": "SharedType", "aux_id": "someone/ComfyUI_IPAdapter_plus"},
                                   {"type": "NotInAnyDb", "aux_id": "studio/Private-Pack"}])
        result = self.run_resolve(wanted, loaded_from_object_info({}))
        self.assertEqual({p["repo"]: (p["types"], p["source"]) for p in result.packs}, {
            FORK: (["SharedType"], "workflow"),
            "https://github.com/studio/Private-Pack": (["NotInAnyDb"], "workflow"),
        })

    def test_the_cnr_id_picks_among_candidates_by_manager_id_or_folder_name(self):
        wanted = wanted_from_list([{"type": "INTConstant", "cnr_id": "comfyui-kjnodes"},
                                   {"type": "Power Lora Loader (rgthree)", "cnr_id": "rgthree"}])
        result = self.run_resolve(wanted, loaded_from_object_info({}))
        self.assertEqual({p["folder"]: p["source"] for p in result.packs},
                         {"ComfyUI-KJNodes": "workflow", "rgthree-comfy": "workflow"})

    def test_an_unknown_cnr_id_asks_the_registry(self):
        asked = []

        def registry(cnr_id):
            asked.append(cnr_id)
            return "https://github.com/studio/Registry-Pack" if cnr_id == "registry-pack" else None

        wanted = wanted_from_list([{"type": "RegType", "cnr_id": "registry-pack"},
                                   {"type": "Lost", "cnr_id": "nobody-knows"}])
        result = self.run_resolve(wanted, loaded_from_object_info({}), registry=registry)
        self.assertEqual(self.packs(result), {"Registry-Pack": ("install", ["RegType"], "registry")})
        self.assertEqual(result.unknown, ["Lost"])
        self.assertEqual(sorted(asked), ["nobody-knows", "registry-pack"])

    def test_two_candidates_are_ambiguous_unless_one_is_tracked_or_on_disk(self):
        loaded = loaded_from_object_info({})
        result = self.run_resolve(["SharedType"], loaded)
        self.assertEqual(result.packs, [])
        self.assertEqual(result.ambiguous[0]["types"], ["SharedType"])
        self.assertEqual(sorted(o["repo"] for o in result.ambiguous[0]["options"]), sorted([IPA, FORK]))
        result = self.run_resolve(["SharedType"], loaded, tracked=[FORK])
        self.assertEqual([p["repo"] for p in result.packs], [FORK])

    def test_types_sharing_their_candidates_are_one_ambiguous_entry(self):
        db = NodeDb({IPA: [["T1", "T2"], {}], FORK: [["T1", "T2"], {}]}, {})
        result = resolve(wanted_from_list(["T1", "T2"]), loaded_from_object_info({}), db, [], set())
        self.assertEqual([(a["types"], len(a["options"])) for a in result.ambiguous], [(["T1", "T2"], 2)])

    def test_a_core_type_is_comfyuis_own(self):
        wanted = wanted_from_list(["NewCoreNode", {"type": "Unlisted", "cnr_id": "comfy-core"}])
        result = self.run_resolve(wanted, loaded_from_object_info({}))
        self.assertEqual((result.core, result.packs), (["NewCoreNode", "Unlisted"], []))

    def test_a_folder_holding_a_namesake_is_blocked(self):
        # The old resolver matched repositories by folder name: a fork passed for the pack.
        folders = [Folder("ComfyUI_IPAdapter_plus", FORK)]
        result = self.run_resolve(["IPAdapterAdvanced"], loaded_from_object_info({}), folders)
        self.assertEqual(result.packs, [])
        self.assertEqual(result.blocked[0]["folder"], "ComfyUI_IPAdapter_plus")
        self.assertEqual(result.blocked[0]["origin"], FORK)

    def test_a_db_entry_that_is_no_git_repository_is_blocked(self):
        result = self.run_resolve(["GistNode"], loaded_from_object_info({}))
        self.assertEqual((result.packs, result.blocked[0]["reason"]), ([], "not a git repository"))

    def test_a_reference_that_differs_from_files_clones_files(self):
        result = self.run_resolve(["AliasedType"], loaded_from_object_info({}))
        self.assertEqual(result.packs[0]["repo"], "https://github.com/real/Real-Name")

    def test_frontend_types_of_a_loaded_pack_are_satisfied(self):
        loaded = loaded_from_object_info(object_info(INTConstant="custom_nodes.ComfyUI-KJNodes",
                                                     X="custom_nodes.rgthree-comfy"))
        folders = [Folder("ComfyUI-KJNodes", KJ), Folder("rgthree-comfy", RG)]
        result = self.run_resolve(["SetNode", "Fast Groups Muter (rgthree)"], loaded, folders)
        self.assertTrue(result.is_empty())
        self.assertEqual(sorted(result.frontend), ["Fast Groups Muter (rgthree)", "SetNode"])
        # Absent, their pack is installed.
        result = self.run_resolve(["SetNode"], loaded_from_object_info({}))
        self.assertEqual(self.packs(result), {"ComfyUI-KJNodes": ("install", ["SetNode"], "builtin")})

    def test_nothing_known_is_unknown_and_no_db_still_takes_aux_ids(self):
        wanted = wanted_from_list(["Nowhere", {"type": "Aux", "aux_id": "o/r"}])
        result = self.run_resolve(wanted, loaded_from_object_info({}), db=False)
        self.assertEqual(result.unknown, ["Nowhere"])
        self.assertEqual([p["repo"] for p in result.packs], ["https://github.com/o/r"])

    def test_one_pack_gathers_its_types_and_versions(self):
        wanted = wanted_from_list([{"type": "INTConstant", "cnr_id": "comfyui-kjnodes", "ver": "a"},
                                   {"type": "KJFuture", "ver": "b"}])
        result = self.run_resolve(wanted, loaded_from_object_info({}))
        self.assertEqual(len(result.packs), 1)
        self.assertEqual((result.packs[0]["types"], result.packs[0]["versions"]),
                         (["INTConstant", "KJFuture"], ["a", "b"]))
        self.assertEqual(json.loads(json.dumps(result.as_dict()))["packs"][0]["action"], "install")


class NodeDbTest(unittest.TestCase):
    def test_indexes(self):
        db = manager_db()
        self.assertEqual(db.core_types, {"KSampler", "NewCoreNode"})
        self.assertNotIn("KSampler", db.type_repos)
        self.assertEqual(db.candidates("Fast Groups Muter (rgthree)"), [repo_identity(RG)])
        self.assertTrue(db.declares(repo_identity(KJ), "INTConstant"))
        self.assertFalse(db.declares(repo_identity(RG), "Fast Groups Muter (rgthree)"))
        self.assertEqual(db.by_registry_id("KJNodes"), [repo_identity(KJ)])  # the Manager id
        self.assertEqual(db.by_registry_id("comfyui_ipadapter_plus"), [repo_identity(IPA), repo_identity(FORK)])
        self.assertEqual(db.by_registry_id(""), [])
        self.assertFalse(db.info(repo_identity(GIST))["installable"])

    def test_malformed_files_index_nothing(self):
        db = NodeDb({"x": "not a list", 3: [[]], "https://github.com/a/b": [["T", 4], "meta"]},
                    {"custom_nodes": [None, {"files": []}, {"files": [3]}]})
        self.assertEqual(db.candidates("T"), ["github.com/a/b"])
        self.assertEqual(NodeDb([], "x").type_repos, {})


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=_support.SANDBOX)
        self.downloads = []

    def fake_download(self, payload=None, error=None):
        def download(url, dest, timeout=60):
            self.downloads.append(url)
            if error:
                raise error
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(payload)
        return mock.patch("deployer.core.http.download_file", download)

    def test_a_fresh_copy_is_reused_and_an_old_one_refreshed(self):
        with self.fake_download('{"v": 1}'):
            self.assertEqual(cached_json("a.json", "u", cache_dir=self.dir), {"v": 1})
            self.assertEqual(cached_json("a.json", "u", cache_dir=self.dir), {"v": 1})
        self.assertEqual(len(self.downloads), 1)
        with self.fake_download('{"v": 2}'):
            later = os.path.getmtime(os.path.join(self.dir, "a.json")) + 2 * node_db.DEFAULT_MAX_AGE
            self.assertEqual(cached_json("a.json", "u", cache_dir=self.dir, now=lambda: later), {"v": 2})
            self.assertEqual(cached_json("a.json", "u", cache_dir=self.dir, refresh=True), {"v": 2})
        self.assertEqual(len(self.downloads), 3)

    def test_a_failed_refresh_keeps_the_copy_and_no_copy_is_an_error(self):
        with self.fake_download('{"v": 1}'):
            cached_json("a.json", "u", cache_dir=self.dir)
        with self.fake_download(error=OSError("offline")):
            self.assertEqual(cached_json("a.json", "u", cache_dir=self.dir, refresh=True), {"v": 1})
            with self.assertRaises(NodeDbUnavailable):
                cached_json("b.json", "u", cache_dir=self.dir)

    def test_a_download_that_is_not_json_never_replaces_the_copy(self):
        with self.fake_download('{"v": 1}'):
            cached_json("a.json", "u", cache_dir=self.dir)
        with self.fake_download("<html>rate limited</html>"):
            self.assertEqual(cached_json("a.json", "u", cache_dir=self.dir, refresh=True), {"v": 1})
        self.assertEqual(os.listdir(self.dir), ["a.json"])  # no .part left behind


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=_support.SANDBOX)
        self.calls = []

    def fetch(self, answer):
        def fetch(url, timeout):
            self.calls.append(url)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return fetch

    def test_a_found_repository_is_cached(self):
        body = {"id": "pack", "repository": "https://github.com/o/Pack"}
        self.assertEqual(registry_repository("Pack", cache_dir=self.dir, fetch=self.fetch(body)),
                         "https://github.com/o/Pack")
        self.assertEqual(registry_repository("pack", cache_dir=self.dir, fetch=self.fetch(OSError())),
                         "https://github.com/o/Pack")
        self.assertEqual(self.calls, ["https://api.comfy.org/nodes/pack"])

    def test_an_unknown_id_is_cached_and_an_outage_is_not(self):
        missing = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        self.assertIsNone(registry_repository("gone", cache_dir=self.dir, fetch=self.fetch(missing)))
        self.assertIsNone(registry_repository("gone", cache_dir=self.dir, fetch=self.fetch(OSError())))
        self.assertIsNone(registry_repository("other", cache_dir=self.dir, fetch=self.fetch(OSError("down"))))
        self.assertIsNone(registry_repository("other", cache_dir=self.dir,
                                              fetch=self.fetch(urllib.error.HTTPError("u", 503, "x", {}, None))))
        self.assertEqual(len(self.calls), 3)  # gone once; other asked again each time

    def test_ids_and_answers_are_checked(self):
        self.assertIsNone(registry_repository("../etc", cache_dir=self.dir, fetch=self.fetch({})))
        self.assertIsNone(registry_repository("", cache_dir=self.dir, fetch=self.fetch({})))
        self.assertEqual(self.calls, [])
        self.assertIsNone(registry_repository("p", cache_dir=self.dir,
                                              fetch=self.fetch({"repository": "file:///C:/x"})))


class ResolveNodesOnThisMachineTest(_support.SandboxTestCase):
    """workflow_resolver.resolve_nodes: folders, origins, tracked list and DB gathered for real."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(workflow_resolver, "load_node_db", lambda refresh=False: manager_db())
        patch.start()
        self.addCleanup(patch.stop)

    def test_folders_are_read_with_their_origin_and_the_tracked_list_counts(self):
        ipa = _support.make_repo(os.path.join(self.repos, "ComfyUI_IPAdapter_plus"))
        _support.git("clone", "-q", ipa, self.node_path("ComfyUI_IPAdapter_plus"), cwd=self.work)
        os.makedirs(self.node_path("Loose.disabled"))
        with open(self.settings_path, "w", encoding="utf-8") as fh:
            json.dump({"nodes": [{"repo": FORK}]}, fh)

        folders = workflow_resolver.pack_folders(with_declared=False)
        self.assertEqual([(f.name, f.origin) for f in folders], [("ComfyUI_IPAdapter_plus", ipa)])
        self.assertEqual(workflow_resolver.tracked_identities(), {repo_identity(FORK)})

        # Its origin is a local path, not IPA: the folder holds "another repository".
        result = workflow_resolver.resolve_nodes(wanted_from_list(["IPAdapterAdvanced"]), object_info={},
                                                 use_registry=False)
        self.assertEqual(result.blocked[0]["origin"], ipa)
        # SharedType: the tracked fork wins the ambiguity (a namesake folder is no clone of
        # either), then meets that folder.
        result = workflow_resolver.resolve_nodes(wanted_from_list(["SharedType"]), object_info={},
                                                 use_registry=False)
        self.assertEqual([(b["repo"], b["folder"]) for b in result.blocked], [(FORK, "ComfyUI_IPAdapter_plus")])

    def test_an_unavailable_db_is_a_warning(self):
        warnings = []

        def unavailable(refresh=False):
            raise NodeDbUnavailable("offline")

        with mock.patch.object(workflow_resolver, "load_node_db", unavailable):
            result = workflow_resolver.resolve_nodes(
                wanted_from_list(["X", {"type": "Y", "aux_id": "o/r"}]), object_info={},
                use_registry=False, warn=warnings.append)
        self.assertEqual((result.unknown, [p["repo"] for p in result.packs]), (["X"], ["https://github.com/o/r"]))
        self.assertIn("unavailable", warnings[0])

    def test_nothing_missing_never_loads_the_db(self):
        with mock.patch.object(workflow_resolver, "load_node_db", side_effect=AssertionError("loaded")):
            result = workflow_resolver.resolve_nodes(wanted_from_list(["KSampler"]),
                                                     object_info=object_info(KSampler=True))
        self.assertTrue(result.is_empty())

    def test_the_windows_shape_keeps_installs_conflicts_and_the_rest(self):
        workflow = os.path.join(self.work, "wf.json")
        with open(workflow, "w", encoding="utf-8") as fh:
            json.dump({"nodes": [
                {"type": "IPAdapterAdvanced", "mode": 4},  # bypassed: the window still wants it
                {"type": "SharedType"}, {"type": "NewCoreNode"}, {"type": "Mystery"}, {"type": "GistNode"},
            ]}, fh)
        with mock.patch.object(workflow_resolver, "registry_repository", lambda cnr_id: None):
            resolved, conflicts, unresolved, descriptions = workflow_resolver.resolve_workflow_nodes(workflow, set())
        self.assertEqual([(r.repo, r.node_types) for r in resolved], [(IPA, ["IPAdapterAdvanced"])])
        self.assertEqual([(c.node_types, sorted(c.repo_options)) for c in conflicts],
                         [(["SharedType"], sorted([IPA, FORK]))])
        self.assertEqual(unresolved, ["GistNode", "Mystery", "NewCoreNode"])
        self.assertEqual(descriptions[FORK], "")
        self.assertEqual(workflow_resolver.extract_workflow_node_types(workflow),
                         {"IPAdapterAdvanced", "SharedType", "NewCoreNode", "Mystery", "GistNode"})

    def test_the_static_scan_reads_comfyui_and_the_packs_sources(self):
        from deployer import config

        os.makedirs(os.path.join(config.COMFY_EXTRAS_DIR, "sub"), exist_ok=True)
        os.makedirs(workflow_resolver.COMFY_API_NODES_DIR, exist_ok=True)
        self.addCleanup(_support.rmtree, config.COMFY_EXTRAS_DIR)
        self.addCleanup(_support.rmtree, workflow_resolver.COMFY_API_NODES_DIR)
        files = {
            os.path.join(config.COMFY_EXTRAS_DIR, "sub", "deep.py"): 'NODE_CLASS_MAPPINGS = {"Deep": X}',
            os.path.join(workflow_resolver.COMFY_API_NODES_DIR, "api.py"): 'io.Schema(node_id="ApiNode")',
            os.path.join(self.node_path("Pack"), "nodes.py"): 'NODE_CLASS_MAPPINGS["PackNode"] = P',
        }
        for path, text in files.items():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        result = workflow_resolver.resolve_nodes(wanted_from_list(["Deep", "ApiNode", "PackNode"]),
                                                 use_registry=False)
        self.assertTrue(result.is_empty(), result.as_dict())


if __name__ == "__main__":
    unittest.main()

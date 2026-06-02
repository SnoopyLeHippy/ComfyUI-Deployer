"""Detect and repair broken Python packages in the bundled python_embeded.

Two complementary passes:

* :func:`run_pip_check` — runs ``uv pip check`` to detect dependency-graph
  issues (missing deps, version conflicts).
* :func:`run_file_integrity_check` — for every installed distribution, walks
  the wheel's RECORD and verifies each listed file still exists on disk.
  Catches the case where metadata is intact but native extensions (``.pyd``,
  ``.so``) were deleted or never finished extracting — which ``uv pip check``
  silently misses.

Reinstalls go through :func:`reinstall_packages` which uses uv's
``--reinstall-package`` so only the named packages are touched. CUDA-tied
packages (torch, xformers, triton…) are exposed in :data:`CRITICAL_PACKAGES`
so the UI can warn before letting them be reinstalled.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from deployer.config import COMFYUI_DIR, CUSTOM_NODES_DIR, PYTHON_EXE
from deployer.core.filesystem import force_remove_readonly
from deployer.core.pip_runner import _run, _uv_available, ensure_uv


# Packages whose reinstall risks pulling a CPU-only wheel from PyPI or
# breaking the CUDA ABI of the bundle. The UI shows these unchecked and
# flagged so the user opts in explicitly.
CRITICAL_PACKAGES = frozenset({
    "torch",
    "torchvision",
    "torchaudio",
    "torchsde",
    "xformers",
    "triton",
})


@dataclass
class BrokenPackage:
    """A package flagged by one of the check passes.

    ``reasons`` is a list because the same package can be flagged for multiple
    reasons (e.g. missing files AND a wrong dependency version).

    ``stray_dirs`` is populated by :func:`run_shadow_scan` and lists empty
    directories that shadow the real install at ComfyUI runtime. Reinstall
    only fixes the user-visible bug if these dirs are deleted first.

    ``target_version`` overrides the reinstall version. It is set when a pass
    knows the *correct* version to install differs from what's on disk — e.g.
    a sibling's exact pin was violated by a stray upgrade (pydantic requires
    pydantic-core==X but X+1 got installed). When None, the reinstall pins to
    the currently-installed version (a plain restore).
    """

    name: str
    reasons: list[str] = field(default_factory=list)
    is_critical: bool = False
    stray_dirs: list[str] = field(default_factory=list)
    target_version: str | None = None


def _normalize(name: str) -> str:
    """Return the canonical PyPI form: lowercase, underscores → dashes."""
    return name.strip().lower().replace("_", "-")


# ---------------------------------------------------------------------------
# Pass 1: dependency-graph check via ``uv pip check``
# ---------------------------------------------------------------------------

_CHECK_PATTERN = re.compile(
    r"requires\s+([A-Za-z0-9._-]+)[^,]*,\s*but\s+([A-Za-z0-9._-]+)"
)
_FALLBACK_PATTERN = re.compile(r"^([A-Za-z0-9._-]+)==")

# Matches pydantic's runtime guard (``_ensure_pydantic_core_version``), which
# raises a SystemError when the installed pydantic-core diverges from the exact
# version pydantic was built against. ``uv pip check`` misses this — both
# dist-infos are internally consistent — but it's fatal at ComfyUI startup. We
# capture the broken package (group 1) and the version it *should* be (group 2)
# so the reinstall can pin to the correct release rather than restore the
# already-broken one. Phrased generically enough to survive minor wording
# changes / other packages adopting the same "installed X (a) ... requires b".
_VERSION_GUARD_PATTERN = re.compile(
    r"installed\s+([A-Za-z0-9._-]+)\s+version\s+\([^)]+\)\s+is\s+incompatible"
    r".*?requires\s+([0-9][0-9A-Za-z.\-]*)",
    re.DOTALL,
)


def run_pip_check(python_exe: str = PYTHON_EXE) -> list[BrokenPackage]:
    """Run ``uv pip check`` and parse the broken packages from its output.

    The check reports a problem like::

        pydantic==2.5 requires pydantic-core==2.14.5, but pydantic-core is not installed

    We extract the *required* package name (``pydantic-core``) as the
    actionable target — reinstalling it is what fixes the dep graph.
    """
    ensure_uv(python_exe, stream_output=False)
    if not _uv_available(python_exe):
        print("  uv unavailable; skipping pip check pass.")
        return []

    cmd = [python_exe, "-m", "uv", "pip", "check", "--python", python_exe]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        print(f"  uv pip check failed to launch: {exc}")
        return []

    if proc.returncode == 0:
        return []

    broken: dict[str, BrokenPackage] = {}
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip uv's summary lines ("Found N error(s):", "All checks passed").
        if line.lower().startswith(("found ", "all ")):
            continue

        match = _CHECK_PATTERN.search(line)
        if match:
            target = _normalize(match.group(2))
            reason = line
        else:
            fallback = _FALLBACK_PATTERN.match(line)
            if not fallback:
                continue
            target = _normalize(fallback.group(1))
            reason = line

        entry = broken.setdefault(
            target,
            BrokenPackage(name=target, is_critical=target in CRITICAL_PACKAGES),
        )
        if reason not in entry.reasons:
            entry.reasons.append(reason)

    return sorted(broken.values(), key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Pass 2: on-disk file-integrity check
# ---------------------------------------------------------------------------

# Run by the bundle's python_embeded. Walks every installed distribution and
# reports those whose RECORD lists files that no longer exist on disk.
# Keeps the missing-list short (5 entries) so the JSON stays small.
_FILE_INTEGRITY_SCRIPT = r"""
import importlib.metadata as md
import json
import sys

results = []
for dist in md.distributions():
    try:
        meta_name = dist.metadata["Name"] if dist.metadata else None
        if not meta_name:
            continue
        record = dist.read_text("RECORD")
        if not record:
            continue
        missing = []
        for raw_line in record.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            path = line.split(",", 1)[0]
            if not path or path.endswith(".pyc") or path.endswith(".pyo"):
                continue
            try:
                full = dist.locate_file(path)
                if not full.exists():
                    missing.append(path)
                    if len(missing) >= 5:
                        break
            except Exception:
                pass
        if missing:
            results.append({"name": meta_name, "missing": missing})
    except Exception as exc:
        print("# warn: " + repr(exc), file=sys.stderr)
        continue

json.dump(results, sys.stdout)
"""


def run_file_integrity_check(python_exe: str = PYTHON_EXE) -> list[BrokenPackage]:
    """Check every installed package for missing files (per its RECORD)."""
    try:
        proc = subprocess.run(
            [python_exe, "-c", _FILE_INTEGRITY_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        print(f"  File-integrity check failed to launch: {exc}")
        return []

    if proc.returncode != 0:
        snippet = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = "\n  ".join(snippet[-3:]) if snippet else "<no output>"
        print(f"  File-integrity check exited with code {proc.returncode}:\n  {tail}")
        return []

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        print(f"  File-integrity check: could not parse output ({exc}).")
        return []

    broken: list[BrokenPackage] = []
    for entry in data:
        name = _normalize(entry.get("name", ""))
        missing = entry.get("missing") or []
        if not name or not missing:
            continue
        # Pick the most "diagnostic" file (native extensions first) so the
        # reason line tells the user what's actually wrong.
        sample = next(
            (m for m in missing if m.endswith((".pyd", ".so", ".dll"))),
            missing[0],
        )
        reason = f"{len(missing)} file(s) missing on disk (e.g. {sample})"
        broken.append(BrokenPackage(
            name=name,
            reasons=[reason],
            is_critical=name in CRITICAL_PACKAGES,
        ))
    return sorted(broken, key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Pass 3: import probe — catches namespace-package shadowing
# ---------------------------------------------------------------------------

# Heavy packages whose import we deliberately skip. Their cost dwarfs every
# other import, and a "broken torch" surfaces through CUDA errors (not the
# ImportError-style failures this probe is designed to catch).
_IMPORT_PROBE_SKIP = frozenset({
    "torch", "torchvision", "torchaudio", "torchsde",
    "xformers", "triton",
    "tensorflow", "jax", "tensorrt",
    "numpy", "scipy", "pandas",
    "transformers", "diffusers",
})

# Runs in the bundle's python_embeded. Targets a very specific failure mode:
# a distribution is correctly installed per its metadata (pip check passes,
# RECORD-listed files all exist), but Python's import resolution still hits
# an *empty* directory with the same name — so the module imports as a
# degenerate namespace package with no ``__file__`` and no submodules. This
# is the ``(unknown location)`` pattern seen in ComfyUI's pydantic_core bug.
#
# We deliberately skip ImportError noise here: pass 2 already catches missing
# native files, and ImportError from optional-system-library packages
# (pyfluidsynth, mediapipe, IIS-only pywin32 modules) is not actionable
# through a reinstall.
_IMPORT_PROBE_SCRIPT = r"""
import importlib
import importlib.metadata as md
import json
import os
import sys

SKIP = set(%(skip)r)


def _norm(s):
    return s.lower().replace("_", "-")


def _walk_has_real_files(paths):
    # A namespace pkg is "real" if any of its __path__ entries contains a
    # .py / .pyd / .so file anywhere underneath (subpackages count). Stops at
    # the first hit so PEP-420 namespaces with deep trees (google.*, etc.)
    # are cheap to verify.
    for p in paths:
        if not os.path.isdir(p):
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith((".py", ".pyd", ".so")):
                    return True
    return False


try:
    mapping = md.packages_distributions()
except Exception as exc:
    print("# fatal: " + repr(exc), file=sys.stderr)
    sys.exit(1)

results = []
for top_name, dist_names in mapping.items():
    if not top_name or top_name.startswith("_") or top_name in SKIP:
        continue
    primary = dist_names[0] if dist_names else None
    if not primary:
        continue
    # Only probe when the import name matches the dist name. Skips legit
    # PEP-420 namespaces shared across dists (``google`` from protobuf,
    # ``mpl_toolkits`` from matplotlib, IIS-only pywin32 submodules…) which
    # otherwise produce false positives. Tradeoff: dists with non-matching
    # import names (pillow→PIL, beautifulsoup4→bs4) are not probed.
    if _norm(top_name) != _norm(primary):
        continue

    try:
        mod = importlib.import_module(top_name)
    except BaseException:
        # Import failures are intentionally ignored here; pass 2 covers the
        # actionable corruption cases (missing files), and the rest is noise.
        continue

    if getattr(mod, "__file__", None) is not None:
        continue  # Regular package on disk — fine.

    paths = list(getattr(mod, "__path__", []))
    if _walk_has_real_files(paths):
        continue  # Legit namespace pkg with real submodules.

    sample = paths[0] if paths else "<no path>"
    results.append({
        "dist": primary,
        "module": top_name,
        "error": (
            "Imports as empty namespace package (no files inside) at "
            + sample + " — reinstall should restore the real package files."
        ),
    })

json.dump(results, sys.stdout)
""" % {"skip": list(_IMPORT_PROBE_SKIP)}


def run_import_probe(python_exe: str = PYTHON_EXE) -> list[BrokenPackage]:
    """Import every package's top-level module and flag failures.

    Complementary to :func:`run_file_integrity_check`: catches cases where the
    dist-info and the on-disk files are intact, but Python's import resolution
    is hitting a *different* directory (typically an empty stray dir on
    ``sys.path``). The error surfaces as a namespace-package import that has
    no ``__file__`` — exactly the ``(unknown location)`` pattern users see in
    ComfyUI's pydantic_core failure.
    """
    try:
        proc = subprocess.run(
            [python_exe, "-c", _IMPORT_PROBE_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
    except subprocess.TimeoutExpired:
        print("  Import probe timed out after 240s.")
        return []
    except OSError as exc:
        print(f"  Import probe failed to launch: {exc}")
        return []

    if proc.returncode != 0:
        snippet = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = "\n  ".join(snippet[-3:]) if snippet else "<no output>"
        print(f"  Import probe exited with code {proc.returncode}:\n  {tail}")
        return []

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        print(f"  Import probe: could not parse output ({exc}).")
        return []

    by_dist: dict[str, BrokenPackage] = {}
    for entry in data:
        dist = _normalize(entry.get("dist", ""))
        if not dist:
            continue
        reason = entry.get("error", "import failed")
        pkg = by_dist.setdefault(
            dist,
            BrokenPackage(name=dist, is_critical=dist in CRITICAL_PACKAGES),
        )
        if reason not in pkg.reasons:
            pkg.reasons.append(reason)
    return sorted(by_dist.values(), key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Pass 4: shadow scan — stray dirs in ComfyUI/ and custom_nodes/
# ---------------------------------------------------------------------------

# ComfyUI top-level subdirs we will NEVER flag as a stray, even if a future
# pip package coincidentally takes one of these names. Lets the scan be
# aggressive without flagging legitimate ComfyUI internals.
_COMFYUI_RESERVED = frozenset({
    "app", "comfy", "comfy_api", "comfy_extras", "comfy_api_nodes",
    "custom_nodes", "input", "output", "models", "user", "web",
    "tests", "tests-unit", "script_examples", "notebooks",
    "fix_torch", "alembic_db", "api_server", "utils", "templates",
})

_SCAN_EXCLUDED = frozenset({".git", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", ".venv"})


def _list_installed_top_levels(python_exe: str) -> dict[str, str]:
    """Return a dict mapping each top-level module name → primary dist name.

    Uses ``importlib.metadata.packages_distributions()`` inside the bundle's
    python_embeded so we get exactly what pip considers installed there.
    """
    proc = subprocess.run(
        [
            python_exe, "-c",
            "import importlib.metadata as md, json; "
            "print(json.dumps(md.packages_distributions()))",
        ],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        mapping = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}

    candidates: dict[str, str] = {}
    for top_name, dist_names in mapping.items():
        if not top_name or top_name.startswith("_"):
            continue
        if not dist_names:
            continue
        # Prefer the dist whose name matches the top-level (after normalization)
        # so we reinstall the actual owner, not a co-dist that happens to ship
        # the same top-level.
        primary = next(
            (d for d in dist_names if _normalize(d) == _normalize(top_name)),
            dist_names[0],
        )
        candidates[top_name] = primary
    return candidates


def _dir_has_package_files(path: str) -> bool:
    """Return True if *path* looks like a real package directory.

    A real package has either ``__init__.py`` or a native module file (``.pyd``
    / ``.so``) directly inside, or contains any ``.py`` / ``.pyd`` file deeper
    in its tree (case of namespace packages with subpackages).
    """
    try:
        top_entries = os.listdir(path)
    except OSError:
        return False
    if "__init__.py" in top_entries:
        return True
    for e in top_entries:
        if e.endswith((".pyd", ".so")) and os.path.isfile(os.path.join(path, e)):
            return True
    for _root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SCAN_EXCLUDED]
        for f in files:
            if f.endswith((".py", ".pyd", ".so")):
                return True
    return False


def run_shadow_scan(python_exe: str = PYTHON_EXE) -> list[BrokenPackage]:
    """Scan ``ComfyUI/`` and ``custom_nodes/`` for empty stray dirs that
    shadow installed pip packages at runtime.

    ComfyUI prepends ``ComfyUI/`` (where ``main.py`` lives) and adds
    ``custom_nodes/`` to ``sys.path`` at startup. Any direct subdirectory in
    those paths whose name matches an installed top-level module is found
    *before* the real install in ``site-packages`` and gets imported as a
    degenerate namespace package — the ``(unknown location)`` ImportError.

    Reinstalling alone won't fix this; the stray dirs must be removed first.
    """
    candidates = _list_installed_top_levels(python_exe)
    if not candidates:
        return []

    # case-insensitive lookup for Windows-friendly matching
    candidates_ci: dict[str, tuple[str, str]] = {
        top.lower(): (top, dist) for top, dist in candidates.items()
    }

    locations: list[tuple[str, frozenset[str]]] = []
    if os.path.isdir(COMFYUI_DIR):
        locations.append((COMFYUI_DIR, _COMFYUI_RESERVED))
    if os.path.isdir(CUSTOM_NODES_DIR):
        # Custom_nodes has no reserved names — every direct child is a node
        # that could potentially be (or contain) a shadow.
        locations.append((CUSTOM_NODES_DIR, frozenset()))

    broken: dict[str, BrokenPackage] = {}
    for location, reserved in locations:
        try:
            entries = os.listdir(location)
        except OSError:
            continue
        for entry in entries:
            entry_lower = entry.lower()
            if entry_lower in _SCAN_EXCLUDED or entry in reserved:
                continue
            full = os.path.join(location, entry)
            if not os.path.isdir(full):
                continue
            match = candidates_ci.get(entry_lower)
            if not match:
                continue
            _top_name, dist_name = match
            # If the dir has real package files, it's a legitimate copy
            # (e.g. a custom_node that vendors a dep) — not a shadow we can fix.
            if _dir_has_package_files(full):
                continue

            key = _normalize(dist_name)
            pkg = broken.setdefault(
                key,
                BrokenPackage(name=key, is_critical=key in CRITICAL_PACKAGES),
            )
            reason = (
                f"Stray empty dir at {full} — Python finds this before "
                f"site-packages and imports it as an empty namespace package, "
                f"shadowing pip-installed {dist_name}. Will be deleted on reinstall."
            )
            if reason not in pkg.reasons:
                pkg.reasons.append(reason)
            if full not in pkg.stray_dirs:
                pkg.stray_dirs.append(full)

    return sorted(broken.values(), key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Pass 5: startup probe — runs in ComfyUI's actual runtime sys.path
# ---------------------------------------------------------------------------

# This script gets passed via -c, runs with cwd=ComfyUI/. It reproduces the
# sys.path layout that main.py sees: ComfyUI/ prepended (script dir) plus
# custom_nodes/, then runs every custom_node's prestartup_script.py — that's
# where prestart scripts can sneak more paths onto sys.path. After all that
# we ask ``importlib.util.find_spec`` exactly where each installed top-level
# resolves; namespace-package resolutions whose dirs hold no real Python
# files are reported with their full paths so they can be deleted.
_STARTUP_PROBE_SCRIPT = r"""
import importlib.metadata as md
import importlib.util
import json
import os
import sys
import traceback

SKIP = set(%(skip)r)


def _norm(s):
    return s.lower().replace("_", "-")


def _has_real_files(path):
    if not isinstance(path, str) or not os.path.isdir(path):
        return False
    try:
        entries = os.listdir(path)
    except OSError:
        return False
    if "__init__.py" in entries:
        return True
    for e in entries:
        if e.endswith((".pyd", ".so")) and os.path.isfile(os.path.join(path, e)):
            return True
    for _r, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith((".py", ".pyd", ".so")):
                return True
    return False


# Mimic main.py's sys.path:
script_dir = os.getcwd()
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
custom_nodes = os.path.join(script_dir, "custom_nodes")
if os.path.isdir(custom_nodes) and custom_nodes not in sys.path:
    sys.path.insert(0, custom_nodes)

# Some prestart scripts (e.g. ComfyUI-Manager) inspect ``sys.modules['__main__'].__file__``
# to anchor their paths. We're running via ``python -c`` which leaves __main__
# without a __file__, so point it at the real main.py to match runtime.
_main_py = os.path.join(script_dir, "main.py")
if os.path.isfile(_main_py):
    sys.modules["__main__"].__file__ = _main_py

# Run each prestart script. Some custom_nodes inject more paths from here.
prestart = []
if os.path.isdir(custom_nodes):
    for entry in sorted(os.listdir(custom_nodes)):
        script_path = os.path.join(custom_nodes, entry, "prestartup_script.py")
        if not os.path.isfile(script_path):
            continue
        try:
            with open(script_path, "r", encoding="utf-8") as fh:
                code = fh.read()
            # Run with __file__ set so relative-path tricks inside the script work.
            exec(compile(code, script_path, "exec"),
                 {"__name__": "prestartup_script", "__file__": script_path})
            prestart.append({"node": entry, "status": "OK"})
        except SystemExit as exc:
            prestart.append({"node": entry, "status": "SystemExit", "code": str(exc)})
        except BaseException as exc:  # noqa: BLE001
            prestart.append({
                "node": entry,
                "status": "ERR",
                "error": type(exc).__name__ + ": " + str(exc),
            })

# Snapshot sys.path AFTER prestart so the diagnostic shows what was added.
post_prestart_path = list(sys.path)

# Walk installed dists, see where each top-level actually resolves now.
# A top-level whose name matches its dist (e.g. pydantic_core ↔ pydantic-core)
# should always resolve as a *regular* package: pip wheels for such packages
# ship an ``__init__.py``. If find_spec returns a namespace package (origin
# None), something on sys.path holds a ``<name>/`` directory without
# ``__init__.py`` — either site-packages was corrupted (the .pyd survives
# but __init__.py was deleted) or a stray dir contributes to the namespace.
# Either way, every namespace contributor without ``__init__.py`` is junk we
# can safely delete before reinstalling.
results = []
try:
    mapping = md.packages_distributions()
except BaseException as exc:
    print("# fatal: " + repr(exc), file=sys.stderr)
    sys.exit(1)

for top_name, dist_names in mapping.items():
    if not top_name or top_name.startswith("_") or top_name in SKIP:
        continue
    primary = None
    for d in dist_names or []:
        if _norm(d) == _norm(top_name):
            primary = d
            break
    if primary is None and dist_names:
        primary = dist_names[0]
    if not primary or _norm(top_name) != _norm(primary):
        continue

    try:
        spec = importlib.util.find_spec(top_name)
    except BaseException:
        continue
    if spec is None:
        continue
    if spec.origin and spec.has_location:
        continue  # Regular package on disk — fine.

    # Only flag when the dist's RECORD EXPECTS __init__.py to exist. Some
    # packages (HF optimum and friends) intentionally ship as PEP 420
    # namespaces so other dists can extend them; their RECORD never lists
    # __init__.py and we must not nuke their dirs.
    record = ""
    record_source = "none"
    for name_attempt in (primary, top_name, primary.replace("-", "_"), primary.replace("_", "-")):
        try:
            dist_obj = md.distribution(name_attempt)
        except BaseException:
            continue
        try:
            text = dist_obj.read_text("RECORD")
        except BaseException:
            text = None
        if text:
            record = text
            record_source = "md.distribution({!r})".format(name_attempt)
            break
    expected = top_name + "/__init__.py"
    record_has_init = False
    for raw_line in record.splitlines():
        path = raw_line.split(",", 1)[0].strip().replace("\\", "/")
        if path == expected or path.endswith("/" + expected):
            record_has_init = True
            break

    # Always log namespace-pkg findings to stderr so users can see why we
    # did or didn't flag each one. Indexed by top_name so the parent can
    # surface the failures even when nothing gets flagged.
    print(
        "# nspkg: top={} primary={} record_src={} record_len={} has_init={} paths={}".format(
            top_name, primary, record_source, len(record), record_has_init,
            list(spec.submodule_search_locations or []),
        ),
        file=sys.stderr,
    )

    if not record_has_init:
        continue  # Intentional namespace package; nothing to repair.

    paths = [p for p in (spec.submodule_search_locations or [])]
    bad_paths = [
        p for p in paths
        if isinstance(p, str) and not os.path.isfile(os.path.join(p, "__init__.py"))
    ]
    if not bad_paths:
        continue

    results.append({
        "dist": primary,
        "module": top_name,
        "stray_dirs": bad_paths,
        "all_search_locations": paths,
        "source": "record_check",
    })

# Always include a focused report for the import line that fails in user logs.
focused = {}
for name in ("pydantic", "pydantic_core"):
    try:
        spec = importlib.util.find_spec(name)
        if spec is None:
            focused[name] = {"status": "not_found"}
        else:
            focused[name] = {
                "origin": str(spec.origin) if spec.origin else None,
                "submodule_search_locations": list(spec.submodule_search_locations or []),
                "has_location": bool(spec.has_location),
            }
    except BaseException as exc:
        focused[name] = {"error": repr(exc)}

# Actually attempt the import that fails for the user. Captures the precise
# traceback if it still fails inside our reproduction.
pydantic_import = {}
try:
    from pydantic import ValidationError  # noqa: F401
    pydantic_import["status"] = "OK"
except BaseException as exc:
    pydantic_import["status"] = "FAILED"
    pydantic_import["error"] = type(exc).__name__ + ": " + str(exc)
    pydantic_import["traceback"] = traceback.format_exc()

# Fallback flagging: when the reproduction failed AND the error message blames
# a specific module ("cannot import name 'X' from 'Y'"), trust the traceback
# over our heuristic. This catches cases where packages_distributions() doesn't
# include the broken top-level (e.g. dist-info missing top_level.txt and
# RECORD can't be inferred because the install is half-corrupted).
import re as _re
if pydantic_import.get("status") == "FAILED":
    err = pydantic_import.get("error", "")
    match = _re.search(r"from ['\"]([^'\"]+)['\"]", err)
    if match:
        broken_top = match.group(1).split(".", 1)[0]

        # Resolve the dist name independently of ``mapping``. Try several
        # variants directly against ``md.distribution`` — the dist-info dir
        # is on disk even when packages_distributions() can't infer the
        # top-level mapping for it.
        broken_dist = None
        seen = set()
        candidates = []
        if mapping.get(broken_top):
            candidates.extend(mapping[broken_top])
        candidates.extend([
            broken_top,
            broken_top.replace("_", "-"),
            broken_top.replace("-", "_"),
        ])
        for cand in candidates:
            if not cand or cand in seen:
                continue
            seen.add(cand)
            try:
                d_obj = md.distribution(cand)
                broken_dist = (d_obj.metadata["Name"] if d_obj.metadata else None) or cand
                break
            except BaseException:
                continue
        # Last resort: normalize the top-level name and use that as the dist.
        if not broken_dist:
            broken_dist = broken_top.replace("_", "-").lower()

        try:
            spec = importlib.util.find_spec(broken_top)
        except BaseException:
            spec = None
        search_paths = list(spec.submodule_search_locations or []) if spec else []
        bad_paths = [
            p for p in search_paths
            if isinstance(p, str) and not os.path.isfile(os.path.join(p, "__init__.py"))
        ]

        print(
            "# fallback: broken_top={} broken_dist={} bad_paths={}".format(
                broken_top, broken_dist, bad_paths,
            ),
            file=sys.stderr,
        )

        if bad_paths and not any(r["dist"] == broken_dist for r in results):
            results.append({
                "dist": broken_dist,
                "module": broken_top,
                "stray_dirs": bad_paths,
                "all_search_locations": search_paths,
                "source": "import_failure_traceback",
            })

# Also dump a quick view of the mapping entries for the module that failed,
# so we can see whether packages_distributions() saw it at all.
if pydantic_import.get("status") == "FAILED":
    pyd_keys = [k for k in mapping.keys() if "pydantic" in k.lower()]
    print(
        "# mapping pydantic-related keys: {}".format(pyd_keys),
        file=sys.stderr,
    )

# Prestart scripts can print arbitrary stuff to stdout; delimit our JSON so
# the parent process can extract it reliably regardless of that noise.
print("__SP_JSON_START__")
print(json.dumps({
    "results": results,
    "focused": focused,
    "pydantic_import": pydantic_import,
    "sys_path": post_prestart_path,
    "prestart": prestart,
}, default=str))
print("__SP_JSON_END__")
""" % {"skip": list(_IMPORT_PROBE_SKIP)}


def run_startup_probe(
    python_exe: str = PYTHON_EXE,
    *,
    timeout: int = 180,
    verbose: bool = True,
) -> list[BrokenPackage]:
    """Reproduce ComfyUI startup just enough to surface the *runtime* sys.path.

    Runs in a subprocess with ``cwd=COMFYUI_DIR`` so Python's automatic
    script-dir prepending matches main.py's, then sources every custom_node's
    ``prestartup_script.py`` exactly as ComfyUI does. After that point any
    extra paths injected by those scripts are live, and we ask
    :func:`importlib.util.find_spec` where each installed top-level resolves —
    pinpointing the stray dir behind the ``(unknown location)`` ImportError.

    The diagnostic block (``focused``, ``pydantic_import``, ``sys_path``) is
    streamed to the console when *verbose* is True so users can paste it back
    if their case still slips through.
    """
    if not os.path.isdir(COMFYUI_DIR):
        return []

    try:
        proc = subprocess.run(
            [python_exe, "-c", _STARTUP_PROBE_SCRIPT],
            cwd=COMFYUI_DIR,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  Startup probe timed out after {timeout}s "
              "(a prestart script is probably hanging).")
        return []
    except OSError as exc:
        print(f"  Startup probe failed to launch: {exc}")
        return []

    stdout = proc.stdout or ""
    if not stdout.strip():
        if proc.stderr:
            print(f"  Startup probe: empty stdout. stderr tail: {proc.stderr.strip()[-300:]}")
        return []

    # Prestart scripts print to stdout too — extract the delimited JSON.
    match = re.search(
        r"__SP_JSON_START__\s*\n(.*?)\n\s*__SP_JSON_END__",
        stdout, re.DOTALL,
    )
    if not match:
        print("  Startup probe: JSON delimiters not found in subprocess output.")
        print(f"  stdout tail: {stdout.strip()[-300:]}")
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        print(f"  Startup probe: could not parse delimited output ({exc}).")
        return []

    if verbose:
        # Surface the diagnostic so users (and the dev console) see exactly
        # where pydantic_core ends up resolving even when nothing trips the
        # heuristic check.
        focused = data.get("focused", {})
        for name, info in focused.items():
            print(f"  startup-probe spec for {name}: {info}")
        pi = data.get("pydantic_import", {})
        if pi.get("status") == "FAILED":
            print("  startup-probe reproduced the import failure:")
            for line in (pi.get("traceback") or "").rstrip().splitlines():
                print(f"    {line}")
        prestart_errors = [p for p in data.get("prestart", []) if p.get("status") not in {"OK", "SystemExit"}]
        if prestart_errors:
            print(f"  startup-probe: {len(prestart_errors)} prestart script(s) errored:")
            for entry in prestart_errors[:5]:
                print(f"    - {entry.get('node')}: {entry.get('error')}")

        # The subprocess writes diagnostic lines to stderr; echo them so we
        # (and the user) can see *why* a flagged-looking case didn't trip
        # the RECORD check, or what the fallback decided.
        for line in (proc.stderr or "").splitlines():
            if line.startswith(("# nspkg:", "# fallback:", "# mapping")):
                print(f"  {line}")

    by_dist: dict[str, BrokenPackage] = {}
    for entry in data.get("results", []):
        dist = _normalize(entry.get("dist", ""))
        if not dist:
            continue
        stray_dirs = [p for p in entry.get("stray_dirs", []) if p and os.path.isdir(p)]
        if not stray_dirs:
            continue
        pkg = by_dist.setdefault(
            dist,
            BrokenPackage(name=dist, is_critical=dist in CRITICAL_PACKAGES),
        )
        for d in stray_dirs:
            if d not in pkg.stray_dirs:
                pkg.stray_dirs.append(d)
        reason = (
            f"At ComfyUI runtime, '{entry.get('module')}' resolves to an "
            f"empty namespace package at {stray_dirs[0]} (no real files). "
            "Will be deleted on reinstall."
        )
        if reason not in pkg.reasons:
            pkg.reasons.append(reason)

    # Version-guard failures (e.g. pydantic refusing a mismatched pydantic-core)
    # are reproduced by the import attempt above but trip none of the on-disk
    # heuristics — uv pip check misses them too. Parse the captured error and
    # flag the offending package, pinned to the version it must be downgraded /
    # upgraded to so the reinstall actually converges.
    pi = data.get("pydantic_import", {})
    if pi.get("status") == "FAILED":
        guard = _VERSION_GUARD_PATTERN.search(pi.get("error", ""))
        if guard:
            dist = _normalize(guard.group(1))
            wanted = guard.group(2).rstrip(".-")
            pkg = by_dist.setdefault(
                dist,
                BrokenPackage(name=dist, is_critical=dist in CRITICAL_PACKAGES),
            )
            pkg.target_version = wanted
            reason = (
                f"At ComfyUI runtime, an installed package requires "
                f"{dist}=={wanted} but a different version is installed "
                "(uv pip check does not catch this). Will be reinstalled at "
                f"{wanted}."
            )
            if reason not in pkg.reasons:
                pkg.reasons.append(reason)

    return sorted(by_dist.values(), key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Merge + reinstall
# ---------------------------------------------------------------------------

def merge_results(*results_lists: list[BrokenPackage]) -> list[BrokenPackage]:
    """Merge multiple check results by package name, concatenating reasons
    and stray_dirs from each contributing pass.
    """
    merged: dict[str, BrokenPackage] = {}
    for results in results_lists:
        for pkg in results:
            entry = merged.setdefault(
                pkg.name,
                BrokenPackage(name=pkg.name, is_critical=pkg.is_critical),
            )
            for reason in pkg.reasons:
                if reason not in entry.reasons:
                    entry.reasons.append(reason)
            for d in pkg.stray_dirs:
                if d not in entry.stray_dirs:
                    entry.stray_dirs.append(d)
            # A known-correct target version wins over a plain restore.
            if pkg.target_version:
                entry.target_version = pkg.target_version
    return sorted(merged.values(), key=lambda p: p.name)


def _installed_versions(python_exe: str, names: list[str]) -> dict[str, str]:
    """Return {normalized name: installed version} for the given packages.

    Reads each distribution's version from its ``METADATA`` (via
    :mod:`importlib.metadata`), which survives even when the install is
    corrupted enough to be missing its ``RECORD`` — exactly the state a repair
    is trying to fix. Packages whose version can't be read are simply absent
    from the result, and the caller reinstalls them unpinned.
    """
    if not names:
        return {}

    script = (
        "import importlib.metadata as md, json, sys\n"
        "out = {}\n"
        "for n in json.load(sys.stdin):\n"
        "    try:\n"
        "        out[n] = md.version(n)\n"
        "    except Exception:\n"
        "        pass\n"
        "json.dump(out, sys.stdout)\n"
    )
    try:
        proc = subprocess.run(
            [python_exe, "-c", script],
            input=json.dumps(names),
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        print(f"  Could not read installed versions: {exc}")
        return {}

    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return {_normalize(k): v for k, v in data.items() if v}


def _delete_stray_dirs(stray_dirs: list[str]) -> None:
    """Remove every stray directory, logging each result.

    Read-only files are coerced via :func:`force_remove_readonly` so the same
    edge-case handling as ``uninstall_node`` applies here.
    """
    for path in stray_dirs:
        if not os.path.isdir(path):
            continue
        print(f"  Removing stray directory: {path}")
        try:
            shutil.rmtree(path, onerror=force_remove_readonly)
        except OSError as exc:
            print(f"  Warning: could not remove {path}: {exc}")


def reinstall_packages(
    python_exe: str,
    packages: list[BrokenPackage],
    *,
    stream_output: bool = True,
) -> int:
    """Repair the given packages without touching their dependencies.

    For each package: deletes any stray shadowing directories first (this is
    the *only* thing that fixes the ``(unknown location)`` namespace-shadow
    failure mode), then runs ``uv pip install --reinstall-package X X==<ver>``
    so uv refreshes the wheel — bypassing the cache copy if it's corrupted —
    without re-resolving the rest of the graph. The version is pinned to what's
    already installed so a repair never upgrades a package out from under a
    sibling's exact pin. Torch and friends stay put.

    Falls back to ``pip install --force-reinstall --no-deps`` when uv is
    unavailable.
    """
    if not packages:
        return 0

    names = [pkg.name for pkg in packages]

    # Read installed versions BEFORE deleting stray dirs (and before uv touches
    # anything) so we can pin the reinstall to the exact version already on
    # disk. Without a pin, uv re-resolves the named requirement to the latest
    # release, which can violate an exact pin held by an already-installed
    # sibling (e.g. pydantic requires pydantic-core==X; an unpinned reinstall
    # pulls X+1 and breaks pydantic). A repair must restore, never upgrade.
    #
    # A pass may also set ``target_version`` when the installed version is
    # itself the problem (the version-guard case); that takes precedence over
    # the on-disk version.
    versions = _installed_versions(python_exe, names)
    requirements: list[str] = []
    unpinned: list[str] = []
    for pkg in packages:
        pin = pkg.target_version or versions.get(pkg.name)
        if pin:
            requirements.append(f"{pkg.name}=={pin}")
        else:
            requirements.append(pkg.name)
            unpinned.append(pkg.name)
    if unpinned:
        print(
            "  Note: could not determine installed version for "
            + ", ".join(unpinned)
            + " — reinstalling unpinned."
        )

    all_stray: list[str] = []
    for pkg in packages:
        all_stray.extend(pkg.stray_dirs)
    if all_stray:
        print(f"Removing {len(all_stray)} stray directory(ies) before reinstall...")
        _delete_stray_dirs(all_stray)

    if ensure_uv(python_exe, stream_output=stream_output):
        cmd = [python_exe, "-m", "uv", "pip", "install", "--python", python_exe]
        for name in names:
            cmd.extend(["--reinstall-package", name])
        cmd.extend(requirements)
        label = "uv pip install --reinstall-package " + " ".join(requirements)
    else:
        cmd = [
            python_exe, "-m", "pip", "install",
            "--force-reinstall", "--no-deps",
            *requirements,
        ]
        label = "pip install --force-reinstall --no-deps " + " ".join(requirements)

    print(f"  {label}")
    return _run(cmd, stream_output=stream_output)

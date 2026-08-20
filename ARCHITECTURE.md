# Architecture — ComfyUI Deployer

Describes the **current state** of the project: module map, key concepts,
invariants and pitfalls. Serves as the entry point so the whole codebase doesn't
have to be re-read on every intervention. Keep it up to date (see `CLAUDE.md`).

## Overview

A PyQt6 desktop application (Windows only) that manages the installation, update
and export ("bundle") of a portable ComfyUI install and its custom nodes.
~11,300 lines of Python across 66 files.

Three uses coexist in the same tool:
1. **Custom-node manager** — card grid, install/update/remove, detection of
   "orphan" nodes (installed but not tracked).
2. **Bundle creator** — exports either a self-installing `.bat` (small, clones
   everything on the recipient's machine) or a full portable folder (heavy, can
   include models).
3. **Plugin system** — adds custom steps to the bundle lifecycle (e.g. copying
   models from a shared folder) and custom buttons to the main window.

## Stack and environment

- Python 3.13, PyQt6.
- Git CLI (subprocess) for all node cloning/versioning.
- `uv` preferred over `pip` (falls back to pip when absent).
- 7-Zip (subprocess) to extract the ComfyUI portable archive.
- Runs on ComfyUI's embedded Python
  (`ComfyUI_windows_portable/python_embeded/python.exe`), not a separate venv.
- `ComfyUI_windows_portable/` is vendored third-party code and gitignored — it
  is not part of this project's source.

## Module map

```
main.py                          Entry point, adds deployer/ to the path
CLAUDE.md                        Project instructions (ARCHITECTURE.md rule)
deployer/
  config.py                      Path constants + GitLab resolution (.env)
  settings.py                    UserSettings — reads/writes user_settings.json
  core/                          Pure business logic (NO Qt import)
    node.py                      CustomNode — a node's model (clone/update/ref)
    git_ops.py                   Subprocess wrappers around `git`
    command_runner.py            stream_command() — run a process, stream its output line by line
    installer.py                 Orchestrates node install + requirements
    orphans.py                   Detects untracked custom_nodes directories
    workflow_io.py               Extracts the workflow graph (JSON or PNG/WebP/JPEG image)
    workflow_resolver.py         Resolves missing node types → repos (ComfyUI-Manager DB)
    package_repair.py            5 diagnostic passes + pip package repair
    junctions.py                 Windows junctions (external models/output/input)
    pip_runner.py                uv/pip wrapper
    http.py                      Download with PowerShell fallback (broken SSL)
    filesystem.py                shutil.rmtree read-only helper
    comfy_runner.py              Starts/stops the ComfyUI subprocess
    comfy_update.py              Runs ComfyUI's update_comfyui.bat, preserving the junctions
  bundle/                        Export generation (folder or .bat)
    builder.py                   create_bundle() — folder-bundle orchestrator
    bat_exporter.py              create_sharable_bat() — generates the self-installing .bat
    headless_install.py          What the .bat runs on the recipient's side (no Qt)
    comfyui_archive.py           Downloads/extracts the ComfyUI portable archive
    node_cloner.py               Clones nodes into the bundle + requirements
    model_copier.py              Selective copy of referenced models
    project_copier.py            Clones the Deployer itself into the bundle
    workflow_parser.py           Extracts node types + model refs from a workflow
  plugins/                       Extension system (bundle lifecycle + main window)
    api.py                       Bundle contract (BundleStep, StepContext, StepPhase) — zero PyQt
    actions.py                   UI contract (UiAction, CommandAction, ActionContext) — zero PyQt
    registry.py                  Discovery/loading (builtin, local, remote) of steps + actions
    runner.py                    Runs the configured steps for a given phase
    builtin/                     Empty by design (infrastructure provided, no opinionated steps)
    examples/                    Reference plugin, never auto-loaded
  ui/
    app.py                       Main window — the central hub
    plugin_actions.py            PluginActionBar — renders plugin UiActions as buttons / menu entries
    controllers/                 Testable logic extracted from app.py (install_planner, workflow_resolution)
    dialogs/                     Modal windows
    widgets/                     Cards, grid, busy button, spinner, console
    theme/                       Centralised palette + Qt stylesheets
plugins/                         Local plugins (gitignored except README + example)
```

## Key concepts

### `CustomNode` (core/node.py)
A node's model: `repo`, `ref`, `description`. Detects on its own whether the repo
is a GitLab one (via `.env`: `GITLAB_URL`/`GITLAB_SSH`) to pick HTTPS vs SSH when
cloning. `is_installed` is computed at construction time **from disk**, not from
the settings.

### `user_settings.json` (settings.py)
Schema:
`{"nodes": [...], "settings": {...}, "steps": [...], "plugins": {"remote": [...]}}`.

Each section has its own read/write accessors that **preserve the other keys**
(`save_nodes` never touches `settings`, and so on). The file is gitignored and
created on first launch from `custom_nodes.json` (static fallback) or from the
legacy GitLab manifest (`SOURCE_NODES_JSON`, see *Legacy*).

### Card states (ui/widgets/card_state.py)
`CardState` is a **9-value** enum, each mapped to
`(stylesheet, badge_text, badge_stylesheet)` in a table — this avoids the
cascades of `if is_selected and is_installed: ...` in every widget. `NodeCard`
and `OrphanNodeCard` share everything through `BaseCard` and only diverge on
`_build_body` / `_current_state`.

### Install plan (ui/controllers/install_planner.py)
`plan_install(node_cards, orphan_cards) -> InstallPlan` translates card state
into concrete actions (`to_install`, `to_uninstall`, `to_update`,
`with_requirements`, `selected_orphans`). Executed in this **specific order** by
`app.py._execute_plan`: uninstall → ref update → install → orphan promotion.
Extracted from `app.py` so it stays testable without Qt.

### Bundle pipeline (bundle/builder.py → create_bundle)
Sequential steps: clone the Deployer (if requested) → download/extract a clean
ComfyUI → copy `extra_model_paths.yaml` → clone the selected nodes → clone the
workflow-resolved nodes → install requirements → reset input/output → copy models
(if requested) → run the plugins' CREATE steps → generate the bundle's
`user_settings.json` → copy the workflows.

The `.bat` mode (bat_exporter.py) performs **no heavy local build**: it generates
a script that reproduces all of the above on the recipient's machine via
`headless_install.py`, with settings/plugins/workflows embedded as base64
(chunked to stay under `cmd`'s line limit).

**Models are never embedded in a `.bat`** — deliberate, they're far too heavy.

### Workflow resolution (core/workflow_resolver.py)
Extracts a workflow's `node.type` values, drops the built-ins (scan of `nodes.py`
/ `comfy_extras`) and the already-installed nodes, then queries the
ComfyUI-Manager DB (`extension-node-map.json` + `custom-node-list.json`, always
re-downloaded, falling back to the local cache when offline). Returns 3
categories: `resolved` (a single candidate repo, auto-added), `conflicts`
(several repos → picker dialog), `unresolved` (not found in the DB).

### ComfyUI update (core/comfy_update.py)
"Update ComfyUI..." in the hamburger menu runs the portable's own
`update/update_comfyui.bat` (with a dummy argument, so its trailing `pause`
doesn't hang the pipe). That script stashes ComfyUI's working tree and checks
`master` back out — and since `models/`, `output/` and `input/` are *tracked*
directories in the ComfyUI repo, the checkout destroys the junctions placed
there. `update_comfyui()` therefore snapshots the junction targets **from disk**
(`read_junction_target`, not `user_settings.json`, so hand-made junctions are
covered too), detaches them before launching the updater — otherwise git writes
its `put_*_here` placeholders straight into the user's external folders — and
re-creates them in a `finally`, replacing the placeholder directories the
checkout left behind.

### Package repair (core/package_repair.py — the largest file)
5 complementary passes to diagnose a broken `python_embeded`:
1. `uv pip check` — declared dependency conflicts.
2. File integrity — each wheel's RECORD vs the actual files on disk.
3. Import probe — imports every module, detects empty namespace packages.
4. Shadow scan — empty directories in `ComfyUI/` and `custom_nodes/` that shadow
   an installed pip package (they come before site-packages on `sys.path`).
5. Startup probe — reproduces ComfyUI's runtime `sys.path` *exactly* (including
   after running each node's `prestartup_script.py`) to catch shadows injected at
   runtime.

`CRITICAL_PACKAGES` (torch, xformers, triton…) are **unchecked by default** in
the UI: reinstalling them can break the bundle's CUDA build.

### Plugin system (deployer/plugins/)
A plugin is a `.py` module exposing `register(registry)` (or an auto-detected
`BundleStep` / `UiAction` subclass). Discovered in 3 locations: `builtin/`
(empty by design), `<root>/plugins/` (local, private),
`<root>/plugins/remote/<name>/` (cloned git repos).

A plugin contributes two independent kinds of thing, held in the same registry:

* **Bundle steps** (`api.py`) — a step declares its `phase` (CREATE = author's
  machine / INSTALL = recipient's machine) and its `bundle_formats`
  (BAT/FOLDER/BOTH), and is persisted per-bundle in `user_settings.json`
  under `steps`.
* **UI actions** (`actions.py`) — a `UiAction` becomes a button in the main
  window's bottom row (`ActionLocation.TOOLBAR`) or an entry in the hamburger
  menu (`ActionLocation.MENU`), and runs a custom command against the *local*
  install. `CommandAction` is the declarative shortcut: a `command` string (or
  argv list) and a `cwd_key` naming an `ActionContext` path, no `run()` needed.
  Nothing about actions is persisted — the registry is the single source of
  truth, so the buttons follow whatever plugins are on disk.

Local plugins travel into bundles through an **explicit copy** (folder) or an
**embedded base64 tar** (`.bat`), not through the Deployer's git clone — so a
plugin's buttons show up in the recipient's deployer too.

`ui/plugin_actions.py` (`PluginActionBar`) is the **only** module that knows
both the action contract and Qt. It builds the widgets, runs each action on a
worker thread by default (`background = True`), and reports a raised exception
to the console instead of letting it kill the app. It is rebuilt on three
events: startup, the end of the background remote-plugin sync, and the closing
of the Manage Plugins dialog.

An action's enabled state is computed in one place (`_apply_enabled`) from two
inputs: it is running, or the window is busy *and* the action declares
`blocked_when_busy` (the default — an action that only reads, like opening a
folder, opts out and stays clickable during an install).

## Invariants not to break

- `deployer/core/` and `deployer/ui/controllers/` **never import PyQt**. That is
  what lets `headless_install.py` run without Qt and keeps these modules
  testable.
- A plugin **never imports PyQt at module level** — lazy-import inside
  `build_widget()` only. A `UiAction` never imports PyQt *at all*: rendering it
  is `ui/plugin_actions.py`'s job.
- `UserSettings` accessors preserve the keys they don't own.
- `plugins/` is gitignored **except** `README.md`,
  `example_copy_models_from_root.py` and `example_ui_actions.py`. The
  `.gitignore` uses `plugins/*` (not `plugins/`) because git cannot re-include
  a file whose parent directory is excluded.

## Legacy: dual GitLab / GitHub surface

`config.py` and `core/node.py` carry GitLab logic (`GITLAB_URL`, `GITLAB_SSH`,
`GITLAB_ROOT`, resolution via `.gitconfig`) inherited from earlier in-company
usage, alongside the public GitHub/ComfyUI-Manager flow. It isn't broken
(`is_gitlab_repo` switches cleanly between HTTPS/SSH), but it explains why
`config.py` holds paths that look out of place for a general-purpose tool
(`COMFY_UI_SOURCE_DIR`, `SOURCE_NODES_JSON`).

**To decide**: keep this mode and document it as an "optional enterprise mode",
or drop it for the public version.

## Known limitation (also documented in README.md)

Resolving model paths through `extra_model_paths.yaml` is not taken into account
during bundle creation — only `MODELS_DIR` (the local junction) is used to locate
the referenced model files.

## Improvement leads

- **Decide the fate of the legacy GitLab mode** (keep/document/remove).
- **Unit tests** for `core/` and `ui/controllers/`: they are already written
  without a Qt dependency, so they're testable as-is (`plan_install`,
  `resolve_workflows`, `workflow_resolver`, `node.py`). The project currently has
  no tests at all.
- **`deployer/plugins/builtin/` is still empty.** Now that a plugin can also
  contribute buttons, a couple of obviously-useful ones (open the ComfyUI
  folder, open the log) would be candidates — at the cost of the "no
  opinionated steps shipped" stance.
- **Duplicated repo-URL-to-directory-name computation**:
  `os.path.basename(repo.rstrip("/").removesuffix(".git"))` is rewritten
  identically in `bundle/builder.py`, `bundle/bat_exporter.py` (×2),
  `bundle/headless_install.py` and `core/orphans.py` (as the `_canonical_url`
  variant). `deployer.plugins.repo_dir_name` does exactly this and is now public —
  those call sites could use it.
- **`ui/app.py` is ~1,490 lines** and concentrates a lot of responsibilities (grid,
  threads, workflow resolution, bundling, config I/O). Both controllers have
  already been extracted; the move could continue if the file becomes painful to
  evolve.
- Implement `extra_model_paths.yaml` resolution during bundle creation.

## Audit history

**2026-08-20 — full audit + cleanup.** Complete read of the codebase. No
functional bug found; the architecture was judged sound (clean
core/bundle/ui/plugins separation, careful docstrings, Windows edge cases well
handled). Fixed in the same pass:

- removed `GENERATION_MODELS_DIR` and `COMFY_RESOURCES_OUTPUT` (the latter held a
  hardcoded personal disk path), both unused;
- removed `CardState.ERROR` (never triggered) and the two styles it left dead,
  `NODE_CARD_ERROR_STYLE` / `BADGE_ERROR_STYLE`. The palette's `ERROR_*` tokens
  were kept: they serve the repair dialog and form a symmetric set with the other
  accents;
- APIs made public because they were used outside their module:
  `_repo_dir_name` → `repo_dir_name` (exported from `deployer.plugins`),
  `_run` → `run_command`, `_uv_available` → `uv_available`;
- fixed `create_bundle.py` docstrings ("4-step" → the actual 5 steps);
- resolved the `plugins/` contradiction: the `.gitignore` now spells out which
  files are tracked, and `plugins/README.md` plus the example's header no longer
  claim the folder is committed;
- fixed the `ComfyUi` → `ComfyUI` casing typo in `.vscode/launch.json` (local).

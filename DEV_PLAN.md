# Plugin System — Dev Plan

## Context

Adding a plugin system to ComfyUI Deployer that lets users define custom bundle
install steps (e.g. copy models from a root folder). Plugins can be local files
(gitignored, private) or remote git repos (GitHub/GitLab).

Branch: `plugin`

---

## DONE ✅

### 1. Plugin infrastructure (`deployer/plugins/`)
- [x] `api.py` — `BundleStep`, `StepContext`, `StepPhase` (CREATE / INSTALL / BOTH), no Qt dependency
- [x] `registry.py` — `PluginRegistry` + global `registry` + `load_plugins()` discovering `.py` in `deployer/plugins/builtin/` and `<root>/plugins/`
- [x] `runner.py` — `run_steps(steps, ctx)` shared by builder and headless install
- [x] `__init__.py` — public API re-exports
- [x] `builtin/__init__.py` — empty builtin dir (infrastructure ships without opinionated steps)
- [x] `examples/copy_models_from_root.py` — full reference plugin (not auto-loaded)

### 2. Persistence (`deployer/settings.py`)
- [x] Added `"steps"` key to `user_settings.json` schema
- [x] `UserSettings.load_steps()` method

### 3. Bundle execution

#### Folder bundle (`deployer/bundle/builder.py`)
- [x] `steps` param added to `create_bundle()`
- [x] CREATE-phase steps run after Step 6 (models), on the author's machine
- [x] Steps persisted via `write_bundle_user_settings(..., steps)`

#### Headless install / .bat (`deployer/bundle/headless_install.py`)
- [x] INSTALL-phase steps run after junctions, on the recipient's machine
- [x] `load_plugins()` called before `run_steps()`

#### .bat exporter (`deployer/bundle/bat_exporter.py`)
- [x] `steps` param added to `create_sharable_bat()`
- [x] Steps embedded in `user_settings.json` base64 blob

#### Bundle user settings (`deployer/bundle/project_copier.py`)
- [x] `write_bundle_user_settings(..., steps)` — writes steps alongside nodes

### 4. Create Bundle dialog — step 5 (basic version)
- [x] 5th page "Install steps (optional)" added to wizard
- [x] `_STEP_TITLES` updated, `_NUM_STEPS = 5`
- [x] `_OPTIONS_PAGE = 3`, `_STEPS_PAGE = 4` constants
- [x] "＋ Add step" button opens QMenu with registered plugins
- [x] Dynamic step rows: header + description + config widget + remove button
- [x] `STEP_CARD_STYLE` added to `deployer/ui/theme/stylesheets.py`
- [x] `_validate_steps()` blocks Create if a step config is invalid
- [x] `steps()` accessor returns `[{"id", "config"}, ...]`

### 5. App wiring (`deployer/ui/app.py`)
- [x] `steps` passed through `_on_create_bundle` → thread args
- [x] `steps` forwarded through `_resolve_workflows_for_bundle` signal payload
- [x] `steps` passed to `_run_create_bundle` and `_run_create_sharable_bat`

### 6. Drop-in `plugins/` folder at repo root
- [x] `plugins/` created and added to `.gitignore`
- [x] `plugins/example_copy_models_from_root.py` — fully commented, disabled by default
- [x] `plugins/README.md`

### 7. Main README updated
- [x] Create Bundle wizard description updated (4-step → 5-step)
- [x] "Plugins" section added with API example, phase table, Qt import warning

---

## TODO ❌

### A. Embed local plugins in the bundle (plugins/ is gitignored → must travel with bundle)

#### A1. `.bat` export
- [x] `_collect_local_plugins(plugin_dir)` — returns sorted list of user `.py` files
- [x] `_build_plugins_tarball_b64(plugin_paths)` — packs them into a tar, base64-encoded
- [x] `plugins_b64` param added to `_render_bat()`
- [x] Bat extracts `plugins.tar` → `plugins/` before `headless_install`
- [x] `create_sharable_bat` scans `plugins/`, builds tarball, passes to `_render_bat`

#### A2. Folder bundle
- [x] `_copy_local_plugins(dest_dir)` helper in `builder.py`
- [x] Called in Step 0b after `clone_deployer_into_bundle` (only when `include_debugger=True`)
- [x] Skips silently if `plugins/` is absent or empty

---

### B. Remote plugin management

#### B1. Persistence
- [x] `"plugins": {"remote": [...]}` added to `user_settings.json` schema docstring
- [x] `UserSettings.load_plugin_repos()` — returns list of `{"repo", "ref"}` dicts
- [x] `UserSettings.save_plugin_repos()` — updates the key, preserves all other keys

#### B2. Clone/sync remote plugins
- [x] `_REMOTE_DIR = plugins/remote/` constant in `registry.py`
- [x] `sync_remote_plugins(repos, *, log)` — clones missing repos, skips present ones, returns `{name: "ok"|"skipped"|"error:..."}` status dict
- [x] `load_plugins()` extended to scan each `plugins/remote/*/` subdir
- [x] `sync_remote_plugins` exported from `deployer/plugins/__init__.py`
- [ ] Called at app startup (after the window is shown, non-blocking thread) — done in B4

#### B3. Plugin management dialog (`deployer/ui/dialogs/manage_plugins.py`)
- [x] `_CloneWorker(QThread)` — clones a remote repo in background, emits `done(status)`
- [x] `_UpdateWorker(QThread)` — git pull in background, emits `done(status)`
- [x] `_AddPluginDialog` — sub-dialog: URL + ref → returns `values()`
- [x] `ManagePluginsDialog` — scrollable list: local cards (filename + badge) + remote cards (name, repo, ref, Update + Remove buttons)
- [x] Clone: persists immediately, rolls back on failure, reloads registry on success
- [x] Remove: deletes dir, updates saved list, reloads registry
- [x] Update: git pull via `_UpdateWorker`, reloads registry
- [x] `git_ops.pull()` added
- [x] Exported from `deployer/ui/dialogs/__init__.py`

#### B4. Hamburger menu entry + startup sync
- [x] `QAction "Manage Plugins..."` added to hamburger menu in `app.py`
- [x] `_on_manage_plugins()` handler opens `ManagePluginsDialog`
- [x] `showEvent` defers `_sync_remote_plugins_bg()` via `QTimer.singleShot(0, ...)`
- [x] `_do_sync_remote_plugins(repos)` runs in daemon thread: `sync_remote_plugins` + `load_plugins(force=True)`

---

### C. Create Bundle step 5 — redesign with plugin selector + step configurator

#### C1. Plugin selector (top)
- [x] Lists all installed plugins (local + remote) with a checkbox each
- [x] Default: all checked
- [x] `_refresh_plugins_section()` rebuilds on every visit, preserving checked state
- [x] Plugin rows show: name, source badge (local/remote)

#### C2. Step configurator (bottom)
- [x] "Add step" menu shows registered steps
- [x] Dynamic step rows: header + description + config widget + remove button

#### C3. `plugin_repos()` accessor
- [x] Returns checked remote plugin repos as `[{"repo", "ref"}, ...]`
  so the export layer knows which repos to clone

---

### D. Bundle export with remote plugins

#### D1. `.bat` export
- [x] `plugin_repos` param added to `create_sharable_bat()`
- [x] Remote plugin repos serialized into `user_settings.json` blob under `"plugins": {"remote": [...]}`
- [x] `headless_install` picks them up via `sync_remote_plugins` (D3)

#### D2. Folder bundle
- [x] `_clone_remote_plugins(dest_dir, plugin_repos)` helper in `builder.py` (Step 0c)
- [x] `plugin_repos` param added to `create_bundle()`; repos cloned in Step 0c
- [x] `plugin_repos` passed to `write_bundle_user_settings()` → persisted in bundle's `user_settings.json`
- [x] `write_bundle_user_settings()` in `project_copier.py` accepts and persists `plugin_repos`
- [x] Local `plugins/*.py` copied in Step 0b (task A2)

#### D3. Headless install update
- [x] Before `load_plugins()`, clone any missing remote plugin repos from
  `user_settings.json["plugins"]["remote"]`
- [x] Reuses `sync_remote_plugins()` from task B2

#### D4. App wiring
- [x] `plugin_repos = dialog.plugin_repos()` read in `_on_create_bundle()`
- [x] Passed through `_resolve_workflows_for_bundle` signal payload
- [x] Forwarded to `_run_create_bundle()` and `_run_create_sharable_bat()`

---

### E. Polish / edge cases
- [ ] Handle case where a remote plugin fails to clone (warn, continue)
- [ ] Handle case where a plugin's `register()` raises (already isolated in `_discover_dir`, verify)
- [ ] Show plugin load errors in the management dialog
- [ ] README: update with remote plugins and management screen

---

## File map

```
deployer/
  plugins/
    __init__.py          ✅ done
    api.py               ✅ done
    registry.py          ✅ done  (needs: remote dir scan, sync_remote_plugins)
    runner.py            ✅ done
    builtin/
      __init__.py        ✅ done
    examples/
      copy_models_from_root.py  ✅ done (reference only)

  bundle/
    builder.py           ✅ done  (needs: local plugin copy, remote plugin clone)
    bat_exporter.py      ✅ done  (needs: embed local .py, remote plugin repo list)
    headless_install.py  ✅ done  (needs: sync_remote_plugins before load_plugins)
    project_copier.py    ✅ done

  settings.py            ✅ done  (needs: load/save plugin repos)

  ui/
    app.py               ✅ done  (needs: Manage Plugins menu entry)
    dialogs/
      create_bundle.py   ✅ done  (needs: C1 plugin selector redesign)
      manage_plugins.py  ❌ to create
    theme/
      stylesheets.py     ✅ done

plugins/                 ✅ created (gitignored)
  README.md              ✅ done
  example_copy_models_from_root.py  ✅ done
```

---

## Implementation order (recommended)

1. **A** — local plugin embedding (unblocks usable bundles with local plugins)
2. **B1 + B2** — persistence + sync (foundation for everything remote)
3. **B3 + B4** — management dialog (UX for remote plugins)
4. **C** — step 5 redesign (plugin selector + filtered steps)
5. **D** — bundle export with remote plugins
6. **E** — polish

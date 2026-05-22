# ComfyUI Deployer

A desktop app for managing custom nodes/intalls for [ComfyUI](https://github.com/Comfy-Org/ComfyUI/). 
It allow to : 
- Install custom nodes from any versions, commit or branch
- Create and export custom nodes configuration 
- Packages the configuration into a self-contained portable bundle.
- Create a bundle from a comfyUi workflow. 
- Update configuration from a ComfyUi workflow

![Main window](docs/screenshots/main_window.png)

## Features

- **Visual node management** — each tracked node is shown as a card with its name, git ref, description, and a "Install requirements" toggle. Click a card to mark it for install / uninstall; cards turn orange when the ref drifts from what's on disk and need a re-checkout. Double click on ref allow you to change the custom node version.
- **Orphan detection** — custom nodes installed inside `ComfyUI/custom_nodes/` but not present in configuration show up as orphan cards. Select them to promote them into the tracked list.
- **Add from workflow** — point the app at a ComfyUI workflow JSON. It diffs the workflow's node types against built-in nodes + currently installed custom nodes, and resolves the rest against the ComfyUI-Manager DB. Ambiguous types are surfaced via a conflict dialog.
- **Bundle export** — package a clean portable ComfyUI with only the custom nodes and models referenced by selected workflows (or everything currently installed). Missing nodes are auto-cloned into the bundle so it boots without any extra setup.
- **Run ComfyUI** — start/stop the bundled ComfyUI subprocess from the app, with stdout/stderr piped into an integrated console panel.

## Quick start

1. Clone this repo into the folder where you want ComfyUI deployed.
2. Make sure [7-Zip](https://www.7-zip.org/) is installed.
3. Double-click **`Launch.bat`**. The script will:
   - Download `ComfyUI_windows_portable_nvidia.7z` from the official release page and extract it next to the script (on first run).
   - Install python requirement into the bundled `python_embeded` if needed.
   - Launch the deployer.

The app use the bundled Python used by comfyUI under (`ComfyUI_windows_portable/python_embeded/python.exe`)

## Usage

### Tracking nodes

The main window lists every node in `user_settings.json` plus any orphan installed nodes (under custom_nodes folder from ComfyUI). Click a card to toggle install/uninstall, double-click the ref or description to edit them inline, and right-click for the "Remove from list" action or be redirected to the node repository.

![Card states](docs/screenshots/card_states.png)

The hamburger menu (top-left) hosts the entry points for everything else:

![Hamburger menu](docs/screenshots/hamburger_menu.png)

Add nodes from the `+` button

![Card states](docs/screenshots/add_menu.png)

### Adding nodes from a workflow

`☰ → Add from workflow...` parses a ComfyUI workflow JSON, drops the built-in / already-installed node types, then queries the ComfyUI-Manager DB for the rest. Unambiguous matches are added as orphan cards automatically; types satisfied by multiple repos pop up a conflict picker:

![Workflow conflict dialog](docs/screenshots/workflow_conflict.png)

### Creating a portable bundle

`☰ → Create Bundle...` opens the bundle dialog. Pick a destination folder; optionally pick one or more workflow JSONs to trim the bundle to only what they need (custom nodes **and** models). When workflow files are provided, missing nodes are resolved against the ComfyUI-Manager DB and cloned directly into the bundle's `custom_nodes/`, so the resulting bundle is self-contained.

![Create bundle dialog](docs/screenshots/create_bundle.png)

**Export as sharable `.bat` file** — instead of building a (potentially multi-gigabyte) bundle locally, this writes a single self-contained `install_comfyui_bundle.bat`. When the recipient double-clicks it, the script clones the ComfyUI Deployer, downloads the matching ComfyUI portable, installs `PyQt6` / `pyyaml` / `uv` into the embedded python, recreates `user_settings.json`, then clones the selected custom nodes and installs their requirements. **Models are never included** (too heavy). Tick **Export advanced settings** to also embed `extra_model_paths.yaml` and the advanced folder settings, so an external model library can be wired up on the target machine.


### Advanced settings

`☰ → Advanced settings...` lets you point ComfyUI at external folders for models, output, input, or an `extra_model_paths.yaml`. The settings are written into the `settings` subdict of `user_settings.json` and applied as junctions inside `ComfyUI/`.

![Advanced settings](docs/screenshots/advanced_settings.png)

## Configuration files

- **`user_settings.json`** (auto-created) — the tracked node list and the folder overrides set in Advanced Settings. See [`deployer/settings.py`](deployer/settings.py) for the schema.
- **`.env`** (optional) — used to configure GitLab cloning and the local "GitLab root" (the parent folder where sibling repos live). Supported keys:
  - `GITLAB_URL`, `GITLAB_SSH` — HTTPS / SSH prefixes used when cloning private GitLab nodes.
  - `GITLAB_ROOT` — direct path to the GitLab root folder. Simplest setup; takes precedence over the gitconfig lookup below.
  - `GITCONFIG_PATH` (defaults to `~/.gitconfig`), `GITCONFIG_SECTION`, `GITCONFIG_KEY` — read the GitLab root from a gitconfig-style ini file. Useful when the path is already declared in `~/.gitconfig` for other tooling. Both `GITCONFIG_SECTION` and `GITCONFIG_KEY` must be set for this branch to activate.

  Resolution order for the GitLab root: `GITLAB_ROOT` → gitconfig lookup → fallback to `ComfyUI/custom_nodes/`.

  Example `~/.gitconfig` entry consumed by the gitconfig branch:

  ```ini
  [MySection]
      gitroot = D:/Gitlab
  ```

  (with `GITCONFIG_SECTION=MySection` and `GITCONFIG_KEY=gitroot` in `.env`)
- **`custom_nodes.json`** (optional) — a static fallback node list used when `user_settings.json` is missing.


## Know issues

- Resolving the model path from `extra_model_paths.yaml` is not taken into account for bundle creation.
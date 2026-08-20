# Project instructions — ComfyUI Deployer

## Rule #1: ARCHITECTURE.md

**At the start of every request, read [`ARCHITECTURE.md`](ARCHITECTURE.md)
before exploring the code.** It holds the module map, the key concepts, the
invariants and the known pitfalls. It exists so the whole codebase doesn't have
to be re-read on every request — always start there to get your bearings.

**Update it as soon as a change makes it inaccurate.** Concretely, after any
change, ask whether one of these has moved:

- a module was added, removed, renamed or relocated → module map;
- a key concept changed behaviour (`user_settings.json` schema, card states,
  bundle pipeline, plugin phases, repair passes);
- a public API was renamed or its contract changed;
- an invariant / pitfall was introduced or lifted;
- an item listed under "Findings" or "Improvement leads" was addressed.

Don't turn it into a changelog: it describes the **current state** of the
project, not the history of changes — that's git's job. If nothing structural
moved, leave it alone.

## Runtime context

- **Windows only.** NTFS junctions, `.bat` scripts, `D:\...` paths.
- The code runs on **ComfyUI's embedded Python**
  (`ComfyUI_windows_portable/python_embeded/python.exe`), not a venv. That's the
  interpreter to use when testing anything.
- `ComfyUI_windows_portable/` is **vendored third-party code** (downloaded by
  `Launch.bat`) and gitignored: never audit or modify it.

## Code conventions

- `deployer/core/` and `deployer/ui/controllers/` must **never import PyQt** —
  that's what keeps them testable and usable by the headless install path. Qt
  stays confined to `deployer/ui/`.
- A plugin must **never import PyQt at module level**: lazy-import it inside
  `build_widget()` only. `headless_install.py` loads plugins without Qt
  available.
- Colors and Qt styles live in `deployer/ui/theme/` — no hardcoded color
  anywhere else.
- After any change, check at minimum that everything compiles and imports:
  `./ComfyUI_windows_portable/python_embeded/python.exe -m compileall -q deployer main.py`

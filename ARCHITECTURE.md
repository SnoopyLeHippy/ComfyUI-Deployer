# Architecture — ComfyUI Deployer

Décrit **l'état actuel** du projet : carte des modules, concepts clés,
invariants et pièges. Sert de point d'entrée pour ne pas avoir à relire tout le
codebase à chaque intervention. À maintenir à jour (voir `CLAUDE.md`).

## Vue d'ensemble

Application desktop PyQt6 (Windows uniquement) qui gère l'installation, la mise
à jour et l'export ("bundle") d'une installation portable de ComfyUI et de ses
custom nodes. ~10 300 lignes de Python réparties en 60 fichiers.

Trois usages coexistent dans le même outil :
1. **Gestionnaire de custom nodes** — grille de cartes, install/update/remove,
   détection des nodes « orphelins » (installés mais pas trackés).
2. **Créateur de bundle** — exporte soit un `.bat` auto-installant (léger, clone
   tout chez le destinataire), soit un dossier portable complet (lourd, peut
   inclure les modèles).
3. **Système de plugins** — ajoute des étapes personnalisées au cycle de vie du
   bundle (ex. copier des modèles depuis un dossier partagé).

## Stack et environnement

- Python 3.13, PyQt6.
- Git CLI (subprocess) pour tout le clonage/versioning des nodes.
- `uv` préféré à `pip` (fallback pip si absent).
- 7-Zip (subprocess) pour extraire l'archive portable ComfyUI.
- Tourne sur le Python embarqué de ComfyUI
  (`ComfyUI_windows_portable/python_embeded/python.exe`), pas un venv séparé.
- `ComfyUI_windows_portable/` est du code tiers vendorisé et gitignoré — ce
  n'est pas du code du projet.

## Carte des modules

```
main.py                          Point d'entrée, ajoute deployer/ au path
CLAUDE.md                        Instructions projet (règle ARCHITECTURE.md)
deployer/
  config.py                      Constantes de chemins + résolution GitLab (.env)
  settings.py                    UserSettings — lecture/écriture user_settings.json
  core/                          Logique métier pure (AUCUN import Qt)
    node.py                      CustomNode — modèle d'un node (clone/update/ref)
    git_ops.py                   Wrappers subprocess autour de `git`
    installer.py                 Orchestration install nodes + requirements
    orphans.py                   Détection des dossiers custom_nodes non trackés
    workflow_io.py               Extraction du graphe workflow (JSON ou image PNG/WebP/JPEG)
    workflow_resolver.py         Résout les node types manquants → repos (DB ComfyUI-Manager)
    package_repair.py            5 passes de diagnostic + réparation de paquets pip
    junctions.py                 Junctions Windows (modèles/output/input externalisés)
    pip_runner.py                Wrapper uv/pip
    http.py                      Téléchargement avec fallback PowerShell (SSL cassé)
    filesystem.py                Utilitaire shutil.rmtree read-only
    comfy_runner.py              Lance/arrête le sous-processus ComfyUI
  bundle/                        Génération des exports (dossier ou .bat)
    builder.py                   create_bundle() — orchestrateur du bundle dossier
    bat_exporter.py              create_sharable_bat() — génère le .bat auto-installant
    headless_install.py          Ce que le .bat exécute côté destinataire (sans Qt)
    comfyui_archive.py           Télécharge/extrait l'archive portable ComfyUI
    node_cloner.py               Clone les nodes dans le bundle + requirements
    model_copier.py              Copie sélective des modèles référencés
    project_copier.py            Clone le Deployer lui-même dans le bundle
    workflow_parser.py           Extrait node types + refs modèles d'un workflow
  plugins/                       Système d'extension du cycle de vie du bundle
    api.py                       Contrat public (BundleStep, StepContext, StepPhase) — zéro PyQt
    registry.py                  Découverte/chargement (builtin, local, remote)
    runner.py                    Exécute les steps configurées pour une phase donnée
    builtin/                     Vide par design (infra fournie, pas de steps imposées)
    examples/                    Plugin de référence, jamais auto-chargé
  ui/
    app.py                       Fenêtre principale (1360 lignes) — le hub central
    controllers/                 Logique testable extraite de app.py (install_planner, workflow_resolution)
    dialogs/                     Fenêtres modales
    widgets/                     Cartes, grille, bouton busy, spinner, console
    theme/                       Palette + stylesheets Qt centralisés
plugins/                         Plugins locaux (gitignoré sauf README + exemple)
```

## Concepts clés

### `CustomNode` (core/node.py)
Modèle d'un node : `repo`, `ref`, `description`. Détecte seul s'il s'agit d'un
repo GitLab (via `.env` : `GITLAB_URL`/`GITLAB_SSH`) pour choisir HTTPS vs SSH au
clone. `is_installed` est calculé à la construction **depuis le disque**, pas
depuis les settings.

### `user_settings.json` (settings.py)
Schéma :
`{"nodes": [...], "settings": {...}, "steps": [...], "plugins": {"remote": [...]}}`.

Chaque section a ses propres accesseurs read/write qui **préservent les autres
clés** (`save_nodes` ne touche pas à `settings`, etc.). Fichier gitignoré, créé
au premier lancement depuis `custom_nodes.json` (fallback statique) ou depuis le
manifest GitLab legacy (`SOURCE_NODES_JSON`, voir *Legacy*).

### États des cartes (ui/widgets/card_state.py)
`CardState` est une énumération de **9 valeurs**, chacune mappée à
`(stylesheet, badge_text, badge_stylesheet)` dans une table — ça évite les
cascades de `if is_selected and is_installed: ...` dans chaque widget.
`NodeCard` et `OrphanNodeCard` partagent tout via `BaseCard` et ne divergent que
sur `_build_body` / `_current_state`.

### Plan d'installation (ui/controllers/install_planner.py)
`plan_install(node_cards, orphan_cards) -> InstallPlan` traduit l'état des cartes
en actions concrètes (`to_install`, `to_uninstall`, `to_update`,
`with_requirements`, `selected_orphans`). Exécuté dans cet **ordre précis** par
`app.py._execute_plan` : uninstall → update ref → install → promotion des
orphelins. Extrait de `app.py` pour rester testable sans Qt.

### Pipeline de bundle (bundle/builder.py → create_bundle)
Étapes séquentielles : clone du Deployer (si demandé) → download/extract ComfyUI
propre → copie `extra_model_paths.yaml` → clone des nodes sélectionnés → clone
des nodes résolus par workflow → install requirements → reset input/output →
copie modèles (si demandé) → steps CREATE des plugins → génération du
`user_settings.json` du bundle → copie des workflows.

Le mode `.bat` (bat_exporter.py) ne fait **aucun build lourd local** : il génère
un script qui reproduit tout ça chez le destinataire via `headless_install.py`,
avec settings/plugins/workflows embarqués en base64 (chunké pour rester sous la
limite de ligne de `cmd`).

**Les modèles ne sont jamais embarqués dans un `.bat`** — volontaire, trop lourd.

### Résolution de workflow (core/workflow_resolver.py)
Extrait les `node.type` d'un workflow, retire les built-ins (scan de `nodes.py` /
`comfy_extras`) et les nodes déjà installés, puis interroge la DB ComfyUI-Manager
(`extension-node-map.json` + `custom-node-list.json`, toujours re-téléchargées,
fallback sur le cache local si offline). Retourne 3 catégories : `resolved` (1
seul repo candidat, auto-ajouté), `conflicts` (plusieurs repos → popup de choix),
`unresolved` (introuvable dans la DB).

### Package repair (core/package_repair.py — le plus gros fichier)
5 passes complémentaires pour diagnostiquer un `python_embeded` cassé :
1. `uv pip check` — conflits de dépendances déclarés.
2. Intégrité fichier — RECORD de chaque wheel vs fichiers réels sur disque.
3. Import probe — importe chaque module, détecte le namespace package vide.
4. Shadow scan — dossiers vides dans `ComfyUI/` et `custom_nodes/` masquant un
   package pip (ils passent avant site-packages dans `sys.path`).
5. Startup probe — reproduit *exactement* le `sys.path` runtime de ComfyUI (y
   compris après exécution des `prestartup_script.py`) pour détecter les shadows
   injectés dynamiquement.

`CRITICAL_PACKAGES` (torch, xformers, triton…) sont **décochés par défaut** dans
l'UI : les réinstaller peut casser le build CUDA du bundle.

### Système de plugins (deployer/plugins/)
Un plugin = un module `.py` exposant `register(registry)` (ou une sous-classe
`BundleStep` auto-détectée). Découverte dans 3 emplacements : `builtin/` (vide
par design), `<root>/plugins/` (local, privé), `<root>/plugins/remote/<name>/`
(repos git clonés). Une step déclare sa `phase` (CREATE = machine auteur /
INSTALL = machine destinataire) et son `bundle_formats` (BAT/FOLDER/BOTH).

Les plugins locaux voyagent dans les bundles par **copie explicite** (dossier) ou
**tar base64 embarqué** (`.bat`), pas via le clone git du Deployer.

## Invariants à ne pas casser

- `deployer/core/` et `deployer/ui/controllers/` **n'importent jamais PyQt**.
  C'est ce qui permet à `headless_install.py` de tourner sans Qt et rend ces
  modules testables.
- Un plugin **n'importe jamais PyQt au niveau module** — uniquement en import
  paresseux dans `build_widget()`.
- Les accesseurs de `UserSettings` préservent les clés qu'ils ne gèrent pas.
- `plugins/` est gitignoré **sauf** `README.md` et
  `example_copy_models_from_root.py`. Le `.gitignore` utilise `plugins/*` (et non
  `plugins/`) car git ne peut pas ré-inclure un fichier dont le dossier parent est
  exclu.

## Legacy : double surface GitLab / GitHub

`config.py` et `core/node.py` portent une logique GitLab (`GITLAB_URL`,
`GITLAB_SSH`, `GITLAB_ROOT`, résolution via `.gitconfig`) héritée d'un usage
antérieur en entreprise, à côté du flux public orienté GitHub/ComfyUI-Manager.
Ce n'est pas cassé (`is_gitlab_repo` bascule proprement HTTPS/SSH), mais ça
explique pourquoi `config.py` contient des chemins qui semblent hors-sujet pour
un outil grand public (`COMFY_UI_SOURCE_DIR`, `SOURCE_NODES_JSON`).

**À trancher** : garder ce mode et le documenter comme « mode entreprise
optionnel », ou le retirer pour la version publique.

## Limitation connue (aussi documentée dans README.md)

La résolution du chemin des modèles via `extra_model_paths.yaml` n'est pas prise
en compte lors de la création de bundle — seul `MODELS_DIR` (junction locale) est
utilisé pour retrouver les fichiers modèles référencés.

## Pistes d'amélioration

- **Trancher le sort du mode GitLab legacy** (garder/documenter/retirer).
- **Tests unitaires** sur `core/` et `ui/controllers/` : ils sont déjà écrits
  sans dépendance Qt, donc testables tels quels (`plan_install`,
  `resolve_workflows`, `workflow_resolver`, `node.py`). Le projet n'a
  actuellement aucun test.
- **Duplication du calcul de nom de dossier depuis une URL de repo** :
  `os.path.basename(repo.rstrip("/").removesuffix(".git"))` est réécrit à
  l'identique dans `bundle/builder.py`, `bundle/bat_exporter.py` (×2),
  `bundle/headless_install.py` et `core/orphans.py` (variante `_canonical_url`).
  `deployer.plugins.repo_dir_name` fait exactement ça et est désormais public —
  ces sites pourraient l'utiliser.
- **`ui/app.py` fait 1360 lignes** et concentre beaucoup de responsabilités
  (grille, threads, résolution workflow, bundle, config I/O). Les deux
  controllers ont déjà été extraits ; le mouvement pourrait continuer si le
  fichier devient pénible à faire évoluer.
- Implémenter la résolution `extra_model_paths.yaml` à la création de bundle.

## Historique des audits

**2026-08-20 — audit complet + nettoyage.** Lecture intégrale du codebase.
Aucun bug fonctionnel trouvé ; architecture jugée saine (séparation core/bundle/
ui/plugins nette, docstrings soignées, cas limites Windows bien gérés). Corrigé
dans la foulée :

- suppression de `GENERATION_MODELS_DIR` et `COMFY_RESOURCES_OUTPUT`
  (ce dernier contenait un chemin de disque personnel en dur), inutilisés ;
- suppression de `CardState.ERROR` (jamais déclenché) et des deux styles
  devenus morts `NODE_CARD_ERROR_STYLE` / `BADGE_ERROR_STYLE`. Les tokens
  `ERROR_*` de la palette sont conservés : ils servent au dialogue de réparation
  et forment un jeu symétrique avec les autres accents ;
- API rendues publiques car utilisées hors de leur module :
  `_repo_dir_name` → `repo_dir_name` (exporté depuis `deployer.plugins`),
  `_run` → `run_command`, `_uv_available` → `uv_available` ;
- docstrings de `create_bundle.py` corrigés (« 4-step » → 5 étapes réelles) ;
- contradiction `plugins/` résolue : le `.gitignore` explicite désormais quels
  fichiers sont trackés, et `plugins/README.md` + l'en-tête de l'exemple ne
  prétendent plus que le dossier est commité ;
- coquille de casse `ComfyUi` → `ComfyUI` dans `.vscode/launch.json` (local).

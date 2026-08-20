# Instructions projet — ComfyUI Deployer

## Règle n°1 : ARCHITECTURE.md

**Au début de chaque demande, lis [`ARCHITECTURE.md`](ARCHITECTURE.md) avant
d'explorer le code.** Il contient la carte des modules, les concepts clés, les
invariants et les pièges connus. Il est écrit pour éviter d'avoir à relire tout
le codebase à chaque requête — commence toujours par là pour te situer.

**Mets-le à jour dès qu'une modification le rend inexact.** Concrètement, après
tout changement, demande-toi si l'un de ces points a bougé :

- un module a été ajouté, supprimé, renommé ou déplacé → carte des modules ;
- un concept clé a changé de comportement (schéma `user_settings.json`, états
  de carte, pipeline de bundle, phases de plugin, passes de réparation) ;
- une API publique a été renommée ou son contrat modifié ;
- un invariant / piège a été introduit ou levé ;
- un point listé dans « Findings » ou « Pistes » a été traité.

Ne le transforme pas en journal de bord : on y décrit **l'état actuel** du
projet, pas l'historique des changements (c'est le rôle de git). Si rien de
structurel n'a bougé, ne le touche pas.

## Contexte d'exécution

- **Windows uniquement.** Junctions NTFS, `.bat`, chemins `D:\...`.
- Le code tourne sur le **Python embarqué de ComfyUI**
  (`ComfyUI_windows_portable/python_embeded/python.exe`), pas un venv.
  C'est cet interpréteur qu'il faut utiliser pour tester quoi que ce soit.
- `ComfyUI_windows_portable/` est du code **tiers vendorisé** (téléchargé par
  `Launch.bat`), gitignoré : ne jamais l'auditer ni le modifier.

## Conventions de code

- `deployer/core/` et `deployer/ui/controllers/` ne doivent **jamais importer
  PyQt** — c'est ce qui les rend testables et utilisables par le chemin
  d'installation headless. Qt reste confiné à `deployer/ui/`.
- Un plugin ne doit **jamais importer PyQt au niveau module** : uniquement en
  import paresseux dans `build_widget()`. `headless_install.py` charge les
  plugins sans Qt disponible.
- Les couleurs et styles Qt vivent dans `deployer/ui/theme/` — pas de couleur
  en dur ailleurs.
- Après modification, vérifier au minimum que tout compile et s'importe :
  `./ComfyUI_windows_portable/python_embeded/python.exe -m compileall -q deployer main.py`

"""Copy only the model files referenced by a workflow into the bundle."""

import os
import shutil


def copy_models_for_bundle(src_models: str, dst_models: str, model_filenames: set[str]) -> None:
    """Copy only the referenced model files / folders into *dst_models*.

    Three lookup strategies, in order:
    1. Exact relative path under *src_models* matching a file.
    2. Exact relative path matching a directory (HuggingFace-style models).
    3. Basename match against an index of every file and directory under
       *src_models*. The first match wins; multiple matches are reported.
    """
    print("  Indexing model files...")
    name_index: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(src_models):
        for fname in filenames:
            name_index.setdefault(fname, []).append(os.path.join(dirpath, fname))
        for dname in dirnames:
            name_index.setdefault(dname, []).append(os.path.join(dirpath, dname))

    for model_ref in sorted(model_filenames):
        model_name = os.path.basename(model_ref)

        # 1) Exact relative path (file)
        direct = os.path.join(src_models, model_ref)
        if os.path.isfile(direct):
            dst_file = os.path.join(dst_models, model_ref)
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            print(f"  Copying model: {model_ref}")
            shutil.copy2(direct, dst_file)
            continue

        # 2) Exact relative path (directory)
        if os.path.isdir(direct):
            dst_dir = os.path.join(dst_models, model_ref)
            os.makedirs(os.path.dirname(dst_dir), exist_ok=True)
            print(f"  Copying model dir: {model_ref}")
            shutil.copytree(direct, dst_dir, dirs_exist_ok=True)
            continue

        # 3) Search by name in the index
        candidates = name_index.get(model_name, [])
        if not candidates:
            print(f"  Model not found: {model_ref}")
            continue

        src_path = candidates[0]
        rel = os.path.relpath(src_path, src_models)
        dst_path = os.path.join(dst_models, rel)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        if os.path.isdir(src_path):
            print(f"  Copying model dir: {rel}")
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
        else:
            print(f"  Copying model: {rel}")
            shutil.copy2(src_path, dst_path)
        if len(candidates) > 1:
            print(f"    (multiple matches, used first: {rel})")

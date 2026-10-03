from __future__ import annotations

import shutil
from pathlib import Path

from scripts.publication.assembler import compute_tree_digest

RESULTS_DIR = "results"
SNAPSHOT_DIR = "data"


class ArtifactError(RuntimeError):
    pass


def verify_tree(tree: Path, expected_sha256: str) -> dict[str, str]:
    if not tree.is_dir():
        raise ArtifactError(f"artifact tree is missing: {tree}")
    digest, _, manifest = compute_tree_digest(tree)
    if digest != expected_sha256:
        raise ArtifactError(f"artifact digest {digest} does not match recorded {expected_sha256}")
    return manifest


def compose_ui_first(current_tree: Path, restored_tree: Path, destination: Path) -> str:
    for label, tree in (("current", current_tree), ("restored", restored_tree)):
        if not (tree / RESULTS_DIR).is_dir():
            raise ArtifactError(f"{label} artifact has no {RESULTS_DIR}/ tree")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(current_tree, destination)
    results = destination / RESULTS_DIR
    for entry in list(results.iterdir()):
        if entry.name == SNAPSHOT_DIR:
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    for entry in (restored_tree / RESULTS_DIR).iterdir():
        if entry.name == SNAPSHOT_DIR:
            continue
        if entry.is_dir():
            shutil.copytree(entry, results / entry.name)
        else:
            shutil.copy2(entry, results / entry.name)
    digest, _, _ = compute_tree_digest(destination)
    return digest

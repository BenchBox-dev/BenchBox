from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from scripts.publication.assembler import compute_file_sha256, compute_tree_digest

RESULTS_DIR = "results"
SNAPSHOT_DIR = "data"
RESULTS_FALLBACK = "404.html"
SNAPSHOT_FILE = f"{SNAPSHOT_DIR}/results.duckdb"


class ArtifactError(RuntimeError):
    pass


def verify_tree(tree: Path, expected_sha256: str) -> dict[str, str]:
    if not tree.is_dir():
        raise ArtifactError(f"artifact tree is missing: {tree}")
    digest, _, manifest = compute_tree_digest(tree)
    if digest != expected_sha256:
        raise ArtifactError(f"artifact digest {digest} does not match recorded {expected_sha256}")
    return manifest


def explorer_pins(explorer_tree: Path, scratch: Path, source_sha: str | None) -> dict[str, Any]:
    snapshot = explorer_tree / SNAPSHOT_FILE
    if not snapshot.is_file():
        raise ArtifactError(f"explorer tree has no snapshot to pin: {snapshot}")
    if scratch.exists():
        shutil.rmtree(scratch)
    shutil.copytree(
        explorer_tree,
        scratch,
        ignore=lambda directory, names: {SNAPSHOT_DIR} if Path(directory) == explorer_tree else set(),
    )
    ui_digest, _, _ = compute_tree_digest(scratch)
    shutil.rmtree(scratch)
    return {
        "ui": {"source_sha": source_sha, "sha256": ui_digest},
        "snapshot": {"path": SNAPSHOT_FILE, "sha256": compute_file_sha256(snapshot)},
    }


def compose_ui_first(current_tree: Path, restored_tree: Path, destination: Path) -> str:
    for label, tree in (("current", current_tree), ("restored", restored_tree)):
        if not (tree / RESULTS_DIR).is_dir():
            raise ArtifactError(f"{label} artifact has no {RESULTS_DIR}/ tree")
    if not (restored_tree / RESULTS_FALLBACK).is_file():
        raise ArtifactError(f"restored artifact has no {RESULTS_FALLBACK} deep-link fallback")
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
    shutil.copy2(restored_tree / RESULTS_FALLBACK, destination / RESULTS_FALLBACK)
    digest, _, _ = compute_tree_digest(destination)
    return digest

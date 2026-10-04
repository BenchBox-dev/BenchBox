from __future__ import annotations

from pathlib import Path

from scripts.publication.assembler import compute_tree_digest

SNAPSHOT_PATH = "/results/data/results.duckdb"
EXTRA_PATHS = ("/docs/api.html",)
SAMPLE_LIMIT = 25
SAMPLE_SUFFIXES = (".html", ".css", ".js", ".svg", ".json", ".xml")


def served_path(relative: str) -> str:
    if relative == "index.html":
        return "/"
    if relative.endswith("/index.html"):
        return "/" + relative[: -len("index.html")]
    return "/" + relative


def route_roots(route_paths: list[str]) -> list[str]:
    return sorted(set(route_paths))


def checksum_manifest(tree: Path, route_paths: list[str]) -> dict[str, str]:
    _, _, files = compute_tree_digest(tree)
    served = {served_path(relative): sha for relative, sha in files.items()}
    required = [*route_roots(route_paths), SNAPSHOT_PATH]
    missing = [path for path in required if path not in served]
    if missing:
        raise ValueError(f"assembled tree does not serve required probe paths: {missing}")
    selected = {path: served[path] for path in required}
    for path in EXTRA_PATHS:
        if path in served:
            selected[path] = served[path]
    candidates = sorted(path for path in served if path.endswith(SAMPLE_SUFFIXES) and path not in selected)
    step = max(1, len(candidates) // SAMPLE_LIMIT)
    for path in candidates[::step][:SAMPLE_LIMIT]:
        selected[path] = served[path]
    return dict(sorted(selected.items()))

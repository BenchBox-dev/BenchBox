from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.publication.assembler import compute_tree_digest

SITE_INVENTORY = Path(__file__).resolve().parents[1] / "site_inventory.py"
ROUTE_PREFIXES = ("/docs/dev/", "/docs/", "/blog/", "/results/", "/")
EXPLANATIONS = {
    "/docs/dev/": "new route: trunk documentation mounted beside the release documentation",
    "/docs/": "release documentation now built from the latest release tag instead of the single deployed ref",
    "/blog/": "blog and its shared assets come from the trunk candidate",
    "/results/": "Explorer UI and DuckDB snapshot come from the trunk candidate",
    "/": "landing page now built from the latest release tag",
}


def route_of(path: str) -> str:
    for prefix in ROUTE_PREFIXES:
        if path.startswith(prefix):
            return prefix
    return "/"


def classify(legacy: Path, routes: Path) -> dict[str, Any]:
    _, _, legacy_files = compute_tree_digest(legacy)
    _, _, route_files = compute_tree_digest(routes)
    added = sorted(set(route_files) - set(legacy_files))
    removed = sorted(set(legacy_files) - set(route_files))
    changed = sorted(path for path in set(legacy_files) & set(route_files) if legacy_files[path] != route_files[path])
    identical = len(set(legacy_files) & set(route_files)) - len(changed)
    by_route: dict[str, dict[str, Any]] = {}
    for kind, paths in (("added", added), ("removed", removed), ("changed", changed)):
        for path in paths:
            entry = by_route.setdefault(route_of("/" + path), {"added": 0, "removed": 0, "changed": 0})
            entry[kind] += 1
    return {
        "legacy_files": len(legacy_files),
        "route_files": len(route_files),
        "identical_files": identical,
        "added": len(added),
        "removed": len(removed),
        "changed": len(changed),
        "by_route": {
            route: {**counts, "explanation": EXPLANATIONS[route]} for route, counts in sorted(by_route.items())
        },
        "removed_samples": removed[:20],
        "added_samples": added[:20],
        "changed_samples": changed[:20],
    }


def inventory_diff(legacy: Path, routes: Path, work_dir: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for label, tree in (("legacy", legacy), ("routes", routes)):
        target = work_dir / f"inventory-{label}.json"
        build = subprocess.run(
            [sys.executable, str(SITE_INVENTORY), "build", "--site-dir", str(tree), "--output", str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if build.returncode != 0:
            return {"ok": False, "detail": f"inventory build failed for {label}: {build.stderr[-300:]}"}
        outputs[label] = target
    diff = subprocess.run(
        [
            sys.executable,
            str(SITE_INVENTORY),
            "diff",
            "--baseline",
            str(outputs["legacy"]),
            "--candidate",
            str(outputs["routes"]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return {"ok": diff.returncode == 0, "exit_code": diff.returncode, "report": diff.stdout.strip().splitlines()[-60:]}


def parity_report(legacy: Path, routes: Path, work_dir: Path) -> dict[str, Any]:
    return {
        "schema": "site-deploy-parity/v1",
        "files": classify(legacy, routes),
        "inventory": inventory_diff(legacy, routes, work_dir),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

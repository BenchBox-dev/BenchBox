#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DECISION = ROOT / "_project/decisions/independent-publication-a0-freeze-2026-08-31.md"
REQUIRED_SURFACES = (
    "_project/analysis/ingest-architecture-design.md",
    "docs/development/adr/adr-published-results-slim-corpus-branch.md",
    "docs/development/benchbox-results-platform-strategy.md",
    "docs/operations/release-guide.md",
    "docs/operations/repo-admin-settings.md",
    "docs/reference/threat-model.md",
    "docs/design/future-state/index.md",
)
REQUIRED_GATES = (
    "G1 archive preservation",
    "G2 dual publication",
    "G3 rollback",
    "G4 ownership",
    "G5 final reconciliation",
)
EXPECTED_DEPS: dict[str, list[str]] = {
    "independent-publication-a0-baseline-and-freeze": [],
    "independent-publication-a1-authority-and-threat-contract": ["independent-publication-a0-baseline-and-freeze"],
    "independent-publication-a2-corpus-trust-isolation": ["independent-publication-a1-authority-and-threat-contract"],
    "independent-publication-a3-control-plane-and-artifact-contract": [
        "independent-publication-a1-authority-and-threat-contract",
        "independent-publication-a2-corpus-trust-isolation",
    ],
    "independent-publication-a4-hermetic-build-and-shadow-assembly": [
        "independent-publication-a3-control-plane-and-artifact-contract"
    ],
    "independent-publication-a5-noop-deploy-and-automatic-rollback": [
        "independent-publication-a4-hermetic-build-and-shadow-assembly"
    ],
    "independent-publication-a6-site-and-api-docs-lane": [
        "independent-publication-a5-noop-deploy-and-automatic-rollback"
    ],
    "independent-publication-a7-explorer-application-lane": [
        "independent-publication-a5-noop-deploy-and-automatic-rollback"
    ],
    "independent-publication-a8-published-results-gate-and-shadow-promotion": [
        "independent-publication-a2-corpus-trust-isolation",
        "independent-publication-a4-hermetic-build-and-shadow-assembly",
        "independent-publication-a7-explorer-application-lane",
    ],
    "independent-publication-a9-corpus-production-cutover": [
        "independent-publication-a6-site-and-api-docs-lane",
        "independent-publication-a7-explorer-application-lane",
        "independent-publication-a8-published-results-gate-and-shadow-promotion",
    ],
    "independent-publication-a10-release-and-mirror-retirement": [
        "independent-publication-a9-corpus-production-cutover"
    ],
    "independent-publication-a11-operations-canaries-and-closeout": [
        "independent-publication-a10-release-and-mirror-retirement"
    ],
}
EXPECTED_EXTERNAL_DEPS: dict[str, frozenset[str]] = {
    "independent-publication-a10-release-and-mirror-retirement": frozenset(
        {"independent-production-deployer-and-retirement"}
    ),
}
TRACKER_CONFIG = ROOT / ".todo-db/config.json"


def planned_tracker_ids(text: str, prefix: str) -> list[str]:
    return list(dict.fromkeys(re.findall(rf"`({re.escape(prefix)}[a-z0-9-]+)`", text)))


def _phase_key(item_id: str, prefix: str) -> tuple[int, str]:
    match = re.search(re.escape(prefix) + r"a(\d+)-", item_id)
    return (int(match.group(1)) if match else 0, item_id)


def live_tracker_ids(items: list[dict], prefix: str) -> list[str]:
    selected: dict[str, dict] = {}
    for item in items:
        item_id = str(item.get("id", ""))
        if item_id.startswith(prefix) and str(item.get("state", "")).lower() != "dropped":
            selected[item_id] = item
    if not any("deps" in item for item in selected.values()):
        return sorted(selected, key=lambda item_id: _phase_key(item_id, prefix))
    deps_of = {
        item_id: [dep for dep in (item.get("deps") or []) if dep in selected] for item_id, item in selected.items()
    }
    order: list[str] = []
    remaining = set(selected)
    while remaining:
        ready = sorted(
            (item_id for item_id in remaining if not (set(deps_of[item_id]) & remaining)),
            key=lambda item_id: _phase_key(item_id, prefix),
        )
        if not ready:
            raise ValueError("cycle in live tracker dependency graph")
        order.extend(ready)
        remaining.difference_update(ready)
    return order


def dependency_violations(plan_order: list[str], deps: dict[str, list[str]]) -> list[str]:
    rank = {item_id: i for i, item_id in enumerate(plan_order)}
    order_set = set(plan_order)
    violations: list[str] = []
    for item_id in plan_order:
        live_all = deps.get(item_id, []) or []
        allowed_external = EXPECTED_EXTERNAL_DEPS.get(item_id, frozenset())
        live_external = {dep for dep in live_all if dep not in order_set}
        for dep in sorted(live_external - allowed_external):
            violations.append(f"{item_id} has unexpected external dependency on {dep}")
        for dep in sorted(allowed_external - live_external):
            violations.append(f"{item_id} is missing expected external dependency on {dep}")
        item_deps = [dep for dep in live_all if dep in order_set]
        for dep in item_deps:
            if rank[dep] >= rank[item_id]:
                violations.append(f"{item_id} depends on {dep}, which the plan orders after it")
        if rank[item_id] > 0 and not any(rank[dep] < rank[item_id] for dep in item_deps):
            violations.append(f"{item_id} has no prior dependency in the plan (removed chain)")
        if item_id in EXPECTED_DEPS:
            expected_in = [dep for dep in EXPECTED_DEPS[item_id] if dep in order_set]
            for exp in expected_in:
                if exp not in item_deps:
                    violations.append(f"{item_id} is missing expected dependency on {exp}")
            for dep in item_deps:
                if dep not in expected_in:
                    violations.append(f"{item_id} has unexpected dependency on {dep}")
        else:
            violations.append(f"{item_id} is not pinned in EXPECTED_DEPS (unpinned phase)")
    return violations


def load_tracker_snapshot(prefix: str | None = None) -> dict | None:
    try:
        config = json.loads(TRACKER_CONFIG.read_text(encoding="utf-8"))
        remote = config["state_remote"]
        branch = config["state_branch"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        return None
    try:
        origin = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd=ROOT,
        ).stdout.strip()
        if origin.rstrip("/").removesuffix(".git") != remote.rstrip("/").removesuffix(".git"):
            return None
        subprocess.run(
            ["git", "fetch", "--quiet", "--no-tags", "--depth", "1", "origin", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
            cwd=ROOT,
        )
        raw_index = subprocess.run(
            ["git", "show", "FETCH_HEAD:index.json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd=ROOT,
        ).stdout
        index = json.loads(raw_index)
        entries = index["items"]
        if not isinstance(entries, dict):
            return None
        states = {str(item_id): str(entry["status"]) for item_id, entry in entries.items()}
        deps = {
            str(item_id): sorted(str(value) for value in entry.get("needs", [])) for item_id, entry in entries.items()
        }
    except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return {"states": states, "deps": deps}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--todo-prefix", required=True)
    args = parser.parse_args()
    text = DECISION.read_text()
    missing = [surface for surface in REQUIRED_SURFACES if surface not in text]
    missing.extend(gate for gate in REQUIRED_GATES if gate not in text)
    tracker_ids = planned_tracker_ids(text, args.todo_prefix)
    snapshot = load_tracker_snapshot(args.todo_prefix)

    if snapshot is None:
        print(
            "ERROR: live tracker unavailable; cannot reconcile the A0-A11 sequence (fail closed)",
            file=sys.stderr,
        )
        missing.append("exact ordered A0-A11 tracker sequence (live tracker unavailable)")
    else:
        states: dict[str, str] = snapshot["states"]
        dep_graph: dict[str, list[str]] = snapshot["deps"]
        prefix_ids = [item_id for item_id in states if item_id.startswith(args.todo_prefix)]

        dropped_required = sorted(
            (
                item_id
                for item_id in prefix_ids
                if states[item_id].lower() == "dropped" and (item_id in EXPECTED_DEPS or item_id in tracker_ids)
            ),
            key=lambda item_id: _phase_key(item_id, args.todo_prefix),
        )
        for did in dropped_required:
            missing.append(f"dropped required phase is dropped: {did}")

        live_item_ids = sorted(
            (item_id for item_id in prefix_ids if states[item_id].lower() != "dropped" and item_id in EXPECTED_DEPS),
            key=lambda item_id: _phase_key(item_id, args.todo_prefix),
        )

        live_deps: dict[str, list[str]] | None = {}
        for item_id in live_item_ids:
            if item_id not in dep_graph:
                live_deps = None
                break
            live_deps[item_id] = dep_graph[item_id]

        if live_deps is None:
            print(
                "ERROR: could not read the tracker dependency graph; cannot reconcile A0-A11 order (fail closed)",
                file=sys.stderr,
            )
            missing.append("exact ordered A0-A11 tracker sequence (dependency graph unavailable)")
        else:
            expected_sorted = sorted(EXPECTED_DEPS.keys(), key=lambda item_id: _phase_key(item_id, args.todo_prefix))
            if tracker_ids != expected_sorted:
                missing.append("exact ordered A0-A11 tracker sequence (plan missing expected phases)")
            if live_item_ids != expected_sorted:
                missing.append("exact ordered A0-A11 tracker sequence (live missing expected phases)")
            if tracker_ids != live_item_ids:
                missing.append("exact ordered A0-A11 tracker sequence (live tracker)")
            missing.extend(dependency_violations(tracker_ids, live_deps))
    if missing:
        for value in missing:
            print(f"ERROR: unreconciled publication surface: {value}")
        return 1
    print(
        f"publication plan reconciled against live tracker: "
        f"{len(REQUIRED_SURFACES)} prior surfaces, {len(REQUIRED_GATES)} gates, {len(tracker_ids)} tracker priorities"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

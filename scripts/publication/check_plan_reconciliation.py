#!/usr/bin/env python3
"""Check that publication migration plans cite all controlling surfaces.

The A0-A11 tracker sequence is sourced from the live tracker (a single lossless
``todo-db export`` envelope) rather than a hard-coded list, so the check cannot
silently pass on a stale expected sequence. The check fails closed: if the live
tracker cannot be reached (no credential or offline), reconciliation is a hard
failure rather than an advisory pass, because without live evidence the gate
cannot prove the plan matches the currently pending migration order.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
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
# Expected dependency graph at the freeze decision (source of truth for edge drift).
# Each key is a tracker item; value is its in-set dependencies. This encodes the
# exact precedence required by the plan so that removal of any required edge
# (even when the total order remains topologically valid) is detected.
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
# Freeze closure deferred A10 retirement onto an independent production deployer.
# That one external predecessor is pinned here; arbitrary external deps still fail.
EXPECTED_EXTERNAL_DEPS: dict[str, frozenset[str]] = {
    "independent-publication-a10-release-and-mirror-retirement": frozenset(
        {"independent-production-deployer-and-retirement"}
    ),
}
# Tracker identity -- must match .todo-db/config.json (project_id / repository).
TRACKER_PROJECT_ID = "benchbox"
TRACKER_REPOSITORY = "https://github.com/joeharris76/BenchBox"
# Environment variables forwarded to the floor CLI for a hosted read. The
# credentialed CI step supplies them; without TODO_DB_AUTH_CONTRACT=v2 a hosted
# call returns a legacy-safe exit 2, which this gate then treats as fail-closed.
_EXPORT_ENV_KEYS = ("TODO_DB_URL", "TODO_DB_RO_AUTH_TOKEN", "TODO_DB_AUTH_CONTRACT")


def planned_tracker_ids(text: str, prefix: str) -> list[str]:
    return list(dict.fromkeys(re.findall(rf"`({re.escape(prefix)}[a-z0-9-]+)`", text)))


def _phase_key(item_id: str, prefix: str) -> tuple[int, str]:
    match = re.search(re.escape(prefix) + r"a(\d+)-", item_id)
    return (int(match.group(1)) if match else 0, item_id)


def live_tracker_ids(items: list[dict], prefix: str) -> list[str]:
    """Order non-dropped tracker items matching ``prefix`` by their dependency graph.

    ``todo list`` returns items across all lifecycle states, and its rows carry
    an optional ``deps`` list. Ordering is read from that dependency graph
    (a topological order) rather than inferred from the A-phase encoded in the
    ID, so a renumbering or dependency change that deletes from the names cannot
    silently reproduce a stale sequence. Dropped items are excluded so the
    reconciliation cannot pass while a step has been dropped. When no row
    carries ``deps`` (for example a plain ``list`` payload), ordering falls back
    to the A-phase key to preserve existing behavior.

    Raises ``ValueError`` if the dependency graph among the selected items
    contains a cycle.
    """
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
    """Return live dependency edges inconsistent with the plan's total order.

    The decision document asserts a total migration order. Every live dependency
    edge within that set must point strictly earlier in the plan, and (except
    for the plan's first item) every item must be justified by at least one
    prior in-set dependency. This detects dependency-edge drift directly -- an
    added or renumbered edge to a later item, or a removed edge that leaves a
    chain inconsistent -- rather than inferring order from the A-phase in the
    ID or a lossy tie-break. A cycle is reported as a backward edge.

    In addition, the live graph is compared against ``EXPECTED_DEPS`` (the
    freeze-time graph). Removal of any required edge -- even when the item
    retains another earlier dependency so the total order stays topologically
    valid (e.g. A8 still depends on A2/A4 after A7 is removed) -- is a
    violation, as is an unexpected in-set edge. This closes the "last prior
    edge" gap where only orphan detection would fire.

    Dependencies outside the A0-A11 set are also validated: only edges listed
    in ``EXPECTED_EXTERNAL_DEPS`` are allowed, and each pinned external
    predecessor must be present. Arbitrary external deps still fail, because
    readiness would otherwise require an unplanned predecessor.

    ``deps`` maps each plan item to its live dependency ids (all deps are
    validated; only in-set edges are checked for order/missing/unexpected).
    """
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


def _export_command(output_path: Path) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        "_project/scripts",
        "--locked",
        "--",
        "todo-db",
        "--project-id",
        TRACKER_PROJECT_ID,
        "--repository",
        TRACKER_REPOSITORY,
        "export",
        "--output",
        str(output_path),
    ]


def _run_export(output_path: Path) -> bool:
    """Run the floor-CLI export, writing the lossless envelope to ``output_path``.

    Returns ``False`` on any failure so the caller fails closed. The hosted-read
    credentials are forwarded from the process environment (the credentialed CI
    step sets them); they are never hard-coded here.
    """
    env = dict(os.environ)
    for key in _EXPORT_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    try:
        subprocess.run(
            _export_command(output_path),
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
            cwd=ROOT,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return True


def parse_envelope(raw: str) -> dict | None:
    """Shape a ``todo-db export`` envelope into the maps reconciliation needs.

    Returns ``{"states": {item_id: state}, "deps": {item_id: [needs_item, ...]}}``
    built from the top-level ``tables.items`` and ``tables.item_deps`` rows, or
    ``None`` when the envelope is malformed or missing a required table so the
    caller fails closed.
    """
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None
    tables = envelope.get("tables")
    if not isinstance(tables, dict):
        return None
    items = tables.get("items")
    item_deps = tables.get("item_deps")
    if not isinstance(items, list) or not isinstance(item_deps, list):
        return None
    states: dict[str, str] = {}
    for row in items:
        if not isinstance(row, dict) or "id" not in row:
            return None
        states[str(row["id"])] = str(row.get("state", ""))
    deps: dict[str, list[str]] = {item_id: [] for item_id in states}
    for row in item_deps:
        if not isinstance(row, dict) or "item_id" not in row or "needs_item" not in row:
            return None
        deps.setdefault(str(row["item_id"]), []).append(str(row["needs_item"]))
    return {"states": states, "deps": {item_id: sorted(values) for item_id, values in deps.items()}}


def load_tracker_snapshot() -> dict | None:
    """Export the live tracker once and shape it, or ``None`` if unavailable.

    A single ``todo-db export`` is an atomic snapshot of the whole tracker, so
    the item states and the dependency graph it returns are mutually consistent
    with no re-read needed (the retired ``todo list``/``todo show`` path had to
    re-read to detect concurrent edits). Any failure -- the export command, an
    unreadable file, or a malformed envelope -- returns ``None`` and the gate
    fails closed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        output_path = Path(tmp) / "tracker-export.json"
        if not _run_export(output_path):
            return None
        try:
            raw = output_path.read_text(encoding="utf-8")
        except OSError:
            return None
    return parse_envelope(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--todo-prefix", required=True)
    args = parser.parse_args()
    text = DECISION.read_text()
    missing = [surface for surface in REQUIRED_SURFACES if surface not in text]
    missing.extend(gate for gate in REQUIRED_GATES if gate not in text)
    tracker_ids = planned_tracker_ids(text, args.todo_prefix)
    snapshot = load_tracker_snapshot()

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

        # Retain dropped rows for explicit drift failure. Filtering dropped
        # before comparison would hide a dropped required phase when the
        # decision is edited to omit that phase (11 vs 11 would match).
        # Check against EXPECTED_DEPS and the plan text so the gate fails even
        # if the plan text was changed to match the filtered live set.
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

        # Every pinned phase must carry its dependency rows in the same atomic
        # export snapshot; an absent id means the envelope is incomplete, so
        # fail closed rather than treating it as having no dependencies.
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
            # Require every pinned phase to be present in both sequences.
            # Without this, both the plan and live could omit a terminal phase
            # (e.g., A11) and still match (11 vs 11) while the dependency loop
            # never visits the missing key.
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

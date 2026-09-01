#!/usr/bin/env python3
"""Check that publication migration plans cite all controlling surfaces.

The A0-A11 tracker sequence is sourced from the live tracker (the todo CLI)
rather than a hard-coded list, so the check cannot silently pass on a stale
expected sequence. The check fails closed: if the live tracker cannot be
reached (no credential or offline), reconciliation is a hard failure rather
than an advisory pass, because without live evidence the gate cannot prove
the plan matches the currently pending migration order.
"""

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
TODO_SHIM = ROOT / "_project/scripts/todo"


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

    Dependencies outside the A0-A11 set are also validated: any live edge to
    an item not in the plan's ordered set is an unexpected external
    dependency, because readiness requires every predecessor to be done.

    ``deps`` maps each plan item to its live dependency ids (all deps are
    validated; only in-set edges are checked for order/missing/unexpected).
    """
    rank = {item_id: i for i, item_id in enumerate(plan_order)}
    order_set = set(plan_order)
    violations: list[str] = []
    for item_id in plan_order:
        live_all = deps.get(item_id, []) or []
        # External dependencies (outside A0-A11) must be explicitly pinned;
        # any such edge is drift because the plan's total order cannot
        # justify it and readiness would require the external predecessor.
        for dep in live_all:
            if dep not in order_set:
                violations.append(f"{item_id} has unexpected external dependency on {dep}")
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


def load_live_deps(item_ids: list[str], todo_cmd: list[str] | None = None) -> dict[str, list[str]] | None:
    """Return ``{item_id: deps}`` for each id, or ``None`` if any read is unavailable.

    ``todo list`` does not expose dependencies, so each item is read with
    ``show <id> --json``. Deps come from the tracker's authoritative graph; an
    unavailable read is treated as a failure so the gate cannot pass without it.

    The lifecycle state is also re-checked from the ``show`` response: if a
    required phase flipped to ``dropped`` after the initial ``list`` call,
    the ``show`` payload carries the fresher state and the gate must fail
    rather than using the stale non-dropped state from the list.
    """
    shim_cmd = todo_cmd if todo_cmd is not None else [str(TODO_SHIM)]
    deps: dict[str, list[str]] = {}
    for item_id in item_ids:
        try:
            result = subprocess.run(
                [*shim_cmd, "show", item_id, "--json"], capture_output=True, text=True, check=True, timeout=60
            )
            item = json.loads(result.stdout)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return None
        if str(item.get("state", "")).lower() == "dropped":
            return None
        deps[item_id] = item.get("deps") or []
    return deps


def load_live_items(todo_cmd: list[str] | None = None) -> list[dict] | None:
    """Return parsed ``todo list --json`` items, or ``None`` if the tracker is unreachable."""
    cmd = todo_cmd if todo_cmd is not None else [str(TODO_SHIM), "list", "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--todo-prefix", required=True)
    args = parser.parse_args()
    text = DECISION.read_text()
    missing = [surface for surface in REQUIRED_SURFACES if surface not in text]
    missing.extend(gate for gate in REQUIRED_GATES if gate not in text)
    tracker_ids = planned_tracker_ids(text, args.todo_prefix)
    live_items = load_live_items()

    if live_items is None:
        print(
            "ERROR: live tracker unavailable; cannot reconcile the A0-A11 sequence (fail closed)",
            file=sys.stderr,
        )
        missing.append("exact ordered A0-A11 tracker sequence (live tracker unavailable)")
    else:
        # Retain dropped rows for explicit drift failure. Filtering dropped
        # before comparison would hide a dropped required phase when the
        # decision is edited to omit that phase (11 vs 11 would match).
        # Check against EXPECTED_DEPS so the gate fails even if the plan
        # text was changed to match the filtered live set.
        prefix_all = [item for item in live_items if str(item.get("id", "")).startswith(args.todo_prefix)]
        dropped_required = [
            item["id"]
            for item in prefix_all
            if str(item.get("state", "")).lower() == "dropped" and item["id"] in EXPECTED_DEPS
        ]
        # Also catch dropped items that appear in the plan but are not in
        # EXPECTED_DEPS yet (forward-compat if the freeze set grows).
        for item in prefix_all:
            if (
                str(item.get("state", "")).lower() == "dropped"
                and str(item.get("id", "")) in tracker_ids
                and item["id"] not in dropped_required
            ):
                dropped_required.append(item["id"])
        for did in sorted(dropped_required, key=lambda item_id: _phase_key(item_id, args.todo_prefix)):
            missing.append(f"dropped required phase is dropped: {did}")
        live_scope = [
            item
            for item in live_items
            if str(item.get("id", "")).startswith(args.todo_prefix)
            and str(item.get("state", "")).lower() != "dropped"
            and item.get("id") in EXPECTED_DEPS
        ]
        live_ids = [item["id"] for item in live_scope]
        live_deps = load_live_deps(live_ids)
        if live_deps is None:
            print(
                "ERROR: could not read the tracker dependency graph; cannot reconcile A0-A11 order (fail closed)",
                file=sys.stderr,
            )
            missing.append("exact ordered A0-A11 tracker sequence (dependency graph unavailable)")
        else:
            # Verify stable snapshot: the tracker must not have changed
            # between the initial list and the per-item show reads. A concurrent
            # change (e.g., A0's deps modified after its show, or a new A12
            # added after the list) could otherwise assemble a mixed snapshot
            # that still matches EXPECTED_DEPS. Use a trailing revision check
            # via re-reading the list and deps after the second sweep so the
            # window ends with an atomic list comparison, not with per-item reads.
            live_items_after = load_live_items()
            if live_items_after is None:
                missing.append("exact ordered A0-A11 tracker sequence (live tracker unavailable on re-read)")
            else:
                prefix_after = [
                    item for item in live_items_after if str(item.get("id", "")).startswith(args.todo_prefix)
                ]
                before_map = {item["id"]: str(item.get("state", "")).lower() for item in prefix_all}
                after_map = {item["id"]: str(item.get("state", "")).lower() for item in prefix_after}
                if before_map != after_map:
                    missing.append("exact ordered A0-A11 tracker sequence (live tracker changed during check)")
                else:
                    live_deps_after = load_live_deps(live_ids)
                    if live_deps_after is None:
                        missing.append("exact ordered A0-A11 tracker sequence (dependency graph changed during check)")
                    elif live_deps_after != live_deps:
                        missing.append(
                            "exact ordered A0-A11 tracker sequence (live dependency graph changed during check)"
                        )
                    else:
                        # Final revision check after the second sweep: ensures no
                        # new phase or state change slipped in after the last show.
                        live_items_final = load_live_items()
                        if live_items_final is None:
                            missing.append(
                                "exact ordered A0-A11 tracker sequence (live tracker unavailable on final re-read)"
                            )
                        else:
                            prefix_final = [
                                item
                                for item in live_items_final
                                if str(item.get("id", "")).startswith(args.todo_prefix)
                            ]
                            final_map = {item["id"]: str(item.get("state", "")).lower() for item in prefix_final}
                            if final_map != before_map:
                                missing.append(
                                    "exact ordered A0-A11 tracker sequence (live tracker changed after dependency reads)"
                                )
            live_item_ids = sorted(live_ids, key=lambda item_id: _phase_key(item_id, args.todo_prefix))
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

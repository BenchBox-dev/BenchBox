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


def load_live_deps(item_ids: list[str], todo_cmd: list[str] | None = None) -> dict[str, list[str]] | None:
    """Return ``{item_id: deps}`` for each id, or ``None`` if any read is unavailable.

    ``todo list`` does not expose dependencies, so each item is read with
    ``show <id> --json``. Deps come from the tracker's authoritative graph; an
    unavailable read is treated as a failure so the gate cannot pass without it.
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
        live_scope = [
            item
            for item in live_items
            if str(item.get("id", "")).startswith(args.todo_prefix) and str(item.get("state", "")).lower() != "dropped"
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
            for item in live_scope:
                item["deps"] = live_deps.get(item["id"], [])
            try:
                expected_ids = live_tracker_ids(live_items, args.todo_prefix)
            except ValueError as exc:
                missing.append(f"exact ordered A0-A11 tracker sequence ({exc})")
                expected_ids = []
            if tracker_ids != expected_ids:
                missing.append("exact ordered A0-A11 tracker sequence (live tracker)")
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

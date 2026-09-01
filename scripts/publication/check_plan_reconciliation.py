#!/usr/bin/env python3
"""Check that publication migration plans cite all controlling surfaces.

The A0-A11 tracker sequence is sourced from the live tracker (the todo CLI)
rather than a hard-coded list, so the check cannot silently pass on a stale
expected sequence. When the live tracker is unreachable (no credential or
offline), the check degrades to advisory mode and reports that live
reconciliation was skipped instead of asserting a hard-coded expectation.
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
    """Order tracker items matching ``prefix`` by their numeric A-phase (a0..a11)."""
    matches = [item["id"] for item in items if str(item.get("id", "")).startswith(prefix)]
    return sorted(matches, key=lambda item_id: _phase_key(item_id, prefix))


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
            "WARNING: live tracker unavailable; skipping live A0-A11 reconciliation (advisory mode)",
            file=sys.stderr,
        )
    else:
        expected_ids = live_tracker_ids(live_items, args.todo_prefix)
        if tracker_ids != expected_ids:
            missing.append("exact ordered A0-A11 tracker sequence (live tracker)")
    if missing:
        for value in missing:
            print(f"ERROR: unreconciled publication surface: {value}")
        return 1
    authority = "live tracker" if live_items is not None else "advisory (document-only)"
    print(
        f"publication plan reconciled against {authority}: "
        f"{len(REQUIRED_SURFACES)} prior surfaces, {len(REQUIRED_GATES)} gates, {len(tracker_ids)} tracker priorities"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

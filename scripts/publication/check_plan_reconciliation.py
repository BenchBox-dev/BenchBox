#!/usr/bin/env python3
"""Check that publication migration plans cite all controlling surfaces."""

from __future__ import annotations

import argparse
import re
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
REQUIRED_TRACKER_IDS = (
    "independent-publication-a0-baseline-and-freeze",
    "independent-publication-a1-authority-and-threat-contract",
    "independent-publication-a2-corpus-trust-isolation",
    "independent-publication-a3-control-plane-and-artifact-contract",
    "independent-publication-a4-hermetic-build-and-shadow-assembly",
    "independent-publication-a5-noop-deploy-and-automatic-rollback",
    "independent-publication-a6-site-and-api-docs-lane",
    "independent-publication-a7-explorer-application-lane",
    "independent-publication-a8-published-results-gate-and-shadow-promotion",
    "independent-publication-a9-corpus-production-cutover",
    "independent-publication-a10-release-and-mirror-retirement",
    "independent-publication-a11-operations-canaries-and-closeout",
)


def planned_tracker_ids(text: str, prefix: str) -> list[str]:
    return list(dict.fromkeys(re.findall(rf"`({re.escape(prefix)}[a-z0-9-]+)`", text)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--todo-prefix", required=True)
    args = parser.parse_args()
    text = DECISION.read_text()
    missing = [surface for surface in REQUIRED_SURFACES if surface not in text]
    missing.extend(gate for gate in REQUIRED_GATES if gate not in text)
    tracker_ids = planned_tracker_ids(text, args.todo_prefix)
    expected_ids = [item_id for item_id in REQUIRED_TRACKER_IDS if item_id.startswith(args.todo_prefix)]
    if tracker_ids != expected_ids:
        missing.append("exact ordered A0-A11 tracker sequence")
    if missing:
        for value in missing:
            print(f"ERROR: unreconciled publication surface: {value}")
        return 1
    print(
        f"publication plan reconciled: {len(REQUIRED_SURFACES)} prior surfaces, "
        f"{len(REQUIRED_GATES)} gates, {len(tracker_ids)} tracker priorities"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

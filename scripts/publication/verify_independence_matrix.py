#!/usr/bin/env python3
"""Four-lane independence matrix verifier (A11 w2).

Proves decoupling and independence across publication lanes:
1. package  - Python package and wheels
2. site     - Prose and Sphinx API documentation
3. explorer - Results Explorer React/TypeScript web app
4. corpus   - Curated seed bundles and results.duckdb

Independence Invariant:
When lane L_i is updated, only Hash(L_i) changes, while Hash(L_{j != i})
remain strictly identical across transitions.

This tool never fabricates transitions. It verifies real recorded lane
transitions supplied in ``--receipts-dir``. With no real transition record it
fails closed (exit 2): it cannot prove independence against a fixture it made
up.

Exit codes:
  0 - Independence verified, zero cross-lane coupling violations.
  1 - Independence violation detected (lane coupling or unexpected hash drift).
  2 - Configuration, file reading, or argument error (including missing input).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
LANES = ("package", "site", "explorer", "corpus")

MATRIX_FILE_NAME = "independence-matrix.json"
LANE_TRANSITIONS_FILE_NAME = "lane-transitions.json"
HEX_64_RE = re.compile(r"^(sha256:)?[0-9a-f]{64}$", re.IGNORECASE)


class MatrixInputError(ValueError):
    """Raised when no real transition record is available."""


def _validate_artifact_evidence(evidence: Any) -> list[str]:
    """Validate immutable workflow-artifact provenance carried by a transition."""
    if not isinstance(evidence, dict):
        return ["evidence must be an object"]
    errors: list[str] = []
    run_id = evidence.get("workflow_run_id")
    valid_run_id = (isinstance(run_id, int) and not isinstance(run_id, bool) and run_id > 0) or (
        isinstance(run_id, str) and run_id.isdecimal() and int(run_id) > 0
    )
    if not valid_run_id:
        errors.append("workflow_run_id must be a positive integer")
    for key in ("event_id", "artifact_name"):
        value = evidence.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{key} must be a non-empty string")
    digest = evidence.get("artifact_digest")
    if not isinstance(digest, str) or HEX_64_RE.fullmatch(digest.strip()) is None:
        errors.append("artifact_digest must be a SHA-256 digest")
    return errors


@dataclass
class LaneTransition:
    """A recorded transition between two publication states."""

    transition_id: str
    target_lane: str
    before_hashes: dict[str, str]
    after_hashes: dict[str, str]
    valid: bool = True
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IndependenceReport:
    """Structured report on cross-lane independence verification."""

    valid: bool = True
    lanes: list[str] = field(default_factory=lambda: list(LANES))
    transitions_checked: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)
    matrix: dict[str, dict[str, bool]] = field(default_factory=dict)
    transitions: list[LaneTransition] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "lanes": self.lanes,
            "transitions_checked": self.transitions_checked,
            "violations": self.violations,
            "matrix": self.matrix,
            "transitions": [t.to_dict() for t in self.transitions],
            "timestamp": self.timestamp,
        }


def verify_transition_independence(
    transition_id: str,
    target_lane: str,
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
) -> LaneTransition:
    """Verify that only target_lane has mutated between before and after hashes."""
    violations: list[str] = []

    if target_lane not in LANES:
        violations.append(f"Unknown target lane '{target_lane}'; expected one of {LANES}")

    target_before = before_hashes.get(target_lane, "")
    target_after = after_hashes.get(target_lane, "")
    if not target_before or not target_after:
        violations.append(f"Target lane '{target_lane}' is missing a before/after hash")
    elif target_before == target_after:
        violations.append(
            f"Target lane '{target_lane}' hash did not change during update ({target_before[:8]} == {target_after[:8]})"
        )

    for lane in LANES:
        if lane == target_lane:
            continue
        h_before = before_hashes.get(lane, "")
        h_after = after_hashes.get(lane, "")
        if not h_before or not h_after:
            violations.append(f"Non-target lane '{lane}' is missing a before/after hash")
        elif h_before != h_after:
            violations.append(
                f"Independence violation: non-target lane '{lane}' changed during '{target_lane}' update "
                f"({h_before[:8]} -> {h_after[:8]})"
            )

    is_valid = len(violations) == 0
    return LaneTransition(
        transition_id=transition_id,
        target_lane=target_lane,
        before_hashes=before_hashes,
        after_hashes=after_hashes,
        valid=is_valid,
        violations=violations,
    )


def _parse_transition_records(raw_transitions: Any) -> list[LaneTransition]:
    if not isinstance(raw_transitions, list):
        raise MatrixInputError("transition record must contain a list of transitions")
    parsed: list[LaneTransition] = []
    for r in raw_transitions:
        if not isinstance(r, dict):
            raise MatrixInputError(f"transition entry is not an object: {type(r).__name__}")
        evidence_errors = _validate_artifact_evidence(r.get("evidence"))
        if evidence_errors:
            raise MatrixInputError(
                "transition entry lacks valid provenance bound to a workflow event and immutable artifact: "
                + "; ".join(evidence_errors)
            )
        parsed.append(
            verify_transition_independence(
                transition_id=str(r.get("transition_id", "unknown")),
                target_lane=str(r.get("target_lane", "")),
                before_hashes=r.get("before_hashes", {}),
                after_hashes=r.get("after_hashes", {}),
            )
        )
    return parsed


def load_transitions_from_dir(receipts_dir: Path) -> list[LaneTransition]:
    """Load recorded lane transitions from a receipts directory.

    Raises MatrixInputError when no recognised transition record is present or
    the file cannot be parsed as JSON.
    """
    matrix_file = receipts_dir / MATRIX_FILE_NAME
    lane_trans_file = receipts_dir / LANE_TRANSITIONS_FILE_NAME

    source = matrix_file if matrix_file.is_file() else lane_trans_file if lane_trans_file.is_file() else None
    if source is None:
        raise MatrixInputError(
            f"no transition record found in {receipts_dir} "
            f"(expected {MATRIX_FILE_NAME} or {LANE_TRANSITIONS_FILE_NAME})"
        )

    try:
        with source.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise MatrixInputError(f"cannot read transition record {source}: {e}") from e

    raw = data if isinstance(data, list) else data.get("transitions") if isinstance(data, dict) else None
    if raw is None:
        raise MatrixInputError(f"transition record {source} has no 'transitions' array")
    transitions = _parse_transition_records(raw)
    if not transitions:
        raise MatrixInputError(f"transition record {source} contains zero transitions")
    return transitions


def verify_independence(
    transitions: list[LaneTransition] | None = None,
    receipts_dir: Path | None = None,
) -> IndependenceReport:
    """Verify lane independence matrix and build the 4x4 coupling matrix.

    Exactly one real source of transitions must be provided: an explicit
    ``transitions`` list or a ``receipts_dir`` holding a recorded transition
    file. With neither, this raises ``MatrixInputError`` - there is no synthetic
    fallback.
    """
    if transitions:
        eval_transitions = list(transitions)
    elif receipts_dir is not None:
        eval_transitions = load_transitions_from_dir(receipts_dir)
    else:
        raise MatrixInputError(
            "verify_independence requires real transitions or a receipts directory; "
            "it will not verify a self-made fixture"
        )

    all_violations: list[dict[str, Any]] = []
    matrix: dict[str, dict[str, bool]] = {i: dict.fromkeys(LANES, False) for i in LANES}

    for t in eval_transitions:
        if not t.valid:
            all_violations.append(
                {
                    "transition_id": t.transition_id,
                    "target_lane": t.target_lane,
                    "violations": t.violations,
                }
            )
        for lane in LANES:
            h_before = t.before_hashes.get(lane)
            h_after = t.after_hashes.get(lane)
            if h_before is not None and h_after is not None and h_before != h_after:
                if t.target_lane in matrix:
                    matrix[t.target_lane][lane] = True

    for row in LANES:
        for col in LANES:
            changed = matrix[row][col]
            if row == col and not changed:
                all_violations.append(
                    {
                        "transition_id": f"matrix_diagonal_{row}",
                        "target_lane": row,
                        "violations": [f"Lane '{row}' failed to mutate in its own transition"],
                    }
                )
            elif row != col and changed:
                all_violations.append(
                    {
                        "transition_id": f"matrix_off_diagonal_{row}_{col}",
                        "target_lane": row,
                        "violations": [f"Coupling detected: updating lane '{row}' caused mutation in lane '{col}'"],
                    }
                )

    is_valid = len(all_violations) == 0

    return IndependenceReport(
        valid=is_valid,
        lanes=list(LANES),
        transitions_checked=len(eval_transitions),
        violations=all_violations,
        matrix=matrix,
        transitions=eval_transitions,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Four-lane independence matrix verifier (A11 w2).")
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing a recorded lane transition file "
            f"({MATRIX_FILE_NAME} or {LANE_TRANSITIONS_FILE_NAME}). REQUIRED."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as formatted JSON.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.receipts_dir is None:
        sys.stderr.write(
            "Error: --receipts-dir is required. This canary verifies real recorded "
            "lane transitions; it does not verify a self-generated fixture.\n"
        )
        return 2
    if not args.receipts_dir.is_dir():
        sys.stderr.write(f"Receipts directory not found: {args.receipts_dir}\n")
        return 2

    try:
        report = verify_independence(receipts_dir=args.receipts_dir)
    except MatrixInputError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status_str = "PASS - INDEPENDENT" if report.valid else "FAIL - COUPLING DETECTED"
        print(f"Four-Lane Independence Verification: {status_str}")
        print(f"  Lanes Checked       : {', '.join(report.lanes)}")
        print(f"  Transitions Checked : {report.transitions_checked}")
        print(f"  Violations          : {len(report.violations)}")

        print("\nIndependence Matrix (Diagonal = True, Off-diagonal = False):")
        header = "Target \\ Observed | " + " | ".join(f"{lane:>8}" for lane in report.lanes)
        print("  " + header)
        print("  " + "-" * len(header))
        for row in report.lanes:
            row_vals = " | ".join(f"{str(report.matrix[row][col]):>8}" for col in report.lanes)
            print(f"  {row:>17} | {row_vals}")

        if report.violations:
            print("\nCoupling Violations:")
            for v in report.violations:
                print(f"  - [{v['transition_id']}] Target: {v['target_lane']}")
                for msg in v["violations"]:
                    print(f"      {msg}")

    return 0 if report.valid else 1


if __name__ == "__main__":
    sys.exit(main())

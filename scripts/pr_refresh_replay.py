#!/usr/bin/env python3
"""Deterministic replay of recorded refresh events through the classifier.

Evidence generation only. This module never skips a CI job and never
publishes a required status. Callers inject recorded PR, check-run, and
Actions-run data so unit tests do not touch the network.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pr_refresh_certification import (
    DECISION_FULL,
    DECISION_SHADOW,
    classify,
    request_from_mapping,
)

from benchbox.core.results.metrics import percentile_ms

# GitHub check-run conclusions that represent a settled outcome. A lane whose
# recorded value is absent, null, empty, "pending", or an unrecognized string has
# no terminal result yet, so completeness must reject it rather than accept the
# key's mere presence - `_failed_lanes` reads such a value as "not failed", which
# would report a shadow-eligible record as having no full-only failure before the
# lane actually finished.
TERMINAL_LANE_CONCLUSIONS = frozenset(
    {"success", "failure", "neutral", "cancelled", "timed_out", "action_required", "skipped", "stale"}
)

# Synthetic fixtures (the eligible template and the negative controls) exist to
# pin classifier behaviour, and carry placeholder durations - 100 seconds, 20
# runner-minutes. They are legitimate classification records but are not
# measurements, so performance aggregates must exclude them or the published p50
# / p95 / runner-minute totals describe the fixtures rather than the historical
# window. Records without an explicit kind are treated as observations.
RECORD_KIND_CONTROL = "control"
RECORD_KIND_OBSERVATION = "observation"

FULL_LANE_NAMES = (
    "code-lint",
    "code-test",
    "correctness-gate",
    "plan-capture-gate",
    "medium-test",
)


@dataclass
class ReplayResult:
    record_id: str
    pr_number: int | None
    decision: str
    reasons: list[str] = field(default_factory=list)
    actual_full_lanes_failed: list[str] = field(default_factory=list)
    full_only_failure: bool = False
    required_gate_seconds: float | None = None
    all_workflow_seconds: float | None = None
    runner_minutes: float | None = None
    kind: str = RECORD_KIND_OBSERVATION


@dataclass
class ReplaySummary:
    records: int
    shadow_eligible: int
    full_required: int
    eligibility_yield: float
    full_only_failures: int
    reason_counts: dict[str, int]
    required_gate_p50: float | None
    required_gate_p95: float | None
    all_workflow_p50: float | None
    runner_minutes_total: float | None
    observations: int
    controls: int


def _as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_kind(raw: Mapping[str, Any]) -> str:
    """Classify a record as a synthetic control or a real observation."""
    kind = str(raw.get("kind") or "").strip().lower()
    return RECORD_KIND_CONTROL if kind == RECORD_KIND_CONTROL else RECORD_KIND_OBSERVATION


def _failed_lanes(raw: Mapping[str, Any]) -> list[str]:
    lanes = raw.get("actual_lane_conclusions") or {}
    if not isinstance(lanes, Mapping):
        return []
    failed: list[str] = []
    for name in FULL_LANE_NAMES:
        conclusion = str(lanes.get(name) or "").lower()
        if conclusion in {"failure", "timed_out", "cancelled"}:
            failed.append(name)
    return failed


def normalize_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a recorded event into the classifier request shape."""

    request = raw.get("request") if isinstance(raw.get("request"), Mapping) else raw
    if not isinstance(request, Mapping):
        raise TypeError("record must be a mapping or contain a request mapping")
    return dict(request)


def replay_record(raw: Mapping[str, Any]) -> ReplayResult:
    record_id = str(raw.get("id") or raw.get("record_id") or raw.get("pr_number") or "unknown")
    try:
        request = request_from_mapping(normalize_record(raw))
        decision = classify(request)
    except (AttributeError, TypeError, ValueError, KeyError):
        return ReplayResult(
            record_id=record_id,
            pr_number=int(raw["pr_number"]) if raw.get("pr_number") else None,
            decision=DECISION_FULL,
            reasons=["malformed_payload"],
            kind=_record_kind(raw),
        )
    failed = _failed_lanes(raw)
    return ReplayResult(
        record_id=record_id,
        pr_number=decision.pr_number,
        decision=decision.decision,
        reasons=list(decision.reasons),
        actual_full_lanes_failed=failed,
        full_only_failure=bool(failed) and decision.decision == DECISION_SHADOW,
        required_gate_seconds=_as_float(raw.get("required_gate_seconds")),
        all_workflow_seconds=_as_float(raw.get("all_workflow_seconds")),
        runner_minutes=_as_float(raw.get("runner_minutes")),
        kind=_record_kind(raw),
    )


def _percentile(values: list[float], pct: float) -> float | None:
    """Percentile via the repo-wide nearest-rank definition.

    The previous index arithmetic - `ordered[int(n * pct / 100)]` - degenerated
    to `max()` for any sample of 20 or fewer values, which is every realistic
    replay history, so `required_gate_p95` tracked a single outlier. Delegating
    to `percentile_ms` also keeps one percentile definition across the repo; note
    it takes `p` as a fraction, and passing 95 instead of 0.95 is exactly the
    silent max() this replaced.
    """
    if not values:
        return None
    return percentile_ms(sorted(values), pct / 100)


def summarize(results: list[ReplayResult]) -> ReplaySummary:
    shadow = [item for item in results if item.decision == DECISION_SHADOW]
    full = [item for item in results if item.decision == DECISION_FULL]
    reasons: dict[str, int] = {}
    for item in results:
        for reason in item.reasons or ["(none)"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    # Classification counts cover every record; timing aggregates cover only
    # observations. Both counts are reported so an excluded control is visible
    # rather than silently dropped.
    observed = [item for item in results if item.kind != RECORD_KIND_CONTROL]
    gate = [item.required_gate_seconds for item in observed if item.required_gate_seconds is not None]
    whole = [item.all_workflow_seconds for item in observed if item.all_workflow_seconds is not None]
    minutes = [item.runner_minutes for item in observed if item.runner_minutes is not None]
    total = len(results)
    return ReplaySummary(
        records=total,
        shadow_eligible=len(shadow),
        full_required=len(full),
        eligibility_yield=(len(shadow) / total) if total else 0.0,
        full_only_failures=sum(1 for item in results if item.full_only_failure),
        reason_counts=dict(sorted(reasons.items())),
        required_gate_p50=_percentile(gate, 50),
        required_gate_p95=_percentile(gate, 95),
        all_workflow_p50=_percentile(whole, 50),
        runner_minutes_total=sum(minutes) if minutes else None,
        observations=len(observed),
        controls=total - len(observed),
    )


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        files = sorted(p for p in path.glob("*.json") if p.is_file())
        records = [json.loads(item.read_text(encoding="utf-8")) for item in files]
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else [payload]
    return [item for item in records if isinstance(item, dict)]


def completeness_errors(records: list[Mapping[str, Any]], results: list[ReplayResult]) -> list[str]:
    errors: list[str] = []
    if len(records) != len(results):
        errors.append(f"record/result count mismatch: {len(records)} vs {len(results)}")
    for raw, result in zip(records, results):
        record_id = str(raw.get("id") or result.record_id)
        if result.decision not in {DECISION_SHADOW, DECISION_FULL}:
            errors.append(f"{record_id}: unclassified decision {result.decision!r}")
        lanes = raw.get("actual_lane_conclusions")
        if not isinstance(lanes, Mapping):
            errors.append(f"{record_id}: missing actual_lane_conclusions")
            continue
        missing = [name for name in FULL_LANE_NAMES if name not in lanes]
        if missing:
            errors.append(f"{record_id}: missing lane outcomes {missing}")
        invalid = sorted(
            f"{name}={lanes.get(name)!r}"
            for name in FULL_LANE_NAMES
            if name in lanes and str(lanes.get(name) or "").lower() not in TERMINAL_LANE_CONCLUSIONS
        )
        if invalid:
            errors.append(f"{record_id}: non-terminal lane conclusions {invalid}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Record JSON file or directory")
    parser.add_argument("--fixtures", type=Path, help="Alias for --input")
    parser.add_argument("--json-out", type=Path, help="Write replay summary JSON")
    parser.add_argument(
        "--check-completeness",
        action="store_true",
        help="Fail unless every record has a decision and full-lane outcomes",
    )
    args = parser.parse_args(argv)
    source = args.fixtures or args.input
    if source is None:
        parser.error("one of --input or --fixtures is required")
    records = load_records(source)
    results = [replay_record(item) for item in records]
    summary = summarize(results)
    payload = {
        "summary": asdict(summary),
        "results": [asdict(item) for item in results],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if args.check_completeness:
        errors = completeness_errors(records, results)
        payload["completeness_errors"] = errors
        if errors:
            sys.stderr.write("unclassified or incomplete records:\n")
            for error in errors:
                sys.stderr.write(f"  {error}\n")
            if args.json_out:
                args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return 1
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

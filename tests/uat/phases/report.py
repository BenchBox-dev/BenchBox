"""Report phase: TSV roll-up + optional cross-scale coverage assertion.

The TSV format mirrors the 2026-05-02 retrospective's
`matrix_summary.tsv` so historical comparisons are straightforward.

Cross-scale coverage assertion is opt-in per the methodology spec's
Finding 1 scoping (default OFF; sweep authors enable explicitly).

Exit-code policy (uat-accounting-hardening w1, decided 2026-07-04)
-------------------------------------------------------------------
`ReportSummary.exit_code()` is default-strict: it returns `1` whenever
`fail_count`, `timeout_count`, or `unreachable_count` is nonzero, in addition
to the pre-existing `aborted` (2) and opt-in `cross_scale_floor_breached` (1)
checks. This was option 1 of the two the planning TODO posed (default-strict
vs. an additive `--strict` CLI flag). Evidence for picking option 1 over the
lenient-by-default + `--strict`-flag alternative:

- `tests/uat/_cli.py`'s `report` subcommand (the `make uat-report` entry
  point) and the `Makefile`'s `uat-report` target were grepped for any
  handling of the report's exit code beyond passing it straight through to
  the shell - neither does anything special with a nonzero exit (no
  `|| true`, no exit-code branching); there is no CI workflow under
  `.github/workflows/` that parses or gates on this exit code either.
- The UAT orchestrator (`tests/uat/orchestrator.py`, out of scope for this
  change) already folds the report phase's `exit_code()` into its own
  `SweepResult.exit_code()` via `max(phase_exit_codes.values())`, so making
  report exit codes honest only makes sweep-level exit codes more honest too;
  no orchestrator test asserts `exit_code() == 0` for a sweep containing an
  actual fail/timeout/unreachable cell (only for all-passed or
  aborted/cross-scale-floor-breached cases).
- The one place that *did* rely on the old lenient default was this
  module's own test suite (`tests/uat/test_report_accounting.py`), where two
  fixtures with real failed/unreachable cells asserted `exit_code == 0`
  simply because nobody had wired the check up yet - not because any
  caller depended on that leniency. Those tests were updated alongside this
  change rather than left pinning the stale behavior.

Net: no real caller depends on "exit 0 despite failures," so the more
honest default (option 1) was chosen over the additive `--strict` flag.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from tests.uat.phases import PhaseResult
from tests.uat.runner import CellResult

REPORT_HEADER = (
    "platform\tbenchmark\tscale\tstatus\tterminal_state\telapsed_s\tlog_path\tresult_path\t"
    "submit_terminal_state\tvalidator_status\tsource_commit_sha\tsource_dirty\tthroughput_check"
)

_SKIPPED_STATUSES = frozenset({"skipped"})
_UNREACHABLE_STATUSES = frozenset({"skipped-unreachable", "skipped_unreachable", "unreachable"})


class SourceInfo(Protocol):
    commit_sha: str
    dirty: bool


@dataclass(frozen=True)
class ReportSummary(PhaseResult):
    tsv_path: Path
    rows: int
    pass_count: int
    fail_count: int
    timeout_count: int
    candidate_count: int
    executed_count: int
    attempted_count: int
    skipped_count: int
    unreachable_count: int
    total_defined_count: int
    compatibility_pruned_count: int
    early_stop_pruned_count: int
    cross_scale_clean_pairs: int
    cross_scale_floor: int | None
    cross_scale_floor_breached: bool
    registry_pruned_count: int = 0
    unreachable_count_is_estimated: bool = False

    def exit_code(self) -> int:
        if self.aborted:
            return 2
        has_uncleared_cells = self.fail_count > 0 or self.timeout_count > 0 or self.unreachable_count > 0
        return 1 if has_uncleared_cells or self.cross_scale_floor_breached else 0


def render_row(
    cell: CellResult,
    *,
    validator_status: str = "",
    source_info: SourceInfo | None = None,
) -> str:
    """Render one row matching the current matrix-summary column order."""
    source_commit_sha = source_info.commit_sha if source_info else ""
    source_dirty = str(source_info.dirty).lower() if source_info else ""
    return (
        f"{cell.platform}\t{cell.benchmark}\t{cell.scale}\t"
        f"{cell.status}\t{terminal_state(cell)}\t{cell.elapsed_s:.2f}\t"
        f"{cell.log_path}\t{cell.result_path or ''}\t{cell.submit_terminal_state}\t{validator_status}\t"
        f"{source_commit_sha}\t{source_dirty}\t{cell.throughput_check or ''}"
    )


def terminal_state(cell: CellResult) -> str:
    """Classify the terminal state visible in durable UAT artifacts."""
    if cell.status == "passed":
        return "passed"
    if _is_skipped_status(cell.status):
        return "skipped"
    if _is_unreachable_status(cell.status):
        return "unreachable"
    if cell.status == "timed-out" or cell.exit_code == 124:
        return "timeout"
    if cell.exit_code in {-9, 137}:
        return "killed"
    if cell.result_path is None:
        if cell.exit_code == 0:
            return "no_json_exit_0"
        return "no_json_nonzero"
    if cell.status == "failed":
        # A failed cell that still exported a result JSON must not read as
        # submission-ready: falling through to `submit_terminal_state`
        # (default "submittable") mislabeled failures as clean. The
        # "failed:<submit_state>" token preserves the submit-classification
        # detail while remaining unambiguous with any real submit-ready state.
        return f"failed:{cell.submit_terminal_state}"
    if cell.submit_terminal_state:
        return cell.submit_terminal_state
    return cell.status


def _validator_status_for_path(validator_status_by_path: dict[Path, str], result_path: Path | None) -> str:
    if result_path is None:
        return ""
    return validator_status_by_path.get(result_path, "") or validator_status_by_path.get(result_path.resolve(), "")


def cross_scale_clean_pair_count(
    cells: Iterable[CellResult],
    rungs: list[float],
    validator_status_by_path: dict[Path, str] | None = None,
) -> int:
    """Count (platform, benchmark) pairs that passed AND validator-cleaned every rung."""
    if validator_status_by_path is None:
        validator_status_by_path = {}

    by_pb: dict[tuple[str, str], dict[float, CellResult]] = defaultdict(dict)
    for cell in cells:
        by_pb[(cell.platform, cell.benchmark)][cell.scale] = cell

    rungs_set = set(rungs)
    full = 0
    for pb, by_scale in by_pb.items():
        if not rungs_set.issubset(by_scale):
            continue
        ok = True
        for scale in rungs_set:
            cell = by_scale[scale]
            if cell.status != "passed":
                ok = False
                break
            v = _validator_status_for_path(validator_status_by_path, cell.result_path)
            if v and v not in ("clean", "warning_only"):
                ok = False
                break
        if ok:
            full += 1
    return full


def write_report(
    cells: Iterable[CellResult],
    *,
    output_path: Path,
    rungs: list[float] | None = None,
    cross_scale_floor: int | None = None,
    validator_status_by_path: dict[Path, str] | None = None,
    compatibility_pruned_count: int = 0,
    early_stop_pruned_count: int = 0,
    skipped_unreachable_count: int = 0,
    registry_pruned_count: int = 0,
    unreachable_count_is_estimated: bool = False,
    source_info: SourceInfo | None = None,
    run_status: str = "COMPLETED",
    abort_phase: str | None = None,
    abort_reason: str | None = None,
) -> ReportSummary:
    """Write the matrix summary TSV; optionally enforce a cross-scale floor.

    `registry_pruned_count` is the count of cells dropped for registry
    reasons - a benchmark id absent from the registry (w2) or a requested
    scale outside a benchmark's declared `scale_options` (w3, "ladder
    pruning") - as opposed to `compatibility_pruned_count`, which counts
    platform/benchmark compatibility-RULE drops. Keep the two disjoint: a
    caller should count any given pruned cell in exactly one of the two
    buckets, never both, since both feed `total_defined_count` below.

    `unreachable_count_is_estimated` marks whether `unreachable_count`
    includes a confirmed sidecar-derived `skipped_unreachable_count` (False)
    or was defaulted to 0 because the durable sweep's
    `cells.jsonl.accounting.json` sidecar was missing (True) - see w5's
    `_read_skipped_unreachable_sidecar` in `tests/uat/_cli.py`. It does not
    change `unreachable_count` itself; it only flags whether that number is
    confirmed or assumed.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(cells)
    executed_count = len(rows)

    pass_count = sum(1 for r in rows if r.status == "passed")
    fail_count = sum(1 for r in rows if r.status == "failed")
    timeout_count = sum(1 for r in rows if r.status == "timed-out")
    row_skipped_count = sum(1 for r in rows if _is_skipped_status(r.status))
    row_unreachable_count = sum(1 for r in rows if _is_unreachable_status(r.status))
    attempted_count = executed_count - row_skipped_count - row_unreachable_count
    skipped_count = row_skipped_count + compatibility_pruned_count + early_stop_pruned_count + registry_pruned_count
    unreachable_count = row_unreachable_count + skipped_unreachable_count
    total_defined_count = attempted_count + skipped_count + unreachable_count
    candidate_count = total_defined_count

    with output_path.open("w", encoding="utf-8") as fh:
        fh.write(REPORT_HEADER + "\n")
        for cell in rows:
            v = (
                _validator_status_for_path(validator_status_by_path, cell.result_path)
                if validator_status_by_path
                else ""
            )
            fh.write(render_row(cell, validator_status=v, source_info=source_info) + "\n")
        fh.write(
            "# "
            f"rows={len(rows)} "
            f"candidates={candidate_count} "
            f"executed={executed_count} "
            f"compatibility_pruned={compatibility_pruned_count} "
            f"early_stop_pruned={early_stop_pruned_count} "
            f"attempted={attempted_count} "
            f"skipped={skipped_count} "
            f"unreachable={unreachable_count} "
            f"total_defined={total_defined_count} "
            f"passed={pass_count} "
            f"failed={fail_count} "
            f"timed_out={timeout_count} "
            f"registry_pruned={registry_pruned_count}\n"
        )
        fh.write(
            "# "
            f"release_accounting passed={pass_count} failed={fail_count} timed_out={timeout_count} "
            f"attempted={attempted_count} skipped={skipped_count} unreachable={unreachable_count} "
            f"total_defined={total_defined_count} registry_pruned={registry_pruned_count}\n"
        )
        if unreachable_count or unreachable_count_is_estimated:
            attention = "required" if unreachable_count else "not_required"
            fh.write(
                f"# UNREACHABLE_CELLS={unreachable_count} release_gate_attention={attention} "
                f"unreachable_is_estimated={str(unreachable_count_is_estimated).lower()}\n"
            )
        footer = f"# run_status={run_status}"
        if source_info is not None:
            footer += f" source_commit_sha={source_info.commit_sha} source_dirty={str(source_info.dirty).lower()}"
        if abort_phase:
            footer += f" abort_phase={abort_phase}"
        if abort_reason:
            footer += f" abort_reason={_footer_value(abort_reason)}"
        fh.write(footer + "\n")

    if rungs:
        clean_pairs = cross_scale_clean_pair_count(rows, rungs, validator_status_by_path=validator_status_by_path)
    else:
        clean_pairs = 0

    floor_breached = cross_scale_floor is not None and clean_pairs < cross_scale_floor

    return ReportSummary(
        phase="report",
        tsv_path=output_path,
        rows=len(rows),
        pass_count=pass_count,
        fail_count=fail_count,
        timeout_count=timeout_count,
        candidate_count=candidate_count,
        executed_count=executed_count,
        attempted_count=attempted_count,
        skipped_count=skipped_count,
        unreachable_count=unreachable_count,
        total_defined_count=total_defined_count,
        compatibility_pruned_count=compatibility_pruned_count,
        early_stop_pruned_count=early_stop_pruned_count,
        cross_scale_clean_pairs=clean_pairs,
        cross_scale_floor=cross_scale_floor,
        cross_scale_floor_breached=floor_breached,
        registry_pruned_count=registry_pruned_count,
        unreachable_count_is_estimated=unreachable_count_is_estimated,
        aborted=run_status in {"ABORTED", "BLOCKED"},
        abort_reason=abort_reason,
    )


def _footer_value(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ")


def _normalized_status(status: str) -> str:
    return status.strip().lower()


def _is_skipped_status(status: str) -> bool:
    return _normalized_status(status) in _SKIPPED_STATUSES


def _is_unreachable_status(status: str) -> bool:
    return _normalized_status(status) in _UNREACHABLE_STATUSES


# ---------------------------------------------------------------------------
# Release-gate re-run ordering check.
#
# The release-gate contract (uat-certification-rerun-ordering-and-gate) runs
# four stages — native SQL, then dataframe, then Docker non-OLTP, then Docker
# OLTP — and requires that ALL native + dataframe platforms complete before any
# Docker stack starts. The 2026-05-28/29 evidence was contaminated because a
# Docker stack began before the dataframe sweep finished. Each sweep is a
# separate invocation, so the cross-stage order is enforced by the runbook; this
# helper provides the lightweight, machine-checkable proof from lifecycle logs.
# ---------------------------------------------------------------------------


def parse_docker_up_events(lifecycle_log_text: str) -> list[tuple[_dt.datetime, str]]:
    """Extract ``(timestamp, platform)`` for each Docker ``action=up`` line.

    Parses ``uat_lifecycle.log`` lines of the shape::

        2026-05-30T01:02:03 [docker] platform=lakesail action=up status=ok ...

    Lines without a Docker ``action=up`` marker, or with an unparseable leading
    ISO timestamp, are skipped.
    """
    events: list[tuple[_dt.datetime, str]] = []
    for raw in lifecycle_log_text.splitlines():
        line = raw.strip()
        if "[docker]" not in line or "action=up" not in line:
            continue
        timestamp_token = line.split(" ", 1)[0]
        try:
            timestamp = _dt.datetime.fromisoformat(timestamp_token)
        except ValueError:
            continue
        platform = "unknown"
        for token in line.split():
            if token.startswith("platform="):
                platform = token.split("=", 1)[1]
                break
        events.append((timestamp, platform))
    return events


def release_gate_ordering_violations(
    docker_stage_lifecycle_logs: Iterable[str],
    *,
    native_stage_completed_at: _dt.datetime,
) -> list[str]:
    """Return ordering violations for a release-gate run-set.

    Given the ``uat_lifecycle.log`` text of each Docker stage and the timestamp
    at which the native + dataframe stage completed, return a human-readable
    violation for every Docker ``action=up`` that started at or before that
    boundary. An empty list means the four-stage ordering held: no Docker stack
    came up before native + dataframe finished.
    """
    violations: list[str] = []
    for log_text in docker_stage_lifecycle_logs:
        for timestamp, platform in parse_docker_up_events(log_text):
            if timestamp <= native_stage_completed_at:
                violations.append(
                    f"Docker stack '{platform}' started at {timestamp.isoformat()} "
                    f"at/before native+dataframe stage completion "
                    f"{native_stage_completed_at.isoformat()}"
                )
    return violations

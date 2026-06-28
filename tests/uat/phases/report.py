"""Report phase: TSV roll-up + optional cross-scale coverage assertion.

The TSV format mirrors the 2026-05-02 retrospective's
`matrix_summary.tsv` so historical comparisons are straightforward.

Cross-scale coverage assertion is opt-in per the methodology spec's
Finding 1 scoping (default OFF; sweep authors enable explicitly).
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
    "submit_terminal_state\tvalidator_status\tsource_commit_sha\tsource_dirty"
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

    def exit_code(self) -> int:
        if self.aborted:
            return 2
        return 1 if self.cross_scale_floor_breached else 0


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
        f"{source_commit_sha}\t{source_dirty}"
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
    source_info: SourceInfo | None = None,
    run_status: str = "COMPLETED",
    abort_phase: str | None = None,
    abort_reason: str | None = None,
) -> ReportSummary:
    """Write the matrix summary TSV; optionally enforce a cross-scale floor."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(cells)
    executed_count = len(rows)

    pass_count = sum(1 for r in rows if r.status == "passed")
    fail_count = sum(1 for r in rows if r.status == "failed")
    timeout_count = sum(1 for r in rows if r.status == "timed-out")
    row_skipped_count = sum(1 for r in rows if _is_skipped_status(r.status))
    row_unreachable_count = sum(1 for r in rows if _is_unreachable_status(r.status))
    attempted_count = executed_count - row_skipped_count - row_unreachable_count
    skipped_count = row_skipped_count + compatibility_pruned_count + early_stop_pruned_count
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
            f"timed_out={timeout_count}\n"
        )
        fh.write(
            "# "
            f"release_accounting passed={pass_count} failed={fail_count} timed_out={timeout_count} "
            f"attempted={attempted_count} skipped={skipped_count} unreachable={unreachable_count} "
            f"total_defined={total_defined_count}\n"
        )
        if unreachable_count:
            fh.write(f"# UNREACHABLE_CELLS={unreachable_count} release_gate_attention=required\n")
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

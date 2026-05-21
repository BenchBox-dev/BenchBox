"""Report phase: TSV roll-up + optional cross-scale coverage assertion.

The TSV format mirrors the 2026-05-02 retrospective's
`matrix_summary.tsv` so historical comparisons are straightforward.

Cross-scale coverage assertion is opt-in per the methodology spec's
Finding 1 scoping (default OFF; sweep authors enable explicitly).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tests.uat.phases import PhaseResult
from tests.uat.runner import CellResult

REPORT_HEADER = (
    "platform\tbenchmark\tscale\tstatus\telapsed_s\tlog_path\tresult_path\tsubmit_terminal_state\tvalidator_status"
)


@dataclass(frozen=True)
class ReportSummary(PhaseResult):
    tsv_path: Path
    rows: int
    pass_count: int
    fail_count: int
    timeout_count: int
    candidate_count: int
    executed_count: int
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
) -> str:
    """Render one row matching the current matrix-summary column order."""
    return (
        f"{cell.platform}\t{cell.benchmark}\t{cell.scale}\t"
        f"{cell.status}\t{cell.elapsed_s:.2f}\t"
        f"{cell.log_path}\t{cell.result_path or ''}\t{cell.submit_terminal_state}\t{validator_status}"
    )


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
) -> ReportSummary:
    """Write the matrix summary TSV; optionally enforce a cross-scale floor."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(cells)
    executed_count = len(rows)
    candidate_count = executed_count + compatibility_pruned_count + early_stop_pruned_count

    pass_count = sum(1 for r in rows if r.status == "passed")
    fail_count = sum(1 for r in rows if r.status == "failed")
    timeout_count = sum(1 for r in rows if r.status == "timed-out")

    with output_path.open("w", encoding="utf-8") as fh:
        fh.write(REPORT_HEADER + "\n")
        for cell in rows:
            v = (
                _validator_status_for_path(validator_status_by_path, cell.result_path)
                if validator_status_by_path
                else ""
            )
            fh.write(render_row(cell, validator_status=v) + "\n")
        fh.write(
            "# "
            f"rows={len(rows)} "
            f"candidates={candidate_count} "
            f"executed={executed_count} "
            f"compatibility_pruned={compatibility_pruned_count} "
            f"early_stop_pruned={early_stop_pruned_count} "
            f"passed={pass_count} "
            f"failed={fail_count} "
            f"timed_out={timeout_count}\n"
        )

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
        compatibility_pruned_count=compatibility_pruned_count,
        early_stop_pruned_count=early_stop_pruned_count,
        cross_scale_clean_pairs=clean_pairs,
        cross_scale_floor=cross_scale_floor,
        cross_scale_floor_breached=floor_breached,
    )

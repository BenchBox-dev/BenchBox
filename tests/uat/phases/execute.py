"""Execute phase: iterate the (platform, benchmark, rung) matrix sequentially.

Sequential platform execution discipline (UAT W3 line 222 in
_project/handoffs/results-explorer-uat-retrospective-20260502.md):
parallel platforms contaminate timings. The reserved
`config.execute.parallel_platforms` is hard-rejected at config load
time AND asserted False here as a second line of defence.

This module's `run_execute` walks the cell list in (platform,
benchmark) order, applies the ladder logic from `tests.uat.ladder`,
optionally runs reuse-aware cleanup from `tests.uat.cleanup`, and
returns a list of CellOutcomes.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from tests.uat.cleanup import CellKey, can_prune, prune_database_dir
from tests.uat.config import UATConfig
from tests.uat.ladder import LadderRung, plan_ladder
from tests.uat.matrix import platform_is_reachable
from tests.uat.phases.enumerate import Cell, enumerate_cells
from tests.uat.runner import CellResult, run_cell


@dataclass(frozen=True)
class ExecuteOutcome:
    """Aggregated outcome of run_execute."""

    results: tuple[CellResult, ...]
    pruned: tuple[Cell, ...]
    skipped_unreachable: tuple[Cell, ...]


def run_execute(
    config: UATConfig,
    *,
    log_dir: Path | None = None,
    databases_root: Path | None = None,
    cleanup_enabled: bool = True,
    runner=run_cell,  # injectable for tests
) -> ExecuteOutcome:
    """Walk the matrix sequentially with ladder pruning and reuse-aware cleanup.

    Parameters mirror the spec's W4 execute phase. `runner` is injectable
    so the fast tests can drive the loop without spawning subprocesses.
    """
    assert config.execute.parallel_platforms is False, "parallel_platforms must remain False — UAT W3 line 222"

    cells = enumerate_cells(config.raw)
    by_pb: dict[tuple[str, str], list[Cell]] = defaultdict(list)
    for cell in cells:
        by_pb[(cell.platform, cell.benchmark)].append(cell)
    # Sort each (platform, benchmark) by ascending scale so the ladder
    # walk is deterministic.
    for key in by_pb:
        by_pb[key].sort(key=lambda c: c.scale)

    results: list[CellResult] = []
    pruned: list[Cell] = []
    skipped_unreachable: list[Cell] = []

    for (platform, benchmark), pb_cells in by_pb.items():
        if config.execute.skip_unreachable and not platform_is_reachable(platform):
            skipped_unreachable.extend(pb_cells)
            continue

        ladder_rungs = [c.scale for c in pb_cells]
        observed: list[LadderRung] = []
        for cell in pb_cells:
            next_rungs, pruned_rungs = plan_ladder(
                ladder_rungs,
                observed,
                early_stop_after_s=config.execute.early_stop_after_s,
                early_stop_on_failure=config.execute.early_stop_on_failure,
            )
            if cell.scale in pruned_rungs:
                pruned.append(cell)
                continue
            cell_result = runner(
                cell.platform,
                cell.benchmark,
                cell.scale,
                timeout_s=config.execute.per_cell_timeout_s,
                phases=config.execute.phases_arg,
                compression=config.execute.compression,
                log_dir=log_dir,
            )
            results.append(cell_result)
            observed.append(
                LadderRung(
                    scale=cell.scale,
                    elapsed_s=cell_result.elapsed_s,
                    passed=(cell_result.status == "passed"),
                )
            )

        if cleanup_enabled and databases_root is not None:
            # Per-platform/benchmark mid-sweep cleanup: only prune when
            # all consumers of this source/scale are completed within
            # this platform.
            pending_after_pb = _pending_cells_after(by_pb, platform, benchmark)
            completed_for_platform = [
                CellKey(r.platform, r.benchmark, r.scale) for r in results if r.platform == platform
            ]
            for scale in {c.scale for c in pb_cells}:
                decision = can_prune(
                    benchmark,
                    platform=platform,
                    scale=scale,
                    pending_cells=[CellKey(c.platform, c.benchmark, c.scale) for c in pending_after_pb],
                    completed_cells=completed_for_platform,
                )
                if decision.safe_to_prune:
                    prune_database_dir(
                        databases_root,
                        platform=platform,
                        benchmark=benchmark,
                        scale=scale,
                        dry_run=config.dry_run,
                    )

    return ExecuteOutcome(
        results=tuple(results),
        pruned=tuple(pruned),
        skipped_unreachable=tuple(skipped_unreachable),
    )


def _pending_cells_after(
    by_pb: dict[tuple[str, str], list[Cell]],
    current_platform: str,
    current_benchmark: str,
) -> list[Cell]:
    """Return cells in by_pb that haven't been processed yet (same/later platform/benchmark order)."""
    out: list[Cell] = []
    seen = False
    for (platform, benchmark), pb_cells in by_pb.items():
        if (platform, benchmark) == (current_platform, current_benchmark):
            seen = True
            continue
        if seen:
            out.extend(pb_cells)
    return out


def default_log_dir(config: UATConfig, now: _dt.datetime | None = None) -> Path:
    """Resolve the YAML log_dir_template against {date} and {name}."""
    now = now or _dt.datetime.now()
    template = config.output.logs_dir_template
    rendered = template.replace("{date}", now.strftime("%Y%m%d")).replace("{name}", config.name)
    return Path(rendered).expanduser()

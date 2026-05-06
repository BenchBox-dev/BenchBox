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

from tests.uat.cleanup import SOURCE_REUSE_GRAPH, CellKey, can_prune, prune_database_dir
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
    benchmark_runs_dir: Path | None = None,
    databases_root: Path | None = None,
    cleanup_enabled: bool = True,
    runner=None,
) -> ExecuteOutcome:
    """Walk the matrix sequentially with ladder pruning and reuse-aware cleanup.

    Parameters mirror the spec's W4 execute phase. `runner` is injectable
    so the fast tests can drive the loop without spawning subprocesses.
    Resolves the module-level `run_cell` lazily so monkeypatching
    `tests.uat.phases.execute.run_cell` from a test takes effect.
    """
    if runner is None:
        runner = run_cell
    assert config.execute.parallel_platforms is False, "parallel_platforms must remain False — UAT W3 line 222"
    benchmark_runs_dir = (
        Path(benchmark_runs_dir).expanduser() if benchmark_runs_dir is not None else default_benchmark_runs_dir(config)
    )

    cells = enumerate_cells(config.raw)
    by_pb: dict[tuple[str, str], list[Cell]] = defaultdict(list)
    for cell in cells:
        by_pb[(cell.platform, cell.benchmark)].append(cell)
    # Sort each (platform, benchmark) by ascending scale so the ladder
    # walk is deterministic.
    for key in by_pb:
        by_pb[key].sort(key=lambda c: c.scale)

    # Reorder by_pb so that for each platform, sources from
    # SOURCE_REUSE_GRAPH come before their consumers. Without this,
    # `include: [read_primitives, tpch]` (or a future registry change
    # that moves consumer-categories ahead of sources) would attempt to
    # run a consumer before the source has loaded its DB.
    by_pb = _reorder_for_topology(by_pb)

    results: list[CellResult] = []
    pruned: list[Cell] = []
    skipped_unreachable: list[Cell] = []
    completed_pairs: set[tuple[str, str]] = set()
    already_pruned: set[tuple[str, str, float]] = set()

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
                extra_args=config.execute.extra_args,
                log_dir=log_dir,
                benchmark_runs_dir=benchmark_runs_dir,
            )
            results.append(cell_result)
            observed.append(
                LadderRung(
                    scale=cell.scale,
                    elapsed_s=cell_result.elapsed_s,
                    passed=(cell_result.status == "passed"),
                )
            )

        completed_pairs.add((platform, benchmark))

        if cleanup_enabled and databases_root is not None:
            # Re-check pruneability for EVERY benchmark we have already
            # completed on this platform, not just the one that just
            # finished. The source DB (e.g. tpch) becomes prunable only
            # when its last consumer (read_primitives, write_primitives,
            # …) finishes, which is by definition a later iteration.
            _maybe_prune_completed(
                platform=platform,
                by_pb=by_pb,
                results=results,
                completed_pairs=completed_pairs,
                already_pruned=already_pruned,
                databases_root=databases_root,
                dry_run=config.dry_run,
            )

    return ExecuteOutcome(
        results=tuple(results),
        pruned=tuple(pruned),
        skipped_unreachable=tuple(skipped_unreachable),
    )


def _reorder_for_topology(
    by_pb: dict[tuple[str, str], list[Cell]],
) -> dict[tuple[str, str], list[Cell]]:
    """Reorder by_pb so for each platform, sources precede their consumers.

    Reuse graph from `cleanup.SOURCE_REUSE_GRAPH` (e.g. tpch is a source
    for read_primitives etc.). The topological sort is stable: benchmarks
    not constrained by the graph keep their original relative order.
    """
    consumer_to_sources: dict[str, list[str]] = {}
    for source, consumers in SOURCE_REUSE_GRAPH.items():
        for c in consumers:
            if c == source:
                continue
            consumer_to_sources.setdefault(c, []).append(source)

    # Bucket pairs by platform, preserving original order within each.
    by_platform: dict[str, list[tuple[str, list[Cell]]]] = {}
    for (platform, benchmark), pb_cells in by_pb.items():
        by_platform.setdefault(platform, []).append((benchmark, pb_cells))

    out: dict[tuple[str, str], list[Cell]] = {}
    for platform, pairs in by_platform.items():
        bench_to_cells = dict(pairs)
        bench_order = [b for b, _ in pairs]
        sorted_benches = _topological_sort(bench_order, consumer_to_sources)
        for bench in sorted_benches:
            out[(platform, bench)] = bench_to_cells[bench]
    return out


def _topological_sort(
    benchmarks: list[str],
    consumer_to_sources: dict[str, list[str]],
) -> list[str]:
    """Stable topological sort: sources precede consumers, otherwise input order."""
    bench_set = set(benchmarks)
    pending = set(benchmarks)
    dependents: dict[str, list[str]] = defaultdict(list)
    indegree = dict.fromkeys(benchmarks, 0)
    out: list[str] = []
    for consumer in benchmarks:
        for src in consumer_to_sources.get(consumer, ()):
            if src in bench_set:
                dependents[src].append(consumer)
                indegree[consumer] += 1

    while pending:
        ready = next((b for b in benchmarks if b in pending and indegree[b] == 0), None)
        if ready is None:
            # SOURCE_REUSE_GRAPH is expected to be acyclic, but preserve
            # deterministic progress if a future edit introduces a cycle.
            ready = next(b for b in benchmarks if b in pending)
        pending.remove(ready)
        out.append(ready)
        for dependent in dependents.get(ready, ()):
            indegree[dependent] -= 1
    return out


def _maybe_prune_completed(
    *,
    platform: str,
    by_pb: dict[tuple[str, str], list[Cell]],
    results: list[CellResult],
    completed_pairs: set[tuple[str, str]],
    already_pruned: set[tuple[str, str, float]],
    databases_root: Path,
    dry_run: bool,
) -> None:
    """For each (platform, benchmark) already completed, prune any scale whose consumers are all done."""
    pending_keys = [
        CellKey(c.platform, c.benchmark, c.scale)
        for (p, b), pb in by_pb.items()
        if (p, b) not in completed_pairs
        for c in pb
    ]
    completed_keys_this_platform = [
        CellKey(r.platform, r.benchmark, r.scale) for r in results if r.platform == platform
    ]
    benches_done_on_platform = [b for (p, b) in completed_pairs if p == platform]
    for prev_bench in benches_done_on_platform:
        scales_for_prev = {c.scale for c in by_pb.get((platform, prev_bench), [])}
        for scale in scales_for_prev:
            key = (platform, prev_bench, scale)
            if key in already_pruned:
                continue
            decision = can_prune(
                prev_bench,
                platform=platform,
                scale=scale,
                pending_cells=pending_keys,
                completed_cells=completed_keys_this_platform,
            )
            if decision.safe_to_prune:
                prune_database_dir(
                    databases_root,
                    platform=platform,
                    benchmark=prev_bench,
                    scale=scale,
                    dry_run=dry_run,
                )
                already_pruned.add(key)


def default_log_dir(config: UATConfig, now: _dt.datetime | None = None) -> Path:
    """Resolve the YAML log_dir_template against {date} and {name}."""
    now = now or _dt.datetime.now()
    template = config.output.logs_dir_template
    rendered = template.replace("{date}", now.strftime("%Y%m%d")).replace("{name}", config.name)
    return Path(rendered).expanduser()


def default_benchmark_runs_dir(config: UATConfig, now: _dt.datetime | None = None) -> Path:
    """Resolve the YAML benchmark_runs root against {date} and {name}."""
    now = now or _dt.datetime.now()
    template = config.output.benchmark_runs_dir_template
    rendered = template.replace("{date}", now.strftime("%Y%m%d")).replace("{name}", config.name)
    return Path(rendered).expanduser()

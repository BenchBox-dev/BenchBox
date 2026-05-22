"""Execute phase: iterate the (platform, benchmark, rung) matrix sequentially.

Sequential platform execution discipline (UAT W3 line 222 in
_project/handoffs/results-explorer-uat-retrospective-20260502.md):
parallel platforms contaminate timings. The reserved
`config.execute.parallel_platforms` is hard-rejected at config load
time AND asserted False here as a second line of defence.

This module's `run_execute` walks the cell list in platform order,
applies the ladder logic from `tests.uat.ladder`, optionally runs
reuse-aware cleanup from `tests.uat.cleanup`, and returns a list of
CellOutcomes. Docker-backed platform lifecycle is handled here, at the
platform boundary, because this is the layer that can preserve
same-platform reuse while releasing UAT-owned Docker volumes before the
next platform starts.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from tests.uat import docker_assets
from tests.uat.cleanup import CellKey, can_prune, prune_database_dir, source_reuse_graph
from tests.uat.config import UATConfig
from tests.uat.ladder import LadderRung, plan_ladder
from tests.uat.matrix import invalidate_reachability_cache_after_lifecycle_change, platform_is_reachable
from tests.uat.phases import PhaseResult
from tests.uat.phases.enumerate import (
    Cell,
    CompatibilityPrunedCell,
    enumerate_cells_with_pruning,
)
from tests.uat.phases.preflight import free_space_gib as default_free_space_reader
from tests.uat.runner import CellResult, classify_for_submit, run_cell, submit_state_is_cell_failure


@dataclass(frozen=True)
class DockerLifecycleEvent:
    """Structured Docker lifecycle record for logs/tests."""

    platform: str
    action: str
    status: str
    project_name: str | None
    message: str
    result: docker_assets.DockerCommandResult | None = None
    free_space_gib: float | None = None


@dataclass(frozen=True)
class ExecuteOutcome(PhaseResult):
    """Aggregated outcome of run_execute."""

    results: tuple[CellResult, ...]
    pruned: tuple[Cell, ...]
    skipped_unreachable: tuple[Cell, ...]
    compatibility_pruned: tuple[CompatibilityPrunedCell, ...] = ()
    docker_events: tuple[DockerLifecycleEvent, ...] = ()

    def exit_code(self) -> int:
        if self.aborted:
            return 2
        return 0 if all(result.status == "passed" for result in self.results) else 1


@dataclass(frozen=True)
class _DockerPlatformState:
    spec: docker_assets.DockerPlatformSpec | None = None
    project_name: str | None = None
    started: bool = False
    cleanup_status: str = "not-run"


DockerRunner = Callable[..., docker_assets.DockerCommandResult]
FreeSpaceReader = Callable[[str | Path], float]


def run_execute(
    config: UATConfig,
    *,
    log_dir: Path | None = None,
    benchmark_runs_dir: Path | None = None,
    databases_root: Path | None = None,
    cleanup_enabled: bool = True,
    runner=None,
    docker_runner: DockerRunner | None = None,
    free_space_checks_enabled: bool = False,
    free_space_path: Path | str | None = None,
    free_space_min_gib: float | None = None,
    free_space_reader: FreeSpaceReader | None = None,
) -> ExecuteOutcome:
    """Walk the matrix sequentially with ladder pruning and platform-boundary cleanup.

    Parameters mirror the spec's W4 execute phase. `runner`, `docker_runner`,
    and `free_space_reader` are injectable so fast tests can drive the loop
    without spawning subprocesses or requiring a live Docker daemon. Resolves
    the module-level `run_cell` lazily so monkeypatching
    `tests.uat.phases.execute.run_cell` from a test takes effect.
    """
    if runner is None:
        runner = run_cell
    if docker_runner is None:
        docker_runner = docker_assets.run_docker_command
    if free_space_reader is None:
        free_space_reader = default_free_space_reader
    assert config.execute.parallel_platforms is False, "parallel_platforms must remain False — UAT W3 line 222"
    benchmark_runs_dir = (
        Path(benchmark_runs_dir).expanduser() if benchmark_runs_dir is not None else default_benchmark_runs_dir(config)
    )
    if free_space_path is None:
        free_space_path = config.preflight.free_space_path or benchmark_runs_dir
    if free_space_min_gib is None:
        free_space_min_gib = config.preflight.free_space_min_gib

    enumeration = enumerate_cells_with_pruning(config)
    cells = list(enumeration.cells)
    by_pb: dict[tuple[str, str], list[Cell]] = defaultdict(list)
    for cell in cells:
        by_pb[(cell.platform, cell.benchmark)].append(cell)
    # Sort each (platform, benchmark) by ascending scale so the ladder
    # walk is deterministic.
    for key in by_pb:
        by_pb[key].sort(key=lambda c: c.scale)

    # Reorder by_pb so that for each platform, registry-declared data
    # sources come before their consumers. Without this,
    # `include: [read_primitives, tpch]` (or a future registry change
    # that moves consumer-categories ahead of sources) would attempt to
    # run a consumer before the source has loaded its DB.
    by_pb = _reorder_for_topology(by_pb)
    by_platform = _group_by_platform(by_pb)

    results: list[CellResult] = []
    pruned: list[Cell] = []
    skipped_unreachable: list[Cell] = []
    docker_events: list[DockerLifecycleEvent] = []
    completed_pairs: set[tuple[str, str]] = set()
    already_pruned: set[tuple[str, str, float]] = set()
    last_completed_platform: str | None = None
    last_docker_cleanup_status = "not-run"
    abort_reason: str | None = None

    for platform, platform_pairs in by_platform:
        platform_abort_reason = _free_space_abort_reason(
            enabled=free_space_checks_enabled,
            path=free_space_path,
            min_gib=free_space_min_gib,
            reader=free_space_reader,
            last_completed_platform=last_completed_platform,
            docker_cleanup_status=last_docker_cleanup_status,
            context=f"before starting platform {platform}",
            log_dir=log_dir,
        )
        docker_state = _DockerPlatformState(cleanup_status=last_docker_cleanup_status)

        try:
            if platform_abort_reason is None:
                docker_state, platform_abort_reason = _start_docker_platform_if_needed(
                    config,
                    platform=platform,
                    benchmark_runs_dir=benchmark_runs_dir,
                    docker_runner=docker_runner,
                    docker_events=docker_events,
                    log_dir=log_dir,
                )
                last_docker_cleanup_status = docker_state.cleanup_status
            if platform_abort_reason is None:
                _run_or_skip_platform(
                    config,
                    platform=platform,
                    platform_pairs=platform_pairs,
                    by_pb=by_pb,
                    results=results,
                    pruned=pruned,
                    skipped_unreachable=skipped_unreachable,
                    completed_pairs=completed_pairs,
                    already_pruned=already_pruned,
                    databases_root=databases_root,
                    cleanup_enabled=cleanup_enabled,
                    runner=runner,
                    log_dir=log_dir,
                    benchmark_runs_dir=benchmark_runs_dir,
                )
        finally:
            docker_state, teardown_abort_reason = _teardown_docker_platform_if_needed(
                config,
                platform=platform,
                docker_state=docker_state,
                benchmark_runs_dir=benchmark_runs_dir,
                docker_runner=docker_runner,
                docker_events=docker_events,
                free_space_checks_enabled=free_space_checks_enabled,
                free_space_path=free_space_path,
                free_space_min_gib=free_space_min_gib,
                free_space_reader=free_space_reader,
                log_dir=log_dir,
            )
            last_docker_cleanup_status = docker_state.cleanup_status
            if platform_abort_reason is None:
                platform_abort_reason = teardown_abort_reason

        if platform_abort_reason is not None:
            abort_reason = platform_abort_reason
            break
        last_completed_platform = platform

    return ExecuteOutcome(
        phase="execute",
        results=tuple(results),
        pruned=tuple(pruned),
        skipped_unreachable=tuple(skipped_unreachable),
        compatibility_pruned=enumeration.compatibility_pruned,
        docker_events=tuple(docker_events),
        aborted=abort_reason is not None,
        abort_reason=abort_reason,
    )


def _start_docker_platform_if_needed(
    config: UATConfig,
    *,
    platform: str,
    benchmark_runs_dir: Path,
    docker_runner: DockerRunner,
    docker_events: list[DockerLifecycleEvent],
    log_dir: Path | None,
) -> tuple[_DockerPlatformState, str | None]:
    if not docker_assets.is_docker_platform(platform):
        return _DockerPlatformState(), None

    spec = docker_assets.docker_platform_spec(platform)
    if not config.cleanup.docker_manage_platforms:
        _record_docker_event(
            docker_events,
            log_dir=log_dir,
            platform=platform,
            action="manage",
            status="disabled",
            project_name=None,
            message="cleanup.docker_manage_platforms=false; probing externally managed stack only",
        )
        return _DockerPlatformState(spec=spec, cleanup_status="disabled-external"), None

    project_name = docker_assets.compose_project_name(
        config.name,
        platform,
        config.cleanup.docker_project_prefix,
    )
    try:
        docker_assets.validate_managed_start_allowed(
            spec,
            config.cleanup.docker_fixed_container_name_policy,
        )
    except docker_assets.DockerAssetError as exc:
        return _DockerPlatformState(spec=spec, project_name=project_name), str(exc)

    up_result = docker_runner(
        docker_assets.compose_up_command(
            spec,
            project_name,
            start_timeout_s=config.cleanup.docker_start_timeout_s,
        ),
        dry_run=config.dry_run,
        timeout_s=config.cleanup.docker_start_timeout_s,
        cwd=docker_assets.REPO_ROOT,
        env=docker_assets.compose_environment(spec, benchmark_runs_dir=benchmark_runs_dir),
    )
    _record_docker_event(
        docker_events,
        log_dir=log_dir,
        platform=platform,
        action="up",
        status="ok" if up_result.succeeded else "failed",
        project_name=project_name,
        message=_docker_result_message(up_result),
        result=up_result,
    )
    state = _DockerPlatformState(
        spec=spec,
        project_name=project_name,
        started=True,
        cleanup_status="started" if up_result.succeeded else "startup-failed",
    )
    if up_result.succeeded:
        invalidate_reachability_cache_after_lifecycle_change()
        return state, None
    return (
        state,
        f"UAT-managed Docker startup failed for {platform} project {project_name}: {_docker_result_message(up_result)}",
    )


def _teardown_docker_platform_if_needed(
    config: UATConfig,
    *,
    platform: str,
    docker_state: _DockerPlatformState,
    benchmark_runs_dir: Path,
    docker_runner: DockerRunner,
    docker_events: list[DockerLifecycleEvent],
    free_space_checks_enabled: bool,
    free_space_path: Path | str,
    free_space_min_gib: float,
    free_space_reader: FreeSpaceReader,
    log_dir: Path | None,
) -> tuple[_DockerPlatformState, str | None]:
    if not docker_state.started or docker_state.spec is None or docker_state.project_name is None:
        return docker_state, None

    cleanup_status, cleanup_abort_reason = _run_docker_teardown(
        config,
        platform=platform,
        docker_state=docker_state,
        benchmark_runs_dir=benchmark_runs_dir,
        docker_runner=docker_runner,
        docker_events=docker_events,
        log_dir=log_dir,
    )
    state = _DockerPlatformState(
        spec=docker_state.spec,
        project_name=docker_state.project_name,
        started=docker_state.started,
        cleanup_status=cleanup_status,
    )
    abort_reason = _free_space_abort_reason(
        enabled=free_space_checks_enabled,
        path=free_space_path,
        min_gib=free_space_min_gib,
        reader=free_space_reader,
        last_completed_platform=platform,
        docker_cleanup_status=cleanup_status,
        context=f"after Docker teardown for platform {platform}",
        log_dir=log_dir,
    )
    return state, cleanup_abort_reason or abort_reason


def _run_docker_teardown(
    config: UATConfig,
    *,
    platform: str,
    docker_state: _DockerPlatformState,
    benchmark_runs_dir: Path,
    docker_runner: DockerRunner,
    docker_events: list[DockerLifecycleEvent],
    log_dir: Path | None,
) -> tuple[str, str | None]:
    assert docker_state.spec is not None
    assert docker_state.project_name is not None
    if config.cleanup.docker_platform_switch == "off":
        _record_docker_event(
            docker_events,
            log_dir=log_dir,
            platform=platform,
            action="down",
            status="off",
            project_name=docker_state.project_name,
            message="cleanup.docker_platform_switch=off; UAT-managed Docker teardown skipped",
        )
        return "off", None

    down_result = docker_runner(
        docker_assets.compose_down_command(
            docker_state.spec,
            docker_state.project_name,
            config.cleanup.docker_platform_switch,
        ),
        dry_run=config.dry_run,
        timeout_s=config.cleanup.docker_start_timeout_s,
        cwd=docker_assets.REPO_ROOT,
        env=docker_assets.compose_environment(docker_state.spec, benchmark_runs_dir=benchmark_runs_dir),
    )
    cleanup_status = "ok" if down_result.succeeded else "failed"
    _record_docker_event(
        docker_events,
        log_dir=log_dir,
        platform=platform,
        action="down",
        status=cleanup_status,
        project_name=docker_state.project_name,
        message=_docker_result_message(down_result),
        result=down_result,
    )
    if down_result.succeeded:
        return cleanup_status, None
    return (
        cleanup_status,
        f"UAT-managed Docker cleanup failed for {platform} project {docker_state.project_name}: "
        f"{_docker_result_message(down_result)}",
    )


def _run_or_skip_platform(
    config: UATConfig,
    *,
    platform: str,
    platform_pairs: list[tuple[str, list[Cell]]],
    by_pb: dict[tuple[str, str], list[Cell]],
    results: list[CellResult],
    pruned: list[Cell],
    skipped_unreachable: list[Cell],
    completed_pairs: set[tuple[str, str]],
    already_pruned: set[tuple[str, str, float]],
    databases_root: Path | None,
    cleanup_enabled: bool,
    runner,
    log_dir: Path | None,
    benchmark_runs_dir: Path,
) -> None:
    platform_cells = [cell for _, pb_cells in platform_pairs for cell in pb_cells]
    if config.execute.skip_unreachable and not platform_is_reachable(platform):
        skipped_unreachable.extend(platform_cells)
        return
    for benchmark, pb_cells in platform_pairs:
        _run_platform_benchmark(
            config,
            platform=platform,
            benchmark=benchmark,
            pb_cells=pb_cells,
            by_pb=by_pb,
            results=results,
            pruned=pruned,
            completed_pairs=completed_pairs,
            already_pruned=already_pruned,
            databases_root=databases_root,
            cleanup_enabled=cleanup_enabled,
            runner=runner,
            log_dir=log_dir,
            benchmark_runs_dir=benchmark_runs_dir,
        )


def _run_platform_benchmark(
    config: UATConfig,
    *,
    platform: str,
    benchmark: str,
    pb_cells: list[Cell],
    by_pb: dict[tuple[str, str], list[Cell]],
    results: list[CellResult],
    pruned: list[Cell],
    completed_pairs: set[tuple[str, str]],
    already_pruned: set[tuple[str, str, float]],
    databases_root: Path | None,
    cleanup_enabled: bool,
    runner,
    log_dir: Path | None,
    benchmark_runs_dir: Path,
) -> None:
    ladder_rungs = [c.scale for c in pb_cells]
    observed: list[LadderRung] = []
    for cell in pb_cells:
        _, pruned_rungs = plan_ladder(
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
            local_managed_platform=config.cleanup.docker_manage_platforms
            and docker_assets.is_docker_platform(cell.platform),
            log_dir=log_dir,
            benchmark_runs_dir=benchmark_runs_dir,
        )
        cell_result = _apply_submit_classification(cell_result)
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


def _apply_submit_classification(cell_result: CellResult) -> CellResult:
    """Mirror submit refusals for any runner that returned a result JSON."""
    if cell_result.status != "passed" or cell_result.result_path is None or not cell_result.result_path.exists():
        return cell_result
    submit_state = classify_for_submit(cell_result.result_path)
    if submit_state.value == cell_result.submit_terminal_state and not submit_state_is_cell_failure(submit_state):
        return cell_result
    return replace(
        cell_result,
        status="failed" if submit_state_is_cell_failure(submit_state) else cell_result.status,
        exit_code=(cell_result.exit_code or 1) if submit_state_is_cell_failure(submit_state) else cell_result.exit_code,
        submit_terminal_state=submit_state.value,
    )


def _reorder_for_topology(
    by_pb: dict[tuple[str, str], list[Cell]],
) -> dict[tuple[str, str], list[Cell]]:
    """Reorder by_pb so for each platform, sources precede their consumers.

    Reuse graph from registry `data_source` metadata (e.g. tpch is a
    source for read_primitives etc.). The topological sort is stable:
    benchmarks not constrained by the graph keep their original relative
    order.
    """
    consumer_to_sources: dict[str, list[str]] = {}
    for source, consumers in source_reuse_graph().items():
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


def _group_by_platform(
    by_pb: dict[tuple[str, str], list[Cell]],
) -> list[tuple[str, list[tuple[str, list[Cell]]]]]:
    """Group ordered (platform, benchmark) cells by platform."""
    grouped: list[tuple[str, list[tuple[str, list[Cell]]]]] = []
    index: dict[str, list[tuple[str, list[Cell]]]] = {}
    for (platform, benchmark), pb_cells in by_pb.items():
        if platform not in index:
            bucket: list[tuple[str, list[Cell]]] = []
            index[platform] = bucket
            grouped.append((platform, bucket))
        index[platform].append((benchmark, pb_cells))
    return grouped


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
            # The registry-derived reuse graph is expected to be acyclic, but preserve
            # deterministic progress if a future edit introduces a cycle.
            ready = next(b for b in benchmarks if b in pending)
        pending.remove(ready)
        out.append(ready)
        for dependent in dependents.get(ready, ()):  # pragma: no branch - tiny loop
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


def _free_space_abort_reason(
    *,
    enabled: bool,
    path: Path | str,
    min_gib: float,
    reader: FreeSpaceReader,
    last_completed_platform: str | None,
    docker_cleanup_status: str,
    context: str,
    log_dir: Path | None,
) -> str | None:
    if not enabled or min_gib <= 0:
        return None
    free_gib = reader(path)
    _append_lifecycle_log(
        log_dir,
        f"[free-space] {context}: {free_gib:.2f} GiB free at {path} "
        f"(threshold {min_gib:.2f} GiB, docker_cleanup_status={docker_cleanup_status})",
    )
    if free_gib >= min_gib:
        return None
    last_platform = last_completed_platform or "none"
    return (
        f"free space {free_gib:.2f} GiB < cutoff {min_gib:.2f} GiB at {path} "
        f"{context}; last_completed_platform={last_platform}; "
        f"docker_cleanup_status={docker_cleanup_status}"
    )


def _record_docker_event(
    events: list[DockerLifecycleEvent],
    *,
    log_dir: Path | None,
    platform: str,
    action: str,
    status: str,
    project_name: str | None,
    message: str,
    result: docker_assets.DockerCommandResult | None = None,
    free_space_gib: float | None = None,
) -> None:
    event = DockerLifecycleEvent(
        platform=platform,
        action=action,
        status=status,
        project_name=project_name,
        message=message,
        result=result,
        free_space_gib=free_space_gib,
    )
    events.append(event)
    command = f" command={result.command}" if result is not None else ""
    _append_lifecycle_log(
        log_dir,
        f"[docker] platform={platform} action={action} status={status} project={project_name}"
        f"{command} message={message}",
    )


def _docker_result_message(result: docker_assets.DockerCommandResult) -> str:
    if result.dry_run:
        return "dry-run: command recorded but not executed"
    if result.succeeded:
        return "command completed successfully"
    detail = result.error or result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
    if result.timed_out:
        detail = result.error or detail
    return detail


def _append_lifecycle_log(log_dir: Path | None, line: str) -> None:
    if log_dir is None:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "uat_lifecycle.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{_dt.datetime.now().isoformat(timespec='seconds')} {line}\n")


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

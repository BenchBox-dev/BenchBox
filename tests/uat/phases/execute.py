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
import os
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tests.uat import docker_assets
from tests.uat.cleanup import CellKey, can_prune, prune_database_dir, source_reuse_graph
from tests.uat.clickhouse_memory import runtime_limit_matches_rung
from tests.uat.config import OutputConfig, UATConfig
from tests.uat.ladder import LadderRung, plan_ladder
from tests.uat.matrix import (
    invalidate_reachability_cache_after_lifecycle_change,
    platform_is_reachable,
    probe_platform_reachability,
)
from tests.uat.phases import PhaseResult
from tests.uat.phases.enumerate import (
    Cell,
    CompatibilityPrunedCell,
    enumerate_cells_with_pruning,
)
from tests.uat.preflight_budget import (
    MemorySnapshot,
    check_memory_headroom,
    format_memory_headroom_failure,
    free_space_gib as default_free_space_reader,
    read_memory_snapshot as default_free_memory_reader,
)
from tests.uat.runner import CellResult, run_cell

# Frozen-dataclass default instance, used to render the schema-default
# templates for BENCHBOX_OUTPUT_DIR suffix splicing -- see
# _resolve_output_base. Whether a config's output.*_template was explicitly
# set in YAML is tracked by provenance on OutputConfig.explicitly_set, NOT by
# comparing against these defaults (a config that explicitly sets a template
# to a string equal to the default must still count as explicit).
_DEFAULT_OUTPUT = OutputConfig()

# BENCHBOX_OUTPUT_DIR (uat-operator-provisioning w2): bare `uat-cell` runs
# already honor this env var as the runs root (tests.uat.runner._default_*_dir).
# Sweeps did not -- default_log_dir/default_benchmark_runs_dir below resolved
# only from the YAML output.* templates, so docs telling operators to "set
# BENCHBOX_OUTPUT_DIR for sweeps" (uat-framework.md, AGENTS.md) were false for
# every checked-in config, which all use the DEFAULT templates. Honor the env
# var as the base ONLY when the template key was left unset in YAML -- an
# explicit YAML template always wins (no silent root switching for a
# configured sweep), even when its value happens to match the schema default
# string (see uat-operator-provisioning review response, 2026-07-19).
BENCHBOX_OUTPUT_DIR_ENV_VAR = "BENCHBOX_OUTPUT_DIR"


def _resolve_output_base(template: str, default_template: str, *, explicit: bool) -> str:
    """Splice `BENCHBOX_OUTPUT_DIR` in as the base directory when `template`
    was left unset in YAML (`explicit=False`) and the env var is set;
    otherwise return `template` unchanged (explicit YAML templates always
    win -- gated on provenance, not on `template == default_template`, so a
    config that explicitly sets a template to the default string is still
    honored as explicit)."""
    if explicit:
        return template
    override = os.environ.get(BENCHBOX_OUTPUT_DIR_ENV_VAR)
    if not override:
        return template
    default_base = _DEFAULT_OUTPUT.benchmark_runs_dir_template
    if not default_template.startswith(default_base):
        return template  # defensive; schema defaults changed shape unexpectedly.
    suffix = default_template[len(default_base) :]
    return override.rstrip("/") + suffix


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
    # Cells for a platform whose managed Docker stack never started
    # (compose-up failure) -- distinct from `skipped_unreachable` (a
    # reachability probe that found nothing listening). Kept as its own
    # collection rather than folded into `skipped_unreachable` so accounting
    # can tell "stack failed to start" from "TCP probe found nothing
    # listening" -- see uat-fail-advance-consistency w3.
    startup_failed: tuple[Cell, ...] = ()
    # Cells not run because the platform's stack was reachable when the
    # platform started and had STOPPED being reachable by the time the cell
    # was about to run -- the 2026-08-04 CedarDB failure mode, where the
    # container died ~29s after `up --wait` returned and all 171 remaining
    # cells were recorded as ordinary cell failures.
    #
    # Its own bucket, deliberately not folded into any existing one:
    #   - not `results`: these cells never ran, and recording them as
    #     failures is the exact miscount this exists to stop;
    #   - not `startup_failed`: the stack DID start, and saying otherwise is
    #     a second false claim about the same incident;
    #   - not `skipped_unreachable`: that means "never found listening", a
    #     platform we skipped over. This one was up and then died, which is
    #     an infrastructure fault worth surfacing, not a clean skip.
    died_mid_platform: tuple[Cell, ...] = ()
    compatibility_pruned: tuple[CompatibilityPrunedCell, ...] = ()
    docker_events: tuple[DockerLifecycleEvent, ...] = ()
    # Typed cause for `aborted` -- e.g. "disk_floor", "docker_startup",
    # "docker_teardown". None when not aborted. Consumers must branch on this
    # field, never on substrings of `abort_reason` (a human-facing message
    # that can be reworded without notice) -- see
    # uat-execute-path-unification w5. Not part of the cells.jsonl schema;
    # do not thread it into cells_io.write_cells_jsonl.
    abort_kind: str | None = None

    def exit_code(self) -> int:
        if self.aborted:
            return 2
        # `all(... for result in self.results)` is vacuously True when
        # `self.results` is empty (e.g. every platform was unreachable, or
        # every managed Docker compose-up failed) -- that must not read as a
        # clean sweep. Zero results = nonzero exit is deliberate: a
        # degenerate config whose whole matrix is compatibility-pruned exits
        # 1 here even though the report phase would exit 0 for it (pruned
        # cells count as "skipped", not failures, in ReportSummary.exit_code()).
        if not self.results:
            return 1
        # A stack dying mid-platform is a real failure of the sweep, not a
        # clean skip: cells that were supposed to run did not, because the
        # infrastructure under them went away. It must not be possible for a
        # sweep to lose a platform mid-run and still exit 0 -- that is the
        # quiet-and-wrong shape of the original bug, just relocated.
        if self.died_mid_platform:
            return 1
        return 0 if all(result.status == "passed" for result in self.results) else 1


class _PlatformDiedMidRun(Exception):
    """Internal control-flow signal: a platform's stack died partway through its cells.

    Raised by `_run_platform_benchmark`'s per-cell liveness probe and caught
    by `_run_or_skip_platform`, which is the only scope that can see the
    platform's remaining benchmarks. An exception rather than a return flag
    because unwinding is the point: the interrupted benchmark must NOT fall
    through to its `completed_pairs.add(...)` / database-pruning tail, which
    would mark a half-run pair as finished.

    Never escapes `_run_or_skip_platform`.
    """

    def __init__(self, *, platform: str, remaining_cells: list[Cell]) -> None:
        super().__init__(f"{platform} stopped being reachable mid-run")
        self.platform = platform
        self.remaining_cells = remaining_cells


@dataclass(frozen=True)
class _DockerPlatformState:
    spec: docker_assets.DockerPlatformSpec | None = None
    project_name: str | None = None
    started: bool = False
    cleanup_status: str = "not-run"


DockerRunner = Callable[..., docker_assets.DockerCommandResult]
FreeSpaceReader = Callable[[str | Path], float]
FreeMemoryReader = Callable[[], MemorySnapshot]
SleepFn = Callable[[float], None]


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
    memory_reader: FreeMemoryReader | None = None,
    sleep_fn: SleepFn | None = None,
) -> ExecuteOutcome:
    """Walk the matrix sequentially with ladder pruning and platform-boundary cleanup.

    Parameters mirror the spec's W4 execute phase. `runner`, `docker_runner`,
    `free_space_reader`, `memory_reader`, and `sleep_fn` are injectable so
    fast tests can drive the loop without spawning subprocesses, requiring a
    live Docker daemon, reading real host memory, or waiting out the
    post-start settle window. Resolves the module-level `run_cell` lazily so
    monkeypatching `tests.uat.phases.execute.run_cell` from a test takes
    effect.

    Submit classification is the runner's contract, not this phase's: the
    real `run_cell` (runner.py:256-260) classifies the exported result JSON
    and downgrades a passed cell before returning, so `run_execute` treats
    every `CellResult` it receives as already classified. Injected test
    runners must do the same (see
    test_execute_downgrades_passed_cell_with_query_failure_result).

    Unlike the free-space check (`free_space_checks_enabled`, an explicit
    opt-in flag the orchestrator sets from `config.disk_gate_enabled`), the
    Docker-startup readiness re-check and the free-memory gate are driven
    directly off `config` -- `config.cleanup.docker_manage_platforms` and
    `config.preflight.free_memory_min_gib` -- with no separate enable flag,
    so every caller (including the orchestrator, unchanged) gets both for
    free the moment `docker_manage_platforms: true` is set.
    """
    if runner is None:
        runner = run_cell
    if docker_runner is None:
        docker_runner = docker_assets.run_docker_command
    if free_space_reader is None:
        free_space_reader = default_free_space_reader
    if memory_reader is None:
        memory_reader = default_free_memory_reader
    if sleep_fn is None:
        sleep_fn = time.sleep
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
    startup_failed: list[Cell] = []
    died_mid_platform: list[Cell] = []
    docker_events: list[DockerLifecycleEvent] = []
    completed_pairs: set[tuple[str, str]] = set()
    already_pruned: set[tuple[str, str, float]] = set()
    last_completed_platform: str | None = None
    last_docker_cleanup_status = "not-run"
    abort_reason: str | None = None
    abort_kind: str | None = None

    for platform, platform_pairs in by_platform:
        platform_abort_reason, platform_abort_kind = _pre_start_abort_reason(
            config,
            platform=platform,
            free_space_checks_enabled=free_space_checks_enabled,
            free_space_path=free_space_path,
            free_space_min_gib=free_space_min_gib,
            free_space_reader=free_space_reader,
            memory_reader=memory_reader,
            last_completed_platform=last_completed_platform,
            docker_cleanup_status=last_docker_cleanup_status,
            log_dir=log_dir,
        )
        docker_state = _DockerPlatformState(cleanup_status=last_docker_cleanup_status)

        docker_startup_failed = False
        try:
            if platform_abort_reason is None:
                docker_state, startup_reason = _start_docker_platform_if_needed(
                    config,
                    platform=platform,
                    benchmark_runs_dir=benchmark_runs_dir,
                    docker_runner=docker_runner,
                    docker_events=docker_events,
                    log_dir=log_dir,
                    sleep_fn=sleep_fn,
                    memory_reader=memory_reader,
                )
                last_docker_cleanup_status = docker_state.cleanup_status
                if startup_reason is not None:
                    # A managed Docker compose-up failure (e.g. the LakeSail
                    # Spark Connect service exceeding docker_start_timeout_s) is
                    # a per-platform infrastructure failure, not a global abort.
                    # The failure is already captured in docker_events /
                    # uat_lifecycle.log (action=up status=failed). Record this
                    # platform's cells as unreachable and advance to the next
                    # stack so one stack's startup failure cannot truncate the
                    # whole sweep. Genuine global aborts (free space, fixed
                    # container-name policy, teardown failure) still abort below.
                    # These cells are recorded in `startup_failed`, not
                    # `skipped_unreachable` -- a stack that never started is
                    # accounted separately from a reachability probe that
                    # found nothing listening (uat-fail-advance-consistency
                    # w3).
                    if docker_state.cleanup_status == "startup-failed":
                        startup_failed.extend(cell for _, pb_cells in platform_pairs for cell in pb_cells)
                        docker_startup_failed = True
                    else:
                        platform_abort_reason = startup_reason
                        platform_abort_kind = "docker_startup"
            if platform_abort_reason is None and not docker_startup_failed:
                try:
                    _run_or_skip_platform(
                        config,
                        platform=platform,
                        platform_pairs=platform_pairs,
                        by_pb=by_pb,
                        results=results,
                        pruned=pruned,
                        skipped_unreachable=skipped_unreachable,
                        died_mid_platform=died_mid_platform,
                        completed_pairs=completed_pairs,
                        already_pruned=already_pruned,
                        databases_root=databases_root,
                        cleanup_enabled=cleanup_enabled,
                        runner=runner,
                        log_dir=log_dir,
                        benchmark_runs_dir=benchmark_runs_dir,
                    )
                except Exception as exc:  # noqa: BLE001 - re-raised after annotation
                    # A mid-sweep DiskFloorAbort propagates out of the runner
                    # here, bypassing the normal ExecuteOutcome return.
                    # Annotate it with what the orchestrator needs to thread
                    # into the abort artifact instead of losing it (or, for
                    # compatibility_pruned, re-deriving it via a second,
                    # possibly-diverging enumeration). The platform teardown
                    # still runs via the enclosing `finally` before the
                    # exception propagates.
                    _annotate_disk_floor_abort(
                        exc,
                        skipped_unreachable=skipped_unreachable,
                        startup_failed=startup_failed,
                        died_mid_platform=died_mid_platform,
                        compatibility_pruned=enumeration.compatibility_pruned,
                    )
                    raise
        finally:
            docker_state, teardown_abort_reason, teardown_abort_kind = _teardown_docker_platform_if_needed(
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
                platform_abort_kind = teardown_abort_kind

        if platform_abort_reason is not None:
            abort_reason = platform_abort_reason
            abort_kind = platform_abort_kind
            break
        last_completed_platform = platform

    return ExecuteOutcome(
        phase="execute",
        results=tuple(results),
        pruned=tuple(pruned),
        skipped_unreachable=tuple(skipped_unreachable),
        startup_failed=tuple(startup_failed),
        died_mid_platform=tuple(died_mid_platform),
        compatibility_pruned=enumeration.compatibility_pruned,
        docker_events=tuple(docker_events),
        aborted=abort_reason is not None,
        abort_reason=abort_reason,
        abort_kind=abort_kind,
    )


def _start_docker_platform_if_needed(
    config: UATConfig,
    *,
    platform: str,
    benchmark_runs_dir: Path,
    docker_runner: DockerRunner,
    docker_events: list[DockerLifecycleEvent],
    log_dir: Path | None,
    sleep_fn: SleepFn,
    memory_reader: FreeMemoryReader,
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
        # A relative/empty BENCHBOX_DATA_DIR for a path-mirroring platform
        # (lakesail, velox) is a config problem, not a per-cell/per-query
        # failure -- it would break EVERY cell on this platform identically.
        # Treat it like validate_managed_start_allowed above: fail before
        # ever invoking compose, same DockerAssetError contract, same
        # abort-worthy handling below (uat-fail-advance-consistency:
        # pre-flight config errors abort, runtime compose-up failures
        # advance-past).
        compose_env = docker_assets.compose_environment(
            spec,
            benchmark_runs_dir=benchmark_runs_dir,
            memory_limit=config.preflight.clickhouse_memory_limit,
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
        env=compose_env,
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
    if not up_result.succeeded:
        state = _DockerPlatformState(
            spec=spec,
            project_name=project_name,
            started=True,
            cleanup_status="startup-failed",
        )
        return (
            state,
            f"UAT-managed Docker startup failed for {platform} project {project_name}: "
            f"{_docker_result_message(up_result)}",
        )
    # Invalidate BEFORE the readiness re-check below (not after, as before
    # this fix) so its reachability probe is fresh for the container that
    # just started, not a stale cached value from before it existed.
    invalidate_reachability_cache_after_lifecycle_change()

    # `up --wait` exiting 0 only proves the container reported
    # started/healthy AT THAT INSTANT -- observed 2026-08-04: mocker
    # reported CedarDB Started, then `mocker compose ps` showed it Exited
    # ~29s later, and UAT ran 171 cells against the dead stack before this
    # check existed. Re-check before trusting it. Skipped for a dry run:
    # nothing was actually started to settle or probe.
    if not config.dry_run:
        readiness_reason = _check_docker_platform_readiness(
            config,
            spec=spec,
            project_name=project_name,
            platform=platform,
            docker_runner=docker_runner,
            docker_events=docker_events,
            log_dir=log_dir,
            benchmark_runs_dir=benchmark_runs_dir,
            sleep_fn=sleep_fn,
            memory_reader=memory_reader,
        )
        if readiness_reason is not None:
            # A dedicated event: the "ps" event above only carries
            # `_docker_result_message`, which reports "command completed
            # successfully" for a `compose ps` that ran fine but found an
            # Exited/Restarting service -- the readiness verdict itself
            # (why THIS platform was routed to startup_failed) needs its
            # own line in uat_lifecycle.log.
            _record_docker_event(
                docker_events,
                log_dir=log_dir,
                platform=platform,
                action="readiness",
                status="failed",
                project_name=project_name,
                message=readiness_reason,
            )
            state = _DockerPlatformState(
                spec=spec,
                project_name=project_name,
                started=True,
                cleanup_status="startup-failed",
            )
            return state, readiness_reason

    state = _DockerPlatformState(
        spec=spec,
        project_name=project_name,
        started=True,
        cleanup_status="started",
    )
    return state, None


def _check_docker_platform_readiness(
    config: UATConfig,
    *,
    spec: docker_assets.DockerPlatformSpec,
    project_name: str,
    platform: str,
    docker_runner: DockerRunner,
    docker_events: list[DockerLifecycleEvent],
    log_dir: Path | None,
    benchmark_runs_dir: Path,
    sleep_fn: SleepFn,
    memory_reader: FreeMemoryReader,
) -> str | None:
    """Immediate-crash detector for a stack `up --wait` already reported started.

    Settles for `cleanup.docker_settle_s` (default 10s), then checks
    `compose ps -a` service state and probes host reachability.

    SCOPE -- read this before changing `docker_settle_s`. This check runs
    EXACTLY ONCE and has rendered its verdict about twelve seconds after
    `up --wait` returned. It therefore catches a container that is already
    dead by then: an immediate crash. It does NOT catch a container that
    dies later, and no value of `docker_settle_s` makes it: a one-shot
    check cannot cover an unbounded window. Concretely, it would NOT have
    caught the 2026-08-04 CedarDB incident, where the container died ~29s
    after `up --wait` returned -- do not claim otherwise. Deaths at
    arbitrary latency are covered by the per-cell liveness probe in
    `_run_platform_benchmark` (`execute.liveness_probe_timeout_s`), which
    is a separate mechanism; this one exists because failing a platform in
    twelve seconds is much cheaper than discovering it one cell later.

    Probes via `probe_platform_reachability`, the NO-CACHE variant,
    deliberately. Using the cached `platform_is_reachable` here wrote
    `True` into `matrix._REACHABILITY_CACHE`, which
    `_run_or_skip_platform`'s skip_unreachable check then read instead of
    probing -- so adding this check silently disabled the next check
    downstream of it. The cache is cleared only on lifecycle changes, never
    between here and the cells.

    A stack that fails either check here is reported exactly like a
    compose-up failure (same `startup-failed` routing in the caller): the
    platform's cells go to `startup_failed` and the sweep advances to the
    next stack instead of running cells against a dead stack (see
    uat-container-readiness-and-memory-headroom-gate w0/w1, and
    uat-docker-stack-recovery w2 for the advance-past-broken-stack policy
    this reuses).
    """
    sleep_fn(config.cleanup.docker_settle_s)

    ps_result = docker_runner(
        docker_assets.compose_ps_command(spec, project_name),
        dry_run=False,
        timeout_s=config.cleanup.docker_start_timeout_s,
        cwd=docker_assets.REPO_ROOT,
        env=docker_assets.compose_environment(
            spec,
            benchmark_runs_dir=benchmark_runs_dir,
            memory_limit=config.preflight.clickhouse_memory_limit,
        ),
    )
    _record_docker_event(
        docker_events,
        log_dir=log_dir,
        platform=platform,
        action="ps",
        status="ok" if ps_result.succeeded else "failed",
        project_name=project_name,
        message=_docker_result_message(ps_result),
        result=ps_result,
    )
    if not ps_result.succeeded:
        return (
            f"UAT readiness check for {platform} project {project_name} could not run `compose ps` "
            f"{config.cleanup.docker_settle_s}s after `up --wait` reported success: "
            f"{_docker_result_message(ps_result)}"
        )
    if not docker_assets.compose_ps_service_rows(ps_result.stdout):
        # Fail CLOSED on an empty table. `up --wait` just reported success
        # for this project and `ps -a` includes stopped containers, so "no
        # rows at all" means the project has no containers: they were
        # removed, or the project name does not match what was started.
        # Neither is a state to run a platform's whole cell list against,
        # and passing here would be the same fail-open shape as the missing
        # `-a` -- an empty result read as a healthy one.
        return (
            f"UAT-managed Docker readiness check failed for {platform} project {project_name}: "
            f"`compose ps -a` listed no services {config.cleanup.docker_settle_s}s "
            "after `up --wait` reported success"
        )
    unhealthy = docker_assets.compose_ps_unhealthy_services(ps_result.stdout)
    if unhealthy:
        return (
            f"UAT-managed Docker readiness check failed for {platform} project {project_name}: "
            f"service(s) {', '.join(unhealthy)} not ready {config.cleanup.docker_settle_s}s "
            "after `up --wait` reported success"
        )

    if not probe_platform_reachability(platform, timeout_s=config.execute.liveness_probe_timeout_s or 2.0):
        endpoint = docker_assets.host_reachability_endpoint(platform) or platform
        return (
            f"UAT-managed Docker readiness check failed for {platform} project {project_name}: "
            f"reachability probe to {endpoint} failed {config.cleanup.docker_settle_s}s after `up --wait` reported success"
        )
    return _check_clickhouse_runtime_memory(
        config,
        spec=spec,
        project_name=project_name,
        platform=platform,
        docker_runner=docker_runner,
        docker_events=docker_events,
        log_dir=log_dir,
        memory_reader=memory_reader,
    )


def _check_clickhouse_runtime_memory(
    config: UATConfig,
    *,
    spec: docker_assets.DockerPlatformSpec,
    project_name: str,
    platform: str,
    docker_runner: DockerRunner,
    docker_events: list[DockerLifecycleEvent],
    log_dir: Path | None,
    memory_reader: FreeMemoryReader,
) -> str | None:
    """Verify the selected ClickHouse limit and reserve after startup."""
    if platform != "clickhouse-server":
        return None
    try:
        selected_value, selected_bytes = docker_assets.resolve_clickhouse_memory_limit(
            config.preflight.clickhouse_memory_limit
        )
    except docker_assets.DockerAssetError as exc:
        return f"ClickHouse runtime memory admission could not resolve the selected request: {exc}"
    stats_result = docker_runner(
        docker_assets.compose_stats_command(spec, project_name),
        dry_run=False,
        timeout_s=config.cleanup.docker_start_timeout_s,
        cwd=docker_assets.REPO_ROOT,
        env=docker_assets.compose_environment(
            spec,
            benchmark_runs_dir=None,
            memory_limit=config.preflight.clickhouse_memory_limit,
        ),
    )
    runtime_limit = docker_assets.parse_runtime_memory_limit(stats_result.stdout)
    _record_docker_event(
        docker_events,
        log_dir=log_dir,
        platform=platform,
        action="memory-admission",
        status="ok" if stats_result.succeeded and runtime_limit is not None else "failed",
        project_name=project_name,
        message=(
            f"requested={selected_value} requested_bytes={selected_bytes} "
            f"runtime_limit_bytes={runtime_limit} reserve_gib={config.preflight.docker_memory_reserve_gib:.2f}"
        )
        if stats_result.succeeded
        else _docker_result_message(stats_result),
        result=stats_result,
    )
    if not stats_result.succeeded:
        return (
            f"ClickHouse runtime memory admission failed for {project_name}: stats could not be read: "
            f"{_docker_result_message(stats_result)}"
        )
    if runtime_limit is None:
        return (
            f"ClickHouse runtime memory admission failed for {project_name}: stats did not report a memory limit; "
            "refusing to infer one from host RAM or an engine default"
        )
    if not runtime_limit_matches_rung(runtime_limit, selected_bytes / (1024**3), requested_bytes=selected_bytes):
        return (
            f"ClickHouse runtime memory admission failed for {project_name}: requested {selected_value} "
            f"({selected_bytes} bytes), runtime reported {runtime_limit} bytes"
        )
    snapshot = memory_reader()
    required_gib = selected_bytes / (1024**3) + config.preflight.docker_memory_reserve_gib
    append_lifecycle_log(
        log_dir,
        f"[memory-runtime] platform={platform} project={project_name} available_gib={snapshot.free_gib} "
        f"request_gib={selected_bytes / (1024**3):.3f} reserve_gib={config.preflight.docker_memory_reserve_gib:.3f} "
        f"required_gib={required_gib:.3f} swap_used_percent={snapshot.swap_used_percent}",
    )
    if snapshot.free_gib is None:
        return (
            f"ClickHouse runtime memory admission failed for {project_name}: host available memory could not be "
            "measured after startup; refusing to continue without request plus reserve evidence"
        )
    if snapshot.free_gib < required_gib:
        return (
            f"ClickHouse runtime memory admission failed for {project_name}: {snapshot.free_gib:.2f} GiB available "
            f"< {required_gib:.2f} GiB required ({selected_value} request + "
            f"{config.preflight.docker_memory_reserve_gib:.2f} GiB reserve)"
        )
    return None


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
) -> tuple[_DockerPlatformState, str | None, str | None]:
    if not docker_state.started or docker_state.spec is None or docker_state.project_name is None:
        return docker_state, None, None

    # A stack whose OWN startup already failed already advanced the sweep at
    # the #700 FAIL-and-advance decision point above (`run_execute`,
    # docker_startup_failed). `started=True` is still set unconditionally so
    # this teardown runs -- a partially-started compose stack can still leak
    # containers/volumes -- but if teardown on that SAME broken stack also
    # fails, that must not defeat the advance-past-broken-stack intent by
    # turning into a GLOBAL abort. Only a stack that started successfully
    # makes an undoable teardown failure a genuine resource-leak emergency
    # worth aborting the whole sweep for -- see
    # uat-fail-advance-consistency w4.
    stack_started_successfully = docker_state.cleanup_status == "started"

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
    if cleanup_abort_reason is not None:
        if stack_started_successfully:
            return state, cleanup_abort_reason, "docker_teardown"
        _record_docker_event(
            docker_events,
            log_dir=log_dir,
            platform=platform,
            action="down-policy",
            status="advance-after-startup-failed",
            project_name=docker_state.project_name,
            message=(
                "Teardown also failed for a stack whose own startup already failed; "
                f"advancing per FAIL-and-advance policy instead of a global abort: {cleanup_abort_reason}"
            ),
        )
    free_space_abort_reason = _free_space_abort_reason(
        enabled=free_space_checks_enabled,
        path=free_space_path,
        min_gib=free_space_min_gib,
        reader=free_space_reader,
        last_completed_platform=platform,
        docker_cleanup_status=cleanup_status,
        context=f"after Docker teardown for platform {platform}",
        log_dir=log_dir,
    )
    if free_space_abort_reason is not None:
        return state, free_space_abort_reason, "disk_floor"
    return state, None, None


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

    try:
        compose_env = docker_assets.compose_environment(
            docker_state.spec,
            benchmark_runs_dir=benchmark_runs_dir,
            memory_limit=config.preflight.clickhouse_memory_limit,
        )
    except docker_assets.DockerAssetError:
        # Teardown must never fail (or worse, raise out of run_execute's
        # `finally`) just because BENCHBOX_DATA_DIR is unset or relative --
        # `down` never mounts anything, so any absolute value lets compose
        # parse the file. A throwaway placeholder is fine here; the
        # Makefile's compose_down_fresh does the identical substitution for
        # `make test-docker-down-*`, for the identical reason (a stack
        # whose own startup failed for this exact config problem must still
        # be torn down -- uat-fail-advance-consistency w4).
        compose_env = {"BENCHBOX_DATA_DIR": str(docker_assets.REPO_ROOT)}

    down_result = docker_runner(
        docker_assets.compose_down_command(
            docker_state.spec,
            docker_state.project_name,
            config.cleanup.docker_platform_switch,
        ),
        dry_run=config.dry_run,
        timeout_s=config.cleanup.docker_start_timeout_s,
        cwd=docker_assets.REPO_ROOT,
        env=compose_env,
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
    # mocker 0.5.4's `compose down -v` leaks named volumes (live-validated in
    # uat-container-engine-routing w0); sweep them project-scoped, mirroring
    # the Makefile's compose_down_fresh macro (Makefile:452-463). Only when
    # `-v` was actually requested (cleanup_mode volumes/images) -- a
    # `containers`-mode teardown intentionally keeps volumes for reuse, and
    # sweeping them here would defeat that. Best-effort regardless of
    # `down_result` (matches the Makefile's `;` sequencing, not `&&`): a
    # stack whose `down` itself failed can still have created volumes worth
    # sweeping.
    if (
        config.cleanup.docker_platform_switch in {"volumes", "images"}
        and docker_assets.resolve_container_cli() == "mocker"
    ):
        removed_volumes = docker_assets.sweep_leaked_mocker_volumes(
            docker_state.project_name,
            docker_state.spec,
            runner=docker_runner,
            dry_run=config.dry_run,
        )
        _record_docker_event(
            docker_events,
            log_dir=log_dir,
            platform=platform,
            action="volume-sweep",
            status="ok",
            project_name=docker_state.project_name,
            message=(
                f"removed {len(removed_volumes)} leaked mocker named volume(s): {', '.join(removed_volumes)}"
                if removed_volumes
                else "no leaked mocker named volumes found"
            ),
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
    died_mid_platform: list[Cell],
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
    # Arm the per-cell liveness probe only for a platform that is reachable
    # RIGHT NOW, at the start of its cell list. The bucket means "was up,
    # then died"; arming against a platform that was never reachable would
    # relabel an ordinary never-listening platform (which `skip_unreachable:
    # false` configs deliberately still attempt) as a mid-run death. A
    # platform with no reachability endpoint at all (duckdb, ...) probes
    # True here and True forever after, so the probe never fires for it.
    liveness_armed = (
        config.execute.liveness_probe_timeout_s > 0
        and not config.dry_run
        and probe_platform_reachability(platform, timeout_s=config.execute.liveness_probe_timeout_s)
    )
    for index, (benchmark, pb_cells) in enumerate(platform_pairs):
        try:
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
                liveness_armed=liveness_armed,
            )
        except _PlatformDiedMidRun as died:
            # Everything this platform still owed: the rest of the benchmark
            # that was interrupted, plus every benchmark after it. The pair
            # is deliberately NOT added to `completed_pairs` (that happens
            # at the end of `_run_platform_benchmark`, which we skipped), so
            # database pruning does not treat a half-run pair as finished.
            died_mid_platform.extend(died.remaining_cells)
            for _later_benchmark, later_cells in platform_pairs[index + 1 :]:
                died_mid_platform.extend(later_cells)
            return


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
    liveness_armed: bool,
) -> None:
    ladder_rungs = [c.scale for c in pb_cells]
    observed: list[LadderRung] = []
    for index, cell in enumerate(pb_cells):
        _, pruned_rungs = plan_ladder(
            ladder_rungs,
            observed,
            early_stop_after_s=config.execute.early_stop_after_s,
            early_stop_on_failure=config.execute.early_stop_on_failure,
        )
        if cell.scale in pruned_rungs:
            pruned.append(cell)
            continue
        # Liveness probe, immediately before handing this cell to the
        # runner. This is the check that covers a stack dying at ARBITRARY
        # latency: the post-start readiness check renders its verdict once,
        # seconds after `up --wait`, and cannot see a death that happens an
        # hour into a platform's cell list.
        if liveness_armed and not probe_platform_reachability(
            platform, timeout_s=config.execute.liveness_probe_timeout_s
        ):
            endpoint = docker_assets.host_reachability_endpoint(platform) or platform
            append_lifecycle_log(
                log_dir,
                f"[liveness] {platform}/{benchmark}: probe to {endpoint} failed before cell "
                f"scale={cell.scale}; stack was reachable when the platform started. "
                f"Recording this and every remaining {platform} cell as died-mid-platform.",
            )
            raise _PlatformDiedMidRun(platform=platform, remaining_cells=list(pb_cells[index:]))
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
            official=config.execute.official,
            streams=config.execute.streams,
            seed=config.execute.seed,
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


def _annotate_disk_floor_abort(
    exc: BaseException,
    *,
    skipped_unreachable: list[Cell],
    startup_failed: list[Cell],
    died_mid_platform: list[Cell],
    compatibility_pruned: tuple[CompatibilityPrunedCell, ...],
) -> None:
    """Attach accounting the orchestrator needs to thread into abort artifacts.

    A mid-sweep DiskFloorAbort propagates out of `run_execute`, bypassing the
    normal `ExecuteOutcome` return. The skipped-unreachable and
    startup-failed counts, plus this run's actual compatibility-pruned
    enumeration, would otherwise be lost, forcing the orchestrator to either
    under-count `total_defined` or fall back to a second, possibly-diverging
    re-enumeration -- see uat-execute-path-unification w5 and
    uat-fail-advance-consistency w3.
    """
    if not hasattr(exc, "skipped_unreachable_count"):
        try:
            exc.skipped_unreachable_count = len(skipped_unreachable)  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            pass
    if not hasattr(exc, "startup_failed_count"):
        try:
            exc.startup_failed_count = len(startup_failed)  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            pass
    if not hasattr(exc, "died_mid_platform_count"):
        try:
            exc.died_mid_platform_count = len(died_mid_platform)  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            pass
    if not hasattr(exc, "compatibility_pruned"):
        try:
            exc.compatibility_pruned = compatibility_pruned  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            pass


def _pre_start_abort_reason(
    config: UATConfig,
    *,
    platform: str,
    free_space_checks_enabled: bool,
    free_space_path: Path | str,
    free_space_min_gib: float,
    free_space_reader: FreeSpaceReader,
    memory_reader: FreeMemoryReader,
    last_completed_platform: str | None,
    docker_cleanup_status: str,
    log_dir: Path | None,
) -> tuple[str | None, str | None]:
    """Combine the disk-floor and memory-floor platform-boundary gates.

    Disk takes precedence when both fire in the same call -- matches the
    existing precedence between the disk-floor and docker_required checks
    in `phases/preflight.py`'s `run_preflight`. Returns `(reason, kind)`;
    `kind` is one of "disk_floor", "memory_floor", or None.
    """
    context = f"before starting platform {platform}"
    disk_reason = _free_space_abort_reason(
        enabled=free_space_checks_enabled,
        path=free_space_path,
        min_gib=free_space_min_gib,
        reader=free_space_reader,
        last_completed_platform=last_completed_platform,
        docker_cleanup_status=docker_cleanup_status,
        context=context,
        log_dir=log_dir,
    )
    if disk_reason is not None:
        return disk_reason, "disk_floor"
    memory_reason = _free_memory_abort_reason(
        config=config,
        platform=platform,
        reader=memory_reader,
        context=context,
        log_dir=log_dir,
    )
    if memory_reason is not None:
        return memory_reason, "memory_floor"
    return None, None


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
    append_lifecycle_log(
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


def _free_memory_abort_reason(
    *,
    config: UATConfig,
    platform: str,
    reader: FreeMemoryReader,
    context: str,
    log_dir: Path | None,
) -> str | None:
    """Gate on measured host free memory before starting a Docker-managed platform.

    Mirrors `_free_space_abort_reason`'s shape and 0-disables convention
    (`preflight.free_memory_min_gib <= 0` disables the gate). Only relevant
    for Docker-managed platforms -- under mocker, each container is its own
    VM with independent memory sizing, so headroom must exist BEFORE the
    next VM is asked to start (2026-08-04 postmortem: 72 MB free of 16 GB,
    11.7 of 13.3 GB swap used; CedarDB's container reported "Running under
    cgroup memory limit: 1024 MB" and then failed to register an io_uring
    buffer). Gates on MEASURED free memory, never total RAM -- a 16 GB host
    with 72 MB free is not "fine" because it has 16 GB of capacity.

    Logs engine identity, the host free-memory reading (with swap pressure
    alongside, never gating on it), and this platform's declared VM/container
    memory request to uat_lifecycle.log on every call where the gate is
    enabled, regardless of pass/fail -- see
    uat-container-readiness-and-memory-headroom-gate w3.

    The comparison and the operator-facing message both come from
    `preflight_budget.check_memory_headroom` /
    `format_memory_headroom_failure` rather than being open-coded here, so
    the shipped message and the unit-tested one cannot diverge (the disk
    gate routes through `check_disk_headroom` /
    `format_disk_headroom_failure` the same way, at
    phases/preflight.py:264). This function contributes only the
    call-site context the primitives cannot know: which platform boundary
    it fired at, the resolved container engine, and that platform's
    declared VM memory request.
    """
    min_gib = config.preflight.free_memory_min_gib
    if min_gib <= 0 or not config.cleanup.docker_manage_platforms or not docker_assets.is_docker_platform(platform):
        return None

    try:
        engine = docker_assets.resolve_container_cli()
    except docker_assets.DockerAssetError as exc:
        engine = f"unresolved ({exc})"
    vm_request = _describe_platform_vm_request(platform)
    request_gib: float | None = None
    if platform == "clickhouse-server":
        try:
            _, request_bytes = docker_assets.resolve_clickhouse_memory_limit(config.preflight.clickhouse_memory_limit)
        except docker_assets.DockerAssetError as exc:
            return f"ClickHouse memory request is not admissible {context}: {exc}"
        request_gib = request_bytes / (1024**3)
        vm_request = f"clickhouse-server={request_gib:.3f} GiB"

    snapshot = reader()
    required_gib = min_gib
    if request_gib is not None:
        required_gib = max(min_gib, request_gib + config.preflight.docker_memory_reserve_gib)
    check = check_memory_headroom(snapshot, min_free_gib=required_gib)
    swap_note = f", swap {snapshot.swap_used_percent:.1f}% used" if snapshot.swap_used_percent is not None else ""
    if snapshot.free_gib is None and request_gib is not None:
        append_lifecycle_log(
            log_dir,
            f"[free-memory] {context}: engine={engine} vm_request={vm_request} "
            f"host available memory could not be measured; request-aware gate requires "
            f"{required_gib:.2f} GiB (reserve={config.preflight.docker_memory_reserve_gib:.2f} GiB); refusing startup",
        )
        return (
            f"memory request gate failed: host available memory could not be measured for {platform}; "
            f"{required_gib:.2f} GiB ({vm_request} + {config.preflight.docker_memory_reserve_gib:.2f} GiB reserve) "
            f"is required {context} (engine={engine})"
        )
    if snapshot.free_gib is None:
        # Free memory could not be measured on this host -- degrade safely:
        # log it and do NOT gate. Silently treating "unknown" as "healthy"
        # would defeat the gate on exactly the hosts most likely to need it
        # (e.g. a locked-down psutil-less sandbox); treating it as a hard
        # failure would break every host/platform combination where the
        # measurement is merely unavailable, including a perfectly healthy
        # Linux CI box.
        append_lifecycle_log(
            log_dir,
            f"[free-memory] {context}: engine={engine} vm_request={vm_request} "
            "free memory could not be measured on this host; gate skipped",
        )
        return None

    append_lifecycle_log(
        log_dir,
        f"[free-memory] {context}: engine={engine} vm_request={vm_request} "
        f"{snapshot.free_gib:.2f} GiB available (threshold {required_gib:.2f} GiB{swap_note}; "
        f"reserve={config.preflight.docker_memory_reserve_gib:.2f} GiB)",
    )
    if not check.shortfall:
        return None
    return f"{format_memory_headroom_failure(check)} {context} (engine={engine}, vm_request={vm_request})"


def _describe_platform_vm_request(platform: str) -> str:
    """One-line description of a Docker platform's declared memory request, for logging.

    Never raises. This value is pure log/message decoration on the memory
    gate's hot path, so any failure to derive it must degrade to a string --
    an exception escaping here would propagate out of `run_execute` and
    abort an entire multi-hour sweep because a compose file could not be
    summarized for one log line.
    """
    try:
        spec = docker_assets.docker_platform_spec(platform)
    except docker_assets.DockerAssetError:
        return "unknown (no compose spec)"
    try:
        limits = docker_assets.compose_declared_memory_limits(spec)
    except Exception as exc:  # noqa: BLE001 - decoration must never abort the sweep
        return f"unknown (could not read declared limits: {exc})"
    if not limits:
        return "no declared memory limit (engine default)"
    return ", ".join(f"{service}={limit}" for service, limit in sorted(limits.items()))


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
    append_lifecycle_log(
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


def append_lifecycle_log(log_dir: Path | None, line: str) -> None:
    """Append a timestamped line to uat_lifecycle.log. Public: also called from orchestrator.py (sweep-start engine identity, uat-container-engine-routing w2).

    The timestamp is offset-aware (``datetime.now().astimezone()``, not plain
    ``datetime.now()``) so a release-gate boundary comparison spanning a DST
    transition (see report.py's ``release_gate_ordering_violations``) can use
    each event's own recorded offset instead of having to assume one (#1179,
    #1202 follow-up).
    """
    if log_dir is None:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "uat_lifecycle.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{_dt.datetime.now().astimezone().isoformat(timespec='seconds')} {line}\n")


def default_log_dir(config: UATConfig, now: _dt.datetime | None = None) -> Path:
    """Resolve the YAML log_dir_template against {date}, {time}, and {name}.

    {time} (HHMMSS, expanded at sweep start alongside {date}) is what makes
    the DEFAULT template collision-free across same-day sweeps -- see
    uat-resume-retirement-artifact-durability. Templates that never mention
    {time} (every checked-in config predates this and only uses {date})
    render unchanged: `str.replace` is a no-op when the placeholder is
    absent, so existing explicit `logs_dir_template` values keep working
    verbatim.

    HHMMSS alone still collides when two sweeps using a {time} template
    start in the same second (e.g. automation kicking off multiple configs
    at once); since the log dir is now the durable record (no resume
    machinery to merge into it), a resolved path that already exists gets a
    numeric suffix appended until it names a fresh directory.

    `BENCHBOX_OUTPUT_DIR` overrides the base directory ONLY when
    `logs_dir_template` was left unset in YAML -- an explicit YAML template
    always wins, by provenance, even if its value equals the schema default
    (uat-operator-provisioning w2; see _resolve_output_base).
    """
    now = now or _dt.datetime.now()
    template = _resolve_output_base(
        config.output.logs_dir_template,
        _DEFAULT_OUTPUT.logs_dir_template,
        explicit="logs_dir_template" in config.output.explicitly_set,
    )
    rendered = (
        template.replace("{date}", now.strftime("%Y%m%d"))
        .replace("{time}", now.strftime("%H%M%S"))
        .replace("{name}", config.name)
    )
    path = Path(rendered).expanduser()
    if "{time}" in template:
        suffix = 2
        while path.exists():
            path = path.with_name(f"{path.name}-{suffix}")
            suffix += 1
    return path


def default_benchmark_runs_dir(config: UATConfig, now: _dt.datetime | None = None) -> Path:
    """Resolve the YAML benchmark_runs root against {date} and {name}.

    `BENCHBOX_OUTPUT_DIR` overrides the base directory ONLY when
    `benchmark_runs_dir_template` was left unset in YAML -- an explicit YAML
    template always wins, by provenance, even if its value equals the schema
    default (uat-operator-provisioning w2; see _resolve_output_base).
    """
    now = now or _dt.datetime.now()
    template = _resolve_output_base(
        config.output.benchmark_runs_dir_template,
        _DEFAULT_OUTPUT.benchmark_runs_dir_template,
        explicit="benchmark_runs_dir_template" in config.output.explicitly_set,
    )
    rendered = template.replace("{date}", now.strftime("%Y%m%d")).replace("{name}", config.name)
    return Path(rendered).expanduser()


def default_submissions_dir(config: UATConfig, now: _dt.datetime | None = None) -> Path:
    """Resolve the package submissions directory using the same output root."""
    now = now or _dt.datetime.now()
    template = _resolve_output_base(
        config.output.submissions_dir_template,
        _DEFAULT_OUTPUT.submissions_dir_template,
        explicit="submissions_dir_template" in config.output.explicitly_set,
    )
    rendered = template.replace("{date}", now.strftime("%Y%m%d")).replace("{name}", config.name)
    return Path(rendered).expanduser()

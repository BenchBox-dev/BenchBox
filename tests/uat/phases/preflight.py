"""Preflight phase: disk, docker, noisy-neighbor scan.

Mirrors the W1 step of the 2026-05-02 retrospective. Telemetry-first:
warns liberally, aborts only on `free_space_min_gib` unless an operator
opts in to local-platform reachability enforcement.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.uat.config import UATConfig

from tests.uat import docker_assets
from tests.uat.matrix import platform_is_reachable, reset_reachability_cache, resolve_platforms

REPO_ROOT = Path(__file__).resolve().parents[3]


def automated_local_platforms() -> tuple[str, ...]:
    """Derive the UAT-managed local platform set from `docker_assets`.

    Single source of truth: a platform is UAT-managed iff its
    `DockerPlatformSpec.managed_start_allowed` is true and it has no
    `fixed_container_names`. Mirrors the rule used by
    `scripts/uat-bring-up/uat_bring_up.py:automated_platforms`.
    """
    return tuple(
        sorted(
            platform
            for platform, spec in docker_assets.docker_platform_specs().items()
            if spec.managed_start_allowed and not spec.fixed_container_names
        )
    )


AUTOMATED_LOCAL_PLATFORMS: tuple[str, ...] = automated_local_platforms()

BringUpRunner = Callable[[str], int]
ReachabilityChecker = Callable[[str], bool]


@dataclass(frozen=True)
class PreflightResult:
    free_space_gib: float
    docker_reachable: bool
    host_load_1m: float | None
    aborted: bool
    abort_reason: str | None
    warnings: tuple[str, ...]
    local_platforms_checked: tuple[str, ...] = ()
    local_platforms_attempted: tuple[str, ...] = ()
    disk_budget_summary: str | None = None


def free_space_gib(path: str | Path) -> float:
    """Return free space at `path` in GiB."""
    p = Path(path).expanduser()
    if not p.exists():
        # Walk up to first existing ancestor so a missing log dir doesn't
        # falsely trigger the abort.
        p = next((ancestor for ancestor in p.parents if ancestor.exists()), Path("/"))
    usage = shutil.disk_usage(p)
    return usage.free / (1024**3)


def docker_reachable() -> bool:
    """Return True iff `docker ps` succeeds within 5 s."""
    try:
        subprocess.run(
            ["docker", "ps"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def host_load_1m() -> float | None:
    """Return the 1-minute load average, or None on platforms without getloadavg."""
    try:
        return os.getloadavg()[0]
    except (AttributeError, OSError):
        return None


def requested_platforms_from_raw(raw: dict) -> tuple[str, ...]:
    """Resolve the platforms requested by a UAT config's raw matrix filters."""
    platforms_cfg = raw.get("platforms") or {}
    platform_groups_default = ["sql"] if "include" not in platforms_cfg else []
    return tuple(
        resolve_platforms(
            groups=_as_list(platforms_cfg.get("groups", platform_groups_default)),
            include=_as_list(platforms_cfg.get("include", [])),
            exclude=_as_list(platforms_cfg.get("exclude", [])),
        )
    )


def run_preflight(
    *,
    free_space_path: str | Path = "~/Developer/benchmark_runs",
    free_space_min_gib: float = 5.0,
    docker_required: bool = False,
    noisy_neighbor_warn_load: float = 8.0,
    local_platforms_check: bool = False,
    requested_platforms: Iterable[str] = (),
    benchmark_runs_dir: str | Path | None = None,
    bring_up_runner: BringUpRunner | None = None,
    reachability_checker: ReachabilityChecker | None = None,
    disk_budget_config: UATConfig | None = None,
) -> PreflightResult:
    """Execute the preflight phase.

    By default this preserves historical behaviour: missing local services
    remain execute-phase `skipped_unreachable` cells. When
    `local_platforms_check` is true, requested platforms are probed before the
    sweep starts. Automated platforms get one `make uat-bring-up` attempt;
    document-only platforms abort with an operator-facing message.
    """
    free_gib = free_space_gib(free_space_path)
    docker_ok = docker_reachable()
    load_1m = host_load_1m()

    warnings: list[str] = []
    aborted = False
    abort_reason: str | None = None
    checked: tuple[str, ...] = ()
    attempted: tuple[str, ...] = ()
    disk_budget_summary = estimate_disk_budget_summary(disk_budget_config) if disk_budget_config is not None else None

    if free_gib < free_space_min_gib:
        aborted = True
        abort_reason = f"free space {free_gib:.1f} GiB < cutoff {free_space_min_gib:.1f} GiB at {free_space_path}"
    if docker_required and not docker_ok:
        aborted = True
        abort_reason = (abort_reason or "") + ("; docker_required=true but `docker ps` is unreachable")
    if load_1m is not None and load_1m > noisy_neighbor_warn_load:
        warnings.append(f"host load {load_1m:.1f} > {noisy_neighbor_warn_load:.1f}")
    if not docker_ok and not docker_required:
        warnings.append("docker not reachable (any docker platforms will skip)")

    if local_platforms_check and not aborted:
        checked, attempted, local_abort, local_warnings = _check_local_platforms(
            requested_platforms,
            bring_up_runner=bring_up_runner
            or (lambda platform: _run_make_bring_up(platform, benchmark_runs_dir=benchmark_runs_dir)),
            reachability_checker=reachability_checker or platform_is_reachable,
        )
        warnings.extend(local_warnings)
        if local_abort is not None:
            aborted = True
            abort_reason = local_abort

    return PreflightResult(
        free_space_gib=free_gib,
        docker_reachable=docker_ok,
        host_load_1m=load_1m,
        aborted=aborted,
        abort_reason=abort_reason,
        warnings=tuple(warnings),
        local_platforms_checked=checked,
        local_platforms_attempted=attempted,
        disk_budget_summary=disk_budget_summary,
    )


def _check_local_platforms(
    requested_platforms: Iterable[str],
    *,
    bring_up_runner: BringUpRunner,
    reachability_checker: ReachabilityChecker,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None, tuple[str, ...]]:
    checked = tuple(dict.fromkeys(requested_platforms))
    attempted: list[str] = []
    warnings: list[str] = []
    automated = set(automated_local_platforms())
    for platform in checked:
        if reachability_checker(platform):
            continue
        if platform not in automated:
            return (
                checked,
                tuple(attempted),
                f"local platform {platform!r} is unreachable and has no automated UAT bring-up; "
                "see docs/operations/uat-local-provisioning.md",
                tuple(warnings),
            )
        attempted.append(platform)
        returncode = bring_up_runner(platform)
        reset_reachability_cache()
        if returncode != 0:
            return (
                checked,
                tuple(attempted),
                f"local platform {platform!r} is unreachable and `make uat-bring-up PLATFORM={platform}` "
                f"failed with exit {returncode}",
                tuple(warnings),
            )
        if not reachability_checker(platform):
            return (
                checked,
                tuple(attempted),
                f"local platform {platform!r} remains unreachable after `make uat-bring-up PLATFORM={platform}`",
                tuple(warnings),
            )
        warnings.append(f"local platform {platform!r} was unreachable; `make uat-bring-up` recovered it")
    return checked, tuple(attempted), None, tuple(warnings)


def _run_make_bring_up(platform: str, *, benchmark_runs_dir: str | Path | None = None) -> int:
    argv = ["make", "uat-bring-up", f"PLATFORM={platform}"]
    if benchmark_runs_dir is not None:
        argv.append(f"BENCHMARK_RUNS_DIR={Path(benchmark_runs_dir).expanduser()}")
    completed = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        check=False,
    )
    return completed.returncode


def _as_list(value: Iterable | None) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def estimate_disk_budget_summary(config: UATConfig) -> str:
    """Return the advisory disk-budget line for a config."""
    from tests.uat.preflight_budget import estimate_peak_disk, format_disk_budget

    return format_disk_budget(estimate_peak_disk(config))

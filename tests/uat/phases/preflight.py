"""Preflight phase: disk, docker, noisy-neighbor scan.

Mirrors the W1 step of the 2026-05-02 retrospective. Telemetry-first:
warns liberally, aborts only on `free_space_min_gib`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreflightResult:
    free_space_gib: float
    docker_reachable: bool
    host_load_1m: float | None
    aborted: bool
    abort_reason: str | None
    warnings: tuple[str, ...]


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


def run_preflight(
    *,
    free_space_path: str | Path = "~/Developer/benchmark_runs",
    free_space_min_gib: float = 5.0,
    docker_required: bool = False,
    noisy_neighbor_warn_load: float = 8.0,
) -> PreflightResult:
    """Execute the preflight phase. Aborts only on free-space cutoff."""
    free_gib = free_space_gib(free_space_path)
    docker_ok = docker_reachable()
    load_1m = host_load_1m()

    warnings: list[str] = []
    aborted = False
    abort_reason: str | None = None

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

    return PreflightResult(
        free_space_gib=free_gib,
        docker_reachable=docker_ok,
        host_load_1m=load_1m,
        aborted=aborted,
        abort_reason=abort_reason,
        warnings=tuple(warnings),
    )

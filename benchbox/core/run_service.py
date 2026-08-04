"""Shared run service: the one engine below the CLI and MCP surfaces.

Per `docs/development/adr/adr-one-engine-scoped-surfaces.md`, all benchmark
business logic lives in `benchbox.core` below both surfaces. This module is
where run orchestration lands.

Layering is the constraint that shapes every signature here: core sits below
`benchbox.platforms` and `benchbox.cli`, so this module must import neither.
Anything a surface owns -- an adapter, a directory layout, a console, an
interactive prompt -- arrives as a resolved input or an injected factory. That
is why :func:`resolve_run_config` takes an already-computed ``database_path``
instead of a ``DirectoryManager``: the manager is CLI-layer, the path is data.

This first increment covers request/plan types and configuration resolution
only. Execution orchestration follows in a later work unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from benchbox.core.config import BenchmarkConfig, RunConfig
from benchbox.core.constants import (
    GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS,
    GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class VerbosityLike(Protocol):
    """The verbosity surface :func:`resolve_run_config` reads.

    Structural rather than nominal so the CLI's ``VerbositySettings`` satisfies
    it without core depending on the concrete type, and so a caller with no
    verbosity concept can pass :class:`SilentVerbosity`.
    """

    @property
    def verbose(self) -> bool: ...

    @property
    def level(self) -> int: ...

    @property
    def verbose_enabled(self) -> bool: ...

    @property
    def very_verbose(self) -> bool: ...

    @property
    def quiet(self) -> bool: ...


@dataclass(frozen=True)
class SilentVerbosity:
    """Verbosity for callers that have no console.

    MCP suppresses console output and returns structured JSON, so it has no
    verbosity flags to forward; this is the value it will pass rather than
    inventing CLI-shaped settings.
    """

    verbose: bool = False
    level: int = 0
    verbose_enabled: bool = False
    very_verbose: bool = False
    quiet: bool = True


@dataclass(frozen=True)
class RunRequest:
    """A fully-resolved, surface-neutral description of a benchmark run.

    "Fully resolved" is the contract: every interactive decision, credential
    prompt, and default has already been settled by the surface. The service
    never asks a question.
    """

    platform: str
    benchmark: str
    scale_factor: float
    queries: list[str] | None = None
    phases: list[str] | None = None
    mode: str | None = None
    capture_plans: bool = False
    platform_options: Mapping[str, object] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunPlan:
    """The resolved plan for one run: what will execute, and how."""

    request: RunRequest
    benchmark_config: BenchmarkConfig
    run_config: RunConfig
    execution_type: str
    resolved_mode: str | None = None


def resolve_run_config(
    config: BenchmarkConfig,
    *,
    database_path: str | Path,
    verbosity: VerbosityLike,
) -> RunConfig:
    """Build the :class:`RunConfig` for one benchmark run.

    Moved verbatim from ``BenchmarkOrchestrator._prepare_run_config``; the only
    changes are that the two surface-owned inputs it used to reach for through
    ``self`` are now parameters:

    - ``database_path`` replaces ``self.directory_manager.get_database_path(...)``,
      because ``DirectoryManager`` is CLI-layer and core may not import it. The
      caller computes the path; the tuning-aware naming rules stay where they
      already live, in ``benchbox.utils.database_naming``.
    - ``verbosity`` replaces ``self._verbosity``.

    Every value derivation below -- the ``or DEFAULT`` fallbacks, the clamps,
    and the ``is not None`` seed check that preserves a zero seed -- is
    unchanged, and is pinned by
    ``tests/unit/cli/test_run_config_resolution_characterization.py``.
    """
    options = config.options or {}
    iterations = int(
        options.get("power_iterations", GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS)
        or GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS
    )
    warmups = int(
        options.get("power_warmup_iterations", GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS)
        or GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS
    )
    fail_fast = bool(options.get("power_fail_fast", False))

    return RunConfig(
        query_subset=config.queries,
        concurrent_streams=config.concurrency,
        test_execution_type=getattr(config, "test_execution_type", "standard"),
        scale_factor=config.scale_factor,
        capture_plans=config.capture_plans,
        analyze_plans=getattr(config, "analyze_plans", None),
        strict_plan_capture=config.strict_plan_capture,
        seed=int(options.get("seed")) if options.get("seed") is not None else None,
        connection={"database_path": str(database_path)},
        verbose=verbosity.verbose,
        verbose_level=verbosity.level,
        verbose_enabled=verbosity.verbose_enabled,
        very_verbose=verbosity.very_verbose,
        quiet=verbosity.quiet,
        iterations=max(1, iterations),
        warm_up_iterations=max(0, warmups),
        power_fail_fast=fail_fast,
    )


__all__ = [
    "RunPlan",
    "RunRequest",
    "SilentVerbosity",
    "VerbosityLike",
    "resolve_run_config",
]

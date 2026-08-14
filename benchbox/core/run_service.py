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

This module covers request/plan types, configuration resolution, and execution
orchestration. Everything that needs a console, an interactive prompt, or a
concrete adapter class stays in the surface layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from benchbox.core.config import BenchmarkConfig, RunConfig
from benchbox.core.constants import (
    GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS,
    GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS,
    QUERY_PHASES,
)

# TPC-compliant scale factors — moved from ``benchbox.cli.commands.run_official``
# so the validation lives in core beside the run service.
TPC_ALLOWED_SCALE_FACTORS: frozenset[int | float] = frozenset({1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000})


def validate_tpc_scale_factor(scale: float) -> None:
    """Validate that ``scale`` is TPC-compliant.

    Raises:
        ValueError: If scale is not in :data:`TPC_ALLOWED_SCALE_FACTORS`.
    """
    if scale not in TPC_ALLOWED_SCALE_FACTORS:
        raise ValueError(f"Scale factor {scale} is not TPC-compliant. Allowed: {sorted(TPC_ALLOWED_SCALE_FACTORS)}")


def validate_stream_count(streams: int | None, phases: str | None = None) -> None:
    """Validate ``--streams`` for official runs.

    Mirrors the CLI guardrails in ``run_official``:
    - ``--streams`` is required when throughput is requested.
    - Negative values are rejected.
    - Explicit ``1`` is rejected (TPC minimum is 2; the driver floors 1→2
      without an error, so callers must be told here).

    Raises:
        ValueError: On invalid stream count.
    """
    phase_set: set[str] = set()
    if phases:
        phase_set = {p.strip().lower() for p in phases.split(",")}

    if "throughput" in phase_set and streams is None:
        raise ValueError("--streams is required for throughput test")
    if streams is not None and streams < 0:
        raise ValueError(f"--streams must be a non-negative integer, got: {streams}")
    if streams == 1:
        raise ValueError("--streams must be >= 2 (TPC throughput minimum); got: 1")


from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.results.driver_metadata import apply_driver_metadata
from benchbox.core.runner.runner import (
    LifecyclePhases,
    ValidationOptions,
    run_benchmark_lifecycle,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from benchbox.core.results.models import BenchmarkResults
    from benchbox.core.schemas import ExecutionContext


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


@dataclass(frozen=True)
class UnsupportedExecutionMode:
    """Surface-neutral description of an unsupported platform mode."""

    platform: str
    mode: str
    supported: tuple[str, ...]


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


class AdapterFactory(Protocol):
    """Builds the platform adapter for one run.

    This is the injection point the layering contract forces. Constructing an
    adapter means importing ``benchbox.platforms``, which core sits below, so
    the surface supplies a callable instead. The CLI passes a closure over its
    console and verbosity; MCP will pass one over its own adapter resolution.

    Returning None is meaningful: a data-only run has no database to adapt.
    """

    def __call__(
        self,
        *,
        execution_mode: str | None,
        output_root: Any,
        phases: LifecyclePhases,
    ) -> Any | None: ...


def resolve_lifecycle_phases(phases_to_run: list[str] | None) -> LifecyclePhases:
    """Map a requested phase list onto the runner's lifecycle flags.

    ``None`` means the standard lifecycle -- generate, load, execute -- with the
    statistics phase staying opt-in.
    """
    if not phases_to_run:
        return LifecyclePhases(generate=True, load=True, execute=True)

    return LifecyclePhases(
        generate="generate" in phases_to_run,
        load="load" in phases_to_run,
        execute=any(phase in phases_to_run for phase in ("warmup", *QUERY_PHASES)),
        statistics="statistics" in phases_to_run,
    )


def resolve_validation_options(options: Mapping[str, Any] | None) -> ValidationOptions:
    """Read the three validation toggles out of a benchmark's options."""
    opts = options or {}
    return ValidationOptions(
        enable_preflight_validation=bool(opts.get("enable_preflight_validation")),
        enable_postgen_manifest_validation=bool(opts.get("enable_postgen_manifest_validation", False)),
        enable_postload_validation=bool(opts.get("enable_postload_validation", False)),
    )


def resolve_execution_mode(database_config: Any) -> str | None:
    """Determine the execution mode for a run, or None with no database.

    An explicit ``execution_mode`` on the database config wins. Otherwise the
    platform registry's default applies, upgraded to ``dataframe`` when the
    config describes a DataFrame execution.
    """
    if database_config is None:
        return None

    execution_mode = getattr(database_config, "execution_mode", None)
    if execution_mode is not None:
        return execution_mode

    execution_mode = PlatformRegistry.get_default_mode(database_config.type)
    if is_dataframe_execution(database_config):
        execution_mode = "dataframe"
    return execution_mode


def is_dataframe_execution(database_config: Any) -> bool:
    """Return whether a database configuration selects DataFrame execution.

    This mode predicate belongs beside run-plan resolution, not in the
    deprecated compatibility DataFrame runner. The core platform registry
    remains the authority for default modes, while the suffix handling keeps
    the legacy ``adapter_factory.is_dataframe_mode`` behavior intact.
    """
    if database_config is None:
        return False

    platform_type = getattr(database_config, "type", "")
    explicit_mode = getattr(database_config, "mode", None)
    if explicit_mode is not None:
        return explicit_mode == "dataframe"

    platform_lower = platform_type.lower()
    if ":" in platform_lower:
        platform_lower = platform_lower.rsplit(":", 1)[0]
    if platform_lower.endswith("-df"):
        return True
    return PlatformRegistry.get_default_mode(platform_lower) == "dataframe"


def get_execution_mode(database_config: Any) -> str:
    """Return the concrete execution-mode label for a database configuration."""
    return "dataframe" if is_dataframe_execution(database_config) else "sql"


def stamp_requested_phases(config: BenchmarkConfig, phases_to_run: list[str] | None) -> None:
    """Record the exact phases requested on the config's options.

    Combined mode reads this downstream to run only what was asked for, rather
    than everything the execution type implies.
    """
    if not phases_to_run:
        return
    options = dict(getattr(config, "options", {}) or {})
    options["requested_phases"] = list(phases_to_run)
    config.options = options


def execute_run(
    *,
    config: BenchmarkConfig,
    benchmark_instance: Any,
    database_config: Any,
    system_profile: Any,
    platform_config: Mapping[str, Any] | None,
    output_root: Any,
    phases_to_run: list[str] | None,
    adapter_factory: AdapterFactory,
    verbosity: VerbosityLike,
    monitor: Any = None,
    execution_context: ExecutionContext | None = None,
) -> BenchmarkResults:
    """Run one benchmark through the core lifecycle.

    Every input is already resolved by the surface: the benchmark instance, the
    platform config, and the output root all arrive built. The adapter is the
    one thing this function asks for, through ``adapter_factory``, because
    building it requires ``benchbox.platforms``.

    Moved from ``BenchmarkOrchestrator.execute_benchmark``. What did NOT move is
    everything interaction-scoped: console output, the cloud-platform
    load-phase warning, and the credential-setup retry all stay in the CLI,
    which is where the new contract puts them.
    """
    stamp_requested_phases(config, phases_to_run)

    phases = resolve_lifecycle_phases(phases_to_run)
    validation = resolve_validation_options(getattr(config, "options", None))
    execution_mode = resolve_execution_mode(database_config)

    adapter = adapter_factory(execution_mode=execution_mode, output_root=output_root, phases=phases)

    result = run_benchmark_lifecycle(
        benchmark_config=config,
        database_config=database_config,
        system_profile=system_profile,
        platform_config=platform_config,
        phases=phases,
        validation_opts=validation,
        output_root=output_root,
        benchmark_instance=benchmark_instance,
        platform_adapter=adapter,
        verbosity=verbosity,
        monitor=monitor,
        enable_resource_monitoring=False,
        execution_context=execution_context,
    )

    # Canonical runtime metadata enrichment for every run path.
    apply_driver_metadata(result, database_config=database_config, platform_adapter=adapter)
    return result


# ---------------------------------------------------------------------------
# Helpers migrated from MCP for one-engine (w1)
# ---------------------------------------------------------------------------


def _translate_platform_options_for_adapter(platform: str, options: dict) -> dict:
    """Translate validated platform options to adapter kwargs.

    ClickHouse profile resolution stays surface-owned because it needs server
    configuration. This function handles generic DuckDB and Databricks
    rewrites that are independent of the calling surface.
    """
    normalized = dict(options)
    platform_name = platform.lower().removesuffix("-df")
    if platform_name == "duckdb" and "threads" in normalized:
        normalized["thread_limit"] = normalized.pop("threads")
    if platform_name == "databricks":
        tuning_config = build_databricks_clustering_intent(normalized)
        if tuning_config is not None:
            normalized.pop("databricks_clustering_strategy", None)
            normalized.pop("liquid_clustering_columns", None)
            normalized["tuning_config"] = tuning_config
            normalized["tuning_enabled"] = True
    return normalized


def build_databricks_clustering_intent(options: dict[str, object]):
    """Build a validated Databricks layout intent without surface coupling."""
    strategy = options.get("databricks_clustering_strategy")
    columns = options.get("liquid_clustering_columns")
    if strategy is None and columns is None:
        return None

    from benchbox.core.tuning.interface import UnifiedTuningConfiguration

    tuning_config = UnifiedTuningConfiguration()
    platform_optimizations = tuning_config.platform_optimizations
    if strategy is not None:
        strategy = str(strategy).lower()
        platform_optimizations.databricks_clustering_strategy = strategy
        platform_optimizations.liquid_clustering_enabled = strategy in {
            "liquid_clustering",
            "liquid_clustering_auto",
        }
        platform_optimizations.physical_rendering_id = None
    if columns is not None:
        parsed_columns = [column.strip() for column in str(columns).split(",") if column.strip()]
        platform_optimizations.liquid_clustering_columns = parsed_columns
        platform_optimizations.liquid_clustering_enabled = bool(parsed_columns)
        if parsed_columns and strategy is None:
            platform_optimizations.databricks_clustering_strategy = "liquid_clustering"

    platform_optimizations.__post_init__()
    return tuning_config


def _resolve_mode_with_registry(platform: str, mode: str | None):
    """Resolve a requested mode against the shared platform registry."""
    if mode is not None:
        mode = mode.lower()
        if mode in ("datagen", "generate"):
            mode = "data_only"
    if mode == "data_only":
        return "data_only", None
    platform_lower = platform.lower()
    base_platform = platform_lower.replace("-df", "")
    caps = PlatformRegistry.get_platform_capabilities(base_platform)
    if caps is None:
        return mode or "sql", None
    supported = []
    if caps.supports_sql:
        supported.append("sql")
    if caps.supports_dataframe:
        supported.append("dataframe")
    supported.append("data_only")
    if mode is not None:
        if not PlatformRegistry.supports_mode(base_platform, mode):
            return mode, UnsupportedExecutionMode(platform, mode, tuple(supported))
        return mode, None
    if platform_lower.endswith("-df"):
        return "dataframe", None
    return caps.default_mode, None


def _map_phases_to_execution_type(phases: list[str]) -> str:
    """Map the requested phases to the shared benchmark execution type."""
    phases_set = set(phases)
    query_phases = set(QUERY_PHASES)
    selected_query_phases = phases_set & query_phases
    if selected_query_phases:
        # Any mixed query-phase request must use combined mode so the runner
        # executes exactly the requested subset instead of silently selecting
        # the first phase in a priority chain.
        if len(selected_query_phases) > 1:
            return "combined"
        if "power" in selected_query_phases:
            return "power"
        if "throughput" in selected_query_phases:
            return "throughput"
        if "maintenance" in selected_query_phases:
            return "maintenance"
        return "standard"
    elif phases == ["load"] or ("load" in phases_set and not phases_set & query_phases):
        return "load_only"
    elif phases == ["generate"] or ("generate" in phases_set and not phases_set & ({"load"} | query_phases)):
        return "data_only"
    else:
        return "standard"


__all__ = [
    "AdapterFactory",
    "RunPlan",
    "RunRequest",
    "SilentVerbosity",
    "VerbosityLike",
    "execute_run",
    "resolve_execution_mode",
    "resolve_lifecycle_phases",
    "resolve_run_config",
    "resolve_validation_options",
    "stamp_requested_phases",
    "_translate_platform_options_for_adapter",
    "build_databricks_clustering_intent",
    "_resolve_mode_with_registry",
    "UnsupportedExecutionMode",
    "_map_phases_to_execution_type",
]

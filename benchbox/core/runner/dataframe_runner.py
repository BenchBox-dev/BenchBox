"""Deprecated internal compatibility runner for DataFrame benchmark lifecycle.

Production DataFrame execution is routed by ``benchbox.core.runner.runner`` to
``adapter.run_benchmark()``, implemented for DataFrame adapters by
``benchbox.platforms.dataframe.benchmark_mixin.BenchmarkExecutionMixin``. This
module is retained as a deprecated internal compatibility runner while older
tests and helper imports are migrated.

The mode-detection helpers remain internal utility compatibility points for
CLI/dry-run paths. New DataFrame lifecycle behavior should be added to the
adapter mixin path, not here.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import DEFAULT

from benchbox.core.constants import (
    GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS,
    GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS,
)
from benchbox.core.dataframe import (
    check_sufficient_memory,
    format_memory_warning,
    validate_scale_factor,
)
from benchbox.core.dataframe.data_loader import DataFrameDataLoader, get_tpch_column_names
from benchbox.core.dataframe.query_resolution import (
    build_dataframe_query_filter_from_config,
    get_clickbench_dataframe_queries,
    get_tpcds_dataframe_queries,
    get_tpcds_legacy_queries,
    get_tpch_dataframe_queries,
    resolve_tpcds_query_manager,
    resolve_tpcds_stream_queries,
)
from benchbox.core.dataframe.schema_utils import get_benchmark_schema_columns
from benchbox.core.exceptions import InsufficientMemoryError
from benchbox.core.results import (
    BenchmarkInfoInput,
    ResultBuilder,
    build_platform_info,
    normalize_query_result,
)
from benchbox.core.results.builder import RunConfigInput, normalize_benchmark_id
from benchbox.core.results.models import (
    BenchmarkResults,
    TableLoadingStats,
)
from benchbox.core.schemas import BenchmarkConfig, SystemProfile

try:
    from benchbox.monitoring import PerformanceMonitor
except ImportError:
    PerformanceMonitor = None  # type: ignore[assignment,misc]
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.printing import quiet_console
from benchbox.utils.verbosity import VerbositySettings

logger = logging.getLogger(__name__)

console = quiet_console

# Benchmark ids that share the TPC-H DataFrame parameter seam
# (benchbox.core.tpch.dataframe_queries): canonical TPC-H plus the benchmarks
# whose DataFrame queries reuse the same query impls and get_tpch_parameters().
# TPC-H Skew re-registers the TPC-H DataFrame queries verbatim, and TPC-Havoc's
# variants read the same parameter seam, so all three need the scale-dependent
# Q11 default (0.0001/SF) set and cleared together.
_TPCH_FAMILY_DATAFRAME_IDS = ("tpch", "tpch_skew", "tpchavoc")

DATAFRAME_RUNNER_API_SURFACE = "deprecated"
DATAFRAME_RUNNER_LIFECYCLE = "deprecated-internal-compatibility-runner"
DATAFRAME_PRODUCTION_EXECUTION_PATH = "adapter.run_benchmark+BenchmarkExecutionMixin"


def _benchmark_defines_hook(benchmark_instance: Any | None, hook_name: str) -> bool:
    """Return True when a benchmark explicitly defines a hook.

    This accepts real class-defined hooks and explicitly configured mock hooks,
    while rejecting synthetic MagicMock attributes created via ``__getattr__``.
    """
    if benchmark_instance is None:
        return False

    hook = type(benchmark_instance).__dict__.get(hook_name)
    if callable(hook):
        return True

    instance_hook = benchmark_instance.__dict__.get(hook_name)
    if callable(instance_hook):
        return True

    mock_children = getattr(benchmark_instance, "_mock_children", None)
    if not isinstance(mock_children, dict):
        return False

    child = mock_children.get(hook_name)
    if child is None:
        return False

    return (
        getattr(child, "_mock_return_value", DEFAULT) is not DEFAULT
        or getattr(child, "_mock_side_effect", None) is not None
        or getattr(child, "_mock_wraps", None) is not None
    )


def _benchmark_manages_dataframe_loading(benchmark_instance: Any | None) -> bool:
    """Return True when a benchmark explicitly owns DataFrame loading.

    Use class-level hook detection so dynamic test doubles such as MagicMock do
    not accidentally appear to implement the hook via ``__getattr__``.
    """
    if not _benchmark_defines_hook(benchmark_instance, "skip_dataframe_data_loading"):
        return False

    return bool(benchmark_instance.skip_dataframe_data_loading())


def _benchmark_provides_dataframe_queries(benchmark_instance: Any | None) -> bool:
    """Return True when a benchmark defines a DataFrame query provider hook."""
    return _benchmark_defines_hook(benchmark_instance, "get_dataframe_queries")


@dataclass
class DataFramePhases:
    """Phases for DataFrame benchmark execution."""

    load: bool = True
    execute: bool = True


@dataclass
class DataFrameRunOptions:
    """Options for DataFrame benchmark execution."""

    ignore_memory_warnings: bool = False
    force_regenerate: bool = False
    prefer_parquet: bool = True
    cache_dir: Path | None = None
    verbose: bool = False
    very_verbose: bool = False


def run_dataframe_benchmark(
    benchmark_config: BenchmarkConfig,
    adapter: Any,
    system_profile: SystemProfile | None = None,
    *,
    data_dir: Path | None = None,
    phases: DataFramePhases | None = None,
    options: DataFrameRunOptions | None = None,
    benchmark_instance: Any | None = None,
    verbosity: VerbositySettings | None = None,
    monitor: PerformanceMonitor | None = None,
) -> BenchmarkResults:
    """Run a benchmark using DataFrame mode execution.

    Args:
        benchmark_config: Benchmark configuration
        adapter: DataFrame platform adapter (PolarsDataFrameAdapter, PandasDataFrameAdapter)
        system_profile: System profile for resource information
        data_dir: Directory containing benchmark data files
        phases: Which phases to execute
        options: DataFrame-specific execution options
        benchmark_instance: Pre-constructed benchmark instance
        verbosity: Verbosity settings
        monitor: Performance monitor

    Returns:
        BenchmarkResults with execution details
    """
    phases = phases or DataFramePhases()
    if isinstance(options, dict):
        options = DataFrameRunOptions(**options)
    else:
        options = options or DataFrameRunOptions()
    verbosity = verbosity or VerbositySettings.default()

    platform_name = adapter.platform_name
    scale_factor = getattr(benchmark_config, "scale_factor", 1.0)
    test_execution_type = getattr(benchmark_config, "test_execution_type", "standard")

    # Check for unsupported maintenance phase
    if test_execution_type in ("maintenance", "combined"):
        raise NotImplementedError(
            f"Maintenance phase is not yet implemented for DataFrame mode.\n\n"
            f"DataFrame platforms like Spark (Delta Lake, Iceberg), Polars, and others "
            f"can support maintenance operations (INSERT/UPDATE/DELETE), but this "
            f"functionality has not been implemented yet.\n\n"
            f"For now, please use SQL mode (e.g., --platform duckdb) for maintenance "
            f"phase benchmarks.\n\n"
            f"Requested: test_execution_type={test_execution_type}, platform={platform_name}"
        )

    logger.info(f"Starting DataFrame benchmark: {benchmark_config.name}")
    logger.info(f"Platform: {platform_name}, Scale Factor: {scale_factor}")

    # Build platform info using standardized extractor
    platform_info = build_platform_info(adapter, execution_mode="dataframe")

    # Create result builder
    builder = ResultBuilder(
        benchmark=BenchmarkInfoInput(
            name=benchmark_config.name,
            scale_factor=scale_factor,
            test_type=test_execution_type if test_execution_type != "standard" else "power",
            benchmark_id=normalize_benchmark_id(benchmark_config.name),
            display_name=getattr(benchmark_config, "display_name", benchmark_config.name),
        ),
        platform=platform_info,
    )
    builder.mark_started()

    options_map = getattr(benchmark_config, "options", {}) or {}
    builder.set_run_config(
        RunConfigInput(
            compression_type=options_map.get("compression_type"),
            compression_level=options_map.get("compression_level"),
            seed=options_map.get("seed"),
            phases=options_map.get("phases"),
            query_subset=getattr(benchmark_config, "queries", None),
            tuning_mode=options_map.get("tuning_mode"),
            tuning_config=options_map.get("df_tuning_config"),
        )
    )

    # Initialize result tracking
    query_results: list[dict[str, Any]] = []
    table_stats: dict[str, int] = {}
    load_time = 0.0

    try:
        # Pre-execution memory check
        if not options.ignore_memory_warnings:
            memory_check = check_sufficient_memory(benchmark_config.name, scale_factor, platform_name.lower())
            if not memory_check.is_safe:
                warning = format_memory_warning(memory_check)
                raise InsufficientMemoryError(warning)

        # Scale factor validation
        is_valid, sf_warning = validate_scale_factor(scale_factor, platform_name.lower())
        if sf_warning:
            logger.warning(sf_warning)

        # Create execution context
        ctx = adapter.create_context()

        skip_data_loading = _benchmark_manages_dataframe_loading(benchmark_instance)

        # Load phase
        if phases.load and not skip_data_loading:
            load_start = mono_time()
            table_stats, per_table_stats = _load_dataframe_data(
                adapter=adapter,
                ctx=ctx,
                benchmark_config=benchmark_config,
                benchmark_instance=benchmark_instance,
                data_dir=data_dir,
                options=options,
            )
            load_time = elapsed_seconds(load_start)
            logger.info(f"Data loading completed in {load_time:.2f}s")

            # Add table stats to builder
            for table_name, stats in per_table_stats.items():
                builder.add_table_stats(
                    table_name,
                    stats.rows,
                    load_time_ms=stats.load_time_ms,
                    status=stats.status,
                    error_message=stats.error_message,
                )
            builder.set_loading_time(load_time * 1000)
            builder.set_phase_status("data_loading", "COMPLETED", load_time * 1000)
        elif phases.load and skip_data_loading:
            builder.set_phase_status("data_loading", "SKIPPED")

        # Execute phase
        if phases.execute:
            query_results = _execute_dataframe_queries(
                adapter=adapter,
                ctx=ctx,
                benchmark_config=benchmark_config,
                benchmark_instance=benchmark_instance,
                monitor=monitor,
            )

            # Add query results to builder
            for qr in query_results:
                builder.add_query_result(normalize_query_result(qr))
            builder.set_phase_status("power_test", "COMPLETED")

        builder.mark_completed()
        return builder.build()

    except Exception as e:
        logger.error(f"DataFrame benchmark failed: {e}")
        builder.set_validation_status(
            "FAILED",
            {"error": str(e), "error_type": type(e).__name__},
        )
        builder.add_execution_metadata("error", str(e))
        builder.mark_completed()
        return builder.build()


def _load_dataframe_data(
    adapter: Any,
    ctx: Any,
    benchmark_config: BenchmarkConfig,
    benchmark_instance: Any | None,
    data_dir: Path | None,
    options: DataFrameRunOptions,
) -> tuple[dict[str, int], dict[str, TableLoadingStats]]:
    """Load benchmark data into DataFrame context.

    Returns:
        Tuple of (table_stats, per_table_loading_stats)
    """
    platform_name = adapter.platform_name.lower()

    # Create data loader
    loader = DataFrameDataLoader(
        platform=platform_name,
        cache_dir=options.cache_dir,
        prefer_parquet=options.prefer_parquet,
        force_regenerate=options.force_regenerate,
    )

    benchmark_ref = benchmark_instance or benchmark_config
    if benchmark_ref is None:
        raise ValueError("No data source available. Either provide data_dir or generate data first.")

    options_map = getattr(benchmark_config, "options", {}) or {}
    df_tuning_config = options_map.get("df_tuning_config")
    write_config = getattr(df_tuning_config, "write", None) if df_tuning_config else None

    # Always run through DataFrameDataLoader so format conversion/caching rules
    # are applied consistently (e.g., CSV/TBL -> Parquet for Polars/Pandas).
    data_paths = loader.prepare_benchmark_data(
        benchmark=benchmark_ref,
        scale_factor=getattr(benchmark_config, "scale_factor", 1.0),
        data_dir=data_dir,
        write_config=write_config,
    )

    # Get schema info for column names. Raw CSV/TBL loads need explicit names
    # for benchmarks beyond TPC-H (for example TPC-DS .dat shards).
    benchmark_id = normalize_benchmark_id(benchmark_config.name)
    column_names_map = {
        table_name: [column["name"] for column in columns]
        for table_name, columns in get_benchmark_schema_columns(benchmark_ref).items()
    }
    if benchmark_id == "tpch":
        column_names_map.update(get_tpch_column_names())

    # Load tables
    table_stats: dict[str, int] = {}
    per_table_stats: dict[str, TableLoadingStats] = {}

    for table_name, file_paths in data_paths.items():
        load_start = mono_time()
        try:
            column_names = column_names_map.get(table_name.lower())
            normalized_paths = file_paths if isinstance(file_paths, list) else [file_paths]
            row_count = adapter.load_table(ctx, table_name.lower(), normalized_paths, column_names=column_names)
            load_time_ms = int(elapsed_seconds(load_start) * 1000)

            table_stats[table_name] = row_count
            per_table_stats[table_name] = TableLoadingStats(
                rows=row_count,
                load_time_ms=load_time_ms,
                status="SUCCESS",
            )
            logger.debug(f"Loaded {table_name}: {row_count:,} rows in {load_time_ms}ms")

        except Exception as e:
            load_time_ms = int(elapsed_seconds(load_start) * 1000)
            per_table_stats[table_name] = TableLoadingStats(
                rows=0,
                load_time_ms=load_time_ms,
                status="FAILED",
                error_type=type(e).__name__,
                error_message=str(e),
            )
            logger.error(f"Failed to load {table_name}: {e}")

    return table_stats, per_table_stats


def _execute_dataframe_queries(
    adapter: Any,
    ctx: Any,
    benchmark_config: BenchmarkConfig,
    benchmark_instance: Any | None,
    monitor: PerformanceMonitor | None,
) -> list[dict[str, Any]]:
    """Execute DataFrame queries with warmup and measurement iterations.

    Follows TPC power test methodology:
    1. Warmup iterations (default 1): Prime caches, emitted as warmup results
    2. Measurement iterations (default 3): Timed runs, results emitted per iteration

    Each iteration uses a different stream_id for query permutation, matching
    the SQL runner behavior. This ensures each iteration executes queries in
    a different order per TPC-H/TPC-DS specification.

    Returns:
        List of query result dictionaries with warmup + measurement iterations
    """
    # Get warmup and iteration counts from config options
    options = getattr(benchmark_config, "options", {}) or {}
    warmup_iterations = int(
        options.get("power_warmup_iterations", GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS)
        or GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS
    )
    measurement_iterations = int(
        options.get("power_iterations", GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS)
        or GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS
    )

    benchmark_id = normalize_benchmark_id(benchmark_config.name)
    seed = options.get("seed")
    scale_factor = getattr(benchmark_config, "scale_factor", 1.0)

    query_filter = build_dataframe_query_filter_from_config(benchmark_config)

    query_results: list[dict[str, Any]] = []
    override_contexts_applied: set[tuple[int, float, int | None]] = set()
    try:
        # Set up seed-based parameter overrides for DataFrame queries.
        # For TPC-DS, this is stream-aware and applied per stream execution.
        _setup_parameter_overrides_for_stream(
            benchmark_id=benchmark_id,
            seed=seed,
            scale_factor=scale_factor,
            stream_id=0,
            applied_contexts=override_contexts_applied,
        )

        # Get initial query set to determine total count
        initial_queries = _get_queries_for_benchmark(benchmark_config, benchmark_instance, stream_id=0)
        if query_filter:
            initial_queries = [q for q in initial_queries if q.query_id.upper() in query_filter]

        if not initial_queries:
            logger.warning("No queries found for execution")
            return []

        total_queries = len(initial_queries)
        logger.info(f"Executing {total_queries} queries")
        logger.info(f"Warmup iterations: {warmup_iterations}, Measurement iterations: {measurement_iterations}")

        # Execute warmup iterations (emit results)
        # Each warmup uses a different stream_id (0, 1, 2, ...)
        if warmup_iterations > 0:
            console.print(f"\n[yellow]Running {warmup_iterations} warmup iteration(s)...[/yellow]")
            for warmup_iter in range(warmup_iterations):
                warmup_stream_id = warmup_iter
                _setup_parameter_overrides_for_stream(
                    benchmark_id=benchmark_id,
                    seed=seed,
                    scale_factor=scale_factor,
                    stream_id=warmup_stream_id,
                    applied_contexts=override_contexts_applied,
                )
                warmup_queries = _get_queries_for_benchmark(
                    benchmark_config, benchmark_instance, stream_id=warmup_stream_id
                )
                if query_filter:
                    warmup_queries = [q for q in warmup_queries if q.query_id.upper() in query_filter]

                console.print(f"[dim]Warmup {warmup_iter + 1}/{warmup_iterations} (stream {warmup_stream_id})[/dim]")
                for query in warmup_queries:
                    try:
                        result = adapter.execute_query(ctx, query)
                        result = dict(result)
                    except Exception as e:
                        logger.warning(f"Warmup query {query.query_id} failed: {e}")
                        result = {
                            "query_id": query.query_id,
                            "status": "FAILED",
                            "error": str(e),
                            "execution_time_seconds": 0.0,
                        }
                    result["iteration"] = 0
                    result["stream_id"] = warmup_stream_id
                    result["run_type"] = "warmup"
                    query_results.append(result)

        # Execute measurement iterations
        # Each measurement iteration uses a different stream_id (continues from warmup)
        console.print(
            f"\n[cyan]Running {measurement_iterations} measurement iteration(s) with {total_queries} queries each...[/cyan]"
        )

        for iteration in range(measurement_iterations):
            # Each measurement iteration uses a unique stream_id
            # Stream IDs continue from where warmup left off
            measurement_stream_id = warmup_iterations + iteration
            _setup_parameter_overrides_for_stream(
                benchmark_id=benchmark_id,
                seed=seed,
                scale_factor=scale_factor,
                stream_id=measurement_stream_id,
                applied_contexts=override_contexts_applied,
            )
            measurement_queries = _get_queries_for_benchmark(
                benchmark_config, benchmark_instance, stream_id=measurement_stream_id
            )
            if query_filter:
                measurement_queries = [q for q in measurement_queries if q.query_id.upper() in query_filter]

            console.print(
                f"\n[green]Iteration {iteration + 1}/{measurement_iterations} (stream {measurement_stream_id})[/green]"
            )

            for i, query in enumerate(measurement_queries, 1):
                if options.get("verbose") or options.get("very_verbose"):
                    console.print(f"[blue]Executing query {i}/{total_queries}: {query.query_id}[/blue]")

                def execute_single_query(q=query):
                    """Execute a single query and return the result."""
                    try:
                        result = adapter.execute_query(ctx, q)
                        result = dict(result)
                    except Exception as e:
                        logger.error(f"Query {q.query_id} failed: {e}")
                        result = {
                            "query_id": q.query_id,
                            "status": "FAILED",
                            "error": str(e),
                            "execution_time_seconds": 0.0,
                        }
                    result["iteration"] = iteration + 1
                    result["stream_id"] = measurement_stream_id
                    result["run_type"] = "measurement"
                    query_results.append(result)

                # Use time_operation context manager for consistent monitoring
                if monitor:
                    with monitor.time_operation(f"query_{query.query_id}_iter{iteration + 1}"):
                        execute_single_query()
                else:
                    execute_single_query()

        return query_results
    finally:
        # Always clear overrides, including early-return and exception paths.
        _clear_parameter_overrides(benchmark_id)


def _setup_parameter_overrides_for_stream(
    benchmark_id: str,
    seed: int | None,
    scale_factor: float,
    stream_id: int,
    applied_contexts: set[tuple[int, float, int | None]],
) -> None:
    """Apply parameter overrides once per unique seed/SF(/stream) context."""
    # Scale-dependent parameter defaults (e.g. Q11's 0.0001/SF value threshold)
    # apply with or without a seed, so set the scale factor on every call. This
    # keeps the unseeded DataFrame run path scale-faithful, mirroring the SQL
    # side's {q11_fraction} rendering. Seed-derived overrides below still take
    # precedence over the scaled default.
    _setup_scale_dependent_defaults(benchmark_id, scale_factor)

    if seed is None:
        return

    context_key: tuple[int, float, int | None]
    if benchmark_id == "tpcds":
        context_key = (seed, scale_factor, stream_id)
    else:
        # TPC-H extraction is stream-independent.
        context_key = (seed, scale_factor, None)

    if context_key in applied_contexts:
        return

    _setup_parameter_overrides(benchmark_id, seed, scale_factor, stream_id=stream_id)
    applied_contexts.add(context_key)


def _setup_scale_dependent_defaults(benchmark_id: str, scale_factor: float) -> None:
    """Align scale-dependent parameter defaults with the run's scale factor.

    Canonical TPC-H Q11 renders its value threshold as ``0.0001 / SF``. Unseeded
    DataFrame runs would otherwise read the SF=1 default at every scale; setting
    the scale factor here keeps them aligned with the SQL run path. TPC-H Skew
    and TPC-Havoc reuse the same TPC-H DataFrame parameter seam, so they are
    handled the same way (see :data:`_TPCH_FAMILY_DATAFRAME_IDS`).
    """
    if benchmark_id in _TPCH_FAMILY_DATAFRAME_IDS:
        try:
            from benchbox.core.tpch.dataframe_queries import set_scale_factor

            set_scale_factor(scale_factor)
        except Exception:  # pragma: no cover - defensive; never block execution
            logger.debug("Failed to set TPC-H DataFrame scale factor", exc_info=True)


def _setup_parameter_overrides(
    benchmark_id: str,
    seed: int | None,
    scale_factor: float,
    stream_id: int | None = None,
) -> None:
    """Set up seed-based parameter overrides for DataFrame queries.

    When a seed is provided, extracts parameters from qgen/dsqgen binaries
    so that DataFrame queries use identical substitution values to their SQL
    counterparts for the same seed.

    If no seed is provided or extraction fails, queries fall back to static
    default parameters (the previous behavior).
    """
    if seed is None:
        return

    if benchmark_id == "tpch":
        try:
            from benchbox.core.tpch.dataframe_queries import set_parameter_overrides
            from benchbox.core.tpch.parameter_extractor import get_tpch_extracted_parameters

            overrides = get_tpch_extracted_parameters(seed, scale_factor)
            if overrides:
                set_parameter_overrides(overrides)
                logger.info(f"TPC-H parameter overrides set for seed={seed} ({len(overrides)} queries)")
            else:
                logger.debug(f"No TPC-H parameter overrides extracted for seed={seed}")
        except Exception:
            logger.warning(
                "Failed to extract TPC-H parameters for seed=%d; using static defaults",
                seed,
                exc_info=True,
            )

    elif benchmark_id == "tpcds":
        try:
            from benchbox.core.tpcds.dataframe_queries.parameters import set_parameter_overrides
            from benchbox.core.tpcds.parameter_extractor import get_tpcds_extracted_parameters

            overrides = get_tpcds_extracted_parameters(seed, scale_factor, stream_id)
            if overrides:
                set_parameter_overrides(overrides)
                logger.info(
                    "TPC-DS parameter overrides set for seed=%s stream=%s (%d queries)",
                    seed,
                    stream_id,
                    len(overrides),
                )
            else:
                logger.debug("No TPC-DS parameter overrides extracted for seed=%s stream=%s", seed, stream_id)
        except Exception:
            logger.warning(
                "Failed to extract TPC-DS parameters for seed=%d stream=%s; using static defaults",
                seed,
                stream_id,
                exc_info=True,
            )


def _clear_parameter_overrides(benchmark_id: str) -> None:
    """Clear parameter overrides after execution."""
    if benchmark_id in _TPCH_FAMILY_DATAFRAME_IDS:
        try:
            from benchbox.core.tpch.dataframe_queries import set_parameter_overrides, set_scale_factor

            set_parameter_overrides(None)
            # Reset the scale-dependent defaults to the SF=1 rendering.
            set_scale_factor(None)
        except Exception:
            pass
    elif benchmark_id == "tpcds":
        try:
            from benchbox.core.tpcds.dataframe_queries.parameters import set_parameter_overrides

            set_parameter_overrides(None)
        except Exception:
            pass


def _get_queries_for_benchmark(
    benchmark_config: BenchmarkConfig,
    benchmark_instance: Any | None,
    stream_id: int | None = None,
) -> list[Any]:
    """Get DataFrame queries for a benchmark in proper execution order.

    For TPC-H power tests, queries are returned in the TPC-H specification's
    permutation order based on stream_id. This is required for TPC-H compliance.

    Args:
        benchmark_config: Benchmark configuration
        benchmark_instance: Optional benchmark instance
        stream_id: Stream ID for query permutation (default: from config or 0).
                   Each stream ID produces a different query execution order
                   per TPC-H/TPC-DS specification.

    Returns:
        List of DataFrameQuery objects in execution order for the given stream.
    """
    benchmark_id = normalize_benchmark_id(benchmark_config.name)

    # Use provided stream_id, or fall back to config, or default to 0
    if stream_id is None:
        stream_id = getattr(benchmark_config, "stream_id", 0)

    _dispatch = {
        "tpch": _get_tpch_dataframe_queries,
        "tpcds": _get_tpcds_dataframe_queries,
        "clickbench": _get_clickbench_dataframe_queries,
    }

    handler = _dispatch.get(benchmark_id)
    if handler:
        return handler(benchmark_config, benchmark_instance, stream_id)

    # Try benchmark instance
    if _benchmark_provides_dataframe_queries(benchmark_instance):
        return benchmark_instance.get_dataframe_queries()

    return []


def _get_tpch_dataframe_queries(
    benchmark_config: BenchmarkConfig,
    benchmark_instance: Any | None,
    stream_id: int,
) -> list[Any]:
    """Get TPC-H DataFrame queries in permuted order for the given stream."""
    return get_tpch_dataframe_queries(stream_id)


def _get_tpcds_dataframe_queries(
    benchmark_config: BenchmarkConfig,
    benchmark_instance: Any | None,
    stream_id: int,
) -> list[Any]:
    """Get TPC-DS DataFrame queries in permuted order for the given stream."""
    return get_tpcds_dataframe_queries(benchmark_config, benchmark_instance, stream_id)


def _resolve_tpcds_query_manager(benchmark_instance: Any | None) -> Any | None:
    """Resolve the TPC-DS query manager from a benchmark instance."""
    return resolve_tpcds_query_manager(benchmark_instance)


def _get_tpcds_legacy_queries(available_query_ids: list[int], stream_id: int) -> list[Any]:
    """Get TPC-DS queries using legacy 99-query ordering (no query manager)."""
    return get_tpcds_legacy_queries(available_query_ids, stream_id)


def _resolve_tpcds_stream_queries(stream_queries: list[Any], allow_variant_fallback: bool) -> list[Any]:
    """Resolve TPC-DS stream queries to DataFrame queries, handling variants."""
    return resolve_tpcds_stream_queries(stream_queries, allow_variant_fallback)


def _get_clickbench_dataframe_queries(
    benchmark_config: BenchmarkConfig,
    benchmark_instance: Any | None,
    stream_id: int,
) -> list[Any]:
    """Get ClickBench DataFrame queries."""
    return get_clickbench_dataframe_queries(benchmark_config, benchmark_instance, stream_id)


def is_dataframe_execution(database_config: Any) -> bool:
    """Check if execution should use DataFrame mode.

    DataFrame mode is determined by platform naming convention:
    - polars-df: DataFrame mode
    - pandas-df: DataFrame mode
    - polars: SQL mode (if exists)
    - duckdb: SQL mode

    Args:
        database_config: Database configuration with platform type

    Returns:
        True if DataFrame mode should be used
    """
    if database_config is None:
        return False

    from benchbox.platforms.adapter_factory import is_dataframe_mode

    platform_type = getattr(database_config, "type", "")
    explicit_mode = getattr(database_config, "mode", None)
    return is_dataframe_mode(platform_type, explicit_mode)


def get_execution_mode(database_config: Any) -> str:
    """Get the execution mode for a platform.

    Args:
        database_config: Database configuration

    Returns:
        "dataframe" or "sql"
    """
    if is_dataframe_execution(database_config):
        return "dataframe"
    return "sql"

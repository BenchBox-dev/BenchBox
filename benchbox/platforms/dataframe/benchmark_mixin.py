"""Benchmark execution mixin for DataFrame adapters.

This module provides the BenchmarkExecutionMixin that adds run_benchmark()
capability to DataFrame adapters, enabling unified interface with SQL adapters.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import inspect
import logging
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
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
    benchmark_provides_dataframe_queries,
    build_dataframe_query_filter_from_config,
    get_dataframe_queries_for_benchmark,
    get_tpcds_dataframe_queries,
    get_tpch_dataframe_queries,
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
from benchbox.core.results.schema import compute_plan_capture_stats
from benchbox.core.schemas import BenchmarkConfig, SystemProfile
from benchbox.platforms.base.adapter import DriverIsolationCapability
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.printing import quiet_console

if TYPE_CHECKING:
    from benchbox.core.dataframe.query import DataFrameQuery

logger = logging.getLogger(__name__)

console = quiet_console


def _benchmark_defines_hook(benchmark: Any | None, hook_name: str) -> bool:
    """Return True when a benchmark explicitly defines a hook.

    This accepts real class-defined hooks and explicitly configured mock hooks,
    while rejecting synthetic MagicMock attributes created via ``__getattr__``.
    """
    if benchmark is None:
        return False

    hook = type(benchmark).__dict__.get(hook_name)
    if callable(hook):
        return True

    instance_hook = benchmark.__dict__.get(hook_name)
    if callable(instance_hook):
        return True

    mock_children = getattr(benchmark, "_mock_children", None)
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


def _benchmark_manages_dataframe_loading(benchmark: Any | None) -> bool:
    """Return True when a benchmark explicitly owns DataFrame loading.

    Use class-level hook detection so dynamic test doubles such as MagicMock do
    not accidentally appear to implement the hook via ``__getattr__``.
    """
    if not _benchmark_defines_hook(benchmark, "skip_dataframe_data_loading"):
        return False

    return bool(benchmark.skip_dataframe_data_loading())


def _benchmark_supports_dataframe_workload(benchmark: Any | None) -> bool:
    """Return True when a benchmark defines a custom DataFrame workload hook.

    Use class-level hook detection so dynamic test doubles such as MagicMock do
    not accidentally appear to implement the hook via ``__getattr__``.
    """
    return _benchmark_defines_hook(benchmark, "execute_dataframe_workload")


def _benchmark_provides_dataframe_queries(benchmark: Any | None) -> bool:
    """Return True when a benchmark defines a DataFrame query provider hook."""
    return benchmark_provides_dataframe_queries(benchmark)


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


class DataLoadingError(RuntimeError):
    """Raised when DataFrame data loading fails critically."""

    def __init__(
        self,
        message: str,
        table_stats: dict[str, int] | None = None,
        per_table_stats: dict[str, TableLoadingStats] | None = None,
    ) -> None:
        super().__init__(message)
        self.table_stats = table_stats or {}
        self.per_table_stats = per_table_stats or {}


class BenchmarkExecutionMixin:
    """Mixin providing run_benchmark() for DataFrame adapters.

    This mixin adds unified benchmark execution capability to DataFrame
    adapters, enabling them to be used interchangeably with SQL adapters.

    The adapter must provide:
    - platform_name: str property
    - family: str property ("expression" or "pandas")
    - create_context() method
    - load_table() method
    - execute_query() method
    - get_platform_info() method (optional)
    """

    # Default: most DataFrame adapters have no versioned driver package.
    # Subclasses like DataFusionDataFrameAdapter override to SUPPORTED.
    driver_isolation_capability: DriverIsolationCapability = DriverIsolationCapability.NOT_APPLICABLE
    is_dataframe_adapter: bool = True

    # These must be provided by the adapter class
    platform_name: str
    family: str

    @abstractmethod
    def create_context(self) -> Any:
        """Create execution context."""

    @abstractmethod
    def load_table(
        self,
        ctx: Any,
        table_name: str,
        file_paths: list[Path],
        column_names: list[str] | None = None,
    ) -> int:
        """Load a table into context."""

    @abstractmethod
    def execute_query(
        self,
        ctx: Any,
        query: DataFrameQuery,
        query_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a query."""

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information. Override in subclass for details."""
        return {"platform": self.platform_name, "family": self.family}

    def _enrich_with_driver_metadata(self, info: dict[str, Any]) -> None:
        """Add driver runtime contract metadata to a platform info dict.

        Call this from subclass get_platform_info() implementations to propagate
        driver version/isolation metadata set by the adapter factory.
        """
        for attr in (
            "driver_version_requested",
            "driver_version_resolved",
            "driver_version_actual",
            "driver_runtime_strategy",
        ):
            value = getattr(self, attr, None)
            if value:
                info[attr] = value

    def run_benchmark(
        self,
        benchmark: Any,
        *,
        benchmark_config: BenchmarkConfig | None = None,
        system_profile: SystemProfile | None = None,
        data_dir: Path | None = None,
        phases: DataFramePhases | None = None,
        options: DataFrameRunOptions | None = None,
        monitor: Any | None = None,
        **run_config: Any,
    ) -> BenchmarkResults:
        """Run a benchmark using DataFrame mode execution.

        This method provides a unified interface matching SQL adapters,
        allowing DataFrame adapters to be used interchangeably.

        Args:
            benchmark: Benchmark instance with query definitions
            benchmark_config: Optional explicit benchmark configuration.
                             If not provided, extracted from benchmark instance.
            system_profile: System profile for resource information
            data_dir: Directory containing benchmark data files
            phases: Which phases to execute (default: load and execute)
            options: DataFrame-specific execution options
            monitor: Performance monitor for tracking
            **run_config: Additional configuration options

        Returns:
            BenchmarkResults with execution details
        """
        phases = phases or DataFramePhases()
        if isinstance(options, dict):
            options = DataFrameRunOptions(**options)
        else:
            options = options or DataFrameRunOptions()

        # Extract benchmark_config from benchmark if not provided
        if benchmark_config is None:
            benchmark_config = self._extract_benchmark_config(benchmark, run_config)

        platform_name = self.platform_name
        scale_factor = getattr(benchmark_config, "scale_factor", 1.0)

        logger.info(f"Starting DataFrame benchmark: {benchmark_config.name}")
        logger.info(f"Platform: {platform_name}, Scale Factor: {scale_factor}")

        # Build platform info using standardized extractor
        platform_info = build_platform_info(self, execution_mode="dataframe")

        # Create result builder
        builder = ResultBuilder(
            benchmark=BenchmarkInfoInput(
                name=benchmark_config.name,
                scale_factor=scale_factor,
                test_type=getattr(benchmark_config, "test_execution_type", "power"),
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
            ctx = self.create_context()

            skip_data_loading = _benchmark_manages_dataframe_loading(benchmark)

            # Load phase
            if phases.load and not skip_data_loading:
                load_start = mono_time()
                try:
                    table_stats, per_table_stats = self._load_data_phase(
                        ctx=ctx,
                        benchmark_config=benchmark_config,
                        benchmark_instance=benchmark,
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

                except DataLoadingError as load_err:
                    load_time = elapsed_seconds(load_start)

                    # Add failed table stats to builder
                    for table_name, stats in load_err.per_table_stats.items():
                        builder.add_table_stats(
                            table_name,
                            stats.rows,
                            load_time_ms=stats.load_time_ms,
                            status=stats.status,
                            error_message=stats.error_message,
                        )
                    builder.set_loading_time(load_time * 1000)
                    builder.set_validation_status(
                        "FAILED",
                        {"error": str(load_err), "phase": "data_loading"},
                    )
                    builder.set_phase_status("data_loading", "FAILED")
                    builder.mark_completed()
                    return builder.build()
            elif phases.load and skip_data_loading:
                logger.info("Skipping DataFrame table loading for benchmark-managed workload")
                builder.set_phase_status("data_loading", "SKIPPED")

            # Execute phase
            if phases.execute:
                query_results = self._execute_queries_phase(
                    ctx=ctx,
                    benchmark_config=benchmark_config,
                    benchmark_instance=benchmark,
                    monitor=monitor,
                    run_options=options,
                )

                # Add query results to builder
                for qr in query_results:
                    builder.add_query_result(normalize_query_result(qr))

                plans_captured, capture_failures, capture_errors = compute_plan_capture_stats(
                    query_results, getattr(benchmark_config, "capture_plans", False)
                )
                builder.add_plan_capture_stats(
                    plans_captured=plans_captured,
                    capture_failures=capture_failures,
                    capture_errors=capture_errors,
                )
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

    def _extract_benchmark_config(self, benchmark: Any, run_config: dict[str, Any]) -> BenchmarkConfig:
        """Extract BenchmarkConfig from benchmark instance or run_config."""
        # Check if benchmark has config attribute
        if hasattr(benchmark, "config") and isinstance(benchmark.config, BenchmarkConfig):
            return benchmark.config

        # Build from benchmark attributes and run_config
        name = getattr(benchmark, "_name", getattr(benchmark, "name", type(benchmark).__name__.lower()))
        display_name = getattr(benchmark, "display_name", name.upper())
        scale_factor = run_config.get("scale_factor", getattr(benchmark, "scale_factor", 1.0))
        queries = run_config.get("query_subset", run_config.get("queries"))
        capture_plans = bool(run_config.get("capture_plans", False))

        return BenchmarkConfig(
            name=name,
            display_name=display_name,
            scale_factor=scale_factor,
            queries=queries,
            capture_plans=capture_plans,
        )

    @staticmethod
    def _normalize_table_paths(tables: dict[str, Any]) -> dict[str, Path | list[Path]]:
        """Normalize table paths to Path objects."""
        normalized: dict[str, Path | list[Path]] = {}
        for name, path in tables.items():
            if isinstance(path, list):
                normalized[name] = [Path(p) if not isinstance(p, Path) else p for p in path]
            elif isinstance(path, Path):
                normalized[name] = path
            else:
                normalized[name] = Path(path)
        return normalized

    @staticmethod
    def _find_missing_paths(paths: dict[str, Path | list[Path]]) -> dict[str, list[Path]]:
        """Find data paths that don't exist on disk."""
        missing: dict[str, list[Path]] = {}
        for table_name, file_path in paths.items():
            file_list = file_path if isinstance(file_path, list) else [file_path]
            for entry in file_list:
                entry_path = entry if isinstance(entry, Path) else Path(entry)
                if not entry_path.exists():
                    missing.setdefault(table_name, []).append(entry_path)
        return missing

    @staticmethod
    def _raise_missing_paths_error(missing_paths: dict[str, list[Path]]) -> None:
        """Raise DataLoadingError with per-table stats for missing files."""
        per_table_stats: dict[str, TableLoadingStats] = {}
        for table_name, paths in missing_paths.items():
            missing_list = ", ".join(str(p) for p in paths[:5])
            more = "..." if len(paths) > 5 else ""
            per_table_stats[table_name] = TableLoadingStats(
                rows=0,
                load_time_ms=0,
                status="FAILED",
                error_type="MissingDataError",
                error_message=f"Missing data files: {missing_list}{more}",
            )
        missing_summary = "; ".join(f"{t}: {len(p)} file(s)" for t, p in missing_paths.items())
        raise DataLoadingError(
            "Data files not found. Missing: "
            f"{missing_summary}. Run with --phases generate,load or --force-regenerate to recreate data.",
            per_table_stats=per_table_stats,
        )

    def _resolve_data_paths_from_tables(
        self,
        benchmark_instance: Any,
        options: DataFrameRunOptions,
    ) -> dict[str, Path | list[Path]]:
        """Resolve data paths from benchmark instance tables, preferring parquet when configured."""
        parquet_dir = None
        if options.prefer_parquet:
            first_path = next(iter(benchmark_instance.tables.values()))
            if isinstance(first_path, list):
                first_path = first_path[0]
            first_path = Path(first_path)
            parent_dir = first_path.parent
            for pq_candidate in parent_dir.glob("*.parquet"):
                if pq_candidate.is_dir():
                    parquet_dir = pq_candidate
                    logger.info(f"Found parquet directory: {parquet_dir}")
                    break

        if parquet_dir and parquet_dir.is_dir():
            data_paths: dict[str, Path | list[Path]] = {}
            for pq_file in parquet_dir.glob("*.parquet"):
                table_name = pq_file.stem
                data_paths[table_name] = pq_file
            logger.info(f"Using parquet data: {len(data_paths)} tables from {parquet_dir}")
            return data_paths

        data_paths = self._normalize_table_paths(benchmark_instance.tables)
        logger.info(f"Using benchmark-provided data: {len(data_paths)} tables")
        return data_paths

    def _resolve_data_paths(
        self,
        benchmark_instance: Any | None,
        data_dir: Path | None,
        options: DataFrameRunOptions,
        loader: DataFrameDataLoader,
    ) -> dict[str, Path | list[Path]]:
        """Resolve data paths from available sources (tables, data_dir, or generation).

        Priority order (highest to lowest):
        1. benchmark_instance.tables - authoritative if populated (even after force_regenerate,
           since generate_data() populates .tables as a side effect)
        2. data_dir discovery - scan filesystem for data files
        3. benchmark_instance.generate_data() - last resort, generate from scratch
        """
        data_paths: dict[str, Path | list[Path]] = {}

        if options.force_regenerate and benchmark_instance and hasattr(benchmark_instance, "generate_data"):
            data_paths = self._generate_benchmark_data(benchmark_instance)

        if benchmark_instance and hasattr(benchmark_instance, "tables") and benchmark_instance.tables:
            data_paths = self._resolve_data_paths_from_tables(benchmark_instance, options)
        elif data_dir and data_dir.exists():
            data_paths = loader._discover_files(data_dir)
            logger.info(f"Discovered data in {data_dir}: {len(data_paths)} tables")
            if not data_paths and benchmark_instance and hasattr(benchmark_instance, "generate_data"):
                data_paths = self._generate_benchmark_data(benchmark_instance)
        elif benchmark_instance and hasattr(benchmark_instance, "generate_data"):
            try:
                data_paths = self._generate_benchmark_data(benchmark_instance)
                if data_paths:
                    logger.info(f"Generated data: {len(data_paths)} tables")
            except Exception as gen_err:
                logger.warning(f"Data generation failed: {gen_err}")

        return data_paths

    def _generate_benchmark_data(self, benchmark_instance: Any) -> dict[str, Path | list[Path]]:
        """Generate benchmark data and return normalized table paths."""
        logger.info("Generating benchmark data...")
        benchmark_instance.generate_data()
        if hasattr(benchmark_instance, "tables") and benchmark_instance.tables:
            return self._normalize_table_paths(benchmark_instance.tables)
        return {}

    def _resolve_column_names_and_delimiter(
        self,
        benchmark_config: BenchmarkConfig,
        benchmark_instance: Any | None,
    ) -> tuple[dict[str, list[str]], str | None]:
        """Resolve column name mappings and CSV delimiter for the benchmark.

        Returns:
            Tuple of (column_names_map, csv_delimiter)
        """
        benchmark_id = normalize_benchmark_id(benchmark_config.name)
        if benchmark_id != "tpch" and benchmark_instance is not None:
            source_benchmark = getattr(benchmark_instance, "get_data_source_benchmark", lambda: None)()
            if source_benchmark == "tpch":
                benchmark_id = "tpch"
        column_names_map = {
            table_name: [column["name"] for column in columns]
            for table_name, columns in get_benchmark_schema_columns(benchmark_instance).items()
        }
        if benchmark_id == "tpch":
            column_names_map.update(get_tpch_column_names())

        csv_delimiter = getattr(benchmark_instance, "csv_delimiter", None)

        return column_names_map, csv_delimiter

    def _load_tables_into_context(
        self,
        ctx: Any,
        data_paths: dict[str, Path | list[Path]],
        column_names_map: dict[str, list[str]],
        csv_delimiter: str | None,
    ) -> tuple[dict[str, int], dict[str, TableLoadingStats]]:
        """Load all tables into the execution context.

        Returns:
            Tuple of (table_stats, per_table_loading_stats)

        Raises:
            DataLoadingError: If any tables fail to load.
        """
        table_stats: dict[str, int] = {}
        per_table_stats: dict[str, TableLoadingStats] = {}

        for table_name, file_path in data_paths.items():
            load_start = mono_time()
            try:
                column_names = column_names_map.get(table_name.lower())
                file_paths = [file_path] if not isinstance(file_path, list) else file_path
                row_count = self.load_table(
                    ctx, table_name.lower(), file_paths, column_names=column_names, delimiter=csv_delimiter
                )
                load_time_ms = int((elapsed_seconds(load_start)) * 1000)

                table_stats[table_name] = row_count
                per_table_stats[table_name] = TableLoadingStats(
                    rows=row_count,
                    load_time_ms=load_time_ms,
                    status="SUCCESS",
                )
                logger.debug(f"Loaded {table_name}: {row_count:,} rows in {load_time_ms}ms")

            except Exception as e:
                load_time_ms = int((elapsed_seconds(load_start)) * 1000)
                per_table_stats[table_name] = TableLoadingStats(
                    rows=0,
                    load_time_ms=load_time_ms,
                    status="FAILED",
                    error_type=type(e).__name__,
                    error_message=str(e),
                )
                logger.error(f"Failed to load {table_name}: {e}")

        failed_tables = [name for name, stats in per_table_stats.items() if stats.status == "FAILED"]
        if failed_tables:
            raise DataLoadingError(
                f"Failed to load {len(failed_tables)} table(s): {', '.join(failed_tables)}.",
                table_stats=table_stats,
                per_table_stats=per_table_stats,
            )

        return table_stats, per_table_stats

    def _load_data_phase(
        self,
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
        platform_name = self.platform_name.lower()

        loader = DataFrameDataLoader(
            platform=platform_name,
            cache_dir=options.cache_dir,
            prefer_parquet=options.prefer_parquet,
            force_regenerate=options.force_regenerate,
        )

        options_map = getattr(benchmark_config, "options", {}) or {}
        df_tuning_config = options_map.get("df_tuning_config")
        write_config = getattr(df_tuning_config, "write", None) if df_tuning_config else None

        def _prepare_data_or_raise() -> dict[str, Path | list[Path]]:
            if benchmark_instance is None:
                raise DataLoadingError("Cannot prepare Parquet data without a benchmark instance.")
            try:
                prepared_paths = loader.prepare_benchmark_data(
                    benchmark_instance,
                    scale_factor=getattr(benchmark_config, "scale_factor", 1.0),
                    data_dir=data_dir,
                    write_config=write_config,
                )
            except Exception as prep_err:
                raise DataLoadingError(
                    f"Data preparation failed in prefer_parquet mode: {type(prep_err).__name__}: {prep_err}"
                ) from prep_err
            if not prepared_paths:
                raise DataLoadingError("Data preparation produced no table paths in prefer_parquet mode.")
            logger.info(f"Using prepared data: {len(prepared_paths)} tables")
            return prepared_paths

        # Resolve data paths from available sources
        data_paths = self._resolve_data_paths(benchmark_instance, data_dir, options, loader)

        if not data_paths:
            raise ValueError("No data source available. Either provide data_dir or generate data first.")

        if options.prefer_parquet:
            data_paths = _prepare_data_or_raise()

        # Verify paths exist, regenerate if needed
        missing_paths = self._find_missing_paths(data_paths)
        if missing_paths and benchmark_instance and hasattr(benchmark_instance, "generate_data"):
            logger.info("Missing data files detected, regenerating benchmark data...")
            data_paths = self._generate_benchmark_data(benchmark_instance)
            if options.prefer_parquet:
                data_paths = _prepare_data_or_raise()
            missing_paths = self._find_missing_paths(data_paths)

        if missing_paths:
            self._raise_missing_paths_error(missing_paths)

        # Resolve schema and delimiter info
        column_names_map, csv_delimiter = self._resolve_column_names_and_delimiter(benchmark_config, benchmark_instance)

        # Load tables into context
        return self._load_tables_into_context(ctx, data_paths, column_names_map, csv_delimiter)

    def _execute_queries_phase(
        self,
        ctx: Any,
        benchmark_config: BenchmarkConfig,
        benchmark_instance: Any | None,
        monitor: Any | None,
        run_options: DataFrameRunOptions | None = None,
    ) -> list[dict[str, Any]]:
        """Execute DataFrame queries, scoping scale-dependent parameter defaults.

        Canonical TPC-H Q11 renders its value threshold as ``0.0001 / SF``.
        Unseeded DataFrame runs read the SF=1 default unless the scale factor is
        declared, so set it for TPC-H-family benchmarks for the duration of query
        execution (mirroring the SQL run path's ``{q11_fraction}`` rendering) and
        reset it afterwards on every path.
        """
        from benchbox.core.tpch.dataframe_queries import set_scale_factor_for_benchmark

        benchmark_id = normalize_benchmark_id(benchmark_config.name)
        scale_factor = getattr(benchmark_config, "scale_factor", 1.0)
        set_scale_factor_for_benchmark(benchmark_id, scale_factor)
        try:
            return self._run_query_iterations(
                ctx=ctx,
                benchmark_config=benchmark_config,
                benchmark_instance=benchmark_instance,
                monitor=monitor,
                run_options=run_options,
            )
        finally:
            set_scale_factor_for_benchmark(benchmark_id, None)

    def _run_query_iterations(
        self,
        ctx: Any,
        benchmark_config: BenchmarkConfig,
        benchmark_instance: Any | None,
        monitor: Any | None,
        run_options: DataFrameRunOptions | None = None,
    ) -> list[dict[str, Any]]:
        """Execute DataFrame queries with warmup and measurement iterations.

        Follows TPC power test methodology:
        1. Warmup iterations (default 1): Prime caches, not included in results
        2. Measurement iterations (default 3): Timed runs, results aggregated
        """
        # Get warmup and iteration counts from config options
        config_options = getattr(benchmark_config, "options", {}) or {}
        warmup_iterations_raw = config_options.get("power_warmup_iterations")
        measurement_iterations_raw = config_options.get("power_iterations")
        warmup_iterations = (
            GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS if warmup_iterations_raw is None else int(warmup_iterations_raw)
        )
        measurement_iterations = (
            GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS
            if measurement_iterations_raw is None
            else int(measurement_iterations_raw)
        )

        query_filter = self._build_query_filter(benchmark_config)

        # Benchmark-specific DataFrame workload hook for non-query style benchmarks
        if _benchmark_supports_dataframe_workload(benchmark_instance):
            return benchmark_instance.execute_dataframe_workload(
                ctx=ctx,
                adapter=self,
                benchmark_config=benchmark_config,
                query_filter=query_filter,
                monitor=monitor,
                run_options=run_options,
            )

        skip_query_ids = self._collect_skip_query_ids(benchmark_instance)

        # Get initial query set to determine total count
        initial_queries = self._filter_queries(
            self._get_queries_for_benchmark(benchmark_config, benchmark_instance, stream_id=0),
            skip_query_ids,
            query_filter,
        )

        filtered_skip_query_ids = skip_query_ids
        if query_filter and skip_query_ids:
            filtered_skip_query_ids = {query_id for query_id in skip_query_ids if query_id in query_filter}

        skipped_results = self._build_skipped_results(filtered_skip_query_ids)

        if not initial_queries:
            return self._handle_no_queries(skipped_results, filtered_skip_query_ids)

        total_queries = len(initial_queries)
        logger.info(f"Executing {total_queries} queries")
        logger.info(f"Warmup iterations: {warmup_iterations}, Measurement iterations: {measurement_iterations}")

        query_results: list[dict[str, Any]] = list(skipped_results)
        executed_query_ids: list[str] = []

        # Execute warmup iterations (emit results)
        self._run_warmup_iterations(
            ctx=ctx,
            warmup_iterations=warmup_iterations,
            benchmark_config=benchmark_config,
            benchmark_instance=benchmark_instance,
            skip_query_ids=skip_query_ids,
            query_filter=query_filter,
            query_results=query_results,
        )

        # Execute measurement iterations
        self._run_measurement_iterations(
            ctx=ctx,
            measurement_iterations=measurement_iterations,
            warmup_iterations=warmup_iterations,
            total_queries=total_queries,
            benchmark_config=benchmark_config,
            benchmark_instance=benchmark_instance,
            skip_query_ids=skip_query_ids,
            query_filter=query_filter,
            monitor=monitor,
            run_options=run_options,
            query_results=query_results,
            executed_query_ids=executed_query_ids,
        )

        if filtered_skip_query_ids:
            self._append_skip_summary(query_results, set(executed_query_ids), filtered_skip_query_ids)

        return query_results

    @staticmethod
    def _build_query_filter(benchmark_config: BenchmarkConfig) -> set[str] | None:
        """Normalize query subset into a bidirectional filter set (Q1 <-> 1)."""
        return build_dataframe_query_filter_from_config(benchmark_config)

    def _collect_skip_query_ids(self, benchmark_instance: Any | None) -> set[str]:
        """Collect all query IDs to skip from benchmark and platform-specific sources."""
        skip_query_ids: set[str] = set()

        if benchmark_instance and hasattr(benchmark_instance, "get_dataframe_skip_queries"):
            raw_skip_ids = benchmark_instance.get_dataframe_skip_queries()  # type: ignore[no-untyped-call]
            skip_query_ids = {str(query_id).strip().upper() for query_id in raw_skip_ids}

        if (
            hasattr(self, "family")
            and self.family == "expression"
            and benchmark_instance
            and hasattr(benchmark_instance, "get_expression_family_skip_queries")
        ):
            expr_skip_ids = benchmark_instance.get_expression_family_skip_queries()
            skip_query_ids |= {str(query_id).strip().upper() for query_id in expr_skip_ids}

        if (
            hasattr(self, "platform_name")
            and benchmark_instance
            and hasattr(benchmark_instance, "get_platform_skip_queries")
        ):
            platform_skip_ids = benchmark_instance.get_platform_skip_queries(self.platform_name)
            skip_query_ids |= {str(query_id).strip().upper() for query_id in platform_skip_ids}

        # Platform-specific skips for DataFrame mode only
        if (
            hasattr(self, "platform_name")
            and benchmark_instance
            and hasattr(benchmark_instance, "get_df_platform_skip_queries")
        ):
            df_skip_ids = benchmark_instance.get_df_platform_skip_queries(self.platform_name)
            skip_query_ids |= {str(query_id).strip().upper() for query_id in df_skip_ids}

        return skip_query_ids

    @staticmethod
    def _filter_queries(
        queries: list[DataFrameQuery],
        skip_query_ids: set[str],
        query_filter: set[str] | None,
    ) -> list[DataFrameQuery]:
        """Apply skip and filter sets to a query list."""
        if skip_query_ids:
            queries = [q for q in queries if q.query_id.upper() not in skip_query_ids]
        if query_filter:
            queries = [q for q in queries if q.query_id.upper() in query_filter]
        return queries

    @staticmethod
    def _build_skipped_results(filtered_skip_query_ids: set[str]) -> list[dict[str, Any]]:
        """Build result entries for skipped queries."""
        if not filtered_skip_query_ids:
            return []
        return [
            {
                "query_id": query_id,
                "status": "SKIPPED",
                "execution_time_seconds": 0.0,
                "error": "Skipped in DataFrame mode (SQL-only primitive)",
                "run_type": "metadata",
                "stream_id": 0,
                "iteration": 0,
            }
            for query_id in sorted(filtered_skip_query_ids)
        ]

    def _handle_no_queries(
        self,
        skipped_results: list[dict[str, Any]],
        filtered_skip_query_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Handle the case where no executable queries are found."""
        logger.warning("No queries found for execution")
        if skipped_results:
            skipped_categories = self._count_query_categories(filtered_skip_query_ids)
            skipped_results.append(
                {
                    "query_id": "DF_SKIP_SUMMARY",
                    "status": "SUCCESS",
                    "execution_time_seconds": 0.0,
                    "run_type": "summary",
                    "stream_id": 0,
                    "iteration": 0,
                    "rows_returned": len(filtered_skip_query_ids),
                    "dataframe_skip_summary": {
                        "executed_total": 0,
                        "skipped_total": len(filtered_skip_query_ids),
                        "executed_by_category": {},
                        "skipped_by_category": skipped_categories,
                    },
                }
            )
            return skipped_results
        return []

    def _run_warmup_iterations(
        self,
        ctx: Any,
        warmup_iterations: int,
        benchmark_config: BenchmarkConfig,
        benchmark_instance: Any | None,
        skip_query_ids: set[str],
        query_filter: set[str] | None,
        query_results: list[dict[str, Any]],
    ) -> None:
        """Execute warmup iterations, appending results to query_results."""
        if warmup_iterations <= 0:
            return

        console.print(f"\n[yellow]Running {warmup_iterations} warmup iteration(s)...[/yellow]")
        for warmup_iter in range(warmup_iterations):
            warmup_queries = self._filter_queries(
                self._get_queries_for_benchmark(benchmark_config, benchmark_instance, stream_id=0),
                skip_query_ids,
                query_filter,
            )

            console.print(f"[dim]Warmup {warmup_iter + 1}/{warmup_iterations} (stream 0)[/dim]")
            for query in warmup_queries:
                try:
                    result = self.execute_query(ctx, query)
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
                result["stream_id"] = 0
                result["run_type"] = "warmup"
                query_results.append(result)

    def _run_measurement_iterations(
        self,
        ctx: Any,
        measurement_iterations: int,
        warmup_iterations: int,
        total_queries: int,
        benchmark_config: BenchmarkConfig,
        benchmark_instance: Any | None,
        skip_query_ids: set[str],
        query_filter: set[str] | None,
        monitor: Any | None,
        run_options: DataFrameRunOptions | None,
        query_results: list[dict[str, Any]],
        executed_query_ids: list[str],
    ) -> None:
        """Execute measurement iterations, appending results to query_results and executed_query_ids."""
        capture_plans = bool(getattr(benchmark_config, "capture_plans", False))
        profiled_runner = getattr(self, "execute_query_profiled", None)
        supports_profiled = callable(profiled_runner)
        supports_capture_plan_kw = False
        if supports_profiled:
            try:
                supports_capture_plan_kw = "capture_plan" in inspect.signature(profiled_runner).parameters
            except (TypeError, ValueError):
                supports_capture_plan_kw = False

        console.print(
            f"\n[cyan]Running {measurement_iterations} measurement iteration(s) with {total_queries} queries each...[/cyan]"
        )

        for iteration in range(measurement_iterations):
            measurement_stream_id = warmup_iterations + iteration
            measurement_queries = self._filter_queries(
                self._get_queries_for_benchmark(benchmark_config, benchmark_instance, stream_id=measurement_stream_id),
                skip_query_ids,
                query_filter,
            )

            console.print(
                f"\n[green]Iteration {iteration + 1}/{measurement_iterations} (stream {measurement_stream_id})[/green]"
            )

            iteration_results: list[dict[str, Any]] = []
            for i, query in enumerate(measurement_queries, 1):
                if run_options and (run_options.verbose or run_options.very_verbose):
                    console.print(f"[blue]Executing query {i}/{total_queries}: {query.query_id}[/blue]")

                result = self._execute_single_measurement_query(
                    ctx=ctx,
                    query=query,
                    capture_plans=capture_plans,
                    supports_profiled=supports_profiled,
                    supports_capture_plan_kw=supports_capture_plan_kw,
                    profiled_runner=profiled_runner,
                    iteration=iteration + 1,
                    stream_id=measurement_stream_id,
                    monitor=monitor,
                )
                query_results.append(result)
                executed_query_ids.append(str(query.query_id).strip().upper())
                iteration_results.append(result)

            self._print_iteration_summary(
                iteration + 1,
                measurement_iterations,
                iteration_results,
                benchmark_config,
            )

    def _execute_single_measurement_query(
        self,
        ctx: Any,
        query: DataFrameQuery,
        capture_plans: bool,
        supports_profiled: bool,
        supports_capture_plan_kw: bool,
        profiled_runner: Any,
        iteration: int,
        stream_id: int,
        monitor: Any | None,
    ) -> dict[str, Any]:
        """Execute a single measurement query, optionally with monitoring and plan capture."""

        def _run() -> dict[str, Any]:
            try:
                if capture_plans and supports_profiled:
                    if supports_capture_plan_kw:
                        raw_result, profile = profiled_runner(ctx, query, capture_plan=True)
                    else:
                        raw_result, profile = profiled_runner(ctx, query)
                    raw_result = dict(raw_result)
                    if profile.query_plan is not None:
                        raw_result["query_plan"] = profile.query_plan
                else:
                    raw_result = self.execute_query(ctx, query)
                    raw_result = dict(raw_result)
            except Exception as e:
                logger.error(f"Query {query.query_id} failed: {e}")
                raw_result = {
                    "query_id": query.query_id,
                    "status": "FAILED",
                    "error": str(e),
                    "execution_time_seconds": 0.0,
                }
            raw_result["iteration"] = iteration
            raw_result["stream_id"] = stream_id
            raw_result["run_type"] = "measurement"
            return raw_result

        if monitor:
            with monitor.time_operation(f"query_{query.query_id}_iter{iteration}"):
                return _run()
        return _run()

    def _append_skip_summary(
        self,
        query_results: list[dict[str, Any]],
        executed_unique_ids: set[str],
        filtered_skip_query_ids: set[str],
    ) -> None:
        """Append a DF_SKIP_SUMMARY entry to query_results."""
        query_results.append(
            {
                "query_id": "DF_SKIP_SUMMARY",
                "status": "SUCCESS",
                "execution_time_seconds": 0.0,
                "run_type": "summary",
                "stream_id": 0,
                "iteration": 0,
                "rows_returned": len(filtered_skip_query_ids),
                "dataframe_skip_summary": {
                    "executed_total": len(executed_unique_ids),
                    "skipped_total": len(filtered_skip_query_ids),
                    "executed_by_category": self._count_query_categories(executed_unique_ids),
                    "skipped_by_category": self._count_query_categories(filtered_skip_query_ids),
                },
            }
        )

    def _print_iteration_summary(
        self,
        iteration: int,
        total_iterations: int,
        iteration_results: list[dict[str, Any]],
        benchmark_config: BenchmarkConfig,
    ) -> None:
        """Print summary for a completed measurement iteration."""
        from benchbox.core.results.metrics import TPCMetricsCalculator

        total_queries = len(iteration_results)
        successful = [r for r in iteration_results if str(r.get("status", "")).upper() == "SUCCESS"]
        successful_count = len(successful)

        exec_times: list[float] = []
        for result in successful:
            exec_time = result.get("execution_time_seconds")
            if exec_time:
                exec_times.append(float(exec_time))

        total_time = sum(exec_times)
        scale_factor = getattr(benchmark_config, "scale_factor", 1.0)
        benchmark_id = normalize_benchmark_id(benchmark_config.name)

        if benchmark_id == "tpch":
            display_name = "TPC-H"
        elif benchmark_id == "tpcds":
            display_name = "TPC-DS"
        else:
            display_name = str(benchmark_config.name).upper()

        # Power@Size is only defined for TPC benchmarks
        is_tpc = benchmark_id in ("tpch", "tpcds")
        power_at_size = None
        if is_tpc and successful_count == total_queries and exec_times:
            power_at_size = TPCMetricsCalculator.calculate_power_at_size(exec_times, scale_factor)

        test_name = f"{display_name} Power Test" if is_tpc else display_name
        console.print(f"\n[dim]Iteration {iteration}/{total_iterations} summary:[/dim]")
        if successful_count == total_queries:
            if power_at_size and power_at_size > 0:
                console.print(f"[green]{test_name} completed: Power@Size = {power_at_size:.2f}[/green]")
            else:
                console.print(f"[green]{test_name} completed[/green]")
            console.print(f"  Queries executed: {total_queries}, Successful: {successful_count}")
            success_rate = successful_count / max(total_queries, 1)
            if display_name == "TPC-H":
                console.print(f"  Success rate: {success_rate:.1%} (TPC-H requires >=95%)")
            else:
                console.print(f"  Success rate: {success_rate:.1%}")
            console.print(f"  Total execution time: {total_time:.2f}s")
        else:
            console.print(f"[yellow]{test_name} completed with failures[/yellow]")
            console.print(
                f"  Queries: {total_queries}, Successful: {successful_count}, "
                f"Failed: {total_queries - successful_count}"
            )

    def _get_queries_for_benchmark(
        self,
        benchmark_config: BenchmarkConfig,
        benchmark_instance: Any | None,
        stream_id: int | None = None,
    ) -> list[DataFrameQuery]:
        """Get DataFrame queries for a benchmark in proper execution order."""
        return get_dataframe_queries_for_benchmark(benchmark_config, benchmark_instance, stream_id)

    @staticmethod
    def _get_tpch_queries(stream_id: int) -> list[DataFrameQuery]:
        """Get TPC-H DataFrame queries in stream-permuted order."""
        return get_tpch_dataframe_queries(stream_id)

    @staticmethod
    def _get_tpcds_queries(
        benchmark_config: BenchmarkConfig,
        benchmark_instance: Any | None,
        stream_id: int,
    ) -> list[DataFrameQuery]:
        """Get TPC-DS DataFrame queries in stream-permuted order with variant resolution."""
        return get_tpcds_dataframe_queries(benchmark_config, benchmark_instance, stream_id)

    @staticmethod
    def _query_category(query_id: str) -> str:
        normalized = str(query_id).strip().lower()
        if "_" in normalized:
            return normalized.split("_", 1)[0]
        if normalized.startswith("q") and normalized[1:].isdigit():
            return "q"
        return "other"

    def _count_query_categories(self, query_ids: set[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for query_id in query_ids:
            category = self._query_category(query_id)
            counts[category] = counts.get(category, 0) + 1
        return counts

"""
Core benchmark lifecycle runner (generate → optional validate → load → execute).

This module provides a reusable, CLI‑independent orchestration API that executes
benchmark lifecycles using core types and platform adapters. It is designed to be
used by both programmatic clients and the CLI wrapper.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from benchbox.core.benchmark_loader import (
    get_benchmark_instance,
)
from benchbox.core.constants import (
    GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS,
    GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS,
)
from benchbox.core.results.models import (
    BenchmarkResults,
)
from benchbox.core.runner.conversion import FormatConversionOrchestrator
from benchbox.core.schemas import (
    BenchmarkConfig,
    DatabaseConfig,
    ExecutionContext,
    RunConfig,
    SystemProfile,
)
from benchbox.core.validation import ValidationResult

try:
    from benchbox.monitoring import PerformanceMonitor, ResourceMonitor, attach_snapshot_to_result

    _MONITORING_AVAILABLE = True
except ImportError:
    _MONITORING_AVAILABLE = False
    PerformanceMonitor = None  # type: ignore[assignment,misc]
    ResourceMonitor = None  # type: ignore[assignment,misc]

    def attach_snapshot_to_result(*_args: Any, **_kwargs: Any) -> None:  # type: ignore[misc]
        pass


from benchbox.platforms import get_platform_adapter
from benchbox.platforms.dataframe.benchmark_mixin import DataFramePhases, DataFrameRunOptions
from benchbox.utils.cloud_storage import create_path_handler
from benchbox.utils.format_converters import ConversionOptions
from benchbox.utils.printing import emit
from benchbox.utils.verbosity import VerbosityMixin, VerbositySettings

logger = logging.getLogger(__name__)


_STATUS_PRIORITY = {
    "FAILED": 4,
    "WARNINGS": 3,
    "PASSED": 2,
    "NOT_RUN": 1,
    "UNKNOWN": 0,
}


def _resolve_manifest_allowed_names(benchmark: Any, config: BenchmarkConfig) -> set[str]:
    """Return acceptable benchmark identifiers for manifest validation."""

    allowed = {config.name.lower()}

    getter = getattr(benchmark, "get_data_source_benchmark", None)
    if callable(getter):
        try:
            alias = getter()
        except NotImplementedError:
            alias = None
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "data sharing alias resolution failed for %s: %s",
                getattr(benchmark, "__class__", type(benchmark)).__name__,
                exc,
            )
            alias = None

        if alias:
            if isinstance(alias, str):
                allowed.add(alias.lower())
            else:
                logger.warning(
                    "Unexpected alias type %s from %s; ignoring.",
                    type(alias),
                    getattr(benchmark, "__class__", type(benchmark)).__name__,
                )

    return allowed


def _resolve_output_dir_handler(benchmark: Any, output_root: str | None) -> Any | None:
    """Resolve and cache the benchmark output directory handler if available."""

    if output_root:
        handler = create_path_handler(output_root)
        benchmark.output_dir = handler
        return handler

    existing = getattr(benchmark, "output_dir", None)
    if existing is None:
        return None

    handler = create_path_handler(existing)
    benchmark.output_dir = handler
    return handler


def _run_preflight_validation(
    benchmark: Any, benchmark_config: BenchmarkConfig, output_dir_handler: Any
) -> ValidationResult:
    """Execute preflight validation using benchmark helpers or core engine."""

    benchmark_name = getattr(benchmark_config, "name", getattr(benchmark, "name", "")).lower()
    scale_factor = getattr(benchmark_config, "scale_factor", getattr(benchmark, "scale_factor", 1.0))

    if hasattr(benchmark, "validate_preflight"):
        return benchmark.validate_preflight(output_dir=output_dir_handler, benchmark_name=benchmark_name)

    from benchbox.core.validation import DataValidationEngine

    engine = DataValidationEngine()
    if output_dir_handler is None:
        raise RuntimeError("Output directory is required for preflight validation but was not provided.")
    return engine.validate_preflight_conditions(benchmark_name, scale_factor, output_dir_handler)


def _run_manifest_validation(benchmark: Any, benchmark_config: BenchmarkConfig) -> ValidationResult:
    """Validate the generated data manifest if present."""

    if hasattr(benchmark, "validate_manifest"):
        return benchmark.validate_manifest(benchmark_name=benchmark_config.name)

    from benchbox.core.validation import DataValidationEngine, ValidationResult

    output_dir = getattr(benchmark, "output_dir", None)
    if output_dir is None or not hasattr(output_dir, "joinpath"):
        return ValidationResult(
            is_valid=False,
            errors=["Benchmark output directory not configured; cannot validate manifest"],
            warnings=[],
            details={"benchmark": benchmark_config.name},
        )

    manifest_path = output_dir.joinpath("_datagen_manifest.json")
    engine = DataValidationEngine()
    return engine.validate_generated_data(manifest_path)


def _run_postload_validation(
    adapter: Any,
    benchmark_config: BenchmarkConfig,
    platform_config: dict[str, Any] | None,
) -> ValidationResult | None:
    """Execute post-load validation using the core database validation engine."""

    if adapter is None:
        return None

    from benchbox.core.validation import DatabaseValidationEngine, ValidationResult

    if not hasattr(adapter, "create_connection") or not hasattr(adapter, "close_connection"):
        return ValidationResult(
            is_valid=False,
            errors=["Platform adapter does not support connection-based validation"],
            warnings=[],
            details={"benchmark": benchmark_config.name},
        )

    connection = None
    try:
        connection = adapter.create_connection(**(platform_config or {}))
        engine = DatabaseValidationEngine()
        return engine.validate_loaded_data(connection, benchmark_config.name.lower(), benchmark_config.scale_factor)
    except Exception as exc:  # pragma: no cover - defensive safeguard
        return ValidationResult(
            is_valid=False,
            errors=[f"Post-load validation failed: {exc}"],
            warnings=[],
            details={"benchmark": benchmark_config.name},
        )
    finally:
        if connection is not None:
            try:
                adapter.close_connection(connection)
            except Exception:  # pragma: no cover - defensive safeguard
                pass


def _finalize_validation_metadata(
    result: BenchmarkResults, records: list[tuple[str, ValidationResult]]
) -> BenchmarkResults:
    """Merge collected validation records into the final result object."""

    if not records:
        current_status = (result.validation_status or "UNKNOWN").upper()
        if current_status in {"", "UNKNOWN", None}:
            result.validation_status = "NOT_RUN"
        result.validation_details = result.validation_details or {}
        result.validation_details.setdefault("stages", [])
        result.validation_details.setdefault("error_count", 0)
        result.validation_details.setdefault("warning_count", 0)
        return result

    stages = list((result.validation_details or {}).get("stages", []))
    error_count = int((result.validation_details or {}).get("error_count", 0))
    warning_count = int((result.validation_details or {}).get("warning_count", 0))

    aggregate_status = "PASSED"
    for stage_name, record in records:
        stage_status = "FAILED" if not record.is_valid else ("WARNINGS" if record.warnings else "PASSED")
        if stage_status == "FAILED":
            aggregate_status = "FAILED"
        elif stage_status == "WARNINGS" and aggregate_status != "FAILED":
            aggregate_status = "WARNINGS"

        stages.append(
            {
                "stage": stage_name,
                "status": stage_status,
                "errors": list(record.errors),
                "warnings": list(record.warnings),
                "details": record.details,
            }
        )
        error_count += len(record.errors)
        warning_count += len(record.warnings)

    result.validation_details = result.validation_details or {}
    result.validation_details.update(
        {
            "stages": stages,
            "error_count": error_count,
            "warning_count": warning_count,
        }
    )

    current_status = (result.validation_status or "UNKNOWN").upper()
    if _STATUS_PRIORITY.get(aggregate_status, 0) >= _STATUS_PRIORITY.get(current_status, 0):
        result.validation_status = aggregate_status
    else:
        result.validation_status = current_status

    return result


_DRIVER_STR_FIELDS = [
    "driver_package",
    "driver_version_requested",
    "driver_version_resolved",
    "driver_version_actual",
    "driver_runtime_strategy",
    "driver_runtime_path",
    "driver_runtime_python_executable",
]

# Config attribute names differ from local field names for a few fields.
_CONFIG_FIELD_MAP: dict[str, str] = {
    "driver_version_requested": "driver_version",
    "driver_auto_install_used": "driver_auto_install",
}

# execution_metadata fields that use setdefault (preserve existing); others overwrite.
_EXEC_META_SETDEFAULT = {"driver_package", "driver_version_requested", "driver_auto_install_used"}


def _apply_driver_meta_to_dicts(meta: dict[str, Any], result: BenchmarkResults) -> None:
    """Push resolved driver metadata into execution_metadata and platform_info dicts."""
    execution_metadata = result.execution_metadata if isinstance(result.execution_metadata, dict) else None
    if execution_metadata is not None:
        for field in _DRIVER_STR_FIELDS + ["driver_auto_install_used"]:
            value = meta[field]
            if value or field == "driver_auto_install_used":
                if field in _EXEC_META_SETDEFAULT:
                    execution_metadata.setdefault(field, value)
                else:
                    execution_metadata[field] = value

    platform_info = result.platform_info if isinstance(result.platform_info, dict) else None
    if platform_info is not None:
        for field in _DRIVER_STR_FIELDS:
            if meta[field]:
                platform_info.setdefault(field, meta[field])


def _enrich_driver_runtime_metadata(
    result: BenchmarkResults,
    *,
    adapter: Any | None,
    database_config: DatabaseConfig | None,
) -> BenchmarkResults:
    """Attach resolved driver runtime metadata to result objects.

    Lifecycle runs can return BenchmarkResults built through benchmark helpers
    that normalize ``platform_info`` and drop custom top-level fields. Persist
    driver metadata explicitly on result and execution metadata to keep exports
    consistent across all adapters.
    """
    meta: dict[str, Any] = dict.fromkeys(_DRIVER_STR_FIELDS)
    meta["driver_auto_install_used"] = False

    if adapter is not None:
        for field in _DRIVER_STR_FIELDS:
            meta[field] = getattr(adapter, field, None) or meta[field]
        meta["driver_auto_install_used"] = getattr(adapter, "driver_auto_install_used", False)

    if database_config is not None:
        for field in _DRIVER_STR_FIELDS:
            if not meta[field]:
                config_attr = _CONFIG_FIELD_MAP.get(field, field)
                meta[field] = getattr(database_config, config_attr, None)
        # driver_version_resolved also falls back to driver_version
        if not meta["driver_version_resolved"]:
            meta["driver_version_resolved"] = database_config.driver_version
        if not meta["driver_auto_install_used"]:
            meta["driver_auto_install_used"] = database_config.driver_auto_install

        resolved = meta["driver_version_resolved"]
        if resolved and database_config.driver_version_resolved != resolved:
            database_config.driver_version_resolved = resolved

    # Apply to result object
    for field in _DRIVER_STR_FIELDS:
        setattr(result, field, meta[field])
    result.driver_auto_install = meta["driver_auto_install_used"]

    # Apply to execution_metadata and platform_info dicts
    _apply_driver_meta_to_dicts(meta, result)

    return result


def _execute_load_only_mode(
    *,
    benchmark: Any,
    benchmark_config: BenchmarkConfig,
    adapter: Any,
    platform_config: dict[str, Any] | None,
    validation_opts: ValidationOptions,
    table_mode: str = "native",
) -> tuple[BenchmarkResults, ValidationResult | None]:
    """Execute load-only workflow using the core runner primitives."""

    connection = None
    table_stats: dict[str, int] = {}
    load_time = 0.0
    schema_time = 0.0
    postload_result: ValidationResult | None = None

    try:
        connection = adapter.create_connection(**(platform_config or {}))

        if table_mode == "external":
            if not getattr(adapter, "supports_external_tables", False):
                raise RuntimeError(
                    f"Platform '{getattr(adapter, 'platform_name', type(adapter).__name__)}' "
                    "does not support --table-mode external"
                )
            validate_external = getattr(adapter, "validate_external_table_requirements", None)
            if callable(validate_external):
                validate_external()

        data_dir = getattr(benchmark, "output_dir", None)
        if data_dir is None:
            data_dir = _resolve_output_dir_handler(benchmark, None)
        if data_dir is None:
            raise RuntimeError("Benchmark output directory not configured; cannot perform load-only operations")

        if table_mode == "external":
            table_stats, load_time, per_table_timings = adapter.create_external_tables(benchmark, connection, data_dir)
            schema_phase = {
                "status": "SKIPPED",
                "duration_ms": 0,
                "reason": "External table mode bypasses native schema+load materialization",
            }
        else:
            # Create schema before loading data in native table mode.
            schema_time = adapter.create_schema(benchmark, connection)
            table_stats, load_time, per_table_timings = adapter.load_data(benchmark, connection, data_dir)
            schema_phase = {
                "status": "COMPLETED",
                "duration_ms": int(schema_time * 1000),
            }

        if validation_opts.enable_postload_validation:
            if hasattr(benchmark, "validate_loaded_data"):
                postload_result = benchmark.validate_loaded_data(connection, benchmark_name=benchmark_config.name)
            else:
                from benchbox.core.validation import DatabaseValidationEngine

                engine = DatabaseValidationEngine()
                postload_result = engine.validate_loaded_data(
                    connection,
                    benchmark_config.name.lower(),
                    benchmark_config.scale_factor,
                )

        phases = {
            "data_generation": {"status": "COMPLETED"},
            "schema_creation": schema_phase,
            "data_loading": {
                "status": "COMPLETED",
                "duration_ms": int(load_time * 1000),
            },
        }

        # Calculate total rows and data size
        total_rows = sum(table_stats.values()) if table_stats else 0
        # Try to calculate data size from benchmark output_dir if available
        data_size_mb = 0.0
        if hasattr(benchmark, "output_dir") and hasattr(adapter, "_calculate_data_size"):
            try:
                data_size_mb = adapter._calculate_data_size(benchmark.output_dir)
            except Exception:
                data_size_mb = 0.0

        result_obj = benchmark.create_enhanced_benchmark_result(
            platform=getattr(adapter, "platform_name", "load_only"),
            query_results=[],
            duration_seconds=schema_time + load_time,
            phases=phases,
            execution_metadata={"mode": "load_only"},
            schema_creation_time=schema_time,
            data_loading_time=load_time,
            table_statistics=table_stats,
            per_table_timings=per_table_timings,
            total_rows_loaded=total_rows,
            data_size_mb=data_size_mb,
        )
        return result_obj, postload_result
    finally:
        if connection is not None:
            adapter.close_connection(connection)


def _get_table_schemas_from_benchmark(benchmark: Any) -> dict[str, dict[str, Any]]:
    """Extract table schemas from benchmark instance.

    Args:
        benchmark: Benchmark instance with get_schema() method

    Returns:
        Dictionary mapping table_name → schema dict with {"name": ..., "columns": [...]}

    Raises:
        RuntimeError: If schema cannot be extracted
    """
    if not hasattr(benchmark, "get_schema"):
        raise RuntimeError(f"Benchmark {type(benchmark).__name__} does not provide get_schema() method")

    try:
        schema = benchmark.get_schema()
    except Exception as e:
        raise RuntimeError(f"Failed to get schema from benchmark: {e}") from e

    # Handle both dict and list return formats
    if isinstance(schema, dict):
        # Already in expected format: {table_name: {name, columns}}
        return schema
    elif isinstance(schema, list):
        # Convert list format to dict: [{name, columns}, ...] → {name: {name, columns}}
        return {table["name"].lower(): table for table in schema}
    else:
        raise RuntimeError(f"Unexpected schema format: {type(schema)}")


def _run_format_conversion(
    benchmark: Any,
    benchmark_config: BenchmarkConfig,
) -> dict[str, Any] | None:
    """Run format conversion after data generation.

    Args:
        benchmark: Benchmark instance with output_dir and get_schema()
        benchmark_config: Benchmark configuration with conversion settings in options

    Returns:
        Dictionary of conversion results by table name, or None if no conversion
    """
    # Extract conversion settings from benchmark_config.options
    options_dict = getattr(benchmark_config, "options", {}) or {}
    table_format = options_dict.get("table_format")

    # Check if conversion is requested
    if not table_format:
        return None

    # Validate format
    allowed_formats = {"parquet", "vortex", "delta", "iceberg"}
    if table_format.lower() not in allowed_formats:
        logger.error(f"Invalid format: {table_format}. Allowed: {allowed_formats}")
        return None

    output_dir = getattr(benchmark, "output_dir", None)
    if output_dir is None:
        logger.warning("Cannot convert format: benchmark output_dir not configured")
        return None

    manifest_path = output_dir / "_datagen_manifest.json"
    if not manifest_path.exists():
        logger.warning(f"Cannot convert format: manifest not found at {manifest_path}")
        return None

    # Get table schemas from benchmark
    try:
        schemas = _get_table_schemas_from_benchmark(benchmark)
    except RuntimeError as e:
        logger.error(f"Format conversion failed: {e}")
        return None

    # Build conversion options from benchmark_config.options
    tf_compression = options_dict.get("table_format_compression", "snappy")
    tf_partition_cols = options_dict.get("table_format_partition_cols", [])

    options = ConversionOptions(
        compression=tf_compression,
        partition_cols=tf_partition_cols or [],
        merge_shards=True,
        validate_row_count=True,
    )

    # When targeting Vortex in external table mode, require the DuckDB extension writer
    # so that generated files are compatible with DuckDB's read_vortex().
    table_mode = options_dict.get("table_mode", "native")
    if table_format == "vortex" and str(table_mode).lower() == "external":
        options.metadata["require_duckdb_writer"] = True

    # Run conversion orchestration
    orchestrator = FormatConversionOrchestrator()
    logger.info(f"Converting benchmark data to {table_format} format (compression: {options.compression})")

    try:
        results = orchestrator.convert_benchmark_tables(
            manifest_path=manifest_path,
            output_dir=output_dir,
            target_format=table_format,
            schemas=schemas,
            options=options,
        )
        logger.info(f"✓ Format conversion complete: {len(results)} tables converted")
        return results
    except Exception as e:
        logger.error(f"Format conversion failed: {e}")
        raise RuntimeError(f"Format conversion to {table_format} failed") from e


@dataclass
class LifecyclePhases:
    generate: bool = True
    load: bool = True
    execute: bool = True


@dataclass
class ValidationOptions:
    enable_preflight_validation: bool = False
    enable_postgen_manifest_validation: bool = False
    enable_postload_validation: bool = False


def run_benchmark_lifecycle(
    benchmark_config: BenchmarkConfig,
    database_config: DatabaseConfig | None,
    system_profile: SystemProfile | None,
    *,
    platform_config: dict[str, Any] | None = None,
    platform_adapter: Any | None = None,
    phases: LifecyclePhases | None = None,
    validation_opts: ValidationOptions | None = None,
    output_root: str | None = None,
    benchmark_instance: Any | None = None,
    verbosity: VerbositySettings | None = None,
    monitor: PerformanceMonitor | None = None,
    enable_resource_monitoring: bool = True,
    execution_context: ExecutionContext | None = None,
) -> BenchmarkResults:
    """Run the complete benchmark lifecycle in core, returning BenchmarkResults.

    Args:
        benchmark_config: Core benchmark configuration
        database_config: Database configuration (None for data_only)
        system_profile: System profile used for benchmark instantiation
        platform_config: Platform adapter configuration (connection params, etc.)
        phases: Which lifecycle phases to execute
        validation_opts: Validation flags for pre/post generation and postload
        output_root: Optional output directory/URI for data generation
        benchmark_instance: Optional pre-constructed benchmark instance to use
        monitor: Optional PerformanceMonitor to track metrics. If None and monitoring
            not explicitly disabled, a default monitor will be created.
        enable_resource_monitoring: Whether to track CPU/memory during execution (default: True)

    Returns:
        BenchmarkResults representing the full execution with performance metrics attached
    """
    phases = phases or LifecyclePhases()
    validation_opts = validation_opts or ValidationOptions()

    # Create default monitor if not provided (deep integration - automatic monitoring)
    if monitor is None and _MONITORING_AVAILABLE:
        monitor = PerformanceMonitor()  # type: ignore[misc]

    # Start resource monitoring if enabled
    resource_monitor: ResourceMonitor | None = None
    if enable_resource_monitoring and monitor is not None:
        resource_monitor = ResourceMonitor(monitor, sample_interval=2.0)
        resource_monitor.start()

    # Record benchmark metadata in monitor
    if monitor is not None:
        monitor.set_metadata("benchmark", benchmark_config.name)
        monitor.set_metadata("scale_factor", getattr(benchmark_config, "scale_factor", 1.0))
        monitor.set_metadata("platform", database_config.type if database_config else "data_only")

    options_map = getattr(benchmark_config, "options", {}) or {}
    if verbosity is not None:
        verbosity_settings = verbosity
    else:
        stored_settings = options_map.get("verbosity_settings") if isinstance(options_map, Mapping) else None
        if isinstance(stored_settings, VerbositySettings):
            verbosity_settings = stored_settings
        elif isinstance(stored_settings, Mapping):
            verbosity_settings = VerbositySettings.from_mapping(stored_settings)
        else:
            verbosity_settings = VerbositySettings.from_mapping(options_map)

    benchmark = benchmark_instance or get_benchmark_instance(benchmark_config, system_profile)
    if isinstance(benchmark, VerbosityMixin):  # type: ignore[arg-type]
        benchmark.apply_verbosity(verbosity_settings)

    output_dir_handler = _resolve_output_dir_handler(benchmark, output_root)
    validation_records: list[tuple[str, ValidationResult]] = []

    # Determine test type and whether data generation / loading is needed
    test_type = getattr(benchmark_config, "test_execution_type", "standard")
    needs_data = test_type != "data_only"

    # Ensure data exists: always when phases.generate is requested (including data_only),
    # or when a downstream phase (load/execute) needs it.
    datagen_duration = 0.0
    if needs_data or phases.generate:
        datagen_start = time.monotonic()

        # Only run preflight validation when explicitly generating fresh data
        if phases.generate and validation_opts.enable_preflight_validation:
            preflight_result = _run_preflight_validation(benchmark, benchmark_config, output_dir_handler)
            validation_records.append(("preflight", preflight_result))
            if not preflight_result.is_valid:
                error_msg = ", ".join(preflight_result.errors) or "Unknown preflight validation error"
                raise RuntimeError(f"Preflight validation failed: {error_msg}")

        # Always ensure data exists (will reuse manifest if valid, or generate if needed)
        if monitor is not None:
            with monitor.time_operation("data_generation"):
                data_was_generated = _ensure_data_generated(benchmark, benchmark_config)
                if data_was_generated:
                    monitor.increment_counter("tables_generated", len(getattr(benchmark, "tables", []) or []))
        else:
            _ensure_data_generated(benchmark, benchmark_config)

        if validation_opts.enable_postgen_manifest_validation:
            manifest_result = _run_manifest_validation(benchmark, benchmark_config)
            validation_records.append(("post_generation_manifest", manifest_result))

        # Run format conversion if requested (only when data generation phase is enabled)
        if phases.generate:
            _run_format_conversion(benchmark, benchmark_config)

        datagen_duration = time.monotonic() - datagen_start

    if test_type == "data_only":
        execution_id = uuid.uuid4().hex[:8]
        datagen_phase = {
            "status": "COMPLETED",
            "duration_ms": int(datagen_duration * 1000),
        }
        datagen_phase.update(_read_datagen_stats_from_manifest(benchmark))
        result_obj = benchmark.create_enhanced_benchmark_result(
            platform="data_only",
            query_results=[],
            duration_seconds=datagen_duration,
            phases={"data_generation": datagen_phase},
            execution_metadata={
                "mode": "datagen",
                "benchmark_id": benchmark_config.name,
            },
            execution_id=execution_id,
        )
        result_obj._benchmark_id_override = benchmark_config.name
        result_obj = _finalize_validation_metadata(result_obj, validation_records)
        result_obj = _enrich_driver_runtime_metadata(result_obj, adapter=None, database_config=database_config)
        if execution_context is not None:
            result_obj.execution_context = execution_context.model_dump()
        return result_obj

    adapter = platform_adapter
    if adapter is None and database_config is not None:
        adapter = get_platform_adapter(database_config.type, **(platform_config or {}))

    # Set benchmark instance on adapter for database validation
    # This allows the adapter to validate schema compatibility when checking
    # if an existing database can be reused
    if adapter is not None and benchmark:
        adapter.benchmark_instance = benchmark
        adapter.scale_factor = benchmark_config.scale_factor

    if adapter is not None and validation_opts.enable_postload_validation and hasattr(adapter, "enable_validation"):
        adapter.enable_validation = True

    if adapter is not None and isinstance(adapter, VerbosityMixin):
        adapter.apply_verbosity(verbosity_settings)

    options = getattr(benchmark_config, "options", {}) or {}
    table_mode = str(options.get("table_mode", "native") or "native").lower()

    # Propagate table_mode to adapter so run_enhanced_benchmark can route
    # to create_external_tables instead of create_schema + load_data.
    if adapter is not None and hasattr(adapter, "table_mode"):
        adapter.table_mode = table_mode

    # Detect DataFrame adapter by checking for 'family' attribute
    is_dataframe_adapter = hasattr(adapter, "family") and adapter.family in ("expression", "pandas")

    # Check if we should run load-only mode:
    # - Explicit test_type == "load_only" OR
    # - Phases indicate load without execute (e.g., --phases generate,load)
    should_run_load_only = test_type == "load_only" or (phases.load and not phases.execute and adapter is not None)

    if should_run_load_only:
        if adapter is None:
            raise RuntimeError("Load-only mode requires a platform adapter and database configuration")

        if is_dataframe_adapter:
            from pathlib import Path

            data_dir = getattr(benchmark, "output_dir", None)
            if data_dir is None and output_root:
                data_dir = Path(output_root)
            elif isinstance(data_dir, str):
                data_dir = Path(data_dir)

            df_phases = DataFramePhases(load=True, execute=False)
            df_options = DataFrameRunOptions(
                ignore_memory_warnings=bool(options.get("ignore_memory_warnings", False)),
                force_regenerate=bool(options.get("force_regenerate", False)),
                prefer_parquet=bool(options.get("prefer_parquet", True)),
                cache_dir=options.get("cache_dir"),
                verbose=verbosity_settings.verbose,
                very_verbose=verbosity_settings.very_verbose,
            )

            result_obj = adapter.run_benchmark(
                benchmark,
                benchmark_config=benchmark_config,
                system_profile=system_profile,
                data_dir=data_dir,
                phases=df_phases,
                options=df_options,
                monitor=monitor,
            )
        else:
            result_obj, postload_result = _execute_load_only_mode(
                benchmark=benchmark,
                benchmark_config=benchmark_config,
                adapter=adapter,
                platform_config=platform_config,
                validation_opts=validation_opts,
                table_mode=table_mode,
            )

            if postload_result is not None:
                validation_records.append(("post_load", postload_result))

        result_obj = _finalize_validation_metadata(result_obj, validation_records)
        result_obj = _enrich_driver_runtime_metadata(result_obj, adapter=adapter, database_config=database_config)
        if execution_context is not None:
            result_obj.execution_context = execution_context.model_dump()
        return result_obj

    # Only return early for setup-only scenarios (no loading, no execution)
    # This prevents skipping schema creation when phases.load=True
    if adapter is None or (not phases.execute and not phases.load):
        # If execute phase is requested but adapter is missing, this is a configuration error
        if phases.execute and adapter is None:
            raise RuntimeError(
                "Cannot execute benchmark: platform adapter not initialized. "
                "This indicates database configuration is missing or adapter creation failed. "
                "Ensure --platform parameter is provided when using execution phases (power/throughput/maintenance)."
            )

        result_obj = benchmark.create_enhanced_benchmark_result(
            platform=(adapter.platform_name if adapter else "unknown"),
            query_results=[],
            duration_seconds=0.0,
            phases={"setup": {"status": "COMPLETED"}},
            execution_metadata={"mode": "setup_only"},
        )
        result_obj = _finalize_validation_metadata(result_obj, validation_records)
        result_obj = _enrich_driver_runtime_metadata(result_obj, adapter=adapter, database_config=database_config)
        if execution_context is not None:
            result_obj.execution_context = execution_context.model_dump()
        return result_obj

    iterations = int(
        options.get("power_iterations", GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS)
        or GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS
    )
    warmups = int(
        options.get("power_warmup_iterations", GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS)
        or GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS
    )
    fail_fast = bool(options.get("power_fail_fast", False))
    table_format_raw = options.get("table_format")
    table_format = None
    if isinstance(table_format_raw, str) and table_format_raw.strip():
        table_format = table_format_raw.strip().lower()

    # Fail fast: ensure the platform supports the requested table format
    if table_format:
        from benchbox.platforms.base.format_capabilities import get_supported_formats

        platform_name = getattr(adapter, "platform_name", "unknown")
        supported = get_supported_formats(
            platform_name,
            table_mode=table_mode,
            platform_config=getattr(adapter, "__dict__", None),
        )
        if table_format not in supported:
            raise RuntimeError(
                f"Platform '{platform_name}' does not support table format '{table_format}'. "
                f"Supported formats: {supported}"
            )

    table_format_compression_raw = options.get("table_format_compression", "snappy")
    table_format_compression = str(table_format_compression_raw or "snappy")

    table_format_partition_cols_raw = options.get("table_format_partition_cols")
    table_format_partition_cols: list[str] = []
    if isinstance(table_format_partition_cols_raw, str):
        table_format_partition_cols = [
            part.strip() for part in table_format_partition_cols_raw.split(",") if part.strip()
        ]
    elif isinstance(table_format_partition_cols_raw, (list, tuple)):
        table_format_partition_cols = [
            str(part).strip() for part in table_format_partition_cols_raw if str(part).strip()
        ]

    run_config = RunConfig(
        query_subset=benchmark_config.queries,
        concurrent_streams=benchmark_config.concurrency,
        test_execution_type=test_type,
        scale_factor=benchmark_config.scale_factor,
        seed=(int(options.get("seed")) if options.get("seed") is not None else None),
        connection={
            "database_path": (platform_config or {}).get("database_path"),
        },
        enable_postload_validation=validation_opts.enable_postload_validation,
        verbose=verbosity_settings.verbose,
        verbose_level=verbosity_settings.level,
        verbose_enabled=verbosity_settings.verbose_enabled,
        very_verbose=verbosity_settings.very_verbose,
        quiet=verbosity_settings.quiet,
        iterations=max(1, iterations),
        warm_up_iterations=max(0, warmups),
        power_fail_fast=fail_fast,
        capture_plans=benchmark_config.capture_plans,
        strict_plan_capture=benchmark_config.strict_plan_capture,
        table_format=table_format,
        table_format_compression=table_format_compression,
        table_format_partition_cols=table_format_partition_cols,
    )

    if is_dataframe_adapter:
        # DataFrame adapter execution path
        from pathlib import Path

        # Get data directory from benchmark or output_root
        data_dir = getattr(benchmark, "output_dir", None)
        if data_dir is None and output_root:
            data_dir = Path(output_root)
        elif isinstance(data_dir, str):
            data_dir = Path(data_dir)

        # Create DataFrame-specific phases and options
        df_phases = DataFramePhases(
            load=True,  # DataFrame always loads from files
            execute=phases.execute,
        )
        df_options = DataFrameRunOptions(
            ignore_memory_warnings=bool(options.get("ignore_memory_warnings", False)),
            force_regenerate=bool(options.get("force_regenerate", False)),
            prefer_parquet=bool(options.get("prefer_parquet", True)),
            cache_dir=options.get("cache_dir"),
            verbose=verbosity_settings.verbose,
            very_verbose=verbosity_settings.very_verbose,
        )

        # Call DataFrame adapter's run_benchmark
        result_obj = adapter.run_benchmark(
            benchmark,
            benchmark_config=benchmark_config,
            system_profile=system_profile,
            data_dir=data_dir,
            phases=df_phases,
            options=df_options,
            monitor=monitor,
        )
    else:
        # SQL adapter execution path (existing behavior)
        kwargs = {k: v for k, v in run_config.__dict__.items() if k != "benchmark"}
        result_obj = adapter.run_benchmark(benchmark, **kwargs)

    # Postload validation only applies to SQL adapters (database validation)
    if validation_opts.enable_postload_validation and not is_dataframe_adapter:
        postload_result = _run_postload_validation(adapter, benchmark_config, platform_config)
        if postload_result is not None:
            validation_records.append(("post_load", postload_result))

    # Stop resource monitoring and attach performance snapshot to results
    if resource_monitor is not None:
        resource_monitor.stop()

    result_with_validation = _finalize_validation_metadata(result_obj, validation_records)
    result_with_validation = _enrich_driver_runtime_metadata(
        result_with_validation,
        adapter=adapter,
        database_config=database_config,
    )

    # Attach performance monitoring snapshot to result
    if monitor is not None:
        snapshot = monitor.snapshot()
        attach_snapshot_to_result(result_with_validation, snapshot)

    # Attach execution context for reproducibility
    if execution_context is not None:
        result_with_validation.execution_context = execution_context.model_dump()

    return result_with_validation


def _flatten_manifest_v2_entries(table_formats: Any, preferred_formats: list[str] | None = None) -> list[Any]:
    """Select one v2 table format and return its file entries.

    Manifests may contain multiple materializations per table (for example
    `tbl` and `parquet`). For aggregate stats we should count one canonical
    representation per table, not sum across all formats.
    """

    formats = getattr(table_formats, "formats", {}) or {}
    if not isinstance(formats, dict) or not formats:
        return []

    format_order: list[str] = []
    if preferred_formats:
        format_order.extend(preferred_formats)
    format_order.extend(["tbl", "csv", "parquet"])
    format_order.extend(sorted(formats.keys()))

    seen: set[str] = set()
    for format_name in format_order:
        if format_name in seen:
            continue
        seen.add(format_name)
        files = formats.get(format_name)
        if isinstance(files, list) and files:
            return files

    return []


def _read_datagen_stats_from_manifest(benchmark: Any) -> dict[str, int]:
    """Read aggregate datagen stats from manifest when available.

    Returns non-critical stats used for data-only phase reporting. Any
    parse/load failure returns an empty dict by design.
    """

    try:
        output_dir = getattr(benchmark, "output_dir", None)
        if output_dir is None or not hasattr(output_dir, "joinpath"):
            return {}

        manifest_path = output_dir.joinpath("_datagen_manifest.json")
        if not manifest_path.exists():
            return {}

        from benchbox.core.manifest.io import load_manifest

        manifest = load_manifest(manifest_path)
        tables = getattr(manifest, "tables", {}) or {}
        if not isinstance(tables, dict) or not tables:
            return {}
        preferred_formats = list(getattr(manifest, "format_preference", []) or [])

        tables_generated = 0
        total_rows = 0
        total_size_bytes = 0

        for table_data in tables.values():
            if isinstance(table_data, list):
                entries = table_data
            else:
                entries = _flatten_manifest_v2_entries(table_data, preferred_formats)

            if not entries:
                continue

            tables_generated += 1
            for entry in entries:
                total_rows += int(getattr(entry, "row_count", 0) or 0)
                total_size_bytes += int(getattr(entry, "size_bytes", 0) or 0)

        if tables_generated == 0:
            return {}

        return {
            "tables_generated": tables_generated,
            "total_rows": total_rows,
            "total_size_bytes": total_size_bytes,
        }
    except Exception:
        logger.debug("Failed to read datagen stats from manifest", exc_info=True)
        return {}


def _ensure_data_generated(benchmark: Any, config: BenchmarkConfig) -> bool:
    """Ensure data is generated, respecting manifest and generator validator.

    Implements the idempotent behavior: reuse valid existing data when possible,
    unless force_regenerate is requested; optionally fail when no_regenerate is set
    and data is missing/invalid.

    Returns:
        True if data was freshly generated, False if reused from existing manifest
    """
    options = getattr(config, "options", {}) or {}
    force_regenerate_flag = bool(options.get("force_regenerate"))
    no_regenerate_flag = bool(options.get("no_regenerate"))

    # If tables already present, assume generation done (unless force requested)
    if getattr(benchmark, "tables", None) and not force_regenerate_flag:
        return False

    output_dir = getattr(benchmark, "output_dir", None)
    manifest_valid = False
    manifest_found = False
    manifest_data: dict | None = None

    if output_dir and not force_regenerate_flag:
        manifest_valid, manifest_data, manifest_found = _validate_manifest_if_present(benchmark, config)
        if manifest_valid:
            summary = _populate_tables_from_manifest(benchmark, manifest_data)
            if summary:
                _emit_manifest_reuse_message(benchmark, summary)

            # Allow benchmarks to ensure auxiliary files exist even when reusing data
            # This is needed for benchmarks that generate additional test files beyond the main data
            ensure_auxiliary = getattr(benchmark, "ensure_auxiliary_data_files", None)
            if callable(ensure_auxiliary):
                try:
                    ensure_auxiliary()
                except (OSError, PermissionError) as e:
                    # Critical system errors - re-raise (disk full, permissions, I/O failure)
                    raise RuntimeError(
                        f"Failed to generate auxiliary data files due to system error: {e}. "
                        "Check disk space, permissions, and file system health."
                    ) from e
                except ImportError as e:
                    # Missing optional dependency - log warning and continue
                    logger = logging.getLogger("benchbox.core.runner")
                    logger.warning(
                        f"Failed to generate auxiliary data files due to missing dependency: {e}. "
                        "Some benchmark operations may not be available."
                    )
                except Exception as e:
                    # Other errors - log warning but continue (auxiliary files may not be critical)
                    logger = logging.getLogger("benchbox.core.runner")
                    logger.warning(
                        f"Failed to generate auxiliary data files: {type(e).__name__}: {e}. "
                        "Some benchmark operations may fail."
                    )

            return False

    if no_regenerate_flag and not force_regenerate_flag:
        reason = "manifest is invalid or stale" if manifest_found else "manifest is missing"
        raise RuntimeError(f"no_regenerate is set but {reason}")

    # If manifest existed but failed validation, warn before regenerating
    if manifest_found and not manifest_valid:
        emit("⚠️ Manifest validation failed; regenerating benchmark data")

    # Perform generation (force_regenerate_flag is respected by skipping reuse)
    emit("Generating benchmark data...")
    _gen_start = time.monotonic()
    benchmark.generate_data()
    emit(f"✅ Data generation completed in {time.monotonic() - _gen_start:.2f}s")
    return True


def _populate_tables_from_manifest(benchmark: Any, manifest: dict | None = None) -> dict[str, Any] | None:
    """Populate benchmark.tables from _datagen_manifest.json when available.

    Returns a summary dictionary with table_count, file_count, created_at when manifest
    data is loaded successfully. Returns None when manifest is missing or invalid.
    """
    try:
        from benchbox.utils.datagen_manifest import get_table_files

        output_dir = getattr(benchmark, "output_dir", None)
        if not output_dir:
            return None
        manifest_data = _load_manifest_data(output_dir, manifest)
        if manifest_data is None:
            return None
        tbl_map: dict[str, Any] = {}
        total_files = 0
        for table in (manifest_data.get("tables") or {}).keys():
            entries = get_table_files(manifest_data, table)
            if not entries:
                continue
            total_files += len(entries)
            paths = _resolve_manifest_entry_paths(output_dir, table, entries)
            if not paths:
                continue
            tbl_map[table] = paths if len(paths) > 1 else paths[0]
        if tbl_map:
            benchmark.tables = tbl_map
        return {
            "table_count": len(tbl_map),
            "file_count": total_files,
            "created_at": manifest_data.get("created_at"),
        }
    except Exception:
        # Non-fatal; leave tables as-is
        return None


def _load_manifest_data(output_dir: Any, manifest: dict | None) -> dict | None:
    """Load manifest data from disk unless it was supplied directly."""
    if manifest is not None:
        return manifest
    manifest_path = output_dir.joinpath("_datagen_manifest.json")
    if not hasattr(manifest_path, "exists") or not manifest_path.exists():
        return None
    with manifest_path.open("r") as handle:
        return json.load(handle)


def _resolve_manifest_entry_paths(output_dir: Any, table: str, entries: list[dict[str, Any]]) -> list[Any]:
    """Resolve manifest file entries to absolute paths with directory guards."""
    from pathlib import Path

    paths = []
    for entry in entries:
        rel_path = entry.get("path")
        if not rel_path:
            continue
        full_path = output_dir.joinpath(rel_path)
        if isinstance(full_path, Path) and full_path.is_dir() and not entry.get("is_directory", False):
            logger.warning(
                "Manifest entry for table '%s' path '%s' is a directory but not marked as is_directory.",
                table,
                rel_path,
            )
        paths.append(full_path)
    return paths


def _emit_manifest_reuse_message(benchmark: Any, summary: dict[str, Any]) -> None:
    """Emit a concise console/log message when data reuse is triggered."""

    created_at = summary.get("created_at")
    table_count = summary.get("table_count", 0)
    file_count = summary.get("file_count", 0)
    timestamp = f"created {created_at}" if created_at else "existing manifest"
    table_label = "table" if table_count == 1 else "tables"
    file_label = "file" if file_count == 1 else "files"
    emit(f"🔄 Reusing benchmark data ({timestamp}; {table_count} {table_label}, {file_count} {file_label})")


def _validate_manifest_if_present(benchmark: Any, config: BenchmarkConfig) -> tuple[bool, dict | None, bool]:
    """Validate manifest structure and referenced files.

    Returns (valid, manifest_dict or None). Non-fatal; failures are signaled by return value.
    """
    try:
        output_dir = getattr(benchmark, "output_dir", None)
        if not output_dir:
            return False, None, False
        manifest_path = output_dir.joinpath("_datagen_manifest.json")
        manifest_found = bool(hasattr(manifest_path, "exists") and manifest_path.exists())
        if not manifest_found:
            return False, None, False
        with manifest_path.open("r") as f:
            manifest = json.load(f)

        manifest_benchmark = str(manifest.get("benchmark", "")).lower()
        allowed_names = _resolve_manifest_allowed_names(benchmark, config)
        if manifest_benchmark not in allowed_names:
            return False, None, True

        if float(manifest.get("scale_factor", -1)) != float(config.scale_factor):
            return False, None, True

        # Validate manifest entries using V2-aware helper
        from pathlib import Path

        from benchbox.utils.datagen_manifest import compute_entry_size, get_table_files

        tables = manifest.get("tables", {}) or {}
        for table_name in tables.keys():
            entries = get_table_files(manifest, table_name)
            for entry in entries:
                rel = entry.get("path")
                size = int(entry.get("size_bytes", -1))
                if rel is None or size < 0:
                    return False, None, True
                fp = output_dir.joinpath(rel)
                if not hasattr(fp, "exists") or not fp.exists():
                    return False, None, True
                # Entry type guard: file-format entry resolving to a directory
                # (without is_directory flag) indicates corrupted/contaminated state
                if isinstance(fp, Path) and fp.is_dir() and not entry.get("is_directory", False):
                    logger.warning(
                        "Manifest entry for table '%s' path '%s' is a directory "
                        "but not marked as is_directory. Manifest invalid.",
                        table_name,
                        rel,
                    )
                    return False, None, True
                # Use compute_entry_size for directory-aware size comparison
                # (directories like Delta/Iceberg need recursive file sum)
                if isinstance(fp, Path) and compute_entry_size(fp) != size:
                    return False, None, True
                # Cloud paths: fall back to stat() (directories not expected)
                if not isinstance(fp, Path):
                    if hasattr(fp, "is_dir") and fp.is_dir():
                        logger.warning("Cloud path %s is a directory; size check may be inaccurate", rel)
                    if not hasattr(fp, "stat") or fp.stat().st_size != size:
                        return False, None, True
        # Check for table-name directory collisions (e.g., stale Iceberg output).
        # Only check local paths — cloud paths don't have this problem.
        if isinstance(output_dir, Path):
            for table_name in tables.keys():
                table_dir = output_dir / table_name
                if table_dir.is_dir():
                    # Check ALL entries across all formats, not just the preferred format.
                    # get_table_files() only returns the default format's entries, but a
                    # directory might be tracked in a non-default format (e.g., delta).
                    # V1 manifests: table_data is a list (no directory entries possible),
                    # so all_entries stays empty and is_tracked is False — correct.
                    table_data = tables[table_name]
                    all_entries: list[dict] = []
                    if isinstance(table_data, dict):
                        formats_dict = table_data.get("formats", {})
                        if isinstance(formats_dict, dict):
                            for fmt_entries in formats_dict.values():
                                if isinstance(fmt_entries, list):
                                    all_entries.extend(fmt_entries)
                    is_tracked = any(e.get("path") == table_name for e in all_entries)
                    if not is_tracked:
                        logger.warning(
                            "Datagen cache rejected: directory '%s/' collides with table "
                            "name but is not recorded in manifest. Regenerating.",
                            table_name,
                        )
                        return False, None, True

        return True, manifest, True
    except Exception:
        return False, None, bool(locals().get("manifest_found", False))

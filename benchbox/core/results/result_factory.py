"""Shared benchmark-result construction helpers for benchmark base classes."""

from __future__ import annotations

from typing import Any, Optional

from benchbox.core.results.builder import (
    BenchmarkInfoInput,
    ResultBuilder,
    RunConfigInput,
    normalize_benchmark_id,
)
from benchbox.core.results.models import ExecutionPhases
from benchbox.core.results.platform_info import PlatformInfoInput
from benchbox.core.results.query_normalizer import normalize_query_result


def _build_platform_input(
    platform: str, execution_metadata: dict[str, Any], kwargs: dict[str, Any]
) -> PlatformInfoInput:
    """Build the normalized platform info input for the result builder."""
    platform_info = kwargs.get("platform_info", {}) or {}
    return PlatformInfoInput(
        name=platform,
        platform_version=platform_info.get("platform_version") or platform_info.get("version") or "unknown",
        client_library_version=platform_info.get("client_library_version")
        or platform_info.get("client_version")
        or "unknown",
        execution_mode=execution_metadata.get("mode", "sql"),
        config=platform_info if isinstance(platform_info, dict) else {},
    )


def _apply_run_config(builder: ResultBuilder, execution_metadata: dict[str, Any]) -> None:
    """Populate builder run-config fields from execution metadata when present."""
    run_cfg = execution_metadata.get("run_config") if isinstance(execution_metadata, dict) else None
    if not isinstance(run_cfg, dict):
        return

    compression = run_cfg.get("compression") or {}
    builder.set_run_config(
        RunConfigInput(
            compression_type=compression.get("type"),
            compression_level=compression.get("level"),
            seed=run_cfg.get("seed"),
            phases=run_cfg.get("phases"),
            query_subset=run_cfg.get("query_subset"),
            tuning_mode=run_cfg.get("tuning_mode"),
            tuning_config=run_cfg.get("tuning_config"),
            platform_options=run_cfg.get("platform_options"),
            table_mode=run_cfg.get("table_mode"),
            external_format=run_cfg.get("external_format"),
            table_format=run_cfg.get("table_format"),
            table_format_compression=run_cfg.get("table_format_compression"),
            table_format_partition_cols=run_cfg.get("table_format_partition_cols"),
        )
    )


def _add_table_statistics(builder: ResultBuilder, kwargs: dict[str, Any]) -> None:
    """Attach per-table row counts and load timings to the builder."""
    table_statistics = kwargs.get("table_statistics", {}) or {}
    per_table_timings: dict[str, Any] = kwargs.get("per_table_timings") or {}
    for table_name, row_count in table_statistics.items():
        timing = per_table_timings.get(table_name, {})
        load_time_ms = int(timing.get("total_ms", 0)) if isinstance(timing, dict) else 0
        builder.add_table_stats(table_name, row_count, load_time_ms=load_time_ms)


def _apply_phase_data(
    builder: ResultBuilder,
    phases: dict[str, dict[str, Any]] | ExecutionPhases | None,
) -> None:
    """Attach phase execution details to the builder."""
    phases_obj = phases if isinstance(phases, ExecutionPhases) else None
    if phases_obj:
        builder.set_execution_phases(phases_obj)
    if not isinstance(phases, dict):
        return

    for phase_name, phase_data in phases.items():
        if not isinstance(phase_data, dict):
            continue
        extra = {key: value for key, value in phase_data.items() if key not in ("status", "duration_ms")}
        builder.set_phase_status(
            phase_name,
            phase_data.get("status", "NOT_RUN"),
            phase_data.get("duration_ms"),
            **extra,
        )


def _apply_optional_builder_data(
    builder: ResultBuilder,
    execution_metadata: dict[str, Any],
    phases: dict[str, dict[str, Any]] | ExecutionPhases | None,
    resource_utilization: dict[str, Any] | None,
    performance_characteristics: dict[str, Any] | None,
    duration_seconds: float | None,
    kwargs: dict[str, Any],
) -> None:
    """Attach optional metadata blocks and timing details to the builder."""
    if kwargs.get("data_loading_time") is not None:
        builder.set_loading_time(float(kwargs.get("data_loading_time", 0.0)) * 1000)
    if duration_seconds is not None:
        builder.set_total_duration(duration_seconds)

    builder.set_execution_metadata(execution_metadata)
    builder.set_validation_status(kwargs.get("validation_status", "UNKNOWN"), kwargs.get("validation_details", {}))
    builder.set_system_profile(kwargs.get("system_profile", {}))
    builder.set_tuning_info(
        tunings_applied=kwargs.get("tunings_applied"),
        config_hash=kwargs.get("tuning_config_hash"),
        source_file=kwargs.get("tuning_source_file"),
    )
    builder.add_plan_capture_stats(
        kwargs.get("query_plans_captured", 0),
        kwargs.get("plan_capture_failures", 0),
        kwargs.get("plan_capture_errors", []),
    )
    if kwargs.get("cost_summary"):
        builder.set_cost_summary(kwargs.get("cost_summary"))

    _apply_phase_data(builder, phases)

    if performance_characteristics is not None:
        builder.add_execution_metadata("performance_characteristics", performance_characteristics)
    if resource_utilization is not None:
        builder.add_execution_metadata("resource_utilization", resource_utilization)


def build_enhanced_benchmark_result(
    *,
    benchmark: Any,
    platform: str,
    query_results: list[dict[str, Any]],
    execution_metadata: Optional[dict[str, Any]] = None,
    phases: Optional[dict[str, dict[str, Any]] | ExecutionPhases] = None,
    resource_utilization: Optional[dict[str, Any]] = None,
    performance_characteristics: Optional[dict[str, Any]] = None,
    duration_seconds: Optional[float] = None,
    **kwargs: Any,
) -> Any:
    """Build a standardized BenchmarkResults object from benchmark execution data."""

    execution_metadata = execution_metadata or {}
    benchmark_name = benchmark.benchmark_name
    short_name = benchmark_name[:-10] if benchmark_name.lower().endswith(" benchmark") else benchmark_name
    benchmark_id = execution_metadata.get("benchmark_id") or normalize_benchmark_id(benchmark_name)

    builder = ResultBuilder(
        benchmark=BenchmarkInfoInput(
            name=short_name,
            scale_factor=benchmark.scale_factor,
            test_type=kwargs.get("test_execution_type", "standard"),
            benchmark_id=benchmark_id,
            display_name=short_name,
        ),
        platform=_build_platform_input(platform, execution_metadata, kwargs),
        execution_id=kwargs.get("execution_id"),
    )

    _apply_run_config(builder, execution_metadata)

    for query_result in query_results:
        builder.add_query_result(normalize_query_result(query_result))

    _add_table_statistics(builder, kwargs)
    _apply_optional_builder_data(
        builder,
        execution_metadata,
        phases,
        resource_utilization,
        performance_characteristics,
        duration_seconds,
        kwargs,
    )

    return builder.build()

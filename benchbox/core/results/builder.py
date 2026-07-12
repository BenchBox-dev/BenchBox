"""Centralized result builder for benchmark execution.

This module provides the ResultBuilder class that consolidates all BenchmarkResults
creation into a single, centralized location. This ensures consistent, complete
output regardless of execution mode (SQL vs DataFrame).

Usage:
    from benchbox.core.results.builder import ResultBuilder, BenchmarkInfoInput

    builder = ResultBuilder(
        benchmark=BenchmarkInfoInput(name="TPC-H", scale_factor=1.0),
        platform=PlatformInfoInput(name="DuckDB", platform_version="1.0.0"),
    )

    for result in query_results:
        builder.add_query_result(normalize_query_result(result))

    builder.set_loading_time(load_time_ms)
    results = builder.build()

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from benchbox.core.results.environment import (
    NormalizedExecutionEnvironment,
    PlatformCloudMetadata,
    PlatformComputeMetadata,
    PlatformDeploymentMetadata,
    PlatformStorageMetadata,
    build_environment_payload,
    build_platform_metadata_payload,
)
from benchbox.core.results.metrics import (
    TimingStatsCalculator,
    TPCMetricsCalculator,
)
from benchbox.core.results.models import (
    BenchmarkResults,
    DataLoadingPhase,
    ExecutionPhases,
    PowerTestPhase,
    QueryExecution,
    SetupPhase,
    TableLoadingStats,
    ThroughputStream,
    ThroughputTestPhase,
)
from benchbox.core.results.platform_info import (
    PlatformInfoInput,
    format_platform_display_name,
)
from benchbox.core.results.query_normalizer import (
    QueryResultInput,
    format_query_id,
)

if TYPE_CHECKING:
    pass


def normalize_benchmark_id(name: str) -> str:
    """Normalize benchmark name to canonical ID.

    Maps benchmark names to canonical IDs for consistent identification
    across SQL and DataFrame execution paths.

    Args:
        name: Benchmark name (e.g., "TPC-H", "TPC-H Benchmark", "tpch")

    Returns:
        Canonical benchmark ID (e.g., "tpch", "tpcds", "ssb", "clickbench")

    Examples:
        >>> normalize_benchmark_id("TPC-H")
        'tpch'
        >>> normalize_benchmark_id("TPC-H Benchmark")
        'tpch'
        >>> normalize_benchmark_id("TPC-DS")
        'tpcds'
    """
    import re

    # Strip parenthetical suffixes like "(heavy)" and trailing " Benchmark"
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    if cleaned.lower().endswith(" benchmark"):
        cleaned = cleaned[:-10]
    lowered = cleaned.lower().strip()

    # Canonical ID mappings for known benchmarks.
    # Each tuple contains variant spellings that map to the canonical ID.
    # Matching is exact - no substring checks - so each display form that
    # callers may pass must be enumerated explicitly.
    benchmark_mappings: list[tuple[str, tuple[str, ...]]] = [
        ("tpcds_obt", ("tpcds_obt", "tpcds-obt", "tpc-ds obt", "tpc-ds one big table")),
        ("tpchavoc", ("tpchavoc", "tpch-avoc", "tpch_avoc", "tpc-havoc", "tpc-h avoc")),
        ("tpch_skew", ("tpch_skew", "tpch-skew", "tpc-h skew")),
        ("tpch", ("tpch", "tpc-h", "tpc_h")),
        ("tpcds", ("tpcds", "tpc-ds", "tpc_ds")),
        ("ssb", ("ssb", "star schema")),
        ("clickbench", ("clickbench",)),
    ]

    for canonical_id, variants in benchmark_mappings:
        if any(lowered == v for v in variants):
            return canonical_id

    # Generic normalization: lowercase with underscores
    normalized = lowered.replace(" ", "_").replace("-", "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


# Family mapping: canonical benchmark ID → parent family for dialect selection.
# Single source of truth - used by adapter routing and dialect inference.
_BENCHMARK_FAMILY: dict[str, str] = {
    "tpch": "tpch",
    "tpch_skew": "tpch",
    "tpchavoc": "tpch",
    "tpcds": "tpcds",
    "tpcds_obt": "tpcds",
}


def benchmark_family(benchmark_id: str) -> str:
    """Return the parent family for a canonical benchmark ID.

    Returns "tpch", "tpcds", or "generic".
    """
    return _BENCHMARK_FAMILY.get(benchmark_id, "generic")


@dataclass
class BenchmarkInfoInput:
    """Normalized benchmark information."""

    name: str  # Always short form: "TPC-H", "TPC-DS" (not "TPC-H Benchmark")
    scale_factor: float
    test_type: str = "power"  # "power", "throughput", "standard", "combined"
    benchmark_id: str | None = None
    display_name: str | None = None  # Optional full display name
    compliance_class: str | None = None  # e.g., "official", "unofficial_nonstandard", "unofficial_subscale"


@dataclass
class TableStats:
    """Statistics for a loaded table."""

    rows: int
    load_time_ms: int = 0
    status: str = "SUCCESS"
    error_message: str | None = None


@dataclass
class RunConfigInput:
    """Run configuration for reproducibility."""

    compression_type: str | None = None
    compression_level: int | None = None
    seed: int | None = None
    phases: list[str] | None = None
    query_subset: list[str] | None = None
    parallelism: int | None = None
    tuning_mode: str | None = None
    tuning_config: dict[str, Any] | None = None
    platform_options: dict[str, Any] | None = None
    platform_option_sources: dict[str, str] | None = None
    table_mode: str | None = None
    external_format: str | None = None
    table_format: str | None = None
    table_format_compression: str | None = None
    table_format_partition_cols: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.compression_type:
            data["compression"] = {"type": self.compression_type, "level": self.compression_level}
        if self.seed is not None:
            data["seed"] = self.seed
        if self.phases:
            data["phases"] = self.phases
        if self.query_subset:
            data["query_subset"] = self.query_subset
        if self.parallelism is not None:
            data["parallelism"] = self.parallelism
        if self.tuning_mode:
            data["tuning_mode"] = self.tuning_mode
        if self.tuning_config:
            data["tuning_config"] = self.tuning_config
        if self.platform_options:
            data["platform_options"] = self.platform_options
        if self.platform_option_sources:
            data["platform_option_sources"] = self.platform_option_sources
        if self.table_mode and self.table_mode != "native":
            data["table_mode"] = self.table_mode
        if self.external_format:
            data["external_format"] = self.external_format
        if self.table_format:
            data["table_format"] = self.table_format
            if self.table_format_compression:
                data["table_format_compression"] = self.table_format_compression
            if self.table_format_partition_cols:
                data["table_format_partition_cols"] = self.table_format_partition_cols
        return data


class ResultBuilder:
    """Centralized builder for BenchmarkResults.

    This class collects execution data from any adapter (SQL or DataFrame)
    and produces complete, validated BenchmarkResults instances with
    consistent field population.

    Key responsibilities:
    - Normalize query results to consistent format
    - Calculate TPC metrics (Power@Size, Throughput@Size, QphH)
    - Calculate timing statistics (avg, min, max, percentiles, geometric mean)
    - Build complete platform_info with rich configuration
    - Ensure all fields are populated regardless of execution mode
    """

    def __init__(
        self,
        benchmark: BenchmarkInfoInput,
        platform: PlatformInfoInput,
        execution_id: str | None = None,
    ):
        """Initialize the result builder.

        Args:
            benchmark: Benchmark identification and configuration
            platform: Platform identification and configuration
            execution_id: Optional unique execution ID (auto-generated if not provided)
        """
        self._benchmark = benchmark
        self._platform = platform
        self._execution_id = execution_id or self._generate_id()

        # Query results storage
        self._query_results: list[QueryResultInput] = []

        # Table loading statistics
        self._table_stats: dict[str, TableStats] = {}
        self._loading_time_ms: float = 0.0

        # Timing metadata
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None

        # Additional metadata
        self._validation_status: str = "PASSED"
        self._validation_details: dict[str, Any] | None = None
        self._execution_metadata: dict[str, Any] = {}
        self._run_config: RunConfigInput | None = None
        self._phase_status: dict[str, dict[str, Any]] = {}
        self._system_profile: dict[str, Any] | None = None
        self._execution_environment: NormalizedExecutionEnvironment | dict[str, Any] | None = None
        self._platform_deployment: PlatformDeploymentMetadata | dict[str, Any] | None = None
        self._platform_cloud: PlatformCloudMetadata | dict[str, Any] | None = None
        self._platform_compute: PlatformComputeMetadata | dict[str, Any] | None = None
        self._platform_storage: PlatformStorageMetadata | dict[str, Any] | None = None
        self._platform_raw_config: dict[str, Any] | None = None
        self._platform_raw_metadata: dict[str, Any] | None = None
        self._tunings_applied: dict[str, Any] | None = None
        self._tuning_config_hash: str | None = None
        self._tuning_source_file: str | None = None

        # Query plan capture statistics
        self._query_plans_captured: int = 0
        self._plan_capture_failures: int = 0
        self._plan_capture_errors: list[dict[str, str]] = []

        # Cost tracking
        self._cost_summary: dict[str, Any] | None = None

        # Throughput test data (for multi-stream benchmarks)
        self._throughput_streams: list[dict[str, Any]] = []
        self._throughput_total_time_seconds: float = 0.0
        self._execution_phases_override: ExecutionPhases | None = None
        self._total_duration_seconds: float | None = None

    @staticmethod
    def _generate_id() -> str:
        """Generate a unique execution ID."""
        return uuid.uuid4().hex[:8]

    # -------------------------------------------------------------------------
    # Query Result Collection
    # -------------------------------------------------------------------------

    def add_query_result(self, result: QueryResultInput) -> None:
        """Add a query execution result.

        Args:
            result: Normalized query result
        """
        self._query_results.append(result)

    def add_query_results(self, results: list[QueryResultInput]) -> None:
        """Add multiple query execution results.

        Args:
            results: List of normalized query results
        """
        self._query_results.extend(results)

    # -------------------------------------------------------------------------
    # Table Loading Statistics
    # -------------------------------------------------------------------------

    def add_table_stats(
        self,
        table_name: str,
        row_count: int,
        load_time_ms: int = 0,
        status: str = "SUCCESS",
        error_message: str | None = None,
    ) -> None:
        """Add table loading statistics.

        Args:
            table_name: Name of the table
            row_count: Number of rows loaded
            load_time_ms: Time to load the table in milliseconds
            status: "SUCCESS" or "FAILED"
            error_message: Error message if failed
        """
        self._table_stats[table_name] = TableStats(
            rows=row_count,
            load_time_ms=load_time_ms,
            status=status,
            error_message=error_message,
        )

    def set_loading_time(self, time_ms: float) -> None:
        """Set total data loading time.

        Args:
            time_ms: Total loading time in milliseconds
        """
        self._loading_time_ms = time_ms

    def set_total_duration(self, duration_seconds: float) -> None:
        """Set explicit total run duration in seconds.

        Args:
            duration_seconds: Total duration in seconds
        """
        self._total_duration_seconds = duration_seconds

    # -------------------------------------------------------------------------
    # Timing Metadata
    # -------------------------------------------------------------------------

    def set_start_time(self, start_time: datetime) -> None:
        """Set benchmark start time."""
        self._start_time = start_time

    def set_end_time(self, end_time: datetime) -> None:
        """Set benchmark end time."""
        self._end_time = end_time

    def mark_started(self) -> None:
        """Mark the benchmark as started (sets start time to now)."""
        self._start_time = datetime.now()

    def mark_completed(self) -> None:
        """Mark the benchmark as completed (sets end time to now)."""
        self._end_time = datetime.now()

    # -------------------------------------------------------------------------
    # Validation and Metadata
    # -------------------------------------------------------------------------

    def set_validation_status(
        self,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Set validation status and details.

        Args:
            status: "PASSED" or "FAILED"
            details: Optional validation details
        """
        self._validation_status = status
        self._validation_details = details

    def set_execution_metadata(self, metadata: dict[str, Any]) -> None:
        """Set execution metadata.

        Args:
            metadata: Execution context metadata
        """
        self._execution_metadata = metadata

    def add_execution_metadata(self, key: str, value: Any) -> None:
        """Add a single metadata key-value pair."""
        self._execution_metadata[key] = value

    def set_run_config(self, config: RunConfigInput) -> None:
        """Set run configuration for reproducibility."""
        self._run_config = config

    def set_phase_status(
        self,
        phase: str,
        status: str,
        duration_ms: float | None = None,
        **extra: Any,
    ) -> None:
        """Set phase status metadata for export.

        Args:
            phase: Phase name (e.g., "data_generation", "power")
            status: Phase status (e.g., "COMPLETED", "FAILED")
            duration_ms: Optional duration in milliseconds
            **extra: Additional phase metadata (e.g., tables_generated, total_rows)
        """
        entry: dict[str, Any] = {"status": status}
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        entry.update(extra)
        self._phase_status[phase] = entry

    def set_system_profile(self, profile: dict[str, Any]) -> None:
        """Set system profile information."""
        self._system_profile = profile

    def set_execution_environment(self, environment: NormalizedExecutionEnvironment | dict[str, Any]) -> None:
        """Set normalized execution-environment metadata."""
        self._execution_environment = environment

    def set_platform_environment_metadata(
        self,
        *,
        deployment: PlatformDeploymentMetadata | dict[str, Any] | None = None,
        cloud: PlatformCloudMetadata | dict[str, Any] | None = None,
        compute: PlatformComputeMetadata | dict[str, Any] | None = None,
        storage: PlatformStorageMetadata | dict[str, Any] | None = None,
        raw_config: dict[str, Any] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set normalized platform deployment/cloud/compute/storage metadata."""
        if deployment is not None:
            self._platform_deployment = deployment
        if cloud is not None:
            self._platform_cloud = cloud
        if compute is not None:
            self._platform_compute = compute
        if storage is not None:
            self._platform_storage = storage
        if raw_config is not None:
            self._platform_raw_config = raw_config
        if raw_metadata is not None:
            self._platform_raw_metadata = raw_metadata

    def set_tuning_info(
        self,
        tunings_applied: dict[str, Any] | None = None,
        config_hash: str | None = None,
        source_file: str | None = None,
    ) -> None:
        """Set tuning configuration information."""
        self._tunings_applied = tunings_applied
        self._tuning_config_hash = config_hash
        self._tuning_source_file = source_file

    def set_cost_summary(self, cost_summary: dict[str, Any]) -> None:
        """Set cost summary for cloud platforms."""
        self._cost_summary = cost_summary

    def set_execution_phases(self, phases: ExecutionPhases) -> None:
        """Set execution phases directly."""
        self._execution_phases_override = phases

    # -------------------------------------------------------------------------
    # Query Plan Statistics
    # -------------------------------------------------------------------------

    def add_plan_capture_stats(
        self,
        plans_captured: int,
        capture_failures: int = 0,
        capture_errors: list[dict[str, str]] | None = None,
    ) -> None:
        """Add query plan capture statistics."""
        self._query_plans_captured = plans_captured
        self._plan_capture_failures = capture_failures
        self._plan_capture_errors = capture_errors or []

    # -------------------------------------------------------------------------
    # Throughput Test Support
    # -------------------------------------------------------------------------

    def add_throughput_stream(
        self,
        stream_id: int,
        query_results: list[QueryResultInput],
        duration_seconds: float,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> None:
        """Add results from a throughput test stream.

        Args:
            stream_id: Stream identifier
            query_results: Query results from this stream
            duration_seconds: Total stream duration
            start_time: Stream start time
            end_time: Stream end time
        """
        self._throughput_streams.append(
            {
                "stream_id": stream_id,
                "query_results": query_results,
                "duration_seconds": duration_seconds,
                "start_time": start_time,
                "end_time": end_time,
            }
        )

    def set_throughput_total_time(self, total_time_seconds: float) -> None:
        """Set total elapsed time for throughput test."""
        self._throughput_total_time_seconds = total_time_seconds

    # -------------------------------------------------------------------------
    # Build Methods
    # -------------------------------------------------------------------------

    def build(self) -> BenchmarkResults:
        """Build the complete, validated BenchmarkResults.

        Returns:
            Complete BenchmarkResults instance with all metrics calculated
        """
        # Calculate duration
        duration_seconds = self._calculate_duration()

        # Calculate query metrics (prefer measurement results when available)
        measurement_results = [r for r in self._query_results if r.run_type == "measurement" and r.iteration > 0]
        results_for_stats = measurement_results if measurement_results else self._query_results
        successful_queries = [r for r in results_for_stats if r.status == "SUCCESS"]
        # VALIDATION_FAILED (a write/op that ran but failed a post-condition
        # check, e.g. write_primitives/transaction_primitives) counts as a
        # failure here too, not just an execution FAILED -- mirroring
        # execution.py's _log_execution_summary, which already treats the two
        # the same for the console summary (#1150 review).
        failed_queries = [r for r in results_for_stats if r.status in ("FAILED", "VALIDATION_FAILED")]

        # Use measurement execution times for aggregate timing metrics when possible
        exec_times_all = [r.execution_time_seconds for r in results_for_stats if r.execution_time_seconds > 0]

        # Calculate timing statistics
        timing_stats = TimingStatsCalculator.calculate_seconds(exec_times_all)
        total_exec_time = timing_stats.get("total_s", 0.0)
        avg_time = timing_stats.get("avg_s", 0.0)
        geometric_mean = timing_stats.get("geometric_mean_s", 0.0)

        # Calculate TPC metrics only when all queries succeeded and run is official-comparable
        _is_unofficial = self._benchmark.compliance_class == "unofficial_subscale" or (
            hasattr(self._benchmark.compliance_class, "value")
            and self._benchmark.compliance_class.value == "unofficial_subscale"
        )
        if failed_queries or _is_unofficial:
            tpc_metrics = {
                "power_at_size": None,
                "throughput_at_size": None,
                "qph_at_size": None,
            }
            if failed_queries:
                geometric_mean = 0.0
        else:
            tpc_metrics = self._calculate_tpc_metrics()

        # Build execution phases
        execution_phases = self._build_execution_phases(
            exec_times_all,
            tpc_metrics,
        )
        if self._execution_phases_override is not None:
            execution_phases = self._execution_phases_override

        # Build query results list
        query_results_list = self._format_query_results()

        # Build platform info dict
        platform_info = self._build_platform_info_dict()
        execution_environment = self._build_execution_environment_metadata()
        platform_environment = self._build_platform_environment_metadata(platform_info)

        # Determine validation status based on failures
        validation_status = self._validation_status
        if failed_queries and validation_status == "PASSED":
            validation_status = "PARTIAL"

        return BenchmarkResults(
            # Core identification
            benchmark_name=self._benchmark.display_name or self._benchmark.name,
            platform=format_platform_display_name(
                self._platform.name,
                self._platform.execution_mode,
            ),
            scale_factor=self._benchmark.scale_factor,
            execution_id=self._execution_id,
            timestamp=self._start_time or datetime.now(),
            duration_seconds=duration_seconds,
            # Query counts
            total_queries=len(results_for_stats),
            successful_queries=len(successful_queries),
            failed_queries=len(failed_queries),
            # Query results
            query_results=query_results_list,
            # Summary metrics
            total_execution_time=total_exec_time,
            average_query_time=avg_time,
            # Loading stats
            data_loading_time=self._loading_time_ms / 1000.0,
            total_rows_loaded=sum(ts.rows for ts in self._table_stats.values()),
            table_statistics={
                name: {"rows": stats.rows, "load_time_ms": stats.load_time_ms}
                if stats.load_time_ms > 0
                else {"rows": stats.rows}
                for name, stats in self._table_stats.items()
            },
            # Execution phases
            execution_phases=execution_phases,
            # TPC metrics
            test_execution_type=self._benchmark.test_type,
            power_at_size=tpc_metrics.get("power_at_size"),
            throughput_at_size=tpc_metrics.get("throughput_at_size"),
            qph_at_size=tpc_metrics.get("qph_at_size"),
            geometric_mean_execution_time=geometric_mean or None,
            # Validation
            validation_status=validation_status,
            validation_details=self._validation_details,
            execution_environment=execution_environment,
            platform_deployment=(
                self._platform_deployment
                if self._platform_deployment is not None
                else platform_environment.get("deployment")
            ),
            platform_cloud=self._platform_cloud
            if self._platform_cloud is not None
            else platform_environment.get("cloud"),
            platform_compute=(
                self._platform_compute if self._platform_compute is not None else platform_environment.get("compute")
            ),
            platform_storage=(
                self._platform_storage if self._platform_storage is not None else platform_environment.get("storage")
            ),
            platform_raw_config=(
                self._platform_raw_config
                if self._platform_raw_config is not None
                else platform_environment.get("raw_config")
            ),
            platform_raw_metadata=(
                self._platform_raw_metadata
                if self._platform_raw_metadata is not None
                else platform_environment.get("raw_metadata")
            ),
            # Platform info
            platform_info=platform_info,
            # Execution metadata
            execution_metadata=self._build_execution_metadata(),
            system_profile=self._system_profile,
            # Tuning
            tunings_applied=self._tunings_applied,
            tuning_config_hash=self._tuning_config_hash,
            tuning_source_file=self._tuning_source_file,
            # Query plan stats
            query_plans_captured=self._query_plans_captured,
            plan_capture_failures=self._plan_capture_failures,
            plan_capture_errors=self._plan_capture_errors,
            # Cost
            cost_summary=self._cost_summary,
            _benchmark_id_override=self._benchmark.benchmark_id,
            # Methodology/comparability classification
            compliance_class=(
                self._benchmark.compliance_class.value
                if hasattr(self._benchmark.compliance_class, "value")
                else self._benchmark.compliance_class
            ),
        )

    def _calculate_duration(self) -> float:
        """Calculate total duration in seconds."""
        if self._total_duration_seconds is not None:
            return self._total_duration_seconds

        if self._start_time and self._end_time:
            delta = self._end_time - self._start_time
            return delta.total_seconds()

        # Fall back to sum of query times plus loading time
        total_query_time = sum(r.execution_time_seconds for r in self._query_results)
        return total_query_time + (self._loading_time_ms / 1000.0)

    def _calculate_tpc_metrics(self) -> dict[str, float | None]:
        """Calculate TPC benchmark metrics.

        Power@Size, Throughput@Size, and QphH/QphDS are only defined for
        TPC benchmarks (TPC-H, TPC-DS). Non-TPC benchmarks return all None.
        """
        metrics: dict[str, float | None] = {
            "power_at_size": None,
            "throughput_at_size": None,
            "qph_at_size": None,
        }

        # Power@Size is only defined for TPC benchmarks
        benchmark_id = normalize_benchmark_id(self._benchmark.name)
        if benchmark_id not in ("tpch", "tpcds"):
            return metrics

        scale_factor = self._benchmark.scale_factor
        test_type = self._benchmark.test_type

        # Calculate Power@Size for power and combined tests
        if test_type in ("power", "standard", "combined"):
            power = self._calculate_power_at_size()
            if power and power > 0:
                metrics["power_at_size"] = power

        # Calculate Throughput@Size for throughput and combined tests
        if test_type in ("throughput", "combined"):
            total_queries = 0
            num_streams = 0
            total_time = 0.0

            if self._throughput_streams:
                total_queries = sum(len(s["query_results"]) for s in self._throughput_streams)
                num_streams = len(self._throughput_streams)
                total_time = self._throughput_total_time_seconds
            elif self._execution_phases_override and self._execution_phases_override.throughput_test:
                phase = self._execution_phases_override.throughput_test
                total_queries = phase.total_queries_executed
                num_streams = phase.num_streams
                total_time = (phase.duration_ms or 0) / 1000.0

            if total_time > 0 and total_queries > 0 and num_streams > 0:
                throughput = TPCMetricsCalculator.calculate_throughput_at_size(
                    total_queries,
                    total_time,
                    scale_factor,
                    num_streams,
                )
                if throughput > 0:
                    metrics["throughput_at_size"] = throughput

        # Calculate composite QphH for combined tests
        power = metrics.get("power_at_size")
        throughput = metrics.get("throughput_at_size")
        if power and throughput:
            qph = TPCMetricsCalculator.calculate_qph(power, throughput)
            if qph > 0:
                metrics["qph_at_size"] = qph

        return metrics

    def _calculate_power_at_size(self) -> float | None:
        """Calculate Power@Size using only final measurement iteration."""
        measurement = [r for r in self._query_results if r.run_type == "measurement" and r.iteration > 0]
        if not measurement:
            return None

        final_iter = max((r.iteration for r in measurement), default=0)
        final_results = [r for r in measurement if r.iteration == final_iter]
        if not final_results:
            return None
        if any(r.status != "SUCCESS" for r in final_results):
            return None

        times = [r.execution_time_seconds for r in final_results if r.execution_time_seconds > 0]
        if not times:
            return None
        return TPCMetricsCalculator.calculate_power_at_size(times, self._benchmark.scale_factor)

    def _build_execution_phases(
        self,
        exec_times_seconds: list[float],
        tpc_metrics: dict[str, float | None],
    ) -> ExecutionPhases | None:
        """Build ExecutionPhases structure."""
        setup_phase = self._build_setup_phase()
        power_test_phase = self._build_power_test_phase(
            exec_times_seconds,
            tpc_metrics,
        )
        throughput_test_phase = self._build_throughput_test_phase(tpc_metrics)

        if not any([setup_phase, power_test_phase, throughput_test_phase]):
            return None

        return ExecutionPhases(
            setup=setup_phase or SetupPhase(),
            power_test=power_test_phase,
            throughput_test=throughput_test_phase,
        )

    def _build_setup_phase(self) -> SetupPhase | None:
        """Build SetupPhase from table loading stats."""
        if not self._table_stats:
            return None

        per_table_stats = {
            name: TableLoadingStats(
                rows=stats.rows,
                load_time_ms=stats.load_time_ms,
                status=stats.status,
                error_message=stats.error_message,
            )
            for name, stats in self._table_stats.items()
        }

        total_rows = sum(ts.rows for ts in self._table_stats.values())
        failed_count = sum(1 for ts in self._table_stats.values() if ts.status == "FAILED")
        status = "FAILED" if failed_count > 0 else "SUCCESS"

        return SetupPhase(
            data_loading=DataLoadingPhase(
                duration_ms=int(self._loading_time_ms),
                status=status,
                total_rows_loaded=total_rows,
                tables_loaded=len(self._table_stats),
                per_table_stats=per_table_stats,
            )
        )

    def _build_power_test_phase(
        self,
        exec_times_seconds: list[float],
        tpc_metrics: dict[str, float | None],
    ) -> PowerTestPhase | None:
        """Build PowerTestPhase from query results."""
        if self._benchmark.test_type not in ("power", "standard", "combined"):
            return None

        if not self._query_results:
            return None

        # Build query executions
        query_executions = []
        for i, result in enumerate(self._query_results):
            query_executions.append(
                QueryExecution(
                    query_id=format_query_id(result.query_id),
                    stream_id=str(result.stream_id),
                    execution_order=i + 1,
                    execution_time_ms=int(result.execution_time_seconds * 1000),
                    status=result.status,
                    rows_returned=result.rows_returned,
                    error_message=result.error_message,
                    iteration=result.iteration,
                    run_type=result.run_type,
                    row_count_validation=result.row_count_validation,
                    cost=result.cost,
                )
            )

        # Calculate geometric mean
        geometric_mean = 0.0
        if exec_times_seconds:
            geometric_mean = TPCMetricsCalculator.calculate_geometric_mean(exec_times_seconds)

        # Calculate total duration
        total_duration_ms = sum(int(r.execution_time_seconds * 1000) for r in self._query_results)

        now_iso = datetime.now().isoformat()

        return PowerTestPhase(
            start_time=self._start_time.isoformat() if self._start_time else now_iso,
            end_time=self._end_time.isoformat() if self._end_time else now_iso,
            duration_ms=total_duration_ms,
            query_executions=query_executions,
            geometric_mean_time=geometric_mean,
            power_at_size=tpc_metrics.get("power_at_size") or 0.0,
        )

    def _build_throughput_test_phase(
        self,
        tpc_metrics: dict[str, float | None],
    ) -> ThroughputTestPhase | None:
        """Build ThroughputTestPhase from stream data."""
        if self._benchmark.test_type not in ("throughput", "combined"):
            return None

        if not self._throughput_streams:
            return None

        streams = []
        total_queries = 0

        for stream_data in self._throughput_streams:
            stream_id = stream_data["stream_id"]
            results = stream_data["query_results"]
            duration = stream_data["duration_seconds"]
            start = stream_data.get("start_time")
            end = stream_data.get("end_time")

            query_executions = []
            for i, result in enumerate(results):
                query_executions.append(
                    QueryExecution(
                        query_id=format_query_id(result.query_id),
                        stream_id=str(stream_id),
                        execution_order=i + 1,
                        execution_time_ms=int(result.execution_time_seconds * 1000),
                        status=result.status,
                        rows_returned=result.rows_returned,
                        error_message=result.error_message,
                    )
                )
                total_queries += 1

            now_iso = datetime.now().isoformat()
            streams.append(
                ThroughputStream(
                    stream_id=stream_id,
                    start_time=start.isoformat() if start else now_iso,
                    end_time=end.isoformat() if end else now_iso,
                    duration_ms=int(duration * 1000),
                    query_executions=query_executions,
                )
            )

        total_duration_ms = int(self._throughput_total_time_seconds * 1000)
        now_iso = datetime.now().isoformat()

        return ThroughputTestPhase(
            start_time=self._start_time.isoformat() if self._start_time else now_iso,
            end_time=self._end_time.isoformat() if self._end_time else now_iso,
            duration_ms=total_duration_ms,
            num_streams=len(streams),
            streams=streams,
            total_queries_executed=total_queries,
            throughput_at_size=tpc_metrics.get("throughput_at_size") or 0.0,
        )

    def _format_query_results(self) -> list[dict[str, Any]]:
        """Format query results as list of dictionaries."""
        results = []
        for result in self._query_results:
            result_dict: dict[str, Any] = {
                "query_id": format_query_id(result.query_id),
                "execution_time_seconds": result.execution_time_seconds,
                "execution_time": result.execution_time_seconds,
                "execution_time_ms": int(result.execution_time_seconds * 1000),
                "status": result.status,
                "rows_returned": result.rows_returned,
                "iteration": result.iteration,
                "stream_id": result.stream_id,
            }

            if result.error_message:
                result_dict["error_message"] = result.error_message
            if result.cost is not None:
                result_dict["cost"] = result.cost
            if result.run_type:
                result_dict["run_type"] = result.run_type
            if result.row_count_validation:
                result_dict["row_count_validation"] = result.row_count_validation
            if result.dataframe_skip_summary:
                result_dict["dataframe_skip_summary"] = result.dataframe_skip_summary
            if result.query_plan is not None:
                result_dict["query_plan"] = result.query_plan
            if result.plan_fingerprint is not None:
                result_dict["plan_fingerprint"] = result.plan_fingerprint
            if result.plan_fingerprint_normalized is not None:
                result_dict["plan_fingerprint_normalized"] = result.plan_fingerprint_normalized
            if result.plan_capture_time_ms is not None:
                result_dict["plan_capture_time_ms"] = result.plan_capture_time_ms
            if result.plan_capture_error is not None:
                result_dict["plan_capture_error"] = result.plan_capture_error
            if result.result_digest is not None:
                result_dict["result_digest"] = result.result_digest
            if result.test_type:
                result_dict["test_type"] = result.test_type

            results.append(result_dict)

        return results

    def _build_platform_info_dict(self) -> dict[str, Any]:
        """Build platform_info dictionary."""
        info: dict[str, Any] = {
            "platform_name": self._platform.name,
            "execution_mode": self._platform.execution_mode,
        }

        if self._platform.platform_version:
            info["platform_version"] = self._platform.platform_version
        if self._platform.client_library_version:
            info["client_library_version"] = self._platform.client_library_version

        if self._platform.connection_mode:
            info["connection_mode"] = self._platform.connection_mode

        if self._platform.family:
            info["family"] = self._platform.family

        if self._platform.config:
            info["configuration"] = self._platform.config

        if self._platform.engine_version:
            info["engine_version"] = self._platform.engine_version
        if self._platform.engine_version_source:
            info["engine_version_source"] = self._platform.engine_version_source

        return info

    def _build_execution_environment_metadata(self) -> dict[str, Any]:
        """Build normalized execution-environment metadata carried by BenchmarkResults."""
        payload = build_environment_payload(
            system_profile=self._system_profile,
            execution_environment=self._execution_environment,
        )
        return {
            key: payload[key]
            for key in ("client_host", "platform_runtime", "container")
            if isinstance(payload.get(key), dict)
        }

    def _build_platform_environment_metadata(self, platform_info: dict[str, Any]) -> dict[str, Any]:
        """Build normalized platform metadata carried by BenchmarkResults."""
        platform_config = (
            platform_info.get("configuration") if isinstance(platform_info.get("configuration"), dict) else {}
        )
        return build_platform_metadata_payload(
            platform_info=platform_info,
            platform_config=platform_config,
            deployment=self._platform_deployment,
            cloud=self._platform_cloud,
            compute=self._platform_compute,
            storage=self._platform_storage,
            raw_config=self._platform_raw_config if self._platform_raw_config is not None else platform_config,
            raw_metadata=self._platform_raw_metadata,
        )

    def _build_execution_metadata(self) -> dict[str, Any]:
        """Build execution metadata dictionary."""
        metadata = dict(self._execution_metadata)

        # Add execution mode info
        metadata["mode"] = self._platform.execution_mode
        metadata["execution_mode"] = self._platform.execution_mode

        # Add DataFrame-specific metadata
        if self._platform.execution_mode == "dataframe":
            metadata["dataframe_platform"] = self._platform.name
            if self._platform.family:
                metadata["dataframe_family"] = self._platform.family

        if self._run_config:
            run_config = {}
            existing_run_config = metadata.get("run_config")
            if isinstance(existing_run_config, dict):
                run_config.update(existing_run_config)
            run_config.update(self._run_config.to_dict())
            metadata["run_config"] = run_config
        if self._phase_status:
            merged_phase_status: dict[str, dict[str, Any]] = {}
            existing_phase_status = metadata.get("phase_status")
            if isinstance(existing_phase_status, dict):
                for phase_name, phase_data in existing_phase_status.items():
                    if isinstance(phase_data, dict):
                        merged_phase_status[phase_name] = dict(phase_data)
            for phase_name, phase_data in self._phase_status.items():
                current = merged_phase_status.get(phase_name, {})
                current.update(phase_data)
                merged_phase_status[phase_name] = current
            metadata["phase_status"] = merged_phase_status

        return metadata


# Convenience function for quick result building
def build_benchmark_results(
    benchmark_name: str,
    platform_name: str,
    scale_factor: float,
    query_results: list[QueryResultInput],
    *,
    execution_mode: str = "sql",
    test_type: str = "power",
    platform_version: str | None = None,
    table_stats: dict[str, int] | None = None,
    loading_time_ms: float = 0.0,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> BenchmarkResults:
    """Convenience function to build BenchmarkResults in one call.

    Args:
        benchmark_name: Benchmark name (e.g., "TPC-H")
        platform_name: Platform name (e.g., "DuckDB")
        scale_factor: Benchmark scale factor
        query_results: List of normalized query results
        execution_mode: "sql" or "dataframe"
        test_type: "power", "throughput", "standard", or "combined"
        platform_version: Optional platform version string
        table_stats: Optional table row counts {table_name: row_count}
        loading_time_ms: Data loading time in milliseconds
        start_time: Benchmark start time
        end_time: Benchmark end time

    Returns:
        Complete BenchmarkResults instance
    """
    builder = ResultBuilder(
        benchmark=BenchmarkInfoInput(
            name=benchmark_name,
            scale_factor=scale_factor,
            test_type=test_type,
        ),
        platform=PlatformInfoInput(
            name=platform_name,
            platform_version=platform_version,
            client_library_version=None,
            execution_mode=execution_mode,
        ),
    )

    builder.add_query_results(query_results)

    if table_stats:
        for table_name, row_count in table_stats.items():
            builder.add_table_stats(table_name, row_count)

    if loading_time_ms:
        builder.set_loading_time(loading_time_ms)

    if start_time:
        builder.set_start_time(start_time)
    if end_time:
        builder.set_end_time(end_time)

    return builder.build()

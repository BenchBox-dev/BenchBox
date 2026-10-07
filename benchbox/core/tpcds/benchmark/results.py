"""TPC-DS benchmark result dataclasses."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from benchbox.core.throughput.result import throughput_stream_numbering

from .config import ThroughputTestConfig


@dataclass
class ThroughputTestResult:
    """Result of TPC-DS Throughput Test."""

    config: ThroughputTestConfig
    start_time: float
    end_time: float
    total_duration: float
    streams_executed: int
    streams_successful: int
    stream_results: list[dict[str, Any]]
    throughput_at_size: Optional[float]
    success: bool
    error: Optional[str] = None
    stream_numbering: dict[str, Any] = field(default_factory=throughput_stream_numbering)


@dataclass
class MaintenanceTestResult:
    """Result of TPC-DS Maintenance Test."""

    test_duration: float
    total_operations: int
    successful_operations: int
    failed_operations: int = 0
    overall_throughput: float = 0.0
    maintenance_operations: list[dict[str, Any]] = field(default_factory=list)
    error_details: list[str] = field(default_factory=list)


@dataclass
class QueryResult:
    """Result of a single query execution (legacy compatibility)."""

    query_id: int
    stream_id: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    execution_time: Optional[float] = None
    row_count: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None
    sql: Optional[str] = None


@dataclass
class PhaseResult:
    """Result of a benchmark phase (legacy compatibility)."""

    phase_name: str
    queries: list[QueryResult] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_time: float = 0.0
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class BenchmarkResult:
    """Complete benchmark result (legacy compatibility)."""

    scale_factor: float
    num_streams: int = 1
    power_test: Optional[PhaseResult] = None
    throughput_test: Optional[PhaseResult] = None
    maintenance_test: Optional[PhaseResult] = None
    power_at_size: float = 0.0
    throughput_at_size: float = 0.0
    benchmark_start_time: Optional[datetime] = None
    benchmark_end_time: Optional[datetime] = None
    total_benchmark_time: float = 0.0
    success: bool = True
    validation_results: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ThroughputTestResult",
    "MaintenanceTestResult",
    "QueryResult",
    "PhaseResult",
    "BenchmarkResult",
]

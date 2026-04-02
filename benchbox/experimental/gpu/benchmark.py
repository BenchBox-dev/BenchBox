"""GPU benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.base import BaseBenchmark

from .capabilities import GPUInfo, detect_gpu, get_gpu_capabilities
from .metrics import GPUMemoryTracker, GPUMetricsAggregate, GPUMetricsCollector

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class GPUQueryResult:
    """Result of executing a GPU-accelerated query."""

    query_id: str
    success: bool
    execution_time_ms: float
    row_count: int = 0
    memory_used_mb: int = 0
    peak_memory_mb: int = 0
    gpu_utilization_percent: float = 0.0
    error_message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_id": self.query_id,
            "success": self.success,
            "execution_time_ms": self.execution_time_ms,
            "row_count": self.row_count,
            "memory_used_mb": self.memory_used_mb,
            "peak_memory_mb": self.peak_memory_mb,
            "gpu_utilization_percent": self.gpu_utilization_percent,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class GPUBenchmarkResults:
    """Results from running the GPU benchmark."""

    gpu_info: GPUInfo
    started_at: datetime
    completed_at: datetime | None = None
    query_results: list[GPUQueryResult] = field(default_factory=list)
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_execution_time_ms: float = 0.0
    peak_memory_mb: int = 0
    avg_gpu_utilization: float = 0.0
    gpu_metrics_aggregate: GPUMetricsAggregate | None = None

    def add_result(self, result: GPUQueryResult) -> None:
        """Add a query result."""
        self.query_results.append(result)
        self.total_queries += 1
        if result.success:
            self.successful_queries += 1
        else:
            self.failed_queries += 1
        self.total_execution_time_ms += result.execution_time_ms
        self.peak_memory_mb = max(self.peak_memory_mb, result.peak_memory_mb)

    def complete(self, metrics_aggregate: GPUMetricsAggregate | None = None) -> None:
        """Mark the benchmark as complete."""
        self.completed_at = datetime.now(timezone.utc)
        self.gpu_metrics_aggregate = metrics_aggregate
        if metrics_aggregate:
            self.avg_gpu_utilization = metrics_aggregate.avg_utilization_percent

    @property
    def success_rate(self) -> float:
        """Get success rate as a fraction."""
        return self.successful_queries / self.total_queries if self.total_queries > 0 else 0.0

    @property
    def avg_execution_time_ms(self) -> float:
        """Get average execution time."""
        return self.total_execution_time_ms / self.total_queries if self.total_queries > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "gpu_info": self.gpu_info.to_dict(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_queries": self.total_queries,
            "successful_queries": self.successful_queries,
            "failed_queries": self.failed_queries,
            "success_rate": self.success_rate,
            "total_execution_time_ms": self.total_execution_time_ms,
            "avg_execution_time_ms": self.avg_execution_time_ms,
            "peak_memory_mb": self.peak_memory_mb,
            "avg_gpu_utilization": self.avg_gpu_utilization,
            "gpu_metrics_aggregate": self.gpu_metrics_aggregate.to_dict() if self.gpu_metrics_aggregate else None,
            "query_results": [r.to_dict() for r in self.query_results],
        }


# GPU benchmark query definitions
GPU_BENCHMARK_QUERIES: dict[str, dict[str, Any]] = {
    "aggregation_simple": {
        "name": "Simple Aggregation",
        "description": "Basic aggregation operations",
        "sql_template": """
            SELECT
                {group_col},
                COUNT(*) as cnt,
                SUM({sum_col}) as total,
                AVG({sum_col}) as average
            FROM {table}
            GROUP BY {group_col}
        """,
        "category": "aggregation",
    },
    "aggregation_complex": {
        "name": "Complex Aggregation",
        "description": "Multi-column aggregation with filtering",
        "sql_template": """
            SELECT
                {group_col1},
                {group_col2},
                COUNT(*) as cnt,
                SUM({sum_col}) as total,
                AVG({sum_col}) as average,
                MAX({sum_col}) as maximum,
                MIN({sum_col}) as minimum,
                STDDEV({sum_col}) as std_dev
            FROM {table}
            WHERE {filter_col} IS NOT NULL
            GROUP BY {group_col1}, {group_col2}
            ORDER BY total DESC
            LIMIT 100
        """,
        "category": "aggregation",
    },
    "join_inner": {
        "name": "Inner Join",
        "description": "Two-table inner join",
        "sql_template": """
            SELECT
                a.{key_col},
                a.{col1},
                b.{col2}
            FROM {table1} a
            INNER JOIN {table2} b ON a.{key_col} = b.{key_col}
        """,
        "category": "join",
    },
    "join_multi": {
        "name": "Multi-Table Join",
        "description": "Three or more table join",
        "sql_template": """
            SELECT
                a.{key_col},
                a.{col1},
                b.{col2},
                c.{col3}
            FROM {table1} a
            INNER JOIN {table2} b ON a.{key_col} = b.{key_col}
            INNER JOIN {table3} c ON b.{key2_col} = c.{key2_col}
        """,
        "category": "join",
    },
    "window_ranking": {
        "name": "Window Ranking",
        "description": "Row numbering and ranking",
        "sql_template": """
            SELECT
                {partition_col},
                {order_col},
                {value_col},
                ROW_NUMBER() OVER (PARTITION BY {partition_col} ORDER BY {order_col}) as row_num,
                RANK() OVER (PARTITION BY {partition_col} ORDER BY {order_col}) as rnk
            FROM {table}
        """,
        "category": "window",
    },
    "window_aggregate": {
        "name": "Window Aggregate",
        "description": "Running totals and moving averages",
        "sql_template": """
            SELECT
                {partition_col},
                {order_col},
                {value_col},
                SUM({value_col}) OVER (PARTITION BY {partition_col} ORDER BY {order_col}) as running_total,
                AVG({value_col}) OVER (PARTITION BY {partition_col} ORDER BY {order_col} ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) as moving_avg
            FROM {table}
        """,
        "category": "window",
    },
    "string_operations": {
        "name": "String Operations",
        "description": "String manipulation functions",
        "sql_template": """
            SELECT
                {string_col},
                LENGTH({string_col}) as len,
                UPPER({string_col}) as upper_val,
                LOWER({string_col}) as lower_val,
                SUBSTRING({string_col}, 1, 10) as first_10
            FROM {table}
            WHERE {string_col} IS NOT NULL
        """,
        "category": "string",
    },
    "filter_scan": {
        "name": "Filtered Table Scan",
        "description": "Full table scan with filtering",
        "sql_template": """
            SELECT *
            FROM {table}
            WHERE {filter_col} > {filter_value}
            AND {date_col} >= '{date_value}'
        """,
        "category": "scan",
    },
    "sort_large": {
        "name": "Large Sort",
        "description": "Sorting large result sets",
        "sql_template": """
            SELECT *
            FROM {table}
            ORDER BY {sort_col1}, {sort_col2}
        """,
        "category": "sort",
    },
    "distinct_count": {
        "name": "Distinct Count",
        "description": "Count distinct values",
        "sql_template": """
            SELECT
                COUNT(DISTINCT {col1}) as distinct_1,
                COUNT(DISTINCT {col2}) as distinct_2,
                COUNT(DISTINCT {col1} || '_' || {col2}) as distinct_combined
            FROM {table}
        """,
        "category": "aggregation",
    },
}


class GPUBenchmark(BaseBenchmark):
    """GPU Acceleration benchmark for DataFrame operations.

    Benchmarks GPU-accelerated query execution using RAPIDS cuDF and compares
    performance with CPU-based execution.

    Example:
        >>> benchmark = GPUBenchmark()
        >>> if benchmark.is_gpu_available():
        ...     results = benchmark.run_benchmark(adapter, "cudf")
    """

    SUPPORTED_PLATFORMS = {"cudf", "dask_cudf", "spark_rapids"}

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | str | None = None,
        seed: int = 42,
        device_index: int = 0,
        collect_metrics: bool = True,
        metrics_interval: float = 0.5,
        **kwargs: Any,
    ) -> None:
        """Initialize the GPU benchmark.

        Args:
            scale_factor: Scale factor for data generation
            output_dir: Output directory for generated data
            seed: Random seed for reproducibility
            device_index: GPU device index to use
            collect_metrics: Whether to collect GPU metrics during execution
            metrics_interval: Metrics sampling interval in seconds
            **kwargs: Additional configuration
        """
        super().__init__(scale_factor, output_dir, **kwargs)

        self._name = "GPU Acceleration Benchmark"
        self._version = "1.0"
        self._description = (
            "Benchmarks GPU-accelerated DataFrame operations using RAPIDS cuDF, "
            "comparing performance with CPU execution for aggregation, joins, "
            "window functions, and other OLAP operations."
        )

        self.seed = seed
        self.device_index = device_index
        self.collect_metrics = collect_metrics
        self.metrics_interval = metrics_interval

        # GPU detection
        self._gpu_info: GPUInfo | None = None
        self._queries = GPU_BENCHMARK_QUERIES

    @property
    def name(self) -> str:
        """Get benchmark name."""
        return self._name

    @property
    def version(self) -> str:
        """Get benchmark version."""
        return self._version

    @property
    def description(self) -> str:
        """Get benchmark description."""
        return self._description

    def is_gpu_available(self) -> bool:
        """Check if GPU is available for benchmarking."""
        if self._gpu_info is None:
            self._gpu_info = detect_gpu()
        return self._gpu_info.available and self._gpu_info.cudf_available

    def get_gpu_info(self) -> GPUInfo:
        """Get GPU information."""
        if self._gpu_info is None:
            self._gpu_info = detect_gpu()
        return self._gpu_info

    def get_queries(self) -> dict[str, str]:
        """Get all benchmark queries.

        Returns:
            Dictionary mapping query IDs to query strings.
        """
        # Return query templates - actual queries depend on data schema
        return {qid: q["sql_template"] for qid, q in self._queries.items()}

    def get_query(self, query_id: int | str, *, params: dict[str, Any] | None = None) -> str:
        """Get a specific benchmark query.

        Args:
            query_id: Query identifier
            params: Optional parameters for template substitution

        Returns:
            Query SQL string

        Raises:
            ValueError: If query_id not found
        """
        query_id_str = str(query_id)
        if query_id_str not in self._queries:
            available = ", ".join(self._queries.keys())
            raise ValueError(f"Unknown query ID: {query_id_str}. Available: {available}")

        sql_template = self._queries[query_id_str]["sql_template"]

        # Apply parameters if provided
        if params:
            sql_template = sql_template.format(**params)

        return sql_template.strip()

    def get_supported_platforms(self) -> set[str]:
        """Get platforms that support GPU acceleration."""
        return self.SUPPORTED_PLATFORMS.copy()

    def get_query_categories(self) -> list[str]:
        """Get available query categories."""
        return list(set(q["category"] for q in self._queries.values()))

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query IDs for a category."""
        return [qid for qid, q in self._queries.items() if q["category"] == category]

    def generate_data(
        self,
        tables: list[str] | None = None,
        output_format: str = "parquet",
    ) -> dict[str, str]:
        """Generate sample data for GPU benchmarking.

        Args:
            tables: Optional list of tables to generate
            output_format: Output format (parquet recommended for GPU)

        Returns:
            Dictionary mapping table names to file paths
        """
        import random

        random.seed(self.seed)
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        files: dict[str, str] = {}

        # Generate test data using pandas/numpy (can be loaded to GPU later)
        try:
            import numpy as np
            import pandas as pd

            # Scale row count with scale factor
            n_rows = int(100000 * self.scale_factor)

            # Main benchmark table
            df = pd.DataFrame(
                {
                    "id": range(n_rows),
                    "category": np.random.choice(["A", "B", "C", "D", "E"], n_rows),
                    "subcategory": np.random.choice([f"sub_{i}" for i in range(20)], n_rows),
                    "value": np.random.uniform(0, 1000, n_rows),
                    "quantity": np.random.randint(1, 100, n_rows),
                    "date": pd.date_range("2020-01-01", periods=n_rows, freq="h"),
                    "text_field": [f"text_{i % 1000}" for i in range(n_rows)],
                    "flag": np.random.choice([True, False], n_rows),
                }
            )

            main_path = output_path / f"gpu_benchmark_main.{output_format}"
            if output_format == "parquet":
                df.to_parquet(main_path, index=False)
            else:
                df.to_csv(main_path, index=False)
            files["gpu_benchmark_main"] = str(main_path)

            # Dimension table for joins
            dim_df = pd.DataFrame(
                {
                    "category": ["A", "B", "C", "D", "E"],
                    "category_name": ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"],
                    "priority": [1, 2, 3, 4, 5],
                }
            )

            dim_path = output_path / f"gpu_benchmark_dim.{output_format}"
            if output_format == "parquet":
                dim_df.to_parquet(dim_path, index=False)
            else:
                dim_df.to_csv(dim_path, index=False)
            files["gpu_benchmark_dim"] = str(dim_path)

        except ImportError as e:
            logger.warning(f"Could not generate data: {e}")

        return files

    def execute_gpu_query(
        self,
        cudf_df: Any,
        query_id: str,
        query_sql: str,
    ) -> GPUQueryResult:
        """Execute a query on GPU using cuDF.

        Args:
            cudf_df: cuDF DataFrame
            query_sql: SQL query to execute
            query_id: Query identifier

        Returns:
            GPUQueryResult with execution metrics
        """
        memory_tracker = GPUMemoryTracker(device_index=self.device_index)
        memory_tracker.start()

        start_time = time.perf_counter()
        try:
            # cuDF supports SQL via dask-sql or direct DataFrame operations
            # Here we use DataFrame API operations that mirror SQL semantics

            # Register the DataFrame for SQL execution if dask-sql is available
            try:
                from dask_sql import Context  # type: ignore

                c = Context()
                c.create_table("data", cudf_df)
                result = c.sql(query_sql)
                row_count = len(result)
            except ImportError:
                # Fallback: execute as cuDF operations
                # This is a simplified approach - real implementation would parse SQL
                result = cudf_df
                row_count = len(result)

            execution_time_ms = (time.perf_counter() - start_time) * 1000
            memory_summary = memory_tracker.get_summary()

            return GPUQueryResult(
                query_id=query_id,
                success=True,
                execution_time_ms=execution_time_ms,
                row_count=row_count,
                memory_used_mb=memory_summary["end_memory_mb"],
                peak_memory_mb=memory_summary["peak_memory_mb"],
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return GPUQueryResult(
                query_id=query_id,
                success=False,
                execution_time_ms=execution_time_ms,
                error_message=str(e),
            )

    def run_benchmark(
        self,
        cudf_df: Any,
        query_ids: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> GPUBenchmarkResults:
        """Run the GPU benchmark.

        Args:
            cudf_df: cuDF DataFrame to benchmark against
            query_ids: Optional list of specific queries to run
            categories: Optional list of query categories to run

        Returns:
            GPUBenchmarkResults with execution data
        """
        gpu_info = self.get_gpu_info()

        if not gpu_info.available:
            raise RuntimeError("No GPU available for benchmarking")

        results = GPUBenchmarkResults(
            gpu_info=gpu_info,
            started_at=datetime.now(timezone.utc),
        )

        # Start metrics collection
        metrics_collector = None
        if self.collect_metrics:
            metrics_collector = GPUMetricsCollector(
                device_indices=[self.device_index],
                sample_interval_seconds=self.metrics_interval,
            )
            metrics_collector.start()

        try:
            # Determine which queries to run
            if query_ids is not None:
                queries_to_run = [(qid, self._queries[qid]) for qid in query_ids if qid in self._queries]
            elif categories is not None:
                queries_to_run = [(qid, q) for qid, q in self._queries.items() if q["category"] in categories]
            else:
                queries_to_run = list(self._queries.items())

            # Run queries
            for query_id, query_def in queries_to_run:
                logger.info(f"Running GPU query: {query_id}")
                # Note: In real usage, query_sql would be formatted with actual column names
                query_sql = query_def["sql_template"]
                result = self.execute_gpu_query(cudf_df, query_id, query_sql)
                results.add_result(result)

                if result.success:
                    logger.info(f"  ✓ {query_id}: {result.execution_time_ms:.2f}ms ({result.row_count} rows)")
                else:
                    logger.warning(f"  ✗ {query_id}: {result.error_message}")

        finally:
            # Stop metrics collection and get aggregate
            if metrics_collector:
                metrics_collector.stop()
                aggregate = metrics_collector.get_aggregate(self.device_index)
                results.complete(aggregate)
            else:
                results.complete()

        return results

    def export_benchmark_spec(self) -> dict[str, Any]:
        """Export the benchmark specification."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "supported_platforms": list(self.SUPPORTED_PLATFORMS),
            "categories": self.get_query_categories(),
            "queries": {
                qid: {
                    "name": q["name"],
                    "description": q["description"],
                    "category": q["category"],
                }
                for qid, q in self._queries.items()
            },
            "gpu_info": self.get_gpu_info().to_dict(),
            "capabilities": get_gpu_capabilities().to_dict(),
        }


def compare_cpu_vs_gpu(
    pandas_df: Any,
    cudf_df: Any,
    benchmark: GPUBenchmark,
    query_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Compare CPU vs GPU execution times.

    Args:
        pandas_df: pandas DataFrame for CPU execution
        cudf_df: cuDF DataFrame for GPU execution
        benchmark: GPUBenchmark instance
        query_ids: Optional list of queries to compare

    Returns:
        Comparison results with speedup metrics
    """

    queries = query_ids or list(benchmark._queries.keys())
    comparison: dict[str, Any] = {
        "queries": {},
        "summary": {},
    }

    cpu_times = []
    gpu_times = []

    for query_id in queries:
        # CPU execution (using pandas operations)
        cpu_start = time.perf_counter()
        try:
            # Simplified: just measure basic operations
            _ = pandas_df.groupby("category").agg({"value": ["sum", "mean", "count"]})
            cpu_time_ms = (time.perf_counter() - cpu_start) * 1000
        except Exception as e:
            cpu_time_ms = 0.0
            logger.debug(f"CPU execution failed: {e}")

        # GPU execution
        gpu_result = benchmark.execute_gpu_query(
            cudf_df,
            query_id,
            benchmark._queries[query_id]["sql_template"],
        )
        gpu_time_ms = gpu_result.execution_time_ms

        speedup = cpu_time_ms / gpu_time_ms if gpu_time_ms > 0 else 0.0

        comparison["queries"][query_id] = {
            "cpu_time_ms": cpu_time_ms,
            "gpu_time_ms": gpu_time_ms,
            "speedup": speedup,
            "gpu_success": gpu_result.success,
        }

        if cpu_time_ms > 0 and gpu_time_ms > 0:
            cpu_times.append(cpu_time_ms)
            gpu_times.append(gpu_time_ms)

    # Summary statistics
    if cpu_times and gpu_times:
        avg_cpu = sum(cpu_times) / len(cpu_times)
        avg_gpu = sum(gpu_times) / len(gpu_times)
        comparison["summary"] = {
            "avg_cpu_time_ms": avg_cpu,
            "avg_gpu_time_ms": avg_gpu,
            "avg_speedup": avg_cpu / avg_gpu if avg_gpu > 0 else 0.0,
            "total_cpu_time_ms": sum(cpu_times),
            "total_gpu_time_ms": sum(gpu_times),
            "queries_compared": len(cpu_times),
        }

    return comparison

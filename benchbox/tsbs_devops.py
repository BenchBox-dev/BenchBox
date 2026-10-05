"""TSBS DevOps benchmark implementation.

Time Series Benchmark Suite for DevOps monitoring workloads.
Based on https://github.com/timescale/tsbs

This benchmark simulates infrastructure monitoring data:
- CPU metrics (usage, idle, user, system, iowait, etc.)
- Memory metrics (used, free, cached, buffered)
- Disk metrics (reads, writes, IOPS, latency)
- Network metrics (bytes in/out, packets, errors)

Example:
    >>> from benchbox import TSBSDevOps
    >>> from benchbox.platforms.duckdb import DuckDBAdapter
    >>>
    >>> # Create benchmark (SF=1 = 100 hosts, 1 day of data)
    >>> benchmark = TSBSDevOps(scale_factor=1.0)
    >>>
    >>> # Generate synthetic monitoring data
    >>> data_files = benchmark.generate_data()
    >>>
    >>> # Run with platform adapter
    >>> adapter = DuckDBAdapter(database=":memory:")
    >>> adapter.load_benchmark(benchmark)
    >>>
    >>> # Execute queries
    >>> for query_id, query in benchmark.get_queries().items():
    ...     result = adapter.execute_query(query)

Scale factors:
- SF=0.01: 10 hosts, 1 day (~86K rows per metric)
- SF=0.1: 10 hosts, 1 day (~86K rows per metric)
- SF=1.0: 100 hosts, 1 day (~864K rows per metric)
- SF=10: 1000 hosts, 10 days (~86M rows per metric)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tsbs_devops.benchmark import TSBSDevOpsBenchmark


class TSBSDevOps(BaseBenchmark):
    """TSBS DevOps benchmark for infrastructure monitoring workloads.

    Implements Time Series Benchmark Suite for DevOps use cases:
    - CPU, memory, disk, and network monitoring
    - High-frequency metric collection
    - Temporal aggregations and analytics

    Query categories:
    - single-host: Metrics for a specific host over time
    - aggregation: Aggregations across all hosts
    - groupby: Time-bucketed aggregations
    - threshold: Threshold-based alerting queries
    - memory/disk/network: Metric-specific queries
    - combined: Cross-metric correlation queries
    - lastpoint: Most recent value queries
    - tags: Tag-filtered queries
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        num_hosts: Optional[int] = None,
        duration_days: Optional[int] = None,
        interval_seconds: int = 10,
        **kwargs: Any,
    ) -> None:
        """Initialize TSBS DevOps benchmark.

        Args:
            scale_factor: Scale factor (1.0 = 100 hosts, 1 day)
            output_dir: Directory for data files
            num_hosts: Override number of hosts
            duration_days: Override duration in days
            interval_seconds: Measurement interval in seconds
            **kwargs: Additional options:
                - seed: Random seed for reproducibility
                - start_time: Start timestamp
                - verbose: Verbosity level
                - force_regenerate: Force data regeneration

        Raises:
            ValueError: If scale_factor is not positive
            TypeError: If scale_factor is not a number
        """
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        # Initialize the actual implementation using common pattern
        self._initialize_benchmark_implementation(
            TSBSDevOpsBenchmark,
            scale_factor,
            output_dir,
            num_hosts=num_hosts,
            duration_days=duration_days,
            interval_seconds=interval_seconds,
            **kwargs,
        )

    def generate_data(self) -> list[Union[str, Path]]:
        """Generate TSBS DevOps benchmark data.

        Creates synthetic time series data for:
        - tags: Host metadata (hostname, region, datacenter, etc.)
        - cpu: CPU metrics per host at regular intervals
        - mem: Memory metrics per host
        - disk: Disk I/O metrics per host and device
        - net: Network metrics per host and interface

        Returns:
            List of paths to generated data files
        """
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all benchmark queries.

        Args:
            dialect: Target SQL dialect; cloud dialects are translated from the
                DuckDB source

        Returns:
            Dictionary mapping query IDs to query strings
        """
        return self._impl.get_queries(dialect)

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        """Get a specific benchmark query.

        Args:
            query_id: Query identifier (e.g., "single-host-12-hr")
            params: Optional parameter overrides
            **kwargs: Additional arguments

        Returns:
            Parameterized query string

        Raises:
            ValueError: If query_id is unknown
        """
        return self._impl.get_query(query_id, params=params, **kwargs)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the TSBS DevOps schema.

        Returns:
            Schema dictionary with table definitions including:
            - tags: Host metadata
            - cpu: CPU metrics
            - mem: Memory metrics
            - disk: Disk I/O metrics
            - net: Network metrics
        """
        return self._impl.get_schema()

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: Any = None,
    ) -> str:
        """Get SQL to create all benchmark tables.

        Args:
            dialect: SQL dialect (standard, duckdb, clickhouse, timescale)
            tuning_config: Optional tuning configuration

        Returns:
            SQL script for creating tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get benchmark metadata.

        Returns:
            Dictionary with:
            - name: "TSBS DevOps"
            - description: Benchmark description
            - reference: GitHub URL
            - scale_factor: Current scale factor
            - num_hosts: Number of hosts
            - duration_days: Duration in days
            - num_queries: Number of queries
            - query_categories: List of categories
            - tables: List of table names
        """
        return self._impl.get_benchmark_info()

    @property
    def tables(self) -> dict[str, Path]:
        """Get mapping of table names to data file paths.

        Returns:
            Dictionary mapping table names to file paths
        """
        return getattr(self._impl, "tables", {})

    @property
    def num_hosts(self) -> int:
        """Get number of hosts in the dataset."""
        return self._impl.num_hosts

    @property
    def duration_days(self) -> int:
        """Get duration of data in days."""
        return self._impl.duration_days

    @property
    def interval_seconds(self) -> int:
        """Get measurement interval in seconds."""
        return self._impl.interval_seconds

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        """Get metadata for a specific query.

        Args:
            query_id: Query identifier

        Returns:
            Dictionary with query metadata (name, description, category, etc.)
        """
        return self._impl.get_query_info(query_id)

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query IDs for a specific category.

        Available categories:
        - single-host: Metrics for individual hosts
        - aggregation: Aggregations across hosts
        - groupby: Time-bucketed aggregations
        - threshold: Threshold-based queries
        - memory: Memory-specific queries
        - disk: Disk-specific queries
        - network: Network-specific queries
        - combined: Cross-metric queries
        - lastpoint: Most recent value queries
        - tags: Tag-filtered queries

        Args:
            category: Query category name

        Returns:
            List of query IDs in that category
        """
        return self._impl.get_queries_by_category(category)

    def get_generation_stats(self) -> dict:
        """Get statistics about the data generation.

        Returns:
            Dictionary with:
            - num_hosts: Number of hosts
            - duration_days: Duration in days
            - interval_seconds: Measurement interval
            - num_timestamps: Number of time points per host
            - rows: Row counts per table
            - total_rows: Total rows across all tables
        """
        return self._impl.get_generation_stats()

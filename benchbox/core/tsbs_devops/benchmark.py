"""TSBS DevOps benchmark implementation.

Time Series Benchmark Suite for DevOps monitoring workloads.
Simulates infrastructure monitoring data collection and querying.

Based on https://github.com/timescale/tsbs

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tsbs_devops.generator import TSBSDevOpsDataGenerator
from benchbox.core.tsbs_devops.queries import TSBSDevOpsQueryManager
from benchbox.core.tsbs_devops.schema import (
    TSBS_DEVOPS_SCHEMA,
    get_create_tables_sql,
)
from benchbox.utils.compression_mixin import extract_compression_kwargs

if TYPE_CHECKING:
    from benchbox.core.connection import DatabaseConnection


class TSBSDevOpsBenchmark(BaseBenchmark):
    """TSBS DevOps benchmark implementation.

    Implements Time Series Benchmark Suite for DevOps monitoring workloads:
    - CPU metrics (usage, idle, system, user, iowait)
    - Memory metrics (used, free, cached, buffered)
    - Disk metrics (reads, writes, IOPS, latency)
    - Network metrics (bytes, packets, errors)

    The benchmark supports various query patterns:
    - Single host queries over time ranges
    - Aggregations across all hosts
    - Grouped aggregations by time buckets
    - Threshold-based filtering
    - Cross-metric joins

    Usage:
        >>> from benchbox.core.tsbs_devops import TSBSDevOpsBenchmark
        >>> from benchbox.platforms.duckdb import DuckDBAdapter
        >>>
        >>> # Create benchmark (SF=1 = 100 hosts, 2 days)
        >>> benchmark = TSBSDevOpsBenchmark(scale_factor=1.0)
        >>>
        >>> # Generate data
        >>> data_files = benchmark.generate_data()
        >>>
        >>> # Get queries
        >>> queries = benchmark.get_queries()
        >>>
        >>> # Run with platform adapter
        >>> adapter = DuckDBAdapter(database=":memory:")
        >>> adapter.load_benchmark(benchmark)
        >>> results = adapter.run_benchmark(benchmark)

    Attributes:
        scale_factor: Scale factor controlling data size
        num_hosts: Number of simulated hosts
        duration_days: Duration of time series data
        interval_seconds: Measurement interval
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        num_hosts: int | None = None,
        duration_days: int | None = None,
        interval_seconds: int = 10,
        start_time: datetime | None = None,
        seed: int | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_regenerate: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize TSBS DevOps benchmark.

        Args:
            scale_factor: Scale factor (1.0 = 100 hosts, 2 days)
            output_dir: Directory for data files
            num_hosts: Override number of hosts
            duration_days: Override duration in days
            interval_seconds: Measurement interval in seconds
            start_time: Start timestamp for data
            seed: Random seed for reproducibility
            verbose: Verbosity level
            quiet: Suppress output
            force_regenerate: Force data regeneration
            **kwargs: Additional options
        """
        resolved_output_dir = (
            Path(output_dir)
            if output_dir
            else Path.cwd() / "benchmark_runs" / "datagen" / f"tsbs_devops_{scale_factor}"
        )
        super().__init__(
            scale_factor=scale_factor,
            output_dir=resolved_output_dir,
            verbose=verbose,
            quiet=quiet,
            force_regenerate=force_regenerate,
            **kwargs,
        )
        self.seed = seed
        self.csv_has_header: bool = True

        # Benchmark metadata
        self._name = "TSBS DevOps"
        self._version = "1.0"
        self._description = "Time Series Benchmark Suite for DevOps monitoring workloads"

        self.logger = logging.getLogger("benchbox.core.tsbs_devops.benchmark")

        # Create data generator
        compression_kwargs = extract_compression_kwargs(kwargs)
        self.data_generator = TSBSDevOpsDataGenerator(
            scale_factor=scale_factor,
            output_dir=self.output_dir,
            num_hosts=num_hosts,
            duration_days=duration_days,
            interval_seconds=interval_seconds,
            start_time=start_time,
            seed=seed,
            verbose=verbose,
            quiet=quiet,
            force_regenerate=force_regenerate,
            **compression_kwargs,
        )

        # Store configuration
        self.num_hosts = self.data_generator.num_hosts
        self.duration_days = self.data_generator.duration_days
        self.interval_seconds = self.data_generator.interval_seconds
        self.start_time = self.data_generator.start_time

        # Initialize query manager
        self.query_manager = TSBSDevOpsQueryManager(
            num_hosts=self.num_hosts,
            start_time=self.start_time,
            duration_days=self.duration_days,
            seed=seed,
        )

        # Track generated table files
        self.tables: dict[str, Path] = {}

    def generate_data(self) -> list[Union[str, Path]]:
        """Generate TSBS DevOps benchmark data.

        Returns:
            List of paths to generated data files
        """
        self.log_verbose(f"Generating TSBS DevOps data (SF={self.scale_factor})")

        self.tables = self.data_generator.generate()

        if self.verbose_enabled:
            stats = self.data_generator.get_generation_stats()
            self.logger.info(f"Generated {stats['total_rows']} total rows")

        return list(self.tables.values())

    def get_queries(self, dialect: str | None = None) -> dict[str, str]:
        """Get all benchmark queries.

        Args:
            dialect: Target SQL dialect (not used - queries are standard SQL)

        Returns:
            Dictionary mapping query IDs to query strings
        """
        return self.query_manager.get_queries()

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: dict[str, Any] | None = None,
        **kwargs,
    ) -> str:
        """Get a specific benchmark query.

        Args:
            query_id: Query identifier (e.g., "single-host-12-hr", "cpu-max-all-1-hr")
            params: Optional parameter overrides
            **kwargs: Additional arguments

        Returns:
            Parameterized query string

        Raises:
            ValueError: If query_id is unknown
        """
        query_key = str(query_id)
        return self.query_manager.get_query(query_key, params)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the TSBS DevOps schema.

        Returns:
            Schema dictionary with table definitions
        """
        return TSBS_DEVOPS_SCHEMA

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        include_constraints: bool = True,
        time_partitioning: bool = False,
        tuning_config: Any = None,
    ) -> str:
        """Get SQL to create all benchmark tables.

        Args:
            dialect: SQL dialect (standard, duckdb, clickhouse, timescale)
            include_constraints: Include PRIMARY KEY constraints
            time_partitioning: Add time-based partitioning
            tuning_config: Optional tuning configuration (not used)

        Returns:
            SQL script for creating tables
        """
        return get_create_tables_sql(
            dialect=dialect,
            include_constraints=include_constraints,
            time_partitioning=time_partitioning,
        )

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get benchmark metadata.

        Returns:
            Dictionary with benchmark information
        """
        return {
            "name": "TSBS DevOps",
            "description": "Time Series Benchmark Suite for DevOps monitoring workloads",
            "reference": "https://github.com/timescale/tsbs",
            "version": "1.0",
            "scale_factor": self.scale_factor,
            "num_hosts": self.num_hosts,
            "duration_days": self.duration_days,
            "interval_seconds": self.interval_seconds,
            "num_queries": self.query_manager.get_query_count(),
            "query_categories": self.query_manager.get_categories(),
            "tables": ["tags", "cpu", "mem", "disk", "net"],
            "metrics": {
                "cpu": "CPU usage metrics (user, system, idle, iowait, etc.)",
                "mem": "Memory metrics (used, free, cached, buffered)",
                "disk": "Disk I/O metrics (reads, writes, IOPS, latency)",
                "net": "Network metrics (bytes, packets, errors)",
            },
        }

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        """Get metadata for a specific query.

        Args:
            query_id: Query identifier

        Returns:
            Query metadata dictionary
        """
        return self.query_manager.get_query_info(query_id)

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query IDs for a specific category.

        Args:
            category: Query category (single-host, aggregation, groupby, etc.)

        Returns:
            List of query IDs
        """
        return self.query_manager.get_queries_by_category(category)

    def get_generation_stats(self) -> dict:
        """Get statistics about data generation.

        Returns:
            Statistics dictionary
        """
        return self.data_generator.get_generation_stats()

    def _load_data(self, connection: DatabaseConnection) -> None:
        """Load TSBS DevOps data into the database.

        This method loads the generated TSBS data files (.csv format) into the database
        using a simple, database-agnostic approach with INSERT statements.

        Args:
            connection: DatabaseConnection wrapper for database operations

        Raises:
            ValueError: If data hasn't been generated yet
            Exception: If data loading fails
        """
        logger = logging.getLogger(__name__)

        # Check if data has been generated
        if not self.tables:
            raise ValueError("No data has been generated. Call generate_data() first.")

        logger.info("Loading TSBS DevOps data into database...")

        # Create database schema first
        try:
            schema_sql = self.get_create_tables_sql(dialect="standard", include_constraints=False)
            # Handle databases that don't support multiple statements at once
            if ";" in schema_sql:
                statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
                for statement in statements:
                    connection.execute(statement)
            else:
                connection.execute(schema_sql)
            connection.commit()
            logger.info("Created TSBS DevOps database schema")
        except Exception as e:
            logger.error(f"Failed to create database schema: {e}")
            raise

        # Load data for each table in correct order (tags first for foreign key references)
        table_order = ["tags", "cpu", "mem", "disk", "net"]
        total_rows = 0
        loaded_tables = 0

        for table_name in table_order:
            if table_name not in self.tables:
                logger.warning(f"Skipping {table_name} - no data file found")
                continue

            data_file = Path(self.tables[table_name])
            if not data_file.exists():
                logger.warning(f"Skipping {table_name} - data file does not exist: {data_file}")
                continue

            try:
                logger.info(f"Loading data for {table_name}...")
                rows_loaded = self._load_table_data(connection, table_name, data_file)

                total_rows += rows_loaded
                loaded_tables += 1
                logger.info(f"Loaded {rows_loaded:,} rows into {table_name}")

            except Exception as e:
                logger.error(f"Failed to load data for {table_name}: {e}")
                raise

        # Commit all changes
        try:
            connection.commit()
            logger.info(f"Successfully loaded {total_rows:,} total rows across {loaded_tables} tables")
        except Exception as e:
            logger.error(f"Failed to commit data loading transaction: {e}")
            raise

    def _load_table_data(self, connection: DatabaseConnection, table_name: str, data_file: Path) -> int:
        """Load data into a database table using INSERT statements.

        Args:
            connection: DatabaseConnection wrapper
            table_name: Name of the table to load data into
            data_file: Path to the CSV data file

        Returns:
            Number of rows loaded
        """
        # Get table schema to determine column count
        table_schema = TSBS_DEVOPS_SCHEMA[table_name]
        column_names = list(table_schema["columns"].keys())
        num_columns = len(column_names)

        # Prepare insert statement with parameter placeholders
        placeholders = ", ".join(["?" for _ in range(num_columns)])
        insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"

        rows_loaded = 0

        with open(data_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            # Skip header row
            next(reader, None)

            for row in reader:
                # Validate row has correct number of columns
                if len(row) != num_columns:
                    continue  # Skip malformed rows

                # Execute individual INSERT
                connection.execute(insert_sql, row)
                rows_loaded += 1

        return rows_loaded


# ---------------------------------------------------------------------------
# Register benchmark-specific CLI option specs
# ---------------------------------------------------------------------------

from benchbox.cli.benchmark_hooks import (  # noqa: E402
    BenchmarkHookRegistry,
    BenchmarkOptionSpec,
    parse_datetime,
    parse_int,
)

BenchmarkHookRegistry.register_option_specs(
    "tsbs_devops",
    BenchmarkOptionSpec(
        name="num_hosts",
        parser=parse_int,
        help="Number of simulated hosts",
        aliases=("num-hosts",),
    ),
    BenchmarkOptionSpec(
        name="duration_days",
        parser=parse_int,
        help="Duration in days for data generation",
        aliases=("duration-days",),
    ),
    BenchmarkOptionSpec(
        name="interval_seconds",
        parser=parse_int,
        default=10,
        help="Measurement interval in seconds",
        aliases=("interval-seconds",),
    ),
    BenchmarkOptionSpec(
        name="start_time",
        parser=parse_datetime,
        help="Start time for data generation (ISO format)",
        aliases=("start-time",),
    ),
    BenchmarkOptionSpec(
        name="seed",
        parser=parse_int,
        help="Random seed for reproducibility",
    ),
    BenchmarkOptionSpec(
        name="force_regenerate",
        parser=lambda v: v.strip().lower() in ("true", "1", "yes"),
        help="Force data regeneration",
        aliases=("force-regenerate",),
    ),
)

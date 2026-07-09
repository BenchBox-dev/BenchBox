"""Primary adapter for InfluxDB platforms.

InfluxDB 3.x is a time series database built on Apache Arrow, DataFusion, and Parquet.
It supports native SQL queries via FlightSQL protocol, making it suitable for
benchmarking time series workloads.

Key Features:
- Native SQL support via FlightSQL
- Apache Arrow data format
- Optimized for time series data
- High-cardinality support

Deployment Modes:
- Core/OSS: Self-hosted open source (April 2025 GA)
- Cloud: Managed service (Serverless, Dedicated, Clustered)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base import DriverIsolationCapability, PlatformAdapter
from benchbox.utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
    get_package_install_message,
)

from ._dependencies import INFLUXDB_AVAILABLE
from .metadata import InfluxDBMetadataMixin
from .setup import InfluxDBSetupMixin

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
    )

logger = logging.getLogger(__name__)


class InfluxDBAdapter(
    InfluxDBMetadataMixin,
    InfluxDBSetupMixin,
    PlatformAdapter,
):
    """InfluxDB platform adapter for time series benchmarking.

    Supports InfluxDB 3.x via FlightSQL protocol for SQL-based benchmarking.
    Optimized for time series workloads like TSBS DevOps.

    Deployment modes:
    - **InfluxDB Core (OSS)**: Self-hosted, open source, Docker-based
    - **InfluxDB Cloud**: Managed service with token authentication

    Example usage:
        >>> from benchbox.platforms.influxdb import InfluxDBAdapter
        >>>
        >>> # Cloud mode
        >>> adapter = InfluxDBAdapter(
        ...     host="us-east-1-1.aws.cloud2.influxdata.com",
        ...     token="your-token",
        ...     org="your-org",
        ...     database="benchmarks",
        ...     mode="cloud",
        ... )
        >>>
        >>> # Core mode (local Docker)
        >>> adapter = InfluxDBAdapter(
        ...     host="localhost",
        ...     port=8086,
        ...     token="your-token",

        ...     database="benchmarks",
        ...     mode="core",
        ...     ssl=False,
        ... )
    """

    plan_capture_phase_eligible = True

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    def __init__(self, **config):
        """Initialize InfluxDB adapter.

        Args:
            **config: Configuration options including:
                - host: InfluxDB server hostname
                - port: Server port (default: 8086)
                - token: Authentication token (or INFLUXDB_TOKEN env var)
                - org: Organization name
                - database: Database (bucket) name
                - ssl: Use SSL/TLS (default: True)
                - mode: Deployment mode ('core' or 'cloud')

        Raises:
            ImportError: If InfluxDB client dependencies are not available
        """
        super().__init__(**config)

        # Check dependencies
        if not INFLUXDB_AVAILABLE:
            available, missing = check_platform_dependencies("influxdb")
            if not available:
                error_msg = get_dependency_error_message("influxdb", missing)
                raise ImportError(error_msg)

        self._dialect = "influxdb"

        # Get token from config or environment
        token = config.get("token") or os.environ.get("INFLUXDB_TOKEN")
        config["token"] = token

        # Setup connection parameters
        self._setup_connection_params(config)

        # Validate mode
        if self.mode not in ("core", "cloud"):
            raise ValueError(f"Invalid InfluxDB mode '{self.mode}'. Must be 'core' or 'cloud'.")

        # Log configuration
        if self.mode == "core":
            protocol = "http" if not self.ssl else "https"
            self.logger.info(f"InfluxDB Core mode: {protocol}://{self.host}:{self.port}")
        else:
            self.logger.info(f"InfluxDB Cloud mode: {self.host}")

    def get_table_row_count(self, connection: Any, table: str) -> int:
        """Get row count for a table.

        Args:
            connection: Database connection
            table: Name of the table (measurement in InfluxDB terms)

        Returns:
            Number of rows in the table
        """
        query = f'SELECT COUNT(*) FROM "{table}"'
        result = connection.execute(query)
        if result and len(result) > 0:
            return result[0][0] if result[0][0] else 0
        return 0

    def get_tables(self, connection: Any = None) -> list[str]:
        """Get list of tables (measurements) in the database.

        Args:
            connection: Optional existing connection

        Returns:
            List of table names
        """
        if connection is None:
            connection = self.connection
        # InfluxDB 3.x uses system.tables for metadata
        query = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'iox'"
        try:
            result = connection.execute(query)
            return [row[0] for row in result if row[0]]
        except (RuntimeError, ConnectionError):
            # Fallback for different InfluxDB versions or connection issues
            return []

    def table_exists(self, table_name: str, connection: Any = None) -> bool:
        """Check if a table (measurement) exists.

        Args:
            table_name: Name of the table
            connection: Optional existing connection

        Returns:
            True if table exists
        """
        tables = self.get_tables(connection)
        return table_name in tables

    def drop_table(self, table_name: str, connection: Any = None) -> None:
        """Drop a table (not supported in InfluxDB 3.x Core).

        InfluxDB 3.x Core/OSS does not support DELETE operations.
        Data must be managed via retention policies or the InfluxDB API.

        Args:
            table_name: Name of the table
            connection: Optional existing connection
        """
        self.logger.warning(
            f"InfluxDB Core does not support DROP TABLE. Table '{table_name}' cannot be deleted via SQL."
        )

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create database schema for the benchmark.

        InfluxDB 3.x auto-creates measurements (tables) from write operations.
        Explicit CREATE TABLE is not typically needed for time series data.

        Args:
            benchmark: Benchmark instance with schema definitions
            connection: Database connection

        Returns:
            Time taken to create schema (0.0 for InfluxDB since schema is implicit)
        """
        self.logger.info(
            "InfluxDB auto-creates tables from write operations. Explicit schema creation is not required."
        )
        return 0.0

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data into InfluxDB using Line Protocol.

        Converts CSV/Parquet data files to InfluxDB Line Protocol format and
        writes to the database using the influxdb3-python client.

        For TSBS DevOps data:
        - Metric tables (cpu, mem, disk, net) are loaded as measurements
        - hostname is used as a tag (indexed for efficient filtering)
        - device/interface are additional tags for disk/net tables
        - Numeric columns become fields
        - time column provides nanosecond timestamps

        Args:
            benchmark: Benchmark instance
            connection: Database connection with write capability
            data_dir: Directory containing CSV/Parquet data files

        Returns:
            Tuple of (row_counts, load_time, load_metadata)
        """
        import time

        from ._dependencies import INFLUXDB3_AVAILABLE

        if not INFLUXDB3_AVAILABLE:
            self.logger.warning(
                "Line Protocol writes require influxdb3-python. Data loading skipped. "
                + get_package_install_message("influxdb3-python", "")
            )
            return {}, 0.0, {"skipped": True, "reason": "influxdb3-python not available"}

        # Check if connection supports writes
        if not hasattr(connection, "write_batch"):
            self.logger.warning(
                "Connection does not support batch writes. "
                "Data loading requires InfluxDBConnection with influxdb3-python client."
            )
            return {}, 0.0, {"skipped": True, "reason": "write not supported"}

        # TSBS DevOps table configurations for Line Protocol
        tsbs_tables = self._tsbs_table_configs()

        row_counts: dict[str, int] = {}
        total_time = 0.0
        load_metadata: dict[str, Any] = {"tables_loaded": [], "batch_size": 10000}

        self.logger.info(f"Loading TSBS DevOps data from {data_dir}")

        for table_name, config in tsbs_tables.items():
            csv_path = data_dir / f"{table_name}.csv"
            if not csv_path.exists():
                self.logger.debug(f"No data file found for {table_name}, skipping")
                continue

            self.logger.info(f"Loading {table_name} from {csv_path}")
            table_start = time.perf_counter()

            try:
                records = self._read_tsbs_csv(csv_path, config)

                if records:
                    count = connection.write_batch(
                        measurement=table_name,
                        records=records,
                        tag_columns=config["tags"],
                        field_columns=config["fields"],
                        timestamp_column="time",
                        precision="ns",
                        batch_size=10000,
                    )
                    row_counts[table_name] = count
                    load_metadata["tables_loaded"].append(table_name)
                    self.logger.info(f"Loaded {count:,} rows into {table_name}")

            except Exception as e:
                self.logger.error(f"Failed to load {table_name}: {e}")
                row_counts[table_name] = 0

            table_time = time.perf_counter() - table_start
            total_time += table_time
            self.logger.debug(f"{table_name} load time: {table_time:.2f}s")

        load_metadata["total_rows"] = sum(row_counts.values())
        self.logger.info(f"Data loading complete: {load_metadata['total_rows']:,} total rows in {total_time:.2f}s")

        return row_counts, total_time, load_metadata

    @staticmethod
    def _tsbs_table_configs() -> dict[str, dict[str, Any]]:
        """Return TSBS DevOps table configurations for Line Protocol."""
        return {
            "tags": {
                "tags": ["hostname"],
                "fields": [
                    "region",
                    "datacenter",
                    "rack",
                    "os",
                    "arch",
                    "team",
                    "service",
                    "service_version",
                    "service_environment",
                ],
                "timestamp": None,
            },
            "cpu": {
                "tags": ["hostname"],
                "fields": [
                    "usage_user",
                    "usage_system",
                    "usage_idle",
                    "usage_nice",
                    "usage_iowait",
                    "usage_irq",
                    "usage_softirq",
                    "usage_steal",
                    "usage_guest",
                    "usage_guest_nice",
                ],
                "timestamp": "time",
            },
            "mem": {
                "tags": ["hostname"],
                "fields": [
                    "total",
                    "available",
                    "used",
                    "free",
                    "cached",
                    "buffered",
                    "used_percent",
                    "available_percent",
                ],
                "timestamp": "time",
            },
            "disk": {
                "tags": ["hostname", "device"],
                "fields": [
                    "reads_completed",
                    "reads_merged",
                    "sectors_read",
                    "read_time_ms",
                    "writes_completed",
                    "writes_merged",
                    "sectors_written",
                    "write_time_ms",
                    "io_in_progress",
                    "io_time_ms",
                    "weighted_io_time_ms",
                ],
                "timestamp": "time",
            },
            "net": {
                "tags": ["hostname", "interface"],
                "fields": [
                    "bytes_recv",
                    "bytes_sent",
                    "packets_recv",
                    "packets_sent",
                    "err_in",
                    "err_out",
                    "drop_in",
                    "drop_out",
                ],
                "timestamp": "time",
            },
        }

    # Fields that should always remain as floats (not converted to int)
    _FLOAT_ONLY_FIELDS = frozenset(
        {
            "usage_user",
            "usage_system",
            "usage_idle",
            "usage_nice",
            "usage_iowait",
            "usage_irq",
            "usage_softirq",
            "usage_steal",
            "usage_guest",
            "usage_guest_nice",
            "used_percent",
            "available_percent",
        }
    )

    def _read_tsbs_csv(self, csv_path: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Read a TSBS DevOps CSV file and convert rows to records."""
        import csv

        records: list[dict[str, Any]] = []
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                record: dict[str, Any] = {}

                if config["timestamp"] in row:
                    record["time"] = self._parse_timestamp(row[config["timestamp"]])

                for tag in config["tags"]:
                    if tag in row:
                        record[tag] = row[tag]

                for field in config["fields"]:
                    if field in row and row[field]:
                        parsed = self._parse_field_value(field, row[field])
                        if parsed is not None:
                            record[field] = parsed

                records.append(record)
        return records

    @staticmethod
    def _parse_timestamp(ts_str: str):
        """Parse a timestamp string to datetime, trying ISO then Unix format."""
        from datetime import datetime

        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.fromtimestamp(float(ts_str))
            except (ValueError, OSError):
                return None

    def _parse_field_value(self, field: str, raw: str):
        """Parse a field value string to int or float as appropriate."""
        try:
            value = float(raw)
            if value.is_integer() and field not in self._FLOAT_ONLY_FIELDS:
                return int(value)
            return value
        except ValueError:
            self.logger.debug(f"Skipping invalid value for field '{field}': {raw}")
            return None

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply platform-specific optimizations for the benchmark type.

        InfluxDB 3.x is auto-tuned for time series workloads. No explicit
        configuration is typically needed.

        Args:
            connection: Database connection
            benchmark_type: Type of benchmark (e.g., 'tsbs_devops')
        """
        self.logger.debug(f"Configuring InfluxDB for benchmark type: {benchmark_type}")
        # InfluxDB is auto-optimized for time series - no explicit configuration needed

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply platform-specific optimizations.

        InfluxDB 3.x manages its own optimizations. This method is a no-op.

        Args:
            platform_config: Platform optimization configuration
            connection: Database connection
        """
        self.logger.debug("InfluxDB manages its own optimizations - skipping explicit optimization")

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configuration.

        InfluxDB 3.x is a time series database and doesn't support traditional
        relational constraints like primary keys or foreign keys.

        Args:
            primary_key_config: Primary key configuration (ignored)
            foreign_key_config: Foreign key configuration (ignored)
            connection: Database connection
        """
        self.logger.debug("InfluxDB is a time series database - relational constraints not applicable")

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        iteration: int = 1,
        stream_id: int | None = None,
    ) -> tuple[float, int, dict[str, Any] | None]:
        """Execute a benchmark query and return timing and results.

        Args:
            connection: Database connection
            query: SQL query string
            query_id: Query identifier
            iteration: Iteration number
            stream_id: Optional stream ID for throughput tests

        Returns:
            Tuple of (execution_time, row_count, query_plan)
        """
        import time

        start_time = time.perf_counter()

        try:
            result = connection.execute(query)
            row_count = len(result) if result else 0
        except Exception as e:
            self.logger.error(f"Query {query_id} failed: {e}")
            raise

        execution_time = time.perf_counter() - start_time

        return execution_time, row_count, None


__all__ = ["InfluxDBAdapter"]

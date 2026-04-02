"""TimescaleDB platform adapter for BenchBox benchmarking.

Extends PostgreSQL adapter with TimescaleDB-specific functionality:
- Automatic hypertable creation for time-series tables
- Compression policies for historical data
- Chunk interval configuration
- TimescaleDB-optimized query execution

Deployment modes:
- self-hosted: Self-hosted TimescaleDB server (default)
- cloud: TigerData managed service (requires SSL)

TimescaleDB is a PostgreSQL extension that transforms PostgreSQL into a
time-series database with automatic time-based partitioning (hypertables),
compression, and continuous aggregates.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time

from .base import DriverIsolationCapability
from .postgresql import POSTGRES_DIALECT, PostgreSQLAdapter, _add_postgres_compatible_arguments

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2 import sql as psql
except ImportError:
    psycopg2 = None
    psql = None  # type: ignore[assignment]


# Valid PostgreSQL interval pattern: number + unit (e.g., "1 day", "7 days", "2 weeks")
# Supports: microsecond(s), millisecond(s), second(s), minute(s), hour(s), day(s), week(s), month(s), year(s)
_INTERVAL_PATTERN = re.compile(
    r"^\s*\d+\s+"
    r"(microseconds?|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?)"
    r"\s*$",
    re.IGNORECASE,
)


class TimescaleDBAdapter(PostgreSQLAdapter):
    """TimescaleDB platform adapter with hypertable and compression support.

    Extends PostgreSQLAdapter with TimescaleDB-specific features:
    - Automatic hypertable creation for tables with time columns
    - Compression policies for historical data optimization
    - Configurable chunk intervals for time-based partitioning

    Requires PostgreSQL 12+ with TimescaleDB 2.x extension installed.
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    @property
    def platform_name(self) -> str:
        return "TimescaleDB"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for TimescaleDB (PostgreSQL-compatible)."""
        return POSTGRES_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add TimescaleDB-specific CLI arguments."""
        if not hasattr(parser, "add_argument"):
            return
        try:
            _add_postgres_compatible_arguments(
                parser,
                prefix="timescale",
                platform_label="TimescaleDB",
            )
            # TimescaleDB-specific options
            parser.add_argument(
                "--timescale-chunk-interval",
                dest="chunk_interval",
                default="1 day",
                help="Chunk time interval for hypertables (e.g., '1 day', '1 week')",
            )
            parser.add_argument(
                "--timescale-compression",
                dest="compression_enabled",
                action="store_true",
                help="Enable compression on hypertables",
            )
            parser.add_argument(
                "--timescale-compression-after",
                dest="compression_after",
                default="7 days",
                help="Compress chunks older than this interval (e.g., '7 days')",
            )
        except Exception:
            pass

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> TimescaleDBAdapter:
        """Create TimescaleDB adapter from unified configuration."""
        adapter_config = {}

        # Connection parameters (inherited from PostgreSQL)
        adapter_config["host"] = config.get("host", "localhost")
        adapter_config["port"] = config.get("port", 5432)
        adapter_config["username"] = config.get("username", "postgres")
        adapter_config["password"] = config.get("password")
        adapter_config["schema"] = config.get("schema", "public")
        adapter_config["sslmode"] = config.get("sslmode", "prefer")

        # Database name - use provided or generate from benchmark config
        if config.get("database"):
            adapter_config["database"] = config["database"]
        elif config.get("benchmark") and config.get("scale_factor") is not None:
            from benchbox.utils.scale_factor import format_benchmark_name

            benchmark_name = format_benchmark_name(config["benchmark"], config["scale_factor"])
            adapter_config["database"] = f"benchbox_{benchmark_name}".lower().replace("-", "_")
        else:
            adapter_config["database"] = "benchbox"

        # Admin database for CREATE/DROP DATABASE operations
        adapter_config["admin_database"] = config.get("admin_database", "postgres")

        # Performance settings (inherited from PostgreSQL)
        adapter_config["work_mem"] = config.get("work_mem", "256MB")
        adapter_config["maintenance_work_mem"] = config.get("maintenance_work_mem", "512MB")
        adapter_config["effective_cache_size"] = config.get("effective_cache_size", "1GB")
        adapter_config["max_parallel_workers_per_gather"] = config.get("max_parallel_workers_per_gather", 2)

        # Connection pool settings
        adapter_config["connect_timeout"] = config.get("connect_timeout", 10)
        adapter_config["statement_timeout"] = config.get("statement_timeout", 0)

        # TimescaleDB-specific settings
        adapter_config["chunk_interval"] = config.get("chunk_interval", "1 day")
        adapter_config["compression_enabled"] = config.get("compression_enabled", False)
        adapter_config["compression_after"] = config.get("compression_after", "7 days")

        # Force recreate
        adapter_config["force_recreate"] = config.get("force", False)

        # Pass through other config
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def __init__(self, **config):
        # Determine deployment mode with priority:
        # 1. deployment_mode (from factory via colon syntax: timescaledb:cloud)
        # 2. Default to 'self-hosted' (standard self-hosted TimescaleDB)
        deployment_mode = config.get("deployment_mode", "self-hosted")
        self.deployment_mode = deployment_mode.lower()

        # Validate deployment mode
        valid_modes = {"self-hosted", "cloud"}
        if self.deployment_mode not in valid_modes:
            raise ValueError(
                f"Invalid TimescaleDB deployment mode '{self.deployment_mode}'. "
                f"Valid modes: {', '.join(sorted(valid_modes))}"
            )

        # Configure for cloud mode if specified
        if self.deployment_mode == "cloud":
            self._configure_cloud_mode(config)

        # Set enable_timescale=True for parent class
        config["enable_timescale"] = True
        super().__init__(**config)

        # TimescaleDB-specific configuration with validation
        self.chunk_interval = self._validate_interval(config.get("chunk_interval", "1 day"), "chunk_interval")
        self.compression_enabled = config.get("compression_enabled", False)
        self.compression_after = self._validate_interval(config.get("compression_after", "7 days"), "compression_after")

        # Track which tables are hypertables
        self._hypertables: set[str] = set()

        # Set skip_database_management for cloud mode (can't DROP/CREATE managed databases)
        if self.deployment_mode == "cloud":
            self.skip_database_management = config.get("skip_database_management", True)
            logger.info(f"TigerData adapter initialized for host: {config.get('host')}")

    def _configure_cloud_mode(self, config: dict) -> None:
        """Configure adapter for TigerData cloud mode.

        TigerData uses SSL and has specific connection requirements.
        Credentials can be provided via:
        - Config parameters: host, password, username, port, database
        - Environment variables: TIGERDATA_HOST, TIGERDATA_PASSWORD, etc.
          (TIMESCALE_* variables are supported as backward-compatible fallback)
        - Service URL: TIGERDATA_SERVICE_URL (or TIMESCALE_SERVICE_URL fallback)
          (postgres://user:pass@host:port/db)
        """
        # Check for service URL first (most convenient)
        service_url = (
            config.get("service_url")
            or os.environ.get("TIGERDATA_SERVICE_URL")
            or os.environ.get("TIMESCALE_SERVICE_URL")
        )
        if service_url:
            self._parse_service_url(config, service_url)
            return

        # Otherwise use individual parameters
        config["host"] = config.get("host") or os.environ.get("TIGERDATA_HOST") or os.environ.get("TIMESCALE_HOST")
        config["password"] = (
            config.get("password")
            or os.environ.get("TIGERDATA_PASSWORD")
            or os.environ.get("TIMESCALE_PASSWORD")
            or os.environ.get("PGPASSWORD")
        )
        # For cloud mode, default to "tsdbadmin" - don't use PGUSER as it may be set to
        # something else (e.g., "postgres") by system PostgreSQL installations
        config["username"] = (
            config.get("username")
            or os.environ.get("TIGERDATA_USER")
            or os.environ.get("TIMESCALE_USER")
            or "tsdbadmin"
        )
        config["port"] = config.get("port") or int(
            os.environ.get("TIGERDATA_PORT") or os.environ.get("TIMESCALE_PORT") or os.environ.get("PGPORT", "5432")
        )
        config["database"] = (
            config.get("database")
            or os.environ.get("TIGERDATA_DATABASE")
            or os.environ.get("TIMESCALE_DATABASE")
            or os.environ.get("PGDATABASE", "tsdb")
        )

        # Validate required credentials
        if not config.get("host"):
            raise ValueError(
                "TigerData requires host configuration.\n"
                "Provide via --platform-option host=<hostname> or "
                "TIGERDATA_HOST environment variable "
                "(TIMESCALE_HOST supported as fallback), or use "
                "TIGERDATA_SERVICE_URL (TIMESCALE_SERVICE_URL fallback).\n"
                "Example: abc123.rc8ft3nbrw.tsdb.cloud.timescale.com"
            )
        if not config.get("password"):
            raise ValueError(
                "TigerData requires password authentication.\n"
                "Provide via --platform-option password=<password> or "
                "TIGERDATA_PASSWORD/PGPASSWORD environment variable "
                "(TIMESCALE_PASSWORD supported as fallback)."
            )

        # Cloud always requires SSL
        config["sslmode"] = config.get("sslmode", "require")

        # For cloud, disable database recreation (we can't drop managed databases)
        # Users should create a separate database for benchmarks if needed
        config["force_recreate"] = False
        config["skip_database_management"] = True  # New flag to skip DROP/CREATE database

    def _parse_service_url(self, config: dict, service_url: str) -> None:
        """Parse TigerData service URL into connection parameters.

        Service URL format: postgres://user:pass@host:port/database?sslmode=require
        """
        import urllib.parse

        try:
            parsed = urllib.parse.urlparse(service_url)

            if parsed.scheme not in ("postgres", "postgresql"):
                raise ValueError(f"Unsupported scheme '{parsed.scheme}'. Expected 'postgres://' or 'postgresql://'.")

            config["host"] = parsed.hostname
            config["port"] = parsed.port or 5432
            config["username"] = parsed.username or "tsdbadmin"
            config["password"] = urllib.parse.unquote(parsed.password) if parsed.password else None
            config["database"] = parsed.path.lstrip("/") or "tsdb"

            # Parse query parameters for sslmode
            query_params = urllib.parse.parse_qs(parsed.query)
            if "sslmode" in query_params:
                config["sslmode"] = query_params["sslmode"][0]
            else:
                config["sslmode"] = "require"  # Default for cloud

            logger.debug(
                f"Parsed service URL: host={config['host']}, port={config['port']}, database={config['database']}"
            )

        except Exception as e:
            raise ValueError(f"Invalid TIGERDATA_SERVICE_URL (or TIMESCALE_SERVICE_URL) format: {e}")

    @staticmethod
    def _validate_interval(value: str, param_name: str) -> str:
        """Validate that a value is a valid PostgreSQL interval format.

        Args:
            value: The interval string to validate (e.g., "1 day", "7 days")
            param_name: The parameter name for error messages

        Returns:
            The validated interval string (stripped of leading/trailing whitespace)

        Raises:
            ValueError: If the interval format is invalid
        """
        if not isinstance(value, str):
            raise ValueError(f"{param_name} must be a string, got {type(value).__name__}")

        value = value.strip()
        if not _INTERVAL_PATTERN.match(value):
            raise ValueError(
                f"Invalid {param_name} format: '{value}'. "
                f"Expected format: '<number> <unit>' where unit is one of: "
                f"microsecond(s), millisecond(s), second(s), minute(s), hour(s), "
                f"day(s), week(s), month(s), year(s). Examples: '1 day', '7 days', '2 weeks'."
            )
        return value

    def create_connection(self, **connection_config) -> Any:
        """Create TimescaleDB connection and verify extension is available."""
        conn = super().create_connection(**connection_config)

        # Verify TimescaleDB extension is installed
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            result = cursor.fetchone()
            if result:
                self.logger.info(f"TimescaleDB extension version: {result[0]}")
            else:
                # Try to create the extension
                self.logger.info("TimescaleDB extension not found, attempting to create...")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
                conn.commit()
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
                result = cursor.fetchone()
                if result:
                    self.logger.info(f"Created TimescaleDB extension version: {result[0]}")
                else:
                    self.logger.warning(
                        "TimescaleDB extension not available. "
                        "Install TimescaleDB or use the postgresql platform instead."
                    )
        except Exception as e:
            self.logger.warning(f"Could not verify TimescaleDB extension: {e}")
        finally:
            cursor.close()

        return conn

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema with automatic hypertable conversion for time-series tables."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get schema SQL and translate to PostgreSQL dialect
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

        self.log_very_verbose(f"Executing schema creation script ({len(schema_sql)} characters)")

        cursor = connection.cursor()

        # Execute each statement separately
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        tables_created = []

        for stmt in statements:
            try:
                cursor.execute(stmt)
                # Track created tables for potential hypertable conversion
                stmt_upper = stmt.upper()
                if "CREATE TABLE" in stmt_upper:
                    # Extract table name
                    match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)", stmt, re.IGNORECASE)
                    if match:
                        table_name = match.group(1).strip('"').lower()
                        tables_created.append(table_name)
            except Exception as e:
                self.logger.warning(f"Schema statement failed: {e}")
                # Continue with other statements

        connection.commit()

        # Convert time-series tables to hypertables
        self._convert_to_hypertables(connection, tables_created, benchmark)

        cursor.close()

        duration = elapsed_seconds(start_time)
        self.log_operation_complete(
            "Schema creation",
            duration,
            f"Schema and tables created, {len(self._hypertables)} hypertables",
        )
        return duration

    def _convert_to_hypertables(
        self,
        connection: Any,
        tables: list[str],
        benchmark,
    ) -> None:
        """Convert eligible tables to TimescaleDB hypertables.

        Tables with a 'time' column are converted to hypertables for
        time-series optimized storage and querying.
        """
        cursor = connection.cursor()

        # Get tables that have a time column
        time_column_tables = self._get_tables_with_time_column(connection, tables)

        for table_name in time_column_tables:
            try:
                # Build qualified table identifier safely using psycopg2.sql
                if self.schema != "public":
                    table_identifier = psql.Identifier(self.schema, table_name)
                else:
                    table_identifier = psql.Identifier(table_name)

                # Check if already a hypertable
                cursor.execute(
                    """
                    SELECT 1 FROM timescaledb_information.hypertables
                    WHERE hypertable_name = %s
                    """,
                    (table_name,),
                )
                if cursor.fetchone():
                    self.logger.debug(f"Table {table_name} is already a hypertable")
                    self._hypertables.add(table_name)
                    continue

                # Convert to hypertable using safe SQL composition
                # Note: create_hypertable() takes the table name as a regclass string,
                # so we use sql.Literal for safe string escaping
                self.log_verbose(f"Converting {table_name} to hypertable with chunk_interval={self.chunk_interval}")
                cursor.execute(
                    psql.SQL(
                        """
                        SELECT create_hypertable(
                            {}::regclass,
                            'time',
                            chunk_time_interval => INTERVAL {},
                            if_not_exists => TRUE,
                            migrate_data => TRUE
                        )
                        """
                    ).format(
                        psql.Literal(table_identifier.as_string(connection)),
                        psql.Literal(self.chunk_interval),
                    )
                )
                connection.commit()
                self._hypertables.add(table_name)
                self.logger.info(f"Created hypertable: {table_name}")

                # Add compression policy if enabled
                if self.compression_enabled:
                    self._add_compression_policy(connection, table_name)

            except Exception as e:
                self.logger.warning(f"Failed to convert {table_name} to hypertable: {e}")
                connection.rollback()

        cursor.close()

    def _get_tables_with_time_column(self, connection: Any, tables: list[str]) -> list[str]:
        """Get list of tables that have a 'time' column (candidates for hypertables)."""
        if not tables:
            return []

        cursor = connection.cursor()
        time_tables = []

        for table_name in tables:
            try:
                cursor.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = 'time'
                    """,
                    (self.schema, table_name),
                )
                if cursor.fetchone():
                    time_tables.append(table_name)
            except Exception as e:
                self.logger.debug(f"Error checking time column for {table_name}: {e}")

        cursor.close()
        return time_tables

    def _add_compression_policy(self, connection: Any, table_name: str) -> None:
        """Add compression policy to a hypertable."""
        cursor = connection.cursor()

        try:
            # Build qualified table identifier safely using psycopg2.sql
            if self.schema != "public":
                table_identifier = psql.Identifier(self.schema, table_name)
            else:
                table_identifier = psql.Identifier(table_name)

            # Enable compression on the hypertable using safe SQL composition
            cursor.execute(
                psql.SQL(
                    """
                    ALTER TABLE {} SET (
                        timescaledb.compress,
                        timescaledb.compress_segmentby = ''
                    )
                    """
                ).format(table_identifier)
            )

            # Add compression policy using safe SQL composition
            cursor.execute(
                psql.SQL(
                    """
                    SELECT add_compression_policy(
                        {}::regclass,
                        INTERVAL {},
                        if_not_exists => TRUE
                    )
                    """
                ).format(
                    psql.Literal(table_identifier.as_string(connection)),
                    psql.Literal(self.compression_after),
                )
            )
            connection.commit()
            self.log_verbose(f"Added compression policy to {table_name}: compress after {self.compression_after}")

        except Exception as e:
            self.logger.warning(f"Failed to add compression policy to {table_name}: {e}")
            connection.rollback()
        finally:
            cursor.close()

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data with TimescaleDB optimizations.

        Uses PostgreSQL COPY for efficient loading, with hypertable-aware handling.
        """
        # Use parent's load_data implementation (COPY-based)
        table_stats, loading_time, extra_info = super().load_data(benchmark, connection, data_dir)

        # Run ANALYZE on hypertables for updated statistics
        cursor = connection.cursor()
        for table_name in self._hypertables:
            try:
                # Build qualified table identifier safely using psycopg2.sql
                if self.schema != "public":
                    table_identifier = psql.Identifier(self.schema, table_name)
                else:
                    table_identifier = psql.Identifier(table_name)
                cursor.execute(psql.SQL("ANALYZE {}").format(table_identifier))
                connection.commit()
            except Exception as e:
                self.logger.debug(f"ANALYZE failed for hypertable {table_name}: {e}")
        cursor.close()

        return table_stats, loading_time, extra_info

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get TimescaleDB platform information."""
        # Get base PostgreSQL info
        platform_info = super().get_platform_info(connection)

        # Override platform type and name
        platform_info["platform_type"] = "timescaledb"
        platform_info["platform_name"] = "TimescaleDB"

        # Add TimescaleDB-specific configuration
        platform_info["configuration"]["chunk_interval"] = self.chunk_interval
        platform_info["configuration"]["compression_enabled"] = self.compression_enabled
        if self.compression_enabled:
            platform_info["configuration"]["compression_after"] = self.compression_after

        if connection:
            try:
                cursor = connection.cursor()

                # Get TimescaleDB version
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
                result = cursor.fetchone()
                if result:
                    platform_info["timescaledb_version"] = result[0]

                # Get hypertable count
                cursor.execute("SELECT COUNT(*) FROM timescaledb_information.hypertables")
                result = cursor.fetchone()
                if result:
                    platform_info["configuration"]["hypertable_count"] = result[0]

                # Get chunk count
                cursor.execute("SELECT COUNT(*) FROM timescaledb_information.chunks")
                result = cursor.fetchone()
                if result:
                    platform_info["configuration"]["chunk_count"] = result[0]

                cursor.close()

            except Exception as e:
                self.logger.debug(f"Error getting TimescaleDB info: {e}")

        return platform_info

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply TimescaleDB optimizations for benchmark type."""
        # Apply PostgreSQL optimizations first
        super().configure_for_benchmark(connection, benchmark_type)

        # Add TimescaleDB-specific optimizations
        cursor = connection.cursor()

        try:
            if benchmark_type == "olap":
                # Enable parallel chunk processing
                cursor.execute("SET timescaledb.enable_chunk_skipping = on")
            elif benchmark_type == "timeseries":
                # Optimize for time-series workloads
                cursor.execute("SET timescaledb.enable_chunk_skipping = on")

            connection.commit()
        except Exception as e:
            self.logger.debug(f"Could not set TimescaleDB optimizations: {e}")
        finally:
            cursor.close()

    def supports_tuning_type(self, tuning_type: Any) -> bool:
        """Check if TimescaleDB supports a specific tuning type."""
        try:
            from benchbox.core.tuning.interface import TuningType

            supported = {
                TuningType.PARTITIONING: True,  # Hypertables provide automatic partitioning
                TuningType.SORTING: False,  # No native sort keys
                TuningType.DISTRIBUTION: False,  # Not distributed (unless using TimescaleDB multi-node)
                TuningType.CLUSTERING: True,  # CLUSTER command available
                TuningType.PRIMARY_KEYS: True,  # Full constraint support
                TuningType.FOREIGN_KEYS: True,  # Full constraint support
                TuningType.AUTO_COMPACT: True,  # TimescaleDB compression is a form of compaction
            }
            return supported.get(tuning_type, False)
        except ImportError:
            return False


def _build_timescaledb_config(benchmark_config: dict, platform_options: dict) -> dict:
    """Build TimescaleDB configuration from benchmark and platform options.

    This function is registered with PlatformHookRegistry to provide
    TimescaleDB-specific configuration handling.
    """
    config = {
        "host": platform_options.get("host", "localhost"),
        "port": platform_options.get("port", 5432),
        "username": platform_options.get("username", "postgres"),
        "password": platform_options.get("password"),
        "schema": platform_options.get("schema", "public"),
        "database": platform_options.get("database"),
        "admin_database": platform_options.get("admin_database", "postgres"),
        "sslmode": platform_options.get("sslmode", "prefer"),
        "work_mem": platform_options.get("work_mem", "256MB"),
        "maintenance_work_mem": platform_options.get("maintenance_work_mem", "512MB"),
        "effective_cache_size": platform_options.get("effective_cache_size", "1GB"),
        "max_parallel_workers_per_gather": platform_options.get("max_parallel_workers_per_gather", 2),
        # TimescaleDB-specific
        "chunk_interval": platform_options.get("chunk_interval", "1 day"),
        "compression_enabled": platform_options.get("compression_enabled", False),
        "compression_after": platform_options.get("compression_after", "7 days"),
    }

    # Merge benchmark configuration
    config.update(benchmark_config)

    return config

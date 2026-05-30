"""Setup and connection routines for InfluxDB.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import Any

from .client import InfluxDBConnection

logger = logging.getLogger(__name__)


class InfluxDBSetupMixin:
    """Provide setup and connection helpers for InfluxDB."""

    def _setup_connection_params(self, config: dict[str, Any]) -> None:
        """Setup connection parameters from config.

        Extracts and validates connection parameters including host, port, token, org,
        database, SSL setting, and deployment mode. Token is required for authentication;
        if not provided in config, the adapter will attempt to use INFLUXDB_TOKEN
        environment variable during connection.

        Args:
            config: Configuration dictionary with connection parameters:
                - host: InfluxDB server hostname (default: localhost)
                - port: Server port (default: 8086)
                - token: Authentication token (required; can be set via INFLUXDB_TOKEN env var)
                - org: Organization name (optional, required for some deployments)
                - database: Database/bucket name (default: benchbox)
                - ssl: Use SSL/TLS connection (default: True)
                - mode: Deployment mode 'core' or 'cloud' (default: cloud)
        """
        # Connection parameters
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 8086)
        self.token = config.get("token")
        self.org = config.get("org")
        self.database = config.get("database", "benchbox")
        self.ssl = config.get("ssl", True)
        self.verify_ssl = config.get("verify_ssl") if config.get("verify_ssl") is not None else True
        self.ca_cert_path = config.get("ca_cert_path")
        self.mode = config.get("mode", "cloud")

        # Validate token is provided
        if not self.token:
            logger.warning("No InfluxDB token provided. Set --token or INFLUXDB_TOKEN environment variable.")

    def create_connection(self, **connection_config) -> InfluxDBConnection:
        """Create InfluxDB connection.

        Args:
            **connection_config: Override connection parameters

        Returns:
            Connected InfluxDBConnection instance

        Raises:
            ConnectionError: If connection fails
        """
        self.log_operation_start("InfluxDB connection", f"mode: {self.mode}")
        self.handle_existing_database(**connection_config)

        # Get connection parameters with overrides
        host = connection_config.get("host", self.host)
        port = connection_config.get("port", self.port)
        token = connection_config.get("token", self.token)
        database = connection_config.get("database", self.database)
        ssl = connection_config.get("ssl", self.ssl)
        org = connection_config.get("org", self.org)
        verify_ssl = connection_config.get("verify_ssl", self.verify_ssl)
        ca_cert_path = connection_config.get("ca_cert_path", self.ca_cert_path)

        try:
            connection = InfluxDBConnection(
                host=host,
                token=token,
                database=database,
                port=port,
                ssl=ssl,
                org=org,
                verify_ssl=verify_ssl,
                ca_cert_path=ca_cert_path,
            )
            connection.connect()

            # Test connection
            if connection.test_connection():
                self.logger.info(f"Connected to InfluxDB at {host}:{port}")
            else:
                raise ConnectionError("Connection test failed")

            return connection

        except Exception as e:
            self.logger.error(f"Failed to connect to InfluxDB: {e}")
            raise

    def close_connection(self, connection: Any) -> None:
        """Close InfluxDB connection.

        Args:
            connection: InfluxDBConnection to close
        """
        try:
            if connection and hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            self.logger.warning(f"Error closing connection: {e}")

    def handle_existing_database(self, **connection_config) -> None:
        """Handle existing database based on force_recreate setting.

        InfluxDB 3.x manages databases (buckets) differently:
        - Core/OSS: Databases are created automatically
        - Cloud: Databases are managed via the InfluxDB UI or API

        For benchmarking, we typically work with existing databases.

        Args:
            **connection_config: Connection configuration
        """
        if getattr(self, "force_recreate", False):
            self.logger.warning(
                "InfluxDB does not support database recreation via SQL. "
                "Database must be managed via InfluxDB UI or API."
            )
        base_handler = getattr(super(), "handle_existing_database", None)
        if base_handler is not None:
            base_handler(**connection_config)

    def check_benchmark_tables_exist(self, **connection_config) -> bool | None:
        """Check whether the InfluxDB bucket has the current benchmark tables."""
        if getattr(self, "force_recreate", False):
            self.log_verbose("Force recreate enabled - treating as fresh database")
            return False

        benchmark = getattr(self, "benchmark", None) or getattr(self, "benchmark_instance", None)
        if benchmark is None:
            self.log_verbose("Benchmark not available - treating as fresh database")
            return False

        expected_tables = None
        table_resolver = getattr(self, "_get_expected_tables", None)
        if callable(table_resolver):
            expected_tables = table_resolver(benchmark)
        if not expected_tables:
            table_map = getattr(benchmark, "tables", None)
            if table_map and hasattr(table_map, "keys"):
                expected_tables = [str(table).lower() for table in table_map.keys()]
        if not expected_tables:
            self.log_verbose("Benchmark has no tables - treating as fresh database")
            return False

        host = connection_config.get("host", self.host)
        port = connection_config.get("port", self.port)
        token = connection_config.get("token", self.token)
        database = connection_config.get("database", self.database)
        ssl = connection_config.get("ssl", self.ssl)
        org = connection_config.get("org", self.org)
        verify_ssl = connection_config.get("verify_ssl", self.verify_ssl)
        ca_cert_path = connection_config.get("ca_cert_path", self.ca_cert_path)

        connection = None
        try:
            connection = InfluxDBConnection(
                host=host,
                token=token,
                database=database,
                port=port,
                ssl=ssl,
                org=org,
                verify_ssl=verify_ssl,
                ca_cert_path=ca_cert_path,
            )
            connection.connect()
            existing_tables = {str(table).lower() for table in self.get_tables(connection)}
        except Exception as e:
            self.logger.debug(f"Error checking existing InfluxDB tables: {e}")
            self.log_verbose("Unable to verify existing tables - treating as fresh database")
            return False
        finally:
            if connection is not None:
                self.close_connection(connection)

        missing_tables = set(expected_tables) - existing_tables
        if missing_tables:
            self.log_verbose(
                f"Expected benchmark tables not found: {', '.join(sorted(missing_tables))} - treating as fresh database"
            )
            return False

        self.log_verbose(f"Found all {len(expected_tables)} expected benchmark tables - reusing database")
        return True

    def get_database_path(self, **connection_config) -> str | None:
        """Get database path for local mode persistence.

        InfluxDB doesn't use file-based databases like DuckDB/SQLite.
        This method is provided for interface compatibility.

        Returns:
            None (InfluxDB doesn't use file paths)
        """
        return None


__all__ = ["InfluxDBSetupMixin"]

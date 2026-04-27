"""PrestoDB platform adapter with distributed SQL query engine optimizations.

Provides PrestoDB-specific optimizations for analytical workloads,
including connector catalog support, session properties, and query optimization.

PrestoDB is Meta's (Facebook's) distributed SQL query engine, maintained as an
open-source project separate from Trino (formerly PrestoSQL).

IMPORTANT: This adapter supports PrestoDB only, NOT Trino.

While PrestoDB and Trino share a common ancestry (Trino forked from Presto in 2019),
they have diverged significantly:
- Different Python drivers (presto-python-client vs trino)
- Different HTTP headers (X-Presto-* vs X-Trino-*)
- Diverging SQL syntax and function implementations
- Different system metadata table schemas

For Trino workloads, use the TrinoAdapter instead.
For AWS Athena (managed Presto-compatible), use the AthenaAdapter.
For Starburst Enterprise (commercial Trino), use the TrinoAdapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.benchmark_mixins import CursorValidationQueryExecutionMixin
from benchbox.core.sql_utils import normalize_table_name_in_sql
from benchbox.platforms.base.ddl_helpers import strip_with_properties
from benchbox.platforms.base.external_table_mixin import HiveExternalTableMixin
from benchbox.platforms.presto_trino_utils import (
    load_file_batches,
    normalize_existing_files,
    resolve_data_files,
)
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
        UnifiedTuningConfiguration,
    )

from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from .base import DriverIsolationCapability, PlatformAdapter
from .presto_trino_utils import validate_catalog_exists

try:
    import prestodb
    from prestodb.auth import BasicAuthentication as PrestoBasicAuthentication
except ImportError:
    prestodb = None
    PrestoBasicAuthentication = None

PRESTO_DIALECT = "presto"


class PrestoAdapter(CursorValidationQueryExecutionMixin, HiveExternalTableMixin, PlatformAdapter):
    """PrestoDB platform adapter for distributed SQL query execution.

    PrestoDB is a distributed SQL query engine designed for interactive analytics
    against data sources of all sizes. It supports querying data from multiple
    sources including Hive, Iceberg, Delta Lake, and cloud storage.

    Key Features:
    - Distributed query execution across multiple workers
    - Federated queries across multiple data sources
    - Session properties for query optimization
    - Support for Hive and other table formats

    Compatibility:
    - PrestoDB (Meta/Facebook): Fully supported
    - Trino: NOT supported - use TrinoAdapter instead
    - AWS Athena: Use AthenaAdapter instead (managed Presto-compatible service)
    - Starburst Enterprise: Use TrinoAdapter (Trino-based)
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    supports_external_tables = True

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies
        if not prestodb:
            available, missing = check_platform_dependencies("presto")
            if not available:
                error_msg = get_dependency_error_message("presto", missing)
                raise ImportError(error_msg)

        self._dialect = PRESTO_DIALECT

        # Presto connection configuration
        self.host = config.get("host") or "localhost"
        self.port = config.get("port") if config.get("port") is not None else 8080
        self.catalog = config.get("catalog")  # Required - validated in _validate_catalog_exists()
        self.schema = config.get("schema") or "default"
        self.source = config.get("source") or "BenchBox"

        # Authentication configuration
        self.username = config.get("username") or config.get("user") or "presto"
        self.password = config.get("password")

        # HTTP configuration
        self.http_scheme = config.get("http_scheme") or ("https" if self.password else "http")
        self.verify_ssl = config.get("verify_ssl") if config.get("verify_ssl") is not None else True
        self.ssl_cert_path = config.get("ssl_cert_path")

        # Session properties for query optimization
        self.session_properties = config.get("session_properties") or {}

        # Track if catalog was auto-selected (for credential saving)
        self._catalog_was_auto_selected = False

        # Query timeout in seconds (0 = no timeout)
        self.query_timeout = config.get("query_timeout") if config.get("query_timeout") is not None else 0

        # Result cache control - disable by default for accurate benchmarking
        self.disable_result_cache = config.get("disable_result_cache", True)

        # Table format configuration (memory, hive)
        # Note: PrestoDB has different Iceberg support than Trino
        self.table_format = config.get("table_format") or "memory"

        # Cloud storage configuration for data loading
        self.staging_root = config.get("staging_root")

        # Source catalog for external data loading (e.g., 'hive' connector for reading files)
        self.source_catalog = config.get("source_catalog")

    @property
    def platform_name(self) -> str:
        return "Presto"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Presto-specific CLI arguments."""

        presto_group = parser.add_argument_group("Presto Arguments")
        presto_group.add_argument("--host", type=str, default="localhost", help="Presto coordinator hostname")
        presto_group.add_argument("--port", type=int, default=8080, help="Presto coordinator port")
        presto_group.add_argument("--catalog", type=str, help="Catalog for queries (e.g., hive, iceberg)")
        presto_group.add_argument("--schema", type=str, default="default", help="Default schema within the catalog")
        presto_group.add_argument("--username", type=str, default="presto", help="Username for authentication")
        presto_group.add_argument("--password", type=str, help="Password for basic authentication")
        presto_group.add_argument(
            "--http-scheme", type=str, choices=["http", "https"], help="HTTP scheme (auto-detected based on password)"
        )
        presto_group.add_argument(
            "--table-format",
            type=str,
            choices=["memory", "hive"],
            default="memory",
            help="Table format for creating benchmark tables",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Presto adapter from unified configuration."""
        from benchbox.utils.database_naming import generate_database_name

        adapter_config: dict[str, Any] = {}

        # Generate proper schema name using benchmark characteristics
        # Presto uses schema instead of database
        if "schema" in config and config["schema"]:
            adapter_config["schema"] = config["schema"]
        else:
            schema_name = generate_database_name(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="presto",
                tuning_config=config.get("tuning_config"),
            )
            adapter_config["schema"] = schema_name

        # Core connection parameters
        for key in ["host", "port", "catalog", "username", "password"]:
            if key in config:
                adapter_config[key] = config[key]

        # Optional configuration parameters
        for key in [
            "http_scheme",
            "verify_ssl",
            "ssl_cert_path",
            "session_properties",
            "query_timeout",
            "disable_result_cache",
            "table_format",
            "staging_root",
            "source_catalog",
            "source",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Presto platform information.

        Captures comprehensive Presto configuration including:
        - Presto version
        - Node count
        - Catalog and schema configuration
        - Session properties
        """
        platform_info = {
            "platform_type": "presto",
            "platform_name": "PrestoDB",
            "connection_mode": "remote",
            "dialect": PRESTO_DIALECT,
            "host": self.host,
            "port": self.port,
            "configuration": {
                "catalog": self.catalog,
                "schema": self.schema,
                "http_scheme": self.http_scheme,
                "table_format": self.table_format,
                "result_cache_disabled": self.disable_result_cache,
                "session_properties": dict(self.session_properties) if self.session_properties else {},
                "client_source": self.source,
            },
        }

        # Get client library version
        if prestodb:
            try:
                platform_info["client_library_version"] = prestodb.__version__
            except AttributeError:
                platform_info["client_library_version"] = None
        else:
            platform_info["client_library_version"] = None

        # Try to get Presto version and extended metadata from connection
        if connection:
            cursor = None
            try:
                cursor = connection.cursor()

                # Get Presto version from system runtime
                # Note: PrestoDB uses same system tables as Trino (shared heritage)
                try:
                    cursor.execute("SELECT node_version FROM system.runtime.nodes WHERE coordinator = true LIMIT 1")
                    result = cursor.fetchone()
                    platform_info["platform_version"] = result[0] if result else None
                except Exception as primary_error:
                    self.logger.debug(f"Primary Presto version query failed: {primary_error}")

                # Fallback to SELECT version() if node metadata not accessible
                if platform_info.get("platform_version") is None:
                    try:
                        cursor.execute("SELECT version()")
                        result = cursor.fetchone()
                        platform_info["platform_version"] = result[0] if result else None
                    except Exception as fallback_error:
                        self.logger.debug(f"Fallback Presto version query failed: {fallback_error}")

                # Get node count
                try:
                    cursor.execute("SELECT count(*) FROM system.runtime.nodes")
                    result = cursor.fetchone()
                    if result:
                        platform_info["configuration"]["node_count"] = result[0]
                except Exception as node_error:
                    self.logger.debug(f"Error collecting Presto node count: {node_error}")

                # Get catalog list
                try:
                    cursor.execute("SHOW CATALOGS")
                    catalogs = [row[0] for row in cursor.fetchall()]
                    platform_info["configuration"]["available_catalogs"] = catalogs
                except Exception as catalog_error:
                    self.logger.debug(f"Error collecting Presto catalogs: {catalog_error}")

            except Exception as e:
                self.logger.debug(f"Error collecting Presto platform info: {e}")
                if platform_info.get("platform_version") is None:
                    platform_info["platform_version"] = None
            finally:
                if cursor:
                    cursor.close()
        else:
            platform_info["platform_version"] = None

        return platform_info

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Presto."""
        return PRESTO_DIALECT

    def _get_connection_params(self) -> dict[str, Any]:
        """Get connection parameters for Presto."""
        params: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "user": self.username,
            "catalog": self.catalog,
            "schema": self.schema,
            "http_scheme": self.http_scheme,
            "source": self.source,
        }

        # Add authentication if password is provided
        if self.password and PrestoBasicAuthentication:
            params["auth"] = PrestoBasicAuthentication(self.username, self.password)

        # SSL verification - presto-python-client uses 'requests_kwargs' for SSL config
        if self.http_scheme == "https":
            requests_kwargs = {}
            if self.ssl_cert_path:
                requests_kwargs["verify"] = self.ssl_cert_path
            else:
                requests_kwargs["verify"] = self.verify_ssl
            if requests_kwargs:
                params["requests_kwargs"] = requests_kwargs

        # Apply session configuration at connection time when provided
        if self.session_properties:
            params["session_properties"] = self.session_properties

        # Enforce request timeout when configured (0 means client default)
        if self.query_timeout and self.query_timeout > 0:
            params["request_timeout"] = self.query_timeout

        return params

    def _get_available_catalogs(self) -> list[str]:
        """Get list of available catalogs from Presto server.

        Returns:
            List of catalog names available on the server.
        """
        try:
            params = self._get_connection_params()
            # Use system catalog which should always exist
            params["catalog"] = "system"
            params["schema"] = "runtime"

            conn = prestodb.dbapi.connect(**params)
            cursor = conn.cursor()

            try:
                cursor.execute("SHOW CATALOGS")
                catalogs = [row[0] for row in cursor.fetchall()]
                return catalogs
            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            self.logger.debug(f"Error getting available catalogs: {e}")
            return []

    def _auto_select_catalog(self) -> str | None:
        """Auto-select best catalog for benchmarking when none specified.

        Connects to the server and selects the most appropriate catalog
        based on typical production configurations.

        Returns:
            Selected catalog name, or None if server unreachable or no usable catalogs
        """
        available = self._get_available_catalogs()

        if not available:
            return None

        # System catalogs that cannot be used for benchmarking (no CREATE TABLE support)
        system_only_catalogs = {"jmx", "system"}

        # Filter to only usable data catalogs
        usable_catalogs = [c for c in available if c not in system_only_catalogs]

        if not usable_catalogs:
            # Only system catalogs exist - return None to trigger helpful error
            return None

        # Prefer persistent storage for production-like behavior
        # hive: common in production, persistent storage
        # iceberg: modern format, good performance
        # delta: Databricks ecosystem
        # memory: fallback, works everywhere but volatile
        # tpch: built-in TPC-H data (if available)
        preferred = ["hive", "iceberg", "delta", "memory", "tpch"]

        for catalog in preferred:
            if catalog in usable_catalogs:
                return catalog

        # Fall back to first usable catalog
        return usable_catalogs[0]

    def _validate_catalog_exists(self, catalog: str | None) -> str:
        """Validate catalog exists, or auto-select one if not specified.

        Args:
            catalog: Catalog name to validate, or None to auto-select

        Returns:
            Validated catalog name (may be auto-selected)

        Raises:
            ConfigurationError: If no catalog available or server unreachable
        """
        validated_catalog, auto_selected = validate_catalog_exists(
            catalog,
            platform_name="Presto",
            auto_select_catalog=self._auto_select_catalog,
            get_available_catalogs=self._get_available_catalogs,
            logger=self.logger,
        )
        if auto_selected:
            self._catalog_was_auto_selected = True
        return validated_catalog

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if schema exists in Presto catalog.

        Presto uses schemas instead of databases. Schemas exist within catalogs.
        """
        try:
            catalog = connection_config.get("catalog", self.catalog)
            schema = connection_config.get("schema", self.schema)

            # Validate and potentially auto-select catalog
            validated_catalog = self._validate_catalog_exists(catalog)

            # Store the validated catalog for use in subsequent operations
            if not self.catalog or self._catalog_was_auto_selected:
                self.catalog = validated_catalog

            catalog = validated_catalog

            # Validate identifiers
            if not self._validate_identifier(catalog) or not self._validate_identifier(schema):
                self.logger.warning(f"Invalid catalog or schema identifier: {catalog}.{schema}")
                return False

            # Create a connection to check schema existence
            params = self._get_connection_params()
            # Connect to information_schema within the target catalog
            params["catalog"] = catalog
            params["schema"] = "information_schema"

            conn = prestodb.dbapi.connect(**params)
            cursor = conn.cursor()

            try:
                cursor.execute(
                    f"SELECT schema_name FROM information_schema.schemata "
                    f"WHERE catalog_name = '{catalog}' AND schema_name = '{schema}'"
                )
                result = cursor.fetchone()
                return result is not None
            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            # Re-raise ConfigurationError (catalog validation errors)
            if (
                "ConfigurationError" in type(e).__name__
                or "server is unreachable" in str(e)
                or "does not exist on the Presto server" in str(e)
            ):
                raise
            self.logger.debug(f"Error checking schema existence: {e}")
            return False

    def _validate_identifier(self, identifier: str) -> bool:
        """Validate SQL identifier to prevent injection attacks.

        Args:
            identifier: The identifier to validate (catalog, schema, table name)

        Returns:
            True if identifier is safe, False otherwise
        """
        if not identifier:
            return False
        # Allow alphanumeric, underscores, and hyphens (common in Presto identifiers)
        # Must start with letter or underscore
        pattern = r"^[a-zA-Z_][a-zA-Z0-9_-]*$"
        return bool(re.match(pattern, identifier)) and len(identifier) <= 128

    def _save_auto_selected_catalog(self) -> None:
        """Save auto-selected catalog to credentials for future runs."""
        try:
            from benchbox.security.credentials import CredentialManager

            cred_manager = CredentialManager()
            platform = "presto"

            # Get existing credentials and merge
            existing = cred_manager.get_platform_credentials(platform) or {}
            existing["catalog"] = self.catalog
            existing["host"] = self.host
            existing["port"] = self.port

            cred_manager.save_platform_credentials(platform, existing)
            self.logger.info(
                f"Saved '{self.catalog}' as default catalog for future presto runs. "
                f"Override with --platform-option catalog=<name> or edit ~/.benchbox/credentials.yaml"
            )
        except Exception as e:
            self.logger.debug(f"Could not save credentials: {e}")

    def drop_database(self, **connection_config) -> None:
        """Drop schema in Presto catalog.

        Presto uses DROP SCHEMA for removing schemas.
        DROP SCHEMA CASCADE is not supported by Presto connectors (including memory,
        hive, iceberg), so we drop tables individually before dropping the schema.
        """
        schema = connection_config.get("schema", self.schema)
        catalog = connection_config.get("catalog", self.catalog)

        # Validate identifiers to prevent SQL injection
        if not self._validate_identifier(catalog) or not self._validate_identifier(schema):
            raise ValueError(f"Invalid catalog or schema identifier: {catalog}.{schema}")

        # Check if schema exists first
        if not self.check_server_database_exists(schema=schema, catalog=catalog):
            self.log_verbose(f"Schema {catalog}.{schema} does not exist - nothing to drop")
            return

        try:
            params = self._get_connection_params()
            # Connect to the target schema to list and drop tables
            params["catalog"] = catalog
            params["schema"] = schema

            conn = prestodb.dbapi.connect(**params)
            cursor = conn.cursor()

            try:
                # Get list of tables in the schema
                cursor.execute("SHOW TABLES")
                tables = [row[0] for row in cursor.fetchall()]

                # Drop each table individually (Presto connectors don't support CASCADE)
                for table in tables:
                    if self._validate_identifier(table):
                        try:
                            cursor.execute(f"DROP TABLE IF EXISTS {catalog}.{schema}.{table}")
                            self.logger.info(f"Dropped table {table}")
                        except Exception as table_error:
                            self.logger.warning(f"Failed to drop table {table}: {table_error}")

                # Now drop the empty schema
                cursor.execute(f"DROP SCHEMA IF EXISTS {catalog}.{schema}")
                self.logger.info(f"Dropped schema {catalog}.{schema}")
            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            raise RuntimeError(f"Failed to drop Presto schema {catalog}.{schema}: {e}") from e

    def _is_local_host(self, host: str | None) -> bool:
        """Return True if the configured host points to the local machine."""
        if not host:
            return False
        normalized = host.strip().lower()
        if normalized in {"localhost", "127.0.0.1", "::1"}:
            return True
        try:
            addr = ipaddress.ip_address(normalized)
            return addr.is_loopback
        except ValueError:
            return normalized.endswith(".local")

    def _error_indicates_connection_refused(self, exc: Exception) -> bool:
        message = str(exc).lower()
        connection_error_markers = [
            "connection refused",
            "failed to establish a new connection",
            "max retries exceeded",
            "errno 61",
            "errno 111",
        ]
        return any(marker in message for marker in connection_error_markers)

    def _build_friendly_connection_error(self, exc: Exception) -> str | None:
        if not self._is_local_host(self.host):
            return None
        if not self._error_indicates_connection_refused(exc):
            return None

        host = self.host or "localhost"
        port = self.port or 8080
        return (
            f"Presto is not running on {host}:{port}. Start your local coordinator before "
            "rerunning BenchBox, or point this benchmark at a running Presto cluster via "
            "`--platform-option host=<host> --platform-option port=<port>`."
        )

    def create_connection(self, **connection_config) -> Any:
        """Create optimized Presto connection."""
        self.log_operation_start("Presto connection")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        params = self._get_connection_params()

        # Override with connection_config if provided
        for key in ["host", "port", "catalog", "schema"]:
            if key in connection_config:
                params[key] = connection_config[key]

        target_schema = params.get("schema", self.schema)
        target_catalog = params.get("catalog", self.catalog)

        # Create schema if needed (before connecting to it)
        if not self.database_was_reused:
            schema_exists = self.check_server_database_exists(schema=target_schema, catalog=target_catalog)

            if not schema_exists:
                self.log_verbose(f"Creating schema: {target_catalog}.{target_schema}")

                # Create schema using a connection to information_schema
                temp_params = params.copy()
                temp_params["schema"] = "information_schema"

                temp_conn = prestodb.dbapi.connect(**temp_params)
                temp_cursor = temp_conn.cursor()

                try:
                    temp_cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {target_catalog}.{target_schema}")
                    self.logger.info(f"Created schema {target_catalog}.{target_schema}")
                finally:
                    temp_cursor.close()
                    temp_conn.close()

        self.log_very_verbose(f"Presto connection params: host={params.get('host')}, catalog={target_catalog}")

        try:
            # presto-python-client applies session properties and headers at connect time
            connection = prestodb.dbapi.connect(**params)

            # Test connection
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()

            self.logger.info(f"Connected to Presto coordinator at {params['host']}:{params['port']}")

            # Save auto-selected catalog to credentials for future runs
            if self._catalog_was_auto_selected:
                self._save_auto_selected_catalog()

            self.log_operation_complete("Presto connection", details=f"Connected to {params['host']}:{params['port']}")

            return connection

        except Exception as e:
            friendly_message = self._build_friendly_connection_error(e)
            if friendly_message:
                self.logger.error(friendly_message)
                raise RuntimeError(friendly_message) from e

            self.logger.error(f"Failed to connect to Presto: {e}")
            raise

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using Presto-optimized table definitions."""
        from benchbox.platforms.presto_trino_utils import execute_schema_statements

        start_time = mono_time()
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")
        execute_schema_statements(
            schema_sql=schema_sql,
            connection=connection,
            logger=self.logger,
            normalize_table_name_in_sql=self._normalize_table_name_in_sql,
            optimize_table_definition=self._optimize_table_definition,
            extract_table_name=self._extract_table_name,
            log_notice=self.log_notice,
        )
        return elapsed_seconds(start_time)

    def _resolve_data_files(self, benchmark: Any, data_dir: Path) -> dict[str, Any]:
        """Resolve benchmark data files from benchmark tables or manifest."""
        return resolve_data_files(
            benchmark,
            data_dir,
            platform_name=self.platform_name,
            table_mode=self.table_mode,
            platform_config=self.platform_config,
            requested_format=self.requested_table_format,
        )

    # External table methods (validate, map types, build columns, build location,
    # create_external_tables) are provided by HiveExternalTableMixin.
    # _normalize_existing_files, _escape_insert_value, and _is_date_value are
    # thin delegates to benchbox.platforms.presto_trino_utils helpers.

    def _load_table_data(
        self,
        cursor: Any,
        table_name: str,
        file_paths: Any,
        target_catalog: str,
        target_schema: str,
    ) -> tuple[int, int] | None:
        """Load one table and return (rows_loaded, valid_file_count)."""
        valid_files = normalize_existing_files(file_paths)
        table_name_lower = table_name.lower()

        if not valid_files:
            self.logger.warning(f"Skipping {table_name} - no valid data files")
            return None

        if not self._validate_identifier(table_name_lower):
            self.logger.warning(f"Skipping {table_name} - invalid table identifier")
            return None

        chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
        self.log_verbose(f"Loading data for table: {table_name}{chunk_info}")

        qualified_table = f"{target_catalog}.{target_schema}.{table_name_lower}"
        rows_loaded = 0
        for file_path in valid_files:
            rows_loaded += load_file_batches(cursor, file_path, qualified_table)

        return rows_loaded, len(valid_files)

    def _log_memory_limit_guidance(self, error_str: str) -> None:
        """Log one-time guidance for memory-limit errors."""
        is_memory_error = "MEMORY_LIMIT_EXCEEDED" in error_str or "exceeds max memory" in error_str.lower()
        if not is_memory_error or hasattr(self, "_memory_error_logged"):
            return

        self._memory_error_logged = True
        self.logger.error(
            "\n"
            "╭─────────────────────────────────────────────────────────────────╮\n"
            "│ PRESTO MEMORY LIMIT EXCEEDED                                    │\n"
            "├─────────────────────────────────────────────────────────────────┤\n"
            "│ The Presto server has insufficient memory for this data load.  │\n"
            "│                                                                 │\n"
            "│ Options to resolve:                                             │\n"
            "│                                                                 │\n"
            "│ 1. Increase Presto memory (recommended for SF1+):              │\n"
            "│    Edit jvm.config: -Xmx4G                                     │\n"
            "│    Edit config.properties:                                     │\n"
            "│      query.max-memory=2GB                                      │\n"
            "│      query.max-memory-per-node=2GB                             │\n"
            "│                                                                 │\n"
            "│ 2. Use a smaller scale factor:                                 │\n"
            "│    benchbox run --platform presto --scale 0.1 ...              │\n"
            "│                                                                 │\n"
            "│ 3. Use a persistent catalog instead of 'memory':               │\n"
            "│    The memory catalog stores all data in RAM.                  │\n"
            "│    For SF1+, use hive, iceberg, or delta catalogs.             │\n"
            "╰─────────────────────────────────────────────────────────────────╯"
        )

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using Presto INSERT statements.

        Presto supports data loading via:
        1. INSERT INTO ... VALUES for small datasets
        2. INSERT INTO ... SELECT from external tables (Hive, S3) for large datasets
        3. CREATE TABLE AS SELECT from external sources

        For benchmarking, we use INSERT statements with values or external table approach
        depending on data size and staging configuration.
        """
        start_time = mono_time()
        table_stats = {}
        total_time = 0.0

        cursor = connection.cursor()
        target_catalog = self.catalog
        target_schema = self.schema

        if not self._validate_identifier(target_catalog) or not self._validate_identifier(target_schema):
            raise ValueError(f"Invalid catalog or schema for load: {target_catalog}.{target_schema}")

        try:
            data_files = self._resolve_data_files(benchmark, data_dir)

            for table_name, file_paths in data_files.items():
                try:
                    load_start = mono_time()
                    table_result = self._load_table_data(cursor, table_name, file_paths, target_catalog, target_schema)

                    table_name_lower = table_name.lower()
                    if table_result is None:
                        table_stats[table_name_lower] = 0
                        continue

                    total_rows_loaded, file_count = table_result
                    table_stats[table_name_lower] = total_rows_loaded
                    chunk_info = f" from {file_count} file(s)" if file_count > 1 else ""
                    self.logger.info(
                        f"✅ Loaded {total_rows_loaded:,} rows into {table_name_lower}{chunk_info} in "
                        f"{elapsed_seconds(load_start):.2f}s"
                    )

                except Exception as e:
                    error_str = str(e)
                    self.logger.error(f"Failed to load {table_name}: {error_str[:100]}...")
                    self._log_memory_limit_guidance(error_str)
                    table_stats[table_name.lower()] = 0

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.logger.info(f"✅ Loaded {total_rows:,} total rows in {total_time:.2f}s")

        except Exception as e:
            self.logger.error(f"Data loading failed: {e}")
            raise
        finally:
            cursor.close()

        return table_stats, total_time, None

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Presto-specific optimizations based on benchmark type."""

        cursor = connection.cursor()

        try:
            # Set session properties for benchmark optimization
            session_settings = []

            if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
                # OLAP-specific optimizations
                session_settings.extend(
                    [
                        # Enable cost-based optimization (PrestoDB syntax)
                        "SET SESSION optimize_hash_generation = true",
                        "SET SESSION join_reordering_strategy = 'AUTOMATIC'",
                        "SET SESSION join_distribution_type = 'AUTOMATIC'",
                    ]
                )

            # Apply session settings
            for setting in session_settings:
                try:
                    cursor.execute(setting)
                    self.logger.debug(f"Applied setting: {setting}")
                except Exception as e:
                    self.logger.warning(f"Failed to apply setting {setting}: {e}")

        finally:
            cursor.close()

    def _extract_table_name(self, statement: str) -> str | None:
        """Extract table name from CREATE TABLE statement."""
        from benchbox.core.sql_utils import extract_table_name

        return extract_table_name(statement)

    def _normalize_table_name_in_sql(self, sql: str) -> str:
        """Normalize table names in SQL to lowercase for Presto."""
        return normalize_table_name_in_sql(sql)

    def _optimize_table_definition(self, statement: str) -> str:
        """Optimize table definition for Presto.

        Presto table creation syntax depends on the connector/catalog being used.
        For memory catalog, minimal syntax is needed.
        For Hive, we can add format specifications.
        """
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # For memory catalog, remove any Presto-incompatible syntax
        # Memory catalog doesn't support WITH properties or NOT NULL constraints

        if self.table_format == "memory" or self.catalog == "memory":
            # Memory catalog: simple CREATE TABLE without WITH clause or NOT NULL
            statement = strip_with_properties(statement)
            statement = re.sub(r"\s+NOT\s+NULL", "", statement, flags=re.IGNORECASE)

        elif self.table_format == "hive":
            # Add table format specification if not present
            if "WITH" not in statement.upper():
                statement += " WITH (format = 'PARQUET')"

        return statement

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get query execution plan for analysis."""
        from benchbox.platforms.base.sql_execution import get_query_plan_from_cursor

        return get_query_plan_from_cursor(connection, query)

    def close_connection(self, connection: Any) -> None:
        """Close Presto connection."""
        try:
            if connection and hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            self.logger.warning(f"Error closing connection: {e}")

    def test_connection(self) -> bool:
        """Test connection to Presto coordinator.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            params = self._get_connection_params()
            # Connect to information_schema for a minimal test
            params["schema"] = "information_schema"

            conn = prestodb.dbapi.connect(**params)
            cursor = conn.cursor()

            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return True
            finally:
                cursor.close()
                conn.close()
        except Exception as e:
            self.logger.debug(f"Connection test failed: {e}")
            return False

    def supports_tuning_type(self, tuning_type) -> bool:
        """Check if Presto supports a specific tuning type.

        Presto supports:
        - PARTITIONING: Via Hive partitioned tables
        - BUCKETING: Via Hive bucketed tables

        Note: Constraints are informational only in Presto (not enforced).
        """
        try:
            from benchbox.core.tuning.interface import TuningType

            return tuning_type in {
                TuningType.PARTITIONING,
            }
        except ImportError:
            return False

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate Presto-specific tuning clauses for CREATE TABLE statements.

        Presto table properties depend on the connector:
        - memory: Limited properties
        - hive: PARTITIONED BY, BUCKETED BY

        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""

        clauses = []

        try:
            from benchbox.core.tuning.interface import TuningType

            # Handle partitioning
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns and self.table_format == "hive":
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                clauses.append(f"PARTITIONED BY ({', '.join(column_names)})")

        except ImportError:
            pass

        if clauses:
            return " ".join(clauses)
        return ""

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to a Presto table.

        Presto tuning is primarily handled at table creation time.
        Post-creation optimization is limited.
        """
        from benchbox.platforms.base.tuning_utils import log_partition_tunings

        log_partition_tunings(table_tuning, self.logger, "Presto")

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to Presto."""
        if not unified_config:
            return

        # Apply constraint configurations (informational only in Presto)
        self.apply_constraint_configuration(unified_config.primary_keys, unified_config.foreign_keys, connection)

        # Apply platform optimizations
        if unified_config.platform_optimizations:
            self.apply_platform_optimizations(unified_config.platform_optimizations, connection)

        # Apply table-level tunings
        for _table_name, table_tuning in unified_config.table_tunings.items():
            self.apply_table_tunings(table_tuning, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply Presto-specific platform optimizations.

        Presto optimizations are primarily session-level:
        - Join reordering strategy
        - Hash generation
        - Memory management

        These are typically set during connection or via session properties.
        """
        if not platform_config:
            return

        self.logger.info("Presto platform optimizations applied via session properties")

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to Presto.

        Note: Presto does not enforce constraints. They are informational only
        and used by the query optimizer for join reordering.
        """
        if primary_key_config and primary_key_config.enabled:
            self.logger.info("Primary key constraints enabled for Presto (informational only, not enforced)")

        if foreign_key_config and foreign_key_config.enabled:
            self.logger.info("Foreign key constraints enabled for Presto (informational only, not enforced)")

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables from Presto schema."""
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW TABLES")
            return [row[0].lower() for row in cursor.fetchall()]
        except Exception:
            return []
        finally:
            cursor.close()

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE on table for query optimization.

        Note: ANALYZE is supported in Hive connector but not memory.
        """
        if self.table_format == "memory":
            self.logger.debug(f"ANALYZE not supported for memory catalog - skipping {table_name}")
            return

        table_name_lower = table_name.lower()
        if not self._validate_identifier(table_name_lower):
            self.logger.warning(f"Skipping analyze for invalid table identifier: {table_name}")
            return

        qualified_table = f"{self.catalog}.{self.schema}.{table_name_lower}"

        cursor = connection.cursor()
        try:
            cursor.execute(f"ANALYZE {qualified_table}")
        except Exception as e:
            self.logger.warning(f"Failed to analyze table {table_name}: {e}")
        finally:
            cursor.close()


def _build_presto_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    from benchbox.platforms.base.config_utils import build_platform_config

    return build_platform_config(
        platform_type="presto",
        credential_key="presto",
        default_display_name="Presto",
        default_driver_package="presto-python-client",
        platform_fields=[
            "host",
            "port",
            "catalog",
            "username",
            "password",
            "http_scheme",
            "verify_ssl",
            "ssl_cert_path",
            "session_properties",
            "query_timeout",
            "table_format",
            "staging_root",
            "schema",
        ],
        options=options,
        overrides=overrides,
        info=info,
    )


# Register the config builder with the platform hook registry
try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("presto", _build_presto_config)
except ImportError:
    # Platform hooks may not be available in all contexts
    pass

"""Firebolt platform adapter supporting both Firebolt Core (local) and Firebolt Cloud.

Provides unified access to Firebolt's vectorized query engine for analytical workloads.
Firebolt Core is a free, self-hosted version that runs locally via Docker with the same
distributed query engine as the cloud version.

Deployment Modes:
- Core (local): Free, Docker-based, no authentication, port 3473
- Cloud: Managed service, requires client credentials and account

Firebolt uses a PostgreSQL-compatible SQL dialect with extensions for analytics.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.benchmark_mixins import CursorValidationQueryExecutionMixin
from benchbox.core.sql_utils import normalize_table_name_in_sql
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.file_format import get_delimiter_for_file

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
        UnifiedTuningConfiguration,
    )

from ..core.exceptions import ConfigurationError
from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from .base import DriverIsolationCapability, PlatformAdapter
from .base.data_loading import FileFormatRegistry

try:
    from firebolt.client.auth import ClientCredentials
    from firebolt.client.auth.firebolt_core import FireboltCore
    from firebolt.db import connect as firebolt_connect

    FIREBOLT_AVAILABLE = True
except ImportError:
    FIREBOLT_AVAILABLE = False
    firebolt_connect = None
    ClientCredentials = None
    FireboltCore = None


def _resolve_firebolt_deployment_mode(
    config: dict, url: str | None, client_id: str | None, client_secret: str | None
) -> str:
    """Resolve deployment mode from explicit config or inferred from credentials.

    Priority: 1) deployment_mode, 2) infer from credentials, 3) default 'core'.
    """
    deployment_mode = config.get("deployment_mode")

    if deployment_mode:
        if deployment_mode not in {"core", "cloud"}:
            raise ValueError(f"Invalid Firebolt deployment mode '{deployment_mode}'. Valid modes: core, cloud")
        return deployment_mode

    if url and not (client_id or client_secret):
        return "core"
    if client_id and client_secret:
        # Guard against ambiguous config (both url and cloud credentials)
        if url:
            raise ValueError(
                "Firebolt configuration is ambiguous: both Core URL and Cloud credentials provided. "
                "Specify --platform firebolt:core or firebolt:cloud explicitly, "
                "or use --platform-option deployment_mode=core|cloud."
            )
        return "cloud"

    return "core"


def _validate_firebolt_mode_config(adapter: FireboltAdapter) -> None:
    """Validate required configuration fields for the resolved deployment mode."""
    if adapter.deployment_mode == "core":
        if not adapter.url:
            # Default to localhost for core mode
            adapter.url = "http://localhost:3473"
    else:
        missing = [
            name
            for name, val in [
                ("client_id", adapter.client_id),
                ("client_secret", adapter.client_secret),
                ("account_name", adapter.account_name),
                ("engine_name", adapter.engine_name),
            ]
            if not val
        ]
        if missing:
            raise ConfigurationError(
                f"Firebolt Cloud configuration is incomplete. Missing: {', '.join(missing)}\n"
                "Configure with:\n"
                "  1. Environment variables: FIREBOLT_CLIENT_ID, FIREBOLT_CLIENT_SECRET, "
                "FIREBOLT_ACCOUNT_NAME, FIREBOLT_ENGINE_NAME\n"
                "  2. CLI options: --platform-option client_id=<id> --platform-option client_secret=<secret>\n"
                "\n"
                "Create service account credentials in the Firebolt console under Settings > Service Accounts."
            )


class FireboltAdapter(CursorValidationQueryExecutionMixin, PlatformAdapter):
    """Firebolt platform adapter for vectorized analytical query execution.

    Supports two deployment modes:
    - **Firebolt Core (local)**: Free, self-hosted Docker deployment on port 3473
    - **Firebolt Cloud**: Managed cloud service requiring authentication

    Key Features:
    - Vectorized query execution optimized for analytics
    - PostgreSQL-compatible SQL dialect
    - Same query engine in both Core and Cloud modes
    - DBAPI 2.0 compliant Python SDK

    Firebolt Core Docker Setup:

        docker run -i --rm --ulimit memlock=8589934592:8589934592 \\
          --security-opt seccomp=unconfined -p 127.0.0.1:3473:3473 \\
          -v ./firebolt-core-data:/firebolt-core/volume \\
          ghcr.io/firebolt-db/firebolt-core:preview-rc
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    def __init__(self, **config):
        """Initialize Firebolt adapter.

        Args:
            **config: Configuration options including:
                Mode detection (auto-detected based on provided params):
                - url: Firebolt Core URL (e.g., "http://localhost:3473")
                - client_id + client_secret: Firebolt Cloud credentials

                Core mode options:
                - url: Core endpoint URL (default: http://localhost:3473)
                - database: Database name

                Cloud mode options:
                - client_id: OAuth client ID
                - client_secret: OAuth client secret
                - account_name: Firebolt account name
                - engine_name: Engine to use for queries
                - database: Database name
                - api_endpoint: API endpoint (default: api.app.firebolt.io)
        """
        super().__init__(**config)

        # Check dependencies
        if not FIREBOLT_AVAILABLE:
            available, missing = check_platform_dependencies("firebolt")
            if not available:
                error_msg = get_dependency_error_message("firebolt", missing)
                raise ImportError(error_msg)

        self._dialect = "postgres"  # Firebolt uses PostgreSQL-compatible dialect

        # Credential loading with env var fallbacks (config takes priority)
        self.url = config.get("url") or config.get("engine_url")
        self.client_id = (
            config.get("client_id") or os.environ.get("FIREBOLT_CLIENT_ID") or os.environ.get("SERVICE_ACCOUNT_ID")
        )
        self.client_secret = (
            config.get("client_secret")
            or os.environ.get("FIREBOLT_CLIENT_SECRET")
            or os.environ.get("SERVICE_ACCOUNT_SECRET")
        )

        self.deployment_mode = _resolve_firebolt_deployment_mode(config, self.url, self.client_id, self.client_secret)

        # Common configuration with env var fallback
        self.database = config.get("database") or os.environ.get("FIREBOLT_DATABASE") or "benchbox"

        # Cloud-specific configuration with env var fallbacks
        self.account_name = config.get("account_name") or os.environ.get("FIREBOLT_ACCOUNT_NAME")
        self.engine_name = config.get("engine_name") or os.environ.get("FIREBOLT_ENGINE_NAME")
        self.api_endpoint = (
            config.get("api_endpoint") or os.environ.get("FIREBOLT_API_ENDPOINT") or "api.app.firebolt.io"
        )

        # Validate required fields per mode
        _validate_firebolt_mode_config(self)

        # S3 staging configuration (for cloud-mode data loading via COPY FROM S3)
        self.s3_staging_url = config.get("s3_staging_url") or os.environ.get("FIREBOLT_S3_STAGING_URL") or None
        self.s3_region = config.get("s3_region") or os.environ.get("FIREBOLT_S3_REGION") or None

        # Validate S3 URL format if provided
        if self.s3_staging_url:
            if not self.s3_staging_url.startswith("s3://"):
                raise ConfigurationError(
                    f"Invalid S3 staging URL: '{self.s3_staging_url}'. "
                    "Must start with 's3://' (e.g., s3://my-bucket/benchbox-staging/)"
                )
            # Ensure trailing slash for consistent path joining
            if not self.s3_staging_url.endswith("/"):
                self.s3_staging_url += "/"

        # Benchmark options
        self.disable_result_cache = self._coerce_bool(config.get("disable_result_cache"), True)
        self.strict_validation = self._coerce_bool(config.get("strict_validation"), False)

    @property
    def platform_name(self) -> str:
        """Return platform display name with mode indicator."""
        return f"Firebolt ({self.deployment_mode.title()})"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Firebolt-specific CLI arguments."""
        firebolt_group = parser.add_argument_group("Firebolt Arguments")

        # Mode selection
        firebolt_group.add_argument(
            "--deployment-mode",
            type=str,
            choices=["core", "cloud"],
            help="Firebolt deployment mode (auto-detected if not specified)",
        )

        # Core mode arguments
        firebolt_group.add_argument(
            "--url",
            type=str,
            default="http://localhost:3473",
            help="Firebolt Core endpoint URL (default: http://localhost:3473)",
        )

        # Cloud mode arguments
        firebolt_group.add_argument(
            "--client-id",
            type=str,
            help="Firebolt Cloud OAuth client ID",
        )
        firebolt_group.add_argument(
            "--client-secret",
            type=str,
            help="Firebolt Cloud OAuth client secret",
        )
        firebolt_group.add_argument(
            "--account-name",
            type=str,
            help="Firebolt Cloud account name",
        )
        firebolt_group.add_argument(
            "--engine-name",
            type=str,
            help="Firebolt Cloud engine name",
        )
        firebolt_group.add_argument(
            "--api-endpoint",
            type=str,
            default="api.app.firebolt.io",
            help="Firebolt Cloud API endpoint",
        )

        # Common arguments
        firebolt_group.add_argument(
            "--database",
            type=str,
            default="benchbox",
            help="Database name (default: benchbox)",
        )

        # S3 staging arguments (cloud mode data loading)
        firebolt_group.add_argument(
            "--firebolt-s3-staging-url",
            type=str,
            help="S3 URL for staging data files during cloud loading (e.g., s3://bucket/benchbox-staging/)",
        )
        firebolt_group.add_argument(
            "--firebolt-s3-region",
            type=str,
            help="AWS region for the S3 staging bucket (e.g., us-east-1)",
        )

        # Benchmark options
        firebolt_group.add_argument(
            "--disable-result-cache",
            action="store_true",
            default=True,
            help="Disable result cache for accurate benchmarking (default: True)",
        )
        firebolt_group.add_argument(
            "--strict-validation",
            action="store_true",
            default=False,
            help="Enable strict validation mode (fail on warnings)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Firebolt adapter from unified configuration."""
        from benchbox.utils.database_naming import generate_database_name

        adapter_config: dict[str, Any] = {}

        # Generate database name using benchmark characteristics
        if "database" in config and config["database"]:
            adapter_config["database"] = config["database"]
        else:
            database_name = generate_database_name(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="firebolt",
                tuning_config=config.get("tuning_config"),
            )
            adapter_config["database"] = database_name

        # Mode and connection parameters
        for key in [
            "url",
            "client_id",
            "client_secret",
            "account_name",
            "engine_name",
            "api_endpoint",
            "deployment_mode",
            "s3_staging_url",
            "s3_region",
            "disable_result_cache",
            "strict_validation",
        ]:
            if key in config and config[key] is not None:
                adapter_config[key] = config[key]

        # Handle mode override
        if config.get("deployment_mode"):
            mode = config["deployment_mode"]
            if mode == "core" and "url" not in adapter_config:
                adapter_config["url"] = "http://localhost:3473"

        return cls(**adapter_config)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Firebolt platform information.

        Captures configuration including:
        - Deployment mode (Core/Cloud)
        - Connection endpoint
        - Database name
        - Engine information (Cloud mode)
        """
        platform_info = {
            "platform_type": "firebolt",
            "platform_name": self.platform_name,
            "connection_mode": self.deployment_mode,
            "configuration": {
                "database": self.database,
            },
        }

        if self.deployment_mode == "core":
            platform_info["url"] = self.url
        else:
            platform_info["account_name"] = self.account_name
            platform_info["engine_name"] = self.engine_name
            platform_info["api_endpoint"] = self.api_endpoint

        # Get SDK version
        try:
            import firebolt

            platform_info["client_library_version"] = firebolt.__version__
        except (ImportError, AttributeError):
            platform_info["client_library_version"] = None

        # Try to get server version from connection
        if connection:
            cursor = None
            try:
                cursor = connection.cursor()
                # Firebolt provides version info via information_schema
                cursor.execute("SELECT version()")
                result = cursor.fetchone()
                platform_info["platform_version"] = result[0] if result else None
                platform_info["engine_version"] = platform_info["platform_version"]
                platform_info["engine_version_source"] = "sql_query"
            except Exception as e:
                self.logger.debug(f"Error collecting Firebolt platform info: {e}")
                platform_info["platform_version"] = None
            finally:
                if cursor:
                    cursor.close()
        else:
            platform_info["platform_version"] = None

        return platform_info

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Firebolt.

        Firebolt uses a PostgreSQL-compatible SQL dialect.
        """
        return "postgres"

    def _get_connection_params(self) -> dict[str, Any]:
        """Get connection parameters based on mode.

        For Core mode, uses FireboltCore auth and 'url' parameter.
        For Cloud mode, uses ClientCredentials auth with account/engine settings.
        """
        params: dict[str, Any] = {
            "database": self.database,
        }

        if self.deployment_mode == "core":
            if not FireboltCore:
                raise ImportError("firebolt-sdk is required for Firebolt Core mode")
            # Core mode requires FireboltCore auth and uses 'url' (not 'engine_url')
            params["auth"] = FireboltCore()
            params["url"] = self.url
        else:
            if not ClientCredentials:
                raise ImportError("firebolt-sdk is required for Firebolt Cloud mode")

            params["auth"] = ClientCredentials(self.client_id, self.client_secret)
            params["account_name"] = self.account_name
            params["engine_name"] = self.engine_name
            params["api_endpoint"] = self.api_endpoint

        return params

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if database exists in Firebolt.

        For Core mode, databases are auto-created on connection but we check
        if there's existing data by looking for tables. An empty database
        is considered "non-existent" for benchmark purposes (safe to recreate).

        For Cloud mode, we query the information schema.
        """
        database = connection_config.get("database", self.database)

        if self.deployment_mode == "core":
            # Core mode: databases are auto-created on connection.
            # We check for existing tables to determine if there's data to preserve.
            # An empty database is treated as "not existing" for benchmark purposes.
            try:
                params = self._get_connection_params()
                if database:
                    params["database"] = database
                conn = firebolt_connect(**params)
                cursor = conn.cursor()
                try:
                    # Try to list tables - if database doesn't exist, this will fail
                    cursor.execute("SHOW TABLES")
                    existing_tables = cursor.fetchall() or []
                    has_tables = len(existing_tables) > 0

                    if has_tables:
                        self.log_verbose(
                            f"Firebolt Core database '{database}' exists with {len(existing_tables)} table(s)"
                        )
                    else:
                        self.log_very_verbose(f"Firebolt Core database '{database}' exists but is empty")

                    # Return True only if there are tables (data to preserve)
                    return has_tables
                finally:
                    cursor.close()
                    conn.close()
            except Exception as e:
                # Connection failure usually means database doesn't exist
                self.logger.debug(f"Core mode database existence check failed: {e}")
                return False

        cursor = None
        conn = None
        try:
            params = self._get_connection_params()
            # Override database to check information_schema
            check_params = params.copy()
            check_params["database"] = "information_schema"

            conn = firebolt_connect(**check_params)
            cursor = conn.cursor()

            database = connection_config.get("database", self.database)
            database_literal = database.replace("'", "''")

            # Query information_schema for database existence
            cursor.execute(
                f"SELECT database_name FROM information_schema.databases WHERE database_name = '{database_literal}'"
            )
            result = cursor.fetchone()

            return result is not None

        except Exception as e:
            self.logger.debug(f"Error checking database existence: {e}")
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def drop_database(self, **connection_config) -> None:
        """Drop database in Firebolt.

        Note: Firebolt Core creates databases implicitly.
        Cloud mode supports explicit DROP DATABASE.
        """
        database = connection_config.get("database", self.database)

        if self.deployment_mode == "core":
            self.log_verbose(f"Firebolt Core: database {database} will be recreated implicitly")
            return

        if not self.check_server_database_exists(database=database):
            self.log_verbose(f"Database {database} does not exist - nothing to drop")
            return

        try:
            params = self._get_connection_params()
            # Connect to a system database to drop target
            params["database"] = "information_schema"

            conn = firebolt_connect(**params)
            cursor = conn.cursor()

            try:
                cursor.execute(f"DROP DATABASE IF EXISTS {self._quote_identifier(database)}")
                self.logger.info(f"Dropped database {database}")
            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            raise RuntimeError(f"Failed to drop Firebolt database {database}: {e}") from e

    def create_connection(self, **connection_config) -> Any:
        """Create Firebolt connection.

        For Core mode, connects directly to the local endpoint.
        For Cloud mode, authenticates and connects to specified engine.
        """
        mode_str = "Core" if self.deployment_mode == "core" else "Cloud"
        self.log_operation_start(f"Firebolt {mode_str} connection")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        params = self._get_connection_params()

        # Override with connection_config if provided
        if "database" in connection_config:
            params["database"] = connection_config["database"]

        self.log_very_verbose(
            f"Firebolt connection params: mode={self.deployment_mode}, database={params.get('database')}"
        )

        try:
            connection = firebolt_connect(**params)

            # Test connection
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()

            # Disable result cache for accurate benchmarking (Cloud mode only)
            if self.disable_result_cache and self.deployment_mode == "cloud":
                self._disable_result_cache(connection)

            endpoint = self.url if self.deployment_mode == "core" else f"{self.account_name}/{self.engine_name}"
            self.logger.info(f"Connected to Firebolt {mode_str} at {endpoint}")

            self.log_operation_complete(
                f"Firebolt {mode_str} connection",
                details=f"Connected to {endpoint}",
            )

            return connection

        except Exception as e:
            self.logger.error(f"Failed to connect to Firebolt: {e}")
            raise

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using Firebolt-optimized table definitions.

        Firebolt uses PostgreSQL-compatible DDL with some differences:
        - TEXT instead of VARCHAR
        - NUMERIC instead of DECIMAL
        - No constraint enforcement
        """
        start_time = mono_time()

        cursor = connection.cursor()

        try:
            # Use common schema creation helper
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

            # Split schema into individual statements and execute
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            for statement in statements:
                if not statement:
                    continue

                # Normalize table names to lowercase
                statement = self._normalize_table_name_in_sql(statement)

                # Optimize table definition for Firebolt
                statement = self._optimize_table_definition(statement)

                try:
                    cursor.execute(statement)
                    self.logger.debug(f"Executed schema statement: {statement[:100]}...")
                except Exception as e:
                    # If table already exists, drop and recreate
                    if "already exists" in str(e).lower():
                        table_name = self._extract_table_name(statement)
                        if table_name:
                            cursor.execute(f"DROP TABLE IF EXISTS {self._quote_identifier(table_name)}")
                            cursor.execute(statement)
                    else:
                        raise

            self.logger.info("Schema created")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise
        finally:
            cursor.close()

        return elapsed_seconds(start_time)

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using INSERT batching or S3 staging (cloud mode).

        Loading strategies:
        - **S3 staging** (cloud mode with s3_staging_url): Upload CSV to S3, then use
          Firebolt's external table function to ingest via INSERT INTO ... SELECT FROM s3().
          This is significantly faster for large datasets.
        - **INSERT batching** (default): Row-by-row INSERT batching via executemany.
          Works for both Core and Cloud modes without external dependencies.

        S3 staging is used when all conditions are met:
        1. deployment_mode == "cloud"
        2. s3_staging_url is configured
        3. boto3 is available
        """
        use_s3_staging = self.deployment_mode == "cloud" and self.s3_staging_url is not None

        if use_s3_staging:
            return self._load_data_via_s3(benchmark, connection, data_dir)
        return self._load_data_via_insert(benchmark, connection, data_dir)

    @staticmethod
    def _normalize_existing_files(file_paths: Any) -> list[Path]:
        """Normalize file inputs to existing, non-empty local paths."""
        normalized_paths = file_paths if isinstance(file_paths, list) else [file_paths]
        valid_files: list[Path] = []
        for file_path in normalized_paths:
            path = Path(file_path)
            if path.exists() and path.stat().st_size > 0:
                valid_files.append(path)
        return valid_files

    def _resolve_data_files(self, benchmark, data_dir: Path) -> dict[str, list[Path]]:
        """Resolve data files from benchmark tables or manifest fallback.

        Returns:
            Mapping of table_name -> list of file paths.

        Raises:
            ValueError: If no data files are found.
        """
        if hasattr(benchmark, "tables") and benchmark.tables:
            # Normalize to dict[str, list[Path]]
            result = {}
            for table, paths in benchmark.tables.items():
                if not isinstance(paths, list):
                    paths = [paths]
                result[table] = [Path(p) for p in paths]
            return result

        data_files = None
        try:
            manifest_path = Path(data_dir) / "_datagen_manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as f:
                    manifest = json.load(f)
                tables = manifest.get("tables") or {}
                mapping = {}
                for table, entries in tables.items():
                    if entries:
                        chunk_paths = []
                        for entry in entries:
                            rel = entry.get("path")
                            if rel:
                                chunk_paths.append(Path(data_dir) / rel)
                        if chunk_paths:
                            mapping[table] = chunk_paths
                if mapping:
                    data_files = mapping
                    self.logger.debug("Using data files from _datagen_manifest.json")
        except Exception as e:
            self.logger.debug(f"Manifest fallback failed: {e}")

        if not data_files:
            raise ValueError("No data files found. Ensure benchmark.generate_data() was called first.")

        return data_files

    def _load_data_via_insert(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using INSERT statement batching.

        This is the default loading path that works for both Core and Cloud modes
        without requiring any external storage or additional dependencies.
        """
        start_time = mono_time()
        table_stats = {}

        cursor = connection.cursor()
        placeholder = self._get_parameter_placeholder(cursor)

        try:
            data_files = self._resolve_data_files(benchmark, data_dir)

            # Load data using INSERT statements in batches
            for table_name, file_paths in data_files.items():
                valid_files = self._normalize_existing_files(file_paths)

                if not valid_files:
                    self.logger.warning(f"Skipping {table_name} - no valid data files")
                    table_stats[table_name.lower()] = 0
                    continue

                chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
                self.log_verbose(f"Loading data for table: {table_name}{chunk_info}")

                try:
                    load_start = mono_time()
                    table_name_lower = table_name.lower()
                    table_name_quoted = self._quote_identifier(table_name_lower)
                    total_rows_loaded = 0

                    for file_path in valid_files:
                        file_path = Path(file_path)

                        # Detect delimiter from file extension (handle compressed extensions)
                        delimiter = get_delimiter_for_file(file_path)

                        # Get compression handler (handles .zst, .gz, or uncompressed)
                        compression_handler = FileFormatRegistry.get_compression_handler(file_path)

                        # Load data using parameterized batches
                        with compression_handler.open(file_path) as f:
                            batch_size = 500  # Moderate batch size for Firebolt
                            batch_rows: list[tuple[Any, ...]] = []
                            insert_sql: str | None = None
                            column_count: int | None = None

                            for raw_line in f:
                                line = raw_line.rstrip("\n")
                                # Handle trailing delimiter (TPC format)
                                if line and line.endswith(delimiter):
                                    line = line[:-1]

                                if not line:
                                    continue

                                values = line.split(delimiter)

                                if column_count is None:
                                    column_count = len(values)
                                    insert_sql = (
                                        f"INSERT INTO {table_name_quoted} VALUES "
                                        f"({', '.join([placeholder for _ in range(column_count)])})"
                                    )
                                elif len(values) != column_count:
                                    raise ValueError(
                                        f"Inconsistent column count in {file_path}: "
                                        f"expected {column_count}, got {len(values)}"
                                    )

                                converted_values = tuple(None if v == "" or v.lower() == "null" else v for v in values)
                                batch_rows.append(converted_values)

                                if len(batch_rows) >= batch_size:
                                    self._execute_batch_insert(cursor, insert_sql, batch_rows)
                                    total_rows_loaded += len(batch_rows)
                                    batch_rows = []

                            # Insert remaining batch
                            if batch_rows:
                                self._execute_batch_insert(cursor, insert_sql, batch_rows)
                                total_rows_loaded += len(batch_rows)

                    # Firebolt doesn't have traditional transactions - no commit needed

                    table_stats[table_name_lower] = total_rows_loaded

                    load_time = elapsed_seconds(load_start)
                    self.logger.info(
                        f"Loaded {total_rows_loaded:,} rows into {table_name_lower}{chunk_info} in {load_time:.2f}s"
                    )

                except Exception as e:
                    self.logger.error(f"Failed to load {table_name}: {str(e)[:100]}...")
                    table_stats[table_name.lower()] = 0

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.logger.info(f"Loaded {total_rows:,} total rows in {total_time:.2f}s")

        except Exception as e:
            self.logger.error(f"Data loading failed: {e}")
            raise
        finally:
            cursor.close()

        return table_stats, total_time, None

    def _load_data_via_s3(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data via S3 staging using Firebolt's external table function.

        Workflow per table:
        1. Upload local CSV/TSV file(s) to S3 staging location
        2. Execute INSERT INTO ... SELECT * FROM s3(...) to ingest from S3
        3. Track row counts from cursor.rowcount or COUNT(*)

        AWS credentials are resolved from:
        1. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment variables
        2. boto3 default credential chain (IAM role, ~/.aws/credentials, etc.)

        Requires boto3 to be installed (lazy import with helpful error message).
        """
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 staging data loading.\n"
                "Install with: uv add boto3\n"
                "Alternatively, remove --firebolt-s3-staging-url to use INSERT batching."
            ) from None

        start_time = mono_time()
        table_stats = {}

        # Resolve AWS credentials for the Firebolt s3() function
        aws_key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
        aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

        # Create S3 client for file uploads
        s3_client_kwargs: dict[str, Any] = {}
        if self.s3_region:
            s3_client_kwargs["region_name"] = self.s3_region
        s3_client = boto3.client("s3", **s3_client_kwargs)

        # Parse S3 staging URL into bucket and prefix
        s3_bucket, s3_prefix = self._parse_s3_url(self.s3_staging_url)

        cursor = connection.cursor()

        try:
            data_files = self._resolve_data_files(benchmark, data_dir)

            for table_name, file_paths in data_files.items():
                if not isinstance(file_paths, list):
                    file_paths = [file_paths]

                # Filter valid files
                valid_files = []
                for file_path in file_paths:
                    file_path = Path(file_path)
                    if file_path.exists() and file_path.stat().st_size > 0:
                        valid_files.append(file_path)

                if not valid_files:
                    self.logger.warning(f"Skipping {table_name} - no valid data files")
                    table_stats[table_name.lower()] = 0
                    continue

                chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
                self.log_verbose(f"Loading data for table (S3 staging): {table_name}{chunk_info}")

                try:
                    load_start = mono_time()
                    table_name_lower = table_name.lower()
                    table_name_quoted = self._quote_identifier(table_name_lower)
                    total_rows_loaded = 0

                    for file_path in valid_files:
                        file_path = Path(file_path)

                        # Detect delimiter
                        delimiter = get_delimiter_for_file(file_path)

                        # Determine the S3 key for this file
                        s3_key = f"{s3_prefix}{table_name_lower}/{file_path.name}"
                        s3_file_url = f"s3://{s3_bucket}/{s3_key}"

                        # Upload file to S3
                        upload_start = mono_time()
                        self.log_verbose(f"Uploading {file_path.name} to {s3_file_url}")
                        s3_client.upload_file(str(file_path), s3_bucket, s3_key)
                        upload_time = elapsed_seconds(upload_start)
                        self.log_verbose(f"Uploaded {file_path.name} in {upload_time:.2f}s")

                        # Map delimiter to Firebolt s3() type parameter
                        s3_type = "CSV" if delimiter == "," else "TSV"

                        # Build the INSERT INTO ... SELECT FROM s3() statement
                        # Firebolt s3() function signature:
                        #   s3(url, aws_key_id, aws_secret_key, type [, ...])
                        # Escape single quotes in credentials for SQL safety
                        safe_key_id = aws_key_id.replace("'", "''")
                        safe_secret = aws_secret_key.replace("'", "''")

                        ingest_sql = (
                            f"INSERT INTO {table_name_quoted} "
                            f"SELECT * FROM s3("
                            f"'{s3_file_url}', "
                            f"'{safe_key_id}', "
                            f"'{safe_secret}', "
                            f"'{s3_type}'"
                            f")"
                        )

                        ingest_start = mono_time()
                        cursor.execute(ingest_sql)
                        ingest_time = elapsed_seconds(ingest_start)

                        # Get row count: prefer cursor.rowcount, fall back to COUNT(*)
                        rows_loaded = getattr(cursor, "rowcount", -1)
                        if rows_loaded is None or rows_loaded < 0:
                            cursor.execute(f"SELECT COUNT(*) FROM {table_name_quoted}")
                            count_result = cursor.fetchone()
                            rows_loaded = count_result[0] if count_result else 0

                        total_rows_loaded += rows_loaded
                        self.log_verbose(
                            f"Ingested {rows_loaded:,} rows from {file_path.name} via S3 in {ingest_time:.2f}s"
                        )

                    table_stats[table_name_lower] = total_rows_loaded

                    load_time = elapsed_seconds(load_start)
                    self.logger.info(
                        f"Loaded {total_rows_loaded:,} rows into {table_name_lower}{chunk_info} "
                        f"via S3 staging in {load_time:.2f}s"
                    )

                except Exception as e:
                    self.logger.error(f"Failed to load {table_name} via S3: {str(e)[:200]}...")
                    table_stats[table_name.lower()] = 0

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.logger.info(f"Loaded {total_rows:,} total rows via S3 staging in {total_time:.2f}s")

        except Exception as e:
            self.logger.error(f"S3 staging data loading failed: {e}")
            raise
        finally:
            cursor.close()

        loading_metadata = {
            "loading_method": "s3_staging",
            "s3_staging_url": self.s3_staging_url,
            "s3_region": self.s3_region,
        }

        return table_stats, total_time, loading_metadata

    @staticmethod
    def _parse_s3_url(s3_url: str) -> tuple[str, str]:
        """Parse an S3 URL into (bucket, prefix) components."""
        from benchbox.utils.cloud_urls import parse_s3_url

        return parse_s3_url(s3_url)

    def _execute_batch_insert(self, cursor: Any, insert_sql: str, rows: list[tuple[Any, ...]]) -> None:
        """Execute batch inserts with executemany fallback."""
        if not rows:
            return

        if hasattr(cursor, "executemany"):
            cursor.executemany(insert_sql, rows)
        else:
            for row in rows:
                cursor.execute(insert_sql, row)

    def _get_parameter_placeholder(self, cursor: Any) -> str:
        """Determine parameter placeholder style for the active cursor."""
        paramstyle = getattr(cursor, "paramstyle", None) or getattr(cursor, "paramstyle_name", None)
        if paramstyle in {"format", "pyformat"}:
            return "%s"
        return "?"

    def _coerce_bool(self, value: Any, default: bool) -> bool:
        """Coerce potentially string config values to booleans."""
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in {"false", "0", "no", "off"}
        return bool(value)

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Firebolt-specific optimizations based on benchmark type.

        Firebolt's vectorized engine is optimized by default for analytical workloads.
        Additional session-level tuning may be applied here.
        """
        # Firebolt is optimized for OLAP by default
        # Log the configuration for informational purposes
        self.log_verbose(f"Configuring Firebolt for {benchmark_type} benchmark")

        if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
            self.log_verbose("Firebolt vectorized engine optimized for analytical workloads")

    def _extract_table_name(self, statement: str) -> str | None:
        """Extract table name from CREATE TABLE statement."""
        from benchbox.core.sql_utils import extract_table_name

        return extract_table_name(statement)

    def _normalize_table_name_in_sql(self, sql: str) -> str:
        """Normalize table names in SQL to lowercase for Firebolt."""
        return normalize_table_name_in_sql(sql)

    def _quote_identifier(self, name: str) -> str:
        """Safely quote identifiers for Firebolt."""
        if not isinstance(name, str) or not name:
            raise ValueError("Identifier must be a non-empty string")
        return '"' + name.replace('"', '""') + '"'

    def _optimize_table_definition(self, statement: str) -> str:
        """Optimize table definition for Firebolt.

        Firebolt-specific type mappings:
        - VARCHAR(n) -> TEXT (Firebolt uses TEXT for all strings)
        - DECIMAL(p,s) -> NUMERIC (Firebolt uses NUMERIC for exact decimals)
        - Remove constraint clauses (Firebolt doesn't enforce constraints)
        """
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # Replace VARCHAR(n) with TEXT
        statement = re.sub(r"VARCHAR\s*\(\s*\d+\s*\)", "TEXT", statement, flags=re.IGNORECASE)
        statement = re.sub(r"\bVARCHAR\b", "TEXT", statement, flags=re.IGNORECASE)
        statement = re.sub(r"\bCHAR\s*\(\s*\d+\s*\)", "TEXT", statement, flags=re.IGNORECASE)

        # Replace DECIMAL with NUMERIC (preserve precision/scale)
        statement = re.sub(r"\bDECIMAL\b", "NUMERIC", statement, flags=re.IGNORECASE)

        # Remove PRIMARY KEY constraints (Firebolt doesn't enforce them)
        statement = re.sub(r",?\s*PRIMARY\s+KEY\s*\([^)]*\)", "", statement, flags=re.IGNORECASE)
        statement = re.sub(r"\s+PRIMARY\s+KEY\b", "", statement, flags=re.IGNORECASE)

        # Remove FOREIGN KEY constraints
        statement = re.sub(
            r",?\s*FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+[^\s,)]+\s*\([^)]*\)",
            "",
            statement,
            flags=re.IGNORECASE,
        )

        # Remove NOT NULL constraints (Firebolt supports nullable by default)
        # Keep NOT NULL as Firebolt does support it
        # statement = re.sub(r"\s+NOT\s+NULL\b", "", statement, flags=re.IGNORECASE)

        # Clean up any double commas or trailing commas before closing paren
        statement = re.sub(r",\s*,", ",", statement)
        statement = re.sub(r",\s*\)", ")", statement)

        return statement

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get query execution plan for analysis."""
        from benchbox.platforms.base.sql_execution import get_query_plan_from_cursor

        return get_query_plan_from_cursor(connection, query)

    def close_connection(self, connection: Any) -> None:
        """Close Firebolt connection."""
        try:
            if connection and hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            self.logger.warning(f"Error closing connection: {e}")

    def test_connection(self) -> bool:
        """Test connection to Firebolt.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            params = self._get_connection_params()
            conn = firebolt_connect(**params)
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
        """Check if Firebolt supports a specific tuning type.

        Firebolt supports:
        - PARTITIONING: Via PARTITION BY clause
        - DISTRIBUTION: Via PRIMARY INDEX clause (critical for Firebolt performance)
        - Aggregating indexes (Firebolt-specific, not exposed via tuning interface)

        Note: Primary/foreign key constraints are NOT enforced in Firebolt.
        Firebolt's PRIMARY INDEX (mapped to DISTRIBUTION tuning type) controls
        how data is distributed across nodes - this is different from PRIMARY KEY.
        """
        try:
            from benchbox.core.tuning.interface import TuningType

            return tuning_type in {
                TuningType.PARTITIONING,
                TuningType.DISTRIBUTION,
            }
        except ImportError:
            return False

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate Firebolt-specific tuning clauses.

        Firebolt table properties include:
        - PRIMARY INDEX: Generated from DISTRIBUTION tuning columns. Controls data
          distribution and is CRITICAL for query performance. Unlike PRIMARY KEY
          constraints, PRIMARY INDEX affects physical data layout across nodes.
        - PARTITION BY: Time-based or value-based partitioning for data organization.

        Example output: PRIMARY INDEX (customer_id, order_date) PARTITION BY order_date
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""

        clauses = []

        try:
            from benchbox.core.tuning.interface import TuningType

            # Handle DISTRIBUTION -> PRIMARY INDEX (most important for Firebolt performance)
            # Firebolt's PRIMARY INDEX controls data distribution across nodes
            distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
            if distribution_columns:
                sorted_cols = sorted(distribution_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                clauses.append(f"PRIMARY INDEX ({', '.join(column_names)})")

            # Handle partitioning
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                clauses.append(f"PARTITION BY {', '.join(column_names)}")

        except ImportError:
            pass

        return " ".join(clauses) if clauses else ""

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to a Firebolt table.

        Firebolt tuning is primarily handled at table creation time.
        Post-creation optimization is limited.
        """
        from benchbox.platforms.base.tuning_utils import log_partition_tunings

        log_partition_tunings(table_tuning, self.logger, "Firebolt")

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to Firebolt."""
        if not unified_config:
            return

        # Apply constraint configurations (informational only in Firebolt)
        self.apply_constraint_configuration(unified_config.primary_keys, unified_config.foreign_keys, connection)

        # Apply platform optimizations
        if unified_config.platform_optimizations:
            self.apply_platform_optimizations(unified_config.platform_optimizations, connection)

        # Apply table-level tunings
        for _table_name, table_tuning in unified_config.table_tunings.items():
            self.apply_table_tunings(table_tuning, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply Firebolt-specific platform optimizations.

        Firebolt's vectorized engine is pre-optimized for analytical workloads.
        Session-level tuning is limited compared to traditional databases.
        """
        if not platform_config:
            return

        self.logger.info("Firebolt platform optimizations noted (engine pre-optimized for analytics)")

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to Firebolt.

        Note: Firebolt does not enforce constraints. They are informational only.
        """
        if primary_key_config and primary_key_config.enabled:
            self.logger.info("Primary key constraints enabled for Firebolt (informational only, not enforced)")

        if foreign_key_config and foreign_key_config.enabled:
            self.logger.info("Foreign key constraints enabled for Firebolt (informational only, not enforced)")

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables from Firebolt database."""
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

        Note: Firebolt may not support explicit ANALYZE commands.
        Statistics are typically collected automatically.
        """
        self.logger.debug(f"Firebolt collects statistics automatically - skipping explicit ANALYZE for {table_name}")

    def _disable_result_cache(self, connection: Any) -> None:
        """Disable result cache for accurate benchmarking.

        Firebolt Cloud caches query results by default. This must be disabled
        for TPC compliance and accurate benchmark measurements.

        Note: This only applies to Cloud mode - Core mode doesn't have result caching.
        """
        if self.deployment_mode != "cloud":
            self.log_very_verbose("Result cache control only applicable to Cloud mode")
            return

        cursor = connection.cursor()
        try:
            # Firebolt uses SET statements for session configuration
            cursor.execute("SET enable_result_cache = false")
            self.log_verbose("Disabled Firebolt result cache for accurate benchmarking")

            # Validate the setting was applied
            if self.strict_validation:
                self.validate_session_cache_control(connection)

        except Exception as e:
            msg = f"Failed to disable Firebolt result cache: {e}"
            if self.strict_validation:
                raise ConfigurationError(msg) from e
            self.logger.warning(msg)
        finally:
            cursor.close()

    def validate_session_cache_control(self, connection: Any) -> bool:
        """Validate that result cache is disabled for the session.

        Returns:
            True if cache is confirmed disabled, False otherwise.

        Raises:
            ConfigurationError: If strict_validation is enabled and validation fails.
        """
        if self.deployment_mode != "cloud":
            return True  # Core mode doesn't have result caching

        cursor = connection.cursor()
        try:
            # Query current session settings
            cursor.execute("SHOW enable_result_cache")
            result = cursor.fetchone()

            if result:
                cache_enabled = str(result[0]).lower() in ("true", "1", "on")
                if cache_enabled:
                    msg = "Result cache is still enabled - benchmark results may be cached"
                    if self.strict_validation:
                        raise ConfigurationError(msg)
                    self.logger.warning(msg)
                    return False

            self.log_very_verbose("Validated: result cache is disabled")
            return True

        except Exception as e:
            if "SHOW" in str(e).upper():
                # SHOW command might not be supported - log warning only
                self.logger.debug(f"Could not validate cache settings (SHOW not supported): {e}")
                return True
            if self.strict_validation:
                raise ConfigurationError(f"Cache validation failed: {e}") from e
            self.logger.warning(f"Could not validate cache settings: {e}")
            return False
        finally:
            cursor.close()

    def _create_admin_connection(self) -> Any:
        """Create admin connection for database management operations.

        For Cloud mode, connects to information_schema database.
        For Core mode, uses the standard connection.

        Returns:
            Database connection for admin operations.
        """
        params = self._get_connection_params()

        if self.deployment_mode == "cloud":
            # Connect to information_schema for admin operations
            params["database"] = "information_schema"

        try:
            conn = firebolt_connect(**params)
            self.log_very_verbose(f"Created Firebolt admin connection (mode={self.deployment_mode})")
            return conn
        except Exception as e:
            self.logger.error(f"Failed to create admin connection: {e}")
            raise

    def _get_platform_metadata(self, connection: Any) -> dict[str, Any]:
        """Collect Firebolt-specific platform metadata.

        Returns detailed information about the Firebolt instance including:
        - Engine configuration (Cloud mode)
        - Resource allocation
        - Version information
        """
        metadata: dict[str, Any] = {
            "mode": self.deployment_mode,
            "database": self.database,
        }

        cursor = connection.cursor()
        try:
            # Get version
            cursor.execute("SELECT version()")
            result = cursor.fetchone()
            if result:
                metadata["version"] = result[0]

            if self.deployment_mode == "cloud":
                metadata["account_name"] = self.account_name
                metadata["engine_name"] = self.engine_name
                metadata["api_endpoint"] = self.api_endpoint

                # Try to get engine details
                try:
                    cursor.execute(
                        "SELECT engine_name, engine_type, status "
                        "FROM information_schema.engines "
                        f"WHERE engine_name = '{self.engine_name}'"
                    )
                    engine_info = cursor.fetchone()
                    if engine_info:
                        metadata["engine_type"] = engine_info[1]
                        metadata["engine_status"] = engine_info[2]
                except Exception as e:
                    self.logger.debug(f"Could not fetch engine details: {e}")
            else:
                metadata["url"] = self.url

        except Exception as e:
            self.logger.debug(f"Error collecting platform metadata: {e}")
        finally:
            cursor.close()

        return metadata


def _build_firebolt_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build Firebolt database configuration with credential loading.

    Args:
        platform: Platform name (should be 'firebolt')
        options: CLI platform options from --platform-option flags
        overrides: Runtime overrides from orchestrator
        info: Platform info from registry

    Returns:
        DatabaseConfig with credentials loaded
    """
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    # Load saved credentials
    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials("firebolt") or {}

    # Build merged options: saved_creds < options < overrides
    merged_options = {}
    merged_options.update(saved_creds)
    merged_options.update(options)
    merged_options.update(overrides)

    name = info.display_name if info else "Firebolt"
    driver_package = info.driver_package if info else "firebolt-sdk"

    config_dict = {
        "type": "firebolt",
        "name": name,
        "options": merged_options or {},
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        # Platform-specific fields at top-level
        "url": merged_options.get("url"),
        "client_id": merged_options.get("client_id"),
        "client_secret": merged_options.get("client_secret"),
        "account_name": merged_options.get("account_name"),
        "engine_name": merged_options.get("engine_name"),
        "api_endpoint": merged_options.get("api_endpoint"),
        "deployment_mode": overrides.get("deployment_mode") or options.get("deployment_mode"),
        # S3 staging configuration
        "s3_staging_url": merged_options.get("s3_staging_url"),
        "s3_region": merged_options.get("s3_region"),
        # Benchmark context for config-aware database naming
        "benchmark": overrides.get("benchmark"),
        "scale_factor": overrides.get("scale_factor"),
        "tuning_config": overrides.get("tuning_config"),
    }

    # Only include explicit database override if provided
    if "database" in overrides and overrides["database"]:
        config_dict["database"] = overrides["database"]

    return DatabaseConfig(**config_dict)


# Register the config builder with the platform hook registry
try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("firebolt", _build_firebolt_config)
except ImportError:
    # Platform hooks may not be available in all contexts
    pass

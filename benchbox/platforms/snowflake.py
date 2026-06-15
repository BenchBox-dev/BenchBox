"""Snowflake platform adapter with native cloud data warehouse optimizations.

Provides Snowflake-specific optimizations for cloud-native analytics,
including multi-cluster warehouse support and automatic scaling.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TuningColumn,
        UnifiedTuningConfiguration,
    )

from ..core.exceptions import ConfigurationError
from ..utils.cloud_storage import get_cloud_path_info
from ..utils.dependencies import check_platform_dependencies, get_dependency_error_message
from .base import DriverIsolationCapability, PlatformAdapter
from .base.config_utils import make_registered_platform_config_builder
from .base.data_loading import NO_BENCHMARK, DataSource, resolve_adapter_data_source, resolve_csv_dialect
from .base.runtime_metadata import build_default_normalized_result_metadata
from .base.tuning import make_informational_constraint_applier
from .presto_trino_utils import normalize_existing_files

try:
    import snowflake.connector
    from snowflake.connector import DictCursor
except ImportError:
    snowflake = None
    DictCursor = None


def _compact_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value not in (None, "", {}, [], ())}


class SnowflakeAdapter(PlatformAdapter):
    """Snowflake platform adapter with cloud data warehouse optimizations."""

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    supports_external_tables = True

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies with improved error message
        available, missing = check_platform_dependencies("snowflake")
        if not available:
            error_msg = get_dependency_error_message("snowflake", missing)
            raise ImportError(error_msg)

        self._dialect = "snowflake"

        # Snowflake connection configuration
        self.account = config.get("account")
        self.warehouse = config.get("warehouse") or "COMPUTE_WH"
        self.database = config.get("database") or "BENCHBOX"
        self.schema = config.get("schema") or "PUBLIC"
        self.username = config.get("username")
        self.password = config.get("password")
        self.role = config.get("role")

        # Authentication options
        self.authenticator = config.get("authenticator") or "snowflake"  # snowflake, oauth, etc.
        self.private_key_path = config.get("private_key_path")
        self.private_key_passphrase = config.get("private_key_passphrase")

        # Warehouse settings
        self.warehouse_size = config.get("warehouse_size") or "MEDIUM"
        self.auto_suspend = config.get("auto_suspend") if config.get("auto_suspend") is not None else 300  # seconds
        self.auto_resume = config.get("auto_resume") if config.get("auto_resume") is not None else True
        self.multi_cluster_warehouse = (
            config.get("multi_cluster_warehouse") if config.get("multi_cluster_warehouse") is not None else False
        )

        # Session settings
        self.query_tag = config.get("query_tag") or "BenchBox"
        self.timezone = config.get("timezone") or "UTC"

        # Result cache control - disable by default for accurate benchmarking
        self.disable_result_cache = config.get("disable_result_cache", True)

        # Validation strictness - raise errors if cache control validation fails
        self.strict_validation = config.get("strict_validation", True)

        # Nondeterministic error suppression - disabled by default to preserve Snowflake's
        # default behavior of erroring on nondeterministic MERGE/UPDATE operations.
        # Enable this for workloads that intentionally use nondeterministic operations.
        self.suppress_nondeterministic_errors = config.get("suppress_nondeterministic_errors", False)

        # Warehouse modification control - when True, BenchBox will ALTER WAREHOUSE settings
        # (size, auto-suspend, scaling policy). These changes PERSIST beyond the benchmark run.
        # Default is False to avoid unexpected infrastructure changes in governed environments.
        # Set to True explicitly if you want BenchBox to configure your warehouse for benchmarking.
        self.modify_warehouse_settings = config.get("modify_warehouse_settings", False)

        # File format settings
        self.file_format = config.get("file_format") or "CSV"
        self.compression = config.get("compression") or "AUTO"

        # Cloud storage staging (optional - Snowflake uses internal stages by default)
        # staging_root is passed by orchestrator when using CloudStagingPath
        # For now, we log it but continue using internal stages (which work with local files)
        self.staging_root = config.get("staging_root")
        self.iceberg_external_volume = config.get("iceberg_external_volume")
        self.iceberg_catalog = config.get("iceberg_catalog") or "SNOWFLAKE"
        self.delta_table_format = config.get("delta_table_format") or "DELTA"
        if self.staging_root:
            path_info = get_cloud_path_info(self.staging_root)
            self.logger.info(
                f"staging_root configured for Snowflake external mode ({path_info['provider']}://{path_info['bucket']})"
            )

        if not all([self.account, self.username, self.password, self.warehouse, self.database]):
            missing = []
            if not self.account:
                missing.append("account (or SNOWFLAKE_ACCOUNT)")
            if not self.username:
                missing.append("username (or SNOWFLAKE_USER)")
            if not self.password:
                missing.append("password (or SNOWFLAKE_PASSWORD)")
            if not self.warehouse:
                missing.append("warehouse (or SNOWFLAKE_WAREHOUSE)")
            if not self.database:
                missing.append("database (or SNOWFLAKE_DATABASE)")

            raise ConfigurationError(
                f"Snowflake configuration is incomplete. Missing: {', '.join(missing)}\n"
                "Configure with one of:\n"
                "  1. CLI: benchbox platforms setup --platform snowflake\n"
                "  2. Environment variables: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, etc.\n"
                "  3. CLI options: --platform-option account=<account> --platform-option warehouse=<wh>"
            )

    @property
    def platform_name(self) -> str:
        return "Snowflake"

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """Build opt-in sorted-ingestion SQL for Snowflake."""
        mode, method = self.resolve_sorted_ingestion_strategy()
        if mode == "off":
            return None

        if method != "ctas":
            raise ValueError(
                f"Sorted ingestion method '{method}' is not supported for Snowflake; use method='ctas' or 'auto'."
            )

        order_by = ", ".join(column.name for column in sort_columns)
        return f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM {table_name} ORDER BY {order_by}"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Snowflake-specific CLI arguments."""

        sf_group = parser.add_argument_group("Snowflake Arguments")
        sf_group.add_argument("--account", type=str, help="Snowflake account identifier")
        sf_group.add_argument("--warehouse", type=str, default="COMPUTE_WH", help="Warehouse name")
        sf_group.add_argument(
            "--platform", type=str, default=None, help="Database name (auto-generated if not specified)"
        )
        sf_group.add_argument("--schema", type=str, default="PUBLIC", help="Schema name")
        sf_group.add_argument("--username", type=str, help="User name")
        sf_group.add_argument("--password", type=str, help="User password")
        sf_group.add_argument("--role", type=str, help="Role to assume for the session")
        sf_group.add_argument("--authenticator", type=str, default="snowflake", help="Authentication method")
        sf_group.add_argument("--private-key-path", type=str, help="Path to private key for key pair auth")

        # Behavior control options
        sf_group.add_argument(
            "--modify-warehouse-settings",
            action="store_true",
            default=False,
            help="Modify warehouse settings (size, auto-suspend, scaling). PERSISTENT changes - use with caution.",
        )
        sf_group.add_argument(
            "--suppress-nondeterministic-errors",
            action="store_true",
            default=False,
            help="Suppress errors on nondeterministic MERGE/UPDATE operations",
        )
        sf_group.add_argument(
            "--no-disable-result-cache",
            action="store_false",
            dest="disable_result_cache",
            help="Enable result cache (disabled by default for accurate benchmarking)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Snowflake adapter from unified configuration."""
        from benchbox.platforms.base.config_utils import build_adapter_config

        return cls(
            **build_adapter_config(
                config,
                platform="snowflake",
                fields=[
                    "account",
                    "warehouse",
                    "schema",
                    "username",
                    "password",
                    "role",
                    "authenticator",
                    "private_key_path",
                    "private_key_passphrase",
                    "warehouse_size",
                    "auto_suspend",
                    "auto_resume",
                    "multi_cluster_warehouse",
                    "query_tag",
                    "timezone",
                    "file_format",
                    "compression",
                    "staging_root",
                    "iceberg_external_volume",
                    "iceberg_catalog",
                    "delta_table_format",
                    "disable_result_cache",
                    "strict_validation",
                    "suppress_nondeterministic_errors",
                    "modify_warehouse_settings",
                ],
            )
        )

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Snowflake platform information.

        Captures comprehensive Snowflake configuration including:
        - Snowflake version
        - Warehouse size and auto-suspend/resume settings
        - Multi-cluster warehouse configuration
        - Cloud provider and region
        - Account edition (best effort)

        Gracefully degrades if permissions are insufficient for metadata queries.
        """
        platform_info = {
            "platform_type": "snowflake",
            "platform_name": "Snowflake",
            "connection_mode": "remote",
            "configuration": {
                "account": self.account,
                "warehouse": self.warehouse,
                "database": self.database,
                "schema": self.schema,
                "role": self.role,
                "warehouse_size": getattr(self, "warehouse_size", None),
                "auto_suspend": self.auto_suspend,
                "auto_resume": self.auto_resume,
                "multi_cluster_warehouse": self.multi_cluster_warehouse,
                "result_cache_enabled": not self.disable_result_cache,
                "file_format": self.file_format,
                "compression": self.compression,
                "staging_root": self.staging_root,
            },
        }

        # Get client library version
        try:
            import snowflake.connector

            platform_info["client_library_version"] = snowflake.connector.__version__
        except (ImportError, AttributeError):
            platform_info["client_library_version"] = None

        # Try to get Snowflake version and extended metadata from connection
        if connection:
            cursor = None
            try:
                cursor = connection.cursor()

                # Get Snowflake version
                result = cursor.execute("SELECT current_version()").fetchone()
                platform_info["platform_version"] = result[0] if result else None
                platform_info["engine_version"] = platform_info["platform_version"]
                platform_info["engine_version_source"] = "sql_query"

                # Get current region and cloud provider
                try:
                    result = cursor.execute("SELECT current_region(), current_cloud()").fetchone()
                    if result:
                        platform_info["cloud_region"] = result[0]
                        platform_info["cloud_provider"] = result[1]
                except Exception as e:
                    self.logger.debug(f"Could not query Snowflake region/cloud: {e}")

                # Try to get warehouse metadata (requires appropriate permissions)
                if self.warehouse:
                    try:
                        # Escape single quotes in LIKE pattern for SQL safety
                        warehouse_escaped = self.warehouse.replace("'", "''")
                        result = cursor.execute(f"SHOW WAREHOUSES LIKE '{warehouse_escaped}'").fetchone()

                        if result:
                            # SHOW WAREHOUSES returns columns in specific order
                            # name, state, type, size, min_cluster_count, max_cluster_count,
                            # started_clusters, running, queued, is_default, is_current,
                            # auto_suspend, auto_resume, available, provisioning, quiescing,
                            # other, created_on, resumed_on, updated_on, owner, comment,
                            # enable_query_acceleration, query_acceleration_max_scale_factor,
                            # resource_monitor, actives, pendings, failed, suspended, uuid, scaling_policy

                            platform_info["compute_configuration"] = {
                                "warehouse_name": result[0] if len(result) > 0 else None,
                                "warehouse_state": result[1] if len(result) > 1 else None,
                                "warehouse_type": result[2] if len(result) > 2 else None,
                                "warehouse_size": result[3] if len(result) > 3 else None,
                                "min_cluster_count": result[4] if len(result) > 4 else None,
                                "max_cluster_count": result[5] if len(result) > 5 else None,
                                "auto_suspend": result[11] if len(result) > 11 else None,
                                "auto_resume": result[12] if len(result) > 12 else None,
                                "enable_query_acceleration": result[21] if len(result) > 21 else None,
                                "query_acceleration_max_scale_factor": result[22] if len(result) > 22 else None,
                                "scaling_policy": result[27] if len(result) > 27 else None,
                            }

                            self.logger.debug(
                                f"Successfully captured Snowflake warehouse metadata for {self.warehouse}"
                            )
                    except Exception as e:
                        platform_info["compute_configuration"] = self._unavailable_warehouse_metadata(e)
                        self.logger.debug(
                            f"Could not fetch Snowflake warehouse metadata (insufficient permissions or warehouse not found): {e}"
                        )

                # Try to get account parameters for edition info (best effort)
                try:
                    # Get organization name which can indicate edition
                    result = cursor.execute("SELECT current_account_name(), current_organization_name()").fetchone()
                    if result:
                        platform_info["configuration"]["account_name"] = result[0]
                        platform_info["configuration"]["organization_name"] = result[1]
                except Exception as e:
                    self.logger.debug(f"Could not query Snowflake account metadata: {e}")

            except Exception as e:
                self.logger.debug(f"Error collecting Snowflake platform info: {e}")
                if platform_info.get("platform_version") is None:
                    platform_info["platform_version"] = None
            finally:
                if cursor:
                    cursor.close()
        else:
            platform_info["platform_version"] = None

        return platform_info

    def get_normalized_result_metadata(
        self,
        *,
        connection: Any | None = None,
        platform_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return Snowflake-specific normalized cloud/runtime metadata."""
        info = dict(platform_info) if isinstance(platform_info, Mapping) else self.get_platform_info(connection)
        metadata = build_default_normalized_result_metadata(self, connection=connection, platform_info=info)
        config = info.get("configuration") if isinstance(info.get("configuration"), Mapping) else {}
        compute = info.get("compute_configuration") if isinstance(info.get("compute_configuration"), Mapping) else {}

        metadata["platform_deployment"] = self._snowflake_deployment_metadata(config)
        metadata["platform_cloud"] = self._snowflake_cloud_metadata(info, config)
        metadata["platform_compute"] = self._snowflake_compute_metadata(config, compute)
        metadata["platform_storage"] = self._snowflake_storage_metadata(config)
        return metadata

    @staticmethod
    def _unavailable_warehouse_metadata(exc: Exception) -> dict[str, Any]:
        return {
            "metadata_collection_status": "unavailable",
            "collection_error_class": type(exc).__name__,
            "collection_error_message": str(exc),
        }

    @staticmethod
    def _snowflake_deployment_metadata(config: Mapping[str, Any]) -> dict[str, Any]:
        return _compact_metadata(
            {
                "deployment_type": "managed_cloud",
                "connection_mode": "remote",
                "endpoint_class": "cloud_endpoint",
                "metadata_source": "observed" if config.get("account_name") else "requested",
                "collection_status": "partial",
                "role": config.get("role"),
                "database": config.get("database"),
                "schema": config.get("schema"),
            }
        )

    @staticmethod
    def _snowflake_cloud_metadata(info: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        provider = info.get("cloud_provider")
        region = info.get("cloud_region")
        account = config.get("account_name") or config.get("account")
        payload = {
            "provider": str(provider).lower() if provider else None,
            "region": region,
            "account": account,
            "organization": config.get("organization_name"),
            "source": "observed" if provider or region or config.get("account_name") else "requested",
            "collection_status": "partial" if account or provider or region else "unavailable",
        }
        return _compact_metadata(payload)

    @staticmethod
    def _snowflake_compute_metadata(config: Mapping[str, Any], compute: Mapping[str, Any]) -> dict[str, Any]:
        observed = any(
            compute.get(key) is not None
            for key in (
                "warehouse_state",
                "warehouse_type",
                "min_cluster_count",
                "max_cluster_count",
                "scaling_policy",
            )
        )
        collection_error = compute.get("collection_error_class")
        collection_status = "available" if observed else "partial"
        if collection_error and not (config.get("warehouse") or config.get("warehouse_size")):
            collection_status = "unavailable"

        payload = {
            "warehouse": compute.get("warehouse_name") or config.get("warehouse"),
            "warehouse_size": compute.get("warehouse_size") or config.get("warehouse_size"),
            "warehouse_type": compute.get("warehouse_type"),
            "warehouse_state": compute.get("warehouse_state"),
            "min_cluster_count": compute.get("min_cluster_count"),
            "max_cluster_count": compute.get("max_cluster_count"),
            "auto_suspend": compute.get("auto_suspend")
            if compute.get("auto_suspend") is not None
            else config.get("auto_suspend"),
            "auto_resume": compute.get("auto_resume")
            if compute.get("auto_resume") is not None
            else config.get("auto_resume"),
            "multi_cluster_warehouse": config.get("multi_cluster_warehouse"),
            "query_acceleration_enabled": compute.get("enable_query_acceleration"),
            "query_acceleration_max_scale_factor": compute.get("query_acceleration_max_scale_factor"),
            "scaling_policy": compute.get("scaling_policy"),
            "result_cache_enabled": config.get("result_cache_enabled"),
            "source": "observed" if observed else "requested",
            "collection_status": collection_status,
            "collection_error_class": collection_error,
            "collection_error_message": compute.get("collection_error_message"),
        }
        return _compact_metadata(payload)

    @staticmethod
    def _snowflake_storage_metadata(config: Mapping[str, Any]) -> dict[str, Any]:
        payload = {
            "table_format": config.get("file_format"),
            "staging_location": config.get("staging_root"),
            "compression": config.get("compression"),
            "source": "requested",
            "collection_status": "partial"
            if config.get("file_format") or config.get("staging_root") or config.get("compression")
            else "unavailable",
        }
        return _compact_metadata(payload)

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Snowflake."""
        return "snowflake"

    def _get_connection_params(self, **connection_config) -> dict[str, Any]:
        """Get standardized connection parameters."""
        return {
            "account": connection_config.get("account", self.account),
            "username": connection_config.get("username", self.username),
            "password": connection_config.get("password", self.password),
            "warehouse": connection_config.get("warehouse", self.warehouse),
            "role": connection_config.get("role", self.role),
        }

    def _create_admin_connection(self, **connection_config) -> Any:
        """Create Snowflake connection for admin operations."""
        params = self._get_connection_params(**connection_config)

        return snowflake.connector.connect(
            **params,
            client_session_keep_alive=True,
            login_timeout=30,
            network_timeout=60,
            # Don't specify database for admin operations
        )

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if database exists in Snowflake account.

        Also checks for existing schemas and tables, since they may exist from a
        previous run even if the database doesn't formally exist at account level.
        """
        try:
            connection = self._create_admin_connection(**connection_config)
            cursor = connection.cursor()

            database = connection_config.get("database", self.database)
            schema = connection_config.get("schema", self.schema)

            # Check if database exists at account level
            cursor.execute("SHOW DATABASES")
            databases = [row[1] for row in cursor.fetchall()]  # Database name is in column 1

            if database.upper() in [db.upper() for db in databases]:
                return True

            # Even if database doesn't formally exist, check if schema/tables exist
            # (they might exist from previous run where database/schema were created)
            try:
                # Quote identifiers and escape LIKE patterns for SQL safety
                cursor.execute(f'USE DATABASE "{database}"')
                schema_escaped = schema.replace("'", "''")
                cursor.execute(f"SHOW SCHEMAS LIKE '{schema_escaped}'")
                schemas = cursor.fetchall()

                if schemas:
                    # Schema exists - check for tables
                    cursor.execute(f'USE SCHEMA "{schema}"')
                    cursor.execute("SHOW TABLES")
                    tables = cursor.fetchall()

                    if tables:
                        # Tables exist - database should be considered as existing
                        return True
            except Exception:
                # Database or schema don't exist
                pass

            return False

        except Exception:
            # If we can't connect or check, assume database doesn't exist
            return False
        finally:
            if "connection" in locals() and connection:
                connection.close()

    def drop_database(self, **connection_config) -> None:
        """Drop database in Snowflake account."""
        database = connection_config.get("database", self.database)
        try:
            connection = self._create_admin_connection(**connection_config)
            cursor = connection.cursor()

            # Drop database and all its schemas/tables (quote identifier for SQL safety)
            cursor.execute(f'DROP DATABASE IF EXISTS "{database}"')

        except Exception as e:
            raise RuntimeError(f"Failed to drop Snowflake database {database}: {e}") from e
        finally:
            if "connection" in locals() and connection:
                connection.close()

    def create_connection(self, **connection_config) -> Any:
        """Create optimized Snowflake connection."""
        self.log_operation_start("Snowflake connection")

        self.log_verbose("Creating Snowflake connection")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        # Get connection parameters
        params = self._get_connection_params(**connection_config)
        self.log_very_verbose(
            f"Snowflake connection params: account={params.get('account')}, database={connection_config.get('database', self.database)}"
        )
        database = connection_config.get("database", self.database)
        schema = connection_config.get("schema", self.schema)

        try:
            # Prepare connection parameters
            self.log_verbose(f"Connecting to Snowflake account: {params['account']}")
            conn_params = {
                "account": params["account"],
                "user": params["username"],  # Snowflake uses 'user' not 'username'
                "password": params["password"],
                "warehouse": params["warehouse"],
                "database": database,
                "schema": schema,
                "application": "BenchBox",
                "timezone": self.timezone,
                "autocommit": True,
            }

            if params["role"]:
                conn_params["role"] = params["role"]
                self.log_very_verbose(f"Using role: {params['role']}")

            # Handle different authentication methods
            if self.authenticator != "snowflake":
                self.log_very_verbose(f"Using authenticator: {self.authenticator}")
                conn_params["authenticator"] = self.authenticator

            if self.private_key_path:
                # Key pair authentication
                self.log_verbose("Using key pair authentication")
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.serialization import (
                    load_pem_private_key,
                )

                with open(self.private_key_path, "rb") as key_file:
                    private_key = load_pem_private_key(
                        key_file.read(),
                        password=self.private_key_passphrase.encode() if self.private_key_passphrase else None,
                    )

                pkb = private_key.private_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )

                conn_params["private_key"] = pkb
                del conn_params["password"]  # Exclude password when using key pair

            # Create connection
            connection = snowflake.connector.connect(**conn_params)

            # Test connection
            self.log_verbose("Testing Snowflake connection")
            cursor = connection.cursor()
            cursor.execute("SELECT CURRENT_VERSION()")
            cursor.fetchall()
            cursor.close()

            self.log_verbose(f"Connected to Snowflake account: {self.account}")
            self.log_verbose(f"Using warehouse: {self.warehouse}, database: {self.database}, schema: {self.schema}")

            self.log_operation_complete(
                "Snowflake connection", details=f"Connected to account {self.account}, database: {self.database}"
            )

            return connection

        except Exception as e:
            self.logger.error(f"Failed to connect to Snowflake: {e}")
            raise

    def _should_skip_schema_creation(self, benchmark, connection: Any) -> bool:
        """Check if schema already exists with data, allowing us to skip recreation.

        This prevents dropping/recreating tables which would:
        1. Remove internal stages (@%TABLE)
        2. Delete uploaded files
        3. Force expensive re-uploads

        Args:
            benchmark: Benchmark instance
            connection: Snowflake connection

        Returns:
            True if all expected tables exist with data, False otherwise
        """
        try:
            cursor = connection.cursor()

            # Get expected tables from benchmark
            expected_tables = self._get_expected_tables(benchmark)
            if not expected_tables:
                return False  # Can't determine, recreate to be safe

            # Check each table exists and has data
            for table_name in expected_tables:
                table_upper = table_name.upper()

                # Check if table exists
                cursor.execute(f"SHOW TABLES LIKE '{table_upper}'")
                if not cursor.fetchone():
                    self.log_verbose(f"Table {table_upper} missing - schema creation required")
                    return False

                # Check if table has data
                cursor.execute(f"SELECT COUNT(*) FROM {table_upper}")
                row_count = cursor.fetchone()[0]
                if row_count == 0:
                    self.log_verbose(f"Table {table_upper} empty - schema creation required")
                    return False

            self.log_verbose(f"All {len(expected_tables)} tables exist with data - skipping schema creation")
            return True

        except Exception as e:
            self.log_very_verbose(f"Schema check failed: {e} - proceeding with creation")
            return False  # If check fails, recreate to be safe

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using Snowflake table definitions."""
        self.log_operation_start("Snowflake schema creation")
        start_time = mono_time()

        self.log_verbose(f"Creating schema for benchmark: {benchmark.__class__.__name__}")
        self.log_very_verbose(f"Target database: {self.database}, schema: {self.schema}")

        cursor = connection.cursor()

        try:
            # Ensure database and schema exist
            self.log_verbose(f"Creating/using database: {self.database}")
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.database}")
            cursor.execute(f"USE DATABASE {self.database}")

            self.log_verbose(f"Creating/using schema: {self.schema}")
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            cursor.execute(f"USE SCHEMA {self.schema}")

            # Check if we can skip table creation (tables exist with data)
            if self._should_skip_schema_creation(benchmark, connection):
                elapsed_time = elapsed_seconds(start_time)
                self.log_operation_complete(
                    "Snowflake schema creation", details=f"Skipped (existing data is valid) in {elapsed_time:.2f}s"
                )
                return elapsed_time

            # Set query tag for tracking
            self.log_very_verbose(f"Setting query tag: {self.query_tag}_schema_creation")
            cursor.execute(f"ALTER SESSION SET QUERY_TAG = '{self.query_tag}_schema_creation'")

            # Use common schema creation helper
            self.log_very_verbose("Retrieving schema SQL from benchmark")
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

            # Split schema into individual statements and execute
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            self.log_verbose(f"Executing {len(statements)} schema statements")

            for i, statement in enumerate(statements, 1):
                # Optimize table definition for Snowflake
                optimized_statement = self._optimize_table_definition(statement)
                self.log_very_verbose(f"Executing statement {i}/{len(statements)}: {optimized_statement[:100]}...")
                cursor.execute(optimized_statement)

            self.log_verbose("Schema created successfully")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise
        finally:
            cursor.close()

        elapsed_time = elapsed_seconds(start_time)
        self.log_operation_complete("Snowflake schema creation", details=f"Completed in {elapsed_time:.2f}s")
        return elapsed_time

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using Snowflake PUT and COPY INTO commands."""
        self.log_operation_start("Snowflake data loading")

        self.log_verbose(f"Starting data loading for benchmark: {benchmark.__class__.__name__}")
        self.log_very_verbose(f"Data directory: {data_dir}")

        start_time = mono_time()
        table_stats = {}
        total_time = 0.0

        cursor = connection.cursor()

        try:
            # Set query tag for tracking
            self.log_very_verbose(f"Setting query tag: {self.query_tag}_data_loading")
            cursor.execute(f"ALTER SESSION SET QUERY_TAG = '{self.query_tag}_data_loading'")

            self._create_load_file_formats(cursor)
            data_source = self._resolve_data_files(benchmark, data_dir)

            # Load data for each table (handle multi-chunk files)
            for table_name, file_paths in data_source.tables.items():
                valid_files = self._normalize_existing_files(file_paths)

                if not valid_files:
                    self.logger.warning(f"Skipping {table_name} - no valid data files")
                    table_stats[table_name] = 0
                    continue

                chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
                self.log_verbose(f"Loading data for table: {table_name}{chunk_info}")

                try:
                    load_start = mono_time()
                    table_name_upper = table_name.upper()
                    actual_count = self._load_table_from_stage(
                        cursor, table_name, table_name_upper, valid_files, data_source, benchmark
                    )
                    table_stats[table_name_upper] = actual_count

                    effective_tuning = self.get_effective_tuning_configuration()
                    if effective_tuning is not None:
                        self.apply_ctas_sort(table_name_upper, effective_tuning, connection)

                    load_time = elapsed_seconds(load_start)
                    self.log_verbose(
                        f"✅ Loaded {actual_count:,} rows into {table_name_upper}{chunk_info} in {load_time:.2f}s"
                    )

                except Exception as e:
                    self.logger.error(f"Failed to load {table_name}: {str(e)[:100]}...")
                    table_stats[table_name.upper()] = 0

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.log_verbose(f"✅ Loaded {total_rows:,} total rows in {total_time:.2f}s")
            self.log_operation_complete(
                "Snowflake data loading", details=f"Loaded {total_rows:,} rows in {total_time:.2f}s"
            )

        except Exception as e:
            self.logger.error(f"Data loading failed: {e}")
            raise
        finally:
            cursor.close()

        # Snowflake doesn't provide detailed per-table timings yet
        return table_stats, total_time, None

    def validate_external_table_requirements(self) -> None:
        """Validate required cloud staging configuration for external table mode."""
        if not self.staging_root:
            raise ValueError(
                "Snowflake external mode requires --platform-option staging_root=<cloud-uri> "
                "(for example s3://bucket/path, gs://bucket/path, or azure://container/path)."
            )

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Register external tables backed by cloud storage via a named external stage."""
        self.validate_external_table_requirements()
        assert self.staging_root is not None

        self.log_operation_start("Snowflake external table registration")
        start_time = mono_time()
        table_stats: dict[str, int] = {}
        cursor = connection.cursor()

        stage_name = f"{self.schema}.BENCHBOX_EXTERNAL_STAGE"
        stage_root = self.staging_root.rstrip("/").replace("'", "''")

        try:
            data_source = self._resolve_data_files(benchmark, data_dir)

            cursor.execute(f"CREATE STAGE IF NOT EXISTS {stage_name} URL='{stage_root}'")

            for table_name, file_paths in data_source.tables.items():
                table_name_upper = table_name.upper()
                table_path = f"{self.database.lower()}/{table_name.lower()}/"
                source_format = self._detect_external_table_format(file_paths)
                if source_format == "iceberg":
                    if not self.iceberg_external_volume:
                        raise ValueError(
                            "Snowflake Iceberg external mode requires --platform-option iceberg_external_volume=<name>."
                        )
                    stage_path = get_cloud_path_info(self.staging_root).get("path", "").strip("/")
                    base_location = f"{stage_path}/{table_path}".strip("/") if stage_path else table_path.strip("/")
                    cursor.execute(f"""
                        CREATE OR REPLACE ICEBERG TABLE {table_name_upper}
                        EXTERNAL_VOLUME = '{self.iceberg_external_volume.replace("'", "''")}'
                        CATALOG = '{self.iceberg_catalog.replace("'", "''")}'
                        BASE_LOCATION = '{base_location.replace("'", "''")}'
                    """)
                else:
                    table_clause = (
                        f"TABLE_FORMAT={self.delta_table_format}"
                        if source_format == "delta"
                        else "FILE_FORMAT=(TYPE=PARQUET)"
                    )
                    cursor.execute(f"""
                        CREATE OR REPLACE EXTERNAL TABLE {table_name_upper}
                        WITH LOCATION=@{stage_name}/{table_path}
                        {table_clause}
                        AUTO_REFRESH=FALSE
                    """)
                    cursor.execute(f"ALTER EXTERNAL TABLE {table_name_upper} REFRESH")
                cursor.execute(f"SELECT COUNT(*) FROM {table_name_upper}")
                result = cursor.fetchone()
                table_stats[table_name_upper] = int(result[0]) if result else 0

        finally:
            cursor.close()

        total_time = elapsed_seconds(start_time)
        self.log_operation_complete("Snowflake external table registration", details=f"{len(table_stats)} tables")
        return table_stats, total_time, None

    @staticmethod
    def _detect_external_table_format(file_paths: Any) -> str:
        """Detect Snowflake external-table source format from file paths."""
        paths = file_paths if isinstance(file_paths, list) else [file_paths]
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_dir():
                continue
            if (path / "_delta_log").is_dir():
                return "delta"
            if (path / "metadata").is_dir():
                return "iceberg"
        return "parquet"

    def _create_load_file_formats(self, cursor: Any) -> None:
        """Create Snowflake file formats used by COPY INTO operations."""
        self.log_verbose("Creating file formats for data loading")
        cursor.execute(f"""
            CREATE OR REPLACE FILE FORMAT {self.schema}.BENCHBOX_CSV_FORMAT
            TYPE = 'CSV'
            FIELD_DELIMITER = ','
            RECORD_DELIMITER = '\\n'
            SKIP_HEADER = 0
            ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE
            REPLACE_INVALID_CHARACTERS = TRUE
            EMPTY_FIELD_AS_NULL = TRUE
            COMPRESSION = '{self.compression}'
        """)
        cursor.execute(f"""
            CREATE OR REPLACE FILE FORMAT {self.schema}.BENCHBOX_TBL_FORMAT
            TYPE = 'CSV'
            FIELD_DELIMITER = '|'
            RECORD_DELIMITER = '\\n'
            SKIP_HEADER = 0
            ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE
            REPLACE_INVALID_CHARACTERS = TRUE
            EMPTY_FIELD_AS_NULL = TRUE
            COMPRESSION = '{self.compression}'
        """)

    def _resolve_data_files(self, benchmark: Any, data_dir: Path) -> DataSource:
        """Resolve benchmark data files from benchmark tables or manifest."""
        return resolve_adapter_data_source(self, benchmark, data_dir)

    _normalize_existing_files = staticmethod(normalize_existing_files)

    def _get_file_format_for_table(
        self,
        table_name: str,
        first_file: Path,
        data_source: DataSource,
        benchmark: Any,
    ) -> str:
        """Select Snowflake file format object based on resolved CSV dialect."""
        dialect = resolve_csv_dialect(data_source, table_name, first_file, benchmark)
        if dialect.null_marker is not None:
            self.log_very_verbose(f"Using TBL file format for {table_name}")
            return f"{self.schema}.BENCHBOX_TBL_FORMAT"
        self.log_very_verbose(f"Using CSV file format for {table_name}")
        return f"{self.schema}.BENCHBOX_CSV_FORMAT"

    def _parse_copy_results(self, copy_results: list[Any]) -> None:
        """Log per-file COPY INTO warnings while tolerating parse failures."""
        for row in copy_results:
            if len(row) <= 3:
                continue

            status = str(row[1]) if len(row) > 1 else "UNKNOWN"
            try:
                loaded = int(row[3])
            except (ValueError, TypeError) as e:
                self.logger.warning(f"Could not parse rows_loaded from COPY result: {e}")
                continue

            if status == "LOADED":
                continue

            file_name = str(row[0]) if len(row) > 0 else "unknown"
            error_msg = str(row[5]) if len(row) > 5 and row[5] else "No error message provided"
            self.logger.warning(f"File {file_name} status: {status}, loaded {loaded} rows. Error: {error_msg}")

    def _load_table_from_stage(
        self,
        cursor: Any,
        table_name: str,
        table_name_upper: str,
        valid_files: list[Path],
        data_source: DataSource | None = None,
        benchmark: Any = None,
    ) -> int:
        """Upload table files to stage, COPY INTO target table, and return actual row count."""
        stage_name = f"@%{table_name_upper}"
        self.log_very_verbose(f"Using stage: {stage_name}")

        for file_idx, file_path in enumerate(valid_files):
            chunk_msg = f" (chunk {file_idx + 1}/{len(valid_files)})" if len(valid_files) > 1 else ""
            self.log_very_verbose(f"Uploading file{chunk_msg} with PUT: {file_path.name}")
            cursor.execute(f"PUT file://{file_path.absolute()} {stage_name}")

        ds = data_source or DataSource(source_type="snowflake_stage", tables={})
        bm = benchmark if benchmark is not None else NO_BENCHMARK
        file_format = self._get_file_format_for_table(table_name, valid_files[0], ds, bm)
        copy_command = f"""
            COPY INTO {table_name_upper}
            FROM {stage_name}
            FILE_FORMAT = (FORMAT_NAME = '{file_format}')
            ON_ERROR = 'CONTINUE'
            PURGE = TRUE
        """
        self.log_very_verbose(f"Executing COPY INTO for {table_name_upper}")
        cursor.execute(copy_command)
        self._parse_copy_results(cursor.fetchall())

        cursor.execute(f"SELECT COUNT(*) FROM {table_name_upper}")
        return cursor.fetchone()[0]

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Snowflake-specific optimizations based on benchmark type."""

        cursor = connection.cursor()

        try:
            # Set query tag for tracking
            cursor.execute(f"ALTER SESSION SET QUERY_TAG = '{self.query_tag}_optimization'")

            # Base optimizations
            session_settings = [
                f"ALTER SESSION SET TIMEZONE = '{self.timezone}'",
                "ALTER SESSION SET AUTOCOMMIT = TRUE",
            ]

            # Only suppress nondeterministic errors if explicitly enabled
            # TPC-H/TPC-DS don't use MERGE/UPDATE so this is unnecessary for standard benchmarks
            if self.suppress_nondeterministic_errors:
                session_settings.extend(
                    [
                        "ALTER SESSION SET ERROR_ON_NONDETERMINISTIC_MERGE = FALSE",
                        "ALTER SESSION SET ERROR_ON_NONDETERMINISTIC_UPDATE = FALSE",
                    ]
                )

            if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
                # OLAP-specific optimizations
                # Use FALSE for result cache to ensure accurate benchmark measurements
                cache_setting = "FALSE" if self.disable_result_cache else "TRUE"
                session_settings.extend(
                    [
                        "ALTER SESSION SET QUERY_ACCELERATION_MAX_SCALE_FACTOR = 8",
                        f"ALTER SESSION SET USE_CACHED_RESULT = {cache_setting}",
                        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 1800",  # 30 minutes
                    ]
                )

                # Warehouse optimizations (only if modify_warehouse_settings is True)
                # These ALTER WAREHOUSE changes PERSIST beyond the benchmark run
                if self.modify_warehouse_settings:
                    if self.multi_cluster_warehouse:
                        cursor.execute(f"""
                            ALTER WAREHOUSE {self.warehouse} SET
                            MIN_CLUSTER_COUNT = 1
                            MAX_CLUSTER_COUNT = 3
                            AUTO_SUSPEND = {self.auto_suspend}
                            AUTO_RESUME = {self.auto_resume}
                            SCALING_POLICY = 'STANDARD'
                        """)
                    else:
                        cursor.execute(f"""
                            ALTER WAREHOUSE {self.warehouse} SET
                            WAREHOUSE_SIZE = '{self.warehouse_size}'
                            AUTO_SUSPEND = {self.auto_suspend}
                            AUTO_RESUME = {self.auto_resume}
                        """)
                else:
                    self.logger.info("Warehouse modifications skipped (modify_warehouse_settings=False)")

            # Apply session settings
            critical_failures = []
            for setting in session_settings:
                try:
                    cursor.execute(setting)
                    self.logger.debug(f"Applied setting: {setting}")
                except Exception as e:
                    # Track if critical cache control setting failed
                    if "USE_CACHED_RESULT" in setting:
                        critical_failures.append(setting)
                    self.logger.warning(f"Failed to apply setting {setting}: {e}")

            # Enable warehouse
            cursor.execute(f"USE WAREHOUSE {self.warehouse}")

            # Validate cache control settings were successfully applied
            if self.disable_result_cache or critical_failures:
                self.logger.debug("Validating cache control settings...")
                validation_result = self.validate_session_cache_control(connection)

                if not validation_result["validated"]:
                    self.logger.warning(f"Cache control validation failed: {validation_result.get('errors', [])}")
                else:
                    self.logger.info(
                        f"Cache control validated successfully: cache_disabled={validation_result['cache_disabled']}"
                    )

        finally:
            cursor.close()

    def validate_session_cache_control(self, connection: Any) -> dict[str, Any]:
        """Validate that session-level cache control settings were successfully applied.

        Args:
            connection: Active Snowflake database connection

        Returns:
            dict with:
                - validated: bool - Whether validation passed
                - cache_disabled: bool - Whether cache is actually disabled
                - settings: dict - Actual session settings
                - warnings: list[str] - Any validation warnings
                - errors: list[str] - Any validation errors

        Raises:
            ConfigurationError: If cache control validation fails and strict_validation=True
        """
        from benchbox.platforms.cloud_shared import validate_session_cache_control

        return validate_session_cache_control(
            connection=connection,
            query="SELECT SYSTEM$GET_SESSION_PARAMETER('USE_CACHED_RESULT') as value",
            setting_key="USE_CACHED_RESULT",
            disabled_value="FALSE",
            enabled_value="TRUE",
            normalize="upper",
            platform_name="Snowflake",
            disable_result_cache=self.disable_result_cache,
            strict_validation=self.strict_validation,
            adapter_logger=self.logger,
        )

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute query with detailed timing and performance tracking."""
        self.log_operation_start("Snowflake query execution", query_id)
        self.log_very_verbose(f"Executing query {query_id}: {query[:100]}...")

        start_time = mono_time()

        cursor = connection.cursor()

        try:
            # Set query tag for tracking
            self.log_very_verbose(f"Setting query tag: {self.query_tag}_{query_id}")
            cursor.execute(f"ALTER SESSION SET QUERY_TAG = '{self.query_tag}_{query_id}'")

            # Execute the query
            # Note: Query dialect translation is now handled automatically by the base adapter
            self.log_verbose(f"Executing query {query_id} on Snowflake")
            cursor.execute(query)
            result = cursor.fetchall()

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result) if result else 0

            # Get query history for performance metrics
            query_stats = self._get_query_statistics(connection, query_id)

            # Validate row count if enabled and benchmark type is provided
            validation_result = None
            if validate_row_count and benchmark_type:
                from benchbox.core.validation.query_validation import QueryValidator

                validator = QueryValidator()
                validation_result = validator.validate_query_result(
                    benchmark_type=benchmark_type,
                    query_id=query_id,
                    actual_row_count=actual_row_count,
                    scale_factor=scale_factor,
                    stream_id=stream_id,
                )

                # Log validation result
                if validation_result.warning_message:
                    self.log_verbose(f"Row count validation: {validation_result.warning_message}")
                elif not validation_result.is_valid:
                    self.log_verbose(f"Row count validation FAILED: {validation_result.error_message}")
                else:
                    self.log_very_verbose(
                        f"Row count validation PASSED: {actual_row_count} rows "
                        f"(expected: {validation_result.expected_row_count})"
                    )

            # Use base helper to build result with consistent validation field mapping
            result_dict = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=result[0] if result else None,
                validation_result=validation_result,
            )

            # Include Snowflake-specific fields
            result_dict["translated_query"] = None  # Translation handled by base adapter
            result_dict["query_statistics"] = query_stats
            # Map query_statistics to resource_usage for cost calculation
            result_dict["resource_usage"] = query_stats

            # Log completion based on final status
            if result_dict["status"] == "FAILED":
                self.log_operation_complete("Snowflake query execution", query_id, "FAILED: validation error")
            else:
                self.log_verbose(f"Query {query_id} completed: {actual_row_count} rows in {execution_time:.3f}s")
                self.log_operation_complete("Snowflake query execution", query_id, f"returned {actual_row_count} rows")

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            self.log_verbose(f"Query {query_id} failed after {execution_time:.3f}s: {e}")
            self.log_operation_complete("Snowflake query execution", query_id, f"FAILED: {e}")

            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            cursor.close()

        # Capture the structured query plan outside the try/except so a strict-mode
        # PlanCaptureError propagates instead of being mislabeled as a failed query.
        # The helper is a no-op when capture_plans is False (no extra EXPLAIN issued).
        self._merge_plan_capture_into_result(result_dict, connection, query, query_id)
        return result_dict

    def get_query_plan(self, connection: Any, query: str) -> str | None:
        """Return the Snowflake query plan as JSON via ``EXPLAIN USING JSON``.

        Snowflake has no plain text EXPLAIN suitable for structured parsing;
        ``EXPLAIN USING JSON`` returns a single-cell JSON document describing the
        plan (``GlobalStats`` + ``Operations``) which SnowflakeQueryPlanParser
        consumes. Returns None on failure so capture degrades gracefully.
        """
        cursor = connection.cursor()
        try:
            cursor.execute(f"EXPLAIN USING JSON {query}")
            rows = cursor.fetchall()
            if not rows or not rows[0]:
                return None
            # The JSON document is returned in the first column of the first row.
            return str(rows[0][0])
        except Exception as e:
            self.logger.debug(f"Failed to get Snowflake query plan: {e}")
            return None
        finally:
            cursor.close()

    def get_query_plan_parser(self):
        """Return the Snowflake query plan parser."""
        from benchbox.core.query_plans.parsers.snowflake import SnowflakeQueryPlanParser

        return SnowflakeQueryPlanParser()

    def _optimize_table_definition(self, statement: str) -> str:
        """Optimize table definition for Snowflake.

        Makes tables idempotent by using CREATE OR REPLACE TABLE.
        """
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # Ensure idempotency with OR REPLACE (defense-in-depth)
        if "CREATE TABLE" in statement and "OR REPLACE" not in statement.upper():
            statement = statement.replace("CREATE TABLE", "CREATE OR REPLACE TABLE", 1)

        # Snowflake automatically optimizes most aspects, but we can add clustering keys
        # This is a simplified heuristic - in production would be more sophisticated
        if "CLUSTER BY" not in statement.upper():
            # Include clustering on first column (simple heuristic)
            # Snowflake will auto-cluster in most cases anyway
            pass

        return statement

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables using Snowflake SHOW TABLES command.

        Args:
            connection: Snowflake connection

        Returns:
            List of table names (lowercase, normalized for case-insensitive comparison)
        """
        try:
            cursor = connection.cursor()
            cursor.execute("SHOW TABLES")
            # SHOW TABLES returns: created_on, name, database_name, schema_name, kind, ...
            # Table name is in column index 1
            # Normalize to lowercase since Snowflake is case-insensitive but stores uppercase,
            # while benchmarks expect lowercase names
            tables = [row[1].lower() for row in cursor.fetchall()]
            return tables
        except Exception:
            # Fallback to base implementation if SHOW TABLES fails
            return []

    def _validate_data_integrity(
        self, benchmark, connection: Any, table_stats: dict[str, int]
    ) -> tuple[str, dict[str, Any]]:
        """Validate basic data integrity checks using Snowflake cursor pattern.

        Snowflake connections require cursor-based execution, unlike the base
        adapter which assumes connection.execute() exists.

        Args:
            benchmark: Benchmark instance
            connection: Snowflake connection
            table_stats: Dictionary of table names to row counts

        Returns:
            Tuple of (status, validation_details)
        """
        validation_details = {}

        try:
            # Verify tables are accessible using Snowflake cursor
            accessible_tables = []
            inaccessible_tables = []

            cursor = connection.cursor()
            for table_name in table_stats:
                try:
                    # Try a simple SELECT to verify table is accessible
                    # table_stats has uppercase keys from Snowflake
                    cursor.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
                    cursor.fetchone()  # Consume the result to prevent resource leaks
                    accessible_tables.append(table_name)
                except Exception:
                    inaccessible_tables.append(table_name)

            if inaccessible_tables:
                validation_details["inaccessible_tables"] = inaccessible_tables
                validation_details["constraints_enabled"] = False
                return "FAILED", validation_details
            else:
                validation_details["accessible_tables"] = accessible_tables
                validation_details["constraints_enabled"] = True
                return "PASSED", validation_details

        except Exception as e:
            validation_details["constraints_enabled"] = False
            validation_details["integrity_error"] = str(e)
            return "FAILED", validation_details

    def _get_query_statistics(
        self, connection: Any, query_id: str, max_retries: int = 3, initial_delay: float = 0.5
    ) -> dict[str, Any]:
        """Get detailed query statistics from Snowflake query history.

        Snowflake query history may not be immediately available after query execution.
        This method implements retry logic with exponential backoff to handle delayed
        statistics availability.

        Args:
            connection: Snowflake connection
            query_id: Query identifier to look up in history
            max_retries: Maximum number of retry attempts (default: 3)
            initial_delay: Initial delay in seconds between retries (default: 0.5s)

        Returns:
            Dictionary with query statistics or note if not available
        """
        import time as time_module

        cursor = connection.cursor()
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Query the QUERY_HISTORY view for performance metrics
                cursor.execute(f"""
                    SELECT
                        QUERY_ID,
                        QUERY_TEXT,
                        TOTAL_ELAPSED_TIME,
                        EXECUTION_TIME,
                        COMPILATION_TIME,
                        BYTES_SCANNED,
                        BYTES_WRITTEN,
                        BYTES_SPILLED_TO_LOCAL_STORAGE,
                        BYTES_SPILLED_TO_REMOTE_STORAGE,
                        ROWS_PRODUCED,
                        ROWS_EXAMINED,
                        CREDITS_USED_CLOUD_SERVICES,
                        WAREHOUSE_SIZE,
                        CLUSTER_NUMBER
                    FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                        END_TIME_RANGE_START => DATEADD('MINUTE', -5, CURRENT_TIMESTAMP()),
                        END_TIME_RANGE_END => CURRENT_TIMESTAMP()
                    ))
                    WHERE QUERY_TAG LIKE '%{query_id}%'
                    ORDER BY START_TIME DESC
                    LIMIT 1
                """)

                result = cursor.fetchone()

                if result:
                    # Statistics available
                    cursor.close()
                    return {
                        "snowflake_query_id": result[0],
                        "total_elapsed_time_ms": result[2],
                        "execution_time_ms": result[3],
                        "compilation_time_ms": result[4],
                        "bytes_scanned": result[5],
                        "bytes_written": result[6],
                        "bytes_spilled_local": result[7],
                        "bytes_spilled_remote": result[8],
                        "rows_produced": result[9],
                        "rows_examined": result[10],
                        "credits_used": result[11],
                        "warehouse_size": result[12],
                        "cluster_number": result[13],
                        "retrieval_attempts": attempt + 1,
                    }
                else:
                    # Statistics not yet available
                    if attempt < max_retries:
                        # Retry with exponential backoff
                        delay = initial_delay * (2**attempt)
                        self.logger.debug(
                            f"Query statistics not yet available for {query_id}, "
                            f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})"
                        )
                        time_module.sleep(delay)
                    else:
                        # Max retries reached
                        cursor.close()
                        return {
                            "note": f"Query statistics not available after {max_retries + 1} attempts. "
                            "Statistics may appear in query history later.",
                            "retrieval_attempts": max_retries + 1,
                        }

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = initial_delay * (2**attempt)
                    self.logger.debug(
                        f"Error retrieving query statistics for {query_id}: {e}, "
                        f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time_module.sleep(delay)
                else:
                    cursor.close()
                    return {
                        "statistics_error": str(last_error),
                        "retrieval_attempts": max_retries + 1,
                    }

        cursor.close()
        return {"note": "Query statistics not yet available", "retrieval_attempts": max_retries + 1}

    def _get_platform_metadata(self, connection: Any) -> dict[str, Any]:
        """Get Snowflake-specific metadata and system information."""
        metadata = {
            "platform": self.platform_name,
            "account": self.account,
            "warehouse": self.warehouse,
            "database": self.database,
            "schema": self.schema,
            "result_cache_enabled": not self.disable_result_cache,
        }

        cursor = connection.cursor()

        try:
            # Get Snowflake version
            cursor.execute("SELECT CURRENT_VERSION()")
            result = cursor.fetchone()
            metadata["snowflake_version"] = result[0] if result else "unknown"

            # Get current session information
            cursor.execute("""
                SELECT
                    CURRENT_USER(),
                    CURRENT_ROLE(),
                    CURRENT_WAREHOUSE(),
                    CURRENT_DATABASE(),
                    CURRENT_SCHEMA(),
                    CURRENT_REGION(),
                    CURRENT_ACCOUNT()
            """)
            result = cursor.fetchone()
            if result:
                metadata["session_info"] = {
                    "current_user": result[0],
                    "current_role": result[1],
                    "current_warehouse": result[2],
                    "current_database": result[3],
                    "current_schema": result[4],
                    "current_region": result[5],
                    "current_account": result[6],
                }

            # Get warehouse information
            cursor.execute(f"""
                SHOW WAREHOUSES LIKE '{self.warehouse}'
            """)
            wh_result = cursor.fetchall()
            if wh_result:
                wh_info = wh_result[0]
                metadata["warehouse_info"] = {
                    "name": wh_info[0],
                    "state": wh_info[1],
                    "type": wh_info[2],
                    "size": wh_info[3],
                    "min_cluster_count": wh_info[4],
                    "max_cluster_count": wh_info[5],
                    "started_clusters": wh_info[6],
                    "running": wh_info[7],
                    "queued": wh_info[8],
                    "auto_suspend": wh_info[12],
                    "auto_resume": wh_info[13],
                    "available": wh_info[14],
                    "provisioning": wh_info[15],
                    "quiescing": wh_info[16],
                    "other": wh_info[17],
                    "created_on": wh_info[18],
                    "resumed_on": wh_info[19],
                    "updated_on": wh_info[20],
                    "owner": wh_info[21],
                    "comment": wh_info[22],
                    "scaling_policy": wh_info[25] if len(wh_info) > 25 else None,
                }

            # Get table information
            cursor.execute(f"""
                SELECT
                    TABLE_NAME,
                    ROW_COUNT,
                    BYTES,
                    RETENTION_TIME,
                    CREATED,
                    LAST_ALTERED,
                    CLUSTERING_KEY
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = '{self.schema}'
                AND TABLE_TYPE = 'BASE TABLE'
            """)
            tables = cursor.fetchall()
            metadata["tables"] = [
                {
                    "table_name": row[0],
                    "row_count": row[1],
                    "bytes": row[2],
                    "retention_time": row[3],
                    "created": row[4].isoformat() if row[4] else None,
                    "last_altered": row[5].isoformat() if row[5] else None,
                    "clustering_key": row[6],
                }
                for row in tables
            ]

        except Exception as e:
            metadata["metadata_error"] = str(e)
        finally:
            cursor.close()

        return metadata

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Trigger table analysis for better query optimization."""
        cursor = connection.cursor()
        try:
            # Snowflake automatically maintains statistics, but we can trigger clustering
            cursor.execute(f"ALTER TABLE {table_name.upper()} RECLUSTER")
            self.logger.info(f"Triggered reclustering for table {table_name.upper()}")
        except Exception as e:
            self.logger.warning(f"Failed to recluster table {table_name}: {e}")
        finally:
            cursor.close()

    def close_connection(self, connection: Any) -> None:
        """Close Snowflake connection."""
        try:
            if connection and hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            self.logger.warning(f"Error closing connection: {e}")

    _supported_tuning_type_names = ("CLUSTERING", "PARTITIONING")

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate Snowflake-specific tuning clauses for CREATE TABLE statements.

        Snowflake supports:
        - CLUSTER BY (column1, column2, ...) for clustering keys
        - Micro-partitions are automatic based on ingestion order and clustering

        Args:
            table_tuning: The tuning configuration for the table

        Returns:
            SQL clause string to be appended to CREATE TABLE statement
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""

        clauses = []

        try:
            # Import here to avoid circular imports
            from benchbox.core.tuning.interface import TuningType

            # Handle clustering - primary tuning mechanism in Snowflake
            cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
            if cluster_columns:
                # Sort by order and create clustering key
                sorted_cols = sorted(cluster_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]

                cluster_clause = f"CLUSTER BY ({', '.join(column_names)})"
                clauses.append(cluster_clause)

            # Handle partitioning as clustering (Snowflake uses micro-partitions automatically)
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns and not cluster_columns:
                # Use partitioning columns as clustering keys if no explicit clustering
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]

                cluster_clause = f"CLUSTER BY ({', '.join(column_names)})"
                clauses.append(cluster_clause)

            # Distribution and sorting handled through clustering in Snowflake

        except ImportError:
            # If tuning interface not available, return empty string
            pass

        return " ".join(clauses)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to a Snowflake table.

        Snowflake tuning approach:
        - CLUSTERING: Handled via CLUSTER BY in CREATE TABLE or ALTER TABLE
        - PARTITIONING: Automatic micro-partitions with optional clustering keys
        - Automatic clustering can be enabled for maintenance

        Args:
            table_tuning: The tuning configuration to apply
            connection: Snowflake connection

        Raises:
            ValueError: If the tuning configuration is invalid for Snowflake
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name = table_tuning.table_name.upper()
        self.logger.info(f"Applying Snowflake tunings for table: {table_name}")

        cursor = connection.cursor()
        try:
            # Import here to avoid circular imports
            from benchbox.core.tuning.interface import TuningType

            # Handle clustering keys
            cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)

            # Determine clustering strategy
            clustering_columns = []
            if cluster_columns:
                sorted_cols = sorted(cluster_columns, key=lambda col: col.order)
                clustering_columns = [col.name for col in sorted_cols]
            elif partition_columns:
                # Use partition columns as clustering keys
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                clustering_columns = [col.name for col in sorted_cols]

            if clustering_columns:
                # Check current clustering key
                cursor.execute(f"""
                    SELECT CLUSTERING_KEY
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = '{self.schema}'
                    AND TABLE_NAME = '{table_name}'
                """)
                result = cursor.fetchone()
                current_clustering = result[0] if result and result[0] else None

                desired_clustering = f"({', '.join(clustering_columns)})"

                if current_clustering != desired_clustering:
                    # Apply clustering key
                    cluster_sql = f"ALTER TABLE {table_name} CLUSTER BY ({', '.join(clustering_columns)})"
                    try:
                        cursor.execute(cluster_sql)
                        self.logger.info(f"Applied clustering key to {table_name}: {', '.join(clustering_columns)}")

                        # Enable automatic clustering if desired
                        if len(clustering_columns) <= 4:  # Snowflake recommendation
                            try:
                                cursor.execute(f"ALTER TABLE {table_name} RESUME RECLUSTER")
                                self.logger.info(f"Enabled automatic clustering for {table_name}")
                            except Exception as e:
                                self.logger.debug(f"Could not enable automatic clustering for {table_name}: {e}")

                    except Exception as e:
                        self.logger.warning(f"Failed to apply clustering key to {table_name}: {e}")
                else:
                    self.logger.info(f"Table {table_name} already has desired clustering key: {current_clustering}")

            # Handle sorting - in Snowflake, this is achieved through clustering
            sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
            if sort_columns and not clustering_columns:
                sorted_cols = sorted(sort_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(
                    f"Sorting in Snowflake achieved via clustering for table {table_name}: {', '.join(column_names)}"
                )

            # Distribution not applicable for Snowflake's architecture
            distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
            if distribution_columns:
                self.logger.warning(
                    f"Distribution tuning not applicable for Snowflake's shared-nothing architecture on table: {table_name}"
                )

        except ImportError:
            self.logger.warning("Tuning interface not available - skipping tuning application")
        except Exception as e:
            raise ValueError(f"Failed to apply tunings to Snowflake table {table_name}: {e}") from e
        finally:
            cursor.close()

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to Snowflake.

        Args:
            unified_config: Unified tuning configuration to apply
            connection: Snowflake connection
        """
        from benchbox.platforms.base.tuning_config import apply_standard_unified_tuning

        apply_standard_unified_tuning(self, unified_config, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply Snowflake-specific platform optimizations.

        Snowflake optimizations include:
        - Warehouse scaling and multi-cluster configuration
        - Query acceleration service settings
        - Result set caching configuration
        - Session-level optimization parameters

        Args:
            platform_config: Platform optimization configuration
            connection: Snowflake connection
        """
        if not platform_config:
            return

        # Snowflake optimizations are typically applied at warehouse or session level
        # Store optimizations for use during query execution
        self.logger.info("Snowflake platform optimizations stored for warehouse and session management")

    apply_constraint_configuration = make_informational_constraint_applier(
        "Primary key constraints enabled for Snowflake (informational only, applied during table creation)",
        "Foreign key constraints enabled for Snowflake (informational only, applied during table creation)",
    )


_build_snowflake_config = make_registered_platform_config_builder(
    "snowflake",
    __name__,
    "Snowflake",
    "snowflake-connector-python",
    [
        "account",
        "warehouse",
        "schema",
        "username",
        "password",
        "role",
        "authenticator",
        "private_key_path",
        "private_key_passphrase",
    ],
)

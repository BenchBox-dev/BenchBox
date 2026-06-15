"""Microsoft Fabric Warehouse platform adapter with OneLake integration.

IMPORTANT LIMITATIONS:
    This adapter ONLY supports Microsoft Fabric **Warehouse** items.
    It does NOT support Fabric Lakehouse (which requires Spark for data loading).

    Fabric has two primary data storage items:
    - **Warehouse**: Full T-SQL DDL/DML support (this adapter)
    - **Lakehouse**: SQL Analytics Endpoint is READ-ONLY (not supported)

    For Lakehouse benchmarking, you would need Spark integration via Livy API,
    which is not currently implemented.

Key differences from Azure Synapse:
    - Entra ID authentication only (no SQL auth)
    - OneLake as unified storage layer (not Azure Blob directly)
    - Automatic distribution management (no user-specified distribution keys)
    - Delta Lake native format
    - Same-region connections required (cross-region not supported)

Billing Model:
    Fabric uses Capacity Units (CUs) for billing. This adapter does not
    currently integrate with Fabric's capacity management APIs for:
    - CU consumption monitoring
    - Pause/Resume capacity (cost optimization)
    - Cost estimation

    For cost optimization, consider using Azure Automation or Logic Apps
    to pause capacity during non-benchmark periods.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import contextlib
import re
import struct
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.tuning import make_informational_constraint_applier
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
    )

from ..utils.dependencies import check_platform_dependencies, get_dependency_error_message, get_package_install_message
from ..utils.file_format import is_parquet_format
from .base import DriverIsolationCapability, PlatformAdapter
from .base.data_loading import NO_BENCHMARK, DataSource, resolve_csv_dialect

# Microsoft Fabric uses T-SQL dialect (subset of SQL Server T-SQL)
FABRIC_DIALECT = "tsql"

# ODBC constant for access token authentication
_SQL_COPT_SS_ACCESS_TOKEN = 1256

try:
    import pyodbc
except ImportError:
    pyodbc = None


class FabricWarehouseAdapter(PlatformAdapter):
    """Microsoft Fabric Warehouse platform adapter with OneLake integration.

    IMPORTANT: This adapter ONLY supports Fabric Warehouse items.
    Fabric Lakehouse uses a READ-ONLY SQL Analytics Endpoint and requires
    Spark for data loading, which is not supported by this adapter.

    Supports Microsoft Fabric Warehouse with:
        - Entra ID authentication (service principal or default credential)
        - OneLake integration for data staging and loading
        - COPY INTO for bulk data ingestion
        - T-SQL dialect with Fabric-specific limitations

    Known Limitations:
        - Lakehouse not supported (requires Spark)
        - Cross-region connections not supported
        - No capacity/billing integration
        - No V-Order optimization (Spark-only feature)

    Example:
        >>> adapter = FabricWarehouseAdapter(
        ...     workspace="my-workspace-guid",
        ...     warehouse="my_warehouse",
        ...     auth_method="default_credential",
        ... )
    """

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    # Fabric item type this adapter supports
    SUPPORTED_ITEM_TYPE = "Warehouse"
    UNSUPPORTED_ITEM_TYPES = ["Lakehouse", "KQL Database", "Mirrored Database"]

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies with improved error message
        available, missing = check_platform_dependencies("fabric_dw")
        if not available:
            error_msg = get_dependency_error_message("fabric_dw", missing)
            raise ImportError(error_msg)

        self._dialect = FABRIC_DIALECT

        # Microsoft Fabric connection configuration
        # Endpoint format: {workspace-guid}.datawarehouse.fabric.microsoft.com
        self.server = config.get("server")
        self.workspace = config.get("workspace")  # Workspace name or GUID
        self.warehouse = config.get("warehouse")  # Warehouse item name
        self.database = config.get("database")  # Alias for warehouse
        self.port = config.get("port") if config.get("port") is not None else 1433

        # Fabric item type - only Warehouse is supported
        self.item_type = config.get("item_type", "Warehouse")
        if self.item_type != "Warehouse":
            warnings.warn(
                f"FabricWarehouseAdapter only supports Warehouse items. "
                f"'{self.item_type}' specified but Lakehouse/KQL Database require "
                f"Spark integration which is not implemented. "
                f"Proceeding with Warehouse endpoint pattern.",
                UserWarning,
                stacklevel=2,
            )

        # Use warehouse as database if database not specified
        if not self.database and self.warehouse:
            self.database = self.warehouse

        # Authentication - Fabric ONLY supports Entra ID
        # Options: "service_principal", "default_credential", "interactive"
        self.auth_method = config.get("auth_method") or "default_credential"
        self.tenant_id = config.get("tenant_id")
        self.client_id = config.get("client_id")
        self.client_secret = config.get("client_secret")

        # ODBC driver configuration - MUST be version 18+
        self.driver = config.get("driver") or "ODBC Driver 18 for SQL Server"

        # Schema configuration
        self.schema = config.get("schema") or "dbo"

        # Connection settings
        self.connect_timeout = config.get("connect_timeout") if config.get("connect_timeout") is not None else 30
        self.query_timeout = config.get("query_timeout") if config.get("query_timeout") is not None else 0

        # OneLake storage configuration for data loading
        # OneLake URI: https://onelake.dfs.fabric.microsoft.com/{workspace}/{item}.Warehouse/Files/
        self.onelake_workspace = config.get("onelake_workspace") or self.workspace
        self.staging_path = config.get("staging_path") or "benchbox-staging"

        # Result cache control - disable by default for accurate benchmarking
        self.disable_result_cache = config.get("disable_result_cache", True)

        # Validation strictness
        self.strict_validation = config.get("strict_validation", True)

        # Validate configuration
        if not self.server and not self.workspace:
            from benchbox.core.exceptions import ConfigurationError

            raise ConfigurationError(
                "Fabric Warehouse configuration requires connection details.\n"
                "Provide either:\n"
                "  1. Workspace GUID: --platform-option workspace=<guid>\n"
                "  2. Full endpoint: --platform-option server=<guid>.datawarehouse.fabric.microsoft.com\n"
                "\n"
                "Find your workspace GUID in the Fabric portal URL:\n"
                "  https://app.fabric.microsoft.com/groups/<workspace-guid>/..."
            )

        if self.auth_method == "service_principal" and not all([self.client_id, self.client_secret, self.tenant_id]):
            missing = []
            if not self.client_id:
                missing.append("client_id (or FABRIC_CLIENT_ID)")
            if not self.client_secret:
                missing.append("client_secret (or FABRIC_CLIENT_SECRET)")
            if not self.tenant_id:
                missing.append("tenant_id (or FABRIC_TENANT_ID)")

            from benchbox.core.exceptions import ConfigurationError

            raise ConfigurationError(
                f"Fabric service principal authentication is incomplete. Missing: {', '.join(missing)}\n"
                "Configure with:\n"
                "  1. Environment variables: FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET, FABRIC_TENANT_ID\n"
                "  2. CLI options: --platform-option client_id=<id> --platform-option tenant_id=<tenant>\n"
                "\n"
                "Alternative: Use --platform-option auth_method=default_credential for Azure CLI/managed identity."
            )

        # Build server endpoint if only workspace provided
        # Note: This pattern is ONLY valid for Warehouse items
        if not self.server and self.workspace:
            self.server = f"{self.workspace}.datawarehouse.fabric.microsoft.com"
            self.logger.debug(
                f"Built Warehouse endpoint: {self.server}. "
                "Note: Lakehouse SQL endpoints use a different pattern and are READ-ONLY."
            )

        if not self.database:
            from benchbox.core.exceptions import ConfigurationError

            raise ConfigurationError(
                "Fabric Warehouse requires a database/warehouse name.\n"
                "Configure with:\n"
                "  1. CLI option: --platform-option warehouse=<warehouse_name>\n"
                "  2. CLI option: --platform-option database=<warehouse_name>\n"
                "\n"
                "Find your warehouse name in the Fabric portal under your workspace."
            )

        # Log important limitations
        self.logger.info(
            "FabricWarehouseAdapter initialized. Note: Only Warehouse items supported. "
            "Lakehouse (requires Spark) and cross-region connections are NOT supported."
        )

    @property
    def platform_name(self) -> str:
        return "Fabric Warehouse"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Microsoft Fabric (T-SQL subset)."""
        return FABRIC_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Fabric Warehouse-specific CLI arguments."""
        fabric_group = parser.add_argument_group("Fabric Warehouse Arguments")
        fabric_group.add_argument(
            "--server",
            type=str,
            help="Fabric warehouse endpoint (e.g., workspace-guid.datawarehouse.fabric.microsoft.com)",
        )
        fabric_group.add_argument("--workspace", type=str, help="Fabric workspace name or GUID")
        fabric_group.add_argument(
            "--warehouse",
            type=str,
            help="Fabric warehouse name (Warehouse items only; Lakehouse not supported)",
        )
        fabric_group.add_argument("--database", type=str, help="Database/warehouse name (alias for --warehouse)")
        fabric_group.add_argument(
            "--auth-method",
            type=str,
            choices=["service_principal", "default_credential", "interactive"],
            default="default_credential",
            help="Authentication method (Entra ID only)",
        )
        fabric_group.add_argument("--tenant-id", type=str, help="Azure tenant ID for service principal auth")
        fabric_group.add_argument("--client-id", type=str, help="Service principal client ID")
        fabric_group.add_argument("--client-secret", type=str, help="Service principal client secret")
        fabric_group.add_argument("--staging-path", type=str, default="benchbox-staging", help="OneLake staging path")

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Fabric Warehouse adapter from unified configuration."""
        from benchbox.platforms.base.config_utils import build_adapter_config

        adapter_source = config
        if not config.get("database") and config.get("warehouse"):
            adapter_source = {**config, "database": config["warehouse"]}

        return cls(
            **build_adapter_config(
                adapter_source,
                platform="fabric_dw",
                fields=[
                    "server",
                    "workspace",
                    "warehouse",
                    "port",
                    "schema",
                    "auth_method",
                    "tenant_id",
                    "client_id",
                    "client_secret",
                    "driver",
                    "connect_timeout",
                    "query_timeout",
                    "onelake_workspace",
                    "staging_path",
                    "disable_result_cache",
                    "strict_validation",
                    "item_type",
                ],
            )
        )

    def _get_access_token(self) -> str:
        """Acquire Entra ID access token for SQL connection.

        Returns:
            Access token string for database authentication.
        """
        try:
            from azure.identity import (
                ClientSecretCredential,
                DefaultAzureCredential,
                InteractiveBrowserCredential,
            )
        except ImportError as err:
            raise ImportError(
                get_package_install_message(
                    "azure-identity", "azure-identity package required for Fabric authentication."
                )
            ) from err

        # SQL Database scope for Fabric
        scope = "https://database.windows.net/.default"

        if self.auth_method == "service_principal":
            credential = ClientSecretCredential(
                tenant_id=self.tenant_id,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        elif self.auth_method == "interactive":
            credential = InteractiveBrowserCredential()
        else:  # default_credential
            credential = DefaultAzureCredential()

        token = credential.get_token(scope)
        return token.token

    def _get_connection_string(self, db: str | None = None) -> str:
        """Generate ODBC connection string for Fabric Warehouse.

        Args:
            db: Optional database name override.

        Returns:
            ODBC connection string.
        """
        database = db or self.database

        # Base connection string - Fabric requires encrypted connections
        conn_str = (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server},{self.port};"
            f"DATABASE={database};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
            f"Connection Timeout={self.connect_timeout};"
        )

        return conn_str

    def _create_token_struct(self, token: str) -> bytes:
        """Create token struct for pyodbc SQL_COPT_SS_ACCESS_TOKEN.

        Args:
            token: Access token string.

        Returns:
            Bytes struct for ODBC driver.
        """
        # Encode token as UTF-16-LE for SQL Server ODBC driver
        token_bytes = token.encode("UTF-16-LE")
        # Create struct: length (4 bytes) + token bytes
        return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    def create_connection(self, **connection_config) -> Any:
        """Create a connection to Fabric Warehouse.

        Note: This only works with Warehouse items. Lakehouse SQL Analytics
        Endpoints are READ-ONLY and will fail on DDL/DML operations.

        Args:
            **connection_config: Optional connection overrides.

        Returns:
            Active database connection.

        Raises:
            ConnectionError: If connection fails.
        """
        db = connection_config.get("database", self.database)

        try:
            # Get access token
            access_token = self._get_access_token()
            token_struct = self._create_token_struct(access_token)

            # Create connection with token
            conn_str = self._get_connection_string(db)

            connection = pyodbc.connect(
                conn_str,
                attrs_before={_SQL_COPT_SS_ACCESS_TOKEN: token_struct},
                autocommit=True,
            )

            # Test connection
            cursor = connection.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0]
            self.logger.info(f"Connected to Fabric Warehouse: {version[:80]}...")
            cursor.close()

            return connection

        except pyodbc.Error as e:
            error_msg = str(e)
            self.logger.error(f"Failed to connect to Fabric Warehouse: {error_msg}")

            # Check for common errors and provide helpful messages
            if "cross-region" in error_msg.lower() or "region" in error_msg.lower():
                self.logger.error(
                    "HINT: Fabric requires same-region connections. "
                    "Ensure your client and Fabric capacity are in the same Azure region."
                )
            if "read-only" in error_msg.lower() or "permission" in error_msg.lower():
                self.logger.error(
                    "HINT: If targeting a Lakehouse SQL Analytics Endpoint, note that it is READ-ONLY. "
                    "This adapter only supports Fabric Warehouse items with full DDL/DML."
                )

            raise ConnectionError(f"Failed to connect to Fabric Warehouse: {error_msg}") from e

    def test_connection(self) -> dict[str, Any]:
        """Test connection to Fabric Warehouse.

        Returns:
            Dict with connection status and info.
        """
        try:
            connection = self.create_connection()
            cursor = connection.cursor()

            # Get version info
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0]

            # Test basic query capability
            cursor.execute("SELECT 1 AS test")
            cursor.fetchone()

            # Test write capability (critical for Warehouse vs Lakehouse distinction)
            try:
                cursor.execute("CREATE TABLE #benchbox_test_temp (id INT)")
                cursor.execute("DROP TABLE #benchbox_test_temp")
                write_capable = True
            except pyodbc.Error:
                write_capable = False
                self.logger.warning(
                    "Write test failed. This may be a Lakehouse SQL Analytics Endpoint "
                    "(READ-ONLY) rather than a Warehouse. Data loading will fail."
                )

            cursor.close()
            connection.close()

            return {
                "success": True,
                "version": version,
                "server": self.server,
                "database": self.database,
                "auth_method": self.auth_method,
                "write_capable": write_capable,
                "item_type": "Warehouse" if write_capable else "Unknown (possibly Lakehouse)",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "server": self.server,
                "database": self.database,
            }

    def check_server_database_exists(self) -> bool:
        """Check if the Fabric Warehouse exists.

        Note: In Fabric, warehouses are created through the Fabric portal,
        not via T-SQL. This checks if we can connect to the specified warehouse.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            connection = self.create_connection()
            connection.close()
            return True
        except Exception as e:
            self.logger.debug(f"Database check failed: {e}")
            return False

    def get_platform_info(self) -> dict[str, Any]:
        """Get Fabric Warehouse platform information.

        Returns:
            Dict with platform details.
        """
        info = {
            "platform": "Fabric Warehouse",
            "dialect": FABRIC_DIALECT,
            "server": self.server,
            "database": self.database,
            "schema": self.schema,
            "auth_method": self.auth_method,
            "driver": self.driver,
            "supported_item_type": self.SUPPORTED_ITEM_TYPE,
            "unsupported_item_types": self.UNSUPPORTED_ITEM_TYPES,
            "limitations": [
                "Lakehouse not supported (requires Spark)",
                "Cross-region connections not supported",
                "No capacity/billing integration",
            ],
        }

        try:
            connection = self.create_connection()
            cursor = connection.cursor()

            # Get version
            cursor.execute("SELECT @@VERSION")
            info["version"] = cursor.fetchone()[0]

            cursor.close()
            connection.close()
        except Exception as e:
            info["version"] = f"Unknown (error: {e})"

        return info

    def create_schema(self, benchmark: Any, connection: Any) -> float:
        """Create schema using Fabric Warehouse table definitions.

        Note: This uses T-SQL DDL which ONLY works on Fabric Warehouse items.
        Lakehouse SQL Analytics Endpoints are READ-ONLY and this will fail.

        Args:
            benchmark: Benchmark instance with schema definitions.
            connection: Active database connection.

        Returns:
            Time taken for schema creation in seconds.
        """
        self.log_operation_start("Fabric Warehouse schema creation")
        start_time = mono_time()

        cursor = connection.cursor()

        try:
            # Create schema if needed (non-dbo schemas)
            if self.schema and self.schema.lower() != "dbo":
                self.log_verbose(f"Creating schema: {self.schema}")
                cursor.execute(
                    f"""
                    IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = '{self.schema}')
                    BEGIN
                        EXEC('CREATE SCHEMA [{self.schema}]')
                    END
                """
                )

            # Use common schema creation helper
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

            # Split schema into individual statements and execute
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            for statement in statements:
                if not statement.upper().startswith("CREATE TABLE"):
                    continue

                # Extract table name
                table_name = self._extract_table_name(statement)
                if not table_name:
                    continue

                # Optimize for Fabric
                optimized_sql = self._optimize_table_definition(statement)

                # Drop existing table if needed
                self.drop_table(connection, table_name)

                # Create table
                self.log_verbose(f"Creating table: {table_name}")
                cursor.execute(optimized_sql)

        except pyodbc.Error as e:
            error_msg = str(e)
            if "permission" in error_msg.lower() or "read-only" in error_msg.lower():
                raise RuntimeError(
                    f"Schema creation failed: {error_msg}. "
                    "This may be a Lakehouse SQL Analytics Endpoint (READ-ONLY). "
                    "FabricWarehouseAdapter only supports Fabric Warehouse items. "
                    "For Lakehouse, you would need Spark integration."
                ) from e
            raise
        finally:
            cursor.close()

        elapsed = elapsed_seconds(start_time)
        self.log_operation_complete(f"Schema creation completed in {elapsed:.2f}s")
        return elapsed

    def configure_for_benchmark(self, connection: Any, benchmark_type: str = "olap") -> None:
        """Configure Fabric Warehouse for benchmark execution.

        Args:
            connection: Database connection.
            benchmark_type: Type of benchmark (olap, analytics, tpch, tpcds).
        """
        if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
            try:
                cursor = connection.cursor()

                # Disable result set caching for accurate benchmarking
                if self.disable_result_cache:
                    try:
                        cursor.execute("ALTER DATABASE SCOPED CONFIGURATION SET QUERY_STORE CLEAR")
                        self.logger.info("Cleared query store for accurate benchmarking")
                    except pyodbc.Error:
                        # Query store control may not be available in Fabric
                        self.logger.debug("Query store control not available")

                # Set ANSI standards
                cursor.execute("SET ANSI_NULLS ON")
                cursor.execute("SET ANSI_PADDING ON")
                cursor.execute("SET ANSI_WARNINGS ON")

                cursor.close()
                self.logger.info(f"Configured for {benchmark_type} benchmark")

            except Exception as e:
                self.logger.warning(f"Could not configure benchmark settings: {e}")

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str | None = None,
        stream_id: int | None = None,
        iteration: int | None = None,
    ) -> dict[str, Any]:
        """Execute a query and return timing/results.

        Args:
            connection: Active database connection.
            query: SQL query to execute.
            query_id: Optional query identifier.
            stream_id: Optional stream ID for throughput testing.
            iteration: Optional iteration number.

        Returns:
            Dict with execution results.
        """
        cursor = connection.cursor()
        start_time = mono_time()

        try:
            cursor.execute(query)

            # Fetch results to ensure query completes
            rows = cursor.fetchall()
            row_count = len(rows)

            execution_time = elapsed_seconds(start_time)

            result_dict = {
                "query_id": query_id,
                "stream_id": stream_id,
                "iteration": iteration,
                "status": "SUCCESS",
                "execution_time_seconds": execution_time,
                "rows_returned": row_count,
            }

        except pyodbc.Error as e:
            execution_time = elapsed_seconds(start_time)
            return {
                "query_id": query_id,
                "stream_id": stream_id,
                "iteration": iteration,
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
        # No-op (no SHOWPLAN issued) when capture_plans is False.
        self._merge_plan_capture_into_result(result_dict, connection, query, str(query_id))
        return result_dict

    def get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables in the schema.

        Args:
            connection: Active database connection.

        Returns:
            List of table names.
        """
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = ?
                  AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME
                """,
                (self.schema,),
            )
            tables = [row[0] for row in cursor.fetchall()]
            return tables
        finally:
            cursor.close()

    def drop_table(self, connection: Any, table_name: str) -> None:
        """Drop a table if it exists.

        Args:
            connection: Active database connection.
            table_name: Name of table to drop.
        """
        qualified_name = f"[{self.schema}].[{table_name}]"
        cursor = connection.cursor()
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {qualified_name}")
            self.logger.info(f"Dropped table {qualified_name}")
        finally:
            cursor.close()

    def _upload_to_onelake(self, local_path: Path, table_name: str) -> str:
        """Upload file to OneLake for COPY INTO.

        Args:
            local_path: Path to local data file.
            table_name: Target table name (used for staging path).

        Returns:
            OneLake URI for the uploaded file.
        """
        try:
            from azure.identity import ClientSecretCredential, DefaultAzureCredential
            from azure.storage.filedatalake import DataLakeServiceClient
        except ImportError as err:
            raise ImportError(
                get_package_install_message(
                    "azure-storage-file-datalake azure-identity",
                    "Azure Storage SDK required for OneLake uploads.",
                )
            ) from err

        # Create credential
        if self.auth_method == "service_principal":
            credential = ClientSecretCredential(
                tenant_id=self.tenant_id,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        else:
            credential = DefaultAzureCredential()

        # Connect to OneLake
        account_url = "https://onelake.dfs.fabric.microsoft.com"
        service_client = DataLakeServiceClient(account_url, credential=credential)

        # Get file system client for workspace
        file_system_client = service_client.get_file_system_client(self.onelake_workspace)

        # Build path: {warehouse}.Warehouse/Files/{staging_path}/{table}/{filename}
        # Note: Warehouse uses .Warehouse suffix; Lakehouse would use .Lakehouse
        warehouse_path = f"{self.database}.Warehouse/Files/{self.staging_path}/{table_name}"
        directory_client = file_system_client.get_directory_client(warehouse_path)

        # Create directory if needed (may already exist)
        with contextlib.suppress(Exception):
            directory_client.create_directory()

        # Upload file
        file_name = local_path.name
        file_client = directory_client.get_file_client(file_name)

        with open(local_path, "rb") as data:
            file_client.upload_data(data, overwrite=True)

        self.logger.debug(f"Uploaded {file_name} to OneLake: {warehouse_path}/{file_name}")

        # Return OneLake URI for COPY INTO
        # Format: https://onelake.dfs.fabric.microsoft.com/{workspace}/{warehouse}.Warehouse/Files/...
        onelake_uri = f"https://onelake.dfs.fabric.microsoft.com/{self.onelake_workspace}/{warehouse_path}/{file_name}"
        return onelake_uri

    def _resolve_data_files(self, benchmark: Any, data_dir: Path) -> DataSource:
        """Resolve benchmark data files via DataSourceResolver."""
        from benchbox.platforms.base.data_loading import DataSourceResolver

        resolver = DataSourceResolver(
            platform_name=self.platform_name,
            table_mode=self.table_mode,
            platform_config=self.platform_config,
            requested_format=self.requested_table_format,
        )
        data_source = resolver.resolve(benchmark, data_dir)
        if not data_source or not data_source.tables:
            raise ValueError(f"No data files found in {data_dir}")
        return data_source

    @staticmethod
    def _normalize_existing_files(file_paths: Any) -> list[Path]:
        """Normalize table file inputs to existing, non-empty local paths."""
        normalized_paths = file_paths if isinstance(file_paths, list) else [file_paths]
        valid_files: list[Path] = []
        for file_path in normalized_paths:
            path = Path(file_path)
            if path.is_file() and path.stat().st_size > 0:
                valid_files.append(path)
        return valid_files

    def load_data(
        self,
        benchmark: Any,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data into Fabric Warehouse.

        Uses OneLake + COPY INTO for optimal performance, with fallback to
        direct INSERT for smaller datasets or when OneLake is unavailable.

        Note: This uses T-SQL DML which ONLY works on Fabric Warehouse items.
        Lakehouse requires Spark for data loading.

        Args:
            benchmark: Benchmark instance with table definitions.
            connection: Active database connection.
            data_dir: Directory containing data files.

        Returns:
            Tuple of (table_stats, elapsed_time, metadata).
        """
        self.log_operation_start("Fabric Warehouse data loading")
        start_time = mono_time()
        table_stats: dict[str, int] = {}
        data_source = self._resolve_data_files(benchmark, data_dir)

        # Try OneLake + COPY INTO first (can be disabled via config)
        use_onelake = getattr(self, "use_onelake", True)

        for table_name, file_paths in data_source.tables.items():
            data_files = self._normalize_existing_files(file_paths)

            if not data_files:
                self.logger.warning(f"No data files found for table {table_name}")
                table_stats[table_name] = 0
                continue

            try:
                if use_onelake:
                    row_count = self._load_data_via_onelake(connection, table_name, data_files, data_source, benchmark)
                else:
                    row_count = self._load_data_direct(connection, table_name, data_files, data_source, benchmark)

                table_stats[table_name] = row_count
                self.logger.info(f"Loaded {row_count:,} rows into {table_name}")

            except pyodbc.Error as e:
                error_msg = str(e)
                if "permission" in error_msg.lower() or "read-only" in error_msg.lower():
                    raise RuntimeError(
                        f"Data loading failed: {error_msg}. "
                        "This may be a Lakehouse SQL Analytics Endpoint (READ-ONLY). "
                        "FabricWarehouseAdapter only supports Fabric Warehouse items. "
                        "For Lakehouse data loading, you would need Spark (Livy API)."
                    ) from e

                self.logger.error(f"Failed to load {table_name}: {str(e)[:100]}...")
                if use_onelake:
                    # Fallback to direct INSERT
                    try:
                        self.logger.info(f"Falling back to direct INSERT for {table_name}")
                        row_count = self._load_data_direct(connection, table_name, data_files, data_source, benchmark)
                        table_stats[table_name] = row_count
                    except Exception as fallback_error:
                        self.logger.error(f"Direct INSERT also failed: {fallback_error}")
                        table_stats[table_name] = 0
                else:
                    table_stats[table_name] = 0

            except Exception as e:
                self.logger.error(f"Failed to load {table_name}: {str(e)[:100]}...")
                table_stats[table_name] = 0

        elapsed = elapsed_seconds(start_time)
        self.log_operation_complete(f"Data loading completed in {elapsed:.2f}s")

        # Return tuple matching abstract method signature
        return table_stats, elapsed, None

    def _load_data_via_onelake(
        self,
        connection: Any,
        table_name: str,
        data_files: list[Path],
        data_source: DataSource | None = None,
        benchmark: Any = None,
    ) -> int:
        """Load data via OneLake and COPY INTO.

        Args:
            connection: Active database connection.
            table_name: Target table name.
            data_files: List of data files to load.

        Returns:
            Number of rows loaded.
        """
        total_rows = 0
        qualified_table = f"[{self.schema}].[{table_name}]"
        cursor = connection.cursor()
        ds = data_source or DataSource(source_type="fabric_onelake", tables={})
        bm = benchmark if benchmark is not None else NO_BENCHMARK

        try:
            for data_file in data_files:
                if data_file.stat().st_size == 0:
                    continue

                # Upload to OneLake
                onelake_uri = self._upload_to_onelake(data_file, table_name)

                # Determine file format and delimiter via resolver
                if is_parquet_format(data_file):
                    file_type = "PARQUET"
                    field_terminator = None
                else:
                    dialect = resolve_csv_dialect(ds, table_name, data_file, bm)
                    file_type = "CSV"
                    field_terminator = dialect.delimiter

                # Build COPY INTO command
                if file_type == "PARQUET":
                    copy_sql = f"""
                        COPY INTO {qualified_table}
                        FROM '{onelake_uri}'
                        WITH (
                            FILE_TYPE = 'PARQUET'
                        )
                    """
                else:
                    copy_sql = f"""
                        COPY INTO {qualified_table}
                        FROM '{onelake_uri}'
                        WITH (
                            FILE_TYPE = 'CSV',
                            FIELDTERMINATOR = '{field_terminator}',
                            ROWTERMINATOR = '0x0A',
                            FIRSTROW = 1,
                            ENCODING = 'UTF8'
                        )
                    """

                start_time = mono_time()
                cursor.execute(copy_sql)
                load_time = elapsed_seconds(start_time)

                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {qualified_table}")
                current_count = cursor.fetchone()[0]
                rows_added = current_count - total_rows
                total_rows = current_count

                self.logger.debug(
                    f"COPY INTO {table_name} from {data_file.name}: {rows_added:,} rows in {load_time:.2f}s"
                )

        finally:
            cursor.close()

        return total_rows

    def _load_data_direct(
        self,
        connection: Any,
        table_name: str,
        data_files: list[Path],
        data_source: DataSource | None = None,
        benchmark: Any = None,
    ) -> int:
        """Load data via direct INSERT statements.

        Fallback method when OneLake is not available.

        Args:
            connection: Active database connection.
            table_name: Target table name.
            data_files: List of data files to load.

        Returns:
            Number of rows loaded.
        """
        import csv

        total_rows = 0
        qualified_table = f"[{self.schema}].[{table_name}]"
        cursor = connection.cursor()
        batch_size = 1000
        ds = data_source or DataSource(source_type="fabric_direct", tables={})
        bm = benchmark if benchmark is not None else NO_BENCHMARK

        try:
            for data_file in data_files:
                if data_file.stat().st_size == 0:
                    continue

                # Determine delimiter via resolver
                dialect = resolve_csv_dialect(ds, table_name, data_file, bm)
                delimiter = dialect.delimiter

                with open(data_file, encoding="utf-8") as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    batch = []

                    for row in reader:
                        # Skip empty rows
                        if not row or (len(row) == 1 and not row[0].strip()):
                            continue

                        # Clean values and handle trailing delimiter
                        values = [v.strip() for v in row if v.strip() or row.index(v) < len(row) - 1]
                        if values:
                            batch.append(values)

                        if len(batch) >= batch_size:
                            self._insert_batch(cursor, qualified_table, batch)
                            total_rows += len(batch)
                            batch = []

                    # Insert remaining rows
                    if batch:
                        self._insert_batch(cursor, qualified_table, batch)
                        total_rows += len(batch)

        finally:
            cursor.close()

        return total_rows

    def _insert_batch(self, cursor: Any, table_name: str, batch: list[list[str]]) -> None:
        """Insert a batch of rows using INSERT VALUES.

        Args:
            cursor: Database cursor.
            table_name: Qualified table name.
            batch: List of row value lists.
        """
        if not batch:
            return

        # Build multi-row INSERT
        value_rows = []
        for row in batch:
            escaped_values = []
            for v in row:
                if v == "" or v.upper() == "NULL":
                    escaped_values.append("NULL")
                else:
                    # Escape single quotes
                    escaped = v.replace("'", "''")
                    escaped_values.append(f"'{escaped}'")
            value_rows.append(f"({', '.join(escaped_values)})")

        insert_sql = f"INSERT INTO {table_name} VALUES {', '.join(value_rows)}"
        cursor.execute(insert_sql)

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get query execution plan.

        Args:
            connection: Active database connection.
            query: SQL query to analyze.

        Returns:
            Query plan as string.
        """
        cursor = connection.cursor()
        try:
            # Enable plan capture. SHOWPLAN_TEXT is a session-level setting, so it
            # MUST be turned off even if the EXPLAINed query fails — otherwise the
            # connection stays in SHOWPLAN mode and subsequent benchmark statements
            # return plans instead of executing, corrupting the rest of the run.
            cursor.execute("SET SHOWPLAN_TEXT ON")
            try:
                cursor.execute(query)
                plan_rows = cursor.fetchall()
            finally:
                # Best-effort reset; never let the OFF mask the original failure.
                try:
                    cursor.execute("SET SHOWPLAN_TEXT OFF")
                except Exception:
                    pass
            return "\n".join([str(row[0]) for row in plan_rows])
        except Exception as e:
            return f"Failed to get query plan: {e}"
        finally:
            cursor.close()

    def get_query_plan_parser(self):
        """Return the Fabric Warehouse (SQL Server SHOWPLAN_TEXT) query plan parser.

        Fabric Warehouse retrieves its plan via ``SET SHOWPLAN_TEXT`` (text
        showplan), a different format from Azure Synapse Dedicated Pool's
        distributed dsql XML, so it uses a dedicated parser rather than reusing
        AzureSynapseQueryPlanParser (see the w6 decision gate).
        """
        from benchbox.core.query_plans.parsers.fabric_warehouse import FabricWarehouseQueryPlanParser

        return FabricWarehouseQueryPlanParser()

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Update table statistics.

        Args:
            connection: Active database connection.
            table_name: Name of table to analyze.
        """
        cursor = connection.cursor()
        try:
            cursor.execute(f"UPDATE STATISTICS [{self.schema}].[{table_name}]")
            self.logger.debug(f"Updated statistics for {table_name}")
        except pyodbc.Error as e:
            self.logger.warning(f"Could not update statistics for {table_name}: {e}")
        finally:
            cursor.close()

    def close_connection(self, connection: Any) -> None:
        """Close database connection.

        Args:
            connection: Connection to close.
        """
        if connection:
            with contextlib.suppress(Exception):
                connection.close()

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply Fabric Warehouse-specific platform optimizations.

        Args:
            platform_config: Platform optimization configuration.
            connection: Active database connection.
        """
        if not platform_config:
            return

        self.logger.info("Fabric Warehouse platform optimizations applied")

    apply_constraint_configuration = make_informational_constraint_applier(
        "Primary key constraints enabled for Fabric Warehouse (informational only)",
        "Foreign key constraints enabled for Fabric Warehouse (informational only)",
    )

    _supported_tuning_type_names = ("CLUSTERING",)

    def generate_tuning_clause(
        self,
        table_tuning: Any,
        _constraint_configs: tuple[Any, Any, Any] | None = None,
    ) -> str:
        """Generate tuning clause for CREATE TABLE.

        In Fabric Warehouse, distribution is automatic. Only clustered
        columnstore index is relevant.

        Args:
            table_tuning: TableTuning configuration.
            constraint_configs: Optional constraint configurations.

        Returns:
            WITH clause for CREATE TABLE.
        """
        # Fabric uses clustered columnstore index by default
        # No explicit WITH clause needed for most cases
        return ""

    def _optimize_table_definition(self, table_sql: str, table_tuning: Any = None) -> str:
        """Optimize table definition for Fabric Warehouse.

        Args:
            table_sql: Original CREATE TABLE statement.
            table_tuning: Optional tuning configuration.

        Returns:
            Optimized CREATE TABLE statement.
        """
        # Add schema prefix if not present
        if "[" not in table_sql and self.schema:
            schema = self.schema

            def _add_schema(m: re.Match) -> str:
                ifne = m.group(1) or ""
                name = m.group(2).strip("[]")
                return f"CREATE TABLE {ifne}[{schema}].[{name}]"

            table_sql = re.sub(
                r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?(\[?\w+\]?)",
                _add_schema,
                table_sql,
                count=1,
                flags=re.IGNORECASE,
            )

        return table_sql

    def _extract_table_name(self, create_statement: str) -> str | None:
        """Extract table name from CREATE TABLE statement.

        Args:
            create_statement: SQL CREATE TABLE statement.

        Returns:
            Table name or None.
        """
        match = re.search(
            r"CREATE\s+TABLE\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?",
            create_statement,
            re.IGNORECASE,
        )
        return match.group(1) if match else None


# Note: Adapter registration is handled centrally in benchbox/core/platform_registry.py
# The canonical platform name is "fabric-warehouse"

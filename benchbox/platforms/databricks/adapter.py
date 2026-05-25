"""Databricks platform adapter with Unity Catalog and Delta Lake optimization.

Provides Databricks-specific optimizations for large-scale analytics,
including Delta Lake table creation and cluster management.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TuningColumn,
        UnifiedTuningConfiguration,
    )

from benchbox.core.upload_validation import UploadValidationEngine
from benchbox.platforms.base import DriverIsolationCapability, PlatformAdapter
from benchbox.platforms.base.runtime_metadata import build_default_normalized_result_metadata
from benchbox.platforms.base.tuning import make_informational_constraint_applier
from benchbox.utils.datagen_manifest import MANIFEST_FILENAME
from benchbox.utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
    get_package_install_message,
)
from benchbox.utils.file_format import COMPRESSION_EXTENSIONS

try:
    from databricks import sql as databricks_sql
except ImportError:
    databricks_sql = None


def _select_databricks_warehouse(warehouses: list, very_verbose: bool, logger: logging.Logger):
    """Select the best warehouse from a list of Databricks SQL warehouses.

    Priority: 1) running warehouse, 2) non-terminal warehouse (for auto-start).
    """
    if not warehouses:
        return None

    # 1. Prefer a running warehouse
    running_wh = next((wh for wh in warehouses if str(wh.state) == "RUNNING"), None)
    if running_wh:
        if very_verbose:
            logger.info(f"Selected running warehouse: {running_wh.name}")
        return running_wh

    if very_verbose:
        logger.info("No running warehouses found. Looking for an available one to auto-start.")
    # 2. Otherwise, take the first available one that is not in a terminal state
    available_wh = next(
        (wh for wh in warehouses if str(wh.state) not in ["DELETING", "DELETED"]),
        None,
    )
    if available_wh and very_verbose:
        logger.info(f"Selected available warehouse to auto-start: {available_wh.name} (State: {available_wh.state})")
    return available_wh


def _compact_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value not in (None, "", {}, [], ())}


class DatabricksAdapter(PlatformAdapter):
    """Databricks platform adapter with Delta Lake and Unity Catalog support."""

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    supports_external_tables = True

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies with improved error message
        available, missing = check_platform_dependencies("databricks")
        if not available:
            error_msg = get_dependency_error_message("databricks", missing)
            raise ImportError(error_msg)

        self._dialect = "databricks"

        # Databricks configuration
        self.server_hostname = config.get("server_hostname") or config.get("host")
        self.http_path = config.get("http_path")
        self.access_token = config.get("access_token") or config.get("token")
        self.catalog = config.get("catalog") or "main"
        self.schema = config.get("schema") or "benchbox"
        # Unity Catalog Volume and staging support
        self.uc_catalog = config.get("uc_catalog")
        self.uc_schema = config.get("uc_schema")
        self.uc_volume = config.get("uc_volume")
        # Explicit staging root (e.g., dbfs:/Volumes/<cat>/<schema>/<volume>/... or s3://...)
        self.staging_root = config.get("staging_root")
        self.region = config.get("region") or config.get("cloud_region") or config.get("workspace_region")

        # Delta Lake settings
        self.enable_delta_optimization = (
            config.get("enable_delta_optimization") if config.get("enable_delta_optimization") is not None else True
        )
        self.delta_auto_optimize = (
            config.get("delta_auto_optimize") if config.get("delta_auto_optimize") is not None else True
        )
        self.delta_auto_compact = (
            config.get("delta_auto_compact") if config.get("delta_auto_compact") is not None else True
        )

        # Cluster settings
        self.cluster_size = config.get("cluster_size") or "Medium"
        self.auto_terminate_minutes = (
            config.get("auto_terminate_minutes") if config.get("auto_terminate_minutes") is not None else 30
        )

        # Schema creation settings
        self.create_catalog = config.get("create_catalog") if config.get("create_catalog") is not None else False

        # Upload/validation controls
        force_upload_val = config.get("force_upload")
        self.force_upload = bool(force_upload_val if force_upload_val is not None else False)

        # Result cache control - disable by default for accurate benchmarking
        self.disable_result_cache = config.get("disable_result_cache", True)
        self._liquid_clustering_operations: list[dict[str, Any]] = []
        self._z_order_operations: list[dict[str, Any]] = []

        if not self.server_hostname or not self.http_path or not self.access_token:
            missing = []
            if not self.server_hostname:
                missing.append("server_hostname (or DATABRICKS_HOST)")
            if not self.http_path:
                missing.append("http_path (or DATABRICKS_HTTP_PATH)")
            if not self.access_token:
                missing.append("access_token (or DATABRICKS_TOKEN)")

            from benchbox.core.exceptions import ConfigurationError

            raise ConfigurationError(
                f"Databricks configuration is incomplete. Missing: {', '.join(missing)}\n"
                "Configure with one of:\n"
                "  1. CLI: benchbox platforms setup --platform databricks\n"
                "  2. Environment variables: DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN\n"
                "  3. CLI options: --platform-option server_hostname=<host> --platform-option http_path=<path>"
            )

    @property
    def platform_name(self) -> str:
        return "Databricks"

    def _resolve_databricks_clustering_strategy(self) -> str:
        """Resolve clustering strategy with backward-compatible precedence rules."""
        effective_config = self.get_effective_tuning_configuration()
        platform_opts = getattr(effective_config, "platform_optimizations", None)
        if platform_opts is None:
            return "z_order"

        strategy = getattr(platform_opts, "databricks_clustering_strategy", "z_order")
        liquid_enabled = bool(getattr(platform_opts, "liquid_clustering_enabled", False))
        liquid_columns = list(getattr(platform_opts, "liquid_clustering_columns", []))
        z_order_enabled = bool(getattr(platform_opts, "z_ordering_enabled", False))

        # Precedence:
        # 1) Explicit liquid settings
        # 2) Explicit strategy field
        # 3) Legacy z_ordering flag (default compatibility path)
        if liquid_enabled or liquid_columns:
            if z_order_enabled:
                self.logger.info("Databricks tuning precedence: liquid clustering overrides legacy z-order settings")
            return "liquid_clustering"
        if strategy in {"liquid_clustering", "none"}:
            return strategy
        if z_order_enabled:
            return "z_order"
        return "z_order"

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """Build opt-in sorted-ingestion SQL for Databricks."""
        mode, method = self.resolve_sorted_ingestion_strategy()
        if mode == "off":
            return None

        sorted_column_names = ", ".join(column.name for column in sort_columns)
        if method == "ctas":
            return f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM {table_name} ORDER BY {sorted_column_names}"
        if method == "z_order":
            return f"OPTIMIZE {table_name} ZORDER BY ({sorted_column_names})"
        if method == "liquid_clustering":
            return f"ALTER TABLE {table_name} CLUSTER BY ({sorted_column_names})"

        raise ValueError(f"Sorted ingestion method '{method}' is not supported for Databricks.")

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Databricks-specific CLI arguments."""
        db_group = parser.add_argument_group("Databricks Arguments")
        db_group.add_argument("--server-hostname", type=str, help="Databricks server hostname")
        db_group.add_argument("--http-path", type=str, help="Databricks SQL Warehouse HTTP path")
        db_group.add_argument("--access-token", type=str, help="Databricks access token")
        db_group.add_argument("--catalog", type=str, default="workspace", help="Databricks catalog name")
        db_group.add_argument(
            "--schema", type=str, default=None, help="Databricks schema name (auto-generated if not specified)"
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Databricks adapter from unified configuration."""
        from benchbox.utils.database_naming import generate_database_name

        # Try auto-detection if credentials not provided
        adapter_config = {}
        very_verbose = config.get("very_verbose", False)

        # Check if we have valid (non-placeholder) credentials
        def is_placeholder(value):
            if not value:
                return True
            str_val = str(value)
            # Common placeholder patterns
            return (
                "your-workspace" in str_val
                or "your-warehouse-id" in str_val
                or "${" in str_val  # Environment variable placeholder
                or "example" in str_val.lower()
            )

        if not all(
            [
                config.get("server_hostname") and not is_placeholder(config.get("server_hostname")),
                config.get("http_path") and not is_placeholder(config.get("http_path")),
                config.get("access_token") and not is_placeholder(config.get("access_token")),
            ]
        ):
            auto_config = cls._auto_detect_databricks_config(very_verbose=very_verbose)
            if auto_config:
                adapter_config.update(auto_config)

        # Override with explicit config values (but skip placeholders)
        for key in ["server_hostname", "http_path", "access_token"]:
            if config.get(key) and not is_placeholder(config.get(key)):
                adapter_config[key] = config[key]

        # Handle catalog
        adapter_config["catalog"] = config.get("catalog", "workspace")

        # Handle schema - prioritize auto-generation when benchmark context is available
        # This ensures schema names reflect benchmark/scale/tuning configuration,
        # rather than using static values from credentials files
        provided_schema = config.get("schema")
        has_benchmark_context = "benchmark" in config and "scale_factor" in config

        if has_benchmark_context:
            # When running a benchmark, always auto-generate schema name unless
            # user provided an explicit non-default override
            is_default_schema = provided_schema in (None, "", "benchbox")

            if is_default_schema:
                # Generate proper schema name using benchmark configuration
                schema_name = generate_database_name(
                    benchmark_name=config["benchmark"],
                    scale_factor=config["scale_factor"],
                    platform="databricks",
                    tuning_config=config.get("tuning_config"),
                )
                adapter_config["schema"] = schema_name
            else:
                # User provided explicit non-default schema - honor it
                adapter_config["schema"] = provided_schema
        else:
            # No benchmark context - fall back to provided schema or default
            adapter_config["schema"] = provided_schema or "benchbox"

        # Pass through other relevant config
        for key in [
            "tuning_config",
            "verbose_enabled",
            "very_verbose",
            "uc_catalog",
            "uc_schema",
            "uc_volume",
            "staging_root",
            "region",
            "cloud_region",
            "workspace_region",
            "cluster_size",
            "auto_terminate_minutes",
            "enable_delta_optimization",
            "delta_auto_optimize",
            "delta_auto_compact",
            "create_catalog",
            "disable_result_cache",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    @staticmethod
    def _auto_detect_databricks_config(very_verbose: bool = False):
        """Auto-detect Databricks configuration from SDK."""
        logger = logging.getLogger("DatabricksAdapter")
        try:
            from databricks.sdk import WorkspaceClient
            from databricks.sdk.service.sql import WarehousesAPI

            if very_verbose:
                logger.info("Attempting to auto-detect Databricks configuration from SDK...")

            workspace = WorkspaceClient()
            server_hostname = workspace.config.host.replace("https://", "")
            access_token = workspace.config.token

            if very_verbose:
                logger.info(f"Found Databricks host: {server_hostname}")

            warehouses = list(WarehousesAPI(workspace.api_client).list())
            if very_verbose:
                logger.info(f"Found {len(warehouses)} Databricks SQL Warehouses.")
                for wh in warehouses:
                    logger.info(f"  - Warehouse: {wh.name}, State: {wh.state}, ID: {wh.id}")

            selected_warehouse = _select_databricks_warehouse(warehouses, very_verbose, logger)

            http_path = None
            if selected_warehouse:
                http_path = f"/sql/1.0/warehouses/{selected_warehouse.id}"
                if very_verbose:
                    logger.info(f"Using HTTP path: {http_path}")
            elif very_verbose:
                logger.warning("No suitable warehouse found for auto-detection.")

            return {
                "server_hostname": server_hostname,
                "http_path": http_path,
                "access_token": access_token,
            }
        except Exception as e:
            if very_verbose:
                logger.error(f"Databricks auto-detection failed: {e}")
            return None

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Databricks platform information.

        Captures comprehensive Databricks configuration including:
        - Runtime/Spark version
        - Warehouse/cluster size and configuration
        - Compute tier and pricing information (best effort)
        - Photon acceleration status
        - Auto-scaling configuration

        Gracefully degrades if SDK is unavailable or permissions are insufficient.
        """
        clustering_strategy = self._resolve_databricks_clustering_strategy()
        effective_config = self.get_effective_tuning_configuration()
        platform_opts = getattr(effective_config, "platform_optimizations", None)

        platform_info = {
            "platform_type": "databricks",
            "platform_name": "Databricks",
            "connection_mode": "remote",
            "host": self.server_hostname,
            "configuration": {
                "server_hostname": self.server_hostname,
                "catalog": self.catalog,
                "schema": self.schema,
                "http_path": self.http_path,
                "warehouse_id": self._warehouse_id_from_http_path(self.http_path),
                "staging_root": self.staging_root,
                "uc_catalog": self.uc_catalog,
                "uc_schema": self.uc_schema,
                "uc_volume": self.uc_volume,
                "region": self.region,
                "enable_delta_optimization": self.enable_delta_optimization,
                "delta_auto_optimize": self.delta_auto_optimize,
                "delta_auto_compact": self.delta_auto_compact,
                "cluster_size": self.cluster_size,
                "auto_terminate_minutes": self.auto_terminate_minutes,
                "cluster_mode": getattr(self, "cluster_mode", None),
                "spark_version": getattr(self, "spark_version", None),
                "result_cache_enabled": not self.disable_result_cache,
                "databricks_clustering_strategy": clustering_strategy,
                "liquid_clustering_enabled": bool(getattr(platform_opts, "liquid_clustering_enabled", False)),
                "liquid_clustering_columns_config": list(getattr(platform_opts, "liquid_clustering_columns", [])),
                "liquid_clustering_operations": list(self._liquid_clustering_operations),
                "z_order_operations": list(self._z_order_operations),
            },
        }

        # Get client library version
        try:
            import databricks.sql

            platform_info["client_library_version"] = getattr(databricks.sql, "__version__", None)
        except (ImportError, AttributeError):
            platform_info["client_library_version"] = None

        # Try to get Databricks runtime version from connection
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT version()")
                result = cursor.fetchone()
                if result:
                    platform_info["platform_version"] = result[0]
                else:
                    # Try alternative query for Spark version
                    cursor.execute("SELECT spark_version() as version")
                    result = cursor.fetchone()
                    platform_info["platform_version"] = result[0] if result else None
                platform_info["engine_version"] = platform_info["platform_version"]
                platform_info["engine_version_source"] = "sql_query"
                cursor.close()
            except Exception as e:
                self.logger.debug(f"Could not query Databricks runtime version: {e}")
                platform_info["platform_version"] = None
        else:
            platform_info["platform_version"] = None

        # Try to get warehouse metadata using Databricks SDK (best effort)
        warehouse_id = self._warehouse_id_from_http_path(self.http_path)
        try:
            from databricks.sdk import WorkspaceClient

            if warehouse_id:
                # Create workspace client
                workspace = WorkspaceClient(host=f"https://{self.server_hostname}", token=self.access_token)

                # Get warehouse configuration
                warehouse = workspace.warehouses.get(warehouse_id)

                # Detect if this is a serverless warehouse
                # Serverless warehouses have warehouse_type=PRO + enable_serverless_compute=True
                is_serverless = (
                    hasattr(warehouse, "warehouse_type")
                    and hasattr(warehouse, "enable_serverless_compute")
                    and warehouse.warehouse_type
                    and warehouse.warehouse_type.value == "PRO"
                    and warehouse.enable_serverless_compute is True
                )

                # Get raw warehouse type and override to SERVERLESS if detected
                raw_warehouse_type = (
                    warehouse.warehouse_type.value
                    if hasattr(warehouse, "warehouse_type") and warehouse.warehouse_type
                    else None
                )
                warehouse_type_display = "SERVERLESS" if is_serverless else raw_warehouse_type

                # Extract channel name and version from channel object
                channel_name = None
                warehouse_version = None
                if hasattr(warehouse, "channel") and warehouse.channel:
                    if hasattr(warehouse.channel, "name") and warehouse.channel.name:
                        channel_name = warehouse.channel.name.value
                    if hasattr(warehouse.channel, "dbsql_version"):
                        warehouse_version = warehouse.channel.dbsql_version

                    # Log if extraction fails to help debugging
                    if channel_name is None:
                        self.logger.debug(f"Channel name extraction failed for warehouse {warehouse_id}")
                    if warehouse_version is None:
                        self.logger.debug(f"Warehouse version extraction failed for warehouse {warehouse_id}")

                platform_info["compute_configuration"] = {
                    "warehouse_id": warehouse.id,
                    "warehouse_name": warehouse.name if hasattr(warehouse, "name") else None,
                    "warehouse_size": warehouse.cluster_size if hasattr(warehouse, "cluster_size") else None,
                    "warehouse_type": warehouse_type_display,
                    "auto_stop_mins": warehouse.auto_stop_mins if hasattr(warehouse, "auto_stop_mins") else None,
                    "min_num_clusters": warehouse.min_num_clusters if hasattr(warehouse, "min_num_clusters") else None,
                    "max_num_clusters": warehouse.max_num_clusters if hasattr(warehouse, "max_num_clusters") else None,
                    "enable_photon": warehouse.enable_photon if hasattr(warehouse, "enable_photon") else None,
                    "enable_serverless_compute": warehouse.enable_serverless_compute
                    if hasattr(warehouse, "enable_serverless_compute")
                    else None,
                    "spot_instance_policy": warehouse.spot_instance_policy.value
                    if hasattr(warehouse, "spot_instance_policy") and warehouse.spot_instance_policy
                    else None,
                    "channel": channel_name,
                    "warehouse_version": warehouse_version,
                    "state": warehouse.state.value if hasattr(warehouse, "state") else None,
                    "warehouse_metadata_collection_status": "available",
                }

                self.logger.debug(f"Successfully captured Databricks warehouse metadata for {warehouse_id}")

        except ImportError as e:
            self.logger.debug("databricks-sdk not installed, skipping warehouse metadata collection")
            platform_info["compute_configuration"] = self._unavailable_warehouse_metadata(warehouse_id, e)
        except Exception as e:
            self.logger.debug(
                f"Could not fetch Databricks warehouse metadata (insufficient permissions or API error): {e}"
            )
            platform_info["compute_configuration"] = self._unavailable_warehouse_metadata(warehouse_id, e)

        return platform_info

    def get_normalized_result_metadata(
        self,
        *,
        connection: Any | None = None,
        platform_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return Databricks-specific normalized workspace and warehouse metadata."""
        info = dict(platform_info) if isinstance(platform_info, Mapping) else self.get_platform_info(connection)
        metadata = build_default_normalized_result_metadata(self, connection=connection, platform_info=info)
        config = info.get("configuration") if isinstance(info.get("configuration"), Mapping) else {}
        compute = info.get("compute_configuration") if isinstance(info.get("compute_configuration"), Mapping) else {}

        metadata["platform_deployment"] = self._databricks_deployment_metadata(config, compute)
        metadata["platform_cloud"] = self._databricks_cloud_metadata(config)
        metadata["platform_compute"] = self._databricks_compute_metadata(config, compute)
        metadata["platform_storage"] = self._databricks_storage_metadata(config)
        return metadata

    @staticmethod
    def _warehouse_id_from_http_path(http_path: str | None) -> str | None:
        if not http_path or "/warehouses/" not in http_path:
            return None
        return http_path.split("/warehouses/")[-1].strip("/") or None

    @staticmethod
    def _is_serverless_warehouse(compute: Mapping[str, Any]) -> bool:
        warehouse_type = str(compute.get("warehouse_type") or "").lower()
        return bool(compute.get("enable_serverless_compute") or warehouse_type == "serverless")

    @staticmethod
    def _unavailable_warehouse_metadata(warehouse_id: str | None, exc: Exception) -> dict[str, Any]:
        return _compact_metadata(
            {
                "warehouse_id": warehouse_id,
                "warehouse_metadata_collection_status": "unavailable",
                "warehouse_metadata_error_class": type(exc).__name__,
                "warehouse_metadata_error_message": str(exc),
            }
        )

    @staticmethod
    def _databricks_cloud_provider(host: Any) -> str | None:
        host_value = str(host or "").lower()
        if "azuredatabricks.net" in host_value:
            return "azure"
        if "gcp.databricks.com" in host_value:
            return "gcp"
        if "databricks.com" in host_value:
            return "aws"
        return None

    @classmethod
    def _databricks_deployment_metadata(
        cls,
        config: Mapping[str, Any],
        compute: Mapping[str, Any],
    ) -> dict[str, Any]:
        observed = bool(compute)
        serverless = cls._is_serverless_warehouse(compute)
        return _compact_metadata(
            {
                "deployment_type": "serverless" if serverless else "managed_cloud",
                "connection_mode": "remote",
                "endpoint_class": "cloud_endpoint",
                "metadata_source": "observed" if observed else "requested",
                "collection_status": "available" if observed else "partial",
                "workspace_host": config.get("server_hostname"),
                "http_path": config.get("http_path"),
                "warehouse_id": compute.get("warehouse_id") or config.get("warehouse_id"),
                "catalog": config.get("catalog"),
                "schema": config.get("schema"),
            }
        )

    @classmethod
    def _databricks_cloud_metadata(cls, config: Mapping[str, Any]) -> dict[str, Any]:
        host = config.get("server_hostname")
        region = config.get("region") or config.get("cloud_region") or config.get("workspace_region")
        provider = cls._databricks_cloud_provider(host)
        has_cloud_metadata = bool(provider or region or host)
        return _compact_metadata(
            {
                "provider": provider,
                "region": region,
                "workspace": host,
                "region_collection_status": "available" if region else "unavailable",
                "source": "inferred" if provider else "requested" if has_cloud_metadata else "unavailable",
                "collection_status": "partial" if has_cloud_metadata else "unavailable",
            }
        )

    @classmethod
    def _databricks_compute_metadata(
        cls,
        config: Mapping[str, Any],
        compute: Mapping[str, Any],
    ) -> dict[str, Any]:
        observed = any(
            compute.get(key) is not None
            for key in (
                "warehouse_name",
                "warehouse_size",
                "warehouse_type",
                "enable_photon",
                "enable_serverless_compute",
                "warehouse_version",
                "state",
            )
        )
        warehouse_id = compute.get("warehouse_id") or config.get("warehouse_id")
        serverless = cls._is_serverless_warehouse(compute)
        auto_stop_mins = (
            compute.get("auto_stop_mins")
            if compute.get("auto_stop_mins") is not None
            else config.get("auto_terminate_minutes")
        )
        return _compact_metadata(
            {
                "warehouse": compute.get("warehouse_name"),
                "warehouse_id": warehouse_id,
                "warehouse_size": compute.get("warehouse_size") or config.get("cluster_size"),
                "warehouse_type": compute.get("warehouse_type"),
                "serverless": serverless if observed else None,
                "photon_enabled": compute.get("enable_photon"),
                "min_cluster_count": compute.get("min_num_clusters"),
                "max_cluster_count": compute.get("max_num_clusters"),
                "auto_stop_mins": auto_stop_mins,
                "spot_instance_policy": compute.get("spot_instance_policy"),
                "channel": compute.get("channel"),
                "warehouse_version": compute.get("warehouse_version"),
                "state": compute.get("state"),
                "result_cache_enabled": config.get("result_cache_enabled"),
                "delta_auto_optimize": config.get("delta_auto_optimize"),
                "delta_auto_compact": config.get("delta_auto_compact"),
                "warehouse_metadata_collection_status": compute.get("warehouse_metadata_collection_status"),
                "warehouse_metadata_error_class": compute.get("warehouse_metadata_error_class"),
                "warehouse_metadata_error_message": compute.get("warehouse_metadata_error_message"),
                "source": "observed" if observed else "requested",
                "collection_status": "available" if observed else "partial",
            }
        )

    @staticmethod
    def _databricks_storage_metadata(config: Mapping[str, Any]) -> dict[str, Any]:
        staging_location = config.get("staging_root")
        if not staging_location and config.get("uc_catalog") and config.get("uc_schema") and config.get("uc_volume"):
            staging_location = f"dbfs:/Volumes/{config['uc_catalog']}/{config['uc_schema']}/{config['uc_volume']}"
        has_storage = bool(staging_location or config.get("catalog") or config.get("schema"))
        return _compact_metadata(
            {
                "table_format": "delta",
                "staging_location": staging_location,
                "catalog": config.get("catalog"),
                "schema": config.get("schema"),
                "uc_catalog": config.get("uc_catalog"),
                "uc_schema": config.get("uc_schema"),
                "uc_volume": config.get("uc_volume"),
                "source": "requested" if has_storage else "unavailable",
                "collection_status": "partial" if has_storage else "unavailable",
            }
        )

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Databricks."""
        return "databricks"

    def _get_connection_params(self, **connection_config) -> dict[str, Any]:
        """Get standardized connection parameters."""
        return {
            "server_hostname": connection_config.get("server_hostname", self.server_hostname),
            "http_path": connection_config.get("http_path", self.http_path),
            "access_token": connection_config.get("access_token", self.access_token),
        }

    def _create_admin_connection(self, **connection_config) -> Any:
        """Create Databricks connection for admin operations."""
        params = self._get_connection_params(**connection_config)

        # Basic connection without session configuration to work with all warehouse types
        return databricks_sql.connect(**params, user_agent_entry="BenchBox/1.0")

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if schema exists in Databricks catalog."""
        try:
            connection = self._create_admin_connection(**connection_config)
            cursor = connection.cursor()

            catalog = connection_config.get("catalog", self.catalog)
            schema = connection_config.get("schema", self.schema)

            # Check if catalog exists
            cursor.execute("SHOW CATALOGS")
            catalogs = [row[0] for row in cursor.fetchall()]

            if catalog not in catalogs:
                return False

            # Check if schema exists in catalog
            cursor.execute(f"SHOW SCHEMAS IN {catalog}")
            schemas = [row[0] for row in cursor.fetchall()]

            return schema in schemas

        except Exception:
            # If we can't connect or check, assume schema doesn't exist
            return False
        finally:
            if "connection" in locals():
                connection.close()

    def drop_database(self, **connection_config) -> None:
        """Drop schema in Databricks catalog."""
        try:
            connection = self._create_admin_connection(**connection_config)
            cursor = connection.cursor()

            catalog = connection_config.get("catalog", self.catalog)
            schema = connection_config.get("schema", self.schema)

            # Drop schema and all its tables
            cursor.execute(f"DROP SCHEMA IF EXISTS {catalog}.{schema} CASCADE")

        except Exception as e:
            raise RuntimeError(f"Failed to drop Databricks schema {catalog}.{schema}: {e}") from e
        finally:
            if "connection" in locals():
                connection.close()

    def create_connection(self, **connection_config) -> Any:
        """Create optimized Databricks SQL connection."""
        self.log_operation_start("Databricks connection")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        try:
            params = self._get_connection_params(**connection_config)
            self.log_very_verbose(
                f"Databricks connection params: host={params.get('server_hostname')}, catalog={self.catalog}"
            )

            connection = self._create_admin_connection(**connection_config)

            # Test connection and set catalog
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            self.log_very_verbose("Databricks connection test successful")

            # Set catalog and schema context
            # If database is being reused, schema already exists - set it now
            # If database is new, schema will be created in create_schema() which will also set it
            cursor.execute(f"USE CATALOG {self.catalog}")
            if self.database_was_reused:
                cursor.execute(f"USE SCHEMA {self.schema}")
                self.log_very_verbose(f"Set schema context to {self.catalog}.{self.schema} (database reused)")
            else:
                self.log_very_verbose(f"Set catalog to {self.catalog}, schema will be set during schema creation")

            self.log_operation_complete(
                "Databricks connection",
                details=f"Connected to {params['server_hostname']}, catalog: {self.catalog}",
            )

            return connection

        except Exception as e:
            self.logger.error(f"Failed to connect to Databricks: {e}")
            raise

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using Databricks Delta Lake tables."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get constraint settings from tuning configuration
        enable_primary_keys, enable_foreign_keys = self._get_constraint_configuration()
        self._log_constraint_configuration(enable_primary_keys, enable_foreign_keys)
        self.log_verbose(
            f"Schema constraints - Primary keys: {enable_primary_keys}, Foreign keys: {enable_foreign_keys}"
        )

        try:
            cursor = connection.cursor()

            # Step 1: Ensure catalog exists (if create_catalog is enabled)
            # Step 2: Create schema BEFORE attempting to USE it (correct order)
            if self.create_catalog:
                cursor.execute(f"CREATE CATALOG IF NOT EXISTS {self.catalog}")
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.catalog}.{self.schema}")
                self.log_verbose(f"Created catalog and schema: {self.catalog}.{self.schema}")
            else:
                # Just create schema if catalog already exists
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.catalog}.{self.schema}")
                self.log_verbose(f"Created schema: {self.catalog}.{self.schema}")

            # Step 3: Set catalog and schema context (now that schema exists)
            cursor.execute(f"USE CATALOG {self.catalog}")
            cursor.execute(f"USE SCHEMA {self.schema}")
            self.log_very_verbose(f"Set schema context to: {self.catalog}.{self.schema}")

            # Use common schema creation helper
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

            # Debug: Log schema SQL generation results
            self.log_verbose(f"Received schema SQL from _create_schema_with_tuning: {len(schema_sql)} characters")
            self.log_very_verbose(f"Schema SQL (first 300 chars): {schema_sql[:300]}")

            if not schema_sql or not schema_sql.strip():
                self.logger.error(f"Schema SQL is empty! Benchmark class: {benchmark.__class__.__name__}")
                self.logger.error(f"Benchmark has get_schema_sql: {hasattr(benchmark, 'get_schema_sql')}")
                raise RuntimeError(f"No schema SQL generated for {benchmark.__class__.__name__}")

            # Transform SQL syntax for Databricks compatibility
            original_len = len(schema_sql)
            schema_sql = self._fix_databricks_sql_syntax(schema_sql)
            self.log_very_verbose(
                f"After _fix_databricks_sql_syntax: {len(schema_sql)} characters (was {original_len})"
            )
            if len(schema_sql) != original_len:
                self.log_verbose(f"SQL length changed after Databricks syntax fix: {original_len} -> {len(schema_sql)}")

            # Split schema into individual statements and execute
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            # Debug: Log statement count
            self.log_verbose(f"Parsed {len(statements)} CREATE TABLE statements from schema SQL")
            if not statements:
                self.logger.error("No CREATE TABLE statements found after parsing schema SQL")
                self.logger.error(f"Raw schema SQL (first 500 chars): {schema_sql[:500]}")
                raise RuntimeError("Schema SQL produced no executable statements")

            # Apply Databricks DDL optimization (DDL_OPTIMIZE rule: convert_to_delta_table)
            statements = [self._convert_to_delta_table(s) for s in statements]

            # Execute statements with error handling from base adapter
            tables_created, failed_tables = self._execute_schema_statements(statements, cursor)

            duration = elapsed_seconds(start_time)
            self.log_operation_complete("Schema creation", duration, f"{tables_created} Delta Lake tables created")

            return duration

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise
        finally:
            if "cursor" in locals():
                cursor.close()

    def _ensure_uc_volume_exists(self, uc_volume_path: str, connection: Any) -> None:
        """Ensure UC Volume exists, creating it if necessary.

        This method also creates the schema if it doesn't exist, providing
        a complete zero-setup experience for UC Volume workflows.

        Args:
            uc_volume_path: UC Volume path (e.g., dbfs:/Volumes/catalog/schema/volume)
            connection: Databricks SQL connection

        Raises:
            ValueError: If volume path is invalid or creation fails
        """
        # Parse volume path: dbfs:/Volumes/catalog/schema/volume
        volume_path = uc_volume_path.replace("dbfs:", "").rstrip("/")

        # Extract catalog, schema, volume from /Volumes/catalog/schema/volume
        if not volume_path.startswith("/Volumes/"):
            raise ValueError(f"Invalid UC Volume path: {uc_volume_path}. Must start with dbfs:/Volumes/")

        path_parts = volume_path.split("/")
        # path_parts = ['', 'Volumes', 'catalog', 'schema', 'volume', ...]

        if len(path_parts) < 5:
            raise ValueError(
                f"Invalid UC Volume path: {uc_volume_path}. "
                "Expected dbfs:/Volumes/catalog/schema/volume (optionally with a subpath)."
            )

        catalog = path_parts[2]
        schema = path_parts[3]
        volume = path_parts[4]

        self.log_verbose(f"Ensuring UC Volume exists: {catalog}.{schema}.{volume}")

        try:
            cursor = connection.cursor()

            # First, ensure the schema exists (required for volume creation)
            try:
                create_schema_sql = f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}"
                cursor.execute(create_schema_sql)
                self.log_very_verbose(f"Schema ready: {catalog}.{schema}")
            except Exception as schema_error:
                # If schema creation fails due to permissions, provide clear guidance
                error_msg = str(schema_error).lower()
                if "permission" in error_msg or "access denied" in error_msg or "unauthorized" in error_msg:
                    raise ValueError(
                        f"Permission denied creating schema: {catalog}.{schema}. "
                        f"Ensure you have CREATE SCHEMA permission on catalog {catalog}. "
                        f"Or create it manually: CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}"
                    ) from None
                raise

            # Now create the volume (IF NOT EXISTS is safe)
            create_volume_sql = f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{volume}"
            cursor.execute(create_volume_sql)

            self.log_verbose(f"✅ UC Volume ready: {catalog}.{schema}.{volume}")
            cursor.close()

        except ValueError:
            # Re-raise ValueError exceptions (our custom error messages)
            raise
        except Exception as e:
            error_msg = str(e).lower()

            # Check for permission errors
            if "permission" in error_msg or "access denied" in error_msg or "unauthorized" in error_msg:
                raise ValueError(
                    f"Permission denied creating UC Volume: {catalog}.{schema}.{volume}. "
                    f"Ensure you have CREATE VOLUME permission on schema {catalog}.{schema}. "
                    f"Or create it manually: CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{volume}"
                ) from e

            # Generic error
            raise ValueError(
                f"Failed to create UC Volume {catalog}.{schema}.{volume}: {e}. "
                f"Try creating manually: CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{volume}"
            ) from e

    def _upload_to_uc_volume(
        self,
        data_files: dict[str, Any],
        uc_volume_path: str,
        data_dir: Path,
        force_upload: bool = False,
    ) -> dict[str, str]:
        """Upload local data files to Unity Catalog Volume using Databricks Files API.

        For sharded files (e.g., customer.tbl.1.zst, customer.tbl.2.zst, ...),
        this method will find and upload ALL chunk files, returning a wildcard pattern
        for COPY INTO to use.

        Args:
            data_files: Dictionary of table_name -> local file path (may be first chunk only)
            uc_volume_path: UC Volume path (e.g., dbfs:/Volumes/catalog/schema/volume)
            data_dir: Base data directory (for resolving relative paths)

        Returns:
            Dictionary mapping table names to UC Volume file URIs (with wildcards for sharded tables)

        Raises:
            ImportError: If databricks-sdk not available
            Exception: If upload fails
        """
        try:
            from databricks.sdk import WorkspaceClient
        except ImportError:
            raise ImportError(
                get_package_install_message("databricks-sdk", "databricks-sdk required for UC Volume uploads.")
            ) from None

        workspace = WorkspaceClient(
            host=f"https://{self.server_hostname}",
            token=self.access_token,
        )

        volume_path = uc_volume_path.replace("dbfs:", "")

        from benchbox.utils.cloud_storage import DatabricksPath

        if isinstance(data_dir, DatabricksPath):
            self.log_very_verbose(f"Using DatabricksPath local component: {data_dir._path}")

        manifest_path = self._resolve_uc_manifest_path(data_dir)

        # Check if we can reuse existing data
        reuse_result = self._try_reuse_uc_volume_data(uc_volume_path, manifest_path, force_upload)
        if reuse_result is not None:
            return reuse_result

        # Upload manifest FIRST for atomic consistency
        if manifest_path.exists():
            try:
                self._upload_manifest_to_uc_volume(manifest_path, uc_volume_path, workspace)
            except Exception as e:
                self.logger.warning(f"Failed to upload manifest to UC Volume: {e}")

        upload_root = self._resolve_local_upload_root(data_dir)
        uploaded_files: dict[str, Any] = {}
        for table_name, file_path in data_files.items():
            local_paths = self._collect_local_paths_for_table(table_name, file_path)
            if not local_paths:
                continue
            upload_entries = self._build_uc_upload_entries(local_paths, upload_root)
            result = self._upload_table_to_uc(
                table_name, local_paths, upload_entries, volume_path, uc_volume_path, workspace, upload_root
            )
            if result is not None:
                uploaded_files[table_name] = result

        # Upload manifest last if present
        if manifest_path.exists():
            try:
                self._upload_manifest_to_uc_volume(manifest_path, uc_volume_path, workspace)
            except Exception as e:
                self.logger.warning(f"Failed to upload manifest to UC Volume: {e}")

        return uploaded_files

    def _collect_local_paths_for_table(self, table_name: str, file_path: Any) -> list[Path]:
        """Resolve and validate candidate local paths for a single table's data file(s)."""
        local_paths: list[Path] = []
        for candidate in self._normalize_table_file_inputs(file_path):
            local_path = Path(candidate) if not isinstance(candidate, Path) else candidate
            if not local_path.is_absolute():
                local_path = local_path.resolve()
            if not local_path.exists():
                self.logger.error(f"File not found for table {table_name}: {local_path}")
                self.logger.error(f"  Checked path: {local_path.absolute()}")
                self.logger.error(f"  CWD: {Path.cwd()}")
                continue
            self.log_very_verbose(f"Found {local_path.name} ({local_path.stat().st_size:,} bytes) at {local_path}")
            local_paths.append(local_path)
        return local_paths

    def _upload_table_to_uc(
        self,
        table_name: str,
        local_paths: list[Path],
        upload_entries: list[tuple[Path, str]],
        volume_path: str,
        uc_volume_path: str,
        workspace: Any,
        upload_root: Path,
    ) -> Any:
        """Upload one table's file(s) to UC Volume; returns the URI, list of URIs, or None."""
        if len(local_paths) == 1:
            return self._upload_single_table_path(
                table_name, local_paths[0], upload_entries[0][1], volume_path, uc_volume_path, workspace, upload_root
            )
        return self._upload_multi_table_paths(table_name, upload_entries, volume_path, uc_volume_path, workspace)

    def _upload_single_table_path(
        self,
        table_name: str,
        local_path: Path,
        remote_path: str,
        volume_path: str,
        uc_volume_path: str,
        workspace: Any,
        upload_root: Path,
    ) -> Any:
        """Upload exactly one file for a table, auto-expanding to sharded chunks if detected."""
        is_sharded, _pattern, chunk_files = self._detect_sharded_files(local_path, table_name)
        if is_sharded and chunk_files:
            sharded_entries = self._build_uc_upload_entries(chunk_files, upload_root)
            sharded_targets = [rp for _lp, rp in sharded_entries]
            self._upload_sharded_files(
                chunk_files, volume_path, uc_volume_path, workspace, remote_paths=sharded_targets
            )
            wildcard = self._detect_manifest_wildcard(sharded_targets)
            if wildcard:
                uri = self._join_uri_path(f"dbfs:{volume_path}", wildcard)
                self.log_verbose(f"Uploaded {len(chunk_files)} chunks for {table_name}, using wildcard: {uri}")
                return uri
            return [self._join_uri_path(f"dbfs:{volume_path}", rp) for rp in sharded_targets]
        return self._upload_single_file(local_path, volume_path, uc_volume_path, workspace, remote_path=remote_path)

    def _upload_multi_table_paths(
        self,
        table_name: str,
        upload_entries: list[tuple[Path, str]],
        volume_path: str,
        uc_volume_path: str,
        workspace: Any,
    ) -> Any:
        """Upload multiple files for a table; returns wildcard URI or list of URIs."""
        wildcard = self._detect_manifest_wildcard([rp for _lp, rp in upload_entries])
        uploaded_uris: list[str] = []
        for local_path, remote_path in upload_entries:
            uri = self._upload_single_file(local_path, volume_path, uc_volume_path, workspace, remote_path=remote_path)
            if uri is not None:
                uploaded_uris.append(uri)
        if wildcard:
            wildcard_uri = self._join_uri_path(f"dbfs:{volume_path}", wildcard)
            self.log_verbose(
                f"Uploaded {len(uploaded_uris)} files for {table_name}, using wildcard pattern: {wildcard_uri}"
            )
            return wildcard_uri
        return uploaded_uris or None

    def _resolve_uc_manifest_path(self, data_dir: Path) -> Path:
        """Determine local manifest path for UC Volume upload validation."""
        try:
            from benchbox.utils.cloud_storage import DatabricksPath
        except Exception:
            DatabricksPath = None

        if DatabricksPath is not None and isinstance(data_dir, DatabricksPath):
            return data_dir._path / MANIFEST_FILENAME
        else:
            return Path(data_dir) / MANIFEST_FILENAME

    def _resolve_local_upload_root(self, data_dir: Path) -> Path:
        """Resolve the local root whose relative paths should be preserved in UC Volumes."""
        try:
            from benchbox.utils.cloud_storage import DatabricksPath
        except Exception:
            DatabricksPath = None

        if DatabricksPath is not None and isinstance(data_dir, DatabricksPath):
            return data_dir._path.resolve()
        return Path(data_dir).resolve()

    @staticmethod
    def _build_uc_upload_entries(local_paths: list[Path], upload_root: Path) -> list[tuple[Path, str]]:
        """Build manifest-stable relative targets for UC Volume uploads.

        Uses a single root for all paths: upload_root if every path is under it,
        otherwise the common parent of all paths. This avoids mixed-strategy
        collisions when only some paths fall outside upload_root.
        """
        all_under_root = all(path.is_relative_to(upload_root) for path in local_paths)

        if all_under_root:
            root = upload_root
        else:
            root = Path(os.path.commonpath([str(path.parent) for path in local_paths]))

        entries = [(path, path.relative_to(root).as_posix()) for path in local_paths]

        seen_targets: set[str] = set()
        for _local_path, remote_path in entries:
            if remote_path in seen_targets:
                raise ValueError(f"UC Volume upload would overwrite duplicate remote path '{remote_path}'")
            seen_targets.add(remote_path)

        return entries

    @staticmethod
    def _join_uri_path(root: str, relative_path: str) -> str:
        """Join a URI/path root with a relative POSIX path."""
        cleaned = relative_path.lstrip("/")
        if not cleaned:
            return root.rstrip("/")
        return f"{root.rstrip('/')}/{cleaned}"

    @staticmethod
    def _split_remote_path(path_like: Any) -> tuple[str, PurePosixPath] | None:
        """Split a remote URI into its anchor and POSIX path."""
        raw = str(path_like).rstrip("/")
        if raw.startswith("dbfs:/"):
            suffix = raw[len("dbfs:/") :].lstrip("/")
            return "dbfs:/", PurePosixPath("/") / suffix if suffix else PurePosixPath("/")

        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}", PurePosixPath(parsed.path or "/")

        return None

    def _common_remote_directory(self, file_paths: list[Any]) -> str | None:
        """Return a shared remote directory for a list of cloud/DBFS file URIs."""
        raw_split_paths = [self._split_remote_path(path_like) for path_like in file_paths]
        if not raw_split_paths or any(item is None for item in raw_split_paths):
            return None

        split_paths = cast(list[tuple[str, PurePosixPath]], raw_split_paths)
        anchors = {anchor for anchor, _path in split_paths}
        if len(anchors) != 1:
            return None

        anchor = split_paths[0][0]
        parent_parts = [path.parent.parts for _anchor, path in split_paths]

        common_parts: list[str] = []
        for segments in zip(*parent_parts):
            if all(segment == segments[0] for segment in segments):
                common_parts.append(segments[0])
            else:
                break

        if not common_parts:
            return anchor

        common_path = PurePosixPath(*common_parts).as_posix().lstrip("/")
        if anchor == "dbfs:/":
            return f"dbfs:/{common_path}" if common_path else "dbfs:/"
        return f"{anchor}/{common_path}" if common_path else anchor

    def _try_reuse_uc_volume_data(
        self, uc_volume_path: str, manifest_path: Path, force_upload: bool
    ) -> dict[str, Any] | None:
        """Check if existing UC Volume data can be reused. Returns mapping or None."""
        if force_upload or not manifest_path.exists():
            return None

        validation_engine = UploadValidationEngine()
        verbose = getattr(self, "very_verbose", False)

        should_upload, validation_result = validation_engine.should_upload_data(
            remote_path=uc_volume_path,
            local_manifest_path=manifest_path,
            force_upload=force_upload,
            verbose=verbose,
        )

        if not should_upload:
            remote_manifest = validation_result.remote_manifest
            if remote_manifest:
                self.log_verbose("Reusing existing data from UC Volume (validation passed)")
                return self._get_remote_file_uris_from_manifest(uc_volume_path, remote_manifest)
            else:
                self.log_verbose("Pre-upload validation passed but remote manifest unavailable, proceeding with upload")

        return None

    def _detect_sharded_files(self, local_path: Path, table_name: str) -> tuple[bool, str, list[Path]]:
        """Detect if a file is part of a sharded set. Returns (is_sharded, pattern, chunk_files)."""
        filename = local_path.name
        parts = filename.split(".")

        is_sharded = False
        chunk_files: list[Path] = []
        pattern = ""

        compression_exts_nodot = {ext.lstrip(".") for ext in COMPRESSION_EXTENSIONS}

        if len(parts) >= 3:
            if len(parts) >= 4 and parts[-1] in compression_exts_nodot and parts[-2].isdigit():
                is_sharded = True
                base_parts = parts[:-2]
                compression = parts[-1]
                pattern = f"{'.'.join(base_parts)}.*.{compression}"
            elif parts[-1].isdigit():
                is_sharded = True
                base_parts = parts[:-1]
                pattern = f"{'.'.join(base_parts)}.*"

            if is_sharded:
                parent_dir = local_path.parent
                chunk_files = sorted([f for f in parent_dir.glob(pattern) if f.is_file()])
                if chunk_files:
                    self.log_verbose(f"Found {len(chunk_files)} chunk files for {table_name}: {pattern}")

        return is_sharded, pattern, chunk_files

    def _upload_file_content_to_uc(
        self, file_path: Path, target_path: str, uc_volume_path: str, workspace: Any
    ) -> None:
        """Read and upload a single file to UC Volume with validation."""
        from io import BytesIO

        expected_size = file_path.stat().st_size
        with open(file_path, "rb") as f:
            content = f.read()

        if len(content) == 0:
            self.logger.error(f"Read 0 bytes from {file_path} (expected {expected_size})")
            raise RuntimeError(f"Failed to read content from {file_path}")

        if len(content) != expected_size:
            self.logger.warning(f"Size mismatch for {file_path.name}: stat={expected_size}, read={len(content)}")

        workspace.files.upload(target_path, BytesIO(content), overwrite=True)
        self.log_very_verbose(f"Successfully uploaded {file_path.name} ({len(content):,} bytes)")

    def _upload_sharded_files(
        self,
        chunk_files: list[Path],
        volume_path: str,
        uc_volume_path: str,
        workspace: Any,
        remote_paths: list[str] | None = None,
    ) -> None:
        """Upload all chunk files for a sharded table."""
        if remote_paths is not None and len(remote_paths) != len(chunk_files):
            raise ValueError("remote_paths length must match chunk_files length")

        for index, chunk_file in enumerate(chunk_files):
            if not chunk_file.exists():
                self.logger.error(f"Chunk file disappeared: {chunk_file}")
                continue

            chunk_size = chunk_file.stat().st_size
            if chunk_size == 0:
                self.logger.warning(f"Skipping empty chunk file: {chunk_file.name}")
                continue

            target_relative = remote_paths[index] if remote_paths is not None else chunk_file.name
            target_path = self._join_uri_path(volume_path, target_relative)
            self.log_very_verbose(f"Uploading {chunk_file.name} ({chunk_size:,} bytes) to {target_path}")

            try:
                self._upload_file_content_to_uc(chunk_file, target_path, uc_volume_path, workspace)
            except Exception as e:
                self.logger.error(f"Failed to upload {chunk_file.name} to UC Volume: {e}")
                raise RuntimeError(f"Failed to upload {chunk_file.name} to {uc_volume_path}: {e}") from e

    def _upload_single_file(
        self,
        local_path: Path,
        volume_path: str,
        uc_volume_path: str,
        workspace: Any,
        remote_path: str | None = None,
    ) -> str | None:
        """Upload a single (non-sharded) file to UC Volume. Returns dbfs URI or None."""
        single_file_size = local_path.stat().st_size
        if single_file_size == 0:
            self.logger.warning(f"Skipping empty file: {local_path.name}")
            return None

        target_relative = remote_path or local_path.name
        target_path = self._join_uri_path(volume_path, target_relative)
        self.log_verbose(f"Uploading {local_path.name} ({single_file_size:,} bytes) to {target_path}")

        try:
            self._upload_file_content_to_uc(local_path, target_path, uc_volume_path, workspace)
            return f"dbfs:{target_path}"
        except Exception as e:
            self.logger.error(f"Failed to upload {local_path.name} to UC Volume: {e}")
            raise RuntimeError(f"Failed to upload {local_path.name} to {uc_volume_path}: {e}") from e

    def _upload_manifest_to_uc_volume(self, manifest_path: Path, uc_volume_path: str, workspace: Any) -> None:
        """Upload the manifest JSON to the UC Volume root."""
        try:
            target_path = uc_volume_path.replace("dbfs:", "")
            if not target_path.endswith("/" + MANIFEST_FILENAME):
                target_path = target_path.rstrip("/") + "/" + MANIFEST_FILENAME

            with open(manifest_path, "rb") as fh:
                content = fh.read()
            from io import BytesIO

            workspace.files.upload(target_path, BytesIO(content), overwrite=True)
            # Small log for visibility
            try:
                manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                tables = manifest.get("tables") or {}
                self.logger.info(f"Uploaded manifest to {uc_volume_path} ({len(content)} bytes, {len(tables)} tables)")
            except Exception:
                self.logger.info(f"Uploaded manifest to {uc_volume_path}")
        except Exception as e:
            raise RuntimeError(f"Manifest upload failed: {e}") from e

    def _get_remote_file_uris_from_manifest(self, uc_volume_path: str, remote_manifest: dict) -> dict[str, Any]:
        """Build UC Volume file URI map per table from manifest entries.

        For sharded tables, return a wildcard pattern like customer.tbl.*.zst
        """
        mapping: dict[str, Any] = {}
        tables = remote_manifest.get("tables") or {}
        for table, entries in tables.items():
            if not entries:
                continue
            if len(entries) == 1:
                rel = entries[0].get("path")
                if rel:
                    mapping[table] = self._join_uri_path(uc_volume_path.rstrip("/"), str(rel))
                continue
            names = [str(e.get("path")) for e in entries if e.get("path")]
            if not names:
                continue
            wildcard = self._detect_manifest_wildcard(names)
            if wildcard:
                mapping[table] = self._join_uri_path(uc_volume_path.rstrip("/"), wildcard)
            else:
                mapping[table] = [self._join_uri_path(uc_volume_path.rstrip("/"), name) for name in names]
        return mapping

    @staticmethod
    def _is_manifest_shard_name(name: str) -> bool:
        """Check if a filename looks like a TPC shard (e.g. customer.tbl.1, lineitem.tbl.3.zst).

        Note: names with purely numeric stems (e.g. "123.parquet") will match
        the trailing-digit heuristic. This is acceptable because such names do
        not appear in TPC benchmark manifests.
        """
        parts = Path(name).name.split(".")
        compression_exts_nodot = {ext.lstrip(".") for ext in COMPRESSION_EXTENSIONS}
        if len(parts) >= 4 and parts[-1] in compression_exts_nodot and parts[-2].isdigit():
            return True
        return len(parts) >= 2 and parts[-1].isdigit()

    @staticmethod
    def _manifest_pattern_for_name(name: str) -> tuple[str, str]:
        parts = name.split(".")
        if len(parts) >= 3 and parts[-2].isdigit():
            return ".".join(parts[:-2]), "." + parts[-1]
        if len(parts) >= 2 and parts[-1].isdigit():
            return ".".join(parts[:-1]), ""
        stem = Path(name).stem
        return stem, Path(name).suffix

    def _detect_manifest_wildcard(self, names: list[str]) -> str | None:
        if not names or not all(self._is_manifest_shard_name(name) for name in names):
            return None
        base0, ext0 = self._manifest_pattern_for_name(names[0])
        for name in names[1:]:
            base, ext = self._manifest_pattern_for_name(name)
            if base != base0 or ext != ext0:
                return None
        return f"{base0}.*{ext0}"

    @staticmethod
    def _normalize_table_file_inputs(file_paths: Any) -> list[Any]:
        """Normalize single-path or multi-path table inputs to a list."""
        if isinstance(file_paths, (str, Path)):
            return [file_paths]
        return list(file_paths)

    @staticmethod
    def _path_name(path_like: Any) -> str:
        """Return the basename for a local path or cloud URI."""
        import os

        path_str = str(path_like).rstrip("/")
        # Cloud URIs (dbfs:/, s3://, etc.) always use forward-slash separators.
        # For local paths, os.path.basename handles both / and \ on Windows.
        if "://" in path_str or path_str.startswith("dbfs:/"):
            return path_str.split("/")[-1]
        return os.path.basename(path_str)

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using Databricks COPY INTO from UC Volumes or cloud storage.

        This implementation avoids temporary views and uses COPY INTO for robust ingestion.
        """
        start_time = mono_time()
        self.log_operation_start("Data loading", f"benchmark: {benchmark.__class__.__name__}")
        self.log_very_verbose(f"Data directory: {data_dir}")

        table_stats = {}
        per_table_timings = {}  # Track detailed timings per table
        cursor = connection.cursor()

        try:
            from benchbox.platforms.base.data_loading import DataSource

            data_source = self._resolve_databricks_data_files(benchmark, data_dir)
            if not isinstance(data_source, DataSource):
                data_source = DataSource(source_type="legacy_test_mapping", tables=data_source)
            stage_root = self._resolve_stage_root(data_dir)
            data_source.tables = self._maybe_upload_to_uc_volume(data_source.tables, stage_root, data_dir, connection)

            # Ensure we're in the correct schema context for table operations
            cursor.execute(f"USE CATALOG {self.catalog}")
            cursor.execute(f"USE SCHEMA {self.schema}")
            self.log_verbose(f"Set schema context for data loading: {self.catalog}.{self.schema}")

            # Verify tables exist before attempting to load data
            cursor.execute(f"SHOW TABLES IN {self.catalog}.{self.schema}")
            existing_tables = {row[1].lower() for row in cursor.fetchall()}
            self.log_very_verbose(f"Found {len(existing_tables)} existing tables in {self.catalog}.{self.schema}")

            # Load data for each table using COPY INTO
            for table_name, file_path in data_source.tables.items():
                try:
                    load_start = mono_time()
                    row_count, copy_time, optimize_time = self._load_single_table(
                        cursor,
                        connection,
                        benchmark,
                        table_name,
                        file_path,
                        stage_root,
                        existing_tables,
                        data_source,
                    )
                    table_stats[table_name.upper()] = row_count
                    load_time = elapsed_seconds(load_start)

                    per_table_timings[table_name.upper()] = {
                        "copy_into_ms": copy_time * 1000,
                        "optimize_ms": optimize_time * 1000,
                        "total_ms": load_time * 1000,
                        "rows": row_count,
                    }

                    self.logger.info(f"✅ Loaded {row_count:,} rows into {table_name.upper()} in {load_time:.2f}s")

                except Exception as e:
                    self.logger.error(f"Failed to load {table_name}: {str(e)[:200]}")
                    table_stats[table_name.upper()] = 0
                    per_table_timings[table_name.upper()] = {
                        "copy_into_ms": 0,
                        "optimize_ms": 0,
                        "total_ms": 0,
                        "rows": 0,
                    }

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.log_operation_complete(
                "Data loading", total_time, f"{total_rows:,} total rows, {len(table_stats)} tables"
            )

        finally:
            cursor.close()

        return table_stats, total_time, per_table_timings

    def _resolve_databricks_data_files(self, benchmark, data_dir: Path):
        """Resolve data files via DataSourceResolver."""
        from benchbox.platforms.base.data_loading import DataSource, DataSourceResolver

        resolver = DataSourceResolver(
            platform_name=self.platform_name,
            table_mode=self.table_mode,
            platform_config=self.platform_config,
            requested_format=self.requested_table_format,
        )
        data_source = resolver.resolve(benchmark, data_dir)
        if not data_source or not data_source.tables:
            raise ValueError("No data files found. Ensure benchmark.generate_data() was called first.")

        normalized: dict[str, Any] = {}
        for table_name, table_files in data_source.tables.items():
            candidates = self._normalize_table_file_inputs(table_files)
            normalized[table_name] = candidates[0] if len(candidates) == 1 else candidates
        # Return a fresh DataSource so we don't mutate the resolver-owned object;
        # table_metadata is forwarded so the COPY INTO delimiter resolver still
        # sees manifest annotations.
        return DataSource(
            source_type=data_source.source_type,
            tables=normalized,
            table_formats=dict(data_source.table_formats),
            table_metadata=dict(data_source.table_metadata),
        )

    @staticmethod
    def _is_cloud_uri(s: str) -> bool:
        """Check if a string is a cloud storage URI."""
        return s.startswith(("s3://", "gs://", "abfss://", "dbfs:/"))

    def _resolve_stage_root(self, data_dir: Path) -> str:
        """Determine the staging root for COPY INTO operations."""
        from benchbox.utils.cloud_storage import DatabricksPath

        stage_root = None

        if isinstance(data_dir, DatabricksPath) and hasattr(data_dir, "dbfs_target") and data_dir.dbfs_target:
            stage_root = data_dir.dbfs_target.rstrip("/")
            self.log_verbose(f"Using DatabricksPath dbfs_target: {stage_root}")
        elif isinstance(self.staging_root, str) and self._is_cloud_uri(self.staging_root):
            stage_root = self.staging_root.rstrip("/")
        else:
            if self.uc_catalog and self.uc_schema and self.uc_volume:
                stage_root = f"dbfs:/Volumes/{self.uc_catalog}/{self.uc_schema}/{self.uc_volume}".rstrip("/")
            else:
                data_dir_str = str(data_dir)
                if self._is_cloud_uri(data_dir_str):
                    stage_root = data_dir_str.rstrip("/")

        if not stage_root:
            raise ValueError(
                "Databricks data loading requires a cloud/UC Volume staging location. "
                "Add --output flag with cloud path `dbfs:/`; `s3://`, `gs://`, `abfss://`."
            )
        return stage_root

    def _maybe_upload_to_uc_volume(self, data_files: dict, stage_root: str, data_dir: Path, connection: Any) -> dict:
        """Upload local data to UC Volume if needed. Returns updated data_files mapping."""
        from benchbox.utils.cloud_storage import DatabricksPath

        data_is_local = isinstance(data_dir, DatabricksPath) or not self._is_cloud_uri(str(data_dir))

        def _is_complete_uc_volume_path(p: str) -> bool:
            v = p.replace("dbfs:", "").rstrip("/")
            if not v.startswith("/Volumes/"):
                return False
            parts = v.split("/")
            return len(parts) >= 5

        if data_is_local and stage_root.startswith("dbfs:/Volumes/") and _is_complete_uc_volume_path(stage_root):
            self.log_verbose(f"Uploading local data to UC Volume: {stage_root}")
            self._ensure_uc_volume_exists(stage_root, connection)
            force_upload = getattr(self, "force_upload", False)
            original_files = dict(data_files)
            uploaded_files = self._upload_to_uc_volume(
                data_files,
                stage_root,
                data_dir,
                force_upload=force_upload,
            )
            data_files = uploaded_files if uploaded_files else original_files
            self.log_verbose("Upload to UC Volume completed")

        return data_files

    def _resolve_file_uri_and_delimiter(
        self,
        file_path,
        stage_root: str,
        *,
        table_name: str | None = None,
        data_source: Any | None = None,
        benchmark: Any | None = None,
    ) -> tuple[str, str, str]:
        """Resolve file URI, filename, and delimiter for a table's data file.

        Returns:
            Tuple of (file_uri, filename, delimiter)
        """
        if isinstance(file_path, list):
            if not file_path:
                raise ValueError("No data files were provided for Databricks COPY INTO")
            if len(file_path) == 1:
                file_path = file_path[0]
            else:
                # Pre-initialize so the wildcard branch can fall through to
                # filename_for_format with a known value (None → use wildcard name).
                common_dir = None
                wildcard = self._detect_manifest_wildcard([self._path_name(path_like) for path_like in file_path])
                if wildcard:
                    first_path = str(file_path[0])
                    if first_path.startswith("dbfs:/Volumes/"):
                        file_uri = f"{first_path.rsplit('/', 1)[0]}/{wildcard}"
                    else:
                        file_uri = f"{stage_root}/{wildcard}"
                    filename = wildcard
                else:
                    common_dir = self._common_remote_directory(file_path)
                    if common_dir is None:
                        raise ValueError(
                            "Databricks COPY INTO requires a single file, a remote directory, or a "
                            "shard-compatible file set per table."
                        )
                    file_uri = common_dir
                    filename = common_dir.rstrip("/").split("/")[-1]
                filename_for_format = (
                    self._path_name(file_path[0]) if common_dir is not None else filename.replace(".*", "")
                )
                dialect_path = Path(self._path_name(file_path[0]))
                delimiter = self._resolve_csv_delimiter(
                    data_source, table_name or dialect_path.stem, dialect_path, benchmark
                )
                return file_uri, filename, delimiter

        if isinstance(file_path, str) and file_path.startswith("dbfs:/Volumes/"):
            file_uri = file_path
            uri_path = file_path.replace("dbfs:", "")
            filename = uri_path.split("/")[-1]
        else:
            filename = self._path_name(file_path)
            file_uri = f"{stage_root}/{filename}"

        # Strip wildcard component for format detection
        filename_for_format = filename.replace(".*", "")
        dialect_path = Path(filename_for_format)
        delimiter = self._resolve_csv_delimiter(data_source, table_name or dialect_path.stem, dialect_path, benchmark)
        return file_uri, filename, delimiter

    def _resolve_csv_delimiter(self, data_source: Any, table_name: str, file_path: Path, benchmark: Any | None) -> str:
        """Resolve Databricks COPY INTO delimiter through the shared CSV dialect pipeline."""
        from benchbox.platforms.base.data_loading import NO_BENCHMARK, DataSource, resolve_csv_dialect

        dialect_source = data_source or DataSource(source_type="databricks_copy_into", tables={})
        return resolve_csv_dialect(
            dialect_source, table_name, file_path, benchmark if benchmark is not None else NO_BENCHMARK
        ).delimiter

    def _get_column_list_for_table(self, benchmark, table_name: str) -> str:
        """Get explicit column mapping from benchmark schema for COPY INTO."""
        if not hasattr(benchmark, "get_schema"):
            return ""
        try:
            schema = benchmark.get_schema()
            table_name_upper = table_name.upper()
            table_schema = schema.get(table_name.lower())
            if not table_schema:
                table_schema = schema.get(table_name_upper.lower())
            if not table_schema:
                table_schema = schema.get(table_name)

            if table_schema and "columns" in table_schema:
                columns = [col["name"] for col in table_schema["columns"]]
                if columns:
                    self.log_very_verbose(
                        f"Using explicit column mapping for {table_name_upper}: {len(columns)} columns"
                    )
                    return f" ({', '.join(columns)})"
        except Exception as e:
            self.log_very_verbose(f"Could not get column list for {table_name}: {e}")
        return ""

    def _load_single_table(
        self,
        cursor,
        connection,
        benchmark,
        table_name: str,
        file_path,
        stage_root: str,
        existing_tables: set[str],
        data_source: Any | None = None,
    ) -> tuple[int, float, float]:
        """Load a single table via COPY INTO. Returns (row_count, copy_time, optimize_time)."""
        table_name_upper = table_name.upper()

        if table_name.lower() not in existing_tables:
            self.logger.error(f"Table {table_name_upper} not found in schema {self.catalog}.{self.schema}")
            self.logger.error(f"Available tables: {sorted(existing_tables)}")
            raise RuntimeError(
                f"Table {table_name_upper} does not exist in {self.catalog}.{self.schema}. "
                f"Ensure schema creation completed successfully before loading data."
            )

        file_uri, filename, delimiter = self._resolve_file_uri_and_delimiter(
            file_path,
            stage_root,
            table_name=table_name,
            data_source=data_source,
            benchmark=benchmark,
        )
        column_list = self._get_column_list_for_table(benchmark, table_name)

        copy_sql = (
            f"COPY INTO {table_name_upper}{column_list} FROM '{file_uri}' "
            f"FILEFORMAT = CSV FORMAT_OPTIONS('delimiter'='{delimiter}', 'header'='false')"
        )

        if "*" in file_uri:
            self.log_verbose(f"Loading {table_name_upper} from wildcard pattern: {file_uri}")

        copy_start = mono_time()
        cursor.execute(copy_sql)
        copy_time = elapsed_seconds(copy_start)

        cursor.execute(f"SELECT COUNT(*) FROM {table_name_upper}")
        row_count = cursor.fetchone()[0]

        effective_tuning = self.get_effective_tuning_configuration()
        if effective_tuning is not None:
            self.apply_ctas_sort(table_name_upper, effective_tuning, connection)

        optimize_time = 0.0
        if self.enable_delta_optimization:
            optimize_start = mono_time()
            with contextlib.suppress(Exception):
                cursor.execute(f"OPTIMIZE {table_name_upper}")
            optimize_time = elapsed_seconds(optimize_start)

        return row_count, copy_time, optimize_time

    def validate_external_table_requirements(self) -> None:
        """Validate required staging configuration for external table mode."""
        has_explicit_staging = isinstance(self.staging_root, str) and self._is_cloud_uri(self.staging_root)
        has_uc_volume = bool(self.uc_catalog and self.uc_schema and self.uc_volume)
        if not has_explicit_staging and not has_uc_volume:
            raise ValueError(
                "Databricks external mode requires cloud staging. Configure --platform-option staging_root=<cloud-uri> "
                "(dbfs:/, s3://, gs://, or abfss://) or Unity Catalog volume options "
                "(uc_catalog, uc_schema, uc_volume)."
            )

    @staticmethod
    def _external_location_from_file_uri(file_uri: str) -> str:
        """Resolve LOCATION path for CREATE TABLE ... USING PARQUET.

        For .parquet files or wildcard patterns, returns the parent directory.
        For suffix-less URIs (directories of Parquet files), returns the URI as-is.
        Raises ValueError for non-Parquet file extensions.
        """
        normalized_uri = file_uri.strip().rstrip("/")
        if "*" in normalized_uri:
            return normalized_uri.rsplit("/", 1)[0]

        suffix = Path(normalized_uri).suffix.lower()
        if suffix == ".parquet":
            return normalized_uri.rsplit("/", 1)[0]

        if suffix:
            raise ValueError(
                f"Databricks external mode requires Parquet sources, got '{file_uri}'. "
                "Provide Parquet input files for --table-mode external."
            )

        return normalized_uri

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Register Databricks external tables via USING PARQUET LOCATION."""
        start_time = mono_time()
        table_stats: dict[str, int] = {}
        cursor = connection.cursor()

        try:
            from benchbox.platforms.base.data_loading import DataSource

            data_source = self._resolve_databricks_data_files(benchmark, data_dir)
            if not isinstance(data_source, DataSource):
                data_source = DataSource(source_type="legacy_test_mapping", tables=data_source)
            stage_root = self._resolve_stage_root(data_dir)
            data_source.tables = self._maybe_upload_to_uc_volume(data_source.tables, stage_root, data_dir, connection)

            cursor.execute(f"USE CATALOG {self.catalog}")
            cursor.execute(f"USE SCHEMA {self.schema}")
            cursor.execute(f"SHOW TABLES IN {self.catalog}.{self.schema}")
            existing_tables = {row[1].lower() for row in cursor.fetchall()}

            for table_name, file_path in data_source.tables.items():
                table_name_upper = table_name.upper()
                table_name_lower = table_name.lower()
                if table_name_lower not in existing_tables:
                    raise RuntimeError(
                        f"Table {table_name_upper} does not exist in {self.catalog}.{self.schema}. "
                        "Ensure schema creation completed before external registration."
                    )

                file_uri, _filename, _delimiter = self._resolve_file_uri_and_delimiter(file_path, stage_root)
                location = self._external_location_from_file_uri(file_uri)

                cursor.execute(f"DROP TABLE IF EXISTS {table_name_upper}")
                cursor.execute(f"CREATE TABLE {table_name_upper} USING PARQUET LOCATION '{location}'")
                cursor.execute(f"SELECT COUNT(*) FROM {table_name_upper}")
                result = cursor.fetchone()
                table_stats[table_name_upper] = int(result[0]) if result else 0

        finally:
            cursor.close()

        total_time = elapsed_seconds(start_time)
        return table_stats, total_time, None

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Databricks-specific configurations including cache control.

        Applies result cache control first, then any user-provided custom Spark configurations.
        """
        cursor = connection.cursor()

        try:
            # Apply result cache control - disable by default for accurate benchmarking
            if self.disable_result_cache:
                try:
                    cursor.execute("SET use_cached_result = false")
                    self.logger.debug("Disabled result cache (use_cached_result = false)")
                except Exception as e:
                    self.logger.warning(f"Failed to disable result cache: {e}")

            # Apply user-provided configurations if specified
            if hasattr(self, "spark_configs") and self.spark_configs:
                for config_key, config_value in self.spark_configs.items():
                    try:
                        cursor.execute(f"SET {config_key} = {config_value}")
                        self.logger.debug(f"Set {config_key} = {config_value}")
                    except Exception as e:
                        self.logger.warning(f"Failed to set {config_key}: {e}")
            else:
                self.logger.debug("No custom Spark configurations to apply")

        finally:
            cursor.close()

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
        """Execute query with detailed timing and profiling."""
        start_time = mono_time()
        self.log_verbose(f"Executing query {query_id}")
        self.log_very_verbose(f"Query SQL (first 200 chars): {query[:200]}{'...' if len(query) > 200 else ''}")

        cursor = connection.cursor()

        try:
            # Schema context is already set in create_connection() and persists for the session
            # No need to set USE <catalog>.<schema> before every query - it adds unnecessary overhead
            # (Each USE statement = 1 extra round-trip to Databricks)

            # Execute the query
            # Note: Query dialect translation is now handled automatically by the base adapter
            cursor.execute(query)
            result = cursor.fetchall()

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result) if result else 0

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

            # Include Databricks-specific fields
            result_dict["translated_query"] = None  # Translation handled by base adapter

            # Add resource usage for cost calculation (execution time for DBU estimation)
            result_dict["resource_usage"] = {
                "execution_time_seconds": execution_time,
            }

            return result_dict

        except Exception as e:
            execution_time = elapsed_seconds(start_time)

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

    def _fix_databricks_sql_syntax(self, sql: str) -> str:
        """Transform SQL syntax for Databricks compatibility.

        This method removes SQL syntax that is not supported by Databricks/Spark SQL,
        particularly NULLS FIRST/LAST clauses in PRIMARY KEY constraints.

        Args:
            sql: SQL statement(s) to fix

        Returns:
            Fixed SQL with Databricks-compatible syntax
        """
        import re

        original_sql = sql

        # Pattern 1: Remove NULLS LAST/FIRST from PRIMARY KEY constraints
        # Databricks doesn't support NULLS ordering in PRIMARY KEY definitions
        # Match: PRIMARY KEY (col1, col2 NULLS LAST)
        # Also match: PRIMARY KEY (col1 NULLS FIRST, col2)
        nulls_in_pk_pattern = r"\b(PRIMARY\s+KEY\s*\([^)]*?)\s+NULLS\s+(LAST|FIRST)\s*([^)]*?\))"

        def remove_nulls_from_pk(match):
            # Reconstruct without the NULLS clause
            before = match.group(1)  # PRIMARY KEY (col1, col2
            after = match.group(3)  # remaining part + closing paren
            return f"{before} {after}".strip()

        fixed_sql = re.sub(nulls_in_pk_pattern, remove_nulls_from_pk, sql, flags=re.IGNORECASE)

        # Pattern 2: Remove standalone NULLS clauses in column definitions within PRIMARY KEY
        # This catches cases like: PRIMARY KEY (col1 NULLS LAST, col2 NULLS FIRST)
        # Apply multiple times to catch all occurrences
        max_iterations = 10  # Safety limit
        for _ in range(max_iterations):
            prev = fixed_sql
            fixed_sql = re.sub(
                r"\b(PRIMARY\s+KEY\s*\([^)]*?)\s+NULLS\s+(LAST|FIRST)\b",
                r"\1",
                fixed_sql,
                flags=re.IGNORECASE,
            )
            if fixed_sql == prev:
                break  # No more replacements

        # Log if any changes were made
        if fixed_sql != original_sql:
            changes_made = original_sql != fixed_sql
            if changes_made:
                self.log_very_verbose("Fixed Databricks SQL syntax (removed NULLS FIRST/LAST from PRIMARY KEY)")
                self.log_very_verbose(f"Before: {original_sql[:200]}...")
                self.log_very_verbose(f"After:  {fixed_sql[:200]}...")

        return fixed_sql

    def _convert_to_delta_table(self, statement: str) -> str:
        """Convert CREATE TABLE statement to Delta Lake format."""
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # Ensure idempotency with OR REPLACE
        if "CREATE TABLE" in statement.upper() and "OR REPLACE" not in statement.upper():
            statement = statement.replace("CREATE TABLE", "CREATE OR REPLACE TABLE", 1)

        # Default to DELTA format when unspecified
        if "USING" not in statement.upper():
            # Find the closing parenthesis of column definitions
            paren_count = 0
            using_pos = len(statement)

            for i, char in enumerate(statement):
                if char == "(":
                    paren_count += 1
                elif char == ")":
                    paren_count -= 1
                    if paren_count == 0:
                        using_pos = i + 1
                        break

            # Insert USING DELTA clause
            statement = statement[:using_pos] + " USING DELTA" + statement[using_pos:]

        # Include Delta Lake optimization properties
        if "TBLPROPERTIES" not in statement.upper():
            statement += " TBLPROPERTIES ("
            properties = []

            if self.delta_auto_optimize:
                properties.append("'delta.autoOptimize.optimizeWrite' = 'true'")
                properties.append("'delta.autoOptimize.autoCompact' = 'true'")

            statement += ", ".join(properties) + ")"

        return statement

    def _get_platform_metadata(self, connection: Any) -> dict[str, Any]:
        """Get Databricks-specific metadata and system information."""
        clustering_strategy = self._resolve_databricks_clustering_strategy()
        effective_config = self.get_effective_tuning_configuration()
        platform_opts = getattr(effective_config, "platform_optimizations", None)
        metadata = {
            "platform": self.platform_name,
            "server_hostname": self.server_hostname,
            "catalog": self.catalog,
            "schema": self.schema,
            "result_cache_enabled": not self.disable_result_cache,
            "databricks_clustering_strategy": clustering_strategy,
            "liquid_clustering_enabled": bool(getattr(platform_opts, "liquid_clustering_enabled", False)),
            "liquid_clustering_columns_config": list(getattr(platform_opts, "liquid_clustering_columns", [])),
            "liquid_clustering_operations": list(self._liquid_clustering_operations),
            "z_order_operations": list(self._z_order_operations),
        }

        cursor = connection.cursor()

        try:
            # Get Spark version
            cursor.execute("SELECT version()")
            result = cursor.fetchone()
            metadata["spark_version"] = result[0] if result else "unknown"

            # Get current catalog and schema
            cursor.execute("SELECT current_catalog(), current_schema()")
            result = cursor.fetchone()
            if result:
                metadata["current_catalog"] = result[0]
                metadata["current_schema"] = result[1]

            # Get cluster information
            cursor.execute("SHOW FUNCTIONS LIKE 'current_*'")
            functions = cursor.fetchall()
            metadata["available_functions"] = [f[0] for f in functions]

            # Get Spark configurations
            cursor.execute("SET")
            configs = cursor.fetchall()
            spark_configs = {k: v for k, v in configs if k.startswith("spark.")}
            metadata["spark_configurations"] = spark_configs

        except Exception as e:
            metadata["metadata_error"] = str(e)
        finally:
            cursor.close()

        return metadata

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE TABLE for better query optimization."""
        cursor = connection.cursor()
        try:
            cursor.execute(f"ANALYZE TABLE {table_name.upper()} COMPUTE STATISTICS")
            self.logger.info(f"Analyzed table {table_name.upper()}")
        except Exception as e:
            self.logger.warning(f"Failed to analyze table {table_name}: {e}")
        finally:
            cursor.close()

    def optimize_table(self, connection: Any, table_name: str) -> None:
        """Optimize Delta Lake table."""
        if not self.enable_delta_optimization:
            return

        cursor = connection.cursor()
        try:
            cursor.execute(f"OPTIMIZE {table_name.upper()}")
            self.logger.info(f"Optimized Delta table {table_name.upper()}")
        except Exception as e:
            self.logger.warning(f"Failed to optimize table {table_name}: {e}")
        finally:
            cursor.close()

    def vacuum_table(self, connection: Any, table_name: str, hours: int = 168) -> None:
        """Vacuum Delta Lake table to remove old files."""
        if not self.enable_delta_optimization:
            return

        cursor = connection.cursor()
        try:
            cursor.execute(f"VACUUM {table_name.upper()} RETAIN {hours} HOURS")
            self.logger.info(f"Vacuumed Delta table {table_name.upper()}")
        except Exception as e:
            self.logger.warning(f"Failed to vacuum table {table_name}: {e}")
        finally:
            cursor.close()

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables in the Databricks schema."""
        try:
            cursor = connection.cursor()
            # Use Databricks-specific query to get tables in current schema
            cursor.execute(f"SHOW TABLES IN {self.catalog}.{self.schema}")
            result = cursor.fetchall()
            cursor.close()

            # Result format is (database, tableName, isTemporary)
            return [row[1] for row in result if not row[2]]  # Exclude temporary tables
        except Exception as e:
            self.logger.debug(f"Failed to get existing tables: {e}")
            return []

    def close_connection(self, connection: Any) -> None:
        """Close Databricks connection."""
        try:
            if connection and hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            self.logger.warning(f"Error closing connection: {e}")

    _supported_tuning_type_names = ("PARTITIONING", "CLUSTERING", "DISTRIBUTION")

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate Databricks-specific tuning clauses for CREATE TABLE statements.

        Databricks supports:
        - USING DELTA (Delta Lake format)
        - PARTITIONED BY (column1, column2, ...)
        - CLUSTER BY (column1, column2, ...) for Delta Lake 2.0+
        - Z-ORDER optimization

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

            # Always use Delta Lake format for better performance
            clauses.append("USING DELTA")

            # Handle partitioning
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                # Sort by order and create partition clause
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]

                partition_clause = f"PARTITIONED BY ({', '.join(column_names)})"
                clauses.append(partition_clause)

            # Handle clustering (Delta Lake 2.0+)
            cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
            if cluster_columns:
                # Sort by order and create cluster clause
                sorted_cols = sorted(cluster_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]

                cluster_clause = f"CLUSTER BY ({', '.join(column_names)})"
                clauses.append(cluster_clause)

            # Distribution handled through Z-ORDER optimization (applied post-creation)

        except ImportError:
            # If tuning interface not available, at least use Delta format
            clauses.append("USING DELTA")

        return " ".join(clauses)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to a Databricks Delta Lake table.

        Databricks tuning approach:
        - PARTITIONING: Handled via PARTITIONED BY in CREATE TABLE
        - CLUSTERING: Handled via CLUSTER BY in CREATE TABLE or ALTER TABLE
        - DISTRIBUTION: Achieved through Z-ORDER clustering and OPTIMIZE
        - Delta Lake optimization and maintenance

        Args:
            table_tuning: The tuning configuration to apply
            connection: Databricks connection

        Raises:
            ValueError: If the tuning configuration is invalid for Databricks
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name = table_tuning.table_name.upper()
        self.logger.info(f"Applying Databricks tunings for table: {table_name}")

        cursor = connection.cursor()
        try:
            # Import here to avoid circular imports
            from benchbox.core.tuning.interface import TuningType

            # Check if table exists and is Delta format
            cursor.execute(f"DESCRIBE EXTENDED {table_name}")
            table_info = cursor.fetchall()

            is_delta_table = any("DELTA" in str(row).upper() for row in table_info)
            if not is_delta_table:
                self.logger.warning(
                    f"Table {table_name} is not a Delta table - some optimizations may not be available"
                )

            effective_config = self.get_effective_tuning_configuration()
            platform_opts = getattr(effective_config, "platform_optimizations", None)
            clustering_strategy = self._resolve_databricks_clustering_strategy()
            liquid_enabled = bool(getattr(platform_opts, "liquid_clustering_enabled", False))
            liquid_columns = list(getattr(platform_opts, "liquid_clustering_columns", []))

            cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
            distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
            sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)

            zorder_columns = self._build_zorder_columns(cluster_columns, distribution_columns)
            use_liquid = clustering_strategy == "liquid_clustering" or liquid_enabled
            self._apply_clustering_strategy(
                cursor,
                table_name,
                is_delta_table,
                use_liquid,
                liquid_columns,
                zorder_columns,
                sort_columns,
            )
            self._log_partitioning_and_sorting(
                table_name,
                partition_columns,
                sort_columns,
                use_liquid,
            )
            if is_delta_table and self.enable_delta_optimization:
                self._apply_delta_optimize(cursor, table_name)

        except ImportError:
            self.logger.warning("Tuning interface not available - skipping tuning application")
        except Exception as e:
            raise ValueError(f"Failed to apply tunings to Databricks table {table_name}: {e}") from e
        finally:
            cursor.close()

    @staticmethod
    def _build_zorder_columns(cluster_columns, distribution_columns) -> list[str]:
        """Merge clustering + distribution columns (in order) for Z-ORDER / Liquid Clustering."""
        cols: list[str] = []
        if cluster_columns:
            cols.extend(col.name for col in sorted(cluster_columns, key=lambda c: c.order))
        if distribution_columns:
            for col in sorted(distribution_columns, key=lambda c: c.order):
                if col.name not in cols:
                    cols.append(col.name)
        return cols

    def _apply_clustering_strategy(
        self,
        cursor: Any,
        table_name: str,
        is_delta_table: bool,
        use_liquid: bool,
        liquid_columns: list[str],
        zorder_columns: list[str],
        sort_columns,
    ) -> None:
        """Apply either Liquid Clustering or Z-ORDER to the table."""
        if use_liquid:
            self._apply_liquid_clustering(
                cursor, table_name, is_delta_table, liquid_columns, zorder_columns, sort_columns
            )
        elif zorder_columns and is_delta_table:
            self._apply_zorder_optimization(cursor, table_name, zorder_columns)

    def _apply_liquid_clustering(
        self,
        cursor: Any,
        table_name: str,
        is_delta_table: bool,
        liquid_columns: list[str],
        zorder_columns: list[str],
        sort_columns,
    ) -> None:
        if not liquid_columns:
            liquid_columns = list(zorder_columns)
        if not liquid_columns and sort_columns:
            liquid_columns = [col.name for col in sorted(sort_columns, key=lambda c: c.order)]
        if liquid_columns and is_delta_table:
            clause = f"ALTER TABLE {table_name} CLUSTER BY ({', '.join(liquid_columns)})"
            try:
                cursor.execute(clause)
                self._liquid_clustering_operations.append(
                    {"table": table_name, "columns": list(liquid_columns), "statement": clause}
                )
                self.logger.info(f"Applied Liquid Clustering to {table_name}: {', '.join(liquid_columns)}")
            except Exception as e:
                self.logger.warning(f"Failed to apply Liquid Clustering to {table_name}: {e}")
        elif is_delta_table:
            self.logger.info(f"Liquid Clustering selected for {table_name} but no clustering columns were available")

    def _apply_zorder_optimization(self, cursor: Any, table_name: str, zorder_columns: list[str]) -> None:
        clause = f"OPTIMIZE {table_name} ZORDER BY ({', '.join(zorder_columns)})"
        try:
            cursor.execute(clause)
            self._z_order_operations.append({"table": table_name, "columns": list(zorder_columns), "statement": clause})
            self.logger.info(f"Applied Z-ORDER optimization to {table_name}: {', '.join(zorder_columns)}")
        except Exception as e:
            self.logger.warning(f"Failed to apply Z-ORDER optimization to {table_name}: {e}")

    def _log_partitioning_and_sorting(self, table_name: str, partition_columns, sort_columns, use_liquid: bool) -> None:
        if partition_columns:
            names = [col.name for col in sorted(partition_columns, key=lambda c: c.order)]
            self.logger.info(
                f"Partitioning strategy for {table_name}: {', '.join(names)} (defined at CREATE TABLE time)"
            )
        if sort_columns:
            names = [col.name for col in sorted(sort_columns, key=lambda c: c.order)]
            mechanism = "Liquid Clustering" if use_liquid else "Z-ORDER clustering"
            self.logger.info(
                f"Sorting in Databricks achieved via {mechanism} for table {table_name}: {', '.join(names)}"
            )

    def _apply_delta_optimize(self, cursor: Any, table_name: str) -> None:
        try:
            cursor.execute(f"OPTIMIZE {table_name}")
            self.logger.info(f"Optimized Delta table {table_name}")
            cursor.execute(f"ANALYZE TABLE {table_name} COMPUTE STATISTICS")
            self.logger.info(f"Updated statistics for {table_name}")
        except Exception as e:
            self.logger.warning(f"Failed to optimize Delta table {table_name}: {e}")

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to Databricks."""
        from benchbox.platforms.base.tuning_config import apply_standard_unified_tuning

        apply_standard_unified_tuning(self, unified_config, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply Databricks-specific platform optimizations.

        Databricks optimizations include:
        - Spark configuration tuning (adaptive query execution, join strategies)
        - Delta Lake optimization settings (auto-optimize, auto-compact)
        - Cluster autoscaling and resource allocation
        - Unity Catalog performance settings

        Args:
            platform_config: Platform optimization configuration
            connection: Databricks connection
        """
        if not platform_config:
            return

        # Databricks optimizations are typically applied at Spark session level
        # Store optimizations for use during query execution and Delta Lake operations
        self.logger.info("Databricks platform optimizations stored for Spark session and Delta Lake management")

    apply_constraint_configuration = make_informational_constraint_applier(
        "Primary key constraints enabled for Databricks (informational only, applied during table creation)",
        "Foreign key constraints enabled for Databricks (informational only, applied during table creation)",
    )

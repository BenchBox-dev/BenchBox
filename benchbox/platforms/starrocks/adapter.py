"""StarRocks OLAP platform adapter.

Provides a BenchBox platform adapter for StarRocks, an open-source
columnar analytics engine supporting sub-second OLAP queries on
large-scale datasets. Connects via MySQL protocol using PyMySQL.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.adapter import DriverIsolationCapability, PlatformAdapter
from benchbox.platforms.base.data_loading import validate_sql_identifier
from benchbox.utils.dependencies import check_platform_dependencies

from .metadata import StarRocksMetadataMixin
from .setup import StarRocksSetupMixin
from .tuning import StarRocksTuningMixin
from .workload import StarRocksWorkloadMixin

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import TuningColumn


class StarRocksAdapter(
    StarRocksWorkloadMixin,
    StarRocksSetupMixin,
    StarRocksMetadataMixin,
    StarRocksTuningMixin,
    PlatformAdapter,
):
    """StarRocks OLAP platform adapter.

    Supports:
    - Connection via MySQL protocol (port 9030)
    - TPC-H and TPC-DS benchmarks
    - Columnar storage with Duplicate Key model
    - Distributed hash partitioning
    - Stream Load for high-throughput data ingestion
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> StarRocksAdapter:
        """Create StarRocks adapter from unified configuration."""
        adapter_config: dict[str, Any] = {}

        adapter_config["host"] = config.get("host", "localhost")
        adapter_config["port"] = config.get("port", 9030)
        adapter_config["username"] = config.get("username", "root")
        adapter_config["password"] = config.get("password", "")
        adapter_config["http_port"] = config.get("http_port", 8040)

        if config.get("database"):
            adapter_config["database"] = config["database"]
        elif config.get("benchmark") and config.get("scale_factor") is not None:
            from benchbox.utils.scale_factor import format_benchmark_name

            benchmark_name = format_benchmark_name(config["benchmark"], config["scale_factor"])
            adapter_config["database"] = f"benchbox_{benchmark_name}".lower().replace("-", "_")

        for key in [
            "tuning_config",
            "verbose_enabled",
            "very_verbose",
            "disable_result_cache",
            "strict_validation",
            "max_execution_time",
            "deployment_mode",
            "verify_ssl",
            "ca_cert_path",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def __init__(self, **config: Any) -> None:
        """Initialize StarRocks adapter.

        Args:
            **config: Configuration parameters including:
                - host: StarRocks FE hostname (default: localhost)
                - port: MySQL protocol port (default: 9030)
                - username: Database username (default: root)
                - password: Database password (default: "")
                - database: Target database name
                - http_port: BE HTTP port for Stream Load (default: 8040)
                - deployment_mode: Deployment mode (default: self-hosted)
        """
        # Check dependencies before proceeding
        deps_ok, missing = check_platform_dependencies("starrocks")
        if not deps_ok:
            raise ImportError(
                f"Missing dependencies for starrocks platform: {', '.join(missing)}\n"
                "Install with: uv add pymysql\n"
                "Or: uv add benchbox --extra starrocks"
            )

        super().__init__(**config)

        # Set dialect for SQL translation
        self._dialect = self.get_target_dialect()

        # Setup connection config from arguments and env vars
        self._setup_connection_config(config)

    @property
    def dialect(self) -> str:
        """Return the SQL dialect for this adapter."""
        return self._dialect or "starrocks"

    def get_connection(self) -> Any:
        """Get a StarRocks connection."""
        return self.create_connection()

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """StarRocks sorting is defined at CREATE TABLE time via sort keys."""
        return None

    def _validate_data_integrity(
        self,
        benchmark: Any,
        connection: Any,
        table_stats: dict[str, int],
    ) -> tuple[str, dict[str, Any]]:
        """Validate data integrity and table accessibility for StarRocks."""
        validation_details: dict[str, Any] = {}

        try:
            accessible_tables = []
            inaccessible_tables = []

            cursor = connection.cursor()
            try:
                for table_name in table_stats:
                    try:
                        validate_sql_identifier(table_name, "table name")
                    except ValueError:
                        self.logger.warning(f"Skipping invalid table name: {table_name!r}")
                        inaccessible_tables.append(table_name)
                        continue
                    try:
                        cursor.execute(f"SELECT 1 FROM `{table_name}` LIMIT 1")
                        cursor.fetchall()
                        accessible_tables.append(table_name)
                    except Exception as e:
                        self.logger.debug(f"Table {table_name} inaccessible: {e}")
                        inaccessible_tables.append(table_name)
            finally:
                cursor.close()

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


__all__ = ["StarRocksAdapter"]

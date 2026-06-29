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

import re
from typing import Any

from benchbox.platforms.base.ddl_helpers import strip_primary_keys, strip_with_properties

from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from .base import DriverIsolationCapability
from .presto_trino_adapter_base import PrestoTrinoAdapterBase

try:
    import prestodb
    from prestodb.auth import BasicAuthentication as PrestoBasicAuthentication
except ImportError:
    prestodb = None
    PrestoBasicAuthentication = None

PRESTO_DIALECT = "presto"


class PrestoAdapter(PrestoTrinoAdapterBase):
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

    plan_capture_phase_eligible = True

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    supports_external_tables = True
    platform_key = "presto"
    platform_log_name = "Presto"
    local_start_hint = "Start your local coordinator before rerunning BenchBox,"
    unavailable_catalog_marker = "does not exist on the Presto server"
    default_username = "presto"
    table_format_choices = ("memory", "hive")
    target_dialect = PRESTO_DIALECT
    uses_client_source = True
    from_config_optional_fields = (*PrestoTrinoAdapterBase.from_config_optional_fields, "source")
    memory_error_markers = ("MEMORY_LIMIT_EXCEEDED", "exceeds max memory")
    info_platform_name = "PrestoDB"
    include_dialect_in_info = True
    include_session_properties_in_info = True
    include_client_source_in_info = True
    use_version_fallback = True
    default_display_name = "Presto"
    default_driver_package = "presto-python-client"
    platform_config_fields = PrestoTrinoAdapterBase.common_platform_config_fields
    supported_tuning_type_names = ("PARTITIONING",)
    qualify_analyze_table = True
    driver_module_attr = "prestodb"
    olap_session_settings = (
        "SET SESSION optimize_hash_generation = true",
        "SET SESSION join_reordering_strategy = 'AUTOMATIC'",
        "SET SESSION join_distribution_type = 'AUTOMATIC'",
    )

    def __init__(self, **config):
        super().__init__(**config)

        if not prestodb:
            available, missing = check_platform_dependencies("presto")
            if not available:
                error_msg = get_dependency_error_message("presto", missing)
                raise ImportError(error_msg)

        self._init_connection_config(config)

    @property
    def platform_name(self) -> str:
        return "Presto"

    def _connect_with_params(self, params: dict[str, Any]) -> Any:
        return prestodb.dbapi.connect(**params)

    def _catalog_listing_params(self) -> dict[str, Any]:
        params = self._bootstrap_connection_params()
        params["catalog"] = "system"
        params["schema"] = "runtime"
        return params

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

    def _optimize_table_definition(self, statement: str) -> str:
        """Optimize table definition for Presto.

        Presto table creation syntax depends on the connector/catalog being used.
        For memory catalog, minimal syntax is needed.
        For Hive, we can add format specifications.
        """
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # Presto rejects PRIMARY KEY constraints in benchmark CREATE TABLE DDL.
        # BenchBox workloads load immutable benchmark data, so the constraint is
        # metadata only and can be stripped for all Presto catalogs.
        statement = strip_primary_keys(statement)

        # For memory catalog, remove any Presto-incompatible syntax.
        # Memory catalog doesn't support WITH properties or NOT NULL constraints.

        if self.table_format == "memory" or self.catalog == "memory":
            # Memory catalog: simple CREATE TABLE without WITH clause or NOT NULL
            statement = strip_with_properties(statement)
            statement = re.sub(r"\s+NOT\s+NULL", "", statement, flags=re.IGNORECASE)

        elif self.table_format == "hive":
            # Add table format specification if not present
            if "WITH" not in statement.upper():
                statement += " WITH (format = 'PARQUET')"

        return statement

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


try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("presto", PrestoAdapter.build_platform_config)
except ImportError:
    # Platform hooks may not be available in all contexts
    pass

_build_presto_config = PrestoAdapter.build_platform_config

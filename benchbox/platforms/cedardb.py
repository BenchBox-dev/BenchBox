"""CedarDB platform adapter for BenchBox benchmarking.

Extends PostgreSQL adapter with CedarDB-specific functionality:
- CedarDB version and platform identification
- OLAP-tuned session defaults
- Standard PostgreSQL COPY for bulk loading (fully supported by CedarDB)

CedarDB (formerly Umbra) is a high-performance RDBMS supporting both OLAP and
OLTP workloads via the PostgreSQL wire protocol. It is a standalone database,
not a PostgreSQL extension, but is fully compatible with standard PostgreSQL
drivers (psycopg2/psycopg3) and tooling (psql, DBeaver, DataGrip).

Deployment modes:
- self-hosted: Self-hosted CedarDB server (default)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from .base.config_utils import (
    POSTGRES_CONNECTION_PLATFORM_FIELDS,
    POSTGRES_FAMILY_BASE_OPTIONS,
    make_platform_config_builder,
)
from .postgresql import (
    POSTGRES_DIALECT,
    PostgreSQLAdapter,
    _add_postgres_compatible_arguments,
    _build_postgres_connection_kwargs,
)

# CedarDB default port - same as PostgreSQL; configurable via platform-option
CEDARDB_DEFAULT_PORT = 5432


class CedarDBAdapter(PostgreSQLAdapter):
    """CedarDB platform adapter for high-performance OLAP/OLTP benchmarking.

    Extends PostgreSQLAdapter for CedarDB (formerly Umbra), a standalone RDBMS
    that uses the PostgreSQL wire protocol. CedarDB is not a PostgreSQL extension;
    it is its own database engine with full PostgreSQL SQL dialect compatibility.

    Standard PostgreSQL bulk loading (COPY) is used for data ingestion.
    Session-level tuning applies OLAP-optimized defaults at connection time.

    Requires CedarDB server with PostgreSQL wire protocol enabled (default port 5432).
    """

    plan_capture_phase_eligible = True

    @property
    def platform_name(self) -> str:
        return "CedarDB"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for CedarDB (PostgreSQL-compatible)."""
        return POSTGRES_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add CedarDB-specific CLI arguments."""
        if not hasattr(parser, "add_argument"):
            return
        try:
            _add_postgres_compatible_arguments(
                parser,
                prefix="cedardb",
                platform_label="CedarDB",
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("Failed to register CedarDB CLI arguments: %s", e)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> CedarDBAdapter:
        """Create CedarDB adapter from unified configuration."""
        adapter_config = _build_postgres_connection_kwargs(config, default_port=CEDARDB_DEFAULT_PORT)
        return cls(**adapter_config)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get CedarDB platform information."""
        platform_info = super().get_platform_info(connection)

        # Override platform type and name
        platform_info["platform_type"] = "cedardb"
        platform_info["platform_name"] = "CedarDB"

        if connection:
            try:
                cursor = connection.cursor()

                # Query the server version string - CedarDB returns its own version
                cursor.execute("SELECT version()")
                result = cursor.fetchone()
                if result:
                    platform_info["cedardb_version_string"] = result[0]

                cursor.close()
            except Exception as e:
                self.logger.debug(f"Error getting CedarDB version info: {e}")

        return platform_info

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply benchmark configuration to CedarDB, skipping unsupported GUCs."""
        import psycopg

        cursor = connection.cursor()
        guc_statements = []
        if benchmark_type == "olap":
            guc_statements = [
                "SET enable_seqscan = on",
                "SET enable_hashjoin = on",
                "SET enable_mergejoin = on",
                "SET random_page_cost = 1.1",
                "SET cpu_tuple_cost = 0.01",
            ]
        elif benchmark_type == "oltp":
            guc_statements = [
                "SET synchronous_commit = on",
                "SET random_page_cost = 4.0",
            ]

        for stmt in guc_statements:
            try:
                cursor.execute(stmt)
                connection.commit()
            except (psycopg.Error, Exception):
                connection.rollback()
                self.logger.debug(f"Skipping unsupported GUC in CedarDB: {stmt}")
        cursor.close()

    # CedarDB uses field-terminator semantics: each field ends with the delimiter,
    # so 4 fields = 4 pipe characters. Keep the trailing pipe from TPC data files.
    _strip_tpc_trailing_pipe: bool = False

    def _copy_options_for_tpc(self, delimiter: str) -> str:
        """CedarDB uses field-terminator semantics - keep trailing pipe, add NULL ''."""
        return f"FORMAT csv, DELIMITER '{delimiter}', NULL ''"

    def drop_database(
        self,
        schema: str | None = None,
        catalog: str | None = None,
        database: str | None = None,
        **_kwargs,
    ) -> None:
        """Drop a database from CedarDB server.

        CedarDB does not support pg_terminate_backend or DROP DATABASE with
        contained objects, so schemas are dropped individually first.
        """
        import psycopg

        db_name = database or self.database
        if not self._validate_identifier(db_name):
            raise ValueError(f"Invalid database identifier: {db_name}")

        try:
            # First check if database exists; skip if not
            admin_params = self._get_connection_params(database=self.admin_database)
            admin_conn = psycopg.connect(**admin_params)
            admin_conn.autocommit = True
            admin_cursor = admin_conn.cursor()
            admin_cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if not admin_cursor.fetchone():
                admin_cursor.close()
                admin_conn.close()
                return
            admin_cursor.close()
            admin_conn.close()

            # CedarDB does not support DROP SCHEMA/DATABASE CASCADE - objects must be
            # removed individually. Connect to the target database, drop each table, then
            # each schema, before dropping the database itself.
            db_params = self._get_connection_params(database=db_name)
            db_conn = psycopg.connect(**db_params)
            db_conn.autocommit = True
            db_cursor = db_conn.cursor()

            # Get all user-owned schemas (exclude system and temp schemas)
            db_cursor.execute(
                """
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                  AND schema_name NOT LIKE 'pg_temp%'
                  AND schema_name NOT LIKE 'pg_toast%'
                """
            )
            schemas = [row[0] for row in db_cursor.fetchall()]

            for s in schemas:
                # Drop all tables in this schema individually
                db_cursor.execute(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    """,
                    (s,),
                )
                tables = [row[0] for row in db_cursor.fetchall()]
                for t in tables:
                    self.log_notice(f'Dropping table if it exists: "{s}"."{t}"')
                    db_cursor.execute(f'DROP TABLE IF EXISTS "{s}"."{t}"')

                # Now the schema should be empty
                db_cursor.execute(f'DROP SCHEMA IF EXISTS "{s}"')
                self.logger.info(f'Dropped schema (if existed): "{s}"')

            db_cursor.close()
            db_conn.close()

            # Now drop the empty database
            admin_conn2 = psycopg.connect(**admin_params)
            admin_conn2.autocommit = True
            admin_cursor2 = admin_conn2.cursor()
            admin_cursor2.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            admin_cursor2.close()
            admin_conn2.close()
            self.logger.info(f"Dropped database: {db_name}")
        except Exception as e:
            self.logger.warning(f"Failed to drop database {db_name}: {e}")
            raise

    _supported_tuning_type_names = ("PRIMARY_KEYS", "FOREIGN_KEYS")


_build_cedardb_config = make_platform_config_builder(
    "cedardb",
    __name__,
    "CedarDB",
    "psycopg",
    POSTGRES_CONNECTION_PLATFORM_FIELDS,
    base_options={"schema": "public"},
    field_defaults={**POSTGRES_FAMILY_BASE_OPTIONS, "port": CEDARDB_DEFAULT_PORT},
    consume_explicit_options=True,
)

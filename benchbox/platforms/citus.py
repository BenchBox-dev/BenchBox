"""Citus platform adapter for BenchBox benchmarking.

Extends PostgreSQL adapter with Citus-specific functionality:
- citus extension verification (distributed PostgreSQL tables)
- Opt-in table distribution via create_distributed_table()

Citus is a PostgreSQL extension that transparently distributes tables
across a coordinator and worker nodes. Without distribution, benchmark
tables stay coordinator-local and the run measures single-node Postgres;
pass --platform-option distribution_column=<col> to distribute every
benchmark table on that column after schema creation. Per-table control
is future work.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .base.config_utils import (
    POSTGRES_FAMILY_BASE_OPTIONS,
    POSTGRES_FAMILY_PLATFORM_FIELDS,
    make_platform_config_builder,
)
from .postgresql import (
    POSTGRES_DIALECT,
    PostgreSQLAdapter,
    _build_postgres_connection_kwargs,
    ensure_postgres_extension,
)

logger = logging.getLogger(__name__)

try:
    import psycopg
except ImportError:
    psycopg = None

CITUS_EXTENSION = "citus"


class CitusAdapter(PostgreSQLAdapter):
    """Citus platform adapter with distributed-table support.

    Extends PostgreSQLAdapter with Citus-specific features:
    - citus extension presence check with create-or-install guidance
    - Opt-in distribution of benchmark tables via create_distributed_table
    - Version reporting in platform info for result provenance

    Requires PostgreSQL 14+ with the citus extension installed on the
    coordinator (and workers for real distribution).
    """

    plan_capture_phase_eligible = True

    @property
    def platform_name(self) -> str:
        return "citus"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Citus (PostgreSQL-compatible)."""
        return POSTGRES_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Citus-specific CLI arguments."""
        if not hasattr(parser, "add_argument"):
            return
        try:
            # Inherit PostgreSQL connection arguments
            parser.add_argument(
                "--citus-host",
                dest="host",
                default="localhost",
                help="Citus coordinator hostname (with citus extension installed)",
            )
            parser.add_argument(
                "--citus-port",
                dest="port",
                type=int,
                default=5432,
                help="Citus coordinator port",
            )
            parser.add_argument(
                "--citus-database",
                dest="database",
                help="PostgreSQL database name (auto-generated if not specified)",
            )
            parser.add_argument(
                "--citus-username",
                dest="username",
                default="postgres",
                help="PostgreSQL username",
            )
            parser.add_argument(
                "--citus-password",
                dest="password",
                help="PostgreSQL password",
            )
            parser.add_argument(
                "--citus-schema",
                dest="schema",
                default="public",
                help="PostgreSQL schema name",
            )
            # Citus-specific options
            parser.add_argument(
                "--citus-distribution-column",
                dest="distribution_column",
                default=None,
                help="Distribute every benchmark table on this column "
                "(e.g. l_orderkey for TPC-H). Unset keeps coordinator-local tables.",
            )
        except Exception:
            pass

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> CitusAdapter:
        """Create Citus adapter from unified configuration."""
        adapter_config = _build_postgres_connection_kwargs(config)
        adapter_config["distribution_column"] = config.get("distribution_column")
        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)
        self.distribution_column: str | None = config.get("distribution_column")

    def create_connection(self, **connection_config) -> Any:
        """Create PostgreSQL connection and verify the citus extension."""
        conn = super().create_connection(**connection_config)
        ensure_postgres_extension(
            conn, self.logger, CITUS_EXTENSION, "https://github.com/citusdata/citus", cascade=True
        )
        return conn

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema, then distribute tables when a column is configured."""
        elapsed = super().create_schema(benchmark, connection)
        if self.distribution_column:
            self._distribute_benchmark_tables(benchmark, connection)
        return elapsed

    def _benchmark_table_names(self, benchmark: Any) -> list[str]:
        """Return benchmark table names in dependency order when available."""
        get_tables = getattr(benchmark, "_get_active_tables", None)
        if callable(get_tables):
            try:
                names = get_tables()
                if names:
                    return [str(name) for name in names]
            except Exception:
                pass
        schema_getter = getattr(benchmark, "get_schema", None)
        if callable(schema_getter):
            try:
                schema = schema_getter()
                if isinstance(schema, dict):
                    return list(schema.keys())
            except Exception:
                pass
        tables = getattr(benchmark, "tables", None)
        if isinstance(tables, dict):
            return list(tables.keys())
        return []

    def _distribute_benchmark_tables(self, benchmark: Any, connection: Any) -> None:
        """Distribute every benchmark table on the configured column.

        Runs after the inherited schema creation so COPY loading fans out to
        workers. Tables lacking the column are left coordinator-local with a
        warning rather than failing the run: dimension tables rarely carry
        the fact-table distribution key.
        """
        assert self.distribution_column is not None
        column = self.distribution_column
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", column):
            raise ValueError(f"Invalid Citus distribution column {column!r}: must be a plain SQL identifier.")
        cursor = connection.cursor()
        try:
            for table_name in self._benchmark_table_names(benchmark):
                quoted_table = '"' + table_name.replace('"', '""') + '"'
                try:
                    cursor.execute(f"SELECT create_distributed_table('{quoted_table}', '{column}')")
                    self.logger.info(f"Distributed Citus table {table_name} on column {column}")
                except Exception as e:
                    connection.rollback()
                    self.logger.warning(
                        f"Table {table_name} left coordinator-local (create_distributed_table on {column} failed: {e})"
                    )
                    continue
            connection.commit()
        finally:
            cursor.close()

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Citus platform information."""
        platform_info = super().get_platform_info(connection)

        # Override platform type and name
        platform_info["platform_type"] = "citus"
        platform_info["platform_name"] = "citus"

        # Add Citus-specific configuration
        platform_info["configuration"]["distribution_column"] = self.distribution_column

        if connection:
            try:
                cursor = connection.cursor()

                # Get citus version
                cursor.execute(f"SELECT extversion FROM pg_extension WHERE extname = '{CITUS_EXTENSION}'")
                result = cursor.fetchone()
                if result:
                    platform_info["citus_version"] = result[0]

                cursor.close()
            except Exception as e:
                self.logger.debug(f"Error getting citus info: {e}")

        return platform_info

    _supported_tuning_type_names = ("PARTITIONING", "CLUSTERING", "PRIMARY_KEYS", "FOREIGN_KEYS")


_build_citus_config = make_platform_config_builder(
    "citus",
    __name__,
    "citus",
    "psycopg",
    POSTGRES_FAMILY_PLATFORM_FIELDS + ("distribution_column",),
    base_options={
        **POSTGRES_FAMILY_BASE_OPTIONS,
    },
)

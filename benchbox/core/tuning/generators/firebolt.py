"""Firebolt DDL Generator.

Generates CREATE TABLE statements with Firebolt-specific tuning clauses.

Firebolt uses:
- PRIMARY INDEX: Controls data distribution across nodes (critical for performance)
- PARTITION BY: Time or value-based partitioning for data organization

Example:
    >>> from benchbox.core.tuning.generators.firebolt import FireboltDDLGenerator
    >>> generator = FireboltDDLGenerator()
    >>> clauses = generator.generate_tuning_clauses(table_tuning)
    >>> emit(clauses.distribute_by)  # "PRIMARY INDEX (l_orderkey, l_linenumber)"
    >>> emit(clauses.partition_by)   # "l_shipdate"

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchbox.core.tuning.ddl_generator import (
    BaseDDLGenerator,
    ColumnDefinition,
    ColumnNullability,
    TuningClauses,
)
from benchbox.core.tuning.type_mapping import map_sql_type_with_fallback

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)

FIREBOLT_TYPE_MAPPING: dict[str, str] = {
    # Integer types
    "INTEGER": "INT",
    "BIGINT": "LONG",
    "SMALLINT": "INT",  # Firebolt doesn't have SMALLINT
    "TINYINT": "INT",  # Firebolt doesn't have TINYINT
    # Floating point
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "REAL": "FLOAT",
    "DOUBLE PRECISION": "DOUBLE",
    # Decimal
    "DECIMAL": "DECIMAL(38, 9)",
    "NUMERIC": "DECIMAL(38, 9)",
    # String types
    "VARCHAR": "TEXT",
    "CHAR": "TEXT",
    "TEXT": "TEXT",
    "STRING": "TEXT",
    # Date/time
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP",
    "DATETIME": "TIMESTAMP",
    "TIME": "TEXT",  # Firebolt has limited TIME support
    # Boolean
    "BOOLEAN": "BOOLEAN",
    "BOOL": "BOOLEAN",
}


class FireboltDDLGenerator(BaseDDLGenerator):
    """DDL generator for Firebolt physical tuning.

    Generates Firebolt table DDL with:
    - PRIMARY INDEX: Column(s) for data distribution (from DISTRIBUTION tuning)
    - PARTITION BY: Time/value-based partitioning (from PARTITIONING tuning)

    Firebolt Tuning Mapping:
    - DISTRIBUTION → PRIMARY INDEX (most important for performance)
    - PARTITIONING → PARTITION BY
    - SORTING → Logged only (Firebolt sorts within segments automatically)
    - CLUSTERING → Logged only (handled by PRIMARY INDEX)

    Example DDL:
        CREATE TABLE lineitem (
            l_orderkey LONG,
            l_shipdate DATE,
            ...
        )
        PRIMARY INDEX (l_orderkey, l_linenumber)
        PARTITION BY l_shipdate;
    """

    IDENTIFIER_QUOTE = '"'
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"distribution", "partitioning", "sorting", "clustering"})

    @property
    def platform_name(self) -> str:
        return "firebolt"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate Firebolt tuning clauses.

        Args:
            table_tuning: Table tuning configuration.
            platform_opts: Platform-specific options.

        Returns:
            TuningClauses with distribute_by (rendered "PRIMARY INDEX (...)"
            clause, never a bare column list) and partition_by fields.
        """
        clauses = TuningClauses()

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        # Handle sorting info (Firebolt sorts within segments automatically)
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            logger.info(
                f"Sorting hint for Firebolt table {table_tuning.table_name}: "
                f"{[c.name for c in sort_columns]}. "
                f"Firebolt automatically sorts data within segments based on PRIMARY INDEX."
            )

        # Handle clustering info (handled by PRIMARY INDEX)
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            logger.info(
                f"Clustering hint for Firebolt table {table_tuning.table_name}: "
                f"{[c.name for c in cluster_columns]}. "
                f"Clustering is achieved through PRIMARY INDEX in Firebolt."
            )

        # Handle DISTRIBUTION -> PRIMARY INDEX. Stored rendered (not bare):
        # get_inline_clauses() emits it verbatim and generate_create_table_ddl()
        # uses it directly, so preview and execution can never disagree.
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.distribute_by = f"PRIMARY INDEX ({', '.join(col_names)})"

        # Handle partitioning -> PARTITION BY
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = ", ".join(col_names)

        return clauses

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses | None = None,
        if_not_exists: bool = False,
        schema: str | None = None,
    ) -> str:
        """Generate Firebolt CREATE TABLE statement.

        Args:
            table_name: Table name.
            columns: Column definitions.
            tuning: Tuning clauses from generate_tuning_clauses().
            if_not_exists: Add IF NOT EXISTS clause.
            schema: Database/schema name.

        Returns:
            Complete CREATE TABLE DDL string.
        """
        parts = ["CREATE TABLE"]

        if if_not_exists:
            parts.append("IF NOT EXISTS")

        parts.append(self.format_qualified_name(table_name, schema))

        statement = " ".join(parts)

        # Column definitions
        col_list = self.generate_column_list(columns)
        statement = f"{statement}\n(\n    {col_list}\n)"

        # Tuning clauses (distribute_by is already the rendered PRIMARY INDEX clause)
        if tuning:
            if tuning.distribute_by:
                statement = f"{statement}\n{tuning.distribute_by}"

            if tuning.partition_by:
                statement = f"{statement}\nPARTITION BY {tuning.partition_by}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def generate_column_list(self, columns: list[ColumnDefinition]) -> str:
        """Generate Firebolt column list with proper type mapping."""
        col_defs = []
        for column in columns:
            parts = [f"{self.IDENTIFIER_QUOTE}{column.name}{self.IDENTIFIER_QUOTE}"]

            # Map to Firebolt types
            data_type = self._map_to_firebolt_type(column.data_type)

            # Firebolt supports NULL/NOT NULL constraints
            if column.nullable == ColumnNullability.NOT_NULL:
                data_type = f"{data_type} NOT NULL"

            parts.append(data_type)

            if column.default_value is not None:
                parts.append(f"DEFAULT {column.default_value}")

            col_defs.append(" ".join(parts))

        return ",\n    ".join(col_defs)

    def _map_to_firebolt_type(self, sql_type: str) -> str:
        """Map standard SQL types to Firebolt types.

        Args:
            sql_type: Standard SQL type name.

        Returns:
            Firebolt-specific type name.
        """
        return map_sql_type_with_fallback(sql_type, FIREBOLT_TYPE_MAPPING)


__all__ = [
    "FireboltDDLGenerator",
]

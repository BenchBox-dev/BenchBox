"""ClickHouse DDL Generator.

Generates CREATE TABLE statements with MergeTree engine tuning clauses for ClickHouse.

ClickHouse uses the MergeTree family of engines with:
- PARTITION BY: Physical data partitioning for query pruning
- ORDER BY: Primary sort order (also used for index)
- PRIMARY KEY: Optional subset of ORDER BY columns
- TTL: Time-based data expiration

Example:
    >>> from benchbox.core.tuning.generators.clickhouse import ClickHouseDDLGenerator
    >>> generator = ClickHouseDDLGenerator()
    >>> clauses = generator.generate_tuning_clauses(table_tuning)
    >>> emit(clauses.partition_by)  # "toYYYYMM(l_shipdate)"
    >>> emit(clauses.sort_by)       # "l_orderkey, l_linenumber"

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from benchbox.core.tuning.ddl_generator import (
    BaseDDLGenerator,
    ColumnDefinition,
    TuningClauses,
)
from benchbox.core.tuning.type_mapping import map_sql_type_with_fallback

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)

CLICKHOUSE_TYPE_MAPPING: dict[str, str] = {
    # Integer types
    "INTEGER": "Int32",
    "INT": "Int32",
    "BIGINT": "Int64",
    "SMALLINT": "Int16",
    "TINYINT": "Int8",
    # Floating point
    "FLOAT": "Float32",
    "DOUBLE": "Float64",
    "REAL": "Float32",
    "DOUBLE PRECISION": "Float64",
    # Decimal
    "DECIMAL": "Decimal(18, 2)",
    "NUMERIC": "Decimal(18, 2)",
    # String types
    "VARCHAR": "String",
    "CHAR": "FixedString(255)",
    "TEXT": "String",
    "STRING": "String",
    # Date/time
    "DATE": "Date",
    "TIMESTAMP": "DateTime",
    "DATETIME": "DateTime",
    "TIME": "String",  # ClickHouse has no native TIME type
    # Boolean
    "BOOLEAN": "Bool",
    "BOOL": "Bool",
}


class MergeTreeEngine(str, Enum):
    """ClickHouse MergeTree engine variants."""

    MERGE_TREE = "MergeTree"
    REPLACING_MERGE_TREE = "ReplacingMergeTree"
    SUMMING_MERGE_TREE = "SummingMergeTree"
    AGGREGATING_MERGE_TREE = "AggregatingMergeTree"
    COLLAPSING_MERGE_TREE = "CollapsingMergeTree"
    VERSIONED_COLLAPSING_MERGE_TREE = "VersionedCollapsingMergeTree"
    GRAPHITE_MERGE_TREE = "GraphiteMergeTree"


class ClickHouseDDLGenerator(BaseDDLGenerator):
    """DDL generator for ClickHouse physical tuning.

    Generates MergeTree table DDL with:
    - ENGINE: MergeTree family engine selection
    - PARTITION BY: Physical partitioning for query pruning
    - ORDER BY: Primary sort order (required for MergeTree)
    - PRIMARY KEY: Optional subset of ORDER BY
    - TTL: Time-to-live for automatic data expiration
    - SETTINGS: Engine-specific settings

    ClickHouse Tuning Mapping:
    - SORTING → ORDER BY (required)
    - CLUSTERING → ORDER BY (combined with sorting)
    - PARTITIONING → PARTITION BY
    - DISTRIBUTION → Logged only (handled by Distributed engine)

    Example DDL:
        CREATE TABLE lineitem (
            l_orderkey Int64,
            l_shipdate Date,
            ...
        )
        ENGINE = MergeTree()
        PARTITION BY toYYYYMM(l_shipdate)
        ORDER BY (l_orderkey, l_linenumber)
        SETTINGS index_granularity = 8192;
    """

    IDENTIFIER_QUOTE = "`"
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"sorting", "clustering", "partitioning", "distribution"})

    def __init__(
        self,
        engine: MergeTreeEngine = MergeTreeEngine.MERGE_TREE,
        index_granularity: int = 8192,
    ):
        """Initialize the ClickHouse DDL generator.

        Args:
            engine: MergeTree engine variant to use.
            index_granularity: Index granularity setting (default 8192).
        """
        self._engine = engine
        self._index_granularity = index_granularity

    @property
    def platform_name(self) -> str:
        return "clickhouse"

    @property
    def engine(self) -> MergeTreeEngine:
        """Get the configured MergeTree engine variant."""
        return self._engine

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate ClickHouse tuning clauses.

        Args:
            table_tuning: Table tuning configuration.
            platform_opts: Platform-specific options.

        Returns:
            TuningClauses with partition_by and sort_by (ORDER BY) fields.
        """
        clauses = TuningClauses()

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        # Handle distribution warning (Distributed engine, not DDL)
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            logger.info(
                f"Distribution hint for ClickHouse table {table_tuning.table_name}: "
                f"{[c.name for c in distribution_columns]}. "
                f"Distribution is handled via Distributed engine, not table DDL."
            )

        # Generate ORDER BY clause from sorting + clustering
        order_columns = []

        # Include clustering columns first
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            order_columns.extend(sorted(cluster_columns, key=lambda c: c.order))

        # Include sorting columns
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            order_columns.extend(sorted(sort_columns, key=lambda c: c.order))

        if order_columns:
            # Remove duplicates while preserving order
            seen = set()
            unique_columns = []
            for col in order_columns:
                if col.name not in seen:
                    unique_columns.append(col)
                    seen.add(col.name)

            col_names = [c.name for c in unique_columns]
            clauses.sort_by = ", ".join(col_names)

        # Generate PARTITION BY clause
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            # For date columns, wrap with toYYYYMM for monthly partitioning
            partition_exprs = []
            for col in sorted_cols:
                if col.type and col.type.lower() in ("date", "datetime", "timestamp"):
                    partition_exprs.append(f"toYYYYMM({col.name})")
                else:
                    partition_exprs.append(col.name)
            clauses.partition_by = ", ".join(partition_exprs)

        return clauses

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses | None = None,
        if_not_exists: bool = False,
        schema: str | None = None,
    ) -> str:
        """Generate ClickHouse CREATE TABLE statement with MergeTree engine.

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

        # Engine clause
        statement = f"{statement}\nENGINE = {self._engine.value}()"

        # Tuning clauses
        if tuning:
            if tuning.partition_by:
                statement = f"{statement}\nPARTITION BY ({tuning.partition_by})"

            if tuning.sort_by:
                statement = f"{statement}\nORDER BY ({tuning.sort_by})"
            else:
                # MergeTree requires ORDER BY, use tuple() for no ordering
                statement = f"{statement}\nORDER BY tuple()"

        else:
            # MergeTree requires ORDER BY
            statement = f"{statement}\nORDER BY tuple()"

        # Settings
        statement = f"{statement}\nSETTINGS index_granularity = {self._index_granularity}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def get_post_load_statements(
        self,
        table_name: str,
        tuning: TuningClauses | None = None,
        schema: str | None = None,
    ) -> list[str]:
        """Get post-load statements for ClickHouse.

        ClickHouse may benefit from OPTIMIZE TABLE after bulk loading.

        Args:
            table_name: Table name.
            tuning: Tuning clauses.
            schema: Database/schema name.

        Returns:
            List of OPTIMIZE statements.
        """
        statements = []
        qualified_name = self.format_qualified_name(table_name, schema)

        # OPTIMIZE TABLE to merge parts and improve query performance
        statements.append(f"OPTIMIZE TABLE {qualified_name}")

        return statements

    def generate_column_list(self, columns: list[ColumnDefinition]) -> str:
        """Generate ClickHouse column list with proper type mapping.

        Overrides base to use ClickHouse-specific type names and nullable handling.
        """
        col_defs = []
        for column in columns:
            parts = [f"{self.IDENTIFIER_QUOTE}{column.name}{self.IDENTIFIER_QUOTE}"]

            # ClickHouse uses Nullable(Type) for nullable columns
            data_type = self._map_to_clickhouse_type(column.data_type)
            # Check using the nullable property from ColumnDefinition
            from benchbox.core.tuning.ddl_generator import ColumnNullability

            if column.nullable == ColumnNullability.NULLABLE or column.nullable == ColumnNullability.DEFAULT:
                data_type = f"Nullable({data_type})"

            parts.append(data_type)

            if column.default_value is not None:
                parts.append(f"DEFAULT {column.default_value}")

            col_defs.append(" ".join(parts))

        return ",\n    ".join(col_defs)

    def _map_to_clickhouse_type(self, sql_type: str) -> str:
        """Map standard SQL types to ClickHouse types.

        Args:
            sql_type: Standard SQL type name.

        Returns:
            ClickHouse-specific type name.
        """
        return map_sql_type_with_fallback(sql_type, CLICKHOUSE_TYPE_MAPPING)


__all__ = [
    "ClickHouseDDLGenerator",
    "MergeTreeEngine",
]

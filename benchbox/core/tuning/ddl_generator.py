"""DDL Generator Protocol and Base Implementation.

This module defines the unified interface for generating CREATE TABLE statements
with physical tuning clauses applied. All platform-specific DDL generators
implement this protocol.

Example usage:
    >>> from benchbox.core.tuning.ddl_generator import TuningClauses, ColumnDefinition
    >>> from benchbox.platforms.redshift import RedshiftDDLGenerator
    >>>
    >>> generator = RedshiftDDLGenerator()
    >>> clauses = generator.generate_tuning_clauses(table_tuning)
    >>> ddl = generator.generate_create_table_ddl("lineitem", columns, clauses)
    >>> emit(ddl)
    CREATE TABLE lineitem (...)
    DISTSTYLE KEY DISTKEY(l_orderkey)
    COMPOUND SORTKEY(l_shipdate, l_orderkey);

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )


class ColumnNullability(Enum):
    """Column nullability options."""

    NULLABLE = "nullable"
    NOT_NULL = "not_null"
    DEFAULT = "default"  # Use platform default


@dataclass
class ColumnDefinition:
    """Represents a column in a table schema.

    This is the input to DDL generation - describes what columns exist
    and their properties for CREATE TABLE statements.
    """

    name: str
    data_type: str
    nullable: ColumnNullability = ColumnNullability.DEFAULT
    default_value: str | None = None
    primary_key: bool = False
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable.value,
        }
        if self.default_value is not None:
            result["default_value"] = self.default_value
        if self.primary_key:
            result["primary_key"] = True
        if self.comment is not None:
            result["comment"] = self.comment
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColumnDefinition:
        """Create from dictionary."""
        nullable = ColumnNullability.DEFAULT
        if "nullable" in data:
            nullable = ColumnNullability(data["nullable"])

        return cls(
            name=data["name"],
            data_type=data["data_type"],
            nullable=nullable,
            default_value=data.get("default_value"),
            primary_key=data.get("primary_key", False),
            comment=data.get("comment"),
        )


@dataclass
class TuningClauses:
    """Structured output from DDL generation.

    Contains all the tuning clauses that will be appended to a CREATE TABLE
    statement. Each field is platform-specific SQL syntax.

    This dataclass is JSON-serializable for dry-run output and debugging.
    """

    # Partitioning clause (e.g., "PARTITION BY DATE(col)" for BigQuery)
    partition_by: str | None = None

    # Clustering clause (e.g., "CLUSTER BY (col1, col2)" for Snowflake)
    cluster_by: str | None = None

    # Distribution clause (e.g., "DISTSTYLE KEY DISTKEY(col)" for Redshift)
    distribute_by: str | None = None

    # Sort key clause (e.g., "COMPOUND SORTKEY(col1, col2)" for Redshift)
    sort_by: str | None = None

    # Primary key clause (e.g., "PRIMARY KEY (col1, col2)")
    primary_key: str | None = None

    # ORDER BY clause for table ordering (e.g., "ORDER BY (col1, col2)" for ClickHouse)
    order_by: str | None = None

    # Platform-specific table properties (e.g., Delta Lake TBLPROPERTIES)
    table_properties: dict[str, str] = field(default_factory=dict)

    # Table options (e.g., BigQuery OPTIONS clause)
    table_options: dict[str, Any] = field(default_factory=dict)

    # Additional clauses that don't fit other categories
    additional_clauses: list[str] = field(default_factory=list)

    # Post-CREATE statements to run after table creation
    # e.g., OPTIMIZE, Z-ORDER, CREATE INDEX, ALTER TABLE
    post_create_statements: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Check if no tuning clauses are defined."""
        return (
            self.partition_by is None
            and self.cluster_by is None
            and self.distribute_by is None
            and self.sort_by is None
            and self.primary_key is None
            and self.order_by is None
            and not self.table_properties
            and not self.table_options
            and not self.additional_clauses
            and not self.post_create_statements
        )

    def get_inline_clauses(self) -> list[str]:
        """Get all clauses that go in the CREATE TABLE statement.

        Returns clauses in the standard order for most SQL dialects.
        Platform-specific generators may override this ordering.
        """
        clauses = []

        # Primary key first (often part of column definitions, but can be table-level)
        if self.primary_key:
            clauses.append(self.primary_key)

        # Distribution before partitioning (Redshift pattern)
        if self.distribute_by:
            clauses.append(self.distribute_by)

        # Partitioning
        if self.partition_by:
            clauses.append(self.partition_by)

        # Clustering
        if self.cluster_by:
            clauses.append(self.cluster_by)

        # Sort keys
        if self.sort_by:
            clauses.append(self.sort_by)

        # ORDER BY (ClickHouse, DuckDB)
        if self.order_by:
            clauses.append(self.order_by)

        # Additional platform-specific clauses
        clauses.extend(self.additional_clauses)

        return clauses

    def get_table_properties_clause(self) -> str | None:
        """Generate TBLPROPERTIES or similar clause.

        Returns:
            Formatted properties clause or None if no properties.
        """
        if not self.table_properties:
            return None

        props = ", ".join(f"'{k}' = '{v}'" for k, v in sorted(self.table_properties.items()))
        return f"TBLPROPERTIES ({props})"

    def get_table_options_clause(self) -> str | None:
        """Generate OPTIONS clause (BigQuery style).

        Returns:
            Formatted options clause or None if no options.
        """
        if not self.table_options:
            return None

        def format_value(v: Any) -> str:
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, str):
                return f"'{v}'"
            return str(v)

        opts = ", ".join(f"{k} = {format_value(v)}" for k, v in sorted(self.table_options.items()))
        return f"OPTIONS ({opts})"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {}

        if self.partition_by:
            result["partition_by"] = self.partition_by
        if self.cluster_by:
            result["cluster_by"] = self.cluster_by
        if self.distribute_by:
            result["distribute_by"] = self.distribute_by
        if self.sort_by:
            result["sort_by"] = self.sort_by
        if self.primary_key:
            result["primary_key"] = self.primary_key
        if self.order_by:
            result["order_by"] = self.order_by
        if self.table_properties:
            result["table_properties"] = self.table_properties
        if self.table_options:
            result["table_options"] = self.table_options
        if self.additional_clauses:
            result["additional_clauses"] = self.additional_clauses
        if self.post_create_statements:
            result["post_create_statements"] = self.post_create_statements

        return result

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string for dry-run output."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TuningClauses:
        """Create from dictionary."""
        return cls(
            partition_by=data.get("partition_by"),
            cluster_by=data.get("cluster_by"),
            distribute_by=data.get("distribute_by"),
            sort_by=data.get("sort_by"),
            primary_key=data.get("primary_key"),
            order_by=data.get("order_by"),
            table_properties=data.get("table_properties", {}),
            table_options=data.get("table_options", {}),
            additional_clauses=data.get("additional_clauses", []),
            post_create_statements=data.get("post_create_statements", []),
        )

    def merge(self, other: TuningClauses) -> TuningClauses:
        """Merge another TuningClauses into this one.

        Values from `other` take precedence for single-value fields.
        List and dict fields are combined.

        Args:
            other: TuningClauses to merge in.

        Returns:
            New TuningClauses with merged values.
        """
        return TuningClauses(
            partition_by=other.partition_by or self.partition_by,
            cluster_by=other.cluster_by or self.cluster_by,
            distribute_by=other.distribute_by or self.distribute_by,
            sort_by=other.sort_by or self.sort_by,
            primary_key=other.primary_key or self.primary_key,
            order_by=other.order_by or self.order_by,
            table_properties={**self.table_properties, **other.table_properties},
            table_options={**self.table_options, **other.table_options},
            additional_clauses=[*self.additional_clauses, *other.additional_clauses],
            post_create_statements=[*self.post_create_statements, *other.post_create_statements],
        )


@runtime_checkable
class DDLGenerator(Protocol):
    """Protocol for platform-specific DDL generation.

    Platform adapters implement this protocol to generate CREATE TABLE
    statements with physical tuning clauses. The protocol is designed
    to be composable - generators can be used standalone or integrated
    into platform adapters.

    Example implementation:
        class RedshiftDDLGenerator:
            def generate_tuning_clauses(
                self,
                table_tuning: TableTuning,
                platform_opts: PlatformOptimizationConfiguration | None = None,
            ) -> TuningClauses:
                clauses = TuningClauses()
                if table_tuning.distribution:
                    col = table_tuning.distribution[0].name
                    clauses.distribute_by = f"DISTSTYLE KEY DISTKEY({col})"
                return clauses
    """

    @property
    def platform_name(self) -> str:
        """Return the platform name for logging and errors."""
        ...

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate tuning clauses for a table.

        This is the main method that converts tuning configuration into
        platform-specific SQL clauses.

        Args:
            table_tuning: Table-level tuning configuration (partitioning,
                clustering, distribution, sorting columns).
            platform_opts: Platform-specific optimization settings
                (Z-ordering, auto-optimize, bloom filters, etc.).

        Returns:
            TuningClauses containing all applicable SQL clauses.
        """
        ...

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses | None = None,
        if_not_exists: bool = False,
        schema: str | None = None,
    ) -> str:
        """Generate complete CREATE TABLE statement.

        Args:
            table_name: Name of the table to create.
            columns: List of column definitions.
            tuning: Optional tuning clauses to apply.
            if_not_exists: Whether to add IF NOT EXISTS clause.
            schema: Optional schema/database name prefix.

        Returns:
            Complete CREATE TABLE SQL statement.
        """
        ...

    def get_post_load_statements(
        self,
        table_name: str,
        tuning: TuningClauses,
        schema: str | None = None,
    ) -> list[str]:
        """Get statements to run after data load.

        Some tuning operations (like OPTIMIZE, Z-ORDER, ANALYZE) must
        run after data is loaded into the table.

        Args:
            table_name: Name of the table.
            tuning: Tuning clauses containing post_create_statements.
            schema: Optional schema/database name prefix.

        Returns:
            List of SQL statements to execute after data load.
        """
        ...

    def supports_tuning_type(self, tuning_type: str) -> bool:
        """Check if this generator supports a specific tuning type.

        Args:
            tuning_type: Name of the tuning type (e.g., "partitioning",
                "clustering", "distribution", "sorting").

        Returns:
            True if the tuning type is supported.
        """
        ...


class BaseDDLGenerator(ABC):
    """Abstract base class for DDL generators with common functionality.

    Provides shared logic for column list generation, identifier quoting,
    and clause formatting. Platform-specific generators extend this class
    and override the abstract methods.

    Class Attributes:
        IDENTIFIER_QUOTE: Character used to quote identifiers (default: '"')
        SUPPORTS_IF_NOT_EXISTS: Whether platform supports IF NOT EXISTS
        STATEMENT_TERMINATOR: Statement terminator (default: ';')
    """

    IDENTIFIER_QUOTE: str = '"'
    SUPPORTS_IF_NOT_EXISTS: bool = True
    STATEMENT_TERMINATOR: str = ";"

    # Tuning types this generator supports
    SUPPORTED_TUNING_TYPES: frozenset[str] = frozenset()

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform name for logging and errors."""
        ...

    def quote_identifier(self, identifier: str) -> str:
        """Quote an identifier if needed.

        Args:
            identifier: Table or column name.

        Returns:
            Quoted identifier if it contains special characters.
        """
        # Simple check - quote if not a simple identifier
        if identifier.isidentifier() and identifier.lower() == identifier:
            return identifier
        return f"{self.IDENTIFIER_QUOTE}{identifier}{self.IDENTIFIER_QUOTE}"

    def format_qualified_name(self, table_name: str, schema: str | None = None) -> str:
        """Format a fully qualified table name.

        Args:
            table_name: Table name.
            schema: Optional schema/database prefix.

        Returns:
            Qualified name like "schema.table" or just "table".
        """
        if schema:
            return f"{self.quote_identifier(schema)}.{self.quote_identifier(table_name)}"
        return self.quote_identifier(table_name)

    def generate_column_list(
        self,
        columns: list[ColumnDefinition],
        include_constraints: bool = True,
    ) -> str:
        """Generate the column definition list for CREATE TABLE.

        Args:
            columns: List of column definitions.
            include_constraints: Whether to include inline constraints.

        Returns:
            Formatted column list for CREATE TABLE.
        """
        col_defs = []
        for col in columns:
            col_def = self._format_column_definition(col, include_constraints)
            col_defs.append(col_def)

        return ",\n    ".join(col_defs)

    def _format_column_definition(
        self,
        column: ColumnDefinition,
        include_constraints: bool = True,
    ) -> str:
        """Format a single column definition.

        Args:
            column: Column definition.
            include_constraints: Whether to include inline constraints.

        Returns:
            Formatted column definition string.
        """
        parts = [self.quote_identifier(column.name), column.data_type]

        if include_constraints:
            # Nullability
            if column.nullable == ColumnNullability.NOT_NULL:
                parts.append("NOT NULL")
            elif column.nullable == ColumnNullability.NULLABLE:
                parts.append("NULL")

            # Default value
            if column.default_value is not None:
                parts.append(f"DEFAULT {column.default_value}")

            # Primary key (inline)
            if column.primary_key:
                parts.append("PRIMARY KEY")

        return " ".join(parts)

    @abstractmethod
    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate tuning clauses for a table.

        Subclasses must implement this method to produce platform-specific
        tuning clauses.
        """
        ...

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses | None = None,
        if_not_exists: bool = False,
        schema: str | None = None,
    ) -> str:
        """Generate complete CREATE TABLE statement.

        This implementation provides the standard SQL structure. Subclasses
        can override for platform-specific syntax.
        """
        parts = ["CREATE TABLE"]

        if if_not_exists and self.SUPPORTS_IF_NOT_EXISTS:
            parts.append("IF NOT EXISTS")

        # Table name
        parts.append(self.format_qualified_name(table_name, schema))

        # Build the full statement
        statement = " ".join(parts)

        # Column definitions
        col_list = self.generate_column_list(columns)
        statement = f"{statement} (\n    {col_list}\n)"

        # Add tuning clauses if provided
        if tuning and not tuning.is_empty():
            logger.debug(
                "Applying tuning to table %s: %s",
                table_name,
                tuning.to_dict(),
            )
            inline_clauses = tuning.get_inline_clauses()
            if inline_clauses:
                statement = f"{statement}\n{chr(10).join(inline_clauses)}"

            # Table properties (Delta Lake, Spark)
            props_clause = tuning.get_table_properties_clause()
            if props_clause:
                statement = f"{statement}\n{props_clause}"

            # Table options (BigQuery)
            opts_clause = tuning.get_table_options_clause()
            if opts_clause:
                statement = f"{statement}\n{opts_clause}"

        # Terminator
        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def get_post_load_statements(
        self,
        table_name: str,
        tuning: TuningClauses,
        schema: str | None = None,
    ) -> list[str]:
        """Get statements to run after data load.

        Default implementation returns the post_create_statements from
        TuningClauses. Subclasses can override to add platform-specific
        logic.
        """
        if not tuning or not tuning.post_create_statements:
            return []

        qualified_name = self.format_qualified_name(table_name, schema)
        return [stmt.format(table_name=qualified_name) for stmt in tuning.post_create_statements]

    def supports_tuning_type(self, tuning_type: str) -> bool:
        """Check if this generator supports a specific tuning type."""
        return tuning_type.lower() in self.SUPPORTED_TUNING_TYPES


class NoOpDDLGenerator(BaseDDLGenerator):
    """DDL generator that produces no tuning clauses.

    Use this for platforms that don't support physical tuning,
    like SQLite or in-memory engines.
    """

    SUPPORTED_TUNING_TYPES: frozenset[str] = frozenset()

    def __init__(self, platform: str = "unknown"):
        self._platform_name = platform

    @property
    def platform_name(self) -> str:
        return self._platform_name

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Return empty tuning clauses."""
        return TuningClauses()


# Type alias for type hints
DDLGeneratorType = DDLGenerator | BaseDDLGenerator


def get_ddl_generator(platform_type: str) -> BaseDDLGenerator:
    """Get the appropriate DDL generator for a platform.

    Args:
        platform_type: Platform type identifier (e.g., "duckdb", "snowflake").

    Returns:
        DDL generator instance for the platform.

    Raises:
        ValueError: If no generator is available for the platform.
    """
    # Import generators here to avoid circular imports
    from benchbox.core.tuning.generators.azure_synapse import AzureSynapseDDLGenerator
    from benchbox.core.tuning.generators.bigquery import BigQueryDDLGenerator
    from benchbox.core.tuning.generators.clickhouse import ClickHouseDDLGenerator
    from benchbox.core.tuning.generators.doris import DorisDDLGenerator
    from benchbox.core.tuning.generators.duckdb import DuckDBDDLGenerator
    from benchbox.core.tuning.generators.firebolt import FireboltDDLGenerator
    from benchbox.core.tuning.generators.postgresql import PostgreSQLDDLGenerator
    from benchbox.core.tuning.generators.redshift import RedshiftDDLGenerator
    from benchbox.core.tuning.generators.snowflake import SnowflakeDDLGenerator
    from benchbox.core.tuning.generators.spark_family import DeltaDDLGenerator
    from benchbox.core.tuning.generators.timescaledb import TimescaleDBDDLGenerator
    from benchbox.core.tuning.generators.trino import AthenaDDLGenerator, TrinoDDLGenerator

    # Map platform types to generators
    generators: dict[str, type[BaseDDLGenerator]] = {
        # Core platforms
        "doris": DorisDDLGenerator,
        "duckdb": DuckDBDDLGenerator,
        "snowflake": SnowflakeDDLGenerator,
        "bigquery": BigQueryDDLGenerator,
        "redshift": RedshiftDDLGenerator,
        "postgresql": PostgreSQLDDLGenerator,
        "timescaledb": TimescaleDBDDLGenerator,
        # ClickHouse (all three first-class platform names map to the shared generator)
        "clickhouse": ClickHouseDDLGenerator,
        "clickhouse-local": ClickHouseDDLGenerator,
        "clickhouse-server": ClickHouseDDLGenerator,
        "chdb": ClickHouseDDLGenerator,
        # Firebolt
        "firebolt": FireboltDDLGenerator,
        # Azure Synapse
        "azure_synapse": AzureSynapseDDLGenerator,
        "synapse": AzureSynapseDDLGenerator,
        # Trino/Presto/Athena
        "trino": TrinoDDLGenerator,
        "presto": TrinoDDLGenerator,
        "athena": AthenaDDLGenerator,
        # Spark family (including Fabric Warehouse which uses Delta)
        "databricks": DeltaDDLGenerator,
        "spark": DeltaDDLGenerator,
        "delta": DeltaDDLGenerator,
        "fabric_warehouse": DeltaDDLGenerator,  # Fabric uses Delta Lake tables
    }

    platform_lower = platform_type.lower()

    if platform_lower in generators:
        return generators[platform_lower]()

    # Return NoOp generator for platforms without tuning support
    return NoOpDDLGenerator(platform_type)


__all__ = [
    "ColumnDefinition",
    "ColumnNullability",
    "TuningClauses",
    "DDLGenerator",
    "BaseDDLGenerator",
    "NoOpDDLGenerator",
    "DDLGeneratorType",
    "get_ddl_generator",
]

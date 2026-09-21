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


# Platforms whose dialect requires DISTRIBUTED BY after PARTITION BY in the
# CREATE TABLE statement (StarRocks, Doris). get_inline_clauses() orders the
# rendered distribute_by after partition_by for these platforms; every other
# platform keeps the legacy distribution-first order.
_DISTRIBUTE_AFTER_PARTITION_PLATFORMS = frozenset({"starrocks", "doris"})


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

    # Distribution clause, always rendered SQL ready for inline emission --
    # never a bare column name. The exact form is platform-specific:
    # - Redshift: "DISTSTYLE KEY\nDISTKEY (col)" / "DISTSTYLE ALL" / ...
    # - StarRocks/Doris: "DISTRIBUTED BY HASH(`col`) BUCKETS N"
    # - Firebolt: "PRIMARY INDEX (col1, col2)"
    # - Spark family: "CLUSTERED BY (cols) INTO N BUCKETS"
    # - Synapse: "HASH([col])" / "ROUND_ROBIN" fragment consumed by the
    #   "DISTRIBUTION = ..." wrapper in its WITH clause.
    # get_inline_clauses() emits this value verbatim; each generator's
    # generate_create_table_ddl() uses it directly without re-rendering.
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

    # Dialect marker set by generators whose inline-clause order differs from
    # the legacy default (e.g., "starrocks", "doris"). Metadata only: ignored
    # by is_empty(), serialized only when set. get_inline_clauses() uses it
    # to pick the platform-aware clause order.
    platform: str | None = None

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

        Returns clauses in the standard order for most SQL dialects
        (distribution before partitioning, the Redshift pattern), except for
        platforms in _DISTRIBUTE_AFTER_PARTITION_PLATFORMS (StarRocks, Doris),
        whose dialects require DISTRIBUTED BY after PARTITION BY; Doris
        additionally orders its DUPLICATE KEY (``sort_by``) first. The order
        is keyed off the ``platform`` marker the corresponding generators set;
        every other platform keeps the legacy order byte-identical.
        """
        clauses = []

        # Primary key first (often part of column definitions, but can be table-level)
        if self.primary_key:
            clauses.append(self.primary_key)

        if self.platform == "doris":
            # Doris pattern: DUPLICATE KEY -> PARTITION BY -> DISTRIBUTED BY,
            # mirroring DorisDDLGenerator.generate_create_table_ddl.
            if self.sort_by:
                clauses.append(self.sort_by)
            if self.partition_by:
                clauses.append(self.partition_by)
            if self.distribute_by:
                clauses.append(self.distribute_by)
        elif self.platform in _DISTRIBUTE_AFTER_PARTITION_PLATFORMS:
            # StarRocks pattern: PARTITION BY -> DISTRIBUTED BY.
            if self.partition_by:
                clauses.append(self.partition_by)
            if self.distribute_by:
                clauses.append(self.distribute_by)
        else:
            # Distribution before partitioning (Redshift pattern)
            if self.distribute_by:
                clauses.append(self.distribute_by)

            # Partitioning
            if self.partition_by:
                clauses.append(self.partition_by)

        # Clustering
        if self.cluster_by:
            clauses.append(self.cluster_by)

        # Sort keys (all platforms except Doris, ordered above)
        if self.sort_by and self.platform != "doris":
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
        # Ordering metadata is meaningless with no clauses to order, so an
        # empty-but-marked instance serializes exactly like an empty one.
        if self.platform and not self.is_empty():
            result["platform"] = self.platform

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
            platform=data.get("platform"),
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
            platform=other.platform or self.platform,
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

# Platforms known to have no physical tuning surface (no partitioning, clustering,
# distribution, or sort-key clauses to emit) - the NoOp fallback for these is
# expected and permanent, so get_ddl_generator() does not warn for them.
# Bare `lakesail` and `velox` are deliberately NOT listed: their SQL adapters
# call _create_schema_with_tuning() and their generate_tuning_clause() methods
# emit PARTITIONED BY, so a tuned dry run must keep the warning that exposes
# the preview-versus-execution gap until they get real registry generators.
_TUNING_FREE_PLATFORMS: frozenset[str] = frozenset(
    {
        "sqlite",
        "sqlite3",
        "pandas",
        "cudf",
        "dask",
        "polars",
        "datafusion",
        "pyspark",
    }
)

# Base engine keys that own a declared "<engine>-df" spelling in the platform
# manifest (the CLI aliases plus the "databricks-df" entry key - see
# benchbox/core/platform_manifest.py). Only these bases strip the "-df"
# suffix below; undeclared combinations such as "snowflake-df" never resolve
# to an unrelated real generator and instead take the warning/NoOp path.
# Update trigger: a new manifest "<engine>-df" alias or entry key.
_DATAFRAME_SUFFIX_BASES: frozenset[str] = frozenset(
    {
        "pandas",
        "cudf",
        "dask",
        "polars",
        "datafusion",
        "pyspark",
        "lakesail",
        "databricks",
    }
)

# Base engine keys that own a declared "dataframe-<engine>" packaging extra
# (see pyproject.toml [project.optional-dependencies]). Only these bases
# strip the "dataframe-" prefix below, so "dataframe-snowflake" takes the
# warning/NoOp path instead of resolving to SnowflakeDDLGenerator.
# Update trigger: a new dataframe-* extra in pyproject.toml.
_DATAFRAME_PREFIX_BASES: frozenset[str] = frozenset(
    {
        "pandas",
        "cudf",
        "dask",
        "polars",
        "datafusion",
        "pyspark",
    }
)

_DATAFRAME_KEY_PREFIX = "dataframe-"
_DATAFRAME_KEY_SUFFIX = "-df"


def _normalize_dataframe_platform_key(platform_lower: str) -> str:
    """Normalize a declared DataFrame-mode platform key to its base engine key.

    Only declared spellings normalize: "<engine>-df" when the base owns a
    manifest-declared DataFrame spelling, and "dataframe-<engine>" when the
    base owns a dataframe-* packaging extra. Anything else returns unchanged.
    """
    if platform_lower.startswith(_DATAFRAME_KEY_PREFIX):
        base = platform_lower[len(_DATAFRAME_KEY_PREFIX) :]
        return base if base in _DATAFRAME_PREFIX_BASES else platform_lower
    if platform_lower.endswith(_DATAFRAME_KEY_SUFFIX):
        base = platform_lower[: -len(_DATAFRAME_KEY_SUFFIX)]
        return base if base in _DATAFRAME_SUFFIX_BASES else platform_lower
    return platform_lower


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
    from benchbox.core.tuning.generators.pg_duckdb import PgDuckDBDDLGenerator
    from benchbox.core.tuning.generators.pg_mooncake import PgMooncakeDDLGenerator
    from benchbox.core.tuning.generators.postgresql import PostgreSQLDDLGenerator
    from benchbox.core.tuning.generators.questdb import QuestDBDDLGenerator
    from benchbox.core.tuning.generators.redshift import RedshiftDDLGenerator
    from benchbox.core.tuning.generators.snowflake import SnowflakeDDLGenerator
    from benchbox.core.tuning.generators.spark_family import DeltaDDLGenerator
    from benchbox.core.tuning.generators.starrocks import StarRocksDDLGenerator
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
        # StarRocks (MPP; DISTRIBUTED BY HASH is engine-mandatory). Both the
        # dry-run preview and the workload's schema-creation path render tuned
        # PARTITION BY / DISTRIBUTED BY / ORDER BY through this one generator.
        "starrocks": StarRocksDDLGenerator,
        # ClickHouse (all first-class platform names map to the shared generator,
        # matching workload.py's execution path, which always renders tuned DDL
        # via the "clickhouse" generator regardless of variant)
        "clickhouse": ClickHouseDDLGenerator,
        "clickhouse-local": ClickHouseDDLGenerator,
        "clickhouse-server": ClickHouseDDLGenerator,
        "clickhouse-cloud": ClickHouseDDLGenerator,
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
        # QuestDB
        "questdb": QuestDBDDLGenerator,
        # pg_duckdb / pg_mooncake (PostgreSQL extensions). Both the hyphenated CLI
        # platform key from PlatformRegistry (e.g. "pg-duckdb") and the underscored
        # form used by the adapters' own platform_name/platform_type (e.g.
        # "pg_duckdb") are registered so callers using either convention resolve
        # to the real generator instead of falling through to NoOp.
        "pg-duckdb": PgDuckDBDDLGenerator,
        "pg_duckdb": PgDuckDBDDLGenerator,
        "pg-mooncake": PgMooncakeDDLGenerator,
        "pg_mooncake": PgMooncakeDDLGenerator,
    }

    platform_lower = platform_type.lower()

    if platform_lower in generators:
        return generators[platform_lower]()

    # Declared DataFrame-mode keys ("<engine>-df" for manifest-declared engines,
    # "dataframe-<engine>" for packaging-extra engines) resolve behind the same
    # registry-owned path: normalize to the base engine key and retry the
    # generators mapping so a real generator always wins when one exists
    # (e.g. "databricks-df" renders Delta DDL). Undeclared combinations skip
    # normalization entirely and fall through to the warning/NoOp path below.
    normalized = _normalize_dataframe_platform_key(platform_lower)
    if normalized != platform_lower and normalized in generators:
        return generators[normalized]()

    # Platforms with no physical tuning surface at all (in-memory/embedded engines
    # with no indexes, partitioning, or clustering clauses to emit). NoOp is the
    # correct, permanent answer for these, so the fallback stays silent. Anything
    # else falling through here is either a platform that should get a real
    # generator eventually or a typo'd platform string - both are worth a
    # warning since dry-run/tuning preview would otherwise go silently empty.
    # The tuning-free check runs on the normalized key so DataFrame-mode
    # spellings ("polars-df", "dataframe-polars", ...) stay silent exactly when
    # their base engine is tuning-free.
    if normalized not in _TUNING_FREE_PLATFORMS:
        logger.warning(
            "No DDL generator registered for platform %r; tuning clauses will be "
            "empty (NoOp fallback). If %r supports physical tuning, register it "
            "in get_ddl_generator().",
            platform_type,
            platform_type,
        )

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

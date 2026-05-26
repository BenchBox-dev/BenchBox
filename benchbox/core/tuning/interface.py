"""Core tuning interface classes for BenchBox.

This module defines the core interfaces for database table tuning configurations,
including enums, dataclasses, and management classes that support serialization,
validation, and platform-specific tuning optimizations.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional


class TuningType(Enum):
    """Enumeration of supported database tuning types.

    This enum defines the different types of database optimizations that can be
    applied to tables across different platforms.
    """

    # Table-level performance tunings
    PARTITIONING = "partitioning"
    CLUSTERING = "clustering"
    DISTRIBUTION = "distribution"
    SORTING = "sorting"

    # Schema constraint tunings
    PRIMARY_KEYS = "primary_keys"
    FOREIGN_KEYS = "foreign_keys"
    UNIQUE_CONSTRAINTS = "unique_constraints"
    CHECK_CONSTRAINTS = "check_constraints"

    # Platform-specific optimizations
    Z_ORDERING = "z_ordering"  # Databricks Delta Lake
    LIQUID_CLUSTERING = "liquid_clustering"  # Databricks Delta Lake
    AUTO_OPTIMIZE = "auto_optimize"  # Databricks
    AUTO_COMPACT = "auto_compact"  # Databricks
    BLOOM_FILTERS = "bloom_filters"  # Various platforms
    MATERIALIZED_VIEWS = "materialized_views"  # Query acceleration

    def __str__(self) -> str:
        """Return the string representation of the tuning type."""
        return self.value

    @classmethod
    def from_string(cls, value: str) -> "TuningType":
        """Create a TuningType from a string value.

        Args:
            value: The string representation of the tuning type

        Returns:
            The corresponding TuningType enum value

        Raises:
            ValueError: If the value is not a valid tuning type
        """
        value_lower = value.lower()
        for tuning_type in cls:
            if tuning_type.value == value_lower:
                return tuning_type
        raise ValueError(f"Invalid tuning type: {value}")

    def is_compatible_with_platform(self, platform: str) -> bool:
        """Check if this tuning type is compatible with the given platform.

        Args:
            platform: The name of the database platform (e.g., 'duckdb', 'snowflake')

        Returns:
            True if the tuning type is supported by the platform
        """
        # Platform compatibility mapping
        compatibility_map = {
            "duckdb": {
                self.SORTING,
                self.PARTITIONING,
                self.PRIMARY_KEYS,
                self.FOREIGN_KEYS,
                self.UNIQUE_CONSTRAINTS,
                self.CHECK_CONSTRAINTS,
            },
            "snowflake": {
                self.CLUSTERING,
                self.PARTITIONING,
                self.PRIMARY_KEYS,
                self.FOREIGN_KEYS,
                self.UNIQUE_CONSTRAINTS,
                self.CHECK_CONSTRAINTS,
                self.MATERIALIZED_VIEWS,
            },
            "bigquery": {
                self.PARTITIONING,
                self.CLUSTERING,
                self.PRIMARY_KEYS,
                self.FOREIGN_KEYS,
                self.CHECK_CONSTRAINTS,
                self.MATERIALIZED_VIEWS,
            },
            "redshift": {
                self.DISTRIBUTION,
                self.SORTING,
                self.PARTITIONING,
                self.PRIMARY_KEYS,
                self.FOREIGN_KEYS,
                self.UNIQUE_CONSTRAINTS,
                self.CHECK_CONSTRAINTS,
                self.MATERIALIZED_VIEWS,
            },
            "clickhouse": {
                self.PARTITIONING,
                self.SORTING,
                self.CLUSTERING,
                self.PRIMARY_KEYS,
                self.UNIQUE_CONSTRAINTS,
                self.MATERIALIZED_VIEWS,
            },
            "databricks": {
                self.PARTITIONING,
                self.CLUSTERING,
                self.DISTRIBUTION,
                self.PRIMARY_KEYS,
                self.FOREIGN_KEYS,
                self.UNIQUE_CONSTRAINTS,
                self.CHECK_CONSTRAINTS,
                self.Z_ORDERING,
                self.LIQUID_CLUSTERING,
                self.AUTO_OPTIMIZE,
                self.AUTO_COMPACT,
                self.BLOOM_FILTERS,
                self.MATERIALIZED_VIEWS,
            },
            "sqlite": {
                self.PRIMARY_KEYS,
                self.FOREIGN_KEYS,
                self.UNIQUE_CONSTRAINTS,
                self.CHECK_CONSTRAINTS,
            },
            "postgresql": {
                self.PARTITIONING,
                self.CLUSTERING,
                self.PRIMARY_KEYS,
                self.FOREIGN_KEYS,
                self.UNIQUE_CONSTRAINTS,
                self.CHECK_CONSTRAINTS,
                self.BLOOM_FILTERS,
                self.MATERIALIZED_VIEWS,
            },
            "mysql": {
                self.PARTITIONING,
                self.PRIMARY_KEYS,
                self.FOREIGN_KEYS,
                self.UNIQUE_CONSTRAINTS,
                self.CHECK_CONSTRAINTS,
            },
        }

        platform_lower = platform.lower()
        return self in compatibility_map.get(platform_lower, set())


# Type aliases for TuningColumn options
SortOrderType = Literal["ASC", "DESC"]
NullsPositionType = Literal["FIRST", "LAST", "DEFAULT"]


@dataclass
class TuningColumn:
    """Represents a column used in table tuning configurations.

    This dataclass defines a column that participates in table tuning,
    including its name, type, ordering, and optional platform-specific settings.

    Attributes:
        name: Column name (valid SQL identifier).
        type: SQL data type (e.g., 'DATE', 'INTEGER', 'VARCHAR(255)').
        order: Position in tuning configuration (1-based, must be unique within a tuning type).
        sort_order: Sort direction for sorting/clustering (ASC or DESC). Default: ASC.
        nulls_position: Position of NULL values in sort order. Default: DEFAULT (platform-specific).
        compression: Platform-specific compression/encoding (e.g., 'lzo', 'zstd', 'az64' for Redshift).
    """

    name: str
    type: str  # SQL data type (e.g., 'DATE', 'INTEGER', 'VARCHAR(255)')
    order: int

    # Optional fields with defaults
    sort_order: SortOrderType = "ASC"
    nulls_position: NullsPositionType = "DEFAULT"
    compression: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate the tuning column configuration after initialization."""
        self._validate_name()
        self._validate_order()
        self._validate_sort_order()
        self._validate_nulls_position()

    def _validate_name(self) -> None:
        """Validate the column name format.

        Raises:
            ValueError: If the column name is invalid
        """
        if not self.name:
            raise ValueError("Column name cannot be empty")

        if not isinstance(self.name, str):
            raise ValueError("Column name must be a string")

        # Check for valid SQL identifier format (alphanumeric and underscore)
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", self.name):
            raise ValueError(
                f"Invalid column name format: '{self.name}'. "
                "Column names must start with a letter or underscore and "
                "contain only letters, numbers, and underscores."
            )

    def _validate_order(self) -> None:
        """Validate the column order value.

        Raises:
            ValueError: If the order is invalid
        """
        if not isinstance(self.order, int):
            raise ValueError("Column order must be an integer")

        if self.order <= 0:
            raise ValueError("Column order must be a positive integer")

    def _validate_sort_order(self) -> None:
        """Validate the sort order value.

        Raises:
            ValueError: If the sort order is invalid
        """
        if self.sort_order not in ("ASC", "DESC"):
            raise ValueError(f"Invalid sort_order: '{self.sort_order}'. Must be 'ASC' or 'DESC'.")

    def _validate_nulls_position(self) -> None:
        """Validate the nulls position value.

        Raises:
            ValueError: If the nulls position is invalid
        """
        if self.nulls_position not in ("FIRST", "LAST", "DEFAULT"):
            raise ValueError(f"Invalid nulls_position: '{self.nulls_position}'. Must be 'FIRST', 'LAST', or 'DEFAULT'.")

    def to_dict(self) -> dict[str, Any]:
        """Convert the tuning column to a dictionary for serialization.

        Only includes non-default values for optional fields to keep
        YAML files clean.

        Returns:
            Dictionary representation of the tuning column
        """
        result = {
            "name": self.name,
            "type": self.type,
            "order": self.order,
        }

        # Only include optional fields if they differ from defaults
        if self.sort_order != "ASC":
            result["sort_order"] = self.sort_order
        if self.nulls_position != "DEFAULT":
            result["nulls_position"] = self.nulls_position
        if self.compression is not None:
            result["compression"] = self.compression

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TuningColumn":
        """Create a TuningColumn from a dictionary.

        Args:
            data: Dictionary containing column configuration

        Returns:
            New TuningColumn instance

        Raises:
            ValueError: If the dictionary is missing required fields
        """
        required_fields = {"name", "type", "order"}
        missing_fields = required_fields - data.keys()
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")

        return cls(
            name=data["name"],
            type=data["type"],
            order=data["order"],
            sort_order=data.get("sort_order", "ASC"),
            nulls_position=data.get("nulls_position", "DEFAULT"),
            compression=data.get("compression"),
        )


# Type aliases for advanced configuration options
PartitionStrategyType = Literal["RANGE", "LIST", "HASH", "DATE"]
PartitionGranularityType = Literal["HOURLY", "DAILY", "MONTHLY", "YEARLY"]
SortKeyStyleType = Literal["COMPOUND", "INTERLEAVED", "AUTO"]
SortedIngestionModeType = Literal["off", "auto", "force"]
SortedIngestionMethodType = Literal["auto", "ctas", "z_order", "hilbert", "liquid_clustering", "vacuum_sort"]
DatabricksClusteringStrategyType = Literal["z_order", "liquid_clustering", "liquid_clustering_auto", "none"]
DatabricksPhysicalRenderingType = Literal[
    "databricks_z_order",
    "databricks_liquid_manual",
    "databricks_liquid_auto",
]


@dataclass
class PartitioningConfig:
    """Advanced partitioning configuration.

    Extends basic column-based partitioning with strategy and granularity
    options needed for platforms like BigQuery, Redshift, and Trino.

    Attributes:
        columns: List of partition columns.
        strategy: Partitioning strategy (RANGE, LIST, HASH, DATE). Default: RANGE.
        granularity: For DATE strategy, the time granularity. Default: None.
        bucket_count: For HASH strategy, number of buckets. Default: None.
        range_boundaries: For RANGE strategy, explicit boundary values. Default: None.
    """

    columns: list[TuningColumn]
    strategy: PartitionStrategyType = "RANGE"
    granularity: Optional[PartitionGranularityType] = None
    bucket_count: Optional[int] = None
    range_boundaries: Optional[list[Any]] = None

    def __post_init__(self) -> None:
        """Validate the partitioning configuration."""
        self._validate_strategy()
        self._validate_bucket_count()

    def _validate_strategy(self) -> None:
        """Validate the partitioning strategy."""
        valid_strategies = ("RANGE", "LIST", "HASH", "DATE")
        if self.strategy not in valid_strategies:
            raise ValueError(f"Invalid strategy: '{self.strategy}'. Must be one of {valid_strategies}.")

    def _validate_bucket_count(self) -> None:
        """Validate bucket count for HASH strategy."""
        if (
            self.strategy == "HASH"
            and self.bucket_count is not None
            and (not isinstance(self.bucket_count, int) or self.bucket_count <= 0)
        ):
            raise ValueError("bucket_count must be a positive integer for HASH strategy")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "columns": [col.to_dict() for col in self.columns],
        }

        # Only include non-default values
        if self.strategy != "RANGE":
            result["strategy"] = self.strategy
        if self.granularity is not None:
            result["granularity"] = self.granularity
        if self.bucket_count is not None:
            result["bucket_count"] = self.bucket_count
        if self.range_boundaries is not None:
            result["range_boundaries"] = self.range_boundaries

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PartitioningConfig":
        """Create from dictionary."""
        columns = [TuningColumn.from_dict(col) for col in data.get("columns", [])]
        return cls(
            columns=columns,
            strategy=data.get("strategy", "RANGE"),
            granularity=data.get("granularity"),
            bucket_count=data.get("bucket_count"),
            range_boundaries=data.get("range_boundaries"),
        )


@dataclass
class SortKeyConfig:
    """Advanced sort key configuration.

    Extends basic sorting with style options needed for platforms like Redshift.

    Attributes:
        columns: List of sort key columns.
        style: Sort key style (COMPOUND, INTERLEAVED, AUTO). Default: COMPOUND.
            - COMPOUND: Best for queries using all leading columns (Redshift default).
            - INTERLEAVED: Best for queries filtering on any column subset.
            - AUTO: Let the platform decide (Redshift AUTO).
    """

    columns: list[TuningColumn]
    style: SortKeyStyleType = "COMPOUND"

    def __post_init__(self) -> None:
        """Validate the sort key configuration."""
        self._validate_style()

    def _validate_style(self) -> None:
        """Validate the sort key style."""
        valid_styles = ("COMPOUND", "INTERLEAVED", "AUTO")
        if self.style not in valid_styles:
            raise ValueError(f"Invalid style: '{self.style}'. Must be one of {valid_styles}.")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "columns": [col.to_dict() for col in self.columns],
        }

        # Only include non-default values
        if self.style != "COMPOUND":
            result["style"] = self.style

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SortKeyConfig":
        """Create from dictionary."""
        columns = [TuningColumn.from_dict(col) for col in data.get("columns", [])]
        return cls(
            columns=columns,
            style=data.get("style", "COMPOUND"),
        )


@dataclass
class ClusteringConfig:
    """Advanced clustering configuration.

    Extends basic clustering with bucket count for hash-based clustering.

    Attributes:
        columns: List of clustering columns.
        bucket_count: Number of buckets for hash-based clustering. Default: None.
    """

    columns: list[TuningColumn]
    bucket_count: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate the clustering configuration."""
        if self.bucket_count is not None and (not isinstance(self.bucket_count, int) or self.bucket_count <= 0):
            raise ValueError("bucket_count must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "columns": [col.to_dict() for col in self.columns],
        }

        if self.bucket_count is not None:
            result["bucket_count"] = self.bucket_count

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClusteringConfig":
        """Create from dictionary."""
        columns = [TuningColumn.from_dict(col) for col in data.get("columns", [])]
        return cls(
            columns=columns,
            bucket_count=data.get("bucket_count"),
        )


@dataclass
class TableTuning:
    """Represents the complete tuning configuration for a database table.

    This dataclass holds all tuning configurations (partitioning, clustering,
    distribution, and sorting) for a single table, along with validation
    methods and serialization support.
    """

    table_name: str
    partitioning: Optional[list[TuningColumn]] = None
    clustering: Optional[list[TuningColumn]] = None
    distribution: Optional[list[TuningColumn]] = None
    sorting: Optional[list[TuningColumn]] = None

    def __post_init__(self) -> None:
        """Validate the table tuning configuration after initialization."""
        self._validate_table_name()
        self._validate_column_lists()
        self.validate()

    def _validate_table_name(self) -> None:
        """Validate the table name format.

        Raises:
            ValueError: If the table name is invalid
        """
        if not self.table_name:
            raise ValueError("Table name cannot be empty")

        if not isinstance(self.table_name, str):
            raise ValueError("Table name must be a string")

        # Check for valid SQL identifier format
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", self.table_name):
            raise ValueError(
                f"Invalid table name format: '{self.table_name}'. "
                "Table names must start with a letter or underscore and "
                "contain only letters, numbers, and underscores."
            )

    def _validate_column_lists(self) -> None:
        """Validate that all column lists contain valid TuningColumn objects."""
        for tuning_type, columns in self._get_tuning_columns().items():
            if columns is not None:
                for i, column in enumerate(columns):
                    if not isinstance(column, TuningColumn):
                        raise ValueError(f"{tuning_type} column at index {i} must be a TuningColumn instance")

    def _get_tuning_columns(self) -> dict[str, Optional[list[TuningColumn]]]:
        """Get a mapping of tuning types to their column lists."""
        return {
            "partitioning": self.partitioning,
            "clustering": self.clustering,
            "distribution": self.distribution,
            "sorting": self.sorting,
        }

    def validate(self) -> list[str]:
        """Validate the table tuning configuration for conflicts and issues.

        Returns:
            List of validation error messages (empty if no errors)
        """
        errors = []

        # Check for empty tuning (at least one tuning type should be specified)
        if not self.has_any_tuning():
            errors.append("Table tuning must specify at least one tuning configuration")

        # Check for duplicate column orders within each tuning type
        errors.extend(self._validate_column_orders())

        # Check for column conflicts between tuning types
        errors.extend(self._detect_column_conflicts())

        return errors

    def has_any_tuning(self) -> bool:
        """Check if any tuning configuration is specified.

        Returns:
            True if at least one tuning type has columns configured
        """
        return any(columns is not None and len(columns) > 0 for columns in self._get_tuning_columns().values())

    def _validate_column_orders(self) -> list[str]:
        """Validate that column orders are unique within each tuning type.

        Returns:
            List of validation error messages
        """
        errors = []

        for tuning_type, columns in self._get_tuning_columns().items():
            if columns is not None and len(columns) > 1:
                orders = [col.order for col in columns]
                if len(set(orders)) != len(orders):
                    duplicates = [order for order in set(orders) if orders.count(order) > 1]
                    errors.append(f"{tuning_type} has duplicate column orders: {duplicates}")

        return errors

    def _detect_column_conflicts(self) -> list[str]:
        """Detect conflicts between different tuning types.

        Returns:
            List of validation error messages
        """
        errors = []

        # Get all column names used in each tuning type
        tuning_columns = {}
        for tuning_type, columns in self._get_tuning_columns().items():
            if columns is not None:
                tuning_columns[tuning_type] = {col.name for col in columns}

        # Check for columns used in multiple tuning types
        all_columns = {}
        for tuning_type, column_names in tuning_columns.items():
            for col_name in column_names:
                if col_name not in all_columns:
                    all_columns[col_name] = []
                all_columns[col_name].append(tuning_type)

        # Report conflicts
        for col_name, tuning_types in all_columns.items():
            if len(tuning_types) > 1:
                errors.append(f"Column '{col_name}' is used in multiple tuning types: {tuning_types}")

        return errors

    def get_columns_by_type(self, tuning_type: TuningType) -> list[TuningColumn]:
        """Get columns for a specific tuning type.

        Args:
            tuning_type: The type of tuning to get columns for

        Returns:
            List of tuning columns for the specified type (empty if none)
        """
        type_mapping = {
            TuningType.PARTITIONING: self.partitioning,
            TuningType.CLUSTERING: self.clustering,
            TuningType.DISTRIBUTION: self.distribution,
            TuningType.SORTING: self.sorting,
        }

        columns = type_mapping.get(tuning_type)
        return columns if columns is not None else []

    def get_all_columns(self) -> set[str]:
        """Get all column names used in any tuning configuration.

        Returns:
            Set of all column names used in tuning
        """
        all_columns = set()
        for columns in self._get_tuning_columns().values():
            if columns is not None:
                all_columns.update(col.name for col in columns)
        return all_columns

    def to_dict(self) -> dict[str, Any]:
        """Convert the table tuning to a dictionary for serialization.

        Returns:
            Dictionary representation of the table tuning
        """
        result = {"table_name": self.table_name}

        for tuning_type, columns in self._get_tuning_columns().items():
            if columns is not None:
                result[tuning_type] = [col.to_dict() for col in columns]

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TableTuning":
        """Create a TableTuning from a dictionary.

        Args:
            data: Dictionary containing table tuning configuration

        Returns:
            New TableTuning instance

        Raises:
            ValueError: If the dictionary is missing required fields
        """
        if "table_name" not in data:
            raise ValueError("Missing required field: table_name")

        # Convert column dictionaries back to TuningColumn objects
        kwargs = {"table_name": data["table_name"]}

        for tuning_type in ["partitioning", "clustering", "distribution", "sorting"]:
            if tuning_type in data:
                kwargs[tuning_type] = [TuningColumn.from_dict(col_data) for col_data in data[tuning_type]]

        return cls(**kwargs)


@dataclass
class BenchmarkTunings:
    """Manages tuning configurations for all tables in a benchmark.

    This class serves as a container and manager for table tuning configurations
    across an entire benchmark, providing validation, conflict detection, and
    serialization capabilities.
    """

    benchmark_name: str
    table_tunings: dict[str, TableTuning] = field(default_factory=dict)
    # Schema constraint configuration
    enable_primary_keys: bool = True
    enable_foreign_keys: bool = True

    def __post_init__(self) -> None:
        """Validate the benchmark tunings configuration after initialization."""
        self._validate_benchmark_name()

    def _validate_benchmark_name(self) -> None:
        """Validate the benchmark name format.

        Raises:
            ValueError: If the benchmark name is invalid
        """
        if not self.benchmark_name:
            raise ValueError("Benchmark name cannot be empty")

        if not isinstance(self.benchmark_name, str):
            raise ValueError("Benchmark name must be a string")

    def add_table_tuning(self, table_tuning: TableTuning) -> None:
        """Add a table tuning configuration to the benchmark.

        Args:
            table_tuning: The table tuning configuration to add

        Raises:
            ValueError: If the table tuning is invalid or conflicts with existing ones
        """
        if not isinstance(table_tuning, TableTuning):
            raise ValueError("table_tuning must be a TableTuning instance")

        # Validate the table tuning
        errors = table_tuning.validate()
        if errors:
            raise ValueError(f"Invalid table tuning for '{table_tuning.table_name}': {errors}")

        # Check for conflicts with existing tunings
        if table_tuning.table_name in self.table_tunings:
            raise ValueError(
                f"Table tuning already exists for '{table_tuning.table_name}'. "
                "Use update_table_tuning() to modify existing tunings."
            )

        self.table_tunings[table_tuning.table_name] = table_tuning

    def update_table_tuning(self, table_tuning: TableTuning) -> None:
        """Update an existing table tuning configuration.

        Args:
            table_tuning: The updated table tuning configuration

        Raises:
            ValueError: If the table tuning is invalid
        """
        if not isinstance(table_tuning, TableTuning):
            raise ValueError("table_tuning must be a TableTuning instance")

        # Validate the table tuning
        errors = table_tuning.validate()
        if errors:
            raise ValueError(f"Invalid table tuning for '{table_tuning.table_name}': {errors}")

        self.table_tunings[table_tuning.table_name] = table_tuning

    def get_table_tuning(self, table_name: str) -> Optional[TableTuning]:
        """Get the tuning configuration for a specific table.

        Args:
            table_name: The name of the table

        Returns:
            The table tuning configuration, or None if not found
        """
        return self.table_tunings.get(table_name)

    def remove_table_tuning(self, table_name: str) -> bool:
        """Remove the tuning configuration for a specific table.

        Args:
            table_name: The name of the table

        Returns:
            True if the table tuning was removed, False if it didn't exist
        """
        if table_name in self.table_tunings:
            del self.table_tunings[table_name]
            return True
        return False

    def get_table_names(self) -> list[str]:
        """Get a list of all table names with tuning configurations.

        Returns:
            Sorted list of table names
        """
        return sorted(self.table_tunings.keys())

    def disable_primary_keys(self) -> None:
        """Disable primary key constraints for all tables."""
        self.enable_primary_keys = False

    def disable_foreign_keys(self) -> None:
        """Disable foreign key constraints for all tables."""
        self.enable_foreign_keys = False

    def enable_all_constraints(self) -> None:
        """Enable both primary key and foreign key constraints."""
        self.enable_primary_keys = True
        self.enable_foreign_keys = True

    def disable_all_constraints(self) -> None:
        """Disable both primary key and foreign key constraints."""
        self.enable_primary_keys = False
        self.enable_foreign_keys = False

    def get_constraint_status(self) -> dict[str, bool]:
        """Get the current constraint configuration status.

        Returns:
            Dictionary with constraint types and their enabled status
        """
        return {
            "primary_keys": self.enable_primary_keys,
            "foreign_keys": self.enable_foreign_keys,
        }

    def validate_all(self) -> dict[str, list[str]]:
        """Validate all table tuning configurations in the benchmark.

        Returns:
            Dictionary mapping table names to lists of validation errors
            (empty lists for tables with no errors)
        """
        validation_results = {}

        for table_name, table_tuning in self.table_tunings.items():
            validation_results[table_name] = table_tuning.validate()

        return validation_results

    def has_valid_tunings(self) -> bool:
        """Check if all table tunings are valid.

        Returns:
            True if all table tunings are valid
        """
        validation_results = self.validate_all()
        return all(len(errors) == 0 for errors in validation_results.values())

    def get_configuration_hash(self) -> str:
        """Generate a hash of the entire tuning configuration.

        This hash can be used to detect changes in tuning configuration
        and validate database compatibility.

        Returns:
            SHA-256 hash of the serialized tuning configuration
        """
        # Create a consistent serialization for hashing
        config_dict = self.to_dict()

        # Sort keys for consistent hashing
        import json

        config_json = json.dumps(config_dict, sort_keys=True, separators=(",", ":"))

        return hashlib.sha256(config_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert the benchmark tunings to a dictionary for serialization.

        Returns:
            Dictionary representation of the benchmark tunings
        """
        return {
            "benchmark_name": self.benchmark_name,
            "table_tunings": {
                table_name: table_tuning.to_dict() for table_name, table_tuning in self.table_tunings.items()
            },
            "enable_primary_keys": self.enable_primary_keys,
            "enable_foreign_keys": self.enable_foreign_keys,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkTunings":
        """Create a BenchmarkTunings from a dictionary.

        Args:
            data: Dictionary containing benchmark tunings configuration

        Returns:
            New BenchmarkTunings instance

        Raises:
            ValueError: If the dictionary is missing required fields
        """
        if "benchmark_name" not in data:
            raise ValueError("Missing required field: benchmark_name")

        # Extract constraint settings with defaults
        enable_primary_keys = data.get("enable_primary_keys", True)
        enable_foreign_keys = data.get("enable_foreign_keys", True)

        benchmark_tunings = cls(
            benchmark_name=data["benchmark_name"],
            enable_primary_keys=enable_primary_keys,
            enable_foreign_keys=enable_foreign_keys,
        )

        if "table_tunings" in data:
            for _table_name, table_data in data["table_tunings"].items():
                table_tuning = TableTuning.from_dict(table_data)
                benchmark_tunings.add_table_tuning(table_tuning)

        return benchmark_tunings

    def __len__(self) -> int:
        """Return the number of table tunings in the benchmark."""
        return len(self.table_tunings)

    def __contains__(self, table_name: str) -> bool:
        """Check if a table has tuning configuration."""
        return table_name in self.table_tunings

    def __iter__(self):
        """Iterate over table names with tuning configurations."""
        return iter(self.table_tunings)


@dataclass
class ConstraintConfiguration:
    """Base class for constraint configurations."""

    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {"enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConstraintConfiguration":
        """Create from dictionary."""
        return cls(enabled=data.get("enabled", True))


@dataclass
class PrimaryKeyConfiguration(ConstraintConfiguration):
    """Configuration for primary key constraints."""

    enforce_uniqueness: bool = True
    nullable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "enforce_uniqueness": self.enforce_uniqueness,
            "nullable": self.nullable,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PrimaryKeyConfiguration":
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            enforce_uniqueness=data.get("enforce_uniqueness", True),
            nullable=data.get("nullable", False),
        )


@dataclass
class ForeignKeyConfiguration(ConstraintConfiguration):
    """Configuration for foreign key constraints."""

    enforce_referential_integrity: bool = True
    on_delete_action: str = "RESTRICT"  # RESTRICT, CASCADE, SET NULL, SET DEFAULT
    on_update_action: str = "RESTRICT"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "enforce_referential_integrity": self.enforce_referential_integrity,
            "on_delete_action": self.on_delete_action,
            "on_update_action": self.on_update_action,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ForeignKeyConfiguration":
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            enforce_referential_integrity=data.get("enforce_referential_integrity", True),
            on_delete_action=data.get("on_delete_action", "RESTRICT"),
            on_update_action=data.get("on_update_action", "RESTRICT"),
        )


@dataclass
class UniqueConstraintConfiguration(ConstraintConfiguration):
    """Configuration for unique constraints."""

    ignore_nulls: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {"enabled": self.enabled, "ignore_nulls": self.ignore_nulls}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UniqueConstraintConfiguration":
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            ignore_nulls=data.get("ignore_nulls", False),
        )


@dataclass
class CheckConstraintConfiguration(ConstraintConfiguration):
    """Configuration for check constraints."""

    enforce_on_insert: bool = True
    enforce_on_update: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "enforce_on_insert": self.enforce_on_insert,
            "enforce_on_update": self.enforce_on_update,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckConstraintConfiguration":
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            enforce_on_insert=data.get("enforce_on_insert", True),
            enforce_on_update=data.get("enforce_on_update", True),
        )


@dataclass
class PlatformOptimizationConfiguration:
    """Configuration for platform-specific optimizations."""

    z_ordering_enabled: bool = False
    z_ordering_columns: list[str] = field(default_factory=list)
    liquid_clustering_enabled: bool = False
    liquid_clustering_columns: list[str] = field(default_factory=list)
    databricks_clustering_strategy: DatabricksClusteringStrategyType = "z_order"
    physical_rendering_id: Optional[DatabricksPhysicalRenderingType] = None
    sorted_ingestion_mode: SortedIngestionModeType = "off"
    sorted_ingestion_method: SortedIngestionMethodType = "auto"
    auto_optimize_enabled: bool = False
    auto_compact_enabled: bool = False
    bloom_filters_enabled: bool = False
    bloom_filter_columns: list[str] = field(default_factory=list)
    materialized_views_enabled: bool = False

    def __post_init__(self) -> None:
        """Validate strategy fields for deterministic tuning behavior."""
        valid_modes = {"off", "auto", "force"}
        valid_methods = {"auto", "ctas", "z_order", "hilbert", "liquid_clustering", "vacuum_sort"}
        valid_dbx_strategies = {"z_order", "liquid_clustering", "liquid_clustering_auto", "none"}
        valid_dbx_renderings = {"databricks_z_order", "databricks_liquid_manual", "databricks_liquid_auto"}

        if self.sorted_ingestion_mode not in valid_modes:
            raise ValueError(
                f"Invalid sorted_ingestion_mode: '{self.sorted_ingestion_mode}'. Must be one of {sorted(valid_modes)}."
            )
        if self.sorted_ingestion_method not in valid_methods:
            raise ValueError(
                f"Invalid sorted_ingestion_method: '{self.sorted_ingestion_method}'. "
                f"Must be one of {sorted(valid_methods)}."
            )
        if self.databricks_clustering_strategy not in valid_dbx_strategies:
            raise ValueError(
                f"Invalid databricks_clustering_strategy: '{self.databricks_clustering_strategy}'. "
                f"Must be one of {sorted(valid_dbx_strategies)}."
            )
        if self.physical_rendering_id is not None and self.physical_rendering_id not in valid_dbx_renderings:
            raise ValueError(
                f"Invalid physical_rendering_id: '{self.physical_rendering_id}'. "
                f"Must be one of {sorted(valid_dbx_renderings)}."
            )

        if self.sorted_ingestion_mode == "off" and self.sorted_ingestion_method != "auto":
            raise ValueError("sorted_ingestion_method must be 'auto' when sorted_ingestion_mode is 'off'")

        if self.liquid_clustering_columns and not self.liquid_clustering_enabled:
            raise ValueError("liquid_clustering_columns requires liquid_clustering_enabled=true")

        liquid_strategy = self.databricks_clustering_strategy in {"liquid_clustering", "liquid_clustering_auto"}
        liquid_requested = liquid_strategy or self.liquid_clustering_enabled or bool(self.liquid_clustering_columns)
        z_order_requested = self.z_ordering_enabled or bool(self.z_ordering_columns)

        if self.databricks_clustering_strategy == "none" and (
            self.liquid_clustering_enabled or self.liquid_clustering_columns or z_order_requested
        ):
            raise ValueError(
                "databricks_clustering_strategy='none' cannot be combined with liquid_clustering_enabled, "
                "liquid_clustering_columns, z_ordering_enabled, or z_ordering_columns"
            )
        if liquid_requested and z_order_requested:
            raise ValueError(
                "Databricks Liquid Clustering cannot be combined with z_ordering_enabled or z_ordering_columns; "
                "set z_ordering_enabled=false and remove z_ordering_columns, or use databricks_z_order."
            )
        if self.databricks_clustering_strategy == "liquid_clustering_auto" and self.liquid_clustering_columns:
            raise ValueError(
                "liquid_clustering_columns cannot be set with databricks_clustering_strategy='liquid_clustering_auto'; "
                "automatic Liquid Clustering uses CLUSTER BY AUTO and Databricks selects keys asynchronously."
            )
        if self.physical_rendering_id == "databricks_z_order" and liquid_requested:
            raise ValueError(
                "physical_rendering_id=databricks_z_order cannot be combined with Liquid Clustering fields"
            )
        if self.physical_rendering_id in {"databricks_liquid_manual", "databricks_liquid_auto"} and z_order_requested:
            raise ValueError(
                f"physical_rendering_id={self.physical_rendering_id} cannot be combined with ZORDER fields"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "z_ordering_enabled": self.z_ordering_enabled,
            "z_ordering_columns": self.z_ordering_columns,
            "liquid_clustering_enabled": self.liquid_clustering_enabled,
            "liquid_clustering_columns": self.liquid_clustering_columns,
            "databricks_clustering_strategy": self.databricks_clustering_strategy,
            "sorted_ingestion_mode": self.sorted_ingestion_mode,
            "sorted_ingestion_method": self.sorted_ingestion_method,
            "auto_optimize_enabled": self.auto_optimize_enabled,
            "auto_compact_enabled": self.auto_compact_enabled,
            "bloom_filters_enabled": self.bloom_filters_enabled,
            "bloom_filter_columns": self.bloom_filter_columns,
            "materialized_views_enabled": self.materialized_views_enabled,
        }
        if self.physical_rendering_id is not None:
            result["physical_rendering_id"] = self.physical_rendering_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlatformOptimizationConfiguration":
        """Create from dictionary."""
        sorted_ingestion_mode = data.get("sorted_ingestion_mode", data.get("deep_sort_mode", "off"))
        sorted_ingestion_method = data.get("sorted_ingestion_method", data.get("deep_sort_method", "auto"))
        strategy = data.get("databricks_clustering_strategy")
        if strategy is None and (data.get("liquid_clustering_enabled", False) or data.get("liquid_clustering_columns")):
            strategy = "liquid_clustering"
        if strategy is None:
            strategy = "z_order"
        return cls(
            z_ordering_enabled=data.get("z_ordering_enabled", False),
            z_ordering_columns=data.get("z_ordering_columns", []),
            liquid_clustering_enabled=data.get("liquid_clustering_enabled", False),
            liquid_clustering_columns=data.get("liquid_clustering_columns", []),
            databricks_clustering_strategy=strategy,
            physical_rendering_id=data.get("physical_rendering_id"),
            sorted_ingestion_mode=sorted_ingestion_mode,
            sorted_ingestion_method=sorted_ingestion_method,
            auto_optimize_enabled=data.get("auto_optimize_enabled", False),
            auto_compact_enabled=data.get("auto_compact_enabled", False),
            bloom_filters_enabled=data.get("bloom_filters_enabled", False),
            bloom_filter_columns=data.get("bloom_filter_columns", []),
            materialized_views_enabled=data.get("materialized_views_enabled", False),
        )


@dataclass
class UnifiedTuningConfiguration:
    """Unified configuration that consolidates all tuning options.

    This class provides a single interface for managing all types of database tunings:
    - Table-level performance tunings (partitioning, clustering, distribution, sorting)
    - Schema constraints (primary keys, foreign keys, unique constraints, check constraints)
    - Platform-specific optimizations (Z-ordering, auto-optimize, bloom filters, etc.)
    """

    # Schema constraints
    primary_keys: PrimaryKeyConfiguration = field(default_factory=PrimaryKeyConfiguration)
    foreign_keys: ForeignKeyConfiguration = field(default_factory=ForeignKeyConfiguration)
    unique_constraints: UniqueConstraintConfiguration = field(default_factory=UniqueConstraintConfiguration)
    check_constraints: CheckConstraintConfiguration = field(default_factory=CheckConstraintConfiguration)

    # Platform-specific optimizations
    platform_optimizations: PlatformOptimizationConfiguration = field(default_factory=PlatformOptimizationConfiguration)

    # Table tunings
    table_tunings: dict[str, TableTuning] = field(default_factory=dict)

    def enable_all_constraints(self) -> None:
        """Enable all schema constraints."""
        self.primary_keys.enabled = True
        self.foreign_keys.enabled = True
        self.unique_constraints.enabled = True
        self.check_constraints.enabled = True

    def disable_all_constraints(self) -> None:
        """Disable all schema constraints."""
        self.primary_keys.enabled = False
        self.foreign_keys.enabled = False
        self.unique_constraints.enabled = False
        self.check_constraints.enabled = False

    def enable_primary_keys(self) -> None:
        """Enable primary key constraints."""
        self.primary_keys.enabled = True

    def disable_primary_keys(self) -> None:
        """Disable primary key constraints."""
        self.primary_keys.enabled = False

    def enable_foreign_keys(self) -> None:
        """Enable foreign key constraints."""
        self.foreign_keys.enabled = True

    def disable_foreign_keys(self) -> None:
        """Disable foreign key constraints."""
        self.foreign_keys.enabled = False

    def enable_platform_optimization(self, optimization_type: TuningType, **kwargs) -> None:
        """Enable a specific platform optimization.

        Args:
            optimization_type: The type of optimization to enable
            **kwargs: Additional configuration parameters
        """
        if optimization_type == TuningType.Z_ORDERING:
            self.platform_optimizations.z_ordering_enabled = True
            if "columns" in kwargs:
                self.platform_optimizations.z_ordering_columns = kwargs["columns"]
        elif optimization_type == TuningType.LIQUID_CLUSTERING:
            self.platform_optimizations.liquid_clustering_enabled = True
            self.platform_optimizations.databricks_clustering_strategy = "liquid_clustering"
            if "columns" in kwargs:
                self.platform_optimizations.liquid_clustering_columns = kwargs["columns"]
        elif optimization_type == TuningType.AUTO_OPTIMIZE:
            self.platform_optimizations.auto_optimize_enabled = True
        elif optimization_type == TuningType.AUTO_COMPACT:
            self.platform_optimizations.auto_compact_enabled = True
        elif optimization_type == TuningType.BLOOM_FILTERS:
            self.platform_optimizations.bloom_filters_enabled = True
            if "columns" in kwargs:
                self.platform_optimizations.bloom_filter_columns = kwargs["columns"]
        elif optimization_type == TuningType.MATERIALIZED_VIEWS:
            self.platform_optimizations.materialized_views_enabled = True

    def disable_platform_optimization(self, optimization_type: TuningType) -> None:
        """Disable a specific platform optimization.

        Args:
            optimization_type: The type of optimization to disable
        """
        if optimization_type == TuningType.Z_ORDERING:
            self.platform_optimizations.z_ordering_enabled = False
        elif optimization_type == TuningType.LIQUID_CLUSTERING:
            self.platform_optimizations.liquid_clustering_enabled = False
        elif optimization_type == TuningType.AUTO_OPTIMIZE:
            self.platform_optimizations.auto_optimize_enabled = False
        elif optimization_type == TuningType.AUTO_COMPACT:
            self.platform_optimizations.auto_compact_enabled = False
        elif optimization_type == TuningType.BLOOM_FILTERS:
            self.platform_optimizations.bloom_filters_enabled = False
        elif optimization_type == TuningType.MATERIALIZED_VIEWS:
            self.platform_optimizations.materialized_views_enabled = False

    _CONSTRAINT_CHECKS = [
        ("primary_keys", TuningType.PRIMARY_KEYS),
        ("foreign_keys", TuningType.FOREIGN_KEYS),
        ("unique_constraints", TuningType.UNIQUE_CONSTRAINTS),
        ("check_constraints", TuningType.CHECK_CONSTRAINTS),
    ]
    _OPT_CHECKS = [
        ("z_ordering_enabled", TuningType.Z_ORDERING),
        ("liquid_clustering_enabled", TuningType.LIQUID_CLUSTERING),
        ("auto_optimize_enabled", TuningType.AUTO_OPTIMIZE),
        ("auto_compact_enabled", TuningType.AUTO_COMPACT),
        ("bloom_filters_enabled", TuningType.BLOOM_FILTERS),
        ("materialized_views_enabled", TuningType.MATERIALIZED_VIEWS),
    ]
    _TABLE_TUNING_CHECKS = [
        ("partitioning", TuningType.PARTITIONING),
        ("clustering", TuningType.CLUSTERING),
        ("distribution", TuningType.DISTRIBUTION),
        ("sorting", TuningType.SORTING),
    ]

    def get_enabled_tuning_types(self) -> set[TuningType]:
        """Get all currently enabled tuning types.

        Returns:
            Set of enabled TuningType values
        """
        enabled_types: set[TuningType] = set()

        for attr, tt in self._CONSTRAINT_CHECKS:
            if getattr(self, attr).enabled:
                enabled_types.add(tt)
        for attr, tt in self._OPT_CHECKS:
            if getattr(self.platform_optimizations, attr):
                enabled_types.add(tt)
        for table_tuning in self.table_tunings.values():
            for attr, tt in self._TABLE_TUNING_CHECKS:
                if getattr(table_tuning, attr):
                    enabled_types.add(tt)

        return enabled_types

    def validate_for_platform(self, platform: str) -> list[str]:
        """Validate configuration against platform capabilities.

        Args:
            platform: Target platform name

        Returns:
            List of validation error messages
        """
        errors = []
        enabled_types = self.get_enabled_tuning_types()

        for tuning_type in enabled_types:
            if not tuning_type.is_compatible_with_platform(platform):
                errors.append(f"Tuning type '{tuning_type.value}' is not supported by platform '{platform}'")

        platform_key = platform.lower().replace("_", "-")
        if platform_key == "databricks":
            errors.extend(self._validate_databricks_effective_layout())

        return errors

    def _validate_databricks_effective_layout(self) -> list[str]:
        """Validate Databricks layout combinations that require the full tuning config."""
        errors: list[str] = []
        try:
            self.platform_optimizations.__post_init__()
        except ValueError as exc:
            errors.append(str(exc))

        strategy = self.platform_optimizations.databricks_clustering_strategy
        liquid_requested = (
            strategy in {"liquid_clustering", "liquid_clustering_auto"}
            or self.platform_optimizations.liquid_clustering_enabled
            or bool(self.platform_optimizations.liquid_clustering_columns)
            or self.platform_optimizations.physical_rendering_id
            in {"databricks_liquid_manual", "databricks_liquid_auto"}
        )
        if not liquid_requested:
            return errors

        partitioned_tables = sorted(
            table_name for table_name, table_tuning in self.table_tunings.items() if table_tuning.partitioning
        )
        if partitioned_tables:
            errors.append(
                "Databricks Liquid Clustering is incompatible with per-table partitioning; "
                f"move partition columns to Liquid clustering intent or use databricks_z_order. Tables: "
                f"{', '.join(partitioned_tables)}"
            )

        distributed_tables = sorted(
            table_name for table_name, table_tuning in self.table_tunings.items() if table_tuning.distribution
        )
        if distributed_tables:
            errors.append(
                "Databricks Liquid Clustering has no user-managed distribution key; "
                f"fold distribution candidates into clustering intent or use databricks_z_order. Tables: "
                f"{', '.join(distributed_tables)}"
            )

        if strategy == "liquid_clustering":
            oversized_tables = sorted(
                table_name
                for table_name, table_tuning in self.table_tunings.items()
                if table_tuning.clustering and len(table_tuning.clustering) > 4
            )
            if oversized_tables:
                errors.append(
                    "Databricks manual Liquid Clustering supports at most four clustering keys per table; "
                    f"use databricks_liquid_auto or reduce clustering columns. Tables: {', '.join(oversized_tables)}"
                )

        return errors

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "primary_keys": self.primary_keys.to_dict(),
            "foreign_keys": self.foreign_keys.to_dict(),
            "unique_constraints": self.unique_constraints.to_dict(),
            "check_constraints": self.check_constraints.to_dict(),
            "platform_optimizations": self.platform_optimizations.to_dict(),
            "table_tunings": {
                table_name: table_tuning.to_dict() for table_name, table_tuning in self.table_tunings.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UnifiedTuningConfiguration":
        """Create from dictionary.

        Args:
            data: Dictionary containing configuration data

        Returns:
            New UnifiedTuningConfiguration instance
        """
        instance = cls()

        # Load constraint configurations
        if "primary_keys" in data:
            instance.primary_keys = PrimaryKeyConfiguration.from_dict(data["primary_keys"])
        if "foreign_keys" in data:
            instance.foreign_keys = ForeignKeyConfiguration.from_dict(data["foreign_keys"])
        if "unique_constraints" in data:
            instance.unique_constraints = UniqueConstraintConfiguration.from_dict(data["unique_constraints"])
        if "check_constraints" in data:
            instance.check_constraints = CheckConstraintConfiguration.from_dict(data["check_constraints"])

        # Load platform optimizations
        if "platform_optimizations" in data:
            instance.platform_optimizations = PlatformOptimizationConfiguration.from_dict(
                data["platform_optimizations"]
            )

        # Load table tunings
        if "table_tunings" in data:
            for table_name, table_data in data["table_tunings"].items():
                instance.table_tunings[table_name] = TableTuning.from_dict(table_data)

        return instance

"""DataFrame write-time physical layout configuration.

This module defines configuration classes for controlling the physical layout
of data when DataFrame platforms write to Parquet files. Unlike runtime tuning
(parallelism, memory), these settings affect the output file structure.

Key Concepts:
- **Partitioning**: Hive-style directory partitioning (year=2024/month=01/)
- **Sorting**: Physical row order within files (improves compression & scans)
- **Row Groups**: Parquet row group sizing (affects scan granularity)
- **Repartitioning**: Number of output files (affects parallelism)

Platform Compatibility:
| Platform | Partition | Sort | Repartition | Row Groups |
|----------|-----------|------|-------------|------------|
| Polars   | No        | Yes  | No          | Yes        |
| Pandas   | No        | Yes  | No          | Yes        |
| Dask     | Yes       | No   | Yes         | Yes        |
| PySpark  | Yes       | Yes  | Yes         | Yes        |
| cuDF     | No        | Yes  | No          | Yes        |

Example:
    >>> from benchbox.core.dataframe.tuning.write_config import (
    ...     DataFrameWriteConfiguration,
    ...     SortColumn,
    ... )
    >>> config = DataFrameWriteConfiguration(
    ...     sort_by=[
    ...         SortColumn(name="l_shipdate", order="asc"),
    ...         SortColumn(name="l_orderkey", order="asc"),
    ...     ],
    ...     row_group_size=1_000_000,
    ...     compression="zstd",
    ... )

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

logger = logging.getLogger(__name__)


class DataFrameWriteTuningType(str, Enum):
    """Tuning types for DataFrame write operations.

    These map to physical layout options that affect file structure
    rather than runtime execution.
    """

    PARTITION_BY = "partition_by"  # Hive-style partitioning
    SORT_BY = "sort_by"  # Physical row ordering
    ROW_GROUP_SIZE = "row_group_size"  # Parquet row group size
    REPARTITION = "repartition"  # Number of output files
    COMPRESSION = "compression"  # Compression codec
    DICTIONARY_ENCODING = "dictionary_encoding"  # Column encoding
    DATA_PAGE_VERSION = "data_page_version"  # Parquet data page version


class PartitionStrategy(str, Enum):
    """Partitioning strategies for Hive-style directories.

    Controls how partition values are organized into directories.
    """

    VALUE = "value"  # Direct value (column=value/)
    DATE_YEAR = "date_year"  # Year extraction (year=2024/)
    DATE_MONTH = "date_month"  # Year/month (year=2024/month=01/)
    DATE_DAY = "date_day"  # Year/month/day


# Type alias for sort order
SortOrder = Literal["asc", "desc"]


@dataclass
class SortColumn:
    """Specification for a sort column.

    Attributes:
        name: Column name to sort by.
        order: Sort order ("asc" or "desc").
    """

    name: str
    order: SortOrder = "asc"

    def __post_init__(self) -> None:
        """Validate sort column configuration."""
        if not self.name:
            raise ValueError("Column name cannot be empty")
        if self.order not in ("asc", "desc"):
            raise ValueError(f"Invalid sort order: {self.order}. Must be 'asc' or 'desc'")

    def to_dict(self) -> dict[str, str]:
        """Serialize to dictionary."""
        return {"name": self.name, "order": self.order}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SortColumn:
        """Deserialize from dictionary."""
        return cls(
            name=data["name"],
            order=data.get("order", "asc"),
        )


@dataclass
class PartitionColumn:
    """Specification for a partition column.

    Attributes:
        name: Column name to partition by.
        strategy: How to extract partition values from the column.
    """

    name: str
    strategy: PartitionStrategy = PartitionStrategy.VALUE

    def __post_init__(self) -> None:
        """Validate partition column configuration."""
        if not self.name:
            raise ValueError("Column name cannot be empty")

    def to_dict(self) -> dict[str, str]:
        """Serialize to dictionary."""
        return {"name": self.name, "strategy": self.strategy.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PartitionColumn:
        """Deserialize from dictionary."""
        strategy = data.get("strategy", "value")
        return cls(
            name=data["name"],
            strategy=PartitionStrategy(strategy) if isinstance(strategy, str) else strategy,
        )


# Supported compression codecs
CompressionCodec = Literal["none", "snappy", "gzip", "zstd", "lz4", "brotli"]


@dataclass
class DataFrameWriteConfiguration:
    """Configuration for DataFrame write-time physical layout.

    This class controls how data is physically organized when DataFrame
    platforms write to Parquet files. Unlike runtime tuning (threads, memory),
    these settings affect the output file structure and downstream query
    performance.

    Attributes:
        partition_by: Columns for Hive-style directory partitioning.
            Creates directories like `year=2024/month=01/`.
            Supported: Dask, PySpark.
        sort_by: Columns for physical row ordering within files.
            Improves compression and enables skip-scanning.
            Supported: All platforms (via sort before write).
        row_group_size: Rows per Parquet row group.
            Affects compression ratio and scan granularity.
            Default: 1,000,000 (1M rows).
        target_file_size_mb: Target size per output file.
            Platforms may split or combine data accordingly.
        repartition_count: Number of output files.
            Supported: Dask (repartition), PySpark.
        compression: Compression codec.
            Options: "none", "snappy", "gzip", "zstd", "lz4", "brotli".
        compression_level: Codec-specific compression level.
            zstd: 1-22 (default 3), gzip: 1-9 (default 6).
        dictionary_columns: Columns to force dictionary encoding.
            Useful for low-cardinality string columns.
        skip_dictionary_columns: Columns to skip dictionary encoding.
            Useful for high-cardinality ID columns.
        data_page_version: Parquet data page serialization version.
            "1.0" (default) compresses levels and values together.
            "2.0" stores levels separately, enabling page-level skipping.
    """

    partition_by: list[PartitionColumn] = field(default_factory=list)
    sort_by: list[SortColumn] = field(default_factory=list)
    row_group_size: int | None = None
    target_file_size_mb: int | None = None
    repartition_count: int | None = None
    compression: CompressionCodec = "zstd"
    compression_level: int | None = None
    dictionary_columns: list[str] = field(default_factory=list)
    skip_dictionary_columns: list[str] = field(default_factory=list)
    data_page_version: Literal["1.0", "2.0"] | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.row_group_size is not None and self.row_group_size < 1:
            raise ValueError("row_group_size must be >= 1")
        if self.target_file_size_mb is not None and self.target_file_size_mb < 1:
            raise ValueError("target_file_size_mb must be >= 1")
        if self.repartition_count is not None and self.repartition_count < 1:
            raise ValueError("repartition_count must be >= 1")
        if self.compression_level is not None:
            self._validate_compression_level()

    def _validate_compression_level(self) -> None:
        """Validate compression level against codec."""
        if self.compression_level is None:
            return

        limits = {
            "zstd": (1, 22),
            "gzip": (1, 9),
            "brotli": (0, 11),
            "lz4": (0, 16),
            "snappy": None,  # No level
            "none": None,
        }

        limit = limits.get(self.compression)
        if limit is None:
            logger.warning(
                f"Compression codec '{self.compression}' does not support "
                f"compression_level (level {self.compression_level} ignored)"
            )
        elif not limit[0] <= self.compression_level <= limit[1]:
            raise ValueError(
                f"compression_level {self.compression_level} out of range for "
                f"{self.compression} (valid: {limit[0]}-{limit[1]})"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for YAML/JSON export.

        Only includes non-default values to keep output concise.
        """
        result: dict[str, Any] = {}

        if self.partition_by:
            result["partition_by"] = [p.to_dict() for p in self.partition_by]
        if self.sort_by:
            result["sort_by"] = [s.to_dict() for s in self.sort_by]
        if self.row_group_size is not None:
            result["row_group_size"] = self.row_group_size
        if self.target_file_size_mb is not None:
            result["target_file_size_mb"] = self.target_file_size_mb
        if self.repartition_count is not None:
            result["repartition_count"] = self.repartition_count
        if self.compression != "zstd":
            result["compression"] = self.compression
        if self.compression_level is not None:
            result["compression_level"] = self.compression_level
        if self.dictionary_columns:
            result["dictionary_columns"] = self.dictionary_columns
        if self.skip_dictionary_columns:
            result["skip_dictionary_columns"] = self.skip_dictionary_columns
        if self.data_page_version is not None:
            result["data_page_version"] = self.data_page_version

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataFrameWriteConfiguration:
        """Deserialize from dictionary.

        Args:
            data: Dictionary containing write configuration.

        Returns:
            DataFrameWriteConfiguration instance.
        """
        partition_by = []
        for p in data.get("partition_by", []):
            if isinstance(p, str):
                partition_by.append(PartitionColumn(name=p))
            else:
                partition_by.append(PartitionColumn.from_dict(p))

        sort_by = []
        for s in data.get("sort_by", []):
            if isinstance(s, str):
                sort_by.append(SortColumn(name=s))
            elif isinstance(s, dict):
                sort_by.append(SortColumn.from_dict(s))
            else:
                sort_by.append(s)

        return cls(
            partition_by=partition_by,
            sort_by=sort_by,
            row_group_size=data.get("row_group_size"),
            target_file_size_mb=data.get("target_file_size_mb"),
            repartition_count=data.get("repartition_count"),
            compression=data.get("compression", "zstd"),
            compression_level=data.get("compression_level"),
            dictionary_columns=data.get("dictionary_columns", []),
            skip_dictionary_columns=data.get("skip_dictionary_columns", []),
            data_page_version=data.get("data_page_version"),
        )

    def is_default(self) -> bool:
        """Check if all values are at their defaults."""
        return (
            not self.partition_by
            and not self.sort_by
            and self.row_group_size is None
            and self.target_file_size_mb is None
            and self.repartition_count is None
            and self.compression == "zstd"
            and self.compression_level is None
            and not self.dictionary_columns
            and not self.skip_dictionary_columns
            and self.data_page_version is None
        )

    def get_enabled_types(self) -> set[DataFrameWriteTuningType]:
        """Get the set of write tuning types that are configured.

        Returns:
            Set of DataFrameWriteTuningType values with non-default config.
        """
        enabled: set[DataFrameWriteTuningType] = set()

        if self.partition_by:
            enabled.add(DataFrameWriteTuningType.PARTITION_BY)
        if self.sort_by:
            enabled.add(DataFrameWriteTuningType.SORT_BY)
        if self.row_group_size is not None:
            enabled.add(DataFrameWriteTuningType.ROW_GROUP_SIZE)
        if self.repartition_count is not None:
            enabled.add(DataFrameWriteTuningType.REPARTITION)
        if self.compression != "zstd" or self.compression_level is not None:
            enabled.add(DataFrameWriteTuningType.COMPRESSION)
        if self.dictionary_columns or self.skip_dictionary_columns:
            enabled.add(DataFrameWriteTuningType.DICTIONARY_ENCODING)
        if self.data_page_version is not None:
            enabled.add(DataFrameWriteTuningType.DATA_PAGE_VERSION)

        return enabled


# Platform capability matrix for write options
PLATFORM_WRITE_CAPABILITIES: dict[str, dict[str, bool]] = {
    "polars": {
        "partition_by": False,
        "sort_by": True,
        "row_group_size": True,
        "repartition_count": False,
        "compression": True,
        "dictionary_encoding": True,
    },
    "pandas": {
        "partition_by": False,
        "sort_by": True,
        "row_group_size": True,
        "repartition_count": False,
        "compression": True,
        "dictionary_encoding": True,
    },
    "dask": {
        "partition_by": True,
        "sort_by": False,  # Limited - requires shuffle
        "row_group_size": True,
        "repartition_count": True,
        "compression": True,
        "dictionary_encoding": True,
    },
    "pyspark": {
        "partition_by": True,
        "sort_by": True,
        "row_group_size": True,
        "repartition_count": True,
        "compression": True,
        "dictionary_encoding": True,
    },
    "cudf": {
        "partition_by": False,
        "sort_by": True,
        "row_group_size": True,
        "repartition_count": False,
        "compression": True,
        "dictionary_encoding": True,
    },
}


def get_platform_write_capabilities(platform: str) -> dict[str, bool]:
    """Get write capabilities for a DataFrame platform.

    Args:
        platform: Platform name (e.g., "polars", "dask").

    Returns:
        Dictionary mapping capability names to boolean support status.
    """
    return PLATFORM_WRITE_CAPABILITIES.get(
        platform.lower(),
        # Default: assume basic capabilities
        {
            "partition_by": False,
            "sort_by": True,
            "row_group_size": True,
            "repartition_count": False,
            "compression": True,
            "dictionary_encoding": True,
        },
    )


def validate_write_config_for_platform(
    config: DataFrameWriteConfiguration,
    platform: str,
) -> list[str]:
    """Validate write configuration against platform capabilities.

    Args:
        config: Write configuration to validate.
        platform: Target platform name.

    Returns:
        List of warning messages for unsupported options.
    """
    warnings: list[str] = []
    capabilities = get_platform_write_capabilities(platform)

    if config.partition_by and not capabilities.get("partition_by"):
        warnings.append(
            f"Platform '{platform}' does not support partitioned writes. "
            f"Partition columns will be ignored: {[p.name for p in config.partition_by]}"
        )

    if config.sort_by and not capabilities.get("sort_by"):
        warnings.append(
            f"Platform '{platform}' has limited sort support. "
            f"Sort may be slow or ignored: {[s.name for s in config.sort_by]}"
        )

    if config.repartition_count is not None and not capabilities.get("repartition_count"):
        warnings.append(
            f"Platform '{platform}' does not support repartitioning. "
            f"repartition_count={config.repartition_count} will be ignored."
        )

    return warnings


__all__ = [
    "CompressionCodec",
    "DataFrameWriteConfiguration",
    "DataFrameWriteTuningType",
    "PartitionColumn",
    "PartitionStrategy",
    "PLATFORM_WRITE_CAPABILITIES",
    "SortColumn",
    "SortOrder",
    "get_platform_write_capabilities",
    "validate_write_config_for_platform",
]

# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

logger = logging.getLogger(__name__)


class DataFrameWriteTuningType(str, Enum):
    PARTITION_BY = "partition_by"
    SORT_BY = "sort_by"
    ROW_GROUP_SIZE = "row_group_size"
    REPARTITION = "repartition"
    COMPRESSION = "compression"
    DICTIONARY_ENCODING = "dictionary_encoding"
    DATA_PAGE_VERSION = "data_page_version"


class PartitionStrategy(str, Enum):
    VALUE = "value"
    DATE_YEAR = "date_year"
    DATE_MONTH = "date_month"
    DATE_DAY = "date_day"


SortOrder = Literal["asc", "desc"]


@dataclass
class SortColumn:
    name: str
    order: SortOrder = "asc"

    def __post_init__(self) -> None:

        if not self.name:
            raise ValueError("Column name cannot be empty")
        if self.order not in ("asc", "desc"):
            raise ValueError(f"Invalid sort order: {self.order}. Must be 'asc' or 'desc'")

    def to_dict(self) -> dict[str, str]:

        return {"name": self.name, "order": self.order}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SortColumn:

        return cls(
            name=data["name"],
            order=data.get("order", "asc"),
        )


@dataclass
class PartitionColumn:
    name: str
    strategy: PartitionStrategy = PartitionStrategy.VALUE

    def __post_init__(self) -> None:

        if not self.name:
            raise ValueError("Column name cannot be empty")

    def to_dict(self) -> dict[str, str]:

        return {"name": self.name, "strategy": self.strategy.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PartitionColumn:

        strategy = data.get("strategy", "value")
        return cls(
            name=data["name"],
            strategy=PartitionStrategy(strategy) if isinstance(strategy, str) else strategy,
        )


CompressionCodec = Literal["none", "snappy", "gzip", "zstd", "lz4", "brotli"]


@dataclass
class DataFrameWriteConfiguration:
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

        if self.row_group_size is not None and self.row_group_size < 1:
            raise ValueError("row_group_size must be >= 1")
        if self.target_file_size_mb is not None and self.target_file_size_mb < 1:
            raise ValueError("target_file_size_mb must be >= 1")
        if self.repartition_count is not None and self.repartition_count < 1:
            raise ValueError("repartition_count must be >= 1")
        if self.compression_level is not None:
            self._validate_compression_level()

    def _validate_compression_level(self) -> None:

        if self.compression_level is None:
            return

        limits = {
            "zstd": (1, 22),
            "gzip": (1, 9),
            "brotli": (0, 11),
            "lz4": (0, 16),
            "snappy": None,
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
        "sort_by": False,
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

    return PLATFORM_WRITE_CAPABILITIES.get(
        platform.lower(),
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

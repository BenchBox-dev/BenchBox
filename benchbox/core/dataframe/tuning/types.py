"""DataFrame tuning type definitions.

This module defines the DataFrameTuningType enum that represents the different
types of tuning options available for DataFrame platforms.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from enum import Enum


class DataFrameTuningType(Enum):
    """Enumeration of supported DataFrame tuning types.

    This enum defines the different types of runtime optimizations that can be
    applied to DataFrame adapters across different platforms.

    Unlike SQL tuning types (which affect schema/DDL), DataFrame tuning types
    affect runtime execution parameters, memory management, and parallelism.
    """

    # Parallelism settings
    THREAD_COUNT = "thread_count"
    WORKER_COUNT = "worker_count"
    THREADS_PER_WORKER = "threads_per_worker"

    # Memory management
    MEMORY_LIMIT = "memory_limit"
    CHUNK_SIZE = "chunk_size"
    SPILL_TO_DISK = "spill_to_disk"
    RECHUNK = "rechunk"

    # Execution mode
    STREAMING_MODE = "streaming_mode"
    ENGINE_AFFINITY = "engine_affinity"
    LAZY_EVALUATION = "lazy_evaluation"

    # Data type optimization
    DTYPE_BACKEND = "dtype_backend"
    STRING_CACHE = "string_cache"

    # I/O optimization
    MEMORY_POOL = "memory_pool"
    MEMORY_MAP = "memory_map"
    PRE_BUFFER = "pre_buffer"
    ROW_GROUP_SIZE = "row_group_size"

    # GPU settings (cuDF)
    GPU_DEVICE = "gpu_device"
    GPU_SPILL_TO_HOST = "gpu_spill_to_host"
    GPU_POOL_TYPE = "gpu_pool_type"

    def __str__(self) -> str:
        """Return the string representation of the tuning type."""
        return self.value

    @classmethod
    def from_string(cls, value: str) -> "DataFrameTuningType":
        """Create a DataFrameTuningType from a string value.

        Args:
            value: The string representation of the tuning type

        Returns:
            The corresponding DataFrameTuningType enum value

        Raises:
            ValueError: If the value is not a valid tuning type
        """
        value_lower = value.lower()
        for tuning_type in cls:
            if tuning_type.value == value_lower:
                return tuning_type
        raise ValueError(f"Invalid DataFrame tuning type: {value}")

    def is_compatible_with_platform(self, platform: str) -> bool:
        """Check if this tuning type is compatible with the given platform.

        Args:
            platform: The name of the DataFrame platform (e.g., 'polars', 'pandas')

        Returns:
            True if the tuning type is supported by the platform
        """
        platform_lower = platform.lower()

        # Normalize platform names (handle -df suffix)
        if platform_lower.endswith("-df"):
            platform_lower = platform_lower[:-3]

        return self in _PLATFORM_COMPATIBILITY.get(platform_lower, set())

    @classmethod
    def get_platform_supported_types(cls, platform: str) -> set["DataFrameTuningType"]:
        """Get all tuning types supported by a platform.

        Args:
            platform: The name of the DataFrame platform

        Returns:
            Set of supported DataFrameTuningType values
        """
        platform_lower = platform.lower()
        if platform_lower.endswith("-df"):
            platform_lower = platform_lower[:-3]

        return _PLATFORM_COMPATIBILITY.get(platform_lower, set()).copy()


# Platform compatibility matrix
# Maps platform names to sets of supported tuning types
_PLATFORM_COMPATIBILITY: dict[str, set[DataFrameTuningType]] = {
    "datafusion": {
        # These are applied to SessionConfig as target partitions and record
        # batch size when the lazy session context is materialized.
        DataFrameTuningType.THREAD_COUNT,
        DataFrameTuningType.CHUNK_SIZE,
    },
    "polars": {
        DataFrameTuningType.THREAD_COUNT,
        DataFrameTuningType.CHUNK_SIZE,
        DataFrameTuningType.RECHUNK,
        DataFrameTuningType.STREAMING_MODE,
        DataFrameTuningType.ENGINE_AFFINITY,
        DataFrameTuningType.LAZY_EVALUATION,
        DataFrameTuningType.STRING_CACHE,
        DataFrameTuningType.MEMORY_POOL,  # Via PyArrow backend
        DataFrameTuningType.ROW_GROUP_SIZE,
    },
    "pandas": {
        DataFrameTuningType.CHUNK_SIZE,
        DataFrameTuningType.DTYPE_BACKEND,
        DataFrameTuningType.STRING_CACHE,  # Via category dtype
        DataFrameTuningType.MEMORY_POOL,  # Via PyArrow backend
        DataFrameTuningType.MEMORY_MAP,
        DataFrameTuningType.PRE_BUFFER,
        DataFrameTuningType.ROW_GROUP_SIZE,
    },
    "dask": {
        DataFrameTuningType.WORKER_COUNT,
        DataFrameTuningType.THREADS_PER_WORKER,
        DataFrameTuningType.MEMORY_LIMIT,
        DataFrameTuningType.CHUNK_SIZE,
        DataFrameTuningType.SPILL_TO_DISK,
        DataFrameTuningType.LAZY_EVALUATION,
        DataFrameTuningType.DTYPE_BACKEND,
        DataFrameTuningType.MEMORY_MAP,
        DataFrameTuningType.PRE_BUFFER,
    },
    "modin": {
        DataFrameTuningType.THREAD_COUNT,  # MODIN_CPUS
        DataFrameTuningType.WORKER_COUNT,  # NPartitions
        DataFrameTuningType.ENGINE_AFFINITY,  # ray/dask
        DataFrameTuningType.DTYPE_BACKEND,
        DataFrameTuningType.STRING_CACHE,
        DataFrameTuningType.MEMORY_MAP,
    },
    "cudf": {
        DataFrameTuningType.STRING_CACHE,
        DataFrameTuningType.GPU_DEVICE,
        DataFrameTuningType.GPU_SPILL_TO_HOST,
        DataFrameTuningType.GPU_POOL_TYPE,
        DataFrameTuningType.ROW_GROUP_SIZE,
    },
}


def get_all_platforms() -> list[str]:
    """Get list of all supported DataFrame platforms.

    Returns:
        List of platform names
    """
    return list(_PLATFORM_COMPATIBILITY.keys())

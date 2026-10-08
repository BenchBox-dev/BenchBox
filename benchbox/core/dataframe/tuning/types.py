# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from enum import Enum


class DataFrameTuningType(Enum):
    THREAD_COUNT = "thread_count"
    WORKER_COUNT = "worker_count"
    THREADS_PER_WORKER = "threads_per_worker"

    MEMORY_LIMIT = "memory_limit"
    CHUNK_SIZE = "chunk_size"
    SPILL_TO_DISK = "spill_to_disk"
    RECHUNK = "rechunk"

    STREAMING_MODE = "streaming_mode"
    ENGINE_AFFINITY = "engine_affinity"
    LAZY_EVALUATION = "lazy_evaluation"

    DTYPE_BACKEND = "dtype_backend"
    STRING_CACHE = "string_cache"

    MEMORY_POOL = "memory_pool"
    MEMORY_MAP = "memory_map"
    PRE_BUFFER = "pre_buffer"
    ROW_GROUP_SIZE = "row_group_size"

    GPU_DEVICE = "gpu_device"
    GPU_SPILL_TO_HOST = "gpu_spill_to_host"
    GPU_POOL_TYPE = "gpu_pool_type"

    def __str__(self) -> str:

        return self.value

    @classmethod
    def from_string(cls, value: str) -> "DataFrameTuningType":

        value_lower = value.lower()
        for tuning_type in cls:
            if tuning_type.value == value_lower:
                return tuning_type
        raise ValueError(f"Invalid DataFrame tuning type: {value}")

    def is_compatible_with_platform(self, platform: str) -> bool:

        platform_lower = platform.lower()

        if platform_lower.endswith("-df"):
            platform_lower = platform_lower[:-3]

        return self in _PLATFORM_COMPATIBILITY.get(platform_lower, set())

    @classmethod
    def get_platform_supported_types(cls, platform: str) -> set["DataFrameTuningType"]:

        platform_lower = platform.lower()
        if platform_lower.endswith("-df"):
            platform_lower = platform_lower[:-3]

        return _PLATFORM_COMPATIBILITY.get(platform_lower, set()).copy()


_PLATFORM_COMPATIBILITY: dict[str, set[DataFrameTuningType]] = {
    "datafusion": {
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
        DataFrameTuningType.MEMORY_POOL,
        DataFrameTuningType.ROW_GROUP_SIZE,
    },
    "pandas": {
        DataFrameTuningType.CHUNK_SIZE,
        DataFrameTuningType.DTYPE_BACKEND,
        DataFrameTuningType.STRING_CACHE,
        DataFrameTuningType.MEMORY_POOL,
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
    "cudf": {
        DataFrameTuningType.STRING_CACHE,
        DataFrameTuningType.GPU_DEVICE,
        DataFrameTuningType.GPU_SPILL_TO_HOST,
        DataFrameTuningType.GPU_POOL_TYPE,
        DataFrameTuningType.ROW_GROUP_SIZE,
    },
}


def get_all_platforms() -> list[str]:

    return list(_PLATFORM_COMPATIBILITY.keys())

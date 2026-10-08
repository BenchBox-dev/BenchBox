# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from benchbox.core.dataframe.tuning.types import DataFrameTuningType
from benchbox.core.dataframe.tuning.write_config import DataFrameWriteConfiguration


@dataclass
class ParallelismConfiguration:
    thread_count: int | None = None
    worker_count: int | None = None
    threads_per_worker: int | None = None

    def __post_init__(self) -> None:

        if self.thread_count is not None and self.thread_count < 1:
            raise ValueError("thread_count must be >= 1")
        if self.worker_count is not None and self.worker_count < 1:
            raise ValueError("worker_count must be >= 1")
        if self.threads_per_worker is not None and self.threads_per_worker < 1:
            raise ValueError("threads_per_worker must be >= 1")

    def to_dict(self) -> dict[str, Any]:

        return {
            "thread_count": self.thread_count,
            "worker_count": self.worker_count,
            "threads_per_worker": self.threads_per_worker,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParallelismConfiguration:

        return cls(
            thread_count=data.get("thread_count"),
            worker_count=data.get("worker_count"),
            threads_per_worker=data.get("threads_per_worker"),
        )

    def is_default(self) -> bool:

        return self.thread_count is None and self.worker_count is None and self.threads_per_worker is None


@dataclass
class MemoryConfiguration:
    memory_limit: str | None = None
    chunk_size: int | None = None
    spill_to_disk: bool = False
    spill_directory: str | None = None
    rechunk_after_filter: bool = True

    def __post_init__(self) -> None:

        if self.chunk_size is not None and self.chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        if self.memory_limit is not None:
            self._validate_memory_limit()

    def _validate_memory_limit(self) -> None:

        import re

        pattern = r"^\d+(\.\d+)?\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)$"
        if not re.match(pattern, self.memory_limit, re.IGNORECASE):
            raise ValueError(
                f"Invalid memory_limit format: {self.memory_limit}. "
                "Expected format: '<number><unit>' (e.g., '4GB', '2GiB')"
            )

    def to_dict(self) -> dict[str, Any]:

        return {
            "memory_limit": self.memory_limit,
            "chunk_size": self.chunk_size,
            "spill_to_disk": self.spill_to_disk,
            "spill_directory": self.spill_directory,
            "rechunk_after_filter": self.rechunk_after_filter,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryConfiguration:

        return cls(
            memory_limit=data.get("memory_limit"),
            chunk_size=data.get("chunk_size"),
            spill_to_disk=data.get("spill_to_disk", False),
            spill_directory=data.get("spill_directory"),
            rechunk_after_filter=data.get("rechunk_after_filter", True),
        )

    def is_default(self) -> bool:

        return (
            self.memory_limit is None
            and self.chunk_size is None
            and not self.spill_to_disk
            and self.spill_directory is None
            and self.rechunk_after_filter
        )


@dataclass
class ExecutionConfiguration:
    streaming_mode: bool = False
    engine_affinity: str | None = None
    lazy_evaluation: bool = True
    collect_timeout: int | None = None

    def __post_init__(self) -> None:

        if self.collect_timeout is not None and self.collect_timeout < 1:
            raise ValueError("collect_timeout must be >= 1")

    def to_dict(self) -> dict[str, Any]:

        return {
            "streaming_mode": self.streaming_mode,
            "engine_affinity": self.engine_affinity,
            "lazy_evaluation": self.lazy_evaluation,
            "collect_timeout": self.collect_timeout,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionConfiguration:

        return cls(
            streaming_mode=data.get("streaming_mode", False),
            engine_affinity=data.get("engine_affinity"),
            lazy_evaluation=data.get("lazy_evaluation", True),
            collect_timeout=data.get("collect_timeout"),
        )

    def is_default(self) -> bool:

        return (
            not self.streaming_mode
            and self.engine_affinity is None
            and self.lazy_evaluation
            and self.collect_timeout is None
        )


@dataclass
class DataTypeConfiguration:
    dtype_backend: str = "numpy_nullable"
    enable_string_cache: bool = False
    auto_categorize_strings: bool = False
    categorical_threshold: float = 0.5

    def __post_init__(self) -> None:

        valid_backends = {"numpy", "numpy_nullable", "pyarrow"}
        if self.dtype_backend not in valid_backends:
            raise ValueError(f"Invalid dtype_backend: {self.dtype_backend}. Must be one of: {valid_backends}")
        if not 0.0 <= self.categorical_threshold <= 1.0:
            raise ValueError("categorical_threshold must be between 0.0 and 1.0")

    def to_dict(self) -> dict[str, Any]:

        return {
            "dtype_backend": self.dtype_backend,
            "enable_string_cache": self.enable_string_cache,
            "auto_categorize_strings": self.auto_categorize_strings,
            "categorical_threshold": self.categorical_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataTypeConfiguration:

        return cls(
            dtype_backend=data.get("dtype_backend", "numpy_nullable"),
            enable_string_cache=data.get("enable_string_cache", False),
            auto_categorize_strings=data.get("auto_categorize_strings", False),
            categorical_threshold=data.get("categorical_threshold", 0.5),
        )

    def is_default(self) -> bool:

        return (
            self.dtype_backend == "numpy_nullable"
            and not self.enable_string_cache
            and not self.auto_categorize_strings
            and self.categorical_threshold == 0.5
        )


@dataclass
class IOConfiguration:
    memory_pool: str = "default"
    memory_map: bool = False
    pre_buffer: bool = True
    row_group_size: int | None = None

    def __post_init__(self) -> None:

        valid_pools = {"default", "jemalloc", "mimalloc", "system"}
        if self.memory_pool not in valid_pools:
            raise ValueError(f"Invalid memory_pool: {self.memory_pool}. Must be one of: {valid_pools}")
        if self.row_group_size is not None and self.row_group_size < 1:
            raise ValueError("row_group_size must be >= 1")

    def to_dict(self) -> dict[str, Any]:

        return {
            "memory_pool": self.memory_pool,
            "memory_map": self.memory_map,
            "pre_buffer": self.pre_buffer,
            "row_group_size": self.row_group_size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IOConfiguration:

        return cls(
            memory_pool=data.get("memory_pool", "default"),
            memory_map=data.get("memory_map", False),
            pre_buffer=data.get("pre_buffer", True),
            row_group_size=data.get("row_group_size"),
        )

    def is_default(self) -> bool:

        return self.memory_pool == "default" and not self.memory_map and self.pre_buffer and self.row_group_size is None


@dataclass
class GPUConfiguration:
    enabled: bool = False
    device_id: int = 0
    spill_to_host: bool = True
    pool_type: str = "default"

    def __post_init__(self) -> None:

        if self.device_id < 0:
            raise ValueError("device_id must be >= 0")
        valid_pools = {"default", "managed", "pool", "cuda"}
        if self.pool_type not in valid_pools:
            raise ValueError(f"Invalid pool_type: {self.pool_type}. Must be one of: {valid_pools}")

    def to_dict(self) -> dict[str, Any]:

        return {
            "enabled": self.enabled,
            "device_id": self.device_id,
            "spill_to_host": self.spill_to_host,
            "pool_type": self.pool_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GPUConfiguration:

        return cls(
            enabled=data.get("enabled", False),
            device_id=data.get("device_id", 0),
            spill_to_host=data.get("spill_to_host", True),
            pool_type=data.get("pool_type", "default"),
        )

    def is_default(self) -> bool:

        return not self.enabled and self.device_id == 0 and self.spill_to_host and self.pool_type == "default"


@dataclass
class TuningMetadata:
    version: str = "1.0"
    format: str = "dataframe_tuning"
    platform: str | None = None
    description: str | None = None
    created: str | None = None
    generated_by: str | None = None

    def to_dict(self) -> dict[str, Any]:

        result: dict[str, Any] = {
            "version": self.version,
            "format": self.format,
        }
        if self.platform:
            result["platform"] = self.platform
        if self.description:
            result["description"] = self.description
        if self.created:
            result["created"] = self.created
        if self.generated_by:
            result["generated_by"] = self.generated_by
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TuningMetadata:

        return cls(
            version=data.get("version", "1.0"),
            format=data.get("format", "dataframe_tuning"),
            platform=data.get("platform"),
            description=data.get("description"),
            created=data.get("created"),
            generated_by=data.get("generated_by"),
        )


@dataclass
class DataFrameTuningConfiguration:
    parallelism: ParallelismConfiguration = field(default_factory=ParallelismConfiguration)
    memory: MemoryConfiguration = field(default_factory=MemoryConfiguration)
    execution: ExecutionConfiguration = field(default_factory=ExecutionConfiguration)
    data_types: DataTypeConfiguration = field(default_factory=DataTypeConfiguration)
    io: IOConfiguration = field(default_factory=IOConfiguration)
    gpu: GPUConfiguration = field(default_factory=GPUConfiguration)
    write: DataFrameWriteConfiguration = field(default_factory=DataFrameWriteConfiguration)
    metadata: TuningMetadata | None = None

    def to_dict(self) -> dict[str, Any]:

        result: dict[str, Any] = {}

        if not self.parallelism.is_default():
            result["parallelism"] = self.parallelism.to_dict()
        if not self.memory.is_default():
            result["memory"] = self.memory.to_dict()
        if not self.execution.is_default():
            result["execution"] = self.execution.to_dict()
        if not self.data_types.is_default():
            result["data_types"] = self.data_types.to_dict()
        if not self.io.is_default():
            result["io"] = self.io.to_dict()
        if not self.gpu.is_default():
            result["gpu"] = self.gpu.to_dict()
        if not self.write.is_default():
            result["write"] = self.write.to_dict()

        if self.metadata:
            result["_metadata"] = self.metadata.to_dict()

        return result

    def to_full_dict(self) -> dict[str, Any]:

        result: dict[str, Any] = {
            "parallelism": self.parallelism.to_dict(),
            "memory": self.memory.to_dict(),
            "execution": self.execution.to_dict(),
            "data_types": self.data_types.to_dict(),
            "io": self.io.to_dict(),
            "gpu": self.gpu.to_dict(),
            "write": self.write.to_dict(),
        }
        if self.metadata:
            result["_metadata"] = self.metadata.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataFrameTuningConfiguration:

        return cls(
            parallelism=ParallelismConfiguration.from_dict(data.get("parallelism", {})),
            memory=MemoryConfiguration.from_dict(data.get("memory", {})),
            execution=ExecutionConfiguration.from_dict(data.get("execution", {})),
            data_types=DataTypeConfiguration.from_dict(data.get("data_types", {})),
            io=IOConfiguration.from_dict(data.get("io", {})),
            gpu=GPUConfiguration.from_dict(data.get("gpu", {})),
            write=DataFrameWriteConfiguration.from_dict(data.get("write", {})),
            metadata=TuningMetadata.from_dict(data["_metadata"]) if "_metadata" in data else None,
        )

    _SETTING_CHECKS: ClassVar[list[tuple[Callable[[DataFrameTuningConfiguration], bool], DataFrameTuningType]]] = [
        (lambda s: s.parallelism.thread_count is not None, DataFrameTuningType.THREAD_COUNT),
        (lambda s: s.parallelism.worker_count is not None, DataFrameTuningType.WORKER_COUNT),
        (lambda s: s.parallelism.threads_per_worker is not None, DataFrameTuningType.THREADS_PER_WORKER),
        (lambda s: s.memory.memory_limit is not None, DataFrameTuningType.MEMORY_LIMIT),
        (lambda s: s.memory.chunk_size is not None, DataFrameTuningType.CHUNK_SIZE),
        (lambda s: s.memory.spill_to_disk, DataFrameTuningType.SPILL_TO_DISK),
        (lambda s: not s.memory.rechunk_after_filter, DataFrameTuningType.RECHUNK),
        (lambda s: s.execution.streaming_mode, DataFrameTuningType.STREAMING_MODE),
        (lambda s: s.execution.engine_affinity is not None, DataFrameTuningType.ENGINE_AFFINITY),
        (lambda s: not s.execution.lazy_evaluation, DataFrameTuningType.LAZY_EVALUATION),
        (lambda s: s.data_types.dtype_backend != "numpy_nullable", DataFrameTuningType.DTYPE_BACKEND),
        (lambda s: s.data_types.enable_string_cache, DataFrameTuningType.STRING_CACHE),
        (lambda s: s.io.memory_pool != "default", DataFrameTuningType.MEMORY_POOL),
        (lambda s: s.io.memory_map, DataFrameTuningType.MEMORY_MAP),
        (lambda s: not s.io.pre_buffer, DataFrameTuningType.PRE_BUFFER),
        (lambda s: s.io.row_group_size is not None, DataFrameTuningType.ROW_GROUP_SIZE),
        (lambda s: s.gpu.enabled, DataFrameTuningType.GPU_DEVICE),
        (lambda s: s.gpu.enabled and not s.gpu.spill_to_host, DataFrameTuningType.GPU_SPILL_TO_HOST),
        (lambda s: s.gpu.enabled and s.gpu.pool_type != "default", DataFrameTuningType.GPU_POOL_TYPE),
    ]

    def get_enabled_settings(self) -> set[DataFrameTuningType]:

        return {tt for check, tt in self._SETTING_CHECKS if check(self)}

    def is_default(self) -> bool:

        return (
            self.parallelism.is_default()
            and self.memory.is_default()
            and self.execution.is_default()
            and self.data_types.is_default()
            and self.io.is_default()
            and self.gpu.is_default()
            and self.write.is_default()
        )

    def get_summary(self) -> dict[str, Any]:

        enabled = self.get_enabled_settings()
        write_enabled = self.write.get_enabled_types()
        return {
            "enabled_settings": [t.value for t in enabled],
            "setting_count": len(enabled),
            "is_default": self.is_default(),
            "has_gpu": self.gpu.enabled,
            "has_streaming": self.execution.streaming_mode,
            "has_write_config": not self.write.is_default(),
            "parallelism": {
                "threads": self.parallelism.thread_count,
                "workers": self.parallelism.worker_count,
            },
            "memory": {
                "limit": self.memory.memory_limit,
                "chunk_size": self.memory.chunk_size,
            },
            "write": {
                "enabled_types": [t.value for t in write_enabled],
                "sort_by": [s.name for s in self.write.sort_by] if self.write.sort_by else None,
                "compression": self.write.compression,
            },
        }

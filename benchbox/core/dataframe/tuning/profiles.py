# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License.

from __future__ import annotations

from benchbox.core.dataframe.tuning.interface import DataFrameTuningConfiguration

DATAFRAME_PLATFORMS = frozenset({"datafusion", "polars", "pandas", "dask", "cudf"})


DATAFRAME_CAPABILITY_ROWS: list[tuple[str, str, str, str]] = [
    ("datafusion", "Expression", "Session partitions and record-batch size", "No"),
    ("polars", "Expression", "Lazy evaluation, streaming, thread control", "No"),
    ("pandas", "Pandas", "dtype_backend, categorical strings", "No"),
    ("dask", "Pandas", "Distributed, worker/thread control, spill to disk", "No"),
    ("cudf", "Pandas", "GPU acceleration, memory pools, spill to host", "Yes"),
]


def create_profile_config(platform: str, profile: str) -> DataFrameTuningConfiguration:

    if platform == "datafusion" and profile not in {"default", "optimized"}:
        raise ValueError(f"DataFusion does not support the {profile!r} tuning profile")

    config = DataFrameTuningConfiguration()

    if profile == "optimized":
        config.execution.lazy_evaluation = True
        if platform == "polars":
            config.execution.engine_affinity = "in-memory"
        elif platform == "datafusion":
            config.parallelism.thread_count = 4
        elif platform == "dask":
            config.parallelism.worker_count = 4
            config.parallelism.threads_per_worker = 2
        elif platform == "cudf":
            config.gpu.enabled = True
            config.gpu.pool_type = "pool"

    elif profile == "streaming":
        config.execution.streaming_mode = True
        config.memory.chunk_size = 100_000
        if platform == "polars":
            config.execution.engine_affinity = "streaming"

    elif profile == "memory-constrained":
        config.execution.streaming_mode = True
        config.memory.chunk_size = 50_000
        config.memory.spill_to_disk = True
        if platform == "dask":
            config.memory.memory_limit = "2GB"

    elif profile == "gpu":
        config.gpu.enabled = True
        config.gpu.pool_type = "pool"
        config.gpu.spill_to_host = True

    return config

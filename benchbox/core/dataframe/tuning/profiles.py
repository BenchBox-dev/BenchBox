"""Core tuning profiles and DataFrame capability table.

Moved from ``benchbox.cli.commands.tuning_group`` so the mapping lives beside
``PLATFORM_TUNING_CAPABILITIES`` and any surface (CLI, MCP) uses the same
policy. The CLI keeps flag parsing and console presentation only.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

from benchbox.core.dataframe.tuning.interface import DataFrameTuningConfiguration

# DataFrame platforms supported by the tuning system — mirrors
# ``benchbox.platforms.dataframe.platform_checker.DATAFRAME_PLATFORMS`` keys.
DATAFRAME_PLATFORMS = frozenset({"datafusion", "polars", "pandas", "dask", "modin", "cudf"})

# Hardcoded DataFrame capability table previously in the CLI's ``list_platforms``
# command. Kept here so the CLI's ``tuning platforms`` table is a projection of
# core, not a second source of truth.
DATAFRAME_CAPABILITY_ROWS: list[tuple[str, str, str, str]] = [
    ("datafusion", "Expression", "Session partitions and record-batch size", "No"),
    ("polars", "Expression", "Lazy evaluation, streaming, thread control", "No"),
    ("pandas", "Pandas", "dtype_backend, categorical strings", "No"),
    ("dask", "Pandas", "Distributed, worker/thread control, spill to disk", "No"),
    ("modin", "Pandas", "Engine selection (ray/dask), parallelization", "No"),
    ("cudf", "Pandas", "GPU acceleration, memory pools, spill to host", "Yes"),
]


def create_profile_config(platform: str, profile: str) -> DataFrameTuningConfiguration:
    """Create a ``DataFrameTuningConfiguration`` for ``(platform, profile)``.

    Mirrors ``benchbox.cli.commands.tuning_group._create_profile_config``
    exactly (verified by byte-compatibility of yielded YAML). The only
    behavioural note preserved is that ``profile == "gpu"`` on a non-cuDF
    platform still produces a GPU-enabled config — the CLI warns about the
    mismatch at the call site, not here.

    Profiles:
        default          — no custom settings (bare defaults)
        optimized        — lazy/cache-friendly settings per platform
        streaming        — streaming execution with chunked memory
        memory-constrained — streaming + spill-to-disk, small chunks
        gpu              — GPU-accelerated (cuDF-centric)

    Args:
        platform: DataFrame platform slug (polars, dask, cudf, ...).
        profile: Profile name.

    Returns:
        Configured :class:`DataFrameTuningConfiguration`.
    """
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

"""Smart defaults for DataFrame tuning configurations.

This module provides functionality to generate recommended tuning configurations
based on system capabilities (CPU, memory, GPU).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from benchbox.core.dataframe.tuning.interface import (
    DataFrameTuningConfiguration,
    TuningMetadata,
)

logger = logging.getLogger(__name__)


@dataclass
class SystemProfile:
    """Profile of system capabilities for tuning recommendations.

    Attributes:
        cpu_cores: Number of CPU cores available
        available_memory_gb: Available system memory in gigabytes
        has_gpu: Whether a GPU is available
        gpu_memory_gb: GPU memory in gigabytes (if available)
        gpu_device_count: Number of GPU devices
    """

    cpu_cores: int
    available_memory_gb: float
    has_gpu: bool = False
    gpu_memory_gb: float = 0.0
    gpu_device_count: int = 0


def detect_system_profile() -> SystemProfile:
    """Detect the current system's capabilities.

    Returns:
        SystemProfile with detected system information
    """
    import multiprocessing

    # Get CPU cores
    cpu_cores = multiprocessing.cpu_count()

    # Get available memory
    available_memory_gb = _get_available_memory_gb()

    # Check for GPU
    has_gpu, gpu_memory_gb, gpu_device_count = _detect_gpu()

    return SystemProfile(
        cpu_cores=cpu_cores,
        available_memory_gb=available_memory_gb,
        has_gpu=has_gpu,
        gpu_memory_gb=gpu_memory_gb,
        gpu_device_count=gpu_device_count,
    )


def _get_available_memory_gb() -> float:
    """Get available system memory in gigabytes.

    Returns:
        Available memory in GB, or 8.0 as fallback
    """
    try:
        import psutil

        mem = psutil.virtual_memory()
        return mem.available / (1024**3)
    except ImportError:
        # psutil not available, try platform-specific methods
        pass

    # Try reading from /proc/meminfo on Linux
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    # Value is in kB
                    kb = int(line.split()[1])
                    return kb / (1024**2)
    except (OSError, ValueError, IndexError):
        pass

    # macOS: use sysctl
    try:
        import subprocess

        result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True)
        total_bytes = int(result.stdout.strip())
        # Assume 70% is available
        return (total_bytes * 0.7) / (1024**3)
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        pass

    # Default fallback
    logger.warning("Could not detect system memory, assuming 8GB")
    return 8.0


def _detect_gpu() -> tuple[bool, float, int]:
    """Detect GPU availability and memory.

    Returns:
        Tuple of (has_gpu, gpu_memory_gb, device_count)
    """
    # Try CUDA via cupy or numba
    try:
        import cupy

        device_count = cupy.cuda.runtime.getDeviceCount()
        if device_count > 0:
            # Get memory from first device
            mem_info = cupy.cuda.runtime.memGetInfo()
            total_memory = mem_info[1]  # Total memory in bytes
            return True, total_memory / (1024**3), device_count
    except (ImportError, Exception):
        pass

    # Try pynvml directly
    try:
        import pynvml

        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        if device_count > 0:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            pynvml.nvmlShutdown()
            return True, info.total / (1024**3), device_count
        pynvml.nvmlShutdown()
    except (ImportError, Exception):
        pass

    # Check environment variable as hint
    if os.environ.get("CUDA_VISIBLE_DEVICES"):
        logger.info("CUDA_VISIBLE_DEVICES set but cannot query GPU, assuming GPU available")
        return True, 8.0, 1

    return False, 0.0, 0


def get_smart_defaults(
    platform: str,
    system_profile: SystemProfile | None = None,
) -> DataFrameTuningConfiguration:
    """Generate recommended tuning configuration based on system capabilities.

    This function analyzes the system profile and generates a configuration
    that balances performance and resource usage for the target platform.

    Args:
        platform: The DataFrame platform name
        system_profile: System capabilities (auto-detected if None)

    Returns:
        DataFrameTuningConfiguration with recommended settings
    """
    if system_profile is None:
        system_profile = detect_system_profile()

    # Normalize platform name
    platform_lower = platform.lower()
    if platform_lower.endswith("-df"):
        platform_lower = platform_lower[:-3]

    # Create base configuration
    config = DataFrameTuningConfiguration(
        metadata=TuningMetadata(
            platform=platform_lower,
            description=f"Auto-generated defaults for {platform_lower}",
            generated_by="benchbox-smart-defaults",
        )
    )

    # Apply general recommendations based on available memory
    _apply_memory_recommendations(config, system_profile)

    # Apply platform-specific recommendations
    if platform_lower == "polars":
        _configure_polars(config, system_profile)
    elif platform_lower == "pandas":
        _configure_pandas(config, system_profile)
    elif platform_lower == "dask":
        _configure_dask(config, system_profile)
    elif platform_lower == "modin":
        _configure_modin(config, system_profile)
    elif platform_lower == "cudf":
        _configure_cudf(config, system_profile)

    return config


def _apply_memory_recommendations(
    config: DataFrameTuningConfiguration,
    profile: SystemProfile,
) -> None:
    """Apply general memory-based recommendations.

    Args:
        config: Configuration to modify
        profile: System profile
    """
    available_gb = profile.available_memory_gb

    # Very low memory: aggressive streaming
    if available_gb < 4:
        config.execution.streaming_mode = True
        config.memory.chunk_size = 50_000
        logger.info("Low memory detected (<4GB), enabling streaming mode")

    # Low memory: enable streaming with larger chunks
    elif available_gb < 8:
        config.execution.streaming_mode = True
        config.memory.chunk_size = 100_000

    # Medium memory: moderate chunk size
    elif available_gb < 32:
        config.memory.chunk_size = 500_000

    # High memory: in-memory processing
    else:
        config.execution.streaming_mode = False


def _configure_polars(config: DataFrameTuningConfiguration, profile: SystemProfile) -> None:
    """Configure Polars-specific settings.

    Args:
        config: Configuration to modify
        profile: System profile
    """
    available_gb = profile.available_memory_gb

    # Engine affinity based on memory
    if available_gb >= 64:
        config.execution.engine_affinity = "in-memory"
        config.execution.streaming_mode = False
    elif available_gb >= 16:
        config.execution.engine_affinity = "in-memory"
        # Keep streaming_mode from memory recommendations
    else:
        config.execution.engine_affinity = "streaming"
        config.execution.streaming_mode = True

    # Always enable lazy evaluation for Polars
    config.execution.lazy_evaluation = True

    # Rechunking based on workload type
    config.memory.rechunk_after_filter = True

    # Thread count recommendation
    # Polars uses all cores by default, but we can recommend a cap
    if profile.cpu_cores > 16:
        config.parallelism.thread_count = min(profile.cpu_cores, 32)


def _configure_pandas(config: DataFrameTuningConfiguration, profile: SystemProfile) -> None:
    """Configure Pandas-specific settings.

    Args:
        config: Configuration to modify
        profile: System profile
    """
    available_gb = profile.available_memory_gb

    # Use PyArrow backend for better performance if enough memory
    if available_gb >= 8:
        config.data_types.dtype_backend = "pyarrow"
    else:
        config.data_types.dtype_backend = "numpy_nullable"

    # Enable memory mapping for low memory environments
    if available_gb < 16:
        config.io.memory_map = True

    # Auto-categorize strings in low memory environments
    if available_gb < 8:
        config.data_types.auto_categorize_strings = True
        config.data_types.categorical_threshold = 0.5


def _configure_dask(config: DataFrameTuningConfiguration, profile: SystemProfile) -> None:
    """Configure Dask-specific settings.

    Args:
        config: Configuration to modify
        profile: System profile
    """
    available_gb = profile.available_memory_gb
    cpu_cores = profile.cpu_cores

    # Worker count: balance between parallelism and memory
    # Rule of thumb: 1 worker per 4GB of memory, or 1/4 of CPU cores
    workers_by_memory = max(1, int(available_gb / 4))
    workers_by_cpu = max(1, cpu_cores // 4)
    worker_count = min(workers_by_memory, workers_by_cpu, 8)  # Cap at 8

    config.parallelism.worker_count = worker_count

    # Threads per worker: inversely related to worker count
    if worker_count <= 2:
        config.parallelism.threads_per_worker = 4
    elif worker_count <= 4:
        config.parallelism.threads_per_worker = 2
    else:
        config.parallelism.threads_per_worker = 1

    # Memory limit per worker
    memory_per_worker = available_gb / worker_count
    # Leave some headroom (80% of calculated)
    config.memory.memory_limit = f"{int(memory_per_worker * 0.8)}GB"

    # Enable spilling for safety
    config.memory.spill_to_disk = True

    # Use PyArrow for better integration
    config.data_types.dtype_backend = "pyarrow"


def _configure_modin(config: DataFrameTuningConfiguration, profile: SystemProfile) -> None:
    """Configure Modin-specific settings.

    Args:
        config: Configuration to modify
        profile: System profile
    """
    # Default to Ray backend (more mature)
    config.execution.engine_affinity = "ray"

    # Worker count based on CPU
    if profile.cpu_cores >= 8:
        config.parallelism.worker_count = profile.cpu_cores
    else:
        config.parallelism.worker_count = max(2, profile.cpu_cores)

    # Use nullable dtypes for compatibility
    config.data_types.dtype_backend = "numpy_nullable"


def _configure_cudf(config: DataFrameTuningConfiguration, profile: SystemProfile) -> None:
    """Configure cuDF-specific settings.

    Args:
        config: Configuration to modify
        profile: System profile
    """
    # Enable GPU
    config.gpu.enabled = True
    config.gpu.device_id = 0

    if profile.has_gpu:
        # If GPU memory is small, enable spilling
        if profile.gpu_memory_gb < 8:
            config.gpu.spill_to_host = True
            config.gpu.pool_type = "managed"  # Better for spilling
        else:
            # Larger GPU: use pooled allocator for speed
            config.gpu.spill_to_host = True  # Safety
            config.gpu.pool_type = "pool"

        # Multi-GPU handling
        if profile.gpu_device_count > 1:
            logger.info(f"Multiple GPUs detected ({profile.gpu_device_count}), using device 0")
    else:
        # No GPU detected but platform is cuDF
        logger.warning("cuDF selected but no GPU detected")
        config.gpu.spill_to_host = True


def get_profile_summary(profile: SystemProfile) -> dict:
    """Get a human-readable summary of the system profile.

    Args:
        profile: System profile to summarize

    Returns:
        Dictionary with summary information
    """
    return {
        "cpu_cores": profile.cpu_cores,
        "available_memory_gb": round(profile.available_memory_gb, 1),
        "has_gpu": profile.has_gpu,
        "gpu_memory_gb": round(profile.gpu_memory_gb, 1) if profile.has_gpu else None,
        "gpu_device_count": profile.gpu_device_count if profile.has_gpu else None,
        "memory_category": (
            "very_low"
            if profile.available_memory_gb < 4
            else "low"
            if profile.available_memory_gb < 8
            else "medium"
            if profile.available_memory_gb < 32
            else "high"
        ),
    }

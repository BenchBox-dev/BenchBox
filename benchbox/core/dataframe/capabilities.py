"""DataFrame Platform Capabilities and Memory Management.

Defines per-platform capabilities including memory requirements, scale factor
limits, and partitioning needs. Provides pre-execution checks to prevent
OOM crashes and guide users to appropriate platforms for their workloads.

Key Features:
- Platform capability definitions for 8 DataFrame platforms
- Memory estimation for TPC-H and TPC-DS benchmarks
- Pre-execution memory validation with helpful error messages
- Scale factor recommendations per platform

Usage:
    from benchbox.core.dataframe.capabilities import (
        PlatformCapabilities,
        get_platform_capabilities,
        estimate_memory_required,
        check_sufficient_memory,
    )

    # Check if platform can handle scale factor
    caps = get_platform_capabilities("pandas")
    if scale_factor > caps.max_recommended_sf:
        emit(f"Warning: SF {scale_factor} exceeds recommended limit {caps.max_recommended_sf}")

    # Check memory before execution
    result = check_sufficient_memory("tpch", scale_factor=10, platform="polars")
    if not result.is_safe:
        emit(result.message)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DataFormat(Enum):
    """Supported data formats for DataFrame loading."""

    CSV = "csv"
    PARQUET = "parquet"
    ARROW = "arrow"


class ExecutionModel(Enum):
    """Platform execution model."""

    EAGER = "eager"  # Loads all data into memory immediately
    LAZY = "lazy"  # Deferred execution, optimized query plans
    DISTRIBUTED = "distributed"  # Distributed across workers
    OUT_OF_CORE = "out_of_core"  # Processes data larger than memory


@dataclass
class PlatformCapabilities:
    """Capabilities and limits for a DataFrame platform.

    Attributes:
        platform_name: Human-readable platform name
        max_recommended_sf: Maximum recommended scale factor (TPC-H)
        memory_overhead_factor: Multiplier for data size to estimate memory
        execution_model: How the platform executes queries
        requires_partitioning: Whether large data needs partitioning
        supports_streaming: Whether streaming mode is available
        gpu_required: Whether GPU is required
        recommended_data_format: Preferred data format for loading
        min_memory_gb: Minimum memory recommended for any usage
        description: Brief description of the platform
    """

    platform_name: str
    max_recommended_sf: float
    memory_overhead_factor: float
    execution_model: ExecutionModel
    requires_partitioning: bool = False
    supports_streaming: bool = False
    gpu_required: bool = False
    recommended_data_format: DataFormat = DataFormat.PARQUET
    min_memory_gb: float = 2.0
    description: str = ""
    notes: list[str] = field(default_factory=list)

    def estimate_memory_for_sf(self, scale_factor: float) -> float:
        """Estimate memory required for a scale factor in GB.

        TPC-H SF 1 is approximately 1 GB of raw data.

        Args:
            scale_factor: TPC-H scale factor

        Returns:
            Estimated memory in GB
        """
        raw_data_gb = scale_factor  # TPC-H SF 1 ≈ 1 GB
        return raw_data_gb * self.memory_overhead_factor

    def can_handle_sf(self, scale_factor: float) -> bool:
        """Check if platform can safely handle scale factor.

        Args:
            scale_factor: TPC-H scale factor

        Returns:
            True if scale factor is within recommended limits
        """
        return scale_factor <= self.max_recommended_sf


# Platform capability definitions
PLATFORM_CAPABILITIES: dict[str, PlatformCapabilities] = {
    "polars": PlatformCapabilities(
        platform_name="Polars",
        max_recommended_sf=100.0,
        memory_overhead_factor=2.0,
        execution_model=ExecutionModel.LAZY,
        supports_streaming=True,
        recommended_data_format=DataFormat.PARQUET,
        description="Fast Rust-based DataFrame library with lazy evaluation",
        notes=[
            "Streaming mode can handle data larger than memory",
            "LazyFrame optimizes query execution",
            "Excellent for single-machine workloads",
        ],
    ),
    "pandas": PlatformCapabilities(
        platform_name="Pandas",
        max_recommended_sf=10.0,
        memory_overhead_factor=2.5,
        execution_model=ExecutionModel.EAGER,
        recommended_data_format=DataFormat.CSV,
        min_memory_gb=4.0,
        description="Reference Python DataFrame library",
        notes=[
            "Loads entire dataset into memory",
            "Use smaller scale factors or switch to Dask for larger data",
            "Memory overhead can be 2-3x raw data size",
        ],
    ),
    "cudf": PlatformCapabilities(
        platform_name="cuDF",
        max_recommended_sf=1.0,  # Limited by GPU VRAM
        memory_overhead_factor=1.8,
        execution_model=ExecutionModel.EAGER,
        gpu_required=True,
        recommended_data_format=DataFormat.PARQUET,
        min_memory_gb=8.0,  # GPU VRAM
        description="NVIDIA RAPIDS GPU DataFrame library",
        notes=[
            "Limited by GPU VRAM (typically 8-24GB)",
            "Extremely fast for data that fits in GPU memory",
            "Requires NVIDIA GPU with CUDA support",
        ],
    ),
    "dask": PlatformCapabilities(
        platform_name="Dask",
        max_recommended_sf=1000.0,
        memory_overhead_factor=1.5,
        execution_model=ExecutionModel.OUT_OF_CORE,
        requires_partitioning=True,
        recommended_data_format=DataFormat.PARQUET,
        description="Parallel computing library for out-of-core processing",
        notes=[
            "Can process datasets larger than memory",
            "Requires proper partitioning for efficiency",
            "Supports distributed clusters",
        ],
    ),
    "vaex": PlatformCapabilities(
        platform_name="Vaex",
        max_recommended_sf=100.0,
        memory_overhead_factor=1.2,
        execution_model=ExecutionModel.OUT_OF_CORE,
        recommended_data_format=DataFormat.PARQUET,
        description="Memory-mapped DataFrame library for large datasets",
        notes=[
            "Uses memory mapping for efficient large dataset handling",
            "Lazy evaluation with expression system",
            "Good for exploratory analysis of large files",
        ],
    ),
    "pyspark": PlatformCapabilities(
        platform_name="PySpark",
        max_recommended_sf=10000.0,
        memory_overhead_factor=3.0,
        execution_model=ExecutionModel.DISTRIBUTED,
        requires_partitioning=True,
        recommended_data_format=DataFormat.PARQUET,
        min_memory_gb=8.0,
        description="Apache Spark Python API for distributed computing",
        notes=[
            "Designed for cluster-scale data processing",
            "Higher overhead for small datasets",
            "Best for very large scale factors (100+)",
        ],
    ),
    "datafusion": PlatformCapabilities(
        platform_name="DataFusion",
        max_recommended_sf=100.0,
        memory_overhead_factor=1.8,
        execution_model=ExecutionModel.LAZY,
        supports_streaming=True,
        recommended_data_format=DataFormat.PARQUET,
        description="Apache Arrow DataFusion query engine",
        notes=[
            "SQL and DataFrame APIs available",
            "Built on Apache Arrow for efficient memory",
            "Good balance of performance and memory efficiency",
        ],
    ),
}


def get_platform_capabilities(platform: str) -> PlatformCapabilities:
    """Get capabilities for a DataFrame platform.

    Args:
        platform: Platform name (case-insensitive)

    Returns:
        PlatformCapabilities for the platform

    Raises:
        ValueError: If platform is unknown
    """
    platform_lower = platform.lower()

    # Handle -df suffix
    if platform_lower.endswith("-df"):
        platform_lower = platform_lower[:-3]

    if platform_lower not in PLATFORM_CAPABILITIES:
        available = ", ".join(sorted(PLATFORM_CAPABILITIES.keys()))
        raise ValueError(f"Unknown DataFrame platform: {platform}. Available: {available}")

    return PLATFORM_CAPABILITIES[platform_lower]


def list_platform_capabilities() -> dict[str, PlatformCapabilities]:
    """Get capabilities for all DataFrame platforms.

    Returns:
        Dictionary mapping platform name to capabilities
    """
    return PLATFORM_CAPABILITIES.copy()


@dataclass
class MemoryEstimate:
    """Memory estimation result."""

    raw_data_gb: float
    estimated_memory_gb: float
    platform: str
    scale_factor: float
    benchmark: str


def estimate_memory_required(
    benchmark: str,
    scale_factor: float,
    platform: str,
) -> MemoryEstimate:
    """Estimate memory required for a benchmark run.

    Args:
        benchmark: Benchmark name ("tpch" or "tpcds")
        scale_factor: Scale factor
        platform: DataFrame platform name

    Returns:
        MemoryEstimate with memory requirements
    """
    caps = get_platform_capabilities(platform)

    # Base data sizes (approximate)
    if benchmark.lower() == "tpch":
        raw_data_gb = scale_factor  # TPC-H SF 1 ≈ 1 GB
    elif benchmark.lower() == "tpcds":
        raw_data_gb = scale_factor  # TPC-DS SF 1 ≈ 1 GB (similar to TPC-H)
    else:
        raw_data_gb = scale_factor  # Default assumption

    estimated_gb = raw_data_gb * caps.memory_overhead_factor

    return MemoryEstimate(
        raw_data_gb=raw_data_gb,
        estimated_memory_gb=estimated_gb,
        platform=caps.platform_name,
        scale_factor=scale_factor,
        benchmark=benchmark,
    )


def get_available_memory_gb() -> float:
    """Get available system memory in GB.

    Returns:
        Available memory in GB, or 0 if cannot be determined
    """
    try:
        import psutil

        return psutil.virtual_memory().available / (1024**3)
    except ImportError:
        logger.debug("psutil not available, cannot determine available memory")
        return 0.0


def get_total_memory_gb() -> float:
    """Get total system memory in GB.

    Returns:
        Total memory in GB, or 0 if cannot be determined
    """
    try:
        import psutil

        return psutil.virtual_memory().total / (1024**3)
    except ImportError:
        logger.debug("psutil not available, cannot determine total memory")
        return 0.0


def get_gpu_memory_gb() -> float | None:
    """Get available GPU memory in GB (for cuDF).

    Returns:
        Available GPU memory in GB, or None if not available
    """
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        pynvml.nvmlShutdown()
        return info.free / (1024**3)
    except Exception:
        return None


@dataclass
class MemoryCheckResult:
    """Result of a memory sufficiency check."""

    is_safe: bool
    message: str
    estimated_memory_gb: float
    available_memory_gb: float
    scale_factor: float
    platform: str
    suggestions: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Allow using result as boolean."""
        return self.is_safe


def check_sufficient_memory(
    benchmark: str,
    scale_factor: float,
    platform: str,
    *,
    safety_margin: float = 0.2,
) -> MemoryCheckResult:
    """Check if sufficient memory is available for a benchmark run.

    Args:
        benchmark: Benchmark name ("tpch" or "tpcds")
        scale_factor: Scale factor
        platform: DataFrame platform name
        safety_margin: Additional safety margin (0.2 = 20%)

    Returns:
        MemoryCheckResult with safety check and suggestions
    """
    caps = get_platform_capabilities(platform)
    estimate = estimate_memory_required(benchmark, scale_factor, platform)

    # Check GPU memory for cuDF
    if caps.gpu_required:
        gpu_mem = get_gpu_memory_gb()
        if gpu_mem is None:
            return MemoryCheckResult(
                is_safe=False,
                message=f"{caps.platform_name} requires a GPU but none was detected.",
                estimated_memory_gb=estimate.estimated_memory_gb,
                available_memory_gb=0,
                scale_factor=scale_factor,
                platform=platform,
                suggestions=[
                    "Ensure NVIDIA GPU is available with CUDA support",
                    "Try a CPU-based platform like Polars or Pandas",
                ],
            )
        available = gpu_mem
        memory_type = "GPU"
    else:
        available = get_available_memory_gb()
        memory_type = "system"

    if available == 0:
        # Cannot determine memory, proceed with warning
        return MemoryCheckResult(
            is_safe=True,
            message=f"Could not determine available {memory_type} memory. Proceeding with caution.",
            estimated_memory_gb=estimate.estimated_memory_gb,
            available_memory_gb=0,
            scale_factor=scale_factor,
            platform=platform,
            suggestions=["Install psutil for memory checks: uv add psutil"],
        )

    required_with_margin = estimate.estimated_memory_gb * (1 + safety_margin)

    if available >= required_with_margin:
        return MemoryCheckResult(
            is_safe=True,
            message=(
                f"Memory check passed: {available:.1f} GB available, "
                f"~{estimate.estimated_memory_gb:.1f} GB required for SF {scale_factor}."
            ),
            estimated_memory_gb=estimate.estimated_memory_gb,
            available_memory_gb=available,
            scale_factor=scale_factor,
            platform=platform,
        )

    # Build suggestions
    suggestions = []

    # Check scale factor limit
    if scale_factor > caps.max_recommended_sf:
        suggestions.append(
            f"Scale factor {scale_factor} exceeds recommended limit for {caps.platform_name} "
            f"(max: {caps.max_recommended_sf})"
        )

    # Suggest smaller scale factor
    if scale_factor > 1:
        safe_sf = available / caps.memory_overhead_factor * (1 - safety_margin)
        if safe_sf >= 0.01:
            suggestions.append(f"Try a smaller scale factor (suggested: SF {safe_sf:.2f} or less)")

    # Suggest alternative platforms
    alternatives = []
    for name, alt_caps in PLATFORM_CAPABILITIES.items():
        if name != platform.lower() and alt_caps.can_handle_sf(scale_factor):
            if alt_caps.execution_model in (ExecutionModel.OUT_OF_CORE, ExecutionModel.DISTRIBUTED):
                alternatives.append(f"{alt_caps.platform_name} ({alt_caps.execution_model.value})")

    if alternatives:
        suggestions.append(f"Consider platforms that handle larger data: {', '.join(alternatives[:3])}")

    # Suggest streaming if available
    if caps.supports_streaming:
        suggestions.append(f"Enable streaming mode for {caps.platform_name}")

    return MemoryCheckResult(
        is_safe=False,
        message=(
            f"Insufficient memory: ~{estimate.estimated_memory_gb:.1f} GB required, "
            f"but only {available:.1f} GB available.\n"
            f"Platform: {caps.platform_name}, Scale Factor: {scale_factor}"
        ),
        estimated_memory_gb=estimate.estimated_memory_gb,
        available_memory_gb=available,
        scale_factor=scale_factor,
        platform=platform,
        suggestions=suggestions,
    )


def validate_scale_factor(
    scale_factor: float,
    platform: str,
    *,
    strict: bool = False,
) -> tuple[bool, str | None]:
    """Validate scale factor for a platform.

    Args:
        scale_factor: TPC-H scale factor
        platform: DataFrame platform name
        strict: If True, reject scale factors above limit; if False, just warn

    Returns:
        Tuple of (is_valid, warning_message)
    """
    caps = get_platform_capabilities(platform)

    if scale_factor <= 0:
        return False, "Scale factor must be positive"

    if scale_factor > caps.max_recommended_sf:
        message = (
            f"Scale factor {scale_factor} exceeds recommended limit of {caps.max_recommended_sf} "
            f"for {caps.platform_name}.\n"
            f"Estimated memory: ~{caps.estimate_memory_for_sf(scale_factor):.1f} GB\n"
        )

        if caps.notes:
            message += f"Note: {caps.notes[0]}"

        if strict:
            return False, message
        return True, message

    return True, None


def format_memory_warning(check_result: MemoryCheckResult) -> str:
    """Format a memory check result as a warning message.

    Args:
        check_result: MemoryCheckResult from check_sufficient_memory

    Returns:
        Formatted warning message
    """
    lines = [check_result.message, ""]

    if check_result.suggestions:
        lines.append("Suggestions:")
        for suggestion in check_result.suggestions:
            lines.append(f"  • {suggestion}")
        lines.append("")

    lines.append("To proceed anyway (not recommended):")
    lines.append("  benchbox run --ignore-memory-warnings ...")

    return "\n".join(lines)


def recommend_platform_for_sf(scale_factor: float) -> str:
    """Recommend the best platform for a scale factor.

    Args:
        scale_factor: TPC-H scale factor

    Returns:
        Recommended platform name
    """
    # For small scale factors, Polars is generally best
    if scale_factor <= 10:
        return "polars"

    # For medium scale factors
    if scale_factor <= 100:
        return "polars"  # With streaming

    # For large scale factors
    if scale_factor <= 1000:
        return "dask"

    # For very large scale factors
    return "pyspark"

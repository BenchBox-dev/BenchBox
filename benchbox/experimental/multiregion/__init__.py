"""Multi-region performance testing framework.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

This module provides tools for testing database performance across regions:
- Region configuration and endpoint management
- Cross-region latency measurement
- Data transfer tracking and cost estimation
- Multi-region benchmark orchestration
"""

from benchbox.experimental.multiregion.config import (
    CloudProvider,
    MultiRegionConfig,
    Region,
    RegionConfig,
)
from benchbox.experimental.multiregion.latency import (
    LatencyMeasurement,
    LatencyMeasurer,
    LatencyProfile,
)
from benchbox.experimental.multiregion.orchestrator import (
    MultiRegionBenchmark,
    MultiRegionResult,
    RegionBenchmarkResult,
)
from benchbox.experimental.multiregion.transfer import (
    DataTransfer,
    TransferCostEstimator,
    TransferTracker,
)

__all__ = [
    # Config
    "Region",
    "RegionConfig",
    "MultiRegionConfig",
    "CloudProvider",
    # Latency
    "LatencyMeasurement",
    "LatencyProfile",
    "LatencyMeasurer",
    # Transfer
    "DataTransfer",
    "TransferTracker",
    "TransferCostEstimator",
    # Orchestration
    "MultiRegionBenchmark",
    "MultiRegionResult",
    "RegionBenchmarkResult",
]

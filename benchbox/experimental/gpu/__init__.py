"""GPU acceleration benchmarking module.

Provides GPU detection, capability checking, and benchmarking for GPU-accelerated
DataFrame operations using RAPIDS cuDF.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from .benchmark import GPUBenchmark, GPUBenchmarkResults, GPUQueryResult
from .capabilities import GPUCapabilities, GPUDevice, GPUInfo, detect_gpu, get_gpu_capabilities
from .metrics import GPUMetrics, GPUMetricsCollector

__all__ = [
    # Detection
    "detect_gpu",
    "get_gpu_capabilities",
    "GPUCapabilities",
    "GPUDevice",
    "GPUInfo",
    # Metrics
    "GPUMetrics",
    "GPUMetricsCollector",
    # Benchmark
    "GPUBenchmark",
    "GPUBenchmarkResults",
    "GPUQueryResult",
]

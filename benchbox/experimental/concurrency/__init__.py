"""Concurrency testing framework for database workload analysis.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

This module provides tools for testing database performance under concurrent load:
- Generic concurrent query execution with configurable patterns
- Queue analysis and wait time measurement
- Connection pool stress testing
- Workload pattern simulation (steady, burst, ramp-up, spike)
- Contention detection and bottleneck identification
"""

from benchbox.experimental.concurrency.analyzer import (
    ConcurrencyAnalyzer,
    ContentionAnalysis,
    QueueAnalysis,
    ScalingAnalysis,
)
from benchbox.experimental.concurrency.executor import (
    ConcurrentLoadConfig,
    ConcurrentLoadExecutor,
    ConcurrentLoadResult,
    StreamResult,
)
from benchbox.experimental.concurrency.patterns import (
    BurstPattern,
    RampUpPattern,
    SpikePattern,
    SteadyPattern,
    StepPattern,
    WavePattern,
    WorkloadPattern,
    WorkloadPhase,
)
from benchbox.experimental.concurrency.pool_tester import (
    ConnectionPoolTester,
    PoolTestConfig,
    PoolTestResult,
)

__all__ = [
    # Executor
    "ConcurrentLoadExecutor",
    "ConcurrentLoadConfig",
    "ConcurrentLoadResult",
    "StreamResult",
    # Patterns
    "WorkloadPattern",
    "WorkloadPhase",
    "SteadyPattern",
    "BurstPattern",
    "RampUpPattern",
    "SpikePattern",
    "StepPattern",
    "WavePattern",
    # Analysis
    "ConcurrencyAnalyzer",
    "QueueAnalysis",
    "ContentionAnalysis",
    "ScalingAnalysis",
    # Pool Testing
    "ConnectionPoolTester",
    "PoolTestConfig",
    "PoolTestResult",
]

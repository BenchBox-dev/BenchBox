"""Shared throughput-test infrastructure for TPC throughput benchmarks.

Provides the unified ``ThroughputStreamResult`` / ``ThroughputResult`` model
and the ``StreamRunner`` concurrent executor, factored out of the per-spec
TPC-H and TPC-DS throughput_test modules.
"""

from benchbox.core.throughput.result import ThroughputResult, ThroughputStreamResult
from benchbox.core.throughput.runner import StreamRunner

__all__ = [
    "StreamRunner",
    "ThroughputResult",
    "ThroughputStreamResult",
]

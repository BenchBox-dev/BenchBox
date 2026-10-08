#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-DS specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from benchbox.core.tpcds.benchmark import TPCDSBenchmark
    from benchbox.core.tpcds.queries import TPCDSQueryManager
    from benchbox.core.tpcds.streams import TPCDSStreamManager, create_standard_streams

    print("✅ Core TPC-DS imports successful")

    from benchbox.monitoring import PerformanceMonitor
    from tests.performance.test_tpcds_performance import TestTPCDSPerformance

    print("✅ Performance test module import successful")

    monitor = PerformanceMonitor()
    monitor.increment_counter("test", 5)
    assert monitor.summary()["counters"]["test"] == 5
    print("✅ PerformanceMonitor counter functionality works")

    import time

    with monitor.time_operation("test_op"):
        time.sleep(0.001)

    summary = monitor.summary()
    assert "test_op" in summary["timings"]
    assert summary["timings"]["test_op"]["count"] == 1
    print("✅ Timing context manager works")

    print("\n✅ All tests passed! The TPC-DS performance test file has been successfully fixed.")

except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    sys.exit(1)

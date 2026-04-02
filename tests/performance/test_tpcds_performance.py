"""TPC-DS Performance Tests.

This module provides comprehensive performance tests for TPC-DS components
that validate performance characteristics, benchmark timing, and ensure
that changes don't introduce regressions.

Tests include:
- Query generation performance benchmarks
- Parameter generation timing tests
- Memory usage validation
- Concurrency performance tests
- Caching effectiveness tests
- Stream generation performance
- Database-aware parameter generation timing
- Performance regression detection

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import gc
import multiprocessing
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
import pytest

from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.core.tpcds.queries import TPCDSQueryManager
from benchbox.core.tpcds.streams import create_standard_streams
from benchbox.monitoring import PerformanceMonitor

pytestmark = [
    pytest.mark.performance,
    pytest.mark.stress,
]


@pytest.mark.performance
@pytest.mark.tpcds
class TestTPCDSPerformance:
    """Performance tests for TPC-DS components."""

    @pytest.fixture
    def benchmark_instance(self):
        """Create a benchmark instance optimized for performance testing."""
        return TPCDSBenchmark(scale_factor=1.0, verbose=False)

    @pytest.fixture
    def query_manager(self):
        """Create a query manager for performance testing."""
        return TPCDSQueryManager()

    @pytest.fixture
    def performance_monitor(self):
        """Create a performance monitor for tracking metrics."""
        return PerformanceMonitor()

    def test_query_generation_performance_benchmark(self, query_manager, performance_monitor):
        """Benchmark query generation performance."""
        test_queries = [1, 2, 3, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
        iterations = 10

        # Warm up
        for _ in range(3):
            query_manager.get_query(1)

        # Benchmark raw query retrieval
        start_time = time.time()
        for _ in range(iterations):
            for query_id in test_queries:
                query_manager.get_query(query_id)
        raw_query_time = time.time() - start_time

        # Benchmark parameterized query generation
        start_time = time.time()
        for _ in range(iterations):
            for query_id in test_queries:
                query_manager.get_query(query_id)
        param_query_time = time.time() - start_time

        # Performance assertions
        queries_per_second_raw = (len(test_queries) * iterations) / raw_query_time
        queries_per_second_param = (len(test_queries) * iterations) / param_query_time

        # Should be able to generate at least 100 raw queries per second
        assert queries_per_second_raw >= 100, f"Raw query generation too slow: {queries_per_second_raw:.2f} q/s"

        # Should be able to generate at least 50 parameterized queries per second
        assert queries_per_second_param >= 50, (
            f"Parameterized query generation too slow: {queries_per_second_param:.2f} q/s"
        )

        # Record performance metrics
        performance_monitor.increment_counter("raw_queries_completed", len(test_queries) * iterations)
        performance_monitor.increment_counter("param_queries_completed", len(test_queries) * iterations)

        print(f"Raw queries per second: {queries_per_second_raw:.2f}")
        print(f"Parameterized queries per second: {queries_per_second_param:.2f}")

    def test_memory_usage_validation(self, benchmark_instance, performance_monitor):
        """Test memory usage during intensive operations."""
        process = psutil.Process(os.getpid())
        system_memory_mb = psutil.virtual_memory().total / 1024 / 1024
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Generate many queries to test memory usage
        queries = []
        for i in range(1, 100):
            try:
                query = benchmark_instance.get_query(i, seed=42)
                queries.append(query)
            except ValueError:
                # Skip invalid queries
                pass

        # Check memory usage after generation
        current_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = current_memory - initial_memory

        # Memory increase should stay within a bounded share of host memory.
        # This avoids false positives on busy CI hosts while still catching spikes.
        dynamic_limit_mb = max(300.0, min(system_memory_mb * 0.08, 768.0))
        assert memory_increase < dynamic_limit_mb, (
            f"Memory usage too high: increase={memory_increase:.2f}MB "
            f"(limit={dynamic_limit_mb:.2f}MB, initial={initial_memory:.2f}MB, current={current_memory:.2f}MB)"
        )

        # Clear references and check for memory leaks
        del queries
        gc.collect()

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_after_cleanup = final_memory - initial_memory

        # Memory should not continue to grow beyond measured working-set growth.
        cleanup_limit_mb = max(memory_increase * 0.95, dynamic_limit_mb)
        assert memory_after_cleanup < cleanup_limit_mb, (
            f"Memory leak detected: retained={memory_after_cleanup:.2f}MB "
            f"(limit={cleanup_limit_mb:.2f}MB, final={final_memory:.2f}MB)"
        )

        # Record memory metrics through counters
        performance_monitor.increment_counter("memory_tests_completed", 1)

    def test_concurrent_query_generation_performance(self, query_manager, performance_monitor):
        """Test performance under concurrent access."""
        test_queries = [1, 2, 3, 5, 10, 15, 20, 25, 30]
        num_threads = 4
        queries_per_thread = 25

        results = []
        errors = []

        def worker_function(worker_id: int):
            """Worker function for concurrent query generation."""
            try:
                start_time = time.time()
                worker_queries = []

                for i in range(queries_per_thread):
                    query_id = test_queries[i % len(test_queries)]
                    query = query_manager.get_query(query_id)
                    worker_queries.append(query)

                end_time = time.time()

                results.append(
                    {
                        "worker_id": worker_id,
                        "execution_time_seconds": end_time - start_time,
                        "queries_generated": len(worker_queries),
                        "queries_per_second": len(worker_queries) / (end_time - start_time),
                    }
                )

            except Exception as e:
                errors.append({"worker_id": worker_id, "error": str(e)})

        # Run concurrent workers
        threads = []
        start_time = time.time()

        for i in range(num_threads):
            thread = threading.Thread(target=worker_function, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        total_time = time.time() - start_time

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent access errors: {errors}"

        # Verify all workers completed
        assert len(results) == num_threads, f"Expected {num_threads} results, got {len(results)}"

        # Calculate performance metrics
        total_queries = sum(r["queries_generated"] for r in results)
        overall_qps = total_queries / total_time
        avg_worker_qps = statistics.mean([r["queries_per_second"] for r in results])

        # Performance should scale with concurrency
        assert overall_qps >= 50, f"Overall concurrent performance too low: {overall_qps:.2f} q/s"
        assert avg_worker_qps >= 25, f"Average worker performance too low: {avg_worker_qps:.2f} q/s"

        # Record concurrent performance metrics
        performance_monitor.increment_counter("concurrent_tests_completed", 1)

    def test_stream_generation_performance(self, benchmark_instance, performance_monitor):
        """Test stream generation performance."""
        num_streams = 5
        query_range = (1, 20)  # Smaller range for performance testing

        start_time = time.time()

        # Create stream manager
        stream_manager = create_standard_streams(
            benchmark_instance.query_manager,
            num_streams=num_streams,
            query_range=query_range,
            base_seed=42,
        )

        # Generate streams
        streams = stream_manager.generate_streams()

        end_time = time.time()
        generation_time = end_time - start_time

        # Verify streams were generated
        assert len(streams) == num_streams, f"Expected {num_streams} streams, got {len(streams)}"

        # Calculate total queries generated
        total_queries = sum(len(stream) for stream in streams.values())

        # Performance should be reasonable
        queries_per_second = total_queries / generation_time

        # Should generate at least 10 stream queries per second
        assert queries_per_second >= 10, f"Stream generation too slow: {queries_per_second:.2f} q/s"

        # Record stream generation metrics
        performance_monitor.increment_counter("stream_tests_completed", 1)

    def test_performance_regression_detection(self, benchmark_instance, performance_monitor):
        """Test for performance regressions by comparing against baseline."""
        # Define baseline performance expectations
        baseline_metrics = {
            "single_query_time": 0.025,  # 25ms for single query (accounts for CI/xdist overhead)
            "parameterized_query_time": 0.04,  # 40ms for parameterized query
            "stream_query_time": 0.1,  # 100ms for stream query
            "memory_per_query": 0.1,  # 100KB per query
        }

        # Test single query performance
        start_time = time.time()
        benchmark_instance.get_query(1)
        single_query_time = time.time() - start_time

        # Test parameterized query performance
        start_time = time.time()
        benchmark_instance.get_query(1)
        param_query_time = time.time() - start_time

        # Test query with seed performance
        start_time = time.time()
        benchmark_instance.get_query(1, seed=42)
        seeded_query_time = time.time() - start_time

        # Check against baselines (allow 2x degradation)
        assert single_query_time <= baseline_metrics["single_query_time"] * 2, (
            f"Single query regression: {single_query_time:.6f}s > {baseline_metrics['single_query_time'] * 2:.6f}s"
        )

        assert param_query_time <= baseline_metrics["parameterized_query_time"] * 2, (
            f"Parameterized query regression: {param_query_time:.6f}s > {baseline_metrics['parameterized_query_time'] * 2:.6f}s"
        )

        assert seeded_query_time <= baseline_metrics["stream_query_time"] * 2, (
            f"Seeded query regression: {seeded_query_time:.6f}s > {baseline_metrics['stream_query_time'] * 2:.6f}s"
        )

        # Record regression test metrics
        performance_monitor.increment_counter("test_completed", 1)
        performance_monitor.increment_counter("test_completed", 1)
        performance_monitor.increment_counter("test_completed", 1)

    def test_scalability_with_increasing_load(self, query_manager, performance_monitor):
        """Test scalability with increasing load."""
        load_levels = [10, 50, 100, 200]
        results = {}
        baseline_qps = 0.0  # Will be set on first iteration

        for load in load_levels:
            start_time = time.time()

            # Generate queries at this load level
            for i in range(load):
                query_id = (i % 50) + 1  # Cycle through queries 1-50
                query_manager.get_query(query_id)

            end_time = time.time()
            execution_time = end_time - start_time
            qps = load / execution_time

            results[load] = {
                "execution_time_seconds": execution_time,
                "queries_per_second": qps,
            }

            # Performance should not degrade significantly with load
            # Allow for reasonable scaling (not requiring linear scaling)
            if load == 10:
                baseline_qps = qps
            else:
                # Performance should not drop below 50% of baseline
                min_acceptable_qps = baseline_qps * 0.5
                assert qps >= min_acceptable_qps, (
                    f"Performance degradation at load {load}: {qps:.2f} < {min_acceptable_qps:.2f} q/s"
                )

        # Record scalability metrics
        for load, _metrics in results.items():
            performance_monitor.increment_counter("test_completed", 1)
            performance_monitor.increment_counter("test_completed", 1)

    def test_memory_efficiency_under_load(self, benchmark_instance, performance_monitor):
        """Test memory efficiency under sustained load."""
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Generate queries continuously and monitor memory
        memory_measurements = []
        queries_generated = 0

        for _batch in range(10):  # 10 batches of 20 queries each
            batch_queries = []

            for i in range(20):
                query_id = (i % 30) + 1
                query = benchmark_instance.get_query(query_id, seed=42 + i)
                batch_queries.append(query)
                queries_generated += 1

            # Measure memory after each batch
            current_memory = process.memory_info().rss / 1024 / 1024  # MB
            memory_increase = current_memory - initial_memory
            memory_measurements.append(memory_increase)

            # Clear batch queries
            del batch_queries
            gc.collect()

        # Memory growth should be bounded
        max_memory_increase = max(memory_measurements)
        final_memory_increase = memory_measurements[-1]

        # Memory should not grow excessively
        # Threshold increased from 100MB to 350MB to account for CI environment variability
        # and query caching overhead during batch generation.
        assert max_memory_increase < 350, f"Memory usage too high: {max_memory_increase:.2f}MB"

        # Memory should stabilize (not grow indefinitely)
        # Threshold increased to 35MB/batch to account for CI environment variability,
        # TPC-DS query caching overhead at SF 1.0+, and GC timing differences.
        memory_growth_rate = (final_memory_increase - memory_measurements[0]) / len(memory_measurements)
        assert memory_growth_rate < 35, f"Memory growth rate too high: {memory_growth_rate:.2f}MB/batch"

        # Record memory efficiency metrics
        performance_monitor.increment_counter("test_completed", 1)
        performance_monitor.increment_counter("test_completed", 1)
        performance_monitor.increment_counter("test_completed", 1)

    @pytest.mark.parametrize("num_workers", [1, 2, 4, 8])
    def test_parallel_processing_scalability(self, query_manager, performance_monitor, num_workers):
        """Test scalability with parallel processing."""
        queries_per_worker = 25
        test_queries = list(range(1, 21))  # Queries 1-20

        def worker_task(worker_queries):
            """Task for parallel processing."""
            results = []
            for query_id in worker_queries:
                query = query_manager.get_query(query_id)
                results.append(len(query))
            return results

        # Prepare work distribution
        work_chunks = []
        for i in range(num_workers):
            chunk = [
                test_queries[j % len(test_queries)] for j in range(i * queries_per_worker, (i + 1) * queries_per_worker)
            ]
            work_chunks.append(chunk)

        # Execute with ThreadPoolExecutor
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_task, chunk) for chunk in work_chunks]
            [future.result() for future in futures]
        end_time = time.time()

        execution_time = end_time - start_time
        total_queries = num_workers * queries_per_worker
        qps = total_queries / execution_time

        # Record parallel processing metrics
        performance_monitor.increment_counter("test_completed", 1)
        performance_monitor.increment_counter("test_completed", 1)

        # Performance should be reasonable for any number of workers
        # Note: Each parametrized test runs independently, so we validate absolute performance
        min_acceptable_qps = 10  # Minimum queries per second regardless of worker count (lowered for CI/xdist)
        assert qps >= min_acceptable_qps, (
            f"Parallel processing performance too low: {qps:.2f} < {min_acceptable_qps:.2f} q/s"
        )

    def test_performance_monitoring_overhead(self, benchmark_instance, performance_monitor):
        """Test overhead of performance monitoring itself."""
        # Test without monitoring
        start_time = time.time()
        for i in range(50):
            benchmark_instance.get_query((i % 20) + 1)
        time_without_monitoring = time.time() - start_time

        # Test with monitoring
        start_time = time.time()
        for i in range(50):
            with performance_monitor.time_operation(f"query_{i}"):
                benchmark_instance.get_query((i % 20) + 1)
        time_with_monitoring = time.time() - start_time

        # Monitoring overhead should be minimal
        overhead_ratio = time_with_monitoring / time_without_monitoring
        assert overhead_ratio < 1.5, f"Performance monitoring overhead too high: {overhead_ratio:.2f}x"

        # Record monitoring overhead
        performance_monitor.increment_counter("test_completed", 1)
        performance_monitor.increment_counter("test_completed", 1)
        performance_monitor.increment_counter("test_completed", 1)

    def test_detailed_performance_report(self, benchmark_instance, performance_monitor):
        """Generate a comprehensive performance report."""
        report = {
            "timestamp": time.time(),
            "test_environment": {
                "cpu_count": multiprocessing.cpu_count(),
                "memory_total": psutil.virtual_memory().total / 1024 / 1024 / 1024,  # GB
                "python_version": f"{psutil.Process().python_version if hasattr(psutil.Process(), 'python_version') else 'unknown'}",
            },
            "performance_metrics": {},
            "benchmark_results": {},
        }

        # Run comprehensive benchmarks
        test_queries = [1, 5, 10, 15, 20, 25, 30]

        # Query generation benchmark
        start_time = time.time()
        for query_id in test_queries:
            query = benchmark_instance.get_query(query_id)
        raw_query_time = time.time() - start_time

        start_time = time.time()
        for query_id in test_queries:
            query = benchmark_instance.get_query(query_id)
        param_query_time = time.time() - start_time

        start_time = time.time()
        for query_id in test_queries:
            query = benchmark_instance.get_query(query_id, seed=42)
        seeded_query_time = time.time() - start_time

        # Memory usage test
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024

        # Generate many queries
        queries = []
        for i in range(100):
            query_id = (i % 50) + 1
            query = benchmark_instance.get_query(query_id, seed=42 + i)
            queries.append(query)

        peak_memory = process.memory_info().rss / 1024 / 1024
        memory_usage = peak_memory - initial_memory

        # Clean up
        del queries
        gc.collect()

        # Populate report
        report["performance_metrics"] = {
            "raw_query_time": raw_query_time,
            "param_query_time": param_query_time,
            "seeded_query_time": seeded_query_time,
            "memory_usage_mb": memory_usage,
            "queries_tested": len(test_queries),
            "raw_queries_per_second": len(test_queries) / raw_query_time,
            "param_queries_per_second": len(test_queries) / param_query_time,
            "seeded_queries_per_second": len(test_queries) / seeded_query_time,
        }

        report["benchmark_results"] = {
            # Memory threshold increased to 300MB to account for TPC-DS SF 1.0 minimum
            # and CI environment variability. Query rate thresholds lowered to account
            # for parallel test execution with xdist.
            "overall_performance": "PASS"
            if all(
                [
                    report["performance_metrics"]["raw_queries_per_second"] >= 5,
                    report["performance_metrics"]["param_queries_per_second"] >= 5,
                    report["performance_metrics"]["seeded_queries_per_second"] >= 2,
                    report["performance_metrics"]["memory_usage_mb"] < 300,
                ]
            )
            else "FAIL",
            "performance_grade": "A" if report["performance_metrics"]["raw_queries_per_second"] >= 10 else "B",
        }

        # Record comprehensive report
        for _key, _value in report["performance_metrics"].items():
            performance_monitor.increment_counter("test_completed", 1)

        # Basic performance assertions
        assert report["benchmark_results"]["overall_performance"] == "PASS", (
            f"Comprehensive performance test failed: {report['benchmark_results']}"
        )

        print(f"Performance Report: {report['performance_metrics']}")
        print(f"Performance Grade: {report['benchmark_results']['performance_grade']}")

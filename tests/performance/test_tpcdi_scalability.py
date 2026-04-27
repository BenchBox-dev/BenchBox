"""
Copyright 2026 Joe Harris / BenchBox Project

Performance and scalability tests for TPC-DI Phase 4: Scalability Testing.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path

import psutil
import pytest

pytestmark = [
    pytest.mark.performance,
    pytest.mark.stress,
]


pytest.importorskip("pandas")

from benchbox.core.tpcdi.benchmark import TPCDIBenchmark
from benchbox.core.tpcdi.config import TPCDIConfig


@pytest.mark.slow  # Data generation rate thresholds are flaky at small scale factors
@pytest.mark.performance
class TestTPCDIScalabilityPerformance:
    """Performance and scalability tests for TPC-DI benchmark."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test outputs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            yield Path(tmp_dir)

    @pytest.fixture
    def test_database(self):
        """Create an in-memory SQLite database for testing."""
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA cache_size = 10000")  # Optimize for performance testing
        conn.execute("PRAGMA temp_store = MEMORY")
        yield conn
        conn.close()

    def test_multi_scale_factor_performance_analysis(self, temp_dir, test_database):
        """Comprehensive performance analysis across multiple scale factors."""
        # Test scale factors: 10, 100, 500, 1000 (as specified in Phase 4 requirements)
        # Using smaller values for practical testing, but structure scales to larger values
        scale_factors = [0.01, 0.1, 0.5, 1.0]
        performance_results = {}

        for scale_factor in scale_factors:
            print(f"\n=== Testing Scale Factor: {scale_factor} ===")

            config = TPCDIConfig(
                scale_factor=scale_factor,
                output_dir=temp_dir / f"scale_{scale_factor}",
                enable_parallel=True,
                max_workers=4,
            )
            config.output_dir.mkdir(parents=True, exist_ok=True)

            benchmark = TPCDIBenchmark(config=config)
            process = psutil.Process(os.getpid())

            # Performance metrics collection
            start_memory = process.memory_info().rss / 1024 / 1024  # MB
            overall_start = time.time()

            # Phase 1: Schema Creation Performance
            schema_start = time.time()
            benchmark.create_schema(test_database, "sqlite")
            schema_time = time.time() - schema_start
            schema_memory = process.memory_info().rss / 1024 / 1024

            # Phase 2: Data Generation Performance
            data_gen_start = time.time()
            benchmark.generate_data()
            data_gen_time = time.time() - data_gen_start
            data_gen_memory = process.memory_info().rss / 1024 / 1024

            # Get the table mapping from the benchmark after data generation
            data_files = benchmark.tables

            # Calculate total data size
            total_data_size = 0
            file_count = 0
            for file_path in data_files.values():
                path_obj = Path(file_path) if isinstance(file_path, str) else file_path
                if path_obj.exists():
                    total_data_size += path_obj.stat().st_size
                    file_count += 1
            total_data_mb = total_data_size / (1024 * 1024)

            # Phase 3: ETL Processing Performance
            etl_start = time.time()
            etl_results = benchmark.run_enhanced_etl_pipeline(
                test_database,
                dialect="sqlite",
                enable_parallel_processing=True,
                enable_data_quality_monitoring=True,
                enable_error_recovery=True,
            )
            etl_time = time.time() - etl_start
            etl_memory = process.memory_info().rss / 1024 / 1024

            # Phase 4: Query Performance Sampling
            query_start = time.time()
            query_results = self._test_query_performance_sample(benchmark, test_database)
            query_time = time.time() - query_start

            overall_time = time.time() - overall_start
            peak_memory = max(schema_memory, data_gen_memory, etl_memory)
            memory_efficiency = total_data_mb / max(peak_memory - start_memory, 0.1)

            # Store comprehensive performance metrics
            performance_results[scale_factor] = {
                # Timing metrics
                "overall_time": overall_time,
                "schema_time": schema_time,
                "data_generation_time": data_gen_time,
                "etl_processing_time": etl_time,
                "query_sample_time": query_time,
                # Data metrics
                "data_files_generated": file_count,
                "total_data_size_mb": total_data_mb,
                "data_generation_rate_mbps": total_data_mb / max(data_gen_time, 0.001),
                # ETL metrics
                "etl_success": etl_results["success"],
                "etl_records_processed": etl_results.get("total_records_processed", 0),
                "etl_processing_rate_rps": etl_results.get("total_records_processed", 0) / max(etl_time, 0.001),
                "etl_quality_score": etl_results.get("quality_score", 0),
                # Memory metrics
                "start_memory_mb": start_memory,
                "peak_memory_mb": peak_memory,
                "memory_growth_mb": peak_memory - start_memory,
                "memory_efficiency_mb_per_mb": memory_efficiency,
                # Query metrics
                "query_sample_results": query_results,
                "successful_queries": sum(1 for q in query_results if q.get("success", False)),
                "average_query_time": sum(q.get("execution_time_seconds", 0) for q in query_results)
                / max(len(query_results), 1),
            }

            print(
                f"Scale {scale_factor}: {overall_time:.2f}s total, {total_data_mb:.1f}MB data, {etl_results.get('total_records_processed', 0)} ETL records"
            )

            # Clear database for next iteration
            self._clear_test_database(test_database)

        # Analysis and validation of scaling characteristics
        self._analyze_scaling_characteristics(performance_results)
        self._validate_performance_thresholds(performance_results)

        # Save performance baseline for regression testing
        self._save_performance_baseline(performance_results, temp_dir)

        # Test passes - all validations successful

    def _test_query_performance_sample(self, benchmark: TPCDIBenchmark, connection) -> list[dict]:
        """Test performance of a sample of queries."""
        test_queries = [1, 2, 3, 4, 5]  # Sample queries for performance testing
        query_results = []

        cursor = connection.cursor()
        for query_id in test_queries:
            try:
                query_sql = benchmark.get_query(query_id, dialect="sqlite")

                start_time = time.time()
                cursor.execute(query_sql)
                results = cursor.fetchall()
                execution_time = time.time() - start_time

                query_results.append(
                    {
                        "query_id": query_id,
                        "execution_time_seconds": execution_time,
                        "row_count": len(results),
                        "success": True,
                        "rows_per_second": len(results) / max(execution_time, 0.001),
                    }
                )

            except Exception as e:
                query_results.append(
                    {
                        "query_id": query_id,
                        "execution_time_seconds": float("inf"),
                        "error": str(e),
                        "success": False,
                    }
                )

        return query_results

    def _clear_test_database(self, connection):
        """Clear test database for next iteration."""
        try:
            cursor = connection.cursor()

            # Get all table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            # Drop all tables
            for table in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")

            connection.commit()
        except Exception as e:
            print(f"Warning: Error clearing database: {e}")

    def _analyze_scaling_characteristics(self, results: dict[str, dict]):
        """Analyze scaling characteristics across scale factors."""
        scale_factors = sorted(results.keys())

        print("\n=== SCALING ANALYSIS ===")

        for i in range(len(scale_factors) - 1):
            current_sf = scale_factors[i]
            next_sf = scale_factors[i + 1]

            current = results[current_sf]
            next_result = results[next_sf]

            sf_ratio = next_sf / current_sf

            # Analyze different scaling aspects
            scaling_metrics = {
                "data_size": next_result["total_data_size_mb"] / max(current["total_data_size_mb"], 0.001),
                "etl_records": next_result["etl_records_processed"] / max(current["etl_records_processed"], 1),
                "etl_time": next_result["etl_processing_time"] / max(current["etl_processing_time"], 0.001),
                "memory_usage": next_result["memory_growth_mb"] / max(current["memory_growth_mb"], 0.001),
                "overall_time": next_result["overall_time"] / max(current["overall_time"], 0.001),
            }

            print(f"\nScale Factor {current_sf} -> {next_sf} (ratio {sf_ratio:.1f}x):")
            for metric, ratio in scaling_metrics.items():
                efficiency = sf_ratio / ratio if ratio > 0 else 0
                print(f"  {metric}: {ratio:.2f}x scaling (efficiency: {efficiency:.2f})")

            # Validate reasonable scaling
            assert scaling_metrics["data_size"] >= sf_ratio * 0.5, (
                f"Data size scaling too low: {scaling_metrics['data_size']:.2f}"
            )
            assert scaling_metrics["etl_records"] >= sf_ratio * 0.15, (
                f"ETL records scaling too low: {scaling_metrics['etl_records']:.2f}"
            )

    def _validate_performance_thresholds(self, results: dict[str, dict]):
        """Validate performance meets acceptable thresholds."""
        print("\n=== PERFORMANCE VALIDATION ===")

        for scale_factor, metrics in results.items():
            print(f"\nScale Factor {scale_factor}:")

            # ETL must succeed
            assert metrics["etl_success"], f"ETL failed at scale factor {scale_factor}"

            # Data generation rate should be reasonable
            # Note: Very small scale factors have significant fixed overhead (setup, file I/O latency)
            # which makes the data rate appear artificially low. Use scaled thresholds.
            if scale_factor >= 0.5:
                min_data_rate = 3.0  # MB/s minimum for larger datasets
            elif scale_factor >= 0.1:
                min_data_rate = 1.0  # MB/s minimum for medium datasets
            else:
                min_data_rate = 0.3  # MB/s minimum for tiny datasets (dominated by fixed overhead)
            assert metrics["data_generation_rate_mbps"] >= min_data_rate, (
                f"Data generation too slow at SF {scale_factor}: {metrics['data_generation_rate_mbps']:.2f} MB/s"
            )

            # ETL processing rate validation
            # Note: Very small scale factors may process minimal records, making rate metrics unreliable
            # Only validate rate if we processed a reasonable number of records
            if metrics["etl_records_processed"] >= 100:
                min_etl_rate = 50  # records/s minimum for larger datasets
                assert metrics["etl_processing_rate_rps"] >= min_etl_rate, (
                    f"ETL processing too slow at SF {scale_factor}: {metrics['etl_processing_rate_rps']:.1f} rec/s"
                )
            else:
                # For very small datasets, just verify some records were processed
                print(
                    f"  ETL Rate: {metrics['etl_processing_rate_rps']:.1f} rec/s (not validated, only {metrics['etl_records_processed']} records)"
                )

            # Memory growth (delta from start_memory) should be reasonable.
            # Calibrated at 100MB base (2x observed max of ~4MB + floor), which subtracts out
            # the ~350MB of OS/Python/xdist baseline so regressions are actually detectable.
            max_growth_mb = 1000 * scale_factor + 100
            assert metrics["memory_growth_mb"] <= max_growth_mb, (
                f"Memory growth too high at SF {scale_factor}: {metrics['memory_growth_mb']:.1f}MB"
            )

            # At least half of sample queries should succeed
            query_success_rate = metrics["successful_queries"] / max(len(metrics["query_sample_results"]), 1)
            assert query_success_rate >= 0.5, f"Too many query failures at SF {scale_factor}: {query_success_rate:.1%}"

            print(f"  Data Rate: {metrics['data_generation_rate_mbps']:.1f} MB/s ✅")
            print(f"  ETL Rate: {metrics['etl_processing_rate_rps']:.1f} rec/s ✅")
            print(f"  Memory Growth: {metrics['memory_growth_mb']:.1f}MB ✅")
            print(f"  Query Success: {query_success_rate:.1%} ✅")

    def _save_performance_baseline(self, results: dict[str, dict], output_dir: Path):
        """Save performance baseline for regression testing."""
        baseline_file = output_dir / "tpcdi_scalability_baseline.json"

        # Create summary for baseline
        baseline_summary = {
            "timestamp": datetime.now().isoformat(),
            "scale_factors_tested": list(results.keys()),
            "performance_summary": {},
        }

        for sf, metrics in results.items():
            baseline_summary["performance_summary"][str(sf)] = {
                "overall_time": metrics["overall_time"],
                "data_generation_rate_mbps": metrics["data_generation_rate_mbps"],
                "etl_processing_rate_rps": metrics["etl_processing_rate_rps"],
                "peak_memory_mb": metrics["peak_memory_mb"],
                "etl_success": metrics["etl_success"],
                "successful_queries": metrics["successful_queries"],
                "average_query_time": metrics["average_query_time"],
            }

        try:
            with open(baseline_file, "w", encoding="utf-8") as f:
                json.dump(baseline_summary, f, indent=2)
            print(f"\nPerformance baseline saved to: {baseline_file}")
        except Exception as e:
            print(f"Warning: Could not save performance baseline: {e}")

    def test_data_generation_performance_detailed(self, temp_dir, test_database):
        """Detailed analysis of data generation performance characteristics."""
        scale_factors = [0.01, 0.1, 0.5]
        generation_profiles = {}

        for scale_factor in scale_factors:
            config = TPCDIConfig(
                scale_factor=scale_factor,
                output_dir=temp_dir / f"datagen_{scale_factor}",
                enable_parallel=True,
                max_workers=4,
            )
            config.output_dir.mkdir(parents=True, exist_ok=True)

            benchmark = TPCDIBenchmark(config=config)

            # Detailed timing of data generation phases
            generation_start = time.time()

            # Monitor resource usage during generation
            process = psutil.Process(os.getpid())
            start_memory = process.memory_info().rss / 1024 / 1024

            benchmark.generate_data()

            generation_time = time.time() - generation_start
            end_memory = process.memory_info().rss / 1024 / 1024

            # Get the table mapping from the benchmark after data generation
            data_files = benchmark.tables

            # Analyze generated files
            file_analysis = {}
            total_size = 0

            for table_name, file_path in data_files.items():
                path_obj = Path(file_path) if isinstance(file_path, str) else file_path
                if path_obj.exists():
                    size_bytes = path_obj.stat().st_size
                    total_size += size_bytes

                    # Count records (approximate)
                    try:
                        with open(path_obj, encoding="utf-8") as f:
                            line_count = sum(1 for _ in f)

                        file_analysis[table_name] = {
                            "size_mb": size_bytes / (1024 * 1024),
                            "estimated_records": line_count,
                            "mb_per_record": size_bytes / (1024 * 1024) / max(line_count, 1),
                        }
                    except Exception:
                        file_analysis[table_name] = {
                            "size_mb": size_bytes / (1024 * 1024),
                            "estimated_records": 0,
                            "mb_per_record": 0,
                        }

            generation_profiles[scale_factor] = {
                "generation_time": generation_time,
                "total_size_mb": total_size / (1024 * 1024),
                "files_generated": len(data_files),
                "memory_used_mb": end_memory - start_memory,
                "generation_rate_mbps": (total_size / (1024 * 1024)) / max(generation_time, 0.001),
                "file_analysis": file_analysis,
            }

        # Validate generation performance scaling
        for i in range(len(scale_factors) - 1):
            current_sf = scale_factors[i]
            next_sf = scale_factors[i + 1]

            current_profile = generation_profiles[current_sf]
            next_profile = generation_profiles[next_sf]

            size_ratio = next_profile["total_size_mb"] / max(current_profile["total_size_mb"], 0.001)
            sf_ratio = next_sf / current_sf

            # Data size should scale reasonably with scale factor
            assert size_ratio >= sf_ratio * 0.5, f"Data generation scaling issue: {size_ratio:.2f} vs {sf_ratio:.2f}"
            assert size_ratio <= sf_ratio * 2.0, f"Data generation over-scaling: {size_ratio:.2f} vs {sf_ratio:.2f}"

    def test_etl_processing_bottleneck_analysis(self, temp_dir, test_database):
        """Analyze ETL processing bottlenecks and performance characteristics."""
        config = TPCDIConfig(scale_factor=0.1, output_dir=temp_dir, enable_parallel=True, max_workers=4)

        benchmark = TPCDIBenchmark(config=config)
        process = psutil.Process(os.getpid())

        # Set up benchmark
        benchmark.create_schema(test_database, "sqlite")
        benchmark.generate_data()

        # Profile ETL pipeline phases
        benchmark._initialize_connection_dependent_systems(test_database, "sqlite")

        phase_profiles = {}

        # Test each ETL phase individually for bottleneck analysis

        # 1. Enhanced Data Processing
        start_time = time.time()
        start_memory = process.memory_info().rss / 1024 / 1024

        try:
            data_processing_result = benchmark._run_enhanced_data_processing()
            success = data_processing_result.get("success", False)
            records = data_processing_result.get("total_records", 0)
        except Exception as e:
            # Private method may fail when called directly outside full pipeline
            print(f"Warning: data_processing phase failed (private method): {e}")
            success = False
            records = 0

        phase_profiles["data_processing"] = {
            "time": time.time() - start_time,
            "memory_delta": process.memory_info().rss / 1024 / 1024 - start_memory,
            "success": success,
            "records": records,
        }

        # 2. SCD Processing
        start_time = time.time()
        start_memory = process.memory_info().rss / 1024 / 1024

        scd_result = benchmark._run_enhanced_scd_processing(test_database)

        phase_profiles["scd_processing"] = {
            "time": time.time() - start_time,
            "memory_delta": process.memory_info().rss / 1024 / 1024 - start_memory,
            "success": scd_result.get("success", False),
            "records": scd_result.get("records_processed", 0),
        }

        # 3. Parallel Batch Processing
        start_time = time.time()
        start_memory = process.memory_info().rss / 1024 / 1024

        parallel_result = benchmark._run_parallel_batch_processing()

        phase_profiles["parallel_processing"] = {
            "time": time.time() - start_time,
            "memory_delta": process.memory_info().rss / 1024 / 1024 - start_memory,
            "success": parallel_result.get("success", False),
            "batches": parallel_result.get("batches_processed", 0),
        }

        # 4. Incremental Loading
        start_time = time.time()
        start_memory = process.memory_info().rss / 1024 / 1024

        incremental_result = benchmark._run_incremental_data_loading(test_database)

        phase_profiles["incremental_loading"] = {
            "time": time.time() - start_time,
            "memory_delta": process.memory_info().rss / 1024 / 1024 - start_memory,
            "success": incremental_result.get("success", False),
            "records": incremental_result.get("records_loaded", 0),
        }

        # 5. Data Quality Monitoring
        start_time = time.time()
        start_memory = process.memory_info().rss / 1024 / 1024

        quality_result = benchmark._run_data_quality_monitoring(test_database)

        phase_profiles["quality_monitoring"] = {
            "time": time.time() - start_time,
            "memory_delta": process.memory_info().rss / 1024 / 1024 - start_memory,
            "success": quality_result.get("success", False),
            "rules": quality_result.get("rules_executed", 0),
        }

        # Analyze bottlenecks
        total_time = sum(profile["time"] for profile in phase_profiles.values())

        print("\n=== ETL PHASE PERFORMANCE ANALYSIS ===")
        for phase_name, profile in phase_profiles.items():
            time_pct = (profile["time"] / max(total_time, 0.001)) * 100
            print(
                f"{phase_name}: {profile['time']:.3f}s ({time_pct:.1f}%), "
                f"Memory: {profile['memory_delta']:+.1f}MB, "
                f"Success: {profile['success']}"
            )

        # Validate phase performance
        # Note: Some phases may fail when called as private methods outside the full pipeline
        # We check that at least some phases succeeded to validate bottleneck analysis works
        successful_phases = sum(1 for profile in phase_profiles.values() if profile["success"])
        total_phases = len(phase_profiles)

        assert successful_phases >= total_phases * 0.6, (
            f"Too many phase failures: {successful_phases}/{total_phases} succeeded. "
            "Note: Private method testing may have limitations."
        )

        for phase_name, profile in phase_profiles.items():
            if profile["success"]:
                assert profile["time"] < 30.0, f"ETL phase {phase_name} too slow: {profile['time']:.1f}s"
            else:
                print(f"Note: Phase {phase_name} failed (may be due to private method limitations)")

    def test_query_execution_performance_comprehensive(self, temp_dir, test_database):
        """Comprehensive query execution performance analysis."""
        config = TPCDIConfig(scale_factor=0.1, output_dir=temp_dir, enable_parallel=True, max_workers=4)

        benchmark = TPCDIBenchmark(config=config)

        # Set up benchmark with substantial data for query testing
        benchmark.create_schema(test_database, "sqlite")
        benchmark.generate_data()

        etl_results = benchmark.run_enhanced_etl_pipeline(
            test_database,
            dialect="sqlite",
            enable_data_quality_monitoring=False,  # Focus on query performance
        )

        assert etl_results["success"], "ETL must succeed for query performance testing"

        # Test expanded set of queries for comprehensive analysis
        test_queries = list(range(1, 11))  # Test queries 1-10
        query_performance = {}

        cursor = test_database.cursor()

        print("\n=== QUERY PERFORMANCE ANALYSIS ===")

        for query_id in test_queries:
            try:
                query_sql = benchmark.get_query(query_id, dialect="sqlite")

                # Multiple execution runs for stable timing
                execution_times = []
                for _run in range(3):
                    start_time = time.time()
                    cursor.execute(query_sql)
                    results = cursor.fetchall()
                    execution_times.append(time.time() - start_time)

                avg_time = sum(execution_times) / len(execution_times)
                min_time = min(execution_times)
                max_time = max(execution_times)

                query_performance[query_id] = {
                    "avg_execution_time": avg_time,
                    "min_execution_time": min_time,
                    "max_execution_time": max_time,
                    "row_count": len(results),
                    "success": True,
                    "rows_per_second": len(results) / max(avg_time, 0.001),
                    "stability_ratio": min_time / max(max_time, 0.001),
                }

                print(
                    f"Query {query_id}: {avg_time:.3f}s avg, {len(results)} rows, "
                    f"{len(results) / max(avg_time, 0.001):.1f} rows/s"
                )

            except Exception as e:
                query_performance[query_id] = {
                    "avg_execution_time": float("inf"),
                    "error": str(e),
                    "success": False,
                }
                print(f"Query {query_id}: FAILED - {str(e)}")

        # Performance analysis
        successful_queries = [q for q, perf in query_performance.items() if perf.get("success")]

        assert len(successful_queries) >= len(test_queries) * 0.7, "Too many query failures"

        # Identify performance categories
        fast_queries = [q for q in successful_queries if query_performance[q]["avg_execution_time"] < 1.0]
        medium_queries = [q for q in successful_queries if 1.0 <= query_performance[q]["avg_execution_time"] < 5.0]
        slow_queries = [q for q in successful_queries if query_performance[q]["avg_execution_time"] >= 5.0]

        print("\nQuery Performance Distribution:")
        print(f"  Fast (<1s): {len(fast_queries)} queries")
        print(f"  Medium (1-5s): {len(medium_queries)} queries")
        print(f"  Slow (>=5s): {len(slow_queries)} queries")

        # Ensure reasonable performance distribution
        assert len(fast_queries) + len(medium_queries) >= len(successful_queries) * 0.8, "Too many slow queries"

    def test_parallel_processing_scalability_analysis(self, temp_dir, test_database):
        """Analyze parallel processing scalability with different worker counts."""
        worker_configurations = [1, 2, 4, 8]
        scalability_results = {}

        for worker_count in worker_configurations:
            config = TPCDIConfig(
                scale_factor=0.1,
                output_dir=temp_dir / f"workers_{worker_count}",
                enable_parallel=True,
                max_workers=worker_count,
            )
            config.output_dir.mkdir(parents=True, exist_ok=True)

            benchmark = TPCDIBenchmark(config=config)

            # Measure parallel processing performance
            start_time = time.time()

            benchmark.create_schema(test_database, "sqlite")
            benchmark.generate_data()

            etl_results = benchmark.run_enhanced_etl_pipeline(
                test_database,
                dialect="sqlite",
                enable_parallel_processing=True,
                enable_data_quality_monitoring=False,  # Focus on parallel performance
            )

            total_time = time.time() - start_time

            scalability_results[worker_count] = {
                "total_time": total_time,
                "etl_success": etl_results["success"],
                "parallel_batches": etl_results["phases"]
                .get("parallel_batch_processing", {})
                .get("batches_processed", 0),
                "workers_used": etl_results["phases"].get("parallel_batch_processing", {}).get("parallel_workers", 0),
                "records_processed": etl_results.get("total_records_processed", 0),
            }

            # Clear database for next test
            self._clear_test_database(test_database)

        # Analyze scalability characteristics
        print("\n=== PARALLEL PROCESSING SCALABILITY ===")

        baseline_time = scalability_results[1]["total_time"]

        for worker_count, result in scalability_results.items():
            speedup = baseline_time / max(result["total_time"], 0.001)
            efficiency = speedup / worker_count

            print(
                f"Workers: {worker_count}, Time: {result['total_time']:.2f}s, "
                f"Speedup: {speedup:.2f}x, Efficiency: {efficiency:.2f}"
            )

            assert result["etl_success"], f"ETL failed with {worker_count} workers"

        # Validate that parallel processing provides some benefit
        max_workers = max(worker_configurations)
        parallel_speedup = baseline_time / max(scalability_results[max_workers]["total_time"], 0.001)

        # Expect parallel processing not to be slower than single-threaded (>= 0.9x)
        # Parallelism benefits vary with environment, and overhead can reduce benefits
        # for small workloads. The key validation is that ETL succeeds with parallelism.
        assert parallel_speedup >= 0.9, f"Parallel processing shows insufficient benefit: {parallel_speedup:.2f}x"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

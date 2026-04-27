#!/usr/bin/env python3
"""Test performance profiling and optimization tools.

This module provides comprehensive performance analysis for test execution:
- Memory usage profiling
- CPU profiling
- Test timing analysis
- Resource utilization monitoring
- Performance regression detection
- Optimization recommendations

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import gc
import json
import os
import statistics
import subprocess
import tempfile
import threading
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import psutil


@dataclass
class PerformanceMetrics:
    """Performance metrics for a single test or test suite."""

    name: str
    duration: float
    memory_peak: int  # bytes
    memory_average: int  # bytes
    cpu_percent: float
    cpu_time: float
    io_read_bytes: int
    io_write_bytes: int
    io_read_count: int
    io_write_count: int
    gc_collections: dict[int, int]
    thread_count: int
    file_descriptors: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class PerformanceBaseline:
    """Performance baseline for regression detection."""

    name: str
    duration_baseline: float
    memory_baseline: int
    cpu_baseline: float
    tolerance_percent: float = 10.0

    def is_regression(self, metrics: PerformanceMetrics) -> dict[str, bool]:
        """Check if metrics represent a performance regression."""
        tolerance = self.tolerance_percent / 100.0

        return {
            "duration": metrics.duration > self.duration_baseline * (1 + tolerance),
            "memory": metrics.memory_peak > self.memory_baseline * (1 + tolerance),
            "cpu": metrics.cpu_percent > self.cpu_baseline * (1 + tolerance),
        }


class ResourceMonitor:
    """Real-time resource monitoring during test execution."""

    def __init__(self, sample_interval: float = 0.1):
        self.sample_interval = sample_interval
        self.monitoring = False
        self.metrics: list[dict[str, Any]] = []
        self.monitor_thread: Optional[threading.Thread] = None
        self.process = psutil.Process()

    def start_monitoring(self) -> None:
        """Start resource monitoring."""
        self.monitoring = True
        self.metrics = []
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def stop_monitoring(self) -> None:
        """Stop resource monitoring."""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.0)

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self.monitoring:
            try:
                # Get current metrics
                with self.process.oneshot():
                    memory_info = self.process.memory_info()
                    cpu_percent = self.process.cpu_percent()
                    io_counters = self.process.io_counters()
                    num_threads = self.process.num_threads()
                    num_fds = self.process.num_fds()

                self.metrics.append(
                    {
                        "timestamp": time.time(),
                        "memory_rss": memory_info.rss,
                        "memory_vms": memory_info.vms,
                        "cpu_percent": cpu_percent,
                        "io_read_bytes": io_counters.read_bytes,
                        "io_write_bytes": io_counters.write_bytes,
                        "io_read_count": io_counters.read_count,
                        "io_write_count": io_counters.write_count,
                        "num_threads": num_threads,
                        "num_fds": num_fds,
                    }
                )

                time.sleep(self.sample_interval)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics from monitoring data."""
        if not self.metrics:
            return {}

        memory_rss = [m["memory_rss"] for m in self.metrics]
        cpu_percent = [m["cpu_percent"] for m in self.metrics]
        io_read = [m["io_read_bytes"] for m in self.metrics]
        io_write = [m["io_write_bytes"] for m in self.metrics]

        return {
            "duration": self.metrics[-1]["timestamp"] - self.metrics[0]["timestamp"],
            "memory_peak": max(memory_rss),
            "memory_average": statistics.mean(memory_rss),
            "cpu_max": max(cpu_percent),
            "cpu_average": statistics.mean(cpu_percent),
            "io_read_total": max(io_read) - min(io_read),
            "io_write_total": max(io_write) - min(io_write),
            "thread_count": self.metrics[-1]["num_threads"],
            "file_descriptors": self.metrics[-1]["num_fds"],
        }


class MemoryProfiler:
    """Memory profiling using tracemalloc."""

    def __init__(self):
        self.snapshots: list[tuple[str, Any]] = []
        self.enabled = False

    def start_profiling(self) -> None:
        """Start memory profiling."""
        tracemalloc.start()
        self.enabled = True
        self.snapshots = []

    def stop_profiling(self) -> None:
        """Stop memory profiling."""
        if self.enabled:
            tracemalloc.stop()
            self.enabled = False

    def take_snapshot(self, name: str) -> None:
        """Take a memory snapshot."""
        if self.enabled:
            snapshot = tracemalloc.take_snapshot()
            self.snapshots.append((name, snapshot))

    def get_memory_diff(self, start_name: str, end_name: str) -> dict[str, Any]:
        """Get memory difference between two snapshots."""
        start_snapshot = None
        end_snapshot = None

        for name, snapshot in self.snapshots:
            if name == start_name:
                start_snapshot = snapshot
            elif name == end_name:
                end_snapshot = snapshot

        if not start_snapshot or not end_snapshot:
            return {}

        top_stats = end_snapshot.compare_to(start_snapshot, "lineno")

        return {
            "total_diff": sum(stat.size_diff for stat in top_stats),
            "count_diff": sum(stat.count_diff for stat in top_stats),
            "top_differences": [
                {
                    "filename": stat.traceback.format()[-1],
                    "size_diff": stat.size_diff,
                    "count_diff": stat.count_diff,
                }
                for stat in top_stats[:10]
            ],
        }

    def get_top_memory_usage(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get top memory usage locations."""
        if not self.snapshots:
            return []

        _, latest_snapshot = self.snapshots[-1]
        top_stats = latest_snapshot.statistics("lineno")

        return [
            {
                "filename": stat.traceback.format()[-1],
                "size": stat.size,
                "count": stat.count,
            }
            for stat in top_stats[:limit]
        ]


class CPUProfiler:
    """CPU profiling using cProfile."""

    def __init__(self):
        self.profile_data: Optional[str] = None
        self.temp_file: Optional[str] = None

    @contextmanager
    def profile_context(self):
        """Context manager for CPU profiling."""
        import cProfile

        profiler = cProfile.Profile()
        profiler.enable()

        try:
            yield profiler
        finally:
            profiler.disable()

            # Save profile data
            self.temp_file = tempfile.mktemp(suffix=".prof")
            profiler.dump_stats(self.temp_file)

    def get_profile_stats(self, sort_by: str = "cumulative", limit: int = 20) -> list[dict[str, Any]]:
        """Get profile statistics."""
        if not self.temp_file or not os.path.exists(self.temp_file):
            return []

        import pstats

        stats = pstats.Stats(self.temp_file)
        stats.sort_stats(sort_by)

        # Extract top functions
        functions = []
        for func_info, (cc, _nc, tt, ct, _callers) in stats.stats.items():
            filename, line_number, function_name = func_info
            functions.append(
                {
                    "filename": filename,
                    "line_number": line_number,
                    "function_name": function_name,
                    "call_count": cc,
                    "total_time": tt,
                    "cumulative_time": ct,
                    "per_call_time": tt / cc if cc > 0 else 0,
                }
            )

        return functions[:limit]

    def cleanup(self) -> None:
        """Clean up temporary files."""
        if self.temp_file and os.path.exists(self.temp_file):
            os.unlink(self.temp_file)


class PerformanceProfiler:
    """Main performance profiler orchestrating all monitoring."""

    def __init__(self, baseline_file: Optional[Path] = None):
        self.baseline_file = baseline_file or Path.home() / ".benchbox" / "performance_baselines.json"
        self.baselines: dict[str, PerformanceBaseline] = {}
        self.load_baselines()

        self.resource_monitor = ResourceMonitor()
        self.memory_profiler = MemoryProfiler()
        self.cpu_profiler = CPUProfiler()

        self.current_metrics: dict[str, PerformanceMetrics] = {}

    def load_baselines(self) -> None:
        """Load performance baselines from disk."""
        if self.baseline_file.exists():
            try:
                with open(self.baseline_file, encoding="utf-8") as f:
                    data = json.load(f)
                    for name, baseline_data in data.items():
                        self.baselines[name] = PerformanceBaseline(**baseline_data)
            except (OSError, json.JSONDecodeError):
                pass

    def save_baselines(self) -> None:
        """Save performance baselines to disk."""
        self.baseline_file.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        for name, baseline in self.baselines.items():
            data[name] = {
                "name": baseline.name,
                "duration_baseline": baseline.duration_baseline,
                "memory_baseline": baseline.memory_baseline,
                "cpu_baseline": baseline.cpu_baseline,
                "tolerance_percent": baseline.tolerance_percent,
            }

        with open(self.baseline_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @contextmanager
    def profile_test(self, test_name: str, enable_cpu_profiling: bool = False):
        """Context manager for profiling a single test."""
        # Start all monitoring
        self.resource_monitor.start_monitoring()
        self.memory_profiler.start_profiling()
        self.memory_profiler.take_snapshot(f"{test_name}_start")

        # Get initial GC stats
        gc_before = {i: gc.get_count()[i] for i in range(3)}

        start_time = time.time()
        cpu_profiler_context = None

        if enable_cpu_profiling:
            cpu_profiler_context = self.cpu_profiler.profile_context()
            cpu_profiler_context.__enter__()

        try:
            yield
        finally:
            # Stop CPU profiling
            if cpu_profiler_context:
                cpu_profiler_context.__exit__(None, None, None)

            # Collect final metrics
            end_time = time.time()
            self.memory_profiler.take_snapshot(f"{test_name}_end")

            # Get final GC stats
            gc_after = {i: gc.get_count()[i] for i in range(3)}
            gc_collections = {i: gc_after[i] - gc_before[i] for i in range(3)}

            # Stop monitoring
            self.resource_monitor.stop_monitoring()
            self.memory_profiler.stop_profiling()

            # Calculate metrics
            resource_summary = self.resource_monitor.get_summary()

            metrics = PerformanceMetrics(
                name=test_name,
                duration=end_time - start_time,
                memory_peak=resource_summary.get("memory_peak", 0),
                memory_average=resource_summary.get("memory_average", 0),
                cpu_percent=resource_summary.get("cpu_average", 0),
                cpu_time=resource_summary.get("duration", 0),
                io_read_bytes=resource_summary.get("io_read_total", 0),
                io_write_bytes=resource_summary.get("io_write_total", 0),
                io_read_count=0,  # Not available in summary
                io_write_count=0,  # Not available in summary
                gc_collections=gc_collections,
                thread_count=resource_summary.get("thread_count", 1),
                file_descriptors=resource_summary.get("file_descriptors", 0),
            )

            self.current_metrics[test_name] = metrics

    def update_baseline(self, test_name: str, tolerance_percent: float = 10.0) -> None:
        """Update baseline for a test using current metrics."""
        if test_name not in self.current_metrics:
            return

        metrics = self.current_metrics[test_name]
        baseline = PerformanceBaseline(
            name=test_name,
            duration_baseline=metrics.duration,
            memory_baseline=metrics.memory_peak,
            cpu_baseline=metrics.cpu_percent,
            tolerance_percent=tolerance_percent,
        )

        self.baselines[test_name] = baseline
        self.save_baselines()

    def check_regressions(self) -> dict[str, dict[str, bool]]:
        """Check for performance regressions."""
        regressions = {}

        for test_name, metrics in self.current_metrics.items():
            if test_name in self.baselines:
                baseline = self.baselines[test_name]
                regressions[test_name] = baseline.is_regression(metrics)

        return regressions

    def get_optimization_recommendations(self, test_name: str) -> list[str]:
        """Get optimization recommendations based on metrics."""
        if test_name not in self.current_metrics:
            return []

        metrics = self.current_metrics[test_name]
        recommendations = []

        # Memory recommendations
        if metrics.memory_peak > 100 * 1024 * 1024:  # 100MB
            recommendations.append(
                "High memory usage detected. Consider using generators or processing data in chunks."
            )

        # CPU recommendations
        if metrics.cpu_percent > 80:
            recommendations.append("High CPU usage detected. Consider optimizing algorithms or using caching.")

        # GC recommendations
        if metrics.gc_collections[2] > 10:  # Many generation 2 collections
            recommendations.append("Frequent garbage collection detected. Consider reducing object creation.")

        # IO recommendations
        if metrics.io_read_bytes > 50 * 1024 * 1024:  # 50MB
            recommendations.append("High I/O read volume detected. Consider caching or reducing file operations.")

        if metrics.io_write_bytes > 50 * 1024 * 1024:  # 50MB
            recommendations.append("High I/O write volume detected. Consider batching writes or using faster storage.")

        # Threading recommendations
        if metrics.thread_count > 10:
            recommendations.append("High thread count detected. Consider using thread pools or async operations.")

        # File descriptor recommendations
        if metrics.file_descriptors > 100:
            recommendations.append("High file descriptor usage detected. Ensure proper resource cleanup.")

        return recommendations

    def generate_performance_report(self, test_names: Optional[list[str]] = None) -> str:
        """Generate comprehensive performance report."""
        if test_names is None:
            test_names = list(self.current_metrics.keys())

        report = []
        report.append("# Performance Analysis Report")
        report.append(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        # Summary statistics
        if test_names:
            total_duration = sum(self.current_metrics[name].duration for name in test_names)
            total_memory = sum(self.current_metrics[name].memory_peak for name in test_names)
            avg_cpu = statistics.mean(self.current_metrics[name].cpu_percent for name in test_names)

            report.append("## Summary")
            report.append(f"- Total Duration: {total_duration:.2f}s")
            report.append(f"- Total Memory: {total_memory / (1024 * 1024):.1f} MB")
            report.append(f"- Average CPU: {avg_cpu:.1f}%")
            report.append("")

        # Per-test analysis
        for test_name in test_names:
            if test_name not in self.current_metrics:
                continue

            metrics = self.current_metrics[test_name]

            report.append(f"## {test_name}")
            report.append(f"- Duration: {metrics.duration:.2f}s")
            report.append(f"- Memory Peak: {metrics.memory_peak / (1024 * 1024):.1f} MB")
            report.append(f"- Memory Average: {metrics.memory_average / (1024 * 1024):.1f} MB")
            report.append(f"- CPU Usage: {metrics.cpu_percent:.1f}%")
            report.append(f"- I/O Read: {metrics.io_read_bytes / (1024 * 1024):.1f} MB")
            report.append(f"- I/O Write: {metrics.io_write_bytes / (1024 * 1024):.1f} MB")
            report.append(f"- GC Collections: {metrics.gc_collections}")
            report.append(f"- Threads: {metrics.thread_count}")
            report.append(f"- File Descriptors: {metrics.file_descriptors}")

            # Regression analysis
            if test_name in self.baselines:
                baseline = self.baselines[test_name]
                regressions = baseline.is_regression(metrics)

                if any(regressions.values()):
                    report.append("- **PERFORMANCE REGRESSION DETECTED**")
                    for metric, is_regression in regressions.items():
                        if is_regression:
                            report.append(f"  - {metric}: REGRESSION")

            # Optimization recommendations
            recommendations = self.get_optimization_recommendations(test_name)
            if recommendations:
                report.append("- Optimization Recommendations:")
                for rec in recommendations:
                    report.append(f"  - {rec}")

            report.append("")

        return "\n".join(report)

    def cleanup(self) -> None:
        """Clean up resources."""
        self.cpu_profiler.cleanup()


def profile_pytest_run(test_command: list[str], output_file: Optional[Path] = None) -> dict[str, Any]:
    """Profile a pytest run and return performance metrics."""
    profiler = PerformanceProfiler()

    with profiler.profile_test("pytest_run"):
        # Run pytest with monitoring
        result = subprocess.run(test_command, capture_output=True, text=True, cwd=Path.cwd())

    # Generate report
    report = profiler.generate_performance_report()

    if output_file:
        output_file.write_text(report)

    return {
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "performance_report": report,
        "metrics": profiler.current_metrics.get("pytest_run"),
    }


def main():
    """CLI entry point for performance profiling."""
    import argparse

    parser = argparse.ArgumentParser(description="Performance profiler for test execution")
    parser.add_argument("command", nargs="+", help="Command to profile")
    parser.add_argument("--output", "-o", type=Path, help="Output file for report")
    parser.add_argument("--update-baseline", action="store_true", help="Update performance baseline")
    parser.add_argument(
        "--check-regressions",
        action="store_true",
        help="Check for performance regressions",
    )

    args = parser.parse_args()

    # Profile the command
    result = profile_pytest_run(args.command, args.output)

    print("Performance profiling completed!")
    print(f"Command exit code: {result['return_code']}")

    if args.output:
        print(f"Report saved to: {args.output}")
    else:
        print("\nPerformance Report:")
        print(result["performance_report"])


if __name__ == "__main__":
    main()

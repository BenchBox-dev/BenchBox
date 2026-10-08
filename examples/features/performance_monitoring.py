#!/usr/bin/env python3

from __future__ import annotations

import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Note: psutil not available. Install with: pip install psutil")
    print("      Resource monitoring will be simulated.")


def get_system_info():
    print("=" * 70)
    print("SYSTEM INFORMATION")
    print("=" * 70)
    print()

    if PSUTIL_AVAILABLE:
        cpu_count = psutil.cpu_count(logical=False)
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()

        print("CPU:")
        print(f"  Physical cores: {cpu_count}")
        print(f"  Logical cores:  {cpu_count_logical}")
        if cpu_freq:
            print(f"  Frequency:      {cpu_freq.current:.0f} MHz (max: {cpu_freq.max:.0f} MHz)")

        memory = psutil.virtual_memory()
        memory_gb = memory.total / (1024**3)

        print("\nMemory:")
        print(f"  Total:     {memory_gb:.1f} GB")
        print(f"  Available: {memory.available / (1024**3):.1f} GB")
        print(f"  Used:      {memory.percent}%")

        disk = psutil.disk_usage("/")
        print("\nDisk:")
        print(f"  Total:     {disk.total / (1024**3):.1f} GB")
        print(f"  Free:      {disk.free / (1024**3):.1f} GB")
        print(f"  Used:      {disk.percent}%")
    else:
        print("System information not available (psutil not installed)")

    print()


class ResourceMonitor:
    def __init__(self):
        self.start_time = None
        self.start_memory = None
        self.start_cpu_percent = None
        self.measurements = []

    def start(self):
        self.start_time = time.time()
        if PSUTIL_AVAILABLE:
            self.start_memory = psutil.virtual_memory().used
            self.start_cpu_percent = psutil.cpu_percent(interval=0.1)

    def record(self, label: str):
        if not PSUTIL_AVAILABLE:
            return

        elapsed = time.time() - self.start_time
        current_memory = psutil.virtual_memory().used
        memory_delta = (current_memory - self.start_memory) / (1024**2)
        cpu_percent = psutil.cpu_percent(interval=0.1)

        self.measurements.append(
            {"label": label, "elapsed": elapsed, "memory_delta_mb": memory_delta, "cpu_percent": cpu_percent}
        )

    def report(self):
        if not self.measurements:
            return

        print("=" * 70)
        print("RESOURCE USAGE REPORT")
        print("=" * 70)
        print()

        print(f"{'Event':<30} {'Time (s)':<12} {'Memory Δ':<15} {'CPU %':<10}")
        print("-" * 70)

        for m in self.measurements:
            print(
                f"{m['label']:<30} "
                f"{m['elapsed']:>8.1f}s    "
                f"{m['memory_delta_mb']:>+10.1f} MB   "
                f"{m['cpu_percent']:>6.1f}%"
            )

        print("-" * 70)
        print()


def demonstrate_basic_monitoring():
    print("=" * 70)
    print("BASIC RESOURCE MONITORING")
    print("=" * 70)
    print()

    monitor = ResourceMonitor()
    monitor.start()

    print("Creating benchmark...")
    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/monitoring"),
        force_regenerate=False,
    )
    monitor.record("Benchmark created")

    print("Generating data...")
    benchmark.generate_data()
    monitor.record("Data generated")

    print("Creating adapter...")
    adapter = DuckDBAdapter(database_path=":memory:")
    monitor.record("Adapter created")

    print("Running benchmark...")
    results = adapter.run_benchmark(
        benchmark,
        test_execution_type="power",
        query_subset=["1", "3", "6"],
    )
    monitor.record("Benchmark completed")

    print(f"✓ Benchmark complete ({results.total_queries} queries)")
    print()

    monitor.report()


def show_memory_estimation():
    print("=" * 70)
    print("MEMORY REQUIREMENT ESTIMATION")
    print("=" * 70)
    print()

    print("TPC-H Memory Requirements (Approximate):")
    print()

    print(f"{'Scale Factor':<15} {'Data Size':<15} {'Recommended RAM':<20}")
    print("-" * 50)
    print(f"{'0.01':<15} {'~10 MB':<15} {'512 MB - 1 GB':<20}")
    print(f"{'0.1':<15} {'~100 MB':<15} {'1 GB - 2 GB':<20}")
    print(f"{'1.0':<15} {'~1 GB':<15} {'4 GB - 8 GB':<20}")
    print(f"{'10.0':<15} {'~10 GB':<15} {'16 GB - 32 GB':<20}")
    print(f"{'100.0':<15} {'~100 GB':<15} {'64 GB - 128 GB':<20}")
    print("-" * 50)
    print()

    print("Factors affecting memory usage:")
    print("  • Scale factor (data volume)")
    print("  • Query complexity (joins, aggregations)")
    print("  • Concurrent query execution")
    print("  • Database buffer pool size")
    print("  • Result set sizes")
    print()

    print("Memory optimization tips:")
    print("  • Use streaming execution for large result sets")
    print("  • Limit concurrent queries")
    print("  • Tune database memory settings")
    print("  • Use disk-based operations for large joins")
    print()


def show_cpu_usage_patterns():
    print("=" * 70)
    print("CPU USAGE PATTERNS")
    print("=" * 70)
    print()

    print("Typical CPU usage during benchmark phases:")
    print()

    print("1. DATA GENERATION")
    print("   • CPU: 10-50% (I/O bound for large datasets)")
    print("   • Duration: Depends on scale factor")
    print("   • Optimization: Use multiple cores if available")
    print()

    print("2. DATA LOADING")
    print("   • CPU: 30-80% (parsing and inserting data)")
    print("   • Duration: Depends on platform and data size")
    print("   • Optimization: Batch inserts, disable indexes during load")
    print()

    print("3. QUERY EXECUTION")
    print("   • CPU: 50-100% (compute-intensive)")
    print("   • Duration: Varies by query complexity")
    print("   • Optimization: Parallel query execution")
    print()

    print("CPU optimization strategies:")
    print("  • Enable parallel query execution")
    print("  • Use columnar storage (reduces CPU for scans)")
    print("  • Create appropriate indexes")
    print("  • Optimize join orders")
    print("  • Use query result caching")
    print()


def show_performance_bottlenecks():
    print("=" * 70)
    print("IDENTIFYING PERFORMANCE BOTTLENECKS")
    print("=" * 70)
    print()

    print("Common bottlenecks and symptoms:")
    print()

    print("1. CPU BOTTLENECK")
    print("   Symptoms:")
    print("     • CPU at 100% during queries")
    print("     • Long query execution times")
    print("     • High CPU wait times")
    print("   Solutions:")
    print("     • Add more CPU cores")
    print("     • Optimize queries (better indexes, rewrite queries)")
    print("     • Use parallel query execution")
    print()

    print("2. MEMORY BOTTLENECK")
    print("   Symptoms:")
    print("     • High memory usage (>90%)")
    print("     • Disk swapping activity")
    print("     • Out-of-memory errors")
    print("   Solutions:")
    print("     • Add more RAM")
    print("     • Reduce scale factor")
    print("     • Tune memory settings")
    print("     • Use disk-based operations")
    print()

    print("3. DISK I/O BOTTLENECK")
    print("   Symptoms:")
    print("     • High disk I/O wait times")
    print("     • Slow data generation/loading")
    print("     • CPU idle while waiting for I/O")
    print("   Solutions:")
    print("     • Use faster storage (SSD vs HDD)")
    print("     • Increase buffer pool size")
    print("     • Use columnar storage")
    print("     • Pre-load data into memory")
    print()

    print("4. NETWORK BOTTLENECK (Cloud platforms)")
    print("   Symptoms:")
    print("     • High network latency")
    print("     • Slow data transfer")
    print("     • Timeout errors")
    print("   Solutions:")
    print("     • Use same region for data and compute")
    print("     • Increase network bandwidth")
    print("     • Batch operations")
    print("     • Use data locality")
    print()


def show_profiling_tools():
    print("=" * 70)
    print("PROFILING TOOLS")
    print("=" * 70)
    print()

    print("System-level monitoring:")
    print("  • psutil (Python): CPU, memory, disk, network")
    print("  • top/htop (Linux): Real-time process monitoring")
    print("  • Activity Monitor (macOS): System resource viewer")
    print("  • Task Manager (Windows): Process and resource monitoring")
    print()

    print("Database-level monitoring:")
    print("  • EXPLAIN ANALYZE: Query execution plan and timing")
    print("  • Database logs: Slow query logs, error logs")
    print("  • Query profiler: Per-operator timing and metrics")
    print("  • System tables: Statistics, locks, queries")
    print()

    print("Application-level monitoring:")
    print("  • Python cProfile: Function-level profiling")
    print("  • memory_profiler: Line-by-line memory usage")
    print("  • py-spy: Sampling profiler for Python")
    print("  • time module: Simple timing measurements")
    print()

    print("Example: Using EXPLAIN ANALYZE")
    print("""
# Get query execution plan with timing
adapter.execute(\"\"\"
    EXPLAIN ANALYZE
    SELECT * FROM lineitem
    WHERE l_shipdate >= '1998-01-01'
\"\"\")

# Output shows:
# - Execution plan (scan, join, aggregate)
# - Time spent in each operator
# - Rows processed
# - Memory usage
    """)


def main() -> int:
    print()
    print("=" * 70)
    print("BENCHBOX FEATURE: PERFORMANCE MONITORING")
    print("=" * 70)
    print()
    print("This example shows how to monitor system resources during")
    print("benchmark execution to identify bottlenecks and optimize performance.")
    print()

    get_system_info()

    demonstrate_basic_monitoring()

    show_memory_estimation()

    show_cpu_usage_patterns()

    show_performance_bottlenecks()

    show_profiling_tools()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("You learned how to:")
    print("  ✓ Monitor CPU usage during benchmarks")
    print("  ✓ Track memory consumption")
    print("  ✓ Estimate system requirements")
    print("  ✓ Identify performance bottlenecks")
    print("  ✓ Use profiling tools")
    print()
    print("Next steps:")
    print("  • Install psutil for resource monitoring:")
    print("    pip install psutil")
    print()
    print("  • Monitor your benchmarks:")
    print("    monitor = ResourceMonitor()")
    print("    monitor.start()")
    print("    # ... run benchmark ...")
    print("    monitor.report()")
    print()
    print("  • Profile slow queries:")
    print("    adapter.execute('EXPLAIN ANALYZE SELECT ...')")
    print()
    print("  • Check system requirements before scaling:")
    print("    # Estimate: Data size * 4-8 = Required RAM")
    print("    # Example: 10GB data → 40-80GB RAM")
    print()
    print("  • Use system monitoring tools:")
    print("    # Linux: htop, iostat, vmstat")
    print("    # macOS: Activity Monitor")
    print("    # Windows: Task Manager, Resource Monitor")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

Performance Monitoring Utilities API
=======================================

.. tags:: reference, python-api, performance

Complete Python API reference for performance monitoring utilities.

Overview
--------

BenchBox provides lightweight performance monitoring primitives for recording runtime metrics, taking snapshots, persisting history, and detecting regressions. The monitoring system is framework-agnostic and can be used by CLI tools, tests, and custom benchmark runners.

**Key Features**:

- **Multiple Metric Types**: Counters, gauges, and timing measurements
- **Statistical Analysis**: Mean, median, percentiles (P90, P95, P99)
- **Snapshot System**: Immutable snapshots with timestamps
- **Performance History**: Persistent storage with rolling window
- **Regression Detection**: Automatic detection with configurable thresholds
- **Trend Analysis**: Identify improving, degrading, or stable trends
- **Anomaly Detection**: Statistical outlier detection

Quick Start
-----------

.. code-block:: python

    from benchbox.monitoring.performance import PerformanceMonitor

    # Create monitor
    monitor = PerformanceMonitor()

    # Record metrics
    monitor.increment_counter("queries_executed")
    monitor.set_gauge("memory_usage_mb", 2048.5)

    with monitor.time_operation("query_execution"):
        # Run benchmark query
        result = execute_query(query)

    # Get snapshot
    snapshot = monitor.snapshot()
    print(f"Queries: {snapshot.counters['queries_executed']}")
    print(f"Avg time: {snapshot.timings['query_execution'].mean:.3f}s")

API Reference
-------------

PerformanceMonitor Class
~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.monitoring.performance.PerformanceMonitor
   :members:
   :inherited-members:

**Constructor**:

.. code-block:: python

    PerformanceMonitor()

Recording Methods
~~~~~~~~~~~~~~~~~

**increment_counter(name, value=1) -> None**

Increment a named counter.

**Parameters**:

- **name** (str): Counter name
- **value** (int): Amount to increment (default: 1)

**Example**:

.. code-block:: python

    monitor.increment_counter("queries_executed")
    monitor.increment_counter("rows_processed", 1000)

**set_gauge(name, value) -> None**

Record the latest value for a gauge metric.

**Parameters**:

- **name** (str): Gauge name
- **value** (float): Gauge value

**Example**:

.. code-block:: python

    monitor.set_gauge("memory_usage_mb", 2048.5)
    monitor.set_gauge("cpu_percent", 75.2)

**record_timing(name, duration_seconds) -> None**

Record a single timing observation.

**Parameters**:

- **name** (str): Timing name
- **duration_seconds** (float): Duration in seconds

**Example**:

.. code-block:: python

    import time
    start = time.perf_counter()
    execute_query(query)
    elapsed = time.perf_counter() - start
    monitor.record_timing("query_execution", elapsed)

**time_operation(name) -> ContextManager**

Context manager that records timing on exit.

**Parameters**:

- **name** (str): Operation name

**Example**:

.. code-block:: python

    with monitor.time_operation("data_loading"):
        load_data_to_database(data_files)

    with monitor.time_operation("query_Q1"):
        result = conn.execute(query_1).fetchall()

**set_metadata(key, value) -> None**

Attach arbitrary metadata to the snapshot.

**Parameters**:

- **key** (str): Metadata key
- **value** (Any): Metadata value

**Example**:

.. code-block:: python

    monitor.set_metadata("benchmark", "tpch")
    monitor.set_metadata("scale_factor", 1.0)
    monitor.set_metadata("database", "duckdb")

**update_metadata(items) -> None**

Bulk update metadata with dict.

**Parameters**:

- **items** (dict[str, Any]): Metadata dict

**Example**:

.. code-block:: python

    monitor.update_metadata({
        "benchmark": "tpcds",
        "scale_factor": 10.0,
        "queries": 99,
        "platform": "databricks"
    })

Snapshot Methods
~~~~~~~~~~~~~~~~

**snapshot() -> PerformanceSnapshot**

Create an immutable snapshot of currently recorded metrics.

**Returns**: ``PerformanceSnapshot`` with all metrics

**Example**:

.. code-block:: python

    snapshot = monitor.snapshot()
    print(f"Timestamp: {snapshot.timestamp}")
    print(f"Counters: {snapshot.counters}")
    print(f"Timings: {snapshot.timings}")

**summary() -> dict**

Return a plain dictionary representation for serialization.

**Returns**: Dict representation of snapshot

**Example**:

.. code-block:: python

    summary = monitor.summary()
    import json
    with open("metrics.json", "w") as f:
        json.dump(summary, f, indent=2)

**reset() -> None**

Clear all recorded metrics and metadata.

**Example**:

.. code-block:: python

    # Reset between benchmark runs
    for benchmark in benchmarks:
        monitor.reset()
        run_benchmark(benchmark)
        snapshot = monitor.snapshot()
        save_results(snapshot)

PerformanceSnapshot Class
~~~~~~~~~~~~~~~~~~~~~~~~~~

Immutable snapshot of recorded metrics.

.. autoclass:: benchbox.monitoring.performance.PerformanceSnapshot

**Fields**:

- **timestamp** (str): ISO 8601 timestamp
- **counters** (dict[str, int]): Counter values
- **gauges** (dict[str, float]): Gauge values
- **timings** (dict[str, TimingStats]): Timing statistics
- **metadata** (dict[str, Any]): Attached metadata

**to_dict() -> dict**

Convert snapshot to dictionary.

TimingStats Class
~~~~~~~~~~~~~~~~~

Aggregate timing statistics for a metric.

.. autoclass:: benchbox.monitoring.performance.TimingStats

**Fields**:

- **count** (int): Number of observations
- **minimum** (float): Minimum value
- **maximum** (float): Maximum value
- **mean** (float): Arithmetic mean
- **median** (float): Median value
- **p90** (float): 90th percentile
- **p95** (float): 95th percentile
- **p99** (float): 99th percentile
- **total** (float): Sum of all values

PerformanceHistory Class
~~~~~~~~~~~~~~~~~~~~~~~~~

Persist performance snapshots and detect regressions.

.. autoclass:: benchbox.monitoring.performance.PerformanceHistory

**Constructor**:

.. code-block:: python

    PerformanceHistory(
        storage_path: Path,
        max_entries: int = 50
    )

**Parameters**:

- **storage_path** (Path): Path to JSON history file
- **max_entries** (int): Maximum snapshots to keep (rolling window)

**record(snapshot, regression_thresholds=None, prefer_lower_metrics=None) -> list[PerformanceRegressionAlert]**

Persist snapshot and return any regression alerts.

**Parameters**:

- **snapshot** (PerformanceSnapshot): Snapshot to persist
- **regression_thresholds** (dict[str, float] | None): Per-metric thresholds (as percentages)
- **prefer_lower_metrics** (list[str] | None): Metrics where higher values indicate regressions

**Returns**: List of ``PerformanceRegressionAlert`` objects

**Example**:

.. code-block:: python

    from pathlib import Path

    history = PerformanceHistory(Path("performance_history.json"))
    snapshot = monitor.snapshot()

    alerts = history.record(
        snapshot,
        regression_thresholds={
            "query_execution": 0.15,  # 15% threshold
            "memory_usage_mb": 0.20   # 20% threshold
        },
        prefer_lower_metrics=["query_execution", "memory_usage_mb"]
    )

    for alert in alerts:
        print(f"⚠️  {alert.metric}: {alert.change_percent:.1%} {alert.direction}")

**trend(metric, window=10) -> str**

Return simple trend descriptor for metric.

**Parameters**:

- **metric** (str): Metric name
- **window** (int): Number of recent entries to analyze

**Returns**: Trend descriptor ("improving", "degrading", "stable", "insufficient_data")

**Example**:

.. code-block:: python

    trend = history.trend("query_execution", window=10)
    if trend == "degrading":
        print("⚠️  Performance is degrading")
    elif trend == "improving":
        print("✅ Performance is improving")

**metric_history(metric) -> list[float]**

Get historical values for a metric.

**Parameters**:

- **metric** (str): Metric name

**Returns**: List of historical values

**Example**:

.. code-block:: python

    values = history.metric_history("query_execution")
    import matplotlib.pyplot as plt
    plt.plot(values)
    plt.title("Query Execution Time Trend")
    plt.show()

PerformanceRegressionAlert Class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Represents a detected performance regression.

.. autoclass:: benchbox.monitoring.performance.PerformanceRegressionAlert

**Fields**:

- **metric** (str): Metric name
- **baseline** (float): Baseline value
- **current** (float): Current value
- **change_percent** (float): Change as percentage (e.g., 0.15 = 15%)
- **threshold_percent** (float): Threshold that was exceeded
- **direction** (str): "increase" or "decrease"

PerformanceTracker Class
~~~~~~~~~~~~~~~~~~~~~~~~~

Simplified file-backed metric recorder.

.. autoclass:: benchbox.monitoring.performance.PerformanceTracker

**Constructor**:

.. code-block:: python

    PerformanceTracker(storage_path: Path | None = None)

**Parameters**:

- **storage_path** (Path | None): Storage path (defaults to temp directory)

.. method:: record_metric(metric_name, value, timestamp=None) -> None

   Record a metric measurement.

.. method:: get_trend(metric_name, days=30) -> dict

   Get trend information for metric over specified days.

.. method:: detect_anomalies(metric_name, threshold_multiplier=2.0) -> list[dict]

   Return entries whose deviation exceeds threshold * std dev.

Usage Examples
--------------

Basic Monitoring
~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.monitoring.performance import PerformanceMonitor

    monitor = PerformanceMonitor()

    # Set benchmark metadata
    monitor.update_metadata({
        "benchmark": "tpch",
        "scale_factor": 1.0,
        "database": "duckdb"
    })

    # Run benchmark and record metrics
    for query_id in range(1, 23):
        with monitor.time_operation(f"query_Q{query_id}"):
            result = execute_query(query_id)
            rows = len(result)

        monitor.increment_counter("queries_executed")
        monitor.increment_counter("rows_returned", rows)

    # Get summary
    snapshot = monitor.snapshot()
    print(f"Executed {snapshot.counters['queries_executed']} queries")
    print(f"Total time: {snapshot.timings['query_Q1'].total:.2f}s")

Statistical Analysis
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Run query multiple times for stable timing
    monitor = PerformanceMonitor()

    for iteration in range(10):
        with monitor.time_operation("query_performance"):
            execute_query(query)

    snapshot = monitor.snapshot()
    stats = snapshot.timings["query_performance"]

    print(f"Count: {stats.count}")
    print(f"Mean: {stats.mean:.3f}s")
    print(f"Median: {stats.median:.3f}s")
    print(f"P95: {stats.p95:.3f}s")
    print(f"P99: {stats.p99:.3f}s")
    print(f"Min: {stats.minimum:.3f}s")
    print(f"Max: {stats.maximum:.3f}s")

Regression Detection
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from pathlib import Path
    from benchbox.monitoring.performance import (
        PerformanceMonitor,
        PerformanceHistory
    )

    # Setup history
    history = PerformanceHistory(
        Path("benchbox_performance.json"),
        max_entries=100
    )

    # Run benchmark
    monitor = PerformanceMonitor()
    monitor.set_metadata("version", "1.2.3")

    with monitor.time_operation("full_benchmark"):
        run_full_benchmark()

    # Record and check for regressions
    snapshot = monitor.snapshot()
    alerts = history.record(
        snapshot,
        regression_thresholds={
            "full_benchmark": 0.10,  # 10% threshold
        },
        prefer_lower_metrics=["full_benchmark"]
    )

    if alerts:
        print("⚠️  Performance regressions detected:")
        for alert in alerts:
            print(f"  {alert.metric}: {alert.baseline:.2f}s → {alert.current:.2f}s "
                  f"({alert.change_percent:.1%} {alert.direction})")
    else:
        print("✅ No regressions detected")

Trend Analysis
~~~~~~~~~~~~~~

.. code-block:: python

    history = PerformanceHistory(Path("performance.json"))

    # Analyze trends
    metrics_to_check = [
        "query_execution",
        "data_loading",
        "memory_usage_mb"
    ]

    for metric in metrics_to_check:
        trend = history.trend(metric, window=20)

        if trend == "degrading":
            print(f"⚠️  {metric}: Performance degrading")
        elif trend == "improving":
            print(f"✅ {metric}: Performance improving")
        elif trend == "stable":
            print(f"➖ {metric}: Performance stable")
        else:
            print(f"❓ {metric}: Insufficient data")

Performance Dashboard
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import json
    from pathlib import Path

    def create_performance_dashboard(history_path: Path):
        """Create performance dashboard from history."""
        history = PerformanceHistory(history_path)

        dashboard = {
            "metrics": {},
            "trends": {},
            "latest_snapshot": None
        }

        # Get all metrics from latest snapshot
        if history._history:
            latest = history._history[-1]
            dashboard["latest_snapshot"] = latest

            # Analyze each timing metric
            for metric_name in latest.get("timings", {}).keys():
                values = history.metric_history(metric_name)
                trend = history.trend(metric_name, window=10)

                dashboard["metrics"][metric_name] = {
                    "current": values[-1] if values else 0,
                    "history": values[-20:],  # Last 20 values
                    "trend": trend
                }

        return dashboard

    # Generate dashboard
    dashboard = create_performance_dashboard(Path("performance.json"))
    with open("dashboard.json", "w") as f:
        json.dump(dashboard, f, indent=2)

CI/CD Integration
~~~~~~~~~~~~~~~~~

.. code-block:: python

    import sys
    from pathlib import Path
    from benchbox.monitoring.performance import (
        PerformanceMonitor,
        PerformanceHistory
    )

    def ci_performance_check():
        """Performance check for CI/CD pipeline."""
        monitor = PerformanceMonitor()
        monitor.set_metadata("ci_run", True)
        monitor.set_metadata("commit", os.getenv("CI_COMMIT_SHA"))

        # Run benchmarks
        with monitor.time_operation("ci_benchmark"):
            run_ci_benchmarks()

        # Check for regressions
        history = PerformanceHistory(
            Path("ci_performance_history.json"),
            max_entries=50
        )

        snapshot = monitor.snapshot()
        alerts = history.record(
            snapshot,
            regression_thresholds={"ci_benchmark": 0.15},
            prefer_lower_metrics=["ci_benchmark"]
        )

        if alerts:
            print("❌ Performance regression detected!")
            for alert in alerts:
                print(f"  {alert.metric}: {alert.change_percent:.1%} slower")
            sys.exit(1)
        else:
            print("✅ Performance check passed")
            sys.exit(0)

    ci_performance_check()

Best Practices
--------------

1. **Use Context Managers for Timing**

   .. code-block:: python

       # Good: Automatic timing
       with monitor.time_operation("operation"):
           do_work()

       # Avoid: Manual timing (error-prone)
       start = time.time()
       do_work()
       monitor.record_timing("operation", time.time() - start)

2. **Record Metadata**

   .. code-block:: python

       # Always record context
       monitor.update_metadata({
           "benchmark": "tpch",
           "scale_factor": 1.0,
           "database": "duckdb",
           "version": "0.9.0",
           "date": datetime.now().isoformat()
       })

3. **Use Appropriate Metric Types**

   .. code-block:: python

       # Counters: Things that accumulate
       monitor.increment_counter("queries_executed")

       # Gauges: Current values
       monitor.set_gauge("memory_usage_mb", current_memory)

       # Timings: Operations with duration
       with monitor.time_operation("query"):
           execute_query()

4. **Set Appropriate Regression Thresholds**

   .. code-block:: python

       # Conservative: 10% threshold
       thresholds = {"query_time": 0.10}

       # Moderate: 15% threshold
       thresholds = {"query_time": 0.15}

       # Permissive: 25% threshold
       thresholds = {"query_time": 0.25}

5. **Maintain History Rolling Window**

   .. code-block:: python

       # Keep manageable history (50-100 entries)
       history = PerformanceHistory(
           Path("performance.json"),
           max_entries=100  # ~100 recent runs
       )

Common Issues
-------------

**Issue: "Insufficient data for trend"**
  - **Cause**: Less than 2 data points
  - **Solution**: Run more iterations or reduce window size

**Issue: False regression alerts**
  - **Cause**: Natural variance or aggressive thresholds
  - **Solution**: Increase threshold (e.g., 0.15 → 0.20) or run more iterations

**Issue: Missing timings in snapshot**
  - **Cause**: Operation not recorded or exception during timing
  - **Solution**: Ensure all operations use time_operation() and handle exceptions

**Issue: History file grows too large**
  - **Cause**: max_entries set too high
  - **Solution**: Reduce max_entries (default: 50, max recommended: 200)

**Issue: Percentile calculations unstable**
  - **Cause**: Too few samples (count < 10)
  - **Solution**: Record more timing observations per snapshot

See Also
--------

- :doc:`result-analysis` - Result analysis and comparison utilities
- :doc:`/advanced/performance-optimization` - Performance optimization guide
- :doc:`/advanced/ci-cd-integration` - CI/CD integration guide
- :doc:`/usage/troubleshooting` - Troubleshooting guide

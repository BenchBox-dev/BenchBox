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
- **Snapshot System**: Frozen snapshot records with timestamps and mutable nested mappings
- **Performance History**: Persistent storage with rolling window
- **Regression Detection**: Automatic detection with configurable thresholds
- **Trend Analysis**: Identify improving, degrading, or stable trends
- **Anomaly Detection**: Statistical outlier detection

Quick Start
-----------

.. code-block:: python

    from benchbox.monitoring.performance import PerformanceMonitor

    monitor = PerformanceMonitor()

    monitor.increment_counter("queries_executed")
    monitor.set_gauge("memory_usage_mb", 2048.5)

    with monitor.time_operation("query_execution"):
        result = execute_query(query)

    snapshot = monitor.snapshot()
    print(f"Queries: {snapshot.counters['queries_executed']}")
    print(f"Avg time: {snapshot.timings['query_execution'].mean:.3f}s")

API Reference
-------------

PerformanceMonitor Class
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.monitoring.performance.PerformanceMonitor()

   Record counters, gauges, timings in seconds and metadata. A new monitor starts empty.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.increment_counter(name: str, value: int=1) -> None

   Add value to the named counter, creating it from zero when absent.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.get_counter(name: str) -> int

   Return the named counter, or zero when it has not been recorded.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.set_gauge(name: str, value: float) -> None

   Store the latest float value for a gauge, replacing its previous value.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.record_timing(name: str, duration_seconds: float) -> None

   Append a duration in seconds to the named timing series. Values are converted to float.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.time_operation(name: str)

   Return a context manager that yields no value and records elapsed seconds
   on exit using a monotonic performance counter. Recording occurs in finally,
   including when the body raises; the exception continues to propagate.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.set_metadata(key: str, value: Any) -> None

   Attach a value under the metadata key, replacing any previous value.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.update_metadata(items: dict[str, Any]) -> None

   Update metadata from the supplied mapping, replacing overlapping keys.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.snapshot() -> PerformanceSnapshot

   Return a timestamped snapshot with copies of the counters, gauges and metadata
   mappings and summarized timing series. The timestamp is an ISO 8601 UTC string.
   Snapshot dataclasses are frozen, but their nested dictionaries and metadata
   values are not deeply immutable.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.summary() -> dict[str, Any]

   Create a fresh snapshot and return its plain dictionary representation, including timing-statistic dictionaries.

.. py:method:: benchbox.monitoring.performance.PerformanceMonitor.reset() -> None

   Clear all counters, gauges, timing observations and metadata.


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

    for benchmark in benchmarks:
        monitor.reset()
        run_benchmark(benchmark)
        snapshot = monitor.snapshot()
        save_results(snapshot)

PerformanceSnapshot Class
~~~~~~~~~~~~~~~~~~~~~~~~~~

Frozen snapshot of recorded metrics; nested mappings remain mutable.

.. py:class:: benchbox.monitoring.performance.PerformanceSnapshot(timestamp: str, counters: dict[str, int], gauges: dict[str, float], timings: dict[str, TimingStats], metadata: dict[str, Any] = <factory>)

   Frozen dataclass of a timestamp and recorded metrics. timestamp, counters,
   gauges and timings are required; metadata defaults to a fresh empty dictionary.
   Freezing prevents field reassignment but does not freeze nested mappings.

.. py:method:: benchbox.monitoring.performance.PerformanceSnapshot.to_dict() -> dict[str, Any]

   Return timestamp, copied counters and gauges, timing-statistic dictionaries and a copied metadata mapping. Nested metadata values remain shared.

.. py:attribute:: benchbox.monitoring.performance.PerformanceSnapshot.timestamp
   :type: str

   ISO 8601 timestamp; monitor snapshots use UTC. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceSnapshot.counters
   :type: dict[str, int]

   Named integer counter values. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceSnapshot.gauges
   :type: dict[str, float]

   Named latest float values in producer-chosen units. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceSnapshot.timings
   :type: dict[str, TimingStats]

   Named TimingStats values summarizing recorded seconds. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceSnapshot.metadata
   :type: dict[str, Any]

   Caller-supplied metadata mapping. Default: a new empty dictionary per instance.


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

.. py:class:: benchbox.monitoring.performance.TimingStats(count: int, minimum: float, maximum: float, mean: float, median: float, p90: float, p95: float, p99: float, total: float)

   Frozen dataclass of timing statistics. All nine arguments are required.
   Durations are seconds, including percentiles and total; count is a number of
   observations. Monitor percentiles use linear interpolation between adjacent
   sorted observations. Empty series summarize to zeros; a single observation
   supplies every percentile.

.. py:method:: benchbox.monitoring.performance.TimingStats.to_dict() -> dict[str, float]

   Return a dictionary of all statistic fields.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.count
   :type: int

   Number of timing observations. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.minimum
   :type: float

   Smallest timing observation in seconds. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.maximum
   :type: float

   Largest timing observation in seconds. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.mean
   :type: float

   Arithmetic mean of timing observations in seconds. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.median
   :type: float

   Median timing observation in seconds. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.p90
   :type: float

   Linearly interpolated 90th percentile in seconds. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.p95
   :type: float

   Linearly interpolated 95th percentile in seconds. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.p99
   :type: float

   Linearly interpolated 99th percentile in seconds. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.TimingStats.total
   :type: float

   Sum of timing observations in seconds. Required constructor argument.


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

.. py:class:: benchbox.monitoring.performance.PerformanceHistory(storage_path: Path, max_entries: int=50)

   Persist a bounded window of snapshots in a JSON file. The parent directory is
   created on construction. Existing entries are loaded; missing, unreadable or
   invalid JSON history starts empty. record compares against the latest entry
   and persists the updated window. Use a positive max_entries for a bounded
   history; the implementation does not validate this argument.

   :param storage_path: JSON history file.
   :param max_entries: Maximum retained snapshots; defaults to 50.

.. py:method:: benchbox.monitoring.performance.PerformanceHistory.record(snapshot: PerformanceSnapshot, regression_thresholds: dict[str, float] | None=None, prefer_lower_metrics: list[str] | None=None) -> list[PerformanceRegressionAlert]

   Compare the snapshot with the most recently recorded entry, append it, retain
   the configured history window and write the JSON history. Return matching
   regression alerts. No earlier baseline means no alerts.

   :param snapshot: Snapshot to compare and persist.
   :param regression_thresholds: Per-metric fractional thresholds, such as 0.15 for 15 percent. Only named metrics are checked; None or an empty mapping produces no alerts.
   :param prefer_lower_metrics: Metrics for which increasing values are regressions. For other named metrics, decreasing values are regressions.
   :returns: Regression alerts; their change_percent and threshold_percent values are fractions.

   The change is (current - baseline) / abs(baseline), and the comparison is strict:
   an increase greater than the threshold alerts for lower-is-better metrics; a
   decrease beyond the negative threshold alerts for other metrics. Missing
   metrics are skipped. A zero baseline yields a zero change and does not alert.
   Counters take precedence over gauges, then timing means when a name overlaps.

.. py:method:: benchbox.monitoring.performance.PerformanceHistory.trend(metric: str, window: int=10) -> str

   Compare the averages of the first and second halves of the latest available
   window. window values below two are raised to two. Return insufficient_data
   with fewer than two values, degrading for a fractional increase greater than
   0.1, improving for a decrease below -0.1, or stable otherwise.

   These labels always treat larger values as worse. They do not use record's
   prefer_lower_metrics setting and must be interpreted appropriately for metrics
   such as throughput.

.. py:method:: benchbox.monitoring.performance.PerformanceHistory.metric_history(metric: str) -> list[float]

   Return recorded numeric values for a metric in history order, skipping entries
   without that metric. Counters take precedence over timing means, then gauges
   when a name overlaps. Timing values are seconds; gauge and counter units are
   chosen by their producer.


**Constructor**:

**Parameters**:

- **storage_path** (Path): Path to JSON history file
- **max_entries** (int): Maximum snapshots to keep (rolling window)

**record(snapshot, regression_thresholds=None, prefer_lower_metrics=None) -> list[PerformanceRegressionAlert]**

Persist snapshot and return any regression alerts.

**Parameters**:

- **snapshot** (PerformanceSnapshot): Snapshot to persist
- **regression_thresholds** (dict[str, float] | None): Per-metric fractional thresholds (0.15 means 15 percent)
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
            "query_execution": 0.15,
            "memory_usage_mb": 0.20
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

.. py:class:: benchbox.monitoring.performance.PerformanceRegressionAlert(metric: str, baseline: float, current: float, change_percent: float, threshold_percent: float, direction: str)

   Frozen dataclass of a detected regression. All six arguments are required.
   change_percent and threshold_percent are fractions: 0.15 represents 15 percent.
   baseline and current retain the metric's own unit. direction is increase for
   lower-is-better metrics or decrease for other configured metrics.

.. py:method:: benchbox.monitoring.performance.PerformanceRegressionAlert.to_dict() -> dict[str, Any]

   Return all alert fields as a dictionary, preserving fractional change and threshold values.

.. py:attribute:: benchbox.monitoring.performance.PerformanceRegressionAlert.metric
   :type: str

   Name of the metric that exceeded its configured threshold. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceRegressionAlert.baseline
   :type: float

   Metric value in the preceding snapshot. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceRegressionAlert.current
   :type: float

   Metric value in the newly recorded snapshot. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceRegressionAlert.change_percent
   :type: float

   Signed relative change as a fraction, not a whole percentage number. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceRegressionAlert.threshold_percent
   :type: float

   Configured fractional regression threshold. Required constructor argument.

.. py:attribute:: benchbox.monitoring.performance.PerformanceRegressionAlert.direction
   :type: str

   increase for a lower-is-better regression, or decrease for another configured metric. Required constructor argument.


**Fields**:

- **metric** (str): Metric name
- **baseline** (float): Baseline value
- **current** (float): Current value
- **change_percent** (float): Relative change as a fraction (e.g., 0.15 = 15%)
- **threshold_percent** (float): Threshold that was exceeded
- **direction** (str): "increase" or "decrease"

PerformanceTracker Class
~~~~~~~~~~~~~~~~~~~~~~~~~

Simplified file-backed metric recorder.

.. py:class:: benchbox.monitoring.performance.PerformanceTracker(storage_path: Path | None=None)

   Persist independently named metric observations for trend and anomaly analysis.
   When storage_path is None, use benchbox_performance_history.json in the system
   temporary directory. Construction creates the parent directory and loads
   existing history; missing, unreadable or invalid JSON history starts empty.
   This format differs from PerformanceHistory's snapshot history.

   :param storage_path: Optional JSON file for metric observations.

.. py:method:: benchbox.monitoring.performance.PerformanceTracker.record_metric(metric_name: str, value: float, timestamp: datetime | None=None) -> None

   Append a float value and ISO timestamp to the metric's history and persist the
   JSON file. Omitted timestamps use the current UTC time; supply timezone-aware
   timestamps when using get_trend's UTC cutoff.

.. py:method:: benchbox.monitoring.performance.PerformanceTracker.get_trend(metric_name: str, days: int=30) -> dict[str, Any]

   Analyze entries within the last days days. With no metric history, return
   trend=unknown, recent_values=[], average=0. With fewer than two recent entries,
   return insufficient_data and the recent entry dictionaries. Otherwise return
   numeric recent_values with average, min, max and sample std_dev.

   Trend labels use a strict 10 percent split-half increase as degrading and a
   strict 10 percent decrease as improving, independent of whether higher values
   are desirable for the metric.

.. py:method:: benchbox.monitoring.performance.PerformanceTracker.detect_anomalies(metric_name: str, threshold_multiplier: float=2.0) -> list[dict[str, Any]]

   Return historical entries whose absolute deviation from the all-history mean
   exceeds threshold_multiplier times the sample standard deviation. Fewer than
   ten entries yields an empty list. Each result contains timestamp, value,
   deviation and threshold in the metric's own units.


**Constructor**:

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

    monitor.update_metadata({
        "benchmark": "tpch",
        "scale_factor": 1.0,
        "database": "duckdb"
    })

    for query_id in range(1, 23):
        with monitor.time_operation(f"query_Q{query_id}"):
            result = execute_query(query_id)
            rows = len(result)

        monitor.increment_counter("queries_executed")
        monitor.increment_counter("rows_returned", rows)

    snapshot = monitor.snapshot()
    print(f"Executed {snapshot.counters['queries_executed']} queries")
    print(f"Total time: {snapshot.timings['query_Q1'].total:.2f}s")

Statistical Analysis
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

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

    history = PerformanceHistory(
        Path("benchbox_performance.json"),
        max_entries=100
    )

    monitor = PerformanceMonitor()
    monitor.set_metadata("version", "1.2.3")

    with monitor.time_operation("full_benchmark"):
        run_full_benchmark()

    snapshot = monitor.snapshot()
    alerts = history.record(
        snapshot,
        regression_thresholds={
            "full_benchmark": 0.10,
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
        history = PerformanceHistory(history_path)

        dashboard = {
            "metrics": {},
            "trends": {},
            "latest_snapshot": None
        }

        if history._history:
            latest = history._history[-1]
            dashboard["latest_snapshot"] = latest

            for metric_name in latest.get("timings", {}).keys():
                values = history.metric_history(metric_name)
                trend = history.trend(metric_name, window=10)

                dashboard["metrics"][metric_name] = {
                    "current": values[-1] if values else 0,
                    "history": values[-20:],
                    "trend": trend
                }

        return dashboard

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
        monitor = PerformanceMonitor()
        monitor.set_metadata("ci_run", True)
        monitor.set_metadata("commit", os.getenv("CI_COMMIT_SHA"))

        with monitor.time_operation("ci_benchmark"):
            run_ci_benchmarks()

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

       with monitor.time_operation("operation"):
           do_work()

       start = time.time()
       do_work()
       monitor.record_timing("operation", time.time() - start)

2. **Record Metadata**

   .. code-block:: python

       monitor.update_metadata({
           "benchmark": "tpch",
           "scale_factor": 1.0,
           "database": "duckdb",
           "version": "0.9.0",
           "date": datetime.now().isoformat()
       })

3. **Use Appropriate Metric Types**

   .. code-block:: python

       monitor.increment_counter("queries_executed")

       monitor.set_gauge("memory_usage_mb", current_memory)

       with monitor.time_operation("query"):
           execute_query()

4. **Set Appropriate Regression Thresholds**

   .. code-block:: python

       thresholds = {"query_time": 0.10}

       thresholds = {"query_time": 0.15}

       thresholds = {"query_time": 0.25}

5. **Maintain History Rolling Window**

   .. code-block:: python

       history = PerformanceHistory(
           Path("performance.json"),
           max_entries=100
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

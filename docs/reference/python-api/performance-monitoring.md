<!-- markdownlint-disable MD024 -->

# Performance Monitoring Utilities API

```{tags} reference, python-api, performance
```

Python API reference for BenchBox's performance monitoring utilities.

## Overview

BenchBox provides lightweight performance monitoring primitives for recording runtime metrics, taking snapshots, persisting history, and detecting regressions. The monitoring system is framework-agnostic and can be used by CLI tools, tests, and custom benchmark runners.

**Key Features**:

- **Multiple Metric Types**: Counters, gauges, and timing measurements
- **Statistical Analysis**: Mean, median, percentiles (P90, P95, P99)
- **Snapshot System**: Frozen snapshots with timestamps
- **Performance History**: Persistent storage with rolling window
- **Regression Detection**: Comparison with the previous run against configurable thresholds
- **Trend Analysis**: Identify improving, degrading, or stable trends

## Quick Start

```python
import time

from benchbox.monitoring import PerformanceMonitor

monitor = PerformanceMonitor()

monitor.increment_counter("queries_executed")
monitor.set_gauge("memory_usage_mb", 2048.5)

with monitor.time_operation("query_execution"):
    time.sleep(0.05)

snapshot = monitor.snapshot()
print(f"Queries: {snapshot.counters['queries_executed']}")
print(f"Memory: {snapshot.gauges['memory_usage_mb']} MB")
print(f"Avg time: {snapshot.timings['query_execution'].mean:.2f}s")
```

Output (the time varies):

```text
Queries: 1
Memory: 2048.5 MB
Avg time: 0.05s
```

## API Reference

Two classes are public: `PerformanceMonitor` records metrics and `PerformanceHistory` stores snapshots. Both import from `benchbox.monitoring`. The other classes on this page appear only as values these two return. They are listed under [Not part of the public contract](#not-part-of-the-public-contract).

### PerformanceMonitor Class

#### `benchbox.monitoring.PerformanceMonitor`

<span id="benchbox.monitoring.performance.PerformanceMonitor"></span>

Records counters, gauges and timing observations in memory and turns them into a snapshot.

**Import:** `from benchbox.monitoring import PerformanceMonitor` · **Extras:** none

##### Parameters

<span id="benchbox.monitoring.performance.PerformanceMonitor.__init__"></span>The constructor takes no parameters.

##### Returns

A new, empty `PerformanceMonitor`.

##### Raises

Nothing it raises itself.

##### Example

```python
from benchbox.monitoring import PerformanceMonitor

monitor = PerformanceMonitor()
print(monitor.snapshot().counters, monitor.snapshot().timings)
```

Output:

```text
{} {}
```

The method examples below reuse this `monitor`.

##### Compatibility

`benchbox.monitoring.performance.PerformanceMonitor` is the same object.

Counters, gauges and timings are kept apart, so one name can exist as more than one kind. Use distinct names: `PerformanceHistory.metric_history` and `PerformanceHistory.record` can pick different kinds for a name that is used twice.

### Recording Methods

#### `increment_counter(name, value=1)`

<span id="benchbox.monitoring.performance.PerformanceMonitor.increment_counter"></span>

Adds `value` to the named counter, which starts at 0. Read the result with `get_counter(name)`.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | `str` | required | Counter name. |
| `value` | `int` | `1` | Amount to add. A negative value subtracts. |

`increment_counter` returns `None`.

```python
monitor.increment_counter("queries_executed")
monitor.increment_counter("rows_processed", 1000)
monitor.increment_counter("rows_processed", -200)

print(monitor.get_counter("queries_executed"))
print(monitor.get_counter("rows_processed"))
print(monitor.get_counter("never_incremented"))
```

Output:

```text
1
800
0
```

#### `get_counter(name)`

<span id="benchbox.monitoring.performance.PerformanceMonitor.get_counter"></span>

Returns the current value of the named counter, or 0 for a name that was never incremented.

#### `set_gauge(name, value)`

<span id="benchbox.monitoring.performance.PerformanceMonitor.set_gauge"></span>

Stores the latest value of a gauge. A later call replaces the earlier value.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | `str` | required | Gauge name. |
| `value` | `float` | required | Gauge value. It is converted with `float()`, so a value that cannot convert raises `ValueError`. |

Returns `None`.

```python
monitor.set_gauge("memory_usage_mb", 2048.5)
monitor.set_gauge("memory_usage_mb", 1024)

print(monitor.snapshot().gauges)
```

Output:

```text
{'memory_usage_mb': 1024.0}
```

#### `record_timing(name, duration_seconds)`

<span id="benchbox.monitoring.performance.PerformanceMonitor.record_timing"></span>

Adds one timing observation, in seconds, to the named timing. Observations accumulate until `reset()`; `snapshot()` summarizes them.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | `str` | required | Timing name. |
| `duration_seconds` | `float` | required | Duration in seconds. It is converted with `float()`. |

Returns `None`.

```python
for seconds in (0.2, 0.4, 0.6):
    monitor.record_timing("query_execution", seconds)

stats = monitor.snapshot().timings["query_execution"]
print(stats.count, f"{stats.mean:.1f}", f"{stats.total:.1f}")
```

Output:

```text
3 0.4 1.2
```

#### `time_operation(name)`

<span id="benchbox.monitoring.performance.PerformanceMonitor.time_operation"></span>

Context manager that measures the elapsed time of its block and records it with `record_timing` when the block ends. It records when the block raises, and the exception then propagates.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | `str` | required | Timing name. |

Returns a context manager that yields `None`.

```python
with monitor.time_operation("data_loading"):
    pass

try:
    with monitor.time_operation("failing_step"):
        raise RuntimeError("boom")
except RuntimeError:
    pass

timings = monitor.snapshot().timings
print(timings["data_loading"].count, timings["failing_step"].count)
```

Output:

```text
1 1
```

#### `set_metadata(key, value)` and `update_metadata(items)`

<span id="benchbox.monitoring.performance.PerformanceMonitor.set_metadata"></span><span id="benchbox.monitoring.performance.PerformanceMonitor.update_metadata"></span>

`set_metadata` attaches one value to the snapshot under `key`. `update_metadata` merges a dict of values. Both replace an existing key and return `None`.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `key` | `str` | required | `set_metadata`: metadata key. |
| `value` | `Any` | required | `set_metadata`: metadata value. |
| `items` | `dict[str, Any]` | required | `update_metadata`: values to merge. |

```python
monitor.set_metadata("benchmark", "tpch")
monitor.update_metadata({"scale_factor": 1.0, "database": "duckdb", "benchmark": "tpcds"})

print(monitor.snapshot().metadata)
```

Output:

```text
{'benchmark': 'tpcds', 'scale_factor': 1.0, 'database': 'duckdb'}
```

### Snapshot Methods

#### `snapshot()`

<span id="benchbox.monitoring.performance.PerformanceMonitor.snapshot"></span>

Returns a frozen copy of the metrics recorded so far. Later changes to the monitor do not change a snapshot that was already taken.

The returned object has these attributes and a `to_dict()` method that returns them as plain dicts:

| Attribute | Type | Meaning |
| --- | --- | --- |
| `timestamp` | `str` | Time of the snapshot, ISO 8601 in UTC. |
| `counters` | `dict[str, int]` | Counter values. |
| `gauges` | `dict[str, float]` | Latest gauge values. |
| `timings` | `dict[str, TimingStats]` | One entry per recorded timing. |
| `metadata` | `dict[str, Any]` | Attached metadata. |

Each `TimingStats` has `count`, `minimum`, `maximum`, `mean`, `median`, `p90`, `p95`, `p99` and `total`, all in seconds except `count`. Percentiles interpolate linearly between the sorted observations; with one observation, every percentile equals it.

Assigning to an attribute raises `dataclasses.FrozenInstanceError`.

```python
snapshot = monitor.snapshot()

print(snapshot.timestamp.endswith("+00:00"))
print(snapshot.counters)
print(snapshot.timings["query_execution"])

monitor.increment_counter("queries_executed")
print(snapshot.counters["queries_executed"], monitor.get_counter("queries_executed"))
```

Output:

```text
True
{'queries_executed': 1, 'rows_processed': 800}
TimingStats(count=3, minimum=0.2, maximum=0.6, mean=0.39999999999999997, median=0.4, p90=0.56, p95=0.58, p99=0.596, total=1.2000000000000002)
1 2
```

#### `summary()`

<span id="benchbox.monitoring.performance.PerformanceMonitor.summary"></span>

Returns the same content as `snapshot().to_dict()`: a dict with `timestamp`, `counters`, `gauges`, `timings` (each timing as a dict of the statistics above) and `metadata`. It is JSON-serializable when the metadata is.

```python
import json
from pathlib import Path

summary = monitor.summary()
print(list(summary))
print(summary["timings"]["query_execution"]["count"])

Path("metrics.json").write_text(json.dumps(summary, indent=2))
```

Output:

```text
['timestamp', 'counters', 'gauges', 'timings', 'metadata']
3
```

#### `reset()`

<span id="benchbox.monitoring.performance.PerformanceMonitor.reset"></span>

Clears all counters, gauges, timings and metadata. Returns `None`.

```python
for benchmark in ("tpch", "tpcds"):
    monitor.reset()
    monitor.increment_counter("queries_executed")
    print(benchmark, monitor.snapshot().counters)

monitor.reset()
summary = monitor.summary()
print(summary["counters"], summary["gauges"], summary["timings"], summary["metadata"])
```

Output:

```text
tpch {'queries_executed': 1}
tpcds {'queries_executed': 1}
{} {} {} {}
```

### PerformanceSnapshot Class

`PerformanceMonitor.snapshot()` returns a `PerformanceSnapshot`. The class is not part of the public contract. Use the attributes listed under [`snapshot()`](#snapshot) and import nothing from it.

### TimingStats Class

Each value of `PerformanceSnapshot.timings` is a `TimingStats`. The class is not part of the public contract. Its fields are listed under [`snapshot()`](#snapshot).

### PerformanceHistory Class

#### `benchbox.monitoring.PerformanceHistory`

<span id="benchbox.monitoring.performance.PerformanceHistory"></span>

Stores performance snapshots in a JSON file and compares each new snapshot with the previous one.

**Import:** `from benchbox.monitoring import PerformanceHistory` · **Extras:** none

##### Parameters

<span id="benchbox.monitoring.performance.PerformanceHistory.__init__"></span>

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `storage_path` | `Path` | required | Path of the JSON history file. A `str` also works. The constructor creates missing parent directories and loads the file if it exists. |
| `max_entries` | `int` | `50` | Number of snapshots to keep. When `record` adds more, the oldest are dropped. |

The file holds `{"entries": [...]}`, one dict per snapshot in the form `snapshot.to_dict()` returns. A file that holds a bare list of such dicts also loads. A file that cannot be read or parsed is treated as empty without an error, and the next `record` overwrites it.

##### Returns

A `PerformanceHistory` loaded with the entries from `storage_path`.

##### Raises

Nothing it raises itself.

##### Example

```python
import json
from pathlib import Path

from benchbox.monitoring import PerformanceHistory, PerformanceMonitor

history = PerformanceHistory(Path("perf/history.json"), max_entries=50)

monitor = PerformanceMonitor()
monitor.record_timing("query_execution", 1.0)
monitor.set_gauge("memory_usage_mb", 2000.0)

print(history.record(monitor.snapshot()))
print(list(json.loads(Path("perf/history.json").read_text())))
```

Output:

```text
[]
['entries']
```

##### Compatibility

`benchbox.monitoring.performance.PerformanceHistory` is the same object.

#### `record(snapshot, regression_thresholds=None, prefer_lower_metrics=None)`

<span id="benchbox.monitoring.performance.PerformanceHistory.record"></span>

Appends the snapshot to the file, trims the file to `max_entries`, and returns the regression alerts found against the previous entry. The first snapshot has nothing to compare with, so it returns `[]`.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `snapshot` | `PerformanceSnapshot` | required | Snapshot from `PerformanceMonitor.snapshot()`. |
| `regression_thresholds` | `dict[str, float] \| None` | `None` | Maximum allowed change per metric, as a fraction: `0.15` means 15%. Only listed metrics are checked. |
| `prefer_lower_metrics` | `list[str] \| None` | `None` | Metrics where a higher value is worse, such as durations. For any other listed metric a drop is the regression. |

For each listed metric, the value is the counter, else the gauge, else the timing's mean. A metric missing from either snapshot is skipped, as is a metric that is 0 in both. The change is `(current - baseline) / abs(baseline)`, or 0 when the baseline is 0.

- **Metric in `prefer_lower_metrics`:** an alert when the change is above the threshold; `direction` is `"increase"`.
- **Any other metric:** an alert when the change is below minus the threshold; `direction` is `"decrease"`.

Returns `list[PerformanceRegressionAlert]`. Each alert has `metric`, `baseline`, `current`, `change_percent` (a fraction, so `0.3` is 30%), `threshold_percent` (the threshold, in the same units), `direction` and `to_dict()`.

Only the previous entry is the baseline, not an average of earlier runs.

```python
monitor = PerformanceMonitor()
monitor.record_timing("query_execution", 1.3)
monitor.set_gauge("memory_usage_mb", 2100.0)

alerts = history.record(
    monitor.snapshot(),
    regression_thresholds={
        "query_execution": 0.15,
        "memory_usage_mb": 0.20,
    },
    prefer_lower_metrics=["query_execution", "memory_usage_mb"],
)

for alert in alerts:
    print(f"{alert.metric}: {alert.change_percent:.1%} {alert.direction}")
print(alerts[0].baseline, alerts[0].current, alerts[0].threshold_percent)
```

Output:

```text
query_execution: 30.0% increase
1.0 1.3 0.15
```

#### `trend(metric, window=10)`

<span id="benchbox.monitoring.performance.PerformanceHistory.trend"></span>

Compares the first half and the second half of the last `window` values of a metric.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `metric` | `str` | required | Metric name. |
| `window` | `int` | `10` | Number of recent entries to use. Values below 2 are treated as 2. |

Returns a `str`:

- **`"insufficient_data"`:** fewer than two values exist for the metric.
- **`"degrading"`:** the mean of the second half is more than 10% above the first half. A first-half mean of 0 with a non-zero second half also counts.
- **`"improving"`:** the second half is more than 10% below the first half.
- **`"stable"`:** otherwise, including when both halves are 0.

A higher value always reads as degrading, so for a metric where higher is better, such as throughput, read the result the other way round.

```python
trend_history = PerformanceHistory(Path("perf/trend.json"))

for seconds in (1.0, 1.0, 1.0, 1.5, 1.5, 1.5):
    monitor = PerformanceMonitor()
    monitor.record_timing("query_execution", seconds)
    trend_history.record(monitor.snapshot())

trend = trend_history.trend("query_execution", window=10)
if trend == "degrading":
    print("Performance is degrading")
elif trend == "improving":
    print("Performance is improving")
else:
    print(trend)
```

Output:

```text
Performance is degrading
```

#### `metric_history(metric)`

<span id="benchbox.monitoring.performance.PerformanceHistory.metric_history"></span>

Returns the stored values of a metric, oldest first, as `list[float]`. A counter gives its value, a timing gives its mean and a gauge gives its value. Entries without the metric are skipped, and an unknown metric gives `[]`.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `metric` | `str` | required | Metric name. |

```python
values = trend_history.metric_history("query_execution")
print(values)
print(trend_history.metric_history("unknown_metric"))
```

Output:

```text
[1.0, 1.0, 1.0, 1.5, 1.5, 1.5]
[]
```

### PerformanceRegressionAlert Class

`PerformanceHistory.record` returns `PerformanceRegressionAlert` objects. The class is not part of the public contract. Their attributes are listed under [`record`](#benchbox.monitoring.performance.PerformanceHistory.record).

### PerformanceTracker Class

`PerformanceTracker` is a simplified file-backed metric recorder. It is not part of the public contract.

## Usage Examples

### Basic Monitoring

```python
import time

from benchbox.monitoring import PerformanceMonitor


def execute_query(query_id):
    time.sleep(0.001)
    return list(range(query_id))


monitor = PerformanceMonitor()

monitor.update_metadata({
    "benchmark": "tpch",
    "scale_factor": 1.0,
    "database": "duckdb",
})

for query_id in range(1, 23):
    with monitor.time_operation(f"query_Q{query_id}"):
        result = execute_query(query_id)
        rows = len(result)

    monitor.increment_counter("queries_executed")
    monitor.increment_counter("rows_returned", rows)

snapshot = monitor.snapshot()
print(f"Executed {snapshot.counters['queries_executed']} queries")
print(f"Rows returned: {snapshot.counters['rows_returned']}")
print(f"Q1 observations: {snapshot.timings['query_Q1'].count}")
print(f"Q1 total time above 1 ms: {snapshot.timings['query_Q1'].total >= 0.001}")
```

Output:

```text
Executed 22 queries
Rows returned: 253
Q1 observations: 1
Q1 total time above 1 ms: True
```

### Statistical Analysis

Percentiles from few observations are rough: the single 0.50 s outlier below moves the mean to 0.158 s while the median stays at 0.120 s.

```python
from benchbox.monitoring import PerformanceMonitor

monitor = PerformanceMonitor()

durations = [0.10, 0.12, 0.11, 0.13, 0.10, 0.15, 0.12, 0.11, 0.14, 0.50]
for seconds in durations:
    monitor.record_timing("query_performance", seconds)

stats = monitor.snapshot().timings["query_performance"]

print(f"Count: {stats.count}")
print(f"Mean: {stats.mean:.3f}s")
print(f"Median: {stats.median:.3f}s")
print(f"P95: {stats.p95:.3f}s")
print(f"P99: {stats.p99:.3f}s")
print(f"Min: {stats.minimum:.3f}s")
print(f"Max: {stats.maximum:.3f}s")
```

Output:

```text
Count: 10
Mean: 0.158s
Median: 0.120s
P95: 0.342s
P99: 0.469s
Min: 0.100s
Max: 0.500s
```

### Regression Detection

The first run has nothing to compare with. The second run is 15% slower than the first, which exceeds the 10% threshold:

```python
from pathlib import Path

from benchbox.monitoring import PerformanceHistory, PerformanceMonitor

history = PerformanceHistory(Path("regression/benchbox_performance.json"), max_entries=100)

for duration in (10.0, 11.5):
    monitor = PerformanceMonitor()
    monitor.set_metadata("version", "1.2.3")
    monitor.record_timing("full_benchmark", duration)

    alerts = history.record(
        monitor.snapshot(),
        regression_thresholds={"full_benchmark": 0.10},
        prefer_lower_metrics=["full_benchmark"],
    )

    if alerts:
        print("Performance regressions detected:")
        for alert in alerts:
            print(f"  {alert.metric}: {alert.baseline:.2f}s -> {alert.current:.2f}s "
                  f"({alert.change_percent:.1%} {alert.direction})")
    else:
        print("No regressions detected")
```

Output:

```text
No regressions detected
Performance regressions detected:
  full_benchmark: 10.00s -> 11.50s (15.0% increase)
```

### Trend Analysis

```python
history = PerformanceHistory(Path("trends/performance.json"))

for step in range(8):
    monitor = PerformanceMonitor()
    monitor.record_timing("query_execution", 1.0 + 0.2 * step)
    monitor.record_timing("data_loading", 5.0 - 0.4 * step)
    monitor.set_gauge("memory_usage_mb", 2048.0)
    history.record(monitor.snapshot())

for metric in ["query_execution", "data_loading", "memory_usage_mb", "unknown_metric"]:
    trend = history.trend(metric, window=20)

    if trend == "degrading":
        print(f"{metric}: performance degrading")
    elif trend == "improving":
        print(f"{metric}: performance improving")
    elif trend == "stable":
        print(f"{metric}: performance stable")
    else:
        print(f"{metric}: insufficient data")
```

Output:

```text
query_execution: performance degrading
data_loading: performance improving
memory_usage_mb: performance stable
unknown_metric: insufficient data
```

### Performance Dashboard

The history file is JSON, so a dashboard can read the latest entry from it directly:

```python
import json
from pathlib import Path

from benchbox.monitoring import PerformanceHistory


def create_performance_dashboard(history_path: Path):
    history = PerformanceHistory(history_path)
    entries = json.loads(Path(history_path).read_text())["entries"]

    dashboard = {"metrics": {}, "latest_snapshot": None}

    if entries:
        latest = entries[-1]
        dashboard["latest_snapshot"] = latest

        for metric_name in latest.get("timings", {}):
            values = history.metric_history(metric_name)

            dashboard["metrics"][metric_name] = {
                "current": values[-1] if values else 0,
                "history": values[-20:],
                "trend": history.trend(metric_name, window=10),
            }

    return dashboard


dashboard = create_performance_dashboard(Path("trends/performance.json"))
Path("dashboard.json").write_text(json.dumps(dashboard, indent=2))

for name, metric in dashboard["metrics"].items():
    print(name, round(metric["current"], 2), metric["trend"], len(metric["history"]))
```

Output:

```text
query_execution 2.4 degrading 8
data_loading 2.2 improving 8
```

### CI/CD Integration

```python
import os
import sys
import time
from pathlib import Path

from benchbox.monitoring import PerformanceHistory, PerformanceMonitor


def run_ci_benchmarks():
    time.sleep(0.01)


def ci_performance_check():
    monitor = PerformanceMonitor()
    monitor.set_metadata("ci_run", True)
    monitor.set_metadata("commit", os.getenv("CI_COMMIT_SHA"))

    with monitor.time_operation("ci_benchmark"):
        run_ci_benchmarks()

    history = PerformanceHistory(
        Path("ci_performance_history.json"),
        max_entries=50,
    )

    alerts = history.record(
        monitor.snapshot(),
        regression_thresholds={"ci_benchmark": 0.15},
        prefer_lower_metrics=["ci_benchmark"],
    )

    if alerts:
        print("Performance regression detected")
        for alert in alerts:
            print(f"  {alert.metric}: {alert.change_percent:.1%} slower")
        return 1

    print("Performance check passed")
    return 0


sys.exit(ci_performance_check())
```

Output (exit code 0):

```text
Performance check passed
[exit 0]
```

## Best Practices

1. **Use Context Managers for Timing**

   ```python
   import time

   from benchbox.monitoring import PerformanceMonitor

   monitor = PerformanceMonitor()


   def do_work():
       time.sleep(0.001)


   with monitor.time_operation("operation"):
       do_work()

   start = time.perf_counter()
   do_work()
   monitor.record_timing("operation", time.perf_counter() - start)

   print(monitor.snapshot().timings["operation"].count)
   ```

2. **Record Metadata**

   ```python
   from datetime import datetime

   monitor.update_metadata({
       "benchmark": "tpch",
       "scale_factor": 1.0,
       "database": "duckdb",
       "version": "0.9.0",
       "date": datetime.now().isoformat(),
   })
   print(sorted(monitor.snapshot().metadata))
   ```

3. **Use Appropriate Metric Types**

   ```python
   current_memory = 2048.0


   def execute_query():
       pass


   monitor.increment_counter("queries_executed")

   monitor.set_gauge("memory_usage_mb", current_memory)

   with monitor.time_operation("query"):
       execute_query()

   snapshot = monitor.snapshot()
   print(snapshot.counters["queries_executed"], snapshot.gauges["memory_usage_mb"], snapshot.timings["query"].count)
   ```

4. **Set Appropriate Regression Thresholds**

   Thresholds are fractions of the previous value:

   ```python
   # Conservative: 10% threshold
   thresholds = {"query_time": 0.10}

   # Moderate: 15% threshold
   thresholds = {"query_time": 0.15}

   # Permissive: 25% threshold
   thresholds = {"query_time": 0.25}
   ```

5. **Maintain History Rolling Window**

   ```python
   history = PerformanceHistory(
       Path("bp/performance.json"),
       max_entries=100,
   )

   for _ in range(3):
       history.record(monitor.snapshot())
   print(len(history.metric_history("queries_executed")))
   ```

## Common Issues

- **Issue: "insufficient_data" from `trend`**
  - **Cause**: Fewer than 2 values for the metric in the history file.
  - **Solution**: Record more snapshots or check the metric name.
- **Issue: False regression alerts**
  - **Cause**: Natural variance or aggressive thresholds.
  - **Solution**: Increase the threshold (e.g., 0.15 to 0.20) or record the mean of more iterations.
- **Issue: Missing timings in snapshot**
  - **Cause**: The operation never ran, or it was recorded under a different name. `time_operation` records even when the block raises.
  - **Solution**: Use the same name where you record and where you read.
- **Issue: History file grows too large**
  - **Cause**: `max_entries` set too high.
  - **Solution**: Reduce `max_entries` (default: 50).
- **Issue: Percentile calculations unstable**
  - **Cause**: Too few samples.
  - **Solution**: Record more timing observations per snapshot.

<span id="not-part-of-public-contract"></span>

## Not part of the public contract

`PerformanceSnapshot`, `TimingStats`, `PerformanceRegressionAlert` and `PerformanceTracker`, with their attributes and methods, are internal names that may change without notice, so do not build on them.

<span id="benchbox.monitoring.performance.PerformanceRegressionAlert"></span><span id="benchbox.monitoring.performance.PerformanceRegressionAlert.__init__"></span><span id="benchbox.monitoring.performance.PerformanceRegressionAlert.baseline"></span><span id="benchbox.monitoring.performance.PerformanceRegressionAlert.change_percent"></span><span id="benchbox.monitoring.performance.PerformanceRegressionAlert.current"></span><span id="benchbox.monitoring.performance.PerformanceRegressionAlert.direction"></span><span id="benchbox.monitoring.performance.PerformanceRegressionAlert.metric"></span><span id="benchbox.monitoring.performance.PerformanceRegressionAlert.threshold_percent"></span><span id="benchbox.monitoring.performance.PerformanceRegressionAlert.to_dict"></span><span id="benchbox.monitoring.performance.PerformanceSnapshot"></span><span id="benchbox.monitoring.performance.PerformanceSnapshot.__init__"></span><span id="benchbox.monitoring.performance.PerformanceSnapshot.counters"></span><span id="benchbox.monitoring.performance.PerformanceSnapshot.gauges"></span><span id="benchbox.monitoring.performance.PerformanceSnapshot.metadata"></span><span id="benchbox.monitoring.performance.PerformanceSnapshot.timestamp"></span><span id="benchbox.monitoring.performance.PerformanceSnapshot.timings"></span><span id="benchbox.monitoring.performance.PerformanceSnapshot.to_dict"></span><span id="benchbox.monitoring.performance.PerformanceTracker"></span><span id="benchbox.monitoring.performance.PerformanceTracker.__init__"></span><span id="benchbox.monitoring.performance.PerformanceTracker.detect_anomalies"></span><span id="benchbox.monitoring.performance.PerformanceTracker.get_trend"></span><span id="benchbox.monitoring.performance.PerformanceTracker.record_metric"></span><span id="benchbox.monitoring.performance.TimingStats"></span><span id="benchbox.monitoring.performance.TimingStats.__init__"></span><span id="benchbox.monitoring.performance.TimingStats.count"></span><span id="benchbox.monitoring.performance.TimingStats.maximum"></span><span id="benchbox.monitoring.performance.TimingStats.mean"></span><span id="benchbox.monitoring.performance.TimingStats.median"></span><span id="benchbox.monitoring.performance.TimingStats.minimum"></span><span id="benchbox.monitoring.performance.TimingStats.p90"></span><span id="benchbox.monitoring.performance.TimingStats.p95"></span><span id="benchbox.monitoring.performance.TimingStats.p99"></span><span id="benchbox.monitoring.performance.TimingStats.to_dict"></span><span id="benchbox.monitoring.performance.TimingStats.total"></span><span id="detect_anomalies"></span><span id="get_trend"></span><span id="record_metric"></span>

## See Also

- {doc}`result-analysis` - Result analysis and comparison utilities
- {doc}`/advanced/performance-optimization` - Performance optimization guide
- {doc}`/advanced/ci-cd-integration` - CI/CD integration guide
- {doc}`/usage/troubleshooting` - Troubleshooting guide

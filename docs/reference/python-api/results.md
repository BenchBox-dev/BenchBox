# Results API

```{tags} reference, python-api, validation
```

Reference for the object that holds the outcome of a benchmark run, `BenchmarkResults`, and for the patterns that read, save and analyze it.

## Overview

The results API gives structured access to benchmark execution data:

- **`BenchmarkResults`**: a dataclass that holds the whole run.
- **`query_results`**: a list with one dict per query execution (there is no `QueryResult` class).
- **Phase timings**: `data_loading_time`, `schema_creation_time` and, in `execution_phases`, a phase breakdown.
- **Validation**: `validation_status` and `validation_details`.

`BenchmarkResults` has no serialization methods. `ResultExporter` writes a result to JSON, CSV or HTML, and `dataclasses.asdict` turns it into a dict.

## Quick Start

Run a benchmark and read the result. This needs the `duckdb` package.

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCH(scale_factor=0.01)
results = benchmark.run_with_platform(DuckDBAdapter())

print(f"Benchmark: {results.benchmark_name}")
print(f"Platform: {results.platform}")
print(f"Total time: {results.total_execution_time:.2f}s")
print(f"Success rate: {results.successful_queries}/{results.total_queries}")

for qr in results.query_results[:3]:
    print(f"{qr['query_id']}: {qr['execution_time']:.3f}s ({qr['status']})")
```

Output (times vary):

```text
Benchmark: TPC-H
Platform: DuckDB
Total time: 0.06s
Success rate: 22/22
Q1: 0.003s (SUCCESS)
Q2: 0.005s (SUCCESS)
Q3: 0.002s (SUCCESS)
```

## Core Classes

### BenchmarkResults

#### `benchbox.core.results.models.BenchmarkResults`

<span id="benchbox.core.results.models.BenchmarkResults"></span>

The container for everything a run produced: identity, timings, query results, validation outcome and platform metadata.

**Import:** `from benchbox.core.results.models import BenchmarkResults` · **Extras:** none

##### Parameters

<span id="benchbox.core.results.models.BenchmarkResults.__init__"></span>`BenchmarkResults` is a dataclass. Every field below is both a constructor parameter and an attribute, and the attributes can be reassigned. Nine fields are required; the rest have defaults. The constructor also accepts a private `_benchmark_id_override`, which is not part of the contract.

The constructor stores what it is given and derives nothing. It does not check types, and it does not compute `failed_queries`, `total_execution_time`, `average_query_time` or any other total from `query_results`. A run through `run_with_platform` fills them. When you build a result yourself, pass them in.

**Identity and counts:**

These nine are required.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.benchmark_name"></span>`benchmark_name` | `str` | required | Display name of the benchmark, for example `TPC-H`. |
| <span id="benchbox.core.results.models.BenchmarkResults.platform"></span>`platform` | `str` | required | Name of the platform that ran it, for example `DuckDB`. |
| <span id="benchbox.core.results.models.BenchmarkResults.scale_factor"></span>`scale_factor` | `float` | required | Scale factor of the data. |
| <span id="benchbox.core.results.models.BenchmarkResults.execution_id"></span>`execution_id` | `str` | required | Identifier of the run, a short string such as `872016fb`. |
| <span id="benchbox.core.results.models.BenchmarkResults.timestamp"></span>`timestamp` | `datetime` | required | Time of the run, as a `datetime`. A run executed through `run_with_platform` produced a `datetime` without a time zone. |
| <span id="benchbox.core.results.models.BenchmarkResults.duration_seconds"></span>`duration_seconds` | `float` | required | Duration of the whole run in seconds. |
| <span id="benchbox.core.results.models.BenchmarkResults.total_queries"></span>`total_queries` | `int` | required | Number of queries attempted. |
| <span id="benchbox.core.results.models.BenchmarkResults.successful_queries"></span>`successful_queries` | `int` | required | Number of queries that succeeded. |
| <span id="benchbox.core.results.models.BenchmarkResults.failed_queries"></span>`failed_queries` | `int` | required | Number of queries that failed. |

**Query data:**

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.query_results"></span>`query_results` | `list[dict[str, Any]]` | `[]` | One dict per query execution. See [Query result entries](#query-result-entries). |
| <span id="benchbox.core.results.models.BenchmarkResults.per_query_timings"></span>`per_query_timings` | `list[dict[str, Any]] \| None` | `[]` | Optional list of detailed per-query timing dicts, used for CSV export and analysis. |
| <span id="benchbox.core.results.models.BenchmarkResults.query_definitions"></span>`query_definitions` | `dict[str, dict[str, QueryDefinition]] \| None` | `None` | Optional nested mapping of the SQL text and parameters that were run. The values are `QueryDefinition` objects with `sql` and `parameters` attributes. |
| <span id="benchbox.core.results.models.BenchmarkResults.query_subset"></span>`query_subset` | `list[str] \| None` | `None` | Optional list of query ids the run was restricted to. |
| <span id="benchbox.core.results.models.BenchmarkResults.concurrency_level"></span>`concurrency_level` | `int \| None` | `None` | Optional concurrency level of the run. |
| <span id="benchbox.core.results.models.BenchmarkResults.execution_phases"></span>`execution_phases` | `ExecutionPhases \| None` | `None` | Optional phase breakdown of the run. Read [`ExecutionPhases`](#executionphases) before relying on it. |

**Timings and loaded data:**

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.total_execution_time"></span>`total_execution_time` | `float` | `0.0` | Seconds spent executing queries. This excludes data loading and schema creation. |
| <span id="benchbox.core.results.models.BenchmarkResults.average_query_time"></span>`average_query_time` | `float` | `0.0` | Mean query execution time in seconds. |
| <span id="benchbox.core.results.models.BenchmarkResults.geometric_mean_execution_time"></span>`geometric_mean_execution_time` | `float \| None` | `None` | Geometric mean of the query execution times in seconds, when the run computed it. |
| <span id="benchbox.core.results.models.BenchmarkResults.data_loading_time"></span>`data_loading_time` | `float` | `0.0` | Seconds spent loading data. |
| <span id="benchbox.core.results.models.BenchmarkResults.schema_creation_time"></span>`schema_creation_time` | `float` | `0.0` | Seconds spent creating the schema. |
| <span id="benchbox.core.results.models.BenchmarkResults.total_rows_loaded"></span>`total_rows_loaded` | `int` | `0` | Rows loaded across all tables. |
| <span id="benchbox.core.results.models.BenchmarkResults.data_size_mb"></span>`data_size_mb` | `float` | `0.0` | Size of the loaded data in megabytes. |
| <span id="benchbox.core.results.models.BenchmarkResults.table_statistics"></span>`table_statistics` | `dict[str, int]` | `{}` | Statistics per table, keyed by table name. |

**Benchmark identity and metrics:**

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.test_execution_type"></span>`test_execution_type` | `str` | `'standard'` | Kind of test the run performed. BenchBox uses `standard`, `power`, `throughput` and `maintenance`. |
| <span id="benchbox.core.results.models.BenchmarkResults.power_at_size"></span>`power_at_size` | `float \| None` | `None` | TPC power metric, when the run computed one. |
| <span id="benchbox.core.results.models.BenchmarkResults.throughput_at_size"></span>`throughput_at_size` | `float \| None` | `None` | TPC throughput metric, when the run computed one. |
| <span id="benchbox.core.results.models.BenchmarkResults.qph_at_size"></span>`qph_at_size` | `float \| None` | `None` | Always `None` for new results: BenchBox does not export QphH or QphDS. Retained so older stored results still load. |
| <span id="benchbox.core.results.models.BenchmarkResults.compliance_class"></span>`compliance_class` | `str \| None` | `None` | Comparability class of the methodology. A TPC-H run at scale factor 0.01 reported `unofficial_subscale`; TPC-DS also uses `official` and `unofficial_nonstandard`. |
| <span id="benchbox.core.results.models.BenchmarkResults.benchmark_version"></span>`benchmark_version` | `str \| None` | `None` | Optional version of the benchmark definition. |
| <span id="benchbox.core.results.models.BenchmarkResults.dataset_version"></span>`dataset_version` | `str \| None` | `None` | Optional dataset identity for manifest-backed benchmarks. |
| <span id="benchbox.core.results.models.BenchmarkResults.manifest_hash"></span>`manifest_hash` | `str \| None` | `None` | Optional manifest hash of the dataset, for manifest-backed benchmarks. |
| <span id="benchbox.core.results.models.BenchmarkResults.data_archive_hash"></span>`data_archive_hash` | `str \| None` | `None` | Optional hash of the dataset archive, for manifest-backed benchmarks. |
| <span id="benchbox.core.results.models.BenchmarkResults.data_generation_version"></span>`data_generation_version` | `int \| None` | `None` | Version of the data generator that produced the data. Results with different versions must not be compared as if equal. `None` for results that predate the stamp. |
| <span id="benchbox.core.results.models.BenchmarkResults.data_generation_hash"></span>`data_generation_hash` | `str \| None` | `None` | Fingerprint of the generator inputs behind the data. Distinguishes datasets whose specifications changed without a version change. `None` for results that predate the stamp. |

**Validation:**

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.validation_status"></span>`validation_status` | `str` | `'PASSED'` | Overall validation outcome. The default is `PASSED`; BenchBox's console output also recognises `FAILED` and `PARTIAL`. |
| <span id="benchbox.core.results.models.BenchmarkResults.validation_details"></span>`validation_details` | `dict[str, Any] \| None` | `None` | Optional dict of validation findings. Its keys are not fixed. |

**Platform, driver and machine:**

The inner keys of these dicts are filled by the platform adapters and vary by platform. They are not part of the contract.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.platform_info"></span>`platform_info` | `dict[str, Any] \| None` | `None` | Optional dict describing the platform. A DuckDB run had `platform_name`, `execution_mode`, `platform_version`, `client_library_version` and `configuration`. |
| <span id="benchbox.core.results.models.BenchmarkResults.platform_metadata"></span>`platform_metadata` | `dict[str, Any] \| None` | `None` | Optional dict of additional platform metadata. |
| <span id="benchbox.core.results.models.BenchmarkResults.platform_deployment"></span>`platform_deployment` | `PlatformDeploymentMetadata \| dict[str, Any] \| None` | `None` | Optional description of how the platform is deployed. |
| <span id="benchbox.core.results.models.BenchmarkResults.platform_cloud"></span>`platform_cloud` | `PlatformCloudMetadata \| dict[str, Any] \| None` | `None` | Optional description of the cloud the platform runs in. |
| <span id="benchbox.core.results.models.BenchmarkResults.platform_compute"></span>`platform_compute` | `PlatformComputeMetadata \| dict[str, Any] \| None` | `None` | Optional description of the platform's compute resources. |
| <span id="benchbox.core.results.models.BenchmarkResults.platform_storage"></span>`platform_storage` | `PlatformStorageMetadata \| dict[str, Any] \| None` | `None` | Optional description of the platform's storage. |
| <span id="benchbox.core.results.models.BenchmarkResults.platform_raw_config"></span>`platform_raw_config` | `dict[str, Any] \| None` | `None` | Optional dict of the platform configuration the run used. |
| <span id="benchbox.core.results.models.BenchmarkResults.platform_raw_metadata"></span>`platform_raw_metadata` | `dict[str, Any] \| None` | `None` | Optional dict of raw metadata reported by the platform. |
| <span id="benchbox.core.results.models.BenchmarkResults.execution_environment"></span>`execution_environment` | `NormalizedExecutionEnvironment \| dict[str, Any] \| None` | `None` | Optional description of the machine that ran the client. |
| <span id="benchbox.core.results.models.BenchmarkResults.system_profile"></span>`system_profile` | `dict[str, Any] \| None` | `None` | Optional dict describing the machine. A Linux run had `os_type`, `os_version`, `architecture`, `cpu_model`, `cpu_cores`, `memory_gb` and `python_version`, among others. |
| <span id="benchbox.core.results.models.BenchmarkResults.database_name"></span>`database_name` | `str \| None` | `None` | Optional name of the database the run used. |
| <span id="benchbox.core.results.models.BenchmarkResults.anonymous_machine_id"></span>`anonymous_machine_id` | `str \| None` | `None` | Optional anonymised machine identifier. |
| <span id="benchbox.core.results.models.BenchmarkResults.execution_metadata"></span>`execution_metadata` | `dict[str, Any] \| None` | `None` | Optional dict of run metadata. When it holds a non-empty string under `benchmark_id`, that string becomes [`benchmark_id`](#benchbox.core.results.models.BenchmarkResults.benchmark_id). |
| <span id="benchbox.core.results.models.BenchmarkResults.execution_context"></span>`execution_context` | `dict[str, Any] \| None` | `None` | Optional dict of the parameters the run was started with. |
| <span id="benchbox.core.results.models.BenchmarkResults.engine_version"></span>`engine_version` | `str \| None` | `None` | Optional version of the database engine or service that ran the queries. |
| <span id="benchbox.core.results.models.BenchmarkResults.engine_version_source"></span>`engine_version_source` | `str \| None` | `None` | Optional note on where `engine_version` came from, for example `sql_query`, `api`, `connection_metadata` or `driver_coupled`. |
| <span id="benchbox.core.results.models.BenchmarkResults.driver_package"></span>`driver_package` | `str \| None` | `None` | Optional name of the Python driver package. |
| <span id="benchbox.core.results.models.BenchmarkResults.driver_version_requested"></span>`driver_version_requested` | `str \| None` | `None` | Optional driver version that was requested. |
| <span id="benchbox.core.results.models.BenchmarkResults.driver_version_resolved"></span>`driver_version_resolved` | `str \| None` | `None` | Optional driver version that resolution selected. |
| <span id="benchbox.core.results.models.BenchmarkResults.driver_version_actual"></span>`driver_version_actual` | `str \| None` | `None` | Optional driver version that was loaded. |
| <span id="benchbox.core.results.models.BenchmarkResults.driver_runtime_strategy"></span>`driver_runtime_strategy` | `str \| None` | `None` | Optional strategy used to provide the driver at run time. |
| <span id="benchbox.core.results.models.BenchmarkResults.driver_runtime_path"></span>`driver_runtime_path` | `str \| None` | `None` | Optional path of the driver runtime. |
| <span id="benchbox.core.results.models.BenchmarkResults.driver_runtime_python_executable"></span>`driver_runtime_python_executable` | `str \| None` | `None` | Optional Python executable used for the driver runtime. |
| <span id="benchbox.core.results.models.BenchmarkResults.driver_auto_install"></span>`driver_auto_install` | `bool` | `False` | Whether the driver was installed automatically. |

**Tuning:**

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.tunings_applied"></span>`tunings_applied` | `dict[str, Any] \| None` | `None` | Optional dict of the tuning configuration the run requested. |
| <span id="benchbox.core.results.models.BenchmarkResults.tuning_config_hash"></span>`tuning_config_hash` | `str \| None` | `None` | Optional SHA-256 hash of the requested tuning configuration. It identifies the request, not what the platform executed. |
| <span id="benchbox.core.results.models.BenchmarkResults.applied_tuning_ledger"></span>`applied_tuning_ledger` | `dict[str, Any] \| None` | `None` | Optional dict recording the tuning statements the run executed. `None` when no tuning ran. |
| <span id="benchbox.core.results.models.BenchmarkResults.applied_ledger_hash"></span>`applied_ledger_hash` | `str \| None` | `None` | Optional SHA-256 hash of the executed tuning statements. Distinct from `tuning_config_hash`. |
| <span id="benchbox.core.results.models.BenchmarkResults.tuning_source_file"></span>`tuning_source_file` | `str \| None` | `None` | Optional reference to the tuning template: a repository-relative path, or `<basename>:<content-hash>` for a template outside the repository. |
| <span id="benchbox.core.results.models.BenchmarkResults.tuning_source"></span>`tuning_source` | `str \| None` | `None` | Optional name of how the tuning was chosen, for example `auto_discovered`, `explicit_file`, `wizard`, `fallback`, `smart_defaults` or `baseline`. |
| <span id="benchbox.core.results.models.BenchmarkResults.tuning_validation_status"></span>`tuning_validation_status` | `str` | `'not_validated'` | Outcome of validating the applied tuning. The default is `not_validated`; a DuckDB run without tuning reported `not_applicable`. |
| <span id="benchbox.core.results.models.BenchmarkResults.tuning_metadata_saved"></span>`tuning_metadata_saved` | `bool` | `False` | Whether tuning metadata was saved. |

**Performance, cost and plans:**

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.performance_characteristics"></span>`performance_characteristics` | `dict[str, Any]` | `{}` | Dict of performance data. Empty by default. |
| <span id="benchbox.core.results.models.BenchmarkResults.performance_summary"></span>`performance_summary` | `dict[str, Any]` | `{}` | Dict summarising query performance, for example `success_rate`, `throughput_qps` and `average_query_time_ms` in a DuckDB run. Empty by default. |
| <span id="benchbox.core.results.models.BenchmarkResults.summary_metrics"></span>`summary_metrics` | `dict[str, Any]` | `{}` | Dict of additional summary metrics. Empty by default. |
| <span id="benchbox.core.results.models.BenchmarkResults.cost_summary"></span>`cost_summary` | `dict[str, Any] \| None` | `None` | Optional dict of cost estimates. |
| <span id="benchbox.core.results.models.BenchmarkResults.resource_utilization"></span>`resource_utilization` | `dict[str, Any] \| None` | `None` | Optional dict of system resource readings. |
| <span id="benchbox.core.results.models.BenchmarkResults.query_plans_captured"></span>`query_plans_captured` | `int` | `0` | Number of queries whose plan was captured. |
| <span id="benchbox.core.results.models.BenchmarkResults.plan_capture_failures"></span>`plan_capture_failures` | `int` | `0` | Number of plan captures that failed. |
| <span id="benchbox.core.results.models.BenchmarkResults.plan_capture_errors"></span>`plan_capture_errors` | `list[dict[str, str]]` | `[]` | List of dicts describing plan capture failures. |
| <span id="benchbox.core.results.models.BenchmarkResults.plan_comparison_summary"></span>`plan_comparison_summary` | `dict[str, Any] \| None` | `None` | Optional dict comparing plans across runs or platforms. |
| <span id="benchbox.core.results.models.BenchmarkResults.total_plan_capture_time_ms"></span>`total_plan_capture_time_ms` | `float` | `0.0` | Total time spent capturing plans, in milliseconds. |
| <span id="benchbox.core.results.models.BenchmarkResults.avg_plan_capture_overhead_pct"></span>`avg_plan_capture_overhead_pct` | `float` | `0.0` | Average plan capture time as a percentage of query time. |
| <span id="benchbox.core.results.models.BenchmarkResults.max_plan_capture_time_ms"></span>`max_plan_capture_time_ms` | `float` | `0.0` | Longest single plan capture, in milliseconds. |
| <span id="benchbox.core.results.models.BenchmarkResults.native_comparison"></span>`native_comparison` | `NativeComparison \| None` | `None` | Optional comparison of pg_duckdb and native DuckDB timings. Set only by a pg_duckdb comparison run. |

**Provenance and output:**

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| <span id="benchbox.core.results.models.BenchmarkResults.funding"></span>`funding` | `str \| None` | `None` | Optional note on how the run was paid for. |
| <span id="benchbox.core.results.models.BenchmarkResults.result_source"></span>`result_source` | `str \| None` | `None` | Optional hint about who produced the result (`internal`, `community` or `vendor`). It is advisory only. |
| <span id="benchbox.core.results.models.BenchmarkResults.output_filename"></span>`output_filename` | `str \| None` | `None` | Optional file name that `ResultExporter` uses, minus its extension, for the exported files. |

##### Query result entries

Each item of `query_results` is a plain dict. An entry from a single-stream DuckDB run through `run_with_platform` has these keys:

| Key | Meaning |
| --- | --- |
| `query_id` | The query, for example `Q1`. |
| `status` | `SUCCESS` or `FAILED`. BenchBox's failure check treats a measurement entry as failed unless its status is `SUCCESS` or `SKIPPED`. |
| `execution_time` | Execution time in seconds. |
| `execution_time_seconds` | Execution time in seconds. |
| `execution_time_ms` | Execution time in milliseconds. |
| `rows_returned` | Number of rows the query returned. |
| `iteration` | Iteration number, starting at 1. |
| `stream_id` | Stream number, `0` for a single-stream run. |
| `run_type` | `measurement` for entries that count towards the result. |

Entries for other test types can have other keys. A failed throughput test, for example, has `execution_time_seconds` and an `error` message but no `execution_time`. Failed entries carry the message under `error`. When you mix test types, read with `qr.get("execution_time")`.

`ResultExporter.export_result` raises `ResultExportError` when an entry holds duration keys that disagree, such as `execution_time_ms=1.0` next to `execution_time=0.0022`.

##### Properties

<span id="benchbox.core.results.models.BenchmarkResults.benchmark_id"></span>**`benchmark_id`** (`str`, read-only) returns the identifier of the benchmark. It is the first of these that applies:

1. The value of `execution_metadata["benchmark_id"]`, when it is a non-empty string.
2. The benchmark name in lower case, with spaces and hyphens replaced by underscores and repeated underscores collapsed: `TPC-H Power` gives `tpc_h_power`, `Join Order` gives `join_order`.

A result returned by `run_with_platform` can carry an identifier that differs from this rule: a TPC-H run returned `tpch`.

##### Returns

A `BenchmarkResults` instance. `run_with_platform` also returns this type, and the Quick Start shows reading it.

##### Raises

`TypeError` when a required argument is missing, from the dataclass constructor. It raises nothing itself.

##### Example

```python
from datetime import datetime

from benchbox.core.results.models import BenchmarkResults

results = BenchmarkResults(
    benchmark_name="TPC-H Power",
    platform="DuckDB",
    scale_factor=1,
    execution_id="demo",
    timestamp=datetime(2026, 10, 3, 12, 0, 0),
    duration_seconds=1.0,
    total_queries=2,
    successful_queries=2,
    failed_queries=0,
)

print(results.benchmark_id)
print(results.total_execution_time)
print(results.query_results)
print(results.validation_status)
```

Output:

```text
tpc_h_power
0.0
[]
PASSED
```

##### Compatibility

`BenchmarkResults` in 0.4.1 has no `to_json_file`, `from_json_file`, `to_json`, `to_dict` or `from_dict` method, and no `QueryResult` class backs `query_results`. Calling the missing methods raises `AttributeError`. Use `ResultExporter` and `dataclasses.asdict` instead; see [Saving Results](#saving-results).

<span id="benchbox.core.results.models.BenchmarkResults.flightdata_source_provenance"></span>`flightdata_source_provenance` (`dict[str, Any] | None`) is a field of `BenchmarkResults` in the development source at SHA `c52e06e6` but not in the 0.4.1 release: its constructor takes no such argument and the attribute does not exist. Do not rely on it until a release ships it.

### ExecutionPhases

`BenchmarkResults.execution_phases` holds a breakdown of the run into setup (data generation, schema creation, data loading, validation), power test, throughput test, maintenance test and migration phases, or `None` when the run did not record one.

The class that holds it, `ExecutionPhases`, and its attributes are not part of the public contract and may change. See [Not part of the public contract](#not-part-of-the-public-contract). For setup timings that are part of the contract, read `data_loading_time` and `schema_creation_time`.

## Working with Results

### Loading Results

BenchBox 0.4.1 has no public loader that rebuilds a `BenchmarkResults` from a file. `BenchmarkResults` has no `from_json_file` or `from_dict` method. `ResultExporter.load_result_from_file` reads an exported file and returns its parsed content in a dict:

```python
from benchbox.core.results.exporter import ResultExporter

exporter = ResultExporter(output_dir="benchmark_runs")
paths = exporter.export_result(results)

loaded = exporter.load_result_from_file(paths["json"])
print(sorted(loaded))
print(loaded["version"])
print(loaded["data"]["benchmark"]["name"], loaded["data"]["summary"]["queries"])
```

Output:

```text
Exported JSON: benchmark_runs/tpch_sf001_duckdb_20261003_193125_196d1732.json
['data', 'filepath', 'result_schema_version', 'version']
2.2
TPC-H {'failed': 0, 'passed': 22, 'total': 22}
```

The `data` entry is the exported JSON document, not a `BenchmarkResults`. See {doc}`result-analysis` for the exporter and the comparison helpers.

### Saving Results

`ResultExporter` writes the result. `export_result` returns a dict that maps each format (`json` by default, also `csv` and `html`) to the path it wrote:

```python
from benchbox.core.results.exporter import ResultExporter

exporter = ResultExporter(output_dir="exports")
paths = exporter.export_result(results, formats=["json", "csv"])
print(sorted(paths))
```

Output:

```text
Exported JSON: exports/tpch_sf001_duckdb_20261003_193125_196d1732.json
Exported CSV: exports/tpch_sf001_duckdb_20261003_193125_196d1732.csv
['csv', 'json']
```

To get a plain dict, use `dataclasses.asdict`. It keeps `datetime` values as they are, so give `json.dumps` a `default`:

```python
import dataclasses
import json

payload = dataclasses.asdict(results)
print(json.dumps({key: payload[key] for key in ("benchmark_name", "platform", "scale_factor")}))
print(type(payload["timestamp"]).__name__)
```

Output:

```text
{"benchmark_name": "TPC-H", "platform": "DuckDB", "scale_factor": 0.01}
datetime
```

## Analyzing Results

The examples in this section use this small result, built by hand so that the output is the same on every run:

```python
from datetime import datetime

from benchbox.core.results.models import BenchmarkResults

results = BenchmarkResults(
    benchmark_name="TPC-H",
    platform="DuckDB",
    scale_factor=0.1,
    execution_id="demo01",
    timestamp=datetime(2026, 10, 3, 12, 0, 0),
    duration_seconds=2.0,
    total_queries=4,
    successful_queries=3,
    failed_queries=1,
    query_results=[
        {"query_id": "Q1", "status": "SUCCESS", "execution_time": 0.5, "rows_returned": 4, "stream_id": 0},
        {"query_id": "Q6", "status": "SUCCESS", "execution_time": 0.125, "rows_returned": 1, "stream_id": 0},
        {"query_id": "Q9", "status": "SUCCESS", "execution_time": 1.0, "rows_returned": 175, "stream_id": 0},
        {"query_id": "Q13", "status": "FAILED", "execution_time": 0.0, "rows_returned": 0, "stream_id": 0,
         "error": "out of memory"},
    ],
    total_execution_time=1.625,
    average_query_time=1.625 / 3,
)
```

### Query Performance Analysis

```python
import statistics

slowest = sorted(results.query_results, key=lambda qr: qr["execution_time"], reverse=True)

print("Slowest queries:")
for qr in slowest[:3]:
    print(f"{qr['query_id']}: {qr['execution_time']:.3f}s")

times = [qr["execution_time"] for qr in results.query_results if qr["status"] == "SUCCESS"]

print(f"Median: {statistics.median(times):.3f}s")
print(f"Mean: {statistics.mean(times):.3f}s")
print(f"Stdev: {statistics.stdev(times):.3f}s")
```

Output:

```text
Slowest queries:
Q9: 1.000s
Q1: 0.500s
Q6: 0.125s
Median: 0.500s
Mean: 0.542s
Stdev: 0.439s
```

### Geometric Mean Calculation

Standard for TPC benchmarks. `BenchmarkResults.geometric_mean_execution_time` holds the value when the run computed it. To compute it yourself:

```python
import math


def geometric_mean(values):
    if not values:
        return 0.0
    return math.prod(values) ** (1.0 / len(values))


times = [qr["execution_time"] for qr in results.query_results if qr["status"] == "SUCCESS"]
print(f"Geometric mean: {geometric_mean(times):.3f}s")
```

Output:

```text
Geometric mean: 0.397s
```

### Result Comparison

Compare two benchmark runs:

```python
import dataclasses


def compare_results(baseline, current, threshold=1.1):
    baseline_times = {
        qr["query_id"]: qr["execution_time"]
        for qr in baseline.query_results
        if qr["status"] == "SUCCESS"
    }
    current_times = {
        qr["query_id"]: qr["execution_time"]
        for qr in current.query_results
        if qr["status"] == "SUCCESS"
    }

    regressions = []
    improvements = []

    for qid in baseline_times:
        if qid in current_times:
            ratio = current_times[qid] / baseline_times[qid]
            entry = {
                "query_id": qid,
                "baseline": baseline_times[qid],
                "current": current_times[qid],
                "ratio": ratio,
            }
            if ratio > threshold:
                regressions.append(entry)
            elif ratio < (1 / threshold):
                improvements.append(entry)

    return {"regressions": regressions, "improvements": improvements}


baseline = results
current = dataclasses.replace(
    results,
    query_results=[
        {**qr, "execution_time": qr["execution_time"] * factor}
        for qr, factor in zip(results.query_results, (1.0, 0.5, 1.5, 1.0))
    ],
)
comparison = compare_results(baseline, current, threshold=1.1)

print(f"Found {len(comparison['regressions'])} regressions:")
for r in comparison["regressions"]:
    print(f"  {r['query_id']}: {r['ratio']:.2f}x slower")
print(f"Found {len(comparison['improvements'])} improvements:")
for r in comparison["improvements"]:
    print(f"  {r['query_id']}: {1 / r['ratio']:.2f}x faster")
```

Output:

```text
Found 1 regressions:
  Q9: 1.50x slower
Found 1 improvements:
  Q6: 2.00x faster
```

### Export to DataFrame

For analysis in pandas:

```python
import pandas as pd

df = pd.DataFrame(
    [
        {
            "query_id": qr["query_id"],
            "execution_time": qr["execution_time"],
            "status": qr["status"],
            "rows_returned": qr["rows_returned"],
            "stream_id": qr["stream_id"],
        }
        for qr in results.query_results
    ]
)

print(df["execution_time"].describe())
print(df.groupby("status").size())

successful = df[df["status"] == "SUCCESS"]
successful.plot(x="query_id", y="execution_time", kind="bar")
```

Output:

```text
count    4.000000
mean     0.406250
std      0.449247
min      0.000000
25%      0.093750
50%      0.312500
75%      0.625000
max      1.000000
Name: execution_time, dtype: float64
status
FAILED     1
SUCCESS    3
dtype: int64
```

## Validation Results

### Check Result Correctness

```python
import dataclasses


def report(result):
    if result.validation_status == "PASSED":
        print("All validation checks passed")
    else:
        print(f"Validation {result.validation_status}:")
        for check, details in (result.validation_details or {}).items():
            print(f"  {check}: {details}")


report(results)
report(dataclasses.replace(
    results,
    validation_status="FAILED",
    validation_details={"row_count_matches": False},
))
```

Output:

```text
All validation checks passed
Validation FAILED:
  row_count_matches: False
```

### Row Count Validation

```python
def validate_row_counts(results, expected_counts):
    mismatches = []

    for qr in results.query_results:
        if qr["query_id"] in expected_counts:
            expected = expected_counts[qr["query_id"]]
            if qr["rows_returned"] != expected:
                mismatches.append({
                    "query_id": qr["query_id"],
                    "expected": expected,
                    "actual": qr["rows_returned"],
                })

    return mismatches


expected_counts = {
    "Q1": 4,
    "Q6": 1,
    "Q9": 170,
}

mismatches = validate_row_counts(results, expected_counts)
if mismatches:
    print("Row count mismatches found:")
    for m in mismatches:
        print(f"  {m['query_id']}: expected {m['expected']}, got {m['actual']}")
```

Output:

```text
Row count mismatches found:
  Q9: expected 170, got 175
```

## System Information

### Access Execution Context

These dicts are filled by runs that go through a platform adapter, and they are `None` on a result you build by hand. `quickstart_results` below is the result from the [Quick Start](#quick-start). The keys shown are those a Linux DuckDB run produced; the contract does not fix them.

```python
print(f"OS: {quickstart_results.system_profile['os_type']} {quickstart_results.system_profile['os_version']}")
print(f"CPU: {quickstart_results.system_profile['cpu_model']}")
print(f"RAM: {quickstart_results.system_profile['memory_gb']:.1f}GB")
print(f"Python: {quickstart_results.system_profile['python_version']}")

print(f"Platform: {quickstart_results.platform_info['platform_name']}")
print(f"Version: {quickstart_results.platform_info['platform_version']}")
print(f"Client library: {quickstart_results.platform_info['client_library_version']}")
```

Output:

```text
OS: Linux 6.18.44-fc-v64
CPU: Intel(R) Xeon(R) Processor @ 2.10GHz
RAM: 15.7GB
Python: 3.11.15
Platform: DuckDB
Version: 1.5.6
Client library: 1.5.6
```

### Execution Metadata

These fields are filled by runs that go through a platform adapter. `quickstart_results` below is the result from the [Quick Start](#quick-start). The keys inside `performance_summary` are those a DuckDB run produced.

```python
print(f"Schema creation: {quickstart_results.schema_creation_time:.3f}s")
print(f"Data loading: {quickstart_results.data_loading_time:.3f}s")

summary = quickstart_results.performance_summary
print(f"Success rate: {summary['success_rate']:.0%}")
print(f"Throughput: {summary['throughput_qps']:.1f} queries/s")
print(f"Geometric mean: {quickstart_results.geometric_mean_execution_time:.4f}s")
```

Output (values vary):

```text
Schema creation: 0.000s
Data loading: 0.005s
Success rate: 100%
Throughput: 58.8 queries/s
Geometric mean: 0.0024s
```

`BenchmarkResults.execution_phases` also holds per-phase timings, but its class is not part of the public contract. See [ExecutionPhases](#executionphases).

## Performance Tracking

### Time Series Analysis

Track performance over time. Export each run with `ResultExporter` into one directory, then read the files back with `json`:

```python
import dataclasses
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from benchbox.core.results.exporter import ResultExporter

exporter = ResultExporter(output_dir="history")
for day, factor in ((1, 1.0), (2, 1.2)):
    run = dataclasses.replace(
        results,
        execution_id=f"run{day}",
        timestamp=datetime(2026, 10, day, 12, 0, 0),
        query_results=[{**qr, "execution_time": qr["execution_time"] * factor} for qr in results.query_results],
    )
    exporter.export_result(run)


def load_historical_results(results_dir):
    rows = []
    for file_path in sorted(Path(results_dir).glob("**/*.json")):
        data = json.loads(file_path.read_text())
        for query in data["queries"]:
            rows.append({
                "timestamp": data["run"]["timestamp"],
                "query_id": query["id"],
                "execution_time": query["ms"] / 1000,
                "status": query["status"],
                "platform": data["platform"]["name"],
                "scale_factor": data["benchmark"]["scale_factor"],
            })
    return pd.DataFrame(rows)


df = load_historical_results("history")

trends = df.groupby(["query_id", "timestamp"])["execution_time"].mean()
print(trends)
```

Output:

```text
Exported JSON: history/tpc_h_sf01_duckdb_20261001_120000_run1.json
Exported JSON: history/tpc_h_sf01_duckdb_20261002_120000_run2.json
query_id  timestamp
1         2026-10-01T12:00:00    0.500
          2026-10-02T12:00:00    0.600
13        2026-10-01T12:00:00    0.000
          2026-10-02T12:00:00    0.000
6         2026-10-01T12:00:00    0.125
          2026-10-02T12:00:00    0.150
9         2026-10-01T12:00:00    1.000
          2026-10-02T12:00:00    1.200
Name: execution_time, dtype: float64
```

### Regression Detection

Automated regression alerting:

```python
def detect_regressions(current_results, baseline_results, threshold=1.15):
    alerts = []

    baseline_map = {
        qr["query_id"]: qr["execution_time"]
        for qr in baseline_results.query_results
        if qr["status"] == "SUCCESS"
    }

    for qr in current_results.query_results:
        if qr["status"] != "SUCCESS":
            continue

        if qr["query_id"] in baseline_map:
            baseline_time = baseline_map[qr["query_id"]]
            ratio = qr["execution_time"] / baseline_time

            if ratio > threshold:
                alerts.append({
                    "severity": "HIGH" if ratio > 1.5 else "MEDIUM",
                    "query_id": qr["query_id"],
                    "baseline": baseline_time,
                    "current": qr["execution_time"],
                    "regression": f"{(ratio - 1) * 100:.1f}%",
                })

    return sorted(alerts, key=lambda x: x["current"], reverse=True)


alerts = detect_regressions(current, baseline, threshold=1.15)
if alerts:
    print(f"{len(alerts)} performance regressions detected:")
    for alert in alerts:
        print(f"  [{alert['severity']}] {alert['query_id']}: +{alert['regression']} regression")
```

Output:

```text
1 performance regressions detected:
  [MEDIUM] Q9: +50.0% regression
```

## Best Practices

### Result Storage

1. **Let the exporter name the files.** `ResultExporter` builds names from the benchmark, scale factor, platform, timestamp and run id. Set `output_filename` to choose one:

```python
from benchbox.core.results.exporter import ResultExporter

results.output_filename = "tpch_sf1_duckdb_baseline.json"
paths = ResultExporter(output_dir="benchmark_runs").export_result(results)
print(paths["json"].name)
```

Output:

```text
Exported JSON: benchmark_runs/tpch_sf1_duckdb_baseline.json
tpch_sf1_duckdb_baseline.json
```

1. **Version control results** for important baselines:

   ```bash
   git add benchmark_runs/baseline/tpch_sf1_duckdb.json
   git commit -m "Add TPC-H SF1 baseline"
   ```

2. **Compress old results**:

   ```bash
   gzip benchmark_runs/archive/*.json
   ```

### Result Analysis

1. **Always check validation status** before trusting results
2. **Use geometric mean** for TPC benchmarks (not arithmetic mean)
3. **Compare like with like** (same scale factor, system profile)
4. **Account for variance** with multiple runs

### Performance Monitoring

1. **Establish baseline** with known-good configuration
2. **Track over time** to detect gradual degradation
3. **Set alert thresholds** (e.g., 15% regression)
4. **Investigate outliers** before dismissing as noise

<span id="not-part-of-public-contract"></span>

## Not part of the public contract

`ExecutionPhases` and its attributes `setup`, `power_test`, `throughput_test`, `maintenance_test` and `migration` are internal names that may change without notice, so do not build on them.

<span id="benchbox.core.results.models.ExecutionPhases"></span><span id="benchbox.core.results.models.ExecutionPhases.__init__"></span><span id="benchbox.core.results.models.ExecutionPhases.setup"></span><span id="benchbox.core.results.models.ExecutionPhases.power_test"></span><span id="benchbox.core.results.models.ExecutionPhases.throughput_test"></span><span id="benchbox.core.results.models.ExecutionPhases.maintenance_test"></span><span id="benchbox.core.results.models.ExecutionPhases.migration"></span>

## See Also

### Conceptual Documentation

- {doc}`/concepts/data-model` - Complete data model reference
- {doc}`/concepts/architecture` - How results fit into BenchBox
- {doc}`/concepts/workflow` - Result collection in workflows

### API Reference

- {doc}`base` - Base benchmark interface
- {doc}`index` - Python API overview
- {doc}`/reference/api-reference` - High-level API guide

### Guides

- {doc}`/advanced/performance` - Performance monitoring
- {doc}`/guides/tpc/tpc-validation-guide` - TPC compliance validation
- {doc}`/usage/examples` - Result analysis examples

### External Resources

- {doc}`/reference/result-schema-v1` - JSON schema specification

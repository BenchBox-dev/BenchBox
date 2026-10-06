# Benchmark Result Schema (v1.1)

```{tags} reference, validation
```

The canonical JSON schema describes every benchmark export produced by BenchBox.
It applies uniformly to CLI and platform execution flows now that all pipelines
emit the lifecycle-aware `BenchmarkResults` model, replacing the legacy
`BenchmarkResult` payloads.

## Top-Level Structure

| Key | Description |
| --- | --- |
| `schema_version` | Literal string `"1.1"`. Increment when the shape changes. |
| `benchmark` | Identifier, human-readable name, and optional version of the benchmark. |
| `execution` | Execution metadata (ID, timestamp, duration, executor/platform, database name, optional metadata). |
| `configuration` | Run configuration including scale factor, concurrency level, query subset, and options. |
| `system` | Anonymised system profile (OS, architecture, CPU count, memory, Python version, hostname, username). |
| `results` | Metrics organized into `queries`, `timing`, optional `tables`, and optional `metrics`. |
| `validation` | `status` (`PASSED`, `FAILED`, `PARTIAL`, `UNKNOWN`) and optional structured `details`. |
| `driver` | Driver metadata: package, requested/resolved versions, and auto-install flag. |
| `export` | Export audit block with timestamp, exporter tool identifier, schema version, and anonymisation flag. |
| `platform` | *(Optional)* Platform metadata (name, additional metadata, tunings, info). Present for adapter runs. |
| `phases` | *(Optional)* Execution phase breakdown when available. |
| `metadata` | *(Optional)* Auxiliary metadata (e.g., `anonymous_machine_id`). |

## Results Payload

### `results.queries`

| Key | Description |
| --- | --- |
| `total` | Total number of queries dispatched. |
| `successful` | Number of queries that completed with `status == "SUCCESS"`. |
| `failed` | Number of queries that failed (derived). |
| `success_rate` | Ratio of `successful / total`, rounded to 4 decimal places (0.0 when `total == 0`). |
| `details` | Ordered list of per-query metrics. |
| `definitions` | Optional nested mapping of query definitions (present when `BenchmarkResults.query_definitions` is populated). |

Each entry of `details` uses the following fields (missing values are omitted). This nested array replaces the
legacy top-level `query_details` payload that existed in the v2/v3 exports.

- `id` (query identifier, e.g., `Q1`)
- `name`
- `status`
- `sequence` (execution order)
- `stream_id` (for throughput workloads)
- `iteration` *(optional)*, iteration number for power tests with warm-up/measurement loops
- `run_type` *(optional)*, `warmup` or `measurement` classification when iterations are used
- `execution_time_ms`
- `rows_returned`
- `error_message`
- `sql_text` (truncated to 4096 characters with a `/* truncated */` marker)
- `sql_truncated` (present only when truncation occurred)
- `resource_usage`
- `row_count_validation` *(optional)*, nested object containing per-query validation results:
  - `expected`, expected number of rows
  - `actual`, actual number of rows returned
  - `status`, validation status (`PASSED`, `FAILED`, `SKIPPED`)
  - `error` *(optional)*, error message when validation fails
  - `warning` *(optional)*, warning message when validation is skipped

> **Why 4096 characters?** BenchBox caps SQL text at 4KB per query to keep
> JSON exports compact (<5 KB/query) while still preserving useful debugging
> context. Consumers can detect truncation programmatically via the
> `sql_truncated` flag.

### `results.timing`

- `total_ms`: Total query execution time in milliseconds.
- `avg_ms`: Average query time (milliseconds) across successful queries.
- `min_ms` / `max_ms`: Minimum and maximum execution time (present for CLI results).
- `data_loading_ms`: Optional data loading duration (milliseconds).
- `schema_creation_ms`: Optional schema creation duration (milliseconds).

### `results.tables`

Populated for platform adapter exports:

- `total_rows_loaded`
- `data_size_mb`
- `per_table`: mapping of table name to row count (or other relevant figures).

### `results.metrics`

Flexible container for benchmark-specific metrics:

- `summary`: arbitrary key/value metrics (populated from `BenchmarkResults.performance_summary`
  or other custom extras attached during result construction).
- `performance_summary`: aggregated figures from platform adapters.
- `performance_characteristics`: optional qualitative metrics.
- `tpc`: standard TPC metrics such as `power_at_size`, `throughput_at_size`, and `geometric_mean_ms`. Exports no longer carry `qphh_at_size` or `qphds_at_size`; older bundles may still contain them and the loader still reads them.

## Export Block

The exporter populates:

```json
"export": {
  "timestamp": "2025-09-01T12:00:00.000123",
  "tool": "benchbox-exporter",
  "schema_version": "1.1",
  "anonymized": true
}
```

When anonymisation is enabled an anonymised system profile is merged into `system`
and an `anonymous_machine_id` is emitted under `metadata`.

## Validation

The validation block has a two-tier structure optimized for size and accessibility:

- `validation.status`, overall validation status: `PASSED`, `FAILED`, `PARTIAL`, or `UNKNOWN`
- `validation.summary`, lightweight summary metrics:
  - `total_tables_validated`, number of tables validated
  - `tables_with_data`, number of tables with data
  - `error_count`, number of validation errors
  - `warning_count`, number of validation warnings
- `validation.details_location`, pointer to full validation details (`phases.setup.validation.validation_details`)

Full validation details (including `verified_tables`, `accessible_tables`, and other detailed information)
are available at `phases.setup.validation.validation_details` to avoid duplicating large arrays.

For per-query validation results, see the `row_count_validation` field in `results.queries.details`.

For anonymised exports the system profile is scrubbed prior to validation and anonymisation metadata is
recorded under `export.anonymized` and `metadata.anonymous_machine_id`. Anonymisation therefore never breaks
schema validation because the payload is transformed before `CanonicalResultValidator` runs.

## Compatibility Notes

- Legacy `schema_version` values (`"2.0"`, `"3.0"`) and their supporting fields (e.g.,
  `benchmark_info`, `performance_metrics`, top-level `query_results`) have been removed.
- Consumers must migrate to the canonical layout before the first public release.
- Version 1.1 adds optional `iteration` and `run_type` fields to `results.queries.details` so
  consumers can distinguish warm-up runs from measurement runs while keeping the payload
  backward compatible for clients that ignore unknown keys.
- Future schema adjustments should bump `SCHEMA_VERSION` and update this document.

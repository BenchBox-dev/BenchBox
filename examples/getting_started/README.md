# Getting Started Examples

These examples add a gentle on-ramp to BenchBox without replacing the
fully featured `examples/unified_runner.py`. Start here, then graduate to
the unified runner once you are comfortable with the workflow.

## Progression

1. **Basic (local DuckDB)** - end-to-end power tests for TPC-H and TPC-DS
   with almost no configuration.
2. **Intermediate (local DuckDB)** - focuses on a common option: running a
   targeted subset of queries for quick smoke tests.
3. **Cloud** - shows the minimum viable setup for Databricks and how to use
   the dry-run tooling to validate BigQuery environments before spending
   credits.

## Local “Hello World” Scripts

| Benchmark | Script                        | Feature Highlight              |
| --------- | ----------------------------- | ------------------------------ |
| TPC-H     | `local/duckdb_tpch_power.py`  | Generate data + run power test |
| TPC-DS    | `local/duckdb_tpcds_power.py` | Same workflow at TPC-DS scale  |

Run from the repository root:

```bash
python examples/getting_started/local/duckdb_tpch_power.py --scale 0.1
python examples/getting_started/local/duckdb_tpch_power.py --scale 0.1 --dry-run ./preview/duckdb_tpch
python examples/getting_started/local/duckdb_tpcds_power.py --scale 0.1
python examples/getting_started/local/duckdb_tpcds_power.py --scale 0.1 --dry-run ./preview/duckdb_tpcds
```

Each script accepts `--scale`, `--force`, and the new
`--dry-run OUTPUT_DIR` flag. When `--dry-run` is provided the script skips
data generation/query execution and writes a JSON + YAML preview along with
per-query SQL files to the chosen directory. Standard executions continue to
store outputs in `benchmark_runs/getting_started/duckdb`.

## Intermediate Example (Query Subset)

- `intermediate/duckdb_tpch_query_subset.py`
  - Runs a user-specified subset of TPC-H queries (defaults to `1,6`).
  - Demonstrates the `query_subset` configuration without exposing every
    CLI option.

```bash
python examples/getting_started/intermediate/duckdb_tpch_query_subset.py --queries 1,6,12
python examples/getting_started/intermediate/duckdb_tpch_query_subset.py --queries 3,7 --dry-run ./preview/duckdb_tpch_subset
```

## Cloud-Focused Examples

- `cloud/databricks_tpch_power.py`
  - Minimal Databricks SQL Warehouse run using
    `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH`, and `DATABRICKS_TOKEN`.
  - Supports `--dry-run OUTPUT_DIR` to preview the job without a running
    warehouse; artifacts highlight required credentials and planned phases.
  - Keeps full executions inside `benchmark_runs/getting_started/databricks`.

- `cloud/bigquery_tpch_dry_run.py`
  - Uses the `DryRunExecutor` to inspect a BigQuery configuration without
    launching jobs. Requires `BIGQUERY_PROJECT` and `BIGQUERY_DATASET`.
  - `--dry-run OUTPUT_DIR` lets you redirect preview artifacts for multiple
    environments (e.g. staging vs production datasets).

These scripts surface clear errors when credentials are missing so they
behave predictably in clean environments.

## Troubleshooting

- **`ImportError: DuckDB not installed`** - install the core extra with
  `uv pip install duckdb` or install BenchBox via `uv add benchbox`.
- **`databricks-sql-connector` missing** - install `benchbox[databricks]`
  or `benchbox[cloud]` before running the Databricks example.
- **BigQuery dry run warnings** - lack of the Google client libraries or
  credentials adds a warning to the dry-run output but still writes the
  preview files so you can confirm configuration.

## Dry Run Artifacts at a Glance

- JSON + YAML report summarising configuration, query list, schema preview,
  and resource estimates.
- One SQL file per query in `*_queries_<timestamp>/` for quick inspection.
- Optional schema DDL file (`*_schema_<timestamp>.sql`) when schema
  generation is supported.
- Rich console summary describing benchmark mode, estimated scale, and
  platform highlights. Sample outputs live in `examples/dry_run_samples/`.

## Where To Go Next

When you are ready for advanced workflows - multiple benchmarks, automatic
comparison reports, and dry-run/export flows - use the existing
`examples/unified_runner.py`. The unified runner remains the canonical
“power user” entry point and now complements these additive, focused
examples.

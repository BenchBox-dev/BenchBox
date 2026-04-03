# Corpus Generation Notes — 2026-04-03

## Platforms Run

### TPC-H (SF 0.01)
- **DuckDB 1.4.3** — PASSED, 22 queries, 3 measurement runs
- **DataFusion 51.0.0** — PASSED, 22 queries, 3 measurement runs
- **Polars 1.37.1** — PASSED, 22 queries, 3 measurement runs (DataFrame mode)

### SSB / Star Schema (SF 0.01)
- **DuckDB 1.4.3** — PASSED, 13 queries, 3 measurement runs
- **DataFusion 51.0.0** — PASSED, 13 queries, 3 measurement runs
- **SQLite 3.50.4** — PASSED, 13 queries, 3 measurement runs

## Skips and Notes

### Polars-df SSB — Skipped (0 queries)
`polars-df` with SSB benchmark emitted 0 queries during execution ("No queries
found for execution"). SSB DataFrame queries are not implemented for the Polars
platform. SQLite was used as the third platform for SSB instead.

### Export bug fix
The `benchbox export` command failed with `TypeError: type NoneType doesn't
define __round__ method` when `load_time_ms` was `None` in `table_statistics`.
Fixed in `benchbox/core/results/schema.py` by guarding `round()` calls with
`is not None` checks.

### Export --last filter caveat
`benchbox export --last --benchmark ssb --platform duckdb` did not find SSB
results because the schema v2 `benchmark.id` field is `star_schema` (not `ssb`).
The `--last --benchmark` filter compares against the JSON `benchmark.id`, so
results were exported directly by filename.

## Cohort Depth
Both cohorts meet the >=3-platform depth criterion required for the Compare view:
- `tpch SF=0.01`: DuckDB, DataFusion, Polars
- `star_schema SF=0.01`: DuckDB, DataFusion, SQLite

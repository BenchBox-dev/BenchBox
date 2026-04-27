# DuckDB TPC-H Extension vs BenchBox TPC-H Validation (2026-03-02)

## Objective

Capture a small, reproducible two-scale comparison with explicit timing boundaries:

1. Engine query-path timing
2. End-to-end workflow timing

## Environment

- Date: 2026-03-02
- Host: macOS 26.3 (`Darwin 25.3.0`, arm64)
- Python: 3.11.12
- BenchBox: 0.1.3
- DuckDB (Python package): 1.4.3

## Methodology

### DuckDB extension path

- In-memory DuckDB session
- Commands:
  - `INSTALL tpch; LOAD tpch;`
  - `CALL dbgen(sf=<scale>)`
  - One warmup `PRAGMA tpch(1)`, then 3 measured runs
- Workflow timing boundary:
  - `INSTALL + LOAD + dbgen + first PRAGMA tpch(1)`
- Engine timing boundary:
  - Median of the 3 measured `PRAGMA tpch(1)` runs

Raw data file:
- `_blog/building-benchbox/research/tpch-extension-vs-benchbox-measurements-2026-03-02.json`

### DuckDB extension API scope check

To validate maintenance-operation scope, we inspected available `tpch` extension entry points after:

```sql
INSTALL tpch;
LOAD tpch;
```

Observed extension objects from `duckdb_functions()`:

- `tpch` (pragma)
- `tpch_answers` (table)
- `tpch_queries` (table)

No RF1/RF2 maintenance entry points were present in this inspection.

### Query text extraction check (scale and permutation)

We extracted Q6 query text from both paths:

- DuckDB extension: `SELECT query FROM tpch_queries() WHERE query_nr = 6`
- BenchBox: `TPCHBenchmark.get_query(6, ..., dialect="duckdb")`

Observed behavior in this local run:

- Extension Q6 text was fixed (example constants included `1994-01-01`, discount `0.05..0.07`, quantity `< 24`).
- BenchBox Q6 text changed with seed:
  - `seed=0`: `1993-01-01`, discount centered at `0.02`, quantity `< 24`
  - `seed=7`: `1994-01-01`, discount centered at `0.08`, quantity `< 25`
- BenchBox Q6 text also changed with stream-derived permutation seed:
  - `params={"stream_id": 0}` and `params={"stream_id": 1}` produced different substitutions.

Scale sensitivity check (fixed seed `42`, Q1-Q22):

- BenchBox query text changed between SF1 and SF10 only for Q11 in this run.
- Q11 changed the HAVING threshold multiplier from `0.0001000000` (SF1) to `0.0000100000` (SF10).

### BenchBox path

- Commands:
  - `uv run benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases generate,load,power --queries 1 --force datagen --non-interactive`
  - `uv run benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate,load,power --queries 1 --force datagen --non-interactive`
- Workflow timing boundary:
  - Shell wall-clock `real` from `/usr/bin/time -p`
- Engine timing boundary:
  - `summary.timing.geometric_mean_ms` from result JSON (3 measurement runs in power test)

Result files:
- `benchmark_runs/results/tpch_sf001_duckdb_sql_20260302_092013_6f872099.json`
- `benchmark_runs/results/tpch_sf1_duckdb_sql_20260302_092035_1b6dd90b.json`

Logs:
- `/tmp/bb_tpch_sf001_q1_forcedatagen.log`
- `/tmp/bb_tpch_sf1_q1_forcedatagen.log`

## Results

| Scale | Extension engine timing (Q1 median ms) | BenchBox engine timing (Q1 geometric mean ms) | Extension workflow timing (ms) | BenchBox workflow timing (ms) |
| --- | ---: | ---: | ---: | ---: |
| 0.01 | 5.572 | 8.0 | 138.193 | 2310 |
| 1 | 39.071 | 31.3 | 4651.215 | 2360 |

## Notes

- This is a bounded methodology sample for blog narrative support, not an official benchmark comparison.
- Query subset mode (`--queries 1`) is not TPC-H compliant for official reporting.
- Engine and workflow boundaries must remain separate in interpretation.

# DuckDB Architecture Claim Verification (2026-02-20)

## Objective
Validate the statement that DuckDB processes TPC-H SF10 "in under 10 seconds" on this machine.

## Environment Snapshot
- Timestamp (UTC): 2026-02-20T13:20:36Z
- OS: macOS 26.3 (25D125)
- Kernel: Darwin 25.3.0 (arm64)
- Python: 3.11.12
- DuckDB: 1.4.3
- BenchBox CLI: 0.1.3 (`.venv/bin/benchbox`)

## Hardware Context (w4)
- Device: Mac mini (`Mac16,10`)
- Chip: Apple M4
- Cores: 10 total (4 performance + 6 efficiency)
- Memory: 16 GB
- Storage: Apple NVMe SSD (`APPLE SSD AP0256Z`, TRIM enabled)

## Fixed Benchmark Command
`/usr/bin/time -p .venv/bin/benchbox run --platform duckdb --benchmark tpch --scale 10 --non-interactive`

All three trials use the exact same command.

## Baseline Trial (w2)
- Log: `/tmp/duckdb_arch_sf10_run1.log`
- Result JSON: `benchmark_runs/results/tpch_sf10_duckdb_sql_20260220_082141_629e754c.json`
- End-to-end command wall time (`real`): `23.44s`
- Measurement run totals inside benchmark:
  - Run 1: `4.74s`
  - Run 2: `4.84s`
  - Run 3: `6.07s`

## Additional Trials + Median (w3)
- Trial 2 log: `/tmp/duckdb_arch_sf10_run3.log`
- Trial 2 result JSON: `benchmark_runs/results/tpch_sf10_duckdb_sql_20260220_082331_1dea1e5a.json`
- Trial 2 wall time (`real`): `21.02s`
- Trial 3 log: `/tmp/duckdb_arch_sf10_run4.log`
- Trial 3 result JSON: `benchmark_runs/results/tpch_sf10_duckdb_sql_20260220_082357_98034fae.json`
- Trial 3 wall time (`real`): `20.61s`

Wall-time summary across the three clean trials:
- Trial 1: `23.44s`
- Trial 2: `21.02s`
- Trial 3: `20.61s`
- Median wall time: `21.02s`
- Mean wall time: `21.69s`

Query-execution totals (power test, per measurement run) were consistently in the ~`4.5s` to `6.1s` range.

## Cross-Check (w7)
- Draft claim: median end-to-end wall time is about `21.02s`.
  - Evidence: `real` from logs
    - `/tmp/duckdb_arch_sf10_run1.log` -> `23.44`
    - `/tmp/duckdb_arch_sf10_run3.log` -> `21.02`
    - `/tmp/duckdb_arch_sf10_run4.log` -> `20.61`
- Draft claim: all 22 TPC-H power queries execute within roughly `4.5s` to `6.1s` total per measurement pass.
  - Evidence: `Total execution time` lines across the same three logs.
- Draft reproducibility command:
  - Matches command used for all captured runs in this note.

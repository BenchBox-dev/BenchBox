# DuckDB Architecture: Updated Performance Claim Notes

## Updated Claim (TPC-H SF10)

DuckDB can execute a full TPC-H SF10 power run quickly on modern local hardware, but our measured end-to-end command time is not "under 10 seconds".

On a Mac mini (Apple M4, 16 GB RAM), we measured:
- End-to-end BenchBox command wall time (3 clean trials): `23.44s`, `21.02s`, `20.61s`
- Median end-to-end wall time: `21.02s`
- Per-measurement query execution totals inside each run: approximately `4.5s` to `6.1s` for all 22 TPC-H power queries

This is the statement to use in the draft instead of the older "under 10 seconds" wording.

## Reproducibility

Run the exact command below on a comparable machine:

```bash
/usr/bin/time -p .venv/bin/benchbox run --platform duckdb --benchmark tpch --scale 10 --non-interactive
```

Run it 3 times and report median wall time (`real`). Also capture the BenchBox result JSON paths for traceability.

### Run Notes

- Keep platform/benchmark/scale fixed across all trials.
- Use `--non-interactive` to avoid prompt-related variance.
- Record both:
  - shell wall time (`real` from `/usr/bin/time -p`)
  - in-run TPC-H measurement totals printed by BenchBox

## Notes

- These measurements reused an existing SF10 DuckDB database when available.
- If schema/data must be recreated, runtime can increase significantly due to load/setup work.
- Full evidence and logs: `_blog/platform-deep-dives/research/duckdb-architecture-verification-2026-02-20.md`

# Canonical JoinOrder stays non-blocking; joinorder_synthetic stays the gate

Date: 2026-09-27

Status: Accepted.

## Decision

`joinorder_synthetic` remains the sole blocking cross-surface CI gate for
JoinOrder-family coverage (`.github/workflows/pr.yml`, the
`joinorder-synthetic-cross-surface-equivalence-report` step). The canonical
`joinorder` suite (canonical IMDb 2013, 113 queries) stays non-blocking and
manual. No canonical-JOB blocking CI step is added by this change, and the
promotion option is struck: if canonical coverage is ever wanted, it becomes a
new explicitly scoped item rather than a reopening of this record.

## Cost evidence

- Dataset: canonical IMDb 2013 archive fetched on first use per
  `benchbox/core/joinorder/data_manifest.toml` (dataset
  `joinorder-imdb-2013-v1`, multi-GB compressed Parquet). The largest fact
  table, `cast_info`, carries 36,244,344 rows in the manifest.
- Query volume: 113 canonical queries (`benchmark_registry.yaml`
  `num_queries: 113`), executed across the SQL plus expression and pandas
  DataFrame surfaces.
- Scale lock: the benchmark accepts only `--scale 1`
  (`benchbox/core/joinorder/benchmark.py`); there is no bounded small cell
  that keeps all 113 queries discriminating the way the synthetic gate's
  bounded DuckDB cell does.
- The synthetic gate exists for exactly this reason: bounded, offline
  coverage without the archive fetch or the 113x3
  execution cost on every PR. At the enforced SF=0.1 cell, 10 of the 13
  queries return all-NULL aggregates and therefore prove little (see
  `_project/analysis/cross-surface-mutation-sensitivity.md`); the gate's
  discriminating power comes from the queries that return real rows, plus
  the 34-query discriminating head of the extended 113-query surface with
  golden-entity seeding. Prefer a bounded cell that makes every query
  discriminating before describing this coverage as complete.

## Manual run path

The canonical suite remains runnable on demand; it is documented in
`docs/benchmarks/join-order.md`:

```text
uv run -- benchbox run --platform duckdb --benchmark joinorder --scale 1
```

Larger or repeated runs belong under `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs`
per the project UAT/stress-run convention, not in routine CI.

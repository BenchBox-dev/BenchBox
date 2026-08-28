# Seed Corpus Specification

**Created:** 2026-04-02
**Originating TODO:** `generate-seed-corpus-for-results-explorer`
**Related:** `docs/development/benchbox-results-platform-strategy.md`

This document belongs in `results-data/` because it describes the corpus contract and
the maintainer-run seed-generation workflow, not scratch analysis. Current checked-in
coverage lives in `results-data/README.md` and `results-data/CORPUS_NOTES.md`; this file
defines the workflow target and storage conventions.

## Purpose

The results explorer only becomes useful once a benchmark × scale cohort has enough
platform depth to support real comparison. The seed corpus is the maintainer-generated
baseline that provides that depth before Phase 2 community submissions or any future
Phase 3 hosted service.

The hard requirement today is still the validator gate in `results-data/validate_corpus.py`:
every committed cohort must have at least 3 platforms. Any workflow target that lands
below that threshold is provisional until a third platform exists or the validation policy
is intentionally changed.

## Generation Contract

| Item | Value |
|------|-------|
| Workflow | `.github/workflows/seed-corpus.yml` |
| Trigger | Manual `workflow_dispatch` only |
| Producer identity | `benchbox-bot` via GitHub Actions |
| Benchmark phases | `generate,load,power` |
| Trust label | `maintainer-run` |
| Visibility | `public-curated` |
| Optional entry | `clickhouse-cloud` at TPC-H SF 1.0, skipped when cloud secrets are absent |

There is no scheduled quarterly refresh in the current workflow. Refreshes are run on
demand by maintainers.

## Workflow Target Matrix

This is the matrix encoded in `.github/workflows/seed-corpus.yml`.

| Benchmark | Scale Factor | Platforms | Expected Bundles |
|-----------|--------------|-----------|------------------|
| TPC-H | 0.01 | duckdb, datafusion, polars-df | 3 |
| TPC-H | 0.1 | duckdb, datafusion, polars-df | 3 |
| TPC-H | 1.0 | duckdb, datafusion, clickhouse-cloud* | 2-3 |
| TPC-DS | 1 | duckdb, datafusion | 2 |
| SSB | 0.01 | duckdb, datafusion, polars-df | 3 |
| SSB | 0.1 | duckdb, datafusion, polars-df | 3 |

\* `clickhouse-cloud` is conditional on `CLICKHOUSE_CLOUD_HOST` and
`CLICKHOUSE_CLOUD_PASSWORD`.

## Merge Gate Caveats

Two important caveats apply to the target matrix above:

1. The current corpus validator fails any cohort with fewer than 3 platforms.
   That means the TPC-DS SF 1 target row is not merge-ready as-is, and the TPC-H
   SF 1.0 row also becomes non-mergeable if ClickHouse Cloud is unavailable.
2. The current checked-in corpus is smaller than the full workflow target. Do not
   read this spec as a statement that all target bundles already exist in `main`.

## Benchmark Notes

### TPC-DS scale factors

TPC-DS generation uses integer-only scale factors. The workflow therefore uses
SF 1 and does not attempt fractional scales such as 0.01 or 0.1.

### DataFrame coverage

The workflow includes `polars-df` for TPC-H and SSB. It intentionally does not
include `polars-df` for TPC-DS because BenchBox does not currently ship a TPC-DS
DataFrame adapter.

### Execution phases

All seed-corpus runs use `--phases generate,load,power`. Throughput and
maintenance are excluded to keep CI runtime bounded and to standardize the
comparison surface on single-stream power timings.

## Storage Layout

Both of the following layouts are valid because the explorer pipeline and validator
scan recursively under `results-data/bundles/`.

### Current checked-in layout

The current repository corpus is flat:

```text
results-data/
  bundles/
    tpch_sf001_duckdb_20260403_093653_9c0925d1.json
    tpch_sf01_polars_df_20260404_191727_mcp_b897c572.json
    ssb_sf01_duckdb_sql_20260404_191819_68f79876.json
```

### Seed-workflow staging layout

The seed-corpus workflow stages new PRs under benchmark/platform/scale directories:

```text
results-data/
  bundles/
    {benchmark}/
      {platform}/
        sf{scale_factor}/
          {run_id}.json
          {run_id}.plans.json
          {run_id}.tuning.json
```

Scale-factor directory naming follows the raw CLI `--scale` value:

- `0.01` -> `sf0.01`
- `0.1` -> `sf0.1`
- `1.0` -> `sf1.0`
- `1` -> `sf1`

## Trust and Attribution

All seed-corpus bundles are maintainer-generated and use:

| Field | Value |
|-------|-------|
| Trust label | `maintainer-run` |
| Visibility | `public-curated` |
| Attribution | BenchBox CI / `benchbox-bot` |

These labels are intentionally compatible with the broader results-platform strategy,
which later adds community-submission flows without changing the underlying result
bundle format.

# Public corpus refresh

The public corpus on `published-results` goes stale when nobody *submits*,
not when CI stops running. Nightly tests do not publish bundles. This page
is the publication calendar.

## Cadence

Monthly, on the 1st at 07:00 UTC, via `.github/workflows/seed-corpus.yml`
(`schedule` plus the existing `workflow_dispatch`). Each run opens a PR
against `develop`. Merging that PR triggers
`sync-results-data-to-published.yml`, which opens a draft mirror onto
`published-results` for a maintainer to accept.

Do not add a second nightly UAT gate for this. Generation already lives in
`seed-corpus.yml`; the schedule is what was missing.

## Recurring matrix

This is the `seed-corpus.yml` matrix. It is DuckDB / DataFusion / Polars
(and optional ClickHouse Cloud when secrets exist). Cloud warehouses
(Snowflake, Databricks, BigQuery) are not on this calendar until live
credentials are confirmed.

| Benchmark | Scales | Platforms | Notes |
| --- | --- | --- | --- |
| TPC-H | 0.01, 0.1, 1.0 | DuckDB, DataFusion, Polars-DF (SF 0.01/0.1); DuckDB, DataFusion, ClickHouse Cloud optional (SF 1.0) | Power phase only |
| TPC-DS | 1 | DuckDB, DataFusion | Integer SF only. Runs with `--official --seed 42` so submit/admission will not classify them unofficial |
| SSB | 0.01, 0.1 | DuckDB, DataFusion, Polars-DF | Power phase only |

TPC-H SF10 / SF100 and extra TPC-DS platforms stay operator-run (too large
for a GitHub-hosted monthly job). They still publish through
`benchbox submit` onto `published-results`, as in PR #1786.

## Operator trigger

```bash
gh workflow run seed-corpus.yml
# optional: -f benchmark=tpch
```

After the develop PR merges, confirm the mirror draft against
`published-results` and merge it. `corpus-drift-check.yml` remains the
loud canary if a push-triggered mirror is dropped.

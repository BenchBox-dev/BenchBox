# Regeneration Checklist - Tuned Cells Dropped 2026-07-16

**Related TODO:** `tuning-corpus-drop-pre-provenance-tuned-bundles-20260716`
**Decision:** Joe, 2026-07-16 (tuning follow-up batch gate)

## What happened

The 2026-07 tuning remediation (#1176 w0 discovery) proved the tuning config
never reached platform adapters on the direct CLI path, so every bundle in the
checked-in seed corpus claiming `execution.tuning_mode == "tuned"` was almost
certainly physically untuned. Cross-submission comparisons against those
bundles are unsound, so they were removed rather than relabeled.

325 bundles (plus their 325 `.manifest.json` sidecars, 650 files total) were
removed from `results-data/bundles/`. The 203 bundles with no `tuning_mode`
recorded were left untouched - they ingest honestly as "not recorded" and
were never a soundness problem.

After removal: `results-data/corpus-inventory.json` was regenerated
(`uv run -- python scripts/generate_corpus_inventory.py --write`) and every
remaining cohort still meets the >=3-platform depth gate in
`results-data/validate_corpus.py`.

## How to find the removed bundles

The exact file list is in the git history of the removal commit (see the
commit body on the `chore/tuning-corpus-drop` branch / PR). The sweep logic
lives in `_project/scripts/explorer_pipeline/transformer.py::_tuning_mode`,
which reads `config.tuning_mode` first and falls back to
`execution.tuning_mode` for seed-corpus-era bundles.

## Benchmarks with zero remaining coverage

Four benchmarks had no non-tuned bundles in the corpus at all, so removing
their tuned bundles drops them from the checked-in corpus entirely until
regenerated: **ai_primitives**, **joinorder_synthetic** (distinct from the
surviving `joinorder` IMDB benchmark, which keeps 3 not-recorded bundles),
**tpcds** (the standalone TPC-DS benchmark; `tpcds_obt` is unaffected and
still has not-recorded coverage), and **vector_search**. `results-data/corpus-inventory.json` will not list these
benchmark ids again until at least one tuned or not-recorded bundle is
re-added for each.

## Regeneration checklist

Once a platform's tuned path is verified to actually reach adapters
(post-#1176/#1180), the following benchmark x scale cells need fresh
maintainer runs with `--tuning-mode tuned` (or equivalent) to restore tuned
coverage. Platforms are listed as they appeared in the dropped bundles for
that cell; a regenerated cell does not need to reproduce every platform
below, but each dropped platform's tuned result is no longer represented
anywhere in the corpus until it is re-run.

| Benchmark | Scale Factor | Platforms Removed |
|-----------|--------------|--------------------|
| ai_primitives | 0.01 | Apache Doris, ClickHouse Local, DuckDB, Presto, SQLite, StarRocks |
| ai_primitives | 0.1 | ClickHouse Local, Presto, SQLite, StarRocks |
| ai_primitives | 1.0 | ClickHouse Local, StarRocks |
| amplab | 0.01 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PySpark, SQLite, Spark, StarRocks |
| amplab | 0.1 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PySpark, SQLite, Spark, StarRocks |
| amplab | 1.0 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PySpark, SQLite, Spark, StarRocks |
| clickbench | 1.0 | Apache Doris, ClickHouse Local, DataFusion, DuckDB, Spark, StarRocks |
| coffeeshop | 0.01 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, Spark, StarRocks |
| coffeeshop | 0.1 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, Spark, StarRocks |
| coffeeshop | 1.0 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, Spark, StarRocks |
| datavault | 0.01 | Apache Doris, ClickHouse Local, DuckDB, StarRocks |
| datavault | 0.1 | Apache Doris, ClickHouse Local, DuckDB, StarRocks |
| datavault | 1.0 | Apache Doris, ClickHouse Local, DuckDB, StarRocks |
| flightdata | 0.01 | Apache Doris, ClickHouse Local, DuckDB, Polars, StarRocks |
| flightdata | 0.1 | Apache Doris, ClickHouse Local, DuckDB, Polars, StarRocks |
| flightdata | 1.0 | ClickHouse Local |
| h2odb | 0.01 | ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, PySpark, Spark, StarRocks |
| h2odb | 0.1 | ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, PySpark, Spark, StarRocks |
| h2odb | 1.0 | ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, PySpark, Spark, StarRocks |
| joinorder_synthetic | 1.0 | ClickHouse Local, DuckDB, SQLite, Spark, StarRocks |
| metadata_primitives | 1.0 | DuckDB, Pandas, Polars, PySpark, StarRocks |
| nyctaxi | 0.01 | Dask, DuckDB, Pandas, Polars, PostgreSQL, PySpark, StarRocks |
| nyctaxi | 0.1 | Dask, DuckDB, Pandas, Polars, PostgreSQL, PySpark, StarRocks |
| nyctaxi | 1.0 | Dask, Pandas, Polars, PostgreSQL, PySpark, StarRocks |
| read_primitives | 0.01 | ClickHouse Local, DataFusion, DuckDB, Polars |
| read_primitives | 0.1 | ClickHouse Local, DataFusion, DuckDB |
| ssb | 0.01 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, PySpark, SQLite, Spark, StarRocks |
| ssb | 0.1 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, PySpark, SQLite, Spark, StarRocks |
| ssb | 1.0 | Apache Doris, ClickHouse Local, Dask, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, PySpark, SQLite, Spark, StarRocks |
| tpcdi | 0.01 | Apache Doris, DuckDB, StarRocks |
| tpcdi | 0.1 | Apache Doris, DuckDB, StarRocks |
| tpcdi | 1.0 | Apache Doris, DuckDB, StarRocks |
| tpcds | 0.01 | Polars |
| tpcds | 0.1 | Polars |
| tpcds | 1.0 | Polars |
| tpcds_obt | 1.0 | DuckDB, Pandas, Polars, PySpark |
| tpch | 0.01 | CedarDB, ClickHouse Local, Dask, DataFusion, DuckDB, Polars, PostgreSQL, Presto, PySpark, SQLite, Spark, StarRocks |
| tpch | 0.1 | CedarDB, ClickHouse Local, Dask, DataFusion, DuckDB, Polars, PySpark, Spark, StarRocks |
| tpch | 1.0 | CedarDB, ClickHouse Local, Dask, DataFusion, DuckDB, Polars, PySpark, Spark, StarRocks |
| tpch_skew | 0.01 | ClickHouse Local, DataFusion, DuckDB, Pandas, Polars, PostgreSQL, PySpark, SQLite, Spark, StarRocks |
| tpch_skew | 0.1 | ClickHouse Local, DataFusion, DuckDB, Pandas, Polars, PySpark, Spark, StarRocks |
| tpch_skew | 1.0 | ClickHouse Local, DataFusion, DuckDB, Pandas, Polars, PySpark, Spark, StarRocks |
| tsbs_devops | 0.01 | ClickHouse Local, Dask, DuckDB, Pandas, Polars, PostgreSQL, PySpark, StarRocks |
| tsbs_devops | 0.1 | ClickHouse Local, Dask, DuckDB, Pandas, Polars, PostgreSQL, PySpark, StarRocks |
| tsbs_devops | 1.0 | ClickHouse Local, Dask, DuckDB, Pandas, Polars, PostgreSQL, PySpark, StarRocks |
| vector_search | 0.01 | ClickHouse Local, DuckDB, StarRocks |
| vector_search | 0.1 | ClickHouse Local, DuckDB, StarRocks |
| vector_search | 1.0 | ClickHouse Local, DuckDB, StarRocks |

48 benchmark x scale cells, 325 removed platform-tuned bundles total (some
cells have more than one bundle per platform, e.g. DataFusion sql + df
variants both landed under `tuning_mode=tuned`).

## Regeneration steps

1. Confirm the platform's tuned path is fixed and covered by a soundness test
   (see #1176 / #1180 follow-up work).
2. Re-run: `benchbox run --platform <platform> --benchmark <benchmark> --scale <sf> --tuning-mode tuned --phases generate,load,power`
3. Package and add the bundle under `results-data/bundles/`.
4. Regenerate the inventory: `uv run -- python scripts/generate_corpus_inventory.py --write`
5. Re-run `uv run -- python results-data/validate_corpus.py` to confirm the
   cohort still meets the >=3-platform depth gate.

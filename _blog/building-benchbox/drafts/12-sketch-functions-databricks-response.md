---
title: "Two benchmarks for one announcement: covering Databricks' new sketch functions in BenchBox"
series: building-benchbox
post_number: 12
type: architecture-design
tags: [benchbox, sketches, datasketches, databricks, approximate-analytics, write-primitives, read-primitives, clickhouse, duckdb, redshift]
meta_description: "Why responding to Databricks' new sketch functions took two BenchBox benchmarks instead of one, and what cross-engine sketch coverage actually looks like."
status: draft
---

# Two benchmarks for one announcement: covering Databricks' new sketch functions in BenchBox

> Databricks shipped sketch functions for distinct counts, quantiles, top-K, and tuple summaries. BenchBox covers three of those families today; the important benchmarking question is not just "which function name maps where?" It is "can the benchmark exercise stored, mergeable, requeryable sketch artifacts?"

**TL;DR**: BenchBox added sketch coverage in two places. `read_primitives` now has five one-shot approximate aggregate queries for HLL distinct counts, KLL or T-Digest quantiles, vector quantiles, and top-K. `write_primitives` adds a sketch lifecycle category that persists, merges, and requeries Theta, KLL, and Top-K sketch state. Tuple sketches are acknowledged but deferred because they need their own cross-engine support design.

---

## Introduction

Databricks' April 29, 2026 sketch announcement was a useful forcing function for BenchBox.[^1] The post introduced four sketch families: KLL quantiles, Theta set sketches, approximate Top-K, and Tuple sketches. At first glance, a benchmark response looks mechanical:

1. Map each Databricks function to the closest Snowflake, BigQuery, DuckDB, ClickHouse, Redshift, and DataFusion function.
2. Add missing queries to the benchmark catalog.
3. Publish a support table.

That is the obvious response. It is also incomplete.

The announcement is not only about approximate aggregate functions. It is about sketches as durable artifacts. Build a sketch once during ETL. Store it as a column. Merge sketches across days, regions, campaigns, or partitions. Extract a value later without rescanning raw rows. Databricks' SQL docs make that shape explicit for Theta (`theta_sketch_agg`, `theta_union_agg`, `theta_sketch_estimate`), KLL (`kll_sketch_agg_double`, `kll_merge_agg_double`, `kll_sketch_get_quantile_double`), and Top-K (`approx_top_k_accumulate`, `approx_top_k_combine`, `approx_top_k_estimate`).[^2][^3][^4][^5][^6]

BenchBox already had a single-query read benchmark. That benchmark can measure aggregate latency. It cannot write sketch state, read it back later, merge it, and validate the extracted answer. That led to the design decision behind this post: one announcement needed two benchmarks.

## The Problem

`read_primitives` is intentionally simple. Each query runs in isolation against benchmark tables and reports latency for one read shape: a filter, a join, a group-by, a percentile, a top-N query. That is the right home for one-shot approximate aggregates:

| Query | Capability |
|-------|------------|
| `approx_count_distinct_simple` | HLL distinct count, single value |
| `approx_count_distinct_groupby` | HLL distinct count per group |
| `approx_quantile_groupby` | KLL or T-Digest style single quantile |
| `approx_quantiles_array` | Multiple quantiles from one aggregate |
| `approx_top_k_lineitem` | Approximate most-frequent values |

Those queries are useful. They answer "how fast is this engine's approximate aggregate surface compared with its exact aggregate surface?" That is still worth benchmarking.

But the sketch lifecycle is a different workload. It has at least three steps:

1. Build per-partition sketch state.
2. Persist that state in a table or file.
3. Merge stored state and extract a scalar or list later.

The second and third steps are the interesting part. They turn "approximate aggregate" from a function call into a data management pattern. A single-query catalog can produce numbers for step one. It cannot exercise the durable state loop.

This surfaced as a framework-gap finding in our own planning notes: function-parity evaluation under-weights claims that depend on the benchmark execution model. Mapping names is necessary, but it is not enough. We also have to ask whether the benchmark can express the capability under test.

## What We Tried

The first pass was the parity table. We mapped Databricks' sketch families against the other engines BenchBox targets:

| Engine | Distinct | Quantile | Top-K |
|--------|----------|----------|-------|
| DuckDB | `APPROX_COUNT_DISTINCT` | `APPROX_QUANTILE` | `APPROX_TOP_K` |
| Snowflake | `APPROX_COUNT_DISTINCT` | `APPROX_PERCENTILE` | `APPROX_TOP_K` |
| BigQuery | `APPROX_COUNT_DISTINCT` | `APPROX_QUANTILES` | `APPROX_TOP_COUNT` |
| Databricks | `approx_count_distinct` | `PERCENTILE_APPROX` | `approx_top_k` |
| ClickHouse | `uniq` | `quantileTDigest` | `topK` |
| Redshift | `APPROXIMATE COUNT(DISTINCT ...)` | `APPROXIMATE PERCENTILE_DISC` | no native top-K |
| DataFusion | `approx_distinct` | `approx_percentile_cont` | no native top-K |

That table belongs in `read_primitives`, and it now lives in the public approximate-functions doc.[^7] It keeps the aggregate-latency path visible.

Then we looked at persistence. Two implementation options were on the table:

| Option | Benefit | Weakness |
|--------|---------|----------|
| Add sketch-like queries only to `read_primitives` | Small change, easy to explain, broad engine coverage | Only measures one-shot aggregate latency |
| Add a `sketch` category to `write_primitives` | Exercises persist, merge, and requery | Requires platform-specific DDL, binary column handling, validation tolerances, and skip rationale |

We chose both. `read_primitives` owns the one-query surface. `write_primitives` owns the lifecycle.

That choice also forced architecture work we would not have seen from the parity table alone. `write_primitives` already had per-platform SQL overrides for the operation body, but validation SQL was still single-body. That breaks as soon as ClickHouse writes with `uniqState` while validation still calls a DuckDB-only `datasketch_*` function. We added `validation_query.platform_overrides` so each engine can validate with its own sketch syntax.

The DataFrame write path had a separate gap. Its operation enum modeled row-level work: insert, bulk-load, update, delete, merge, transaction. Sketch persistence is aggregate-state work, not row maintenance. We added `AGGREGATE_PERSIST` and `AGGREGATE_MERGE` as explicit operation shapes so DataFrame engines with sketch APIs can eventually report build latency, durable state size, and merge latency without pretending the workload is row CRUD.

That is the larger lesson from the attempt: the benchmark shape mattered as much as the function map.

## What We Built

The `write_primitives` sketch category models a full sketch lifecycle with eight operations:

| Operation | Stage | What it measures |
|-----------|-------|------------------|
| `sketch_ddl_create_persistent_table` | DDL | Creating a table with sketch-bearing columns |
| `sketch_insert_theta_per_partition` | INSERT | Building distinct-count sketches per partition |
| `sketch_insert_kll_per_partition` | INSERT | Building quantile sketches per partition |
| `sketch_insert_topk_per_shard` | INSERT | Building frequent-item sketches per shard |
| `sketch_query_theta_union_merge` | MERGE | Merging distinct-count sketches and extracting an estimate |
| `sketch_query_kll_quantiles_merge` | MERGE | Merging quantile sketches and extracting a median |
| `sketch_query_topk_combine` | MERGE | Merging frequent-item sketches and extracting top items |
| `sketch_drop_persistent_table` | DDL | Cleaning up the sketch table |

The catalog separates three kinds of support:

| Family | DataSketches-family or binary-oriented path | Native or substituted path | No-support cases |
|--------|---------------------------------------------|----------------------------|------------------|
| Theta distinct | Databricks, Snowflake, DuckDB extension | ClickHouse `uniqState` and `uniqMerge`; BigQuery and Redshift HLL substitution | DataFusion |
| KLL quantile | Databricks, Snowflake, BigQuery, DuckDB extension | ClickHouse `quantileTDigestState` and `quantileTDigestMerge` | Redshift, DataFusion |
| Top-K frequent items | Databricks, Snowflake, DuckDB extension | ClickHouse `topKState` and `topKMerge` | BigQuery, Redshift, DataFusion |

That table is deliberately not a scoreboard. It is a contract table. When BenchBox says Redshift is HLL-only here, the catalog emits HLL-specific DDL and HLL merge SQL for the distinct-count path, then skips KLL and Top-K with rationale. When BenchBox says ClickHouse is native-but-distinct, it means the persisted state shape matches the benchmark lifecycle, while the bytes are not portable to Apache DataSketches readers.

Validation has two layers for the headline merge operations.

The first layer is scalar bounds. Sketch outputs can vary across algorithms, parameters, and engines. Exact equality would be the wrong contract. Bounds are wide enough to avoid false failures on healthy sketches and tight enough to catch obvious regressions, such as returning zero or merging the wrong column.

The second layer is storage-size validation where the engine exposes a practical byte-length probe. A sketch benchmark that measures only latency misses half of the cost model. Persisted state size affects table storage, cache behavior, network movement, and merge throughput. The current catalog uses DuckDB and ClickHouse probes where verified, while cloud byte-length checks remain deferred until cloud credentials are available.

Tuple sketches stay out of this first lifecycle category. Databricks includes them in the announcement, and they are important because they combine distinct counting with associated metrics such as sums or mins and maxes.[^1] BenchBox defers them because the cross-engine story is different: Databricks and Snowflake have a natural path; BigQuery, Redshift, and ClickHouse do not map cleanly to the same family. Adding Tuple now would make the first lifecycle benchmark broader while making its support table less honest.

## What We Learned

The first lesson is that approximate analytics has two tiers.

The first tier is the one-shot aggregate path: "give me an approximate distinct count now." Most analytical engines have something here. Some use HLL, some use T-Digest, some use engine-specific Top-K accumulators, and some rely on SQL transpilation or hand-written variants. This is the path `read_primitives` measures.

The second tier is the persisted-state path: "build sketches over partitions, store them, merge them later, and extract answers cheaply." This is the path `write_primitives` measures. The engine matrix narrows at this tier, and the portability story becomes more specific. Some engines expose Apache DataSketches-family artifacts. Some expose native aggregate-state combinators. Some expose HLL only. Some do not expose a sketch lifecycle at all.

The second lesson is that verification language has to be precise. BenchBox can document catalog coverage across seven engines, but that is not the same as saying every engine has been verified live for every family. Local `read_primitives` paths are straightforward to exercise. chDB gives us a local ClickHouse-shaped path. DuckDB KLL works against the installed community extension, while DuckDB Theta and frequent-items are blocked by community-extension drift until we pin, vendor, or substitute the missing families. Snowflake, BigQuery, Databricks, and Redshift lifecycle runs remain credential-gated.

That last paragraph is less tidy than a support badge. It is also more useful.

The third lesson is that DataFrame support needs its own accounting. Polars, PySpark, DataFusion, pandas, Dask, Modin, and cuDF do not expose the same sketch surfaces. Some rows are sketch-backed. Some rows fall back to exact aggregates. The benchmark can still run and produce a number, but a pandas exact `nunique` timing is not semantically comparable to a PySpark HLL timing. The docs label those cases explicitly so charts can separate sketch-backed and exact-fallback results.

The final lesson is reusable beyond sketches. Any feature announced as "stored, mergeable, requeryable" needs an execution-model check before we start writing parity tables. Vector indexes, materialized aggregates, search indexes, incremental materialized views, and ML feature stores all have the same shape. The question is not only "what function name maps to what?" It is "does this benchmark have the phases needed to test the claim?"

## Try It Yourself

Run the one-shot approximate aggregate path first:

```bash
benchbox run --platform duckdb --benchmark read_primitives \
  --queries approx_count_distinct_simple,approx_count_distinct_groupby,approx_quantile_groupby,approx_quantiles_array,approx_top_k_lineitem \
  --scale 1 \
  --non-interactive
```

Then run the sketch lifecycle where your target engine supports it. The DuckDB Theta and Top-K paths currently need the community-extension drift resolved first, so KLL is the safer local DuckDB lifecycle smoke:

```bash
benchbox run --platform duckdb --benchmark write_primitives \
  --queries sketch_insert_kll_per_partition,sketch_query_kll_quantiles_merge \
  --scale 0.01 \
  --non-interactive
```

For DataFrame engines, run each platform separately and label sketch-backed versus exact-fallback results before comparing:

```bash
for platform in polars-df pyspark-df datafusion-df pandas-df dask-df; do
  benchbox run --platform "$platform" --benchmark read_primitives \
    --queries approx_count_distinct_simple,approx_count_distinct_groupby,approx_quantile_groupby \
    --scale 0.1 \
    --non-interactive
done
```

The public reference docs are the best place to start:

- [`read_primitives` approximate aggregate functions](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/read-primitives-approximate-functions.md)
- [`write_primitives` sketch persistence operations](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/write-primitives-sketch-functions.md)

## Test Environment

This draft is based on BenchBox branch `feat/write-primitives-sketch-parameter-sweeps` at commit `6e6893aa2`, with package version `0.2.1` in `pyproject.toml`.

Local verification available in this branch:

| Area | Status |
|------|--------|
| `read_primitives` approximate aggregate catalog | Implemented and documented |
| DataFrame approximate aggregate surface | Implemented with sketch-backed versus exact-fallback labels |
| `write_primitives` KLL Databricks SQL overrides | Uses typed Databricks SQL names verified against current docs |
| `validation_query.platform_overrides` | Implemented and covered by unit tests |
| `AGGREGATE_PERSIST` / `AGGREGATE_MERGE` DataFrame operation shapes | Implemented and covered by unit tests |
| DuckDB Theta and Top-K lifecycle runs | Blocked by current DuckDB community datasketches extension drift |
| Cloud lifecycle runs | Deferred until Snowflake, BigQuery, Databricks, and Redshift credentials are available |

## Limitations

This post is about benchmark design and catalog coverage. It does not measure approximation error. A separate benchmark would need paired exact and approximate outputs, relative-error reporting, and workload-specific tolerance choices.

This post also does not claim cross-engine binary sketch portability. Persisting a sketch in one engine and reading it in another needs two-engine orchestration and byte-level compatibility checks. BenchBox does not have that workflow today.

Finally, the support matrix separates catalog support from live verification. That distinction is intentional. It keeps the current draft honest while leaving room for cloud verification and DuckDB extension pinning work to fill in more of the matrix later.

## References

[^1]: Daniel Tenedorio, Kent Marten, Gengliang Wang, and Chenhao Li, ["Approximate Answers, Exact Decisions: New Sketch Functions for Analytics"](https://www.databricks.com/blog/approximate-answers-exact-decisions-new-sketch-functions-analytics), Databricks Blog, April 29, 2026.

[^2]: Databricks, [`theta_sketch_agg` aggregate function](https://docs.databricks.com/aws/en/sql/language-manual/functions/theta_sketch_agg), [`theta_union_agg` aggregate function](https://docs.databricks.com/aws/en/sql/language-manual/functions/theta_union_agg), and [`theta_sketch_estimate` function](https://docs.databricks.com/aws/en/sql/language-manual/functions/theta_sketch_estimate), accessed May 4, 2026.

[^3]: Databricks, [`kll_sketch_agg_double` aggregate function](https://docs.databricks.com/aws/en/sql/language-manual/functions/kll_sketch_agg_double), accessed May 4, 2026.

[^4]: Databricks, [`kll_merge_agg_double` aggregate function](https://docs.databricks.com/aws/en/sql/language-manual/functions/kll_merge_agg_double), accessed May 4, 2026.

[^5]: Databricks, [`kll_sketch_get_quantile_double` function](https://docs.databricks.com/aws/en/sql/language-manual/functions/kll_sketch_get_quantile_double), accessed May 4, 2026.

[^6]: Databricks, [`approx_top_k_accumulate` aggregate function](https://docs.databricks.com/aws/en/sql/language-manual/functions/approx_top_k_accumulate), [`approx_top_k_combine` aggregate function](https://docs.databricks.com/gcp/en/sql/language-manual/functions/approx_top_k_combine), and [`approx_top_k_estimate` function](https://docs.databricks.com/aws/en/sql/language-manual/functions/approx_top_k_estimate), accessed May 4, 2026.

[^7]: BenchBox, [`read_primitives` approximate aggregate functions](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/read-primitives-approximate-functions.md), accessed May 4, 2026.

[^8]: BenchBox, [`write_primitives` sketch persistence operations](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/write-primitives-sketch-functions.md), accessed May 4, 2026.

*Questions or feedback? [Open an issue](https://github.com/joeharris76/BenchBox/issues) or join the discussion.*

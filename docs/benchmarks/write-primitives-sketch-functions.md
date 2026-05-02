# Write Primitives — Sketch Persistence Operations

`write_primitives` exercises the **persist + merge + requery** lifecycle
for Apache DataSketches sketch artifacts. This is the differentiated
half of the modern approximate-analytics story — vendors compete on
millisecond-merge across partitioned sketch columns, not on one-shot
aggregate latency.

For the **one-shot** approximate-aggregate path (HLL distinct, T-Digest /
KLL single quantile, top-K), see
[read_primitives approximate-aggregate functions](read-primitives-approximate-functions.md).

## Operation lifecycle

Each sketch op is fully self-contained — CREATE the persistent table,
populate sketches per partition, run the merge query, DROP. No
cross-op dependencies. Sketch tables live outside `STAGING_TABLES` so
that BINARY-column DDL stays out of the bootstrap loop on dialects
without a binary type (DataFusion, SQLite).

| Op ID                                     | Stage   | Notes                                          |
|-------------------------------------------|---------|------------------------------------------------|
| `sketch_ddl_create_persistent_table`      | DDL     | CREATE/DROP overhead with BINARY columns       |
| `sketch_insert_theta_per_partition`       | INSERT  | Build Theta sketches per (date, region)        |
| `sketch_insert_kll_per_partition`         | INSERT  | Build KLL price sketches per (date, region)    |
| `sketch_insert_topk_per_shard`            | INSERT  | Build frequent-items sketches per shard        |
| ★ `sketch_query_theta_union_merge`        | MERGE   | HEADLINE — distinct-count from merged thetas   |
| ★ `sketch_query_kll_quantiles_merge`      | MERGE   | HEADLINE — median from merged KLLs             |
| ★ `sketch_query_topk_combine`             | MERGE   | HEADLINE — frequent-items count from merge     |
| `sketch_drop_persistent_table`            | DDL     | DROP overhead for sketch-bearing table         |

The three ★ headline tests validate the "millisecond-merge" claim.
Their validation contracts use `expected_value_min/max` (tolerance-
based) because sketch outputs are non-deterministic across engines and
runs. Cross-reference their latency to the matching `read_primitives`
exact-counterpart queries:

| Headline op                       | Exact counterpart in read_primitives |
|-----------------------------------|---------------------------------------|
| `sketch_query_theta_union_merge`  | `aggregation_distinct`                |
| `sketch_query_kll_quantiles_merge`| `statistical_percentiles`             |
| `sketch_query_topk_combine`       | `approx_top_k_lineitem`               |

## Sketch family × engine support matrix

| Sketch family   | DataSketches binary-portable engines                | Native-but-distinct engines                    | No support           |
|-----------------|------------------------------------------------------|-----------------------------------------------|----------------------|
| Theta (distinct)| Databricks, Snowflake, BigQuery (HLL), DuckDB ext   | ClickHouse (`-State`/`-Merge` combinators)    | DataFusion           |
| KLL (quantile)  | Databricks, Snowflake, BigQuery, DuckDB ext         | ClickHouse (`quantileTDigestState`)           | Redshift, DataFusion |
| Top-K (frequent)| Databricks, Snowflake, DuckDB ext                    | ClickHouse (`topKState`), Redshift (HLL only) | BigQuery, DataFusion |

DataSketches binary format is portable across Databricks / Snowflake /
BigQuery / DuckDB-with-extension (all built on the same C++/Java/WASM
DataSketches core). ClickHouse uses its own `-State`/`-Merge` combinator
serialization, which is comparable algorithmically but **not**
binary-compatible. ClickHouse-native variants are deferred to a follow-up
to keep this benchmark scoped to the cross-engine portability story.

Redshift's `HLLSKETCH` covers only the HLL family; KLL and Top-K skip
on Redshift.

## Per-engine column type for sketch storage

| Engine     | Logical type | DDL emitted by `translate_column_type`         |
|------------|--------------|------------------------------------------------|
| Databricks | `BINARY`     | `BINARY`                                       |
| Snowflake  | `BINARY`     | `BINARY`                                       |
| BigQuery   | `BINARY`     | `BYTES`                                        |
| DuckDB     | `BINARY`     | `BLOB` (round-trip cast back to `sketch_kll_*` for KLL merge) |
| ClickHouse | `BINARY`     | `String` (or `AggregateFunction(...)` natively)|
| Redshift   | `BINARY`     | `HLLSKETCH` (HLL only)                         |
| DataFusion | `BINARY`     | — (skipped)                                    |
| SQLite     | `BINARY`     | — (skipped)                                    |

The `translate_column_type` helper in
`benchbox/core/write_primitives/schema.py` rewrites the logical
`BINARY` type per dialect. Tables that declare `BINARY` columns must be
filtered out of `STAGING_TABLES` for unsupported dialects — the sketch
ops do this implicitly by managing their own DDL inside `write_sql`.

## Per-engine function-name reference

### Theta (distinct count)

| Engine     | Build (aggregate)                       | Merge (aggregate)                         | Estimate (scalar)                        |
|------------|------------------------------------------|--------------------------------------------|------------------------------------------|
| Databricks | `theta_sketch_agg(x)`                   | `theta_union_agg(sketch)`                  | `theta_sketch_estimate(sketch)`          |
| Snowflake  | `DATASKETCHES_THETA_ACCUMULATE(x)`      | `DATASKETCHES_THETA_COMBINE(sketch)`       | `DATASKETCHES_THETA_ESTIMATE(sketch)`    |
| BigQuery   | `HLL_COUNT.INIT(x)` (HLL, not Theta)    | `HLL_COUNT.MERGE(sketch)`                  | (merge returns count directly)           |
| DuckDB ext | `datasketch_theta(x)`                   | `datasketch_theta(sketch)`                 | `datasketch_theta_estimate(sketch)`      |

### KLL (quantile)

| Engine     | Build                                    | Merge                                       | Extract median                                    |
|------------|------------------------------------------|---------------------------------------------|---------------------------------------------------|
| Databricks | `kll_sketch_agg(x)`                     | `kll_sketch_agg(sketch)`                    | `kll_sketch_estimate_quantile(sketch, 0.5)`       |
| Snowflake  | `DATASKETCHES_KLL_ACCUMULATE(x)`        | `DATASKETCHES_KLL_COMBINE(sketch)`          | `DATASKETCHES_KLL_GET_QUANTILE(sketch, 0.5)`      |
| BigQuery   | `KLL_QUANTILES.INIT_INT64(x)`           | (merge implicit in extract)                 | `KLL_QUANTILES.MERGE_POINT_INT64(sketch, 0.5)`    |
| DuckDB ext | `datasketch_kll(200, x)`                | `datasketch_kll(200, sketch::sketch_kll_double)` | `datasketch_kll_quantile(sketch, 0.5::DOUBLE, true)` |

### Top-K (frequent items)

| Engine     | Build                                                 | Merge                                          | Extract                                                      |
|------------|--------------------------------------------------------|------------------------------------------------|--------------------------------------------------------------|
| Databricks | `approx_top_k_accumulate(x)`                          | `approx_top_k_combine(sketch)`                 | `approx_top_k_estimate(sketch)` → `ARRAY<STRUCT<item, count>>` |
| Snowflake  | `APPROX_TOP_K_ACCUMULATE(x, k)`                       | `APPROX_TOP_K_COMBINE(sketch)`                 | `APPROX_TOP_K_ESTIMATE(sketch)` → `ARRAY`                    |
| BigQuery   | — (no native top-K accumulator; skipped)              | —                                              | —                                                            |
| DuckDB ext | `datasketch_frequent_items(8, x)`                     | `datasketch_frequent_items(8, sketch)`         | `datasketch_frequent_items_get_frequent(sketch, 'NO_FALSE_POSITIVES')` |

## Validation tolerance methodology

Each ★ headline op declares `expected_value_min/max` bounds tuned
empirically against DuckDB SF=0.01:

| Op                                | Observation                              | Bounds            | Rationale                                       |
|-----------------------------------|------------------------------------------|-------------------|--------------------------------------------------|
| `sketch_query_theta_union_merge`  | 14836.89 (deterministic over 5 runs)     | [14000, 16000]    | True distinct = 15000; ~1% theta error         |
| `sketch_query_kll_quantiles_merge`| 34027.29 – 34361.75 (5 runs)             | [30000, 40000]    | Generous to tolerate SF=0.1 drift; catches no-op |
| `sketch_query_topk_combine`       | 7 (deterministic; lineitem has 7 modes)  | [6, 8]            | Lower bound catches loss; upper catches false-positive |

Bounds are intentionally wide enough to never false-fail on a healthy
sketch but tight enough to catch a regression to a no-op (sketch
returning 0) or a wildly off estimate. Cloud engines may shift the
ranges; tolerances will need re-tuning when first-class cloud coverage
lands.

## Single-query scope: what this benchmark is **not**

This benchmark measures **latency under approximate semantics**, not
**approximation error magnitude**. Users who want to evaluate
approximation-quality tradeoffs (paired exact/approximate queries with
relative-error metrics) will need a separate benchmark — that's
deliberately deferred (see TODO `deferred:` block).

Cross-engine sketch portability tests (write a sketch on engine A,
query it on engine B) are also deferred — this needs two-engine
orchestration that BenchBox does not have today.

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

| Headline op                       | Exact counterpart in read_primitives | Engine coverage notes                                                            |
|-----------------------------------|---------------------------------------|----------------------------------------------------------------------------------|
| `sketch_query_theta_union_merge`  | `aggregation_distinct`                | DataSketches Theta on DuckDB / Databricks / Snowflake; HLL substitution on BigQuery and Redshift |
| `sketch_query_kll_quantiles_merge`| `statistical_percentiles`             | DataSketches KLL on DuckDB / Databricks / Snowflake / BigQuery; skipped on Redshift (no equivalent) |
| `sketch_query_topk_combine`       | `approx_top_k_lineitem`               | Frequent-items on DuckDB / Databricks / Snowflake; skipped on BigQuery and Redshift |

## Sketch family × engine support matrix

| Sketch family   | DataSketches binary-portable engines                | Native-but-distinct engines                                       | No support              |
|-----------------|------------------------------------------------------|--------------------------------------------------------------------|-------------------------|
| Theta (distinct)| Databricks, Snowflake, BigQuery (HLL), DuckDB ext   | ClickHouse (`-State`/`-Merge` combinators), Redshift (HLL substitution) | DataFusion         |
| KLL (quantile)  | Databricks, Snowflake, BigQuery, DuckDB ext         | ClickHouse (`quantileTDigestState`)                                | Redshift, DataFusion    |
| Top-K (frequent)| Databricks, Snowflake, DuckDB ext                    | ClickHouse (`topKState`)                                           | Redshift, BigQuery, DataFusion |

DataSketches binary format is portable across Databricks / Snowflake /
BigQuery / DuckDB-with-extension (all built on the same C++/Java/WASM
DataSketches core). ClickHouse uses its own `-State`/`-Merge` combinator
serialization, which is comparable algorithmically but **not**
binary-compatible. ClickHouse-native variants are deferred to a follow-up
to keep this benchmark scoped to the cross-engine portability story.

### Redshift HLL-only ceiling

Redshift's approximate-aggregate surface is fundamentally HLL-only —
no Theta, no KLL, no T-Digest, no Top-K. The only sketch type the
catalog persists on Redshift is `HLLSKETCH`. Coverage rolls up to:

- `sketch_ddl_create_persistent_table` — runs (HLLSKETCH-typed table).
- `sketch_insert_theta_per_partition` — runs as **HLL substitution**:
  `HLL_CREATE_SKETCH` per partition, persisted in HLLSKETCH columns.
  The op ID retains "theta" to keep cross-engine measurement keys
  comparable; the per-engine substitution is documented inline.
- `sketch_query_theta_union_merge` — runs as **HLL substitution**:
  `HLL_CARDINALITY(HLL_COMBINE(...))` for the merge+requery cycle.
- `sketch_drop_persistent_table` — runs (HLLSKETCH-typed DROP).
- KLL ops (`sketch_insert_kll_per_partition`,
  `sketch_query_kll_quantiles_merge`) — **skipped**; no Redshift
  equivalent.
- Top-K ops (`sketch_insert_topk_per_shard`,
  `sketch_query_topk_combine`) — **skipped**; no Redshift equivalent.

`HLLSKETCH`-typed columns carry non-trivial DDL/query restrictions:
cannot be `DISTKEY` / `SORTKEY`, cannot appear in `GROUP BY` /
`ORDER BY` / `DISTINCT`, fixed default `logm=15`, not supported in
Spectrum or Python UDFs, JDBC/ODBC drivers return them as VARCHAR
JSON/Base64. Each Redshift override emits its DDL inline with
`DISTSTYLE EVEN` to honor these restrictions, rather than activating the generic
`_BINARY_TYPE_BY_DIALECT[redshift] = HLLSKETCH` translator (the
abstraction can't express the constraints safely; per-op explicit DDL
is the chosen pattern).

UDF emulation of the missing families would measure UDF dispatch
overhead, not sketch performance, so KLL / Top-K stay skipped on
Redshift with explicit rationale comments.

## Per-engine column type for sketch storage

| Engine     | Logical type | DDL emitted by `translate_column_type`         |
|------------|--------------|------------------------------------------------|
| Databricks | `BINARY`     | `BINARY`                                       |
| Snowflake  | `BINARY`     | `BINARY`                                       |
| BigQuery   | `BINARY`     | `BYTES`                                        |
| DuckDB     | `BINARY`     | `BLOB` (round-trip cast back to `sketch_kll_*` for KLL merge) |
| ClickHouse | `BINARY`     | `String` (or `AggregateFunction(...)` natively)|
| Redshift   | `BINARY`     | `HLLSKETCH` (HLL only; per-op DDL emits inline with `DISTSTYLE EVEN`) |
| DataFusion | `BINARY`     | — (skipped)                                    |
| SQLite     | `BINARY`     | — (skipped)                                    |

The `translate_column_type` helper in
`benchbox/core/write_primitives/schema.py` rewrites the logical
`BINARY` type per dialect. Tables that declare `BINARY` columns must be
filtered out of `STAGING_TABLES` for unsupported dialects — the sketch
ops do this implicitly by managing their own DDL inside `write_sql`.
On Redshift, the `_BINARY_TYPE_BY_DIALECT` translator stays in place as
documentation but is not activated by any op — `HLLSKETCH` semantics
(no `DISTKEY` / `SORTKEY` / `GROUP BY`) don't fit the generic abstraction
safely, so each Redshift override emits its DDL inline.

## Per-engine function-name reference

### Theta (distinct count)

| Engine     | Build (aggregate)                       | Merge (aggregate)                         | Estimate (scalar)                        |
|------------|------------------------------------------|--------------------------------------------|------------------------------------------|
| Databricks | `theta_sketch_agg(x)`                   | `theta_union_agg(sketch)`                  | `theta_sketch_estimate(sketch)`          |
| Snowflake  | `DATASKETCHES_THETA_ACCUMULATE(x)`      | `DATASKETCHES_THETA_COMBINE(sketch)`       | `DATASKETCHES_THETA_ESTIMATE(sketch)`    |
| BigQuery   | `HLL_COUNT.INIT(x)` (HLL, not Theta)    | `HLL_COUNT.MERGE(sketch)`                  | (merge returns count directly)           |
| Redshift   | `HLL_CREATE_SKETCH(x)` (HLL, not Theta) | `HLL_COMBINE(sketch)`                      | `HLL_CARDINALITY(sketch)`                |
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
| `sketch_query_theta_union_merge`  | 14836.89 (deterministic over 5 runs)     | [14500, 15500]    | True distinct = 15000; tightened after HLL logm=15 review |
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

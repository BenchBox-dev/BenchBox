# Read Primitives — Approximate Aggregate Functions

`read_primitives` exercises one-shot approximate aggregates that every
modern OLAP engine exposes. These queries measure latency on the
approximate path, not approximation error. Sketch persistence and merge
across queries are intentionally **out of scope** for `read_primitives`
— that capability is covered by the `sketch` category of
[`write_primitives`](write-primitives-sketch-functions.md).

## Query coverage

| Query ID                          | Capability                       | Category   |
|-----------------------------------|----------------------------------|------------|
| `approx_count_distinct_simple`    | HLL distinct count, single value | aggregation|
| `approx_count_distinct_groupby`   | HLL distinct count, per group    | aggregation|
| `approx_quantile_groupby`         | T-Digest / KLL single quantile   | statistical|
| `approx_quantiles_array`          | Vector quantiles per group       | statistical|
| `approx_top_k_lineitem`           | Approximate top-K                | topn       |

`approx_quantile_groupby` is the renamed successor of the historical
`intrinsic_appx_median` query, which used exact `PERCENTILE_CONT`
despite the "appx" name.

## Cross-engine function reference

The base SQL uses DuckDB-style names (`APPROX_COUNT_DISTINCT`,
`APPROX_QUANTILE`, `APPROX_TOP_K`). sqlglot rewrites these for most
target dialects automatically; explicit YAML variants exist only where
sqlglot leaves the SQL non-functional.

### Distinct count

| Engine     | Syntax                                       | Source            |
|------------|----------------------------------------------|-------------------|
| DuckDB     | `APPROX_COUNT_DISTINCT(x)`                   | base              |
| Snowflake  | `APPROX_COUNT_DISTINCT(x)`                   | sqlglot rewrite   |
| BigQuery   | `APPROX_COUNT_DISTINCT(x)`                   | sqlglot rewrite   |
| Databricks | `approx_count_distinct(x)`                   | sqlglot rewrite   |
| ClickHouse | `uniq(x)`                                    | sqlglot rewrite   |
| Redshift   | `APPROXIMATE COUNT(DISTINCT x)`              | sqlglot rewrite   |
| DataFusion | `approx_distinct(x)`                         | sqlglot rewrite   |

### Single quantile

| Engine     | Syntax                                                       | Source           |
|------------|--------------------------------------------------------------|------------------|
| DuckDB     | `APPROX_QUANTILE(x, 0.5)`                                    | base             |
| Snowflake  | `APPROX_PERCENTILE(x, 0.5)`                                  | sqlglot rewrite  |
| BigQuery   | `APPROX_QUANTILES(x, 100)[OFFSET(50)]`                       | YAML variant     |
| Databricks | `PERCENTILE_APPROX(x, 0.5)`                                  | sqlglot rewrite  |
| ClickHouse | `quantileTDigest(0.5)(x)`                                    | YAML variant     |
| DataFusion | `approx_percentile_cont(x, 0.5)`                             | YAML variant     |
| Redshift   | `APPROXIMATE PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY x)` | YAML variant     |

Redshift's `APPROXIMATE PERCENTILE_DISC` syntax is rejected by
sqlglot's redshift parser, so the variant is hand-written rather than
sqlglot-rewritten and the static linter has an explicit allowlist for
its `variant_parse_error`. Runtime execution sends the SQL as-is to
the Redshift adapter, so the parse-time gap doesn't block actual runs.
Note: the per-node GROUP BY result-set cap applies; for grouping
columns with cardinality near or above the cap, fall back to exact
`PERCENTILE_CONT`.

### Vector quantiles (one sketch eval per group)

| Engine     | Syntax                                                                                                  | Source           |
|------------|---------------------------------------------------------------------------------------------------------|------------------|
| DuckDB     | `APPROX_QUANTILE(x, [0.25, 0.5, 0.75, 0.95])` → `ARRAY`                                                 | base             |
| BigQuery   | `[APPROX_QUANTILES(x, 100)[OFFSET(25)], …]` (per-quantile slice)                                        | YAML variant     |
| ClickHouse | `quantilesTDigest(0.25, 0.5, 0.75, 0.95)(x)`                                                            | YAML variant     |
| Snowflake  | `ARRAY_CONSTRUCT(APPROX_PERCENTILE(x, 0.25), …)` (no array form)                                        | YAML variant     |
| Databricks | `PERCENTILE_APPROX(x, ARRAY(0.25, 0.5, 0.75, 0.95))`                                                    | sqlglot rewrite  |
| Redshift   | —                                                                                                       | (skipped)        |
| DataFusion | —                                                                                                       | (skipped)        |

### Top-K

| Engine     | Syntax                              | Returns                       | Source           |
|------------|-------------------------------------|-------------------------------|------------------|
| DuckDB     | `APPROX_TOP_K(x, 5)`                | `ARRAY<value>`                | base             |
| Snowflake  | `APPROX_TOP_K(x, 5)`                | `ARRAY<pair>`                 | sqlglot rewrite  |
| BigQuery   | `APPROX_TOP_COUNT(x, 5)`            | `ARRAY<STRUCT<value, count>>` | sqlglot rewrite  |
| Databricks | `approx_top_k(x, 5)`                | `ARRAY<STRUCT<item, count>>`  | sqlglot rewrite  |
| ClickHouse | `topK(5)(x)`                        | `ARRAY<value>`                | YAML variant     |
| Redshift   | —                                   | —                             | (skipped)        |
| DataFusion | —                                   | —                             | (skipped)        |

Top-K result shapes diverge: DuckDB / ClickHouse return an array of
values; BigQuery, Snowflake, and Databricks return arrays of
value+count pairs. The catalog's `result_contract.capability` is set
to `approximate_top_k` so the cross-dialect comparator skips strict
value equality and validates capability + array `type_class` instead.

## DataFrame platform coverage

Three of the five approximate-aggregate queries run on the BenchBox
DataFrame surface. The other two are PySpark-only at the DataFrame
layer and stay in `SKIP_FOR_DATAFRAME`.

| Query                            | Polars                       | PySpark                                   | DataFusion                                  | Pandas / Modin / cuDF | Dask |
|----------------------------------|------------------------------|--------------------------------------------|---------------------------------------------|-----------------------|------|
| `approx_count_distinct_simple`   | `approx_n_unique` (HLL)      | `approx_count_distinct` (HLL)             | `approx_distinct` (HLL)                     | `nunique` (exact)     | `nunique_approx` (HLL) |
| `approx_count_distinct_groupby`  | `approx_n_unique` (HLL)      | `approx_count_distinct` (HLL)             | `approx_distinct` (HLL)                     | `nunique` (exact)     | `nunique` (exact; no groupby HLL API in dask-expr) |
| `approx_quantile_groupby`        | `quantile(0.5)` (exact)      | `percentile_approx(col, 0.5)` (KLL-equiv) | `approx_percentile_cont(col, 0.5)` (T-Digest) | `median` (exact)    | `median` (exact; no groupby T-Digest API in dask-expr) |
| `approx_quantiles_array`         | — (in `SKIP_FOR_DATAFRAME`)  | — (in `SKIP_FOR_DATAFRAME`)               | —                                           | —                     | — |
| `approx_top_k_lineitem`          | — (in `SKIP_FOR_DATAFRAME`)  | — (in `SKIP_FOR_DATAFRAME`)               | —                                           | —                     | — |

### Sketch vs exact-fallback interpretation

When a row above says **(exact)**, the underlying engine has no
sketch-backed surface for that aggregate at the DataFrame layer. The
benchmark still runs and reports a number, but that number is the
*exact* aggregate's latency — it is not directly comparable to the
sketch-backed engines on the same row, because exact aggregates pay
cardinality-proportional cost while sketches pay roughly constant
cost. Cross-engine comparisons in this category are most informative
within the sketch-backed column group.

Pandas / Modin / cuDF have no native sketch surface at all. Dask exposes
Series-level `nunique_approx()` (HLL), which BenchBox uses for the
single-value distinct query. Current dask-expr does not expose matching
groupby HLL or groupby T-Digest APIs; those groupby queries remain exact
fallbacks rather than hand-rolled approximations.

### Why two queries stay PySpark-only

- `approx_quantiles_array` — only PySpark's
  `percentile_approx(col, array(...))` returns an array of quantiles
  from a single sketch evaluation. Polars and DataFusion expose only
  single-quantile aggregates; Dask has no grouped array-quantile sketch
  shape in dask-expr. Emulating the array form via a per-quantile loop
  on those engines defeats the latency measurement that the benchmark
  is supposed to report.
- `approx_top_k_lineitem` — only PySpark 4.1+ ships a native
  `approx_top_k` accumulator. Polars' `top_k` is largest-by-sort-key
  (different semantics — not frequency-based). A real top-K port for
  the other DataFrame engines would land via the `write_primitives`
  PySpark DataFrame surface follow-up
  (`write-primitives-sketch-pyspark-dataframe-surface`) and could
  motivate dropping the SKIP_FOR_DATAFRAME entries here once the
  upstream engines ship equivalents.

## Single-query scope

These queries exercise only the **aggregate latency** path — i.e., the
boring half of the modern approximate-analytics announcement. They run
in isolation against TPC-H tables with no shared state.

The differentiated capability — building sketches in one query,
persisting them as binary columns, then merging them in a later
query — does **not** fit `read_primitives`' single-query execution
model. That capability is exercised by the `sketch` category of
[`write_primitives`](write-primitives-sketch-functions.md), which
shares this doc's cross-engine reference for the underlying
sketch-family function names.

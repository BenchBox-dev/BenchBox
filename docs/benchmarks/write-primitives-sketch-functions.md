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
| ClickHouse | `uniqState(x)` (HLL++, not Theta)       | (merge implicit in `uniqMerge`)            | `uniqMerge(sketch)`                      |
| DuckDB ext | `datasketch_theta(x)`                   | `datasketch_theta(sketch)`                 | `datasketch_theta_estimate(sketch)`      |

### KLL (quantile)

| Engine     | Build                                    | Merge                                       | Extract median                                    |
|------------|------------------------------------------|---------------------------------------------|---------------------------------------------------|
| Databricks | `kll_sketch_agg_double(CAST(x AS DOUBLE))` | `kll_merge_agg_double(sketch)`           | `kll_sketch_get_quantile_double(sketch, 0.5)`     |
| Snowflake  | `DATASKETCHES_KLL_ACCUMULATE(x)`        | `DATASKETCHES_KLL_COMBINE(sketch)`          | `DATASKETCHES_KLL_GET_QUANTILE(sketch, 0.5)`      |
| BigQuery   | `KLL_QUANTILES.INIT_INT64(x)`           | (merge implicit in extract)                 | `KLL_QUANTILES.MERGE_POINT_INT64(sketch, 0.5)`    |
| ClickHouse | `quantileTDigestState(0.5)(x)` (T-Digest, not KLL) | (merge implicit in `quantileTDigestMerge`) | `quantileTDigestMerge(0.5)(sketch)` |
| DuckDB ext | `datasketch_kll(200, x)`                | `datasketch_kll(200, sketch::sketch_kll_double)` | `datasketch_kll_quantile(sketch, 0.5::DOUBLE, true)` |

### Top-K (frequent items)

| Engine     | Build                                                 | Merge                                          | Extract                                                      |
|------------|--------------------------------------------------------|------------------------------------------------|--------------------------------------------------------------|
| Databricks | `approx_top_k_accumulate(x)`                          | `approx_top_k_combine(sketch)`                 | `approx_top_k_estimate(sketch)` → `ARRAY<STRUCT<item, count>>` |
| Snowflake  | `APPROX_TOP_K_ACCUMULATE(x, k)`                       | `APPROX_TOP_K_COMBINE(sketch)`                 | `APPROX_TOP_K_ESTIMATE(sketch)` → `ARRAY`                    |
| BigQuery   | — (no native top-K accumulator; skipped)              | —                                              | —                                                            |
| ClickHouse | `topKState(8)(x)`                                     | (merge implicit in `topKMerge`)                | `topKMerge(8)(sketch)` → `Array(String)`                     |
| DuckDB ext | `datasketch_frequent_items(8, x)`                     | `datasketch_frequent_items(8, sketch)`         | `datasketch_frequent_items_get_frequent(sketch, 'NO_FALSE_POSITIVES')` |

### CPC (compressed probabilistic counting — alternative HLL family)

DuckDB-only. CPC trades update/merge throughput for dramatically smaller
serialized state size — the headline "smaller-than-Theta" sketch. Apache
DataSketches calls this Compressed Probabilistic Counting.

| Engine     | Build                            | Merge (aggregate)                                  | Estimate (scalar)                       |
|------------|----------------------------------|----------------------------------------------------|------------------------------------------|
| DuckDB ext | `datasketch_cpc(lg_k, x)`        | `datasketch_cpc_union(lg_k, sketch::sketch_cpc)`   | `datasketch_cpc_estimate(sketch)`        |
| All others | — (no native CPC surface today)  | —                                                  | —                                        |

### REQ (relative-error quantile — alternative quantile family)

DuckDB-only. REQ provides relative-error guarantees (vs KLL's
normalized-rank error) — useful when caller cares about the percentile's
accuracy relative to the quantile value rather than its rank position.

| Engine     | Build                                    | Merge (aggregate)                                            | Extract median                                                          |
|------------|------------------------------------------|--------------------------------------------------------------|--------------------------------------------------------------------------|
| DuckDB ext | `datasketch_req(k, x)`                   | `datasketch_req(k, sketch::sketch_req_float)` (fold-merge)   | `datasketch_req_quantile(sketch, 0.5::DOUBLE, true)`                    |
| All others | — (no native REQ surface today)          | —                                                            | —                                                                        |

#### Per-family persistence tables for CPC and REQ

CPC and REQ each persist into their own table (`sketch_cpc_partitions`,
`sketch_req_partitions`) rather than sharing a mega-sketch table with
the Theta/KLL/Top-K families. The reasoning: each family carries a
different storage column type and parameter knob (CPC's `lg_k` vs
Theta's `lg_k` vs KLL's `k` vs frequent-items' `lg_max_map_size`), and
the cast pattern at merge time differs (`sketch::sketch_cpc` vs
`sketch::sketch_kll_double` vs `sketch::sketch_req_float`). A combined
table would either need to widen to all column types (carrying nulls
across rows) or normalize via a tagged-union column (forcing additional
casts per query). Per-family tables keep each op self-contained and
make the storage-size validation queries trivial — `octet_length` is
applied to the column whose type already matches the family.

ClickHouse's `-State` / `-Merge` aggregate combinators are *algorithmically*
comparable to DataSketches Theta / KLL / frequent-items but are **not
binary-portable** with the Apache DataSketches binary format — different
hash families and serialization layouts. The persist+merge+requery shape
is identical; portability across engines via raw bytes is not. The
storage column types are parameterised: `AggregateFunction(uniq, UInt64)`,
`AggregateFunction(quantileTDigest(0.5), Float64)`,
`AggregateFunction(topK(8), String)` — different from the BINARY-portable
columns the other engines use.

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

## Storage-size methodology

Each ★ headline op carries a pair of `*_storage_size_<engine>`
`validation_query` entries that measure the byte length of the merged
sketch state. This certifies the persisted sketch hasn't regressed to
zero or grown unboundedly — the cost-per-byte side of the
persistence-vs-recompute tradeoff that latency alone doesn't surface.

The split into per-engine variants (rather than a single cross-engine
validation with a wide envelope) is deliberate: a wide envelope spanning
DuckDB's ~16KB and ClickHouse's ~60KB would let DuckDB silently grow 5x
before alarming. Each variant runs only on its target engine via explicit
`null` overrides for every other engine.

| Op                                | DuckDB variant + bounds                        | ClickHouse variant + bounds                       |
|-----------------------------------|-------------------------------------------------|---------------------------------------------------|
| `sketch_query_theta_union_merge`  | `theta_storage_size_duckdb` [4000, 32000]       | `theta_storage_size_clickhouse` [16000, 100000]   |
| `sketch_query_kll_quantiles_merge`| `kll_storage_size_duckdb` [1000, 6000]          | `kll_storage_size_clickhouse` [1500, 8000]        |
| `sketch_query_topk_combine`       | `topk_storage_size_duckdb` [300, 1200]          | `topk_storage_size_clickhouse` [150, 800]         |
| `sketch_cpc_query_union_merge`    | `cpc_storage_size` [400, 4000] (DuckDB-only)    | —                                                  |
| `sketch_req_query_quantile_merge` | `req_storage_size` [1000, 8000] (DuckDB-only)   | —                                                  |

Observed sizes at SF=0.01 (the source of the bounds): Theta lg_k=12 ~16KB
on DuckDB and ~60KB on ClickHouse (60003 bytes verified clickhouse-local
25.4.2, uniq HLL++ default precision); KLL k=200 ~3KB on DuckDB and ~4.3KB
on ClickHouse (4314 bytes verified clickhouse-local 25.4.2, T-Digest
compression=100); frequent-items lg_max_map_size=8 ~600B on DuckDB and
~317B on ClickHouse (317 bytes verified clickhouse-local 25.4.2, topK K=8);
CPC lg_k=11 ~1.2KB merged; REQ k=12 ~2.5KB merged.

CPC vs Theta storage: CPC at ~1.2KB is roughly **13× smaller** than Theta
at ~16KB on the same 15K distinct keys at SF=0.01. The tradeoff is
slower update/merge throughput — measure both in a single run by
comparing `sketch_query_theta_union_merge` and
`sketch_cpc_query_union_merge` head-to-head.

REQ vs KLL: REQ at ~2.5KB is slightly smaller than KLL at ~3KB. The
algorithmic tradeoff is the error guarantee — KLL gives normalized-rank
error, REQ gives relative-error. Cross-reference
`sketch_query_kll_quantiles_merge` and `sketch_req_query_quantile_merge`.

Per-engine SQL is wired through `validation_query.platform_overrides`:

- DuckDB: `octet_length(<merged_sketch>)` against the `BLOB` column.
- ClickHouse: `length(toString(<agg>MergeState(...)))` against the
  `AggregateFunction(...)` column. `length()` doesn't accept
  AggregateFunction directly, so `toString()` serializes the merged state
  to its bytes-of-string representation. Caveat: this is the textual
  representation length, not the on-disk binary state length — these are
  correlated and stable enough across runs for regression detection, but
  do not interpret the absolute number as the storage cost a ClickHouse
  user actually pays.
- Other engines (Databricks, Snowflake, BigQuery, Redshift, DataFusion,
  SQLite, StarRocks): skipped via explicit `null` overrides because their
  byte-length probes for sketch state aren't yet wired. Add them in
  follow-up TODOs as cloud verification lands.

Bounds span both engines so a single validation passes on whichever
engine the op runs on. Per-engine tightening (separate
`*_storage_size_<engine>` validations with engine-specific bounds) is a
future option if drift detection needs to be tighter.

## Try it locally on clickhouse-local

ClickHouse Local (`clickhouse local`, the embeddable single-binary build
that ships with the standard Homebrew / DEB / RPM ClickHouse package)
runs the headline ClickHouse sketch overrides without any cloud
credentials. Install via `brew install clickhouse` (or your distro
equivalent) and run:

```bash
uv run -- benchbox run --platform clickhouse-local --benchmark write_primitives \
  --scale 0.01 \
  --queries sketch_ddl_create_persistent_table,\
sketch_insert_theta_per_partition,\
sketch_insert_kll_per_partition,\
sketch_insert_topk_per_shard,\
sketch_query_theta_union_merge,\
sketch_query_kll_quantiles_merge,\
sketch_query_topk_combine,\
sketch_drop_persistent_table
```

Expected: 8/8 ops pass, both scalar-bounds and per-engine
`*_storage_size_clickhouse` validations report passed (DuckDB
`*_storage_size_duckdb` siblings are skipped via `null` overrides on
ClickHouse and vice versa). Live observations from clickhouse-local
25.4.2 at SF=0.01: theta merged state 60003 bytes, KLL merged state
4314 bytes, topK merged state 317 bytes — all inside the bounds in
`operations.yaml`.

## Parameter sweeps (DuckDB-only)

The default headline ops use one parameter value per sketch family
(Theta lg_k≈12, KLL k=200, frequent-items lg_max_map_size=8). Real
workloads tune these because the size / accuracy / latency tradeoff is
real and workload-dependent. Six sweep variants pin the parameter
explicitly so users can measure the tradeoff in a single run rather
than guessing.

| Family            | Variants                                | Default               | Range                     |
|-------------------|------------------------------------------|------------------------|----------------------------|
| Theta `lg_k`      | `_lgk10`, `_lgk14`                       | 12 (4096 entries)     | 10 (1024) ↔ 14 (16384)    |
| KLL `k`           | `_k100`, `_k1000`                        | 200 (~3KB)            | 100 (~2KB) ↔ 1000 (~18KB) |
| Top-K `lg_max_map`| `_lgmm8`, `_lgmm10`                      | 8 (256 buckets)       | 8 (~600B) ↔ 10 (~2KB)     |

Naming convention: `sketch_query_<family>_<merge>_<param>`. Example:
`sketch_query_kll_quantiles_merge_k1000`.

Top-K only sweeps two values because `lg_max_map_size=6` (64 buckets)
is too small for TPC-H lineitem's 7 distinct shipmodes — the merged
sketch would saturate.

Cloud-engine sweep variants are deferred. Each cloud engine has
different parameter knobs (Snowflake `APPROX_TOP_K` `counters` vs
DataSketches `lg_max_map_size`, etc.); 6 families × 3 cloud engines is
out of proportion with the analytical value. DuckDB-only sweep is
enough to demonstrate the tradeoff; cloud users tune at their end with
vendor-specific knobs.

KLL variants are end-to-end verified on the installed datasketches
extension (k=100: ~2KB merged at SF=0.01, median=7395 vs true=7500;
k=1000: ~18KB merged, median=7509). Theta and frequent-items variants
share the parent ops' fate w.r.t. the recorded extension drift in
`_project/blind-spots/2026-05-02-155524-duckdb-datasketches-extension-drift.md`.

## Single-query scope: what this benchmark is **not**

This benchmark measures **latency under approximate semantics**, not
**approximation error magnitude**. Users who want to evaluate
approximation-quality tradeoffs (paired exact/approximate queries with
relative-error metrics) will need a separate benchmark — that's
deliberately deferred (see TODO `deferred:` block).

Cross-engine sketch portability tests (write a sketch on engine A,
query it on engine B) are also deferred — this needs two-engine
orchestration that BenchBox does not have today.

## Catalog extension points (architecture-fixes 2026-05-04)

Two catalog extension points support engine-specific sketch work without
abusing existing schemas. Both were added so cross-engine sketch follow-ups
(ClickHouse-native `-State`/`-Merge`, PySpark DataFrame HLL, etc.) can land
without forcing per-engine SQL into a single body or routing aggregate-state
DataFrame ops through row-level mutation APIs.

### `validation_query.platform_overrides`

The shape mirrors operation-level `platform_overrides`:

```yaml
operations:
  - id: sketch_query_theta_union_merge
    write_sql: "SELECT datasketch_theta_estimate(...) FROM ..."  # default (DuckDB)
    platform_overrides:
      clickhouse: "SELECT uniqMerge(user_sketch) FROM ..."
    validation_queries:
      - id: scalar_bounds
        sql: "SELECT datasketch_theta_estimate(...) FROM ..."   # default
        expected_value_min: 14500
        expected_value_max: 15500
        platform_overrides:
          clickhouse: "SELECT uniqMerge(user_sketch) FROM ..."  # ClickHouse-native validation
          redshift: null                                        # explicit skip
```

Resolution rules (see `_resolve_validation_sql` in `benchmark.py`):

- **No override key** → the active platform falls through to the default
  `sql`. Existing catalog entries are unchanged.
- **String override** → the per-platform SQL replaces the default for that
  platform; the resolved SQL is recorded in `validation_results[*].sql` so
  observers see what actually ran.
- **`null` override** → the validation is skipped on that platform with a
  logged reason. The op still passes (skip means "not applicable on this
  engine", not "failed"). The skip is captured in `validation_results[*]`
  as `skipped: true` and `skip_reason: "..."`.

Strict load-time validation rejects empty strings and non-mapping types so a
typo cannot silently disable validation. Use the explicit `null` form when
you want to skip; do not rely on omission.

### `AGGREGATE_PERSIST` / `AGGREGATE_MERGE` DataFrame op types

`WriteOperationType` now models DataFrame-layer aggregate-state work as two
distinct types so the persist and merge phases produce separate user-facing
measurements (write latency + persisted state size vs. merge+extract
latency).

Engines that expose DataFrame-layer sketch APIs flip
`DataFrameWriteCapabilities.supports_aggregate_persist` /
`supports_aggregate_merge` on. PySpark presets do this today (Spark 3.5+
ships `hll_sketch_agg`/`hll_union_agg`); Polars and pandas do not.

The dispatch methods are deliberately engine-agnostic — they accept caller-
supplied callables that own the engine-specific sketch chain:

```python
manager = get_dataframe_write_manager("pyspark-df", spark_session=spark)

def build_state():
    return (
        spark.read.parquet(source)
        .groupBy("activity_date", "region")
        .agg(F.hll_sketch_agg("l_orderkey").alias("user_sketch"))
    )

persist = manager.execute_aggregate_persist(target_path, build_state, compression="zstd")

def merge_extract(path):
    state = spark.read.parquet(str(path))
    estimate = state.agg(F.hll_sketch_estimate(F.hll_union_agg("user_sketch"))).collect()[0][0]
    return float(estimate)

merge = manager.execute_aggregate_merge(target_path, merge_extract)
# merge.metrics["aggregate_value"] holds the extracted scalar
```

The manager owns timing, durability (Parquet write to a target dir),
byte/file-count bookkeeping, and the `DataFrameWriteResult` envelope. The
callable owns the sketch surface. Engines without a DataFrame-layer sketch
API short-circuit through `supports_operation` and return a structured
failure with a clear "use the SQL surface or skip this op" message.

Cleanup of the persisted state directory is the consumer's responsibility
today (the persist phase leaves a Parquet directory at `target_path`;
remove it with `shutil.rmtree` after the merge phase). A dedicated
`execute_aggregate_cleanup` helper may land later if symmetry becomes
load-bearing — surface the request in a follow-up TODO if you need it.

### PySpark sketch factory helpers

`benchbox.core.write_primitives.dataframe_operations` exposes factory
functions that produce the `state_builder` and `merge_extract` callables
for the persist+merge cycle on PySpark, so consumers don't have to repeat
the spark-read / groupBy / agg chain by hand:

| Family | Persist factory                          | Merge factory                          | Spark floor |
|--------|------------------------------------------|----------------------------------------|-------------|
| HLL    | `make_pyspark_hll_persist_builder(...)`  | `make_pyspark_hll_merge_extract(...)`  | 3.5         |
| Top-K  | `make_pyspark_topk_persist_builder(...)` | `make_pyspark_topk_merge_extract(...)` | 4.1         |

Top-K requires `F.approx_top_k_accumulate`, which ships with Spark 4.1+.
Guard with `pyspark_supports_approx_top_k(spark)` before calling the
top-K factory; older runtimes should skip cleanly with a logged reason.
The guard is conservative: it requires both the version gate (≥4.1) and
the function symbol — distributions that backport the function to a
3.5.x build will be rejected by the version check. If you hit that case,
bypass the guard or open a TODO to add a backport-detection branch.

The factory unit tests are MagicMock-based and verify call patterns. The
real-Spark CLI integration is wired through the catalog ops
`sketch_df_hll_persist_merge` and `sketch_df_topk_persist_merge` — both
declare an `aggregate_state` block that the dispatch fork in
`WritePrimitivesBenchmark._execute_dataframe_sql_parity_workload` routes
through `manager.execute_aggregate_persist` /
`manager.execute_aggregate_merge` on the active platform's
`DataFrameWriteOperationsManager` instead of through the DuckDB parity
path. HLL is verified live on PySpark 4.1.1 at SF=0.01:
`aggregate_value=14852` (true distinct l_orderkeys = 15000, 0.99% RSE,
inside the `[14250, 15750]` bound). Top-K skips cleanly on the same
runtime because the PySpark 4.1.1 client wheel does not expose
`F.approx_top_k_accumulate` / `F.approx_top_k_combine` /
`F.approx_top_k_estimate` in its Python `functions` namespace —
`pyspark_supports_approx_top_k(spark)` returns `False` and the dispatch
fork records a structured `SKIPPED` result. To exercise top-K live, run
on a Spark distribution that surfaces `approx_top_k_accumulate` in the
Python API.

KLL is intentionally **not** implemented at the DataFrame layer because
Spark's KLL surface is SQL-UDAF-only today; using `percentile_approx`
would be one-shot (no separate persist+merge measurement), defeating the
whole point.

Example consumer pattern using the factories:

```python
from benchbox.core.write_primitives.dataframe_operations import (
    get_dataframe_write_manager,
    make_pyspark_hll_persist_builder,
    make_pyspark_hll_merge_extract,
)

manager = get_dataframe_write_manager("pyspark-df", spark_session=spark)
target = Path("/tmp/sketch_state/hll")

builder = make_pyspark_hll_persist_builder(
    spark, "/data/lineitem",
    group_cols=["l_shipdate", "l_returnflag"],
    value_col="l_orderkey",
)
persist = manager.execute_aggregate_persist(target, builder, compression="zstd")

merge_extract = make_pyspark_hll_merge_extract(spark, sketch_col="sketch")
merge = manager.execute_aggregate_merge(target, merge_extract)
distinct_estimate = merge.metrics["aggregate_value"]
```

**CLI integration gap.** `benchbox run --platform pyspark --benchmark
write_primitives --queries sketch_df_hll_persist_merge` does not yet
dispatch through these factories — the catalog has no `sketch_df_*`
entries and `_execute_dataframe_sql_parity_workload` always routes to
embedded DuckDB. The factory helpers are usable today via direct manager
calls (covered by `tests/unit/core/write_primitives/test_pyspark_sketch_factories.py`);
wiring them into the benchmark CLI is tracked as a follow-up. See
`_project/blind-spots/2026-05-04-011321-pyspark-sketch-todo-scope-vs-verification-mismatch.md`.

---
blogpost: false
status: outlined
date: TBD
author: Joe Harris
series: building-benchbox
post_number: 12
type: architecture-design
tags: benchbox, approximate-functions, sketches, datasketches, hyperloglog, kll, theta, top-k, databricks, snowflake, bigquery, redshift, clickhouse, duckdb, methodology, design-decision
meta_description: "Why responding to Databricks' new sketch functions took two BenchBox benchmarks instead of one — and what cross-engine sketch coverage actually looks like."
---

# Two benchmarks for one announcement: covering Databricks' new sketch functions in BenchBox

> Databricks shipped sketch functions for distinct counts, quantiles, and top-K. The headline claim wasn't the function names — it was that sketches are *storable, mergeable, requeryable artifacts*. Function-parity tables miss that distinction entirely.

**TL;DR**: BenchBox v0.2.x adds approximate-aggregate coverage to `read_primitives` (5 new queries: HLL distinct, KLL/T-Digest single quantile, vector quantiles, top-K) and a new `sketch` category to `write_primitives` (8 ops covering DataSketches Theta/KLL/Top-K persist + merge + requery). Splitting coverage across two benchmarks was a deliberate choice: the single-query catalog can measure aggregate latency, but it cannot exercise the persist/merge/requery loop that vendors actually compete on. Cross-engine coverage now spans 7 engines, with documented HLL-only ceilings on Redshift, native-but-distinct sketch state on ClickHouse, and explicit skips on DataFusion. The companion docs ship the per-engine function-name reference: [`read_primitives`](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/read-primitives-approximate-functions.md), [`write_primitives` sketch](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/write-primitives-sketch-functions.md).

---

## Audience and scope

**Primary audience**: Data engineers and analytics engineers who read the Databricks announcement and want to know what cross-engine support actually looks like, plus BenchBox users who want to evaluate sketch performance on their own platform mix.

**Secondary audience**: Benchmark designers and OSS maintainers who care about evaluation methodology — specifically about how to keep parity-table evaluations from missing the actually-novel half of a vendor announcement.

**Out of scope** (call out, don't cover):
- Approximation-quality tradeoffs (relative-error vs. exact). BenchBox measures latency under approximate semantics, not error magnitude. Deferred to a future benchmark.
- Cross-engine sketch *portability* tests (write a sketch on engine A, query it on engine B). Needs two-engine orchestration BenchBox does not have today.
- Parameter sweeps over `lg_k` / `k` / `lg_max_map_size`. Tracked in `write-primitives-sketch-parameter-sweeps`, blocked on architecture fixes.

---

## Thesis and key insight

**Thesis**: Function-parity tables were the obvious response to the Databricks sketch announcement, but they capture only the boring half of what the post claims. The differentiated capability — millisecond merge across persisted sketch artifacts — needs an execution model with persistence and multi-query state. BenchBox's `read_primitives` cannot express that loop; `write_primitives` can. So the right response is two benchmarks, not one, with explicit honest-accounting on which engines clear which bar.

**The framework-gap insight** (recorded as a blind-spot finding, `2026-05-02-084332`):
> The standard parity-table evaluation framework under-weights "stored,
> mergeable, requeryable" claims because the evaluation rubric (function
> name → competitor function name → add or skip) doesn't have an axis
> for "does this benchmark's execution model fit the capability under
> test."

This is reusable: it applies to any vendor announcement framed as "stored, mergeable, requeryable" — sketches today, search indexes tomorrow, vector indexes the day after, incremental MVs after that, ML feature stores after that. Every time, the parity table will say "add the queries"; every time, the single-query benchmark will fail to exercise what's actually announced.

---

## Section breakdown

### 1. The Problem (~300 words) — What Databricks announced and why parity tables miss the point

- The April 2026 Databricks post: new sketch functions across three families (Theta-style distinct, KLL quantile, Top-K accumulator) with `*_accumulate` / `*_combine` / `*_estimate` trios.
- Surface-level read: parity-table evaluation. Map each new function to its peer on Snowflake / BigQuery / DuckDB / ClickHouse / Redshift. Mark the gaps.
- Hidden claim: **sketches are storable, mergeable, requeryable artifacts**. Aggregate latency has been "approximate-is-faster-than-exact" on every engine for a decade. The novel claim is "store sketches as columns, merge across time/partition, requery in milliseconds."
- Why parity tables fail: the rubric has no axis for "does the benchmark's execution model fit the capability under test." A read-only single-query catalog can score aggregate latency, but it cannot exercise persist + merge + requery.
- The L2 audit insight (cite the blind-spot file): single-query benchmarks can technically run sketch queries and produce numbers, but those numbers measure the trivial half of the announcement. The post will look correct on paper while missing the differentiated capability.

**Key quotes/data points to include**:
- The exact `*_accumulate` / `*_combine` / `*_estimate` function trio from the Databricks post.
- One paragraph paraphrasing what "millisecond-merge across partitioned sketch columns" actually means operationally.

### 2. What We Tried (~450 words) — The framework-gap insight and the decision to split coverage

- First-pass evaluation: function-by-function competitor parity research (see `_project/DONE/main/read-primitives-approximate-aggregate-queries.yaml`). The output was a clean table mapping each new Databricks function to its peer across 6 engines.
- The L2 blind-spot audit caught the gap before queries shipped: `read_primitives` is structurally a single-query benchmark. Each query in `catalog/queries.yaml` runs in isolation against TPC-H tables, with no facility to write a sketch column, read it back later, or merge across partitions in a multi-query workflow.
- Two options considered:
  - **Option A**: Add sketch-aggregate queries to `read_primitives`. Honest: cheap, single-PR, measures latency. Dishonest: claims to cover the announcement while only exercising the un-novel half.
  - **Option B**: Add a new `sketch` category to `write_primitives`. Honest: actually exercises persist + merge + requery. Cost: requires platform_overrides for cross-dialect DDL, BINARY column type translation, tolerance-based validation for non-deterministic sketch outputs, and explicit Redshift HLL-substitution.
- The decision: do both, with explicit cross-references in both docs explaining which capability each benchmark covers.
- A second-order finding from implementation: the architecture itself wasn't ready. Two write_primitives architectural gaps surfaced when the ClickHouse + cloud verification work started:
  - `validation_query` had no per-platform override mechanism (`2026-05-02-155448`)
  - `WriteOperationType` enum had no aggregate-state shape for DataFrame engines (`2026-05-02-163132`)
- Both fixes landed in the architecture-fixes work-item; the cloud verification, ClickHouse-native variants, DuckDB CPC/REQ families, PySpark DataFrame surface, and parameter sweeps are queued behind it. Honest accounting: cloud verification is deferred until credentials are available; cross-cloud measurements are not in this announcement.

**Key data points**:
- Catalog of architectural gaps surfaced (table linking blind-spot file → resolution TODO).
- Why "skip the persistence half" was rejected (it's the differentiated claim).

### 3. What We Built (~600 words) — The two-benchmark coverage with cross-engine matrices

#### `read_primitives` approximate aggregates (single-query, latency-only)

5 new queries:

| Query | Capability | Skipped on |
|-------|------------|------------|
| `approx_count_distinct_simple` | HLL distinct, single value | sqlite |
| `approx_count_distinct_groupby` | HLL distinct per group | sqlite |
| `approx_quantile_groupby` | T-Digest / KLL single quantile | sqlite |
| `approx_quantiles_array` | Vector quantiles per group | redshift, datafusion, sqlite |
| `approx_top_k_lineitem` | Approximate top-K | redshift, datafusion, sqlite |

Cross-engine function reference table (compressed; full version in docs):

| Engine | Distinct | Quantile | Top-K |
|--------|----------|----------|-------|
| DuckDB | `APPROX_COUNT_DISTINCT` | `APPROX_QUANTILE(x, 0.5)` | `APPROX_TOP_K(x, 5)` |
| Snowflake | `APPROX_COUNT_DISTINCT` | `APPROX_PERCENTILE(x, 0.5)` | `APPROX_TOP_K(x, 5)` |
| BigQuery | `APPROX_COUNT_DISTINCT` | `APPROX_QUANTILES(x, 100)[OFFSET(50)]` | `APPROX_TOP_COUNT(x, 5)` |
| Databricks | `approx_count_distinct` | `PERCENTILE_APPROX(x, 0.5)` | `approx_top_k(x, 5)` |
| ClickHouse | `uniq` | `quantileTDigest(0.5)(x)` | `topK(5)(x)` |
| Redshift | `APPROXIMATE COUNT(DISTINCT x)` | `APPROXIMATE PERCENTILE_DISC(0.5)…` | — (no top-K) |
| DataFusion | `approx_distinct` | `approx_percentile_cont(x, 0.5)` | — |

DataFrame surface (separate matrix; sketch-backed vs exact-fallback distinction):

| Query | Polars | PySpark | DataFusion | pandas / Modin / cuDF | Dask |
|-------|--------|---------|-----------|-----------------------|------|
| `approx_count_distinct_*` (HLL) | `approx_n_unique` | `approx_count_distinct` | `approx_distinct` | exact `nunique` | series-only HLL via `nunique_approx`; groupby exact |
| `approx_quantile_groupby` | exact | `percentile_approx` (KLL) | `approx_percentile_cont` (T-Digest) | exact | exact |
| `approx_quantiles_array`, `approx_top_k_lineitem` | (skip) | (skip) | (skip) | (skip) | (skip) |

Honest accounting: pandas / Modin / cuDF have no native sketch surface, so their "approximate" rows fall back to exact aggregates and are not directly comparable to sketch-backed engines on the same row.

#### `write_primitives` sketch category (persist + merge + requery)

8 ops covering the full DataSketches lifecycle:

| Op | Stage | Notes |
|----|-------|-------|
| `sketch_ddl_create_persistent_table` | DDL | CREATE/DROP overhead with BINARY columns |
| `sketch_insert_theta_per_partition` | INSERT | Build Theta sketches per (date, region) |
| `sketch_insert_kll_per_partition` | INSERT | Build KLL price sketches per (date, region) |
| `sketch_insert_topk_per_shard` | INSERT | Build frequent-items sketches per shard |
| ★ `sketch_query_theta_union_merge` | MERGE | HEADLINE — distinct from merged thetas |
| ★ `sketch_query_kll_quantiles_merge` | MERGE | HEADLINE — median from merged KLLs |
| ★ `sketch_query_topk_combine` | MERGE | HEADLINE — frequent items count from merge |
| `sketch_drop_persistent_table` | DDL | DROP overhead |

Sketch-family × engine support (compressed):

| Family | DataSketches binary-portable | Native-but-distinct | No support |
|--------|------------------------------|----------------------|------------|
| Theta (distinct) | Databricks, Snowflake, BigQuery (HLL substitution), DuckDB ext | ClickHouse (`-State`/`-Merge`), Redshift (HLL substitution) | DataFusion |
| KLL (quantile) | Databricks, Snowflake, BigQuery, DuckDB ext | ClickHouse (`quantileTDigestState`) | Redshift, DataFusion |
| Top-K | Databricks, Snowflake, DuckDB ext | ClickHouse (`topKState`) | Redshift, BigQuery, DataFusion |

Validation tolerance methodology — the ★ headline ops use `expected_value_min/max` because sketch outputs are non-deterministic across engines and runs. Bounds intentionally wide enough never to false-fail, tight enough to catch a regression to no-op or a wildly off estimate.

Redshift HLL-only ceiling — the catalog explicitly carries Redshift overrides that substitute `HLL_CREATE_SKETCH` / `HLL_COMBINE` / `HLL_CARDINALITY` for the Theta path, with KLL and Top-K skipped honestly. Redshift's `HLLSKETCH` columns carry non-trivial DDL restrictions (cannot be DISTKEY/SORTKEY, cannot appear in GROUP BY) that the Redshift-specific DDL emits inline.

### 4. What We Learned (~400 words) — What this exposes about modern OLAP and benchmarking

- **The two-tier reality of "approximate analytics"**. Every modern OLAP engine has the one-shot aggregate path. Only a subset have the persist-merge-requery path. Calling both "approximate functions" obscures the actual capability gap. Vendors compete on the second tier; benchmarks should distinguish them explicitly.
- **DataSketches binary portability is real**. Databricks, Snowflake, BigQuery (for HLL), and the DuckDB community extension all share the underlying C++/Java/WASM core. ClickHouse runs its own format that is comparable algorithmically but not binary-compatible. This matters for any future cross-engine sketch portability story.
- **The HLL-only ceiling on Redshift is structural**, not a roadmap gap. No KLL, no T-Digest, no Top-K, no Theta, no CMS. The April 2026 "Top-K optimization" announcement was an internal optimizer change for `ORDER BY … LIMIT N`, not a new function family. Honest accounting pushes us to skip with rationale rather than emulate via UDFs (which would measure UDF dispatch, not sketch performance).
- **The framework-gap pattern repeats**. Whenever a vendor announces "stored, mergeable, requeryable" — sketches, materialized aggregates, search indexes, vector indexes, incremental MVs, ML features — a single-query benchmark catalog cannot test the differentiated claim. The evaluation rubric needs an explicit axis for "does this benchmark's execution model fit the capability under test?" We're going to apply this to vector indexes next.

### 5. Try It Yourself (~150 words) — Commands to run

```bash
# Read primitives, approximate aggregates only
benchbox run --platform duckdb --benchmark read_primitives \
  --queries approx_count_distinct_simple,approx_count_distinct_groupby,approx_quantile_groupby,approx_quantiles_array,approx_top_k_lineitem \
  --scale 1

# Write primitives sketch category — full persist + merge + requery loop
benchbox run --platform duckdb --benchmark write_primitives \
  --queries sketch_ddl_create_persistent_table,sketch_insert_theta_per_partition,sketch_insert_kll_per_partition,sketch_insert_topk_per_shard,sketch_query_theta_union_merge,sketch_query_kll_quantiles_merge,sketch_query_topk_combine,sketch_drop_persistent_table \
  --scale 1

# DataFrame surface — sketch-backed engines vs exact-fallback engines
benchbox run --platform polars-df,pyspark-df,datafusion-df,pandas-df --benchmark read_primitives \
  --queries approx_count_distinct_simple,approx_count_distinct_groupby,approx_quantile_groupby \
  --scale 0.1

# DuckDB datasketches extension is auto-installed; for ClickHouse, point at chDB
```

Pointer to docs:
- [`read_primitives` approximate-aggregate functions](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/read-primitives-approximate-functions.md)
- [`write_primitives` sketch persistence operations](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/write-primitives-sketch-functions.md)

---

## Required benchmark runs to make the post valuable

The post's claims need supporting numbers from runs that are reproducible with what BenchBox actually has working today (DuckDB SQL + DataFrame engines + chDB local ClickHouse). Cloud verification is deferred until credentials are available.

| # | Run | Platform(s) | Benchmark / queries | Scale | What it shows |
|---|-----|-------------|---------------------|-------|---------------|
| 1 | DuckDB approx vs exact latency | duckdb | `read_primitives` — all 5 approx queries + matched exact counterparts (`aggregation_distinct`, `statistical_percentiles`, …) | SF=1 | Approximate path is 2-10x faster than exact on the same data; concrete numbers anchor the "boring half" claim |
| 2 | DuckDB sketch persist+merge cycle | duckdb | `write_primitives` sketch category — all 8 ops (DDL → 3 inserts → 3 ★ merges → DROP) | SF=1 | Persist+merge+requery is end-to-end working; ★ merge ops report sub-second latency on 14k-15k merged distincts |
| 3 | Sketch merge holds across SF | duckdb | `write_primitives` ★ merge ops (`sketch_query_*_merge`) only | SF=0.1, 1, 10 | Merge latency stays roughly constant while exact aggregate latency grows with cardinality — the "millisecond merge" claim made concrete |
| 4 | DataFrame sketch-backed vs exact-fallback | polars-df, pyspark-df, datafusion-df, pandas-df, dask-df | `read_primitives` — `approx_count_distinct_*` and `approx_quantile_groupby` | SF=0.1 | Sketch-backed engines (Polars HLL, PySpark KLL, DataFusion T-Digest) finish well ahead of exact-fallback engines (pandas, Dask groupby) on the same query — surfaces the capability gap that picking pandas hides |
| 5 | ClickHouse-native variants | chDB (local) | `read_primitives` approx queries — `uniq`, `quantileTDigest`, `topK` via existing dialect variants | SF=0.1 | Demonstrates ClickHouse's native (non-DataSketches) approximate surface is competitive on the aggregate path |
| 6 | (Deferred) Cloud verification | snowflake, bigquery, databricks, redshift | `read_primitives` approx queries + `write_primitives` sketch category | SF=0.1 | Validates the published cross-engine matrix end-to-end. Deferred to a follow-up post when credentials land; tracked in `write-primitives-sketch-cloud-verification`. |

Suggested chart types:
- **Run 1**: side-by-side bar — exact-vs-approx latency, one panel per query.
- **Run 2**: stacked bar — phase breakdown (DDL / insert / merge / DDL) per ★ op.
- **Run 3**: line chart — merge latency vs SF on log-scale (showing flat sketch-merge curve next to a notional exact-aggregate growth curve).
- **Run 4**: grouped bar — DataFrame engine × query, color-coded by sketch-backed (saturated) vs exact-fallback (hatched).
- **Run 5**: companion bar to Run 1 — ClickHouse native variants side-by-side with DuckDB approx.

All charts ASCII via `benchbox visualize` or the textcharts MCP.

---

## Voice and tone targets

Per the building-benchbox series template:
- Frame as "we built the framework gap" not "we caught a flaw" — the L2 audit is presented as the protocol working, not as embarrassment about a near-miss.
- Neutral on platforms — Redshift's HLL-only ceiling and DataFusion's lack of support are stated as engineering facts, not as platform criticism. Databricks gets credit for the announcement that motivated the work.
- "We" for the project and community (per voice guide rule 1).
- No "industry analyst" framing — share findings, don't pronounce judgments (per voice guide rule 5).
- Acknowledge limitations explicitly (voice guide rule 3): cloud verification is deferred; approximation-quality vs latency isn't tested; cross-engine portability isn't tested.

## Anti-patterns to actively avoid

- **Press-release TL;DR**: don't use "Databricks promised X but BenchBox delivered Y" framing. Databricks' announcement is credited as the motivating context, not contrasted against.
- **Function-name list dump**: the cross-engine matrices already exist in the docs; the blog post should compress them, not duplicate them in full.
- **"In our next post…"**: end with a CTA to the docs and the GitHub repo, not a series footer cliffhanger.
- **Defensive sections**: no "addressing skepticism about sketches" — let the data and the methodology footnotes do that work.
- **Pre-defending absent critics**: don't write "you might think parity tables are fine, but…" — just present the framework-gap insight as the interesting finding.

---

## References & related material

### Source material
- Databricks blog post (2026-04-29): "Approximate Answers, Exact Decisions: New Sketch Functions for Analytics" — https://www.databricks.com/blog/approximate-answers-exact-decisions-new-sketch-functions-analytics
- Apache DataSketches project: https://datasketches.apache.org/

### Internal artifacts to cite
- `_project/DONE/main/read-primitives-approximate-aggregate-queries.yaml` — w1-w5 background and per-engine function research
- `_project/DONE/main/read-primitives-approximate-aggregates-dataframe-coverage.yaml` — DataFrame matrix research
- `_project/DONE/main/redshift-maximum-approximate-coverage.yaml` — HLL-only ceiling
- `_project/DONE/main/write-primitives-sketch-persistence-category.yaml` — persist+merge+requery design
- `_project/blind-spots/2026-05-02-084332-read-primitives-cant-test-sketch-persistence.md` — the framework-gap finding (this is the L2 audit insight to feature)
- `_project/blind-spots/2026-05-02-155448-validation-query-no-per-platform-override.md` — architectural gap surfaced
- `_project/blind-spots/2026-05-02-155524-duckdb-datasketches-extension-drift.md` — extension-drift caveat
- `_project/blind-spots/2026-05-02-163132-write-primitives-dataframe-execution-model-no-sketch-shape.md` — DataFrame op-shape gap
- `docs/benchmarks/read-primitives-approximate-functions.md` — public per-engine reference
- `docs/benchmarks/write-primitives-sketch-functions.md` — public per-engine reference

### Recent shipped work (commits to mention)
- PR #112 — sketch persistence + read_primitives approximate-aggregates landed together
- PR #114 — runtime bound enforcement + Snowflake/BigQuery overrides
- PR #134 — Redshift HLL-only coverage
- PR #135 — DataFrame approx_count_distinct + sketch-backed quantile coverage
- PR #138/139 — architecture fixes planning + sketch review followups
- d4384c34c — `validation_query.platform_overrides`
- fcc282e7d — `AGGREGATE_PERSIST` / `AGGREGATE_MERGE` DataFrame op types

### Honest deferrals (called out in the post body, not hidden in a footnote)
- `write-primitives-sketch-cloud-verification` — needs Snowflake/BigQuery/Databricks/Redshift creds
- `write-primitives-sketch-clickhouse-and-storage-metrics` — ClickHouse-native variants + storage-size validation
- `write-primitives-sketch-duckdb-cpc-req-families` — DuckDB CPC and REQ sketch families
- `write-primitives-sketch-pyspark-dataframe-surface` — PySpark DataFrame sketch persist+merge
- `write-primitives-sketch-parameter-sweeps` — `lg_k` / `k` / `lg_max_map_size` parameter axis

---

## Outline status

- **Length target**: ~2,300-2,500 words (sits inside the 1,500-2,500 envelope; the cross-engine matrices push toward the upper end).
- **Conflicts checked**: no overlap with any planned outline. Posts #1-11 are unrelated topics. The benchbox-in-action series is methodology-driven (no overlap with this engineering-decision framing).
- **Next step**: gather the 5 in-scope benchmark runs (DuckDB approx-vs-exact, DuckDB sketch full cycle, multi-SF sketch merge, DataFrame matrix, chDB ClickHouse) and slot the actual numbers in before drafting. Cloud verification stays deferred and is called out as a follow-up.
- **Series-plan update**: row #12 added.

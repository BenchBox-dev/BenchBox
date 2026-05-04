---
blogpost: false
status: outlined
date: TBD
author: Joe Harris
series: building-benchbox
post_number: 12
type: architecture-design
tags: benchbox, sketches, datasketches, databricks, clickhouse, duckdb, methodology, design-decision
meta_description: "Why responding to Databricks' new sketch functions took two BenchBox benchmarks instead of one — and what cross-engine sketch coverage actually looks like."
---

# Two benchmarks for one announcement: covering Databricks' new sketch functions in BenchBox

> Databricks shipped sketch functions for distinct counts, quantiles, and top-K. The headline isn't the function names — it's that sketches are *storable, mergeable, requeryable artifacts*. That's not a single-query story.

**TL;DR**: BenchBox develop (shipping in v0.3.0) covers the full Databricks sketch announcement: 5 approximate-aggregate queries in `read_primitives` and 16 persist+merge+requery ops in a new `write_primitives` sketch category (Theta, KLL, Top-K, plus DuckDB-only CPC and REQ families). Cross-engine sketch coverage spans 7 engines, including ClickHouse 8/8 via `-State`/`-Merge` combinators and Redshift via HLL substitution; DataFusion is the no-support skip. Storage-size validation now rides alongside scalar-bounds validation on the ★ headline ops.

---

## Audience and scope

**Primary audience**: Data engineers and analytics engineers who read the Databricks announcement and want to know what cross-engine support actually looks like, plus BenchBox users who want to evaluate sketch performance on their own platform mix.

**Secondary audience**: Benchmark designers and OSS maintainers who care about evaluation methodology — specifically about how to keep parity-table evaluations from missing the persistence half of a vendor announcement.

**Out of scope** (call out, don't cover):
- Approximation-quality tradeoffs (relative-error vs. exact). BenchBox measures latency under approximate semantics, not error magnitude. Deferred to a future benchmark.
- Cross-engine sketch *portability* tests (write a sketch on engine A, query it on engine B). Needs two-engine orchestration BenchBox does not have today.
- Parameter sweeps over `lg_k` / `k` / `lg_max_map_size`. Tracked in `write-primitives-sketch-parameter-sweeps`.

---

## Thesis and key insight

**Thesis**: Function-parity tables were the obvious response to the Databricks sketch announcement, but they capture only the aggregate-latency path. The persist+merge+requery path needs an execution model with persistence and multi-query state. BenchBox's `read_primitives` cannot express that loop; `write_primitives` can. So the right response is two benchmarks, not one, with explicit accounting of which engines clear which bar.

**The framework-gap insight** (recorded as a blind-spot finding, `2026-05-02-084332`):
> The standard parity-table evaluation framework under-weights "stored,
> mergeable, requeryable" claims because the evaluation rubric (function
> name → competitor function name → add or skip) doesn't have an axis
> for "does this benchmark's execution model fit the capability under
> test."

The pattern is reusable. Any vendor announcement framed as "stored, mergeable, requeryable" — sketches today, vector indexes tomorrow, incremental MVs after that — surfaces the same execution-model question. Single-query catalogs can run the queries and produce numbers; they can't exercise the differentiated capability.

---

## Section breakdown

### 1. The Problem (~300 words) — What Databricks announced and why parity tables miss the point

- The April 2026 Databricks post: new sketch functions across three families (Theta-style distinct, KLL quantile, Top-K accumulator) with `*_accumulate` / `*_combine` / `*_estimate` trios.
- Surface-level read: parity-table evaluation. Map each new function to its peer on Snowflake / BigQuery / DuckDB / ClickHouse / Redshift. Mark the gaps. Ship a coverage table.
- The persist+merge+requery story: **sketches are storable, mergeable, requeryable artifacts** — store sketches as columns, merge across time/partition, requery at near-constant cost. The aggregate-latency path has been "approximate-is-faster-than-exact" on every engine for a decade; the persist+merge+requery path is where vendors compete now.
- Why parity tables come up short: the rubric has no axis for "does the benchmark's execution model fit the capability under test." A read-only single-query catalog can score aggregate latency, but it cannot exercise persist + merge + requery.
- The L2 audit insight (cite the blind-spot file): single-query benchmarks can technically run sketch queries and produce numbers, but those numbers measure the aggregate-latency path. The post will look correct on paper while not exercising the persist+merge+requery story the announcement is centered on.

**Key data points to include**:
- The exact `*_accumulate` / `*_combine` / `*_estimate` function trio from the Databricks post.
- One paragraph paraphrasing what "millisecond-merge across partitioned sketch columns" actually means operationally.

### 2. What We Tried (~450 words) — The framework-gap insight and the decision to split coverage

- First-pass evaluation: function-by-function competitor parity research (see `_project/DONE/main/read-primitives-approximate-aggregate-queries.yaml`). The output was a clean table mapping each new Databricks function to its peer across 6 engines.
- The L2 blind-spot audit caught the gap before queries shipped: `read_primitives` is structurally a single-query benchmark. Each query in `catalog/queries.yaml` runs in isolation against TPC-H tables, with no facility to write a sketch column, read it back later, or merge across partitions in a multi-query workflow.
- Two options considered:
  - **Option A**: Add sketch-aggregate queries to `read_primitives`. Cheap, single-PR, measures aggregate latency. But it would only exercise the aggregate-latency path, not the persist+merge+requery loop the announcement centers on.
  - **Option B**: Add a new `sketch` category to `write_primitives`. Actually exercises persist + merge + requery. Cost: requires `platform_overrides` for cross-dialect DDL, BINARY column-type translation, tolerance-based validation for non-deterministic sketch outputs, and explicit Redshift HLL-substitution.
- The decision: do both, with explicit cross-references in both docs explaining which capability each benchmark covers.
- A second-order finding from implementation: the `write_primitives` architecture itself wasn't ready. Two gaps surfaced when ClickHouse + cloud verification work started:
  - `validation_query` had no per-platform override mechanism (`2026-05-02-155448`)
  - `WriteOperationType` enum had no aggregate-state shape for DataFrame engines (`2026-05-02-163132`)
- Both fixes shipped in `feat/write-primitives-architecture-fixes` (PR #176): `validation_query.platform_overrides` mirrors the existing `write_sql.platform_overrides`, and `AGGREGATE_PERSIST` / `AGGREGATE_MERGE` op types extend the DataFrame execution model. The ClickHouse-native variants (PR #180) and DuckDB CPC/REQ families (PR #182) followed immediately, so the catalog surface today is broader than the original first-pass plan: 16 sketch ops covering five families. Cloud verification is the remaining deferral, blocked only on Snowflake / BigQuery / Databricks / Redshift credentials.

**Key data points**:
- Catalog of architectural gaps surfaced (table linking blind-spot file → resolution PR).
- Why "skip the persistence half" was rejected (it's the central claim of the announcement).

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

Cross-engine function-name reference (DuckDB / Snowflake / BigQuery / Databricks / ClickHouse / Redshift / DataFusion) lives in [`docs/benchmarks/read-primitives-approximate-functions.md`](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/read-primitives-approximate-functions.md). Sample row to anchor the post:

| Engine | Distinct | Quantile | Top-K |
|--------|----------|----------|-------|
| DuckDB | `APPROX_COUNT_DISTINCT(x)` | `APPROX_QUANTILE(x, 0.5)` | `APPROX_TOP_K(x, 5)` |
| ClickHouse | `uniq(x)` | `quantileTDigest(0.5)(x)` | `topK(5)(x)` |
| Redshift | `APPROXIMATE COUNT(DISTINCT x)` | `APPROXIMATE PERCENTILE_DISC(0.5)…` | — (no top-K) |

DataFrame surface — sketch-backed vs exact-fallback distinction:

| Query | Polars | PySpark | DataFusion | pandas / Modin / cuDF | Dask |
|-------|--------|---------|-----------|-----------------------|------|
| `approx_count_distinct_*` (HLL) | `approx_n_unique` | `approx_count_distinct` | `approx_distinct` | exact `nunique` | series-only HLL via `nunique_approx`; groupby exact |
| `approx_quantile_groupby` | exact | `percentile_approx` (KLL) | `approx_percentile_cont` (T-Digest) | exact | exact |
| `approx_quantiles_array`, `approx_top_k_lineitem` | (skip) | (skip) | (skip) | (skip) | (skip) |

Pandas / Modin / cuDF have no native sketch surface, so their "approximate" rows fall back to exact aggregates — the benchmark still runs and reports a number, but it's the exact aggregate's latency, not directly comparable to sketch-backed engines on the same row.

#### `write_primitives` sketch category (persist + merge + requery)

The Theta / KLL / Top-K trio is the original 8 ops. Two more families landed in PR #182 (DuckDB-only): CPC for HLL-family distinct-count with much smaller serialized state (~1.2 KB merged at SF=0.01 vs Theta's ~16 KB), and REQ for relative-error quantiles (vs KLL's normalized-rank error). 16 ops total today.

| Family | Ops | Stage | Notes |
|--------|-----|-------|-------|
| Theta (distinct) | DDL → insert → ★ merge → DROP | full | DataSketches binary-portable across DuckDB / Databricks / Snowflake; HLL substitution on BigQuery / Redshift; ClickHouse via `uniqState`/`uniqMerge` |
| KLL (quantile) | DDL → insert → ★ merge → DROP | full | DataSketches across DuckDB / Databricks / Snowflake / BigQuery; `quantileTDigestState` on ClickHouse; skipped on Redshift |
| Top-K (frequent items) | DDL → insert → ★ merge → DROP | full | DataSketches across DuckDB / Databricks / Snowflake; `topKState(8)` on ClickHouse; skipped on BigQuery / Redshift |
| CPC (distinct, compact) | DDL → insert → merge → DROP | DuckDB-only | Compressed Probabilistic Counting; ~1.2 KB merged vs Theta's ~16 KB at SF=0.01; tradeoff is slower update/merge throughput |
| REQ (quantile, rel-err) | DDL → insert → merge → DROP | DuckDB-only | Relative-error quantiles; ~2.5 KB merged at SF=0.01 |

Sketch-family × engine support, post-PR #180:

| Family | DataSketches binary-portable | ClickHouse-native combinators | HLL substitution | No support |
|--------|------------------------------|--------------------------------|------------------|-----------|
| Theta (distinct) | Databricks, Snowflake, DuckDB ext | ClickHouse (`uniqState`/`uniqMerge`) | BigQuery, Redshift | DataFusion |
| KLL (quantile) | Databricks, Snowflake, BigQuery, DuckDB ext | ClickHouse (`quantileTDigestState`) | — | Redshift, DataFusion |
| Top-K | Databricks, Snowflake, DuckDB ext | ClickHouse (`topKState(8)`) | — | BigQuery, Redshift, DataFusion |
| CPC | DuckDB ext only | — | — | all others |
| REQ | DuckDB ext only | — | — | all others |

ClickHouse coverage went from 0/8 (all skipped via `null` overrides) to 8/8 in PR #180 — full cross-engine sketch matrix for the Theta / KLL / Top-K trio. ClickHouse's combinator format isn't binary-portable with DataSketches, but the persist+merge+requery shape behaves identically.

**Two validation axes per ★ headline op** (PR #180):
- *Scalar bounds* — distinct count, median, frequent-item count must land inside `expected_value_min/max`.
- *Storage size* — `octet_length(<sketch>)` on DuckDB, `length(toString(<agg>MergeState(...)))` on ClickHouse. Bounds tuned per engine because the encodings differ; the check certifies the merged state hasn't regressed to zero or grown unbounded.

Redshift HLL-only ceiling — the catalog explicitly carries Redshift overrides that substitute `HLL_CREATE_SKETCH` / `HLL_COMBINE` / `HLL_CARDINALITY` for the Theta path, with KLL and Top-K skipped because Redshift has no equivalent. `HLLSKETCH` columns carry non-trivial DDL restrictions (cannot be DISTKEY/SORTKEY, cannot appear in GROUP BY) that the Redshift-specific DDL emits inline.

### 4. What We Learned (~400 words) — What this exposes about modern OLAP and benchmarking

- **The two-tier reality of "approximate analytics"**. Every modern OLAP engine has the aggregate-latency path. A subset have the persist+merge+requery path. Calling both "approximate functions" obscures the actual capability gap. Vendors compete on the second tier; benchmarks should distinguish them explicitly.
- **DataSketches binary portability is real, but not universal**. Databricks, Snowflake, BigQuery (for HLL), and the DuckDB community extension all share the underlying C++/Java/WASM core. ClickHouse runs its own `-State`/`-Merge` combinator format — comparable algorithmically, behaviorally identical for persist+merge+requery, not binary-compatible with DataSketches. Redshift is HLL-only by `HLLSKETCH` design. Anyone planning a cross-engine sketch-portability story has to map this terrain first.
- **The HLL-only ceiling on Redshift is structural**, not a roadmap gap. No KLL, no T-Digest, no Top-K, no Theta, no CMS. The April 2026 "Top-K optimization" announcement was an internal optimizer change for `ORDER BY … LIMIT N`, not a new function family. The catalog skips the missing families with rationale comments rather than emulating via UDFs (which would measure UDF dispatch, not sketch performance).
- **Sketch-size matters as much as sketch-latency**. PR #180's storage-size validation makes sketch byte-length a first-class measurement. CPC at ~1.2 KB merged vs. Theta at ~16 KB (PR #182) is a real tradeoff: 13× smaller persisted state, slower update/merge throughput. The benchmark surfaces both axes per op so users can pick the right family for their cost model.
- **The framework-gap pattern repeats**. Whenever a vendor announces "stored, mergeable, requeryable" — sketches, materialized aggregates, search indexes, vector indexes, incremental MVs, ML features — a single-query benchmark catalog cannot test the differentiated claim. The same execution-model question applies the next time a "stored, mergeable, requeryable" announcement lands. The fix is to budget two benchmarks before parity-table planning starts.

### 5. Try It Yourself (~150 words) — Commands to run

```bash
# Read primitives, approximate aggregates only
benchbox run --platform duckdb --benchmark read_primitives \
  --queries approx_count_distinct_simple,approx_count_distinct_groupby,approx_quantile_groupby,approx_quantiles_array,approx_top_k_lineitem \
  --scale 1

# Write primitives sketch — Theta + KLL + Top-K full persist + merge + requery loop
benchbox run --platform duckdb --benchmark write_primitives \
  --queries sketch_ddl_create_persistent_table,sketch_insert_theta_per_partition,sketch_insert_kll_per_partition,sketch_insert_topk_per_shard,sketch_query_theta_union_merge,sketch_query_kll_quantiles_merge,sketch_query_topk_combine,sketch_drop_persistent_table \
  --scale 1

# DuckDB-only CPC + REQ families — distinct (compact) and quantile (rel-err)
benchbox run --platform duckdb --benchmark write_primitives \
  --queries sketch_cpc_create_persistent_table,sketch_cpc_insert_per_partition,sketch_cpc_query_union_merge,sketch_cpc_drop_persistent_table,sketch_req_create_persistent_table,sketch_req_insert_per_partition,sketch_req_query_quantile_merge,sketch_req_drop_persistent_table \
  --scale 1

# DataFrame surface — sketch-backed engines vs exact-fallback engines
benchbox run --platform polars-df,pyspark-df,datafusion-df,pandas-df --benchmark read_primitives \
  --queries approx_count_distinct_simple,approx_count_distinct_groupby,approx_quantile_groupby \
  --scale 0.1

# ClickHouse-native sketch ops via chDB
benchbox run --platform chdb --benchmark write_primitives \
  --queries sketch_ddl_create_persistent_table,sketch_insert_theta_per_partition,sketch_insert_kll_per_partition,sketch_insert_topk_per_shard,sketch_query_theta_union_merge,sketch_query_kll_quantiles_merge,sketch_query_topk_combine,sketch_drop_persistent_table \
  --scale 0.1
```

Pointer to docs:
- [`read_primitives` approximate-aggregate functions](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/read-primitives-approximate-functions.md)
- [`write_primitives` sketch persistence operations](https://github.com/joeharris76/BenchBox/blob/develop/docs/benchmarks/write-primitives-sketch-functions.md)

---

## Required benchmark runs to make the post valuable

The post's claims need supporting numbers from runs that are reproducible with what BenchBox actually has working today (DuckDB SQL + DataFrame engines + chDB local ClickHouse). Cloud verification is deferred until credentials are available.

| # | Run | Platform(s) | Benchmark / queries | Scale | What it shows |
|---|-----|-------------|---------------------|-------|---------------|
| 1 | DuckDB approx vs exact latency | duckdb | `read_primitives` — all 5 approx queries + matched exact counterparts (`aggregation_distinct`, `statistical_percentiles`, …) | SF=1 | Approximate path is materially faster than exact on the same data; concrete numbers anchor the aggregate-latency claim |
| 2 | DuckDB sketch persist+merge cycle | duckdb | `write_primitives` Theta+KLL+Top-K — all 8 ops (DDL → 3 inserts → 3 ★ merges → DROP) | SF=1 | End-to-end persist+merge+requery is working. Note: the catalog's tolerance bounds (e.g. theta merge ∈ [14500, 15500]) are tuned to SF=0.01 (lineitem ~15k orderkeys); SF=1 cardinalities will be ~1.5M distinct and tolerance will need re-tuning before publication |
| 3 | Sketch merge holds across SF | duckdb | `write_primitives` ★ merge ops (`sketch_query_*_merge`) only | SF=0.1, 1, 10 | Merge latency stays roughly constant while exact-aggregate latency grows with cardinality — the "millisecond merge" claim made concrete |
| 4 | DataFrame sketch-backed vs exact-fallback | polars-df, pyspark-df, datafusion-df, pandas-df, dask-df | `read_primitives` — `approx_count_distinct_*` and `approx_quantile_groupby` | SF=0.1 | Sketch-backed engines (Polars HLL, PySpark KLL, DataFusion T-Digest) finish ahead of exact-fallback engines (pandas, Dask groupby) on the same query — surfaces the capability gap that picking pandas hides |
| 5 | ClickHouse-native sketch matrix | chDB (local) | `write_primitives` sketch — all 8 Theta/KLL/Top-K ops via `-State`/`-Merge` overrides | SF=0.1 | ClickHouse 8/8 (post-PR #180) — confirms the persist+merge+requery shape behaves identically under combinator semantics. Companion read_primitives run uses native `uniq` / `quantileTDigest` / `topK` |
| 6 | CPC vs Theta size/latency tradeoff | duckdb | `sketch_cpc_query_union_merge` vs `sketch_query_theta_union_merge` (paired) | SF=0.01, 0.1, 1 | Storage-size validation makes the ~1.2 KB CPC vs ~16 KB Theta delta visible directly; pair latencies show the throughput tradeoff |
| 7 | (Deferred) Cloud verification | snowflake, bigquery, databricks, redshift | `read_primitives` approx queries + `write_primitives` sketch category | SF=0.1 | Validates the published cross-engine matrix end-to-end. Architecture fixes have shipped (PR #176); only blocker is creds. Tracked in `write-primitives-sketch-cloud-verification`. |

Suggested chart types:
- **Run 1**: side-by-side bar — exact-vs-approx latency, one panel per query.
- **Run 2**: stacked bar — phase breakdown (DDL / insert / merge / DDL) per ★ op.
- **Run 3**: line chart — merge latency vs SF on log-scale (showing flat sketch-merge curve next to a notional exact-aggregate growth curve).
- **Run 4**: grouped bar — DataFrame engine × query, color-coded by sketch-backed (saturated) vs exact-fallback (hatched).
- **Run 5**: bar — sketch-merge latency per family on chDB; companion read_primitives bar for `uniq` / `quantileTDigest` / `topK`.
- **Run 6**: dual-axis bar — bytes (left) and ms (right) for CPC vs Theta merge per SF.

All charts ASCII via `benchbox visualize` or the textcharts MCP.

---

## Voice and tone targets

Per the building-benchbox series template:
- Frame as "we noticed the gap and addressed it" not "we caught a flaw" — the L2 audit is presented as the protocol working, not as embarrassment about a near-miss. Equally, do not present it as proof of cleverness — the gap is structural, not a clever catch.
- Neutral on platforms — Redshift's HLL-only ceiling and DataFusion's lack of support are stated as engineering facts, not as platform criticism. Databricks gets credit for the announcement that motivated the work. The Databricks team is a guaranteed reader; framings like "boring half" / "trivial half" / "actually-novel half" trade substance for editorial contrast and read dismissive — substitute "aggregate-latency path" / "persist+merge+requery path" throughout.
- "We" for the project and community (per voice guide rule 1).
- No "industry analyst" framing — share findings, don't pronounce judgments (per voice guide rule 5).
- Acknowledge limitations explicitly (voice guide rule 3): cloud verification is deferred; approximation-quality vs latency isn't tested; cross-engine portability isn't tested.

## Anti-patterns to actively avoid

- **Press-release TL;DR**: don't use "Databricks promised X but BenchBox delivered Y" framing. Databricks' announcement is credited as the motivating context, not contrasted against.
- **Function-name list dump**: the cross-engine matrices already exist in the docs; the blog post should compress them, not duplicate them in full.
- **"In our next post…"**: end with a CTA to the docs and the GitHub repo, not a series footer cliffhanger. Section 4's pattern-repeats closer should be an open observation, not a forecast of the next post.
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
- `_project/DONE/main/planning/write-primitives-architecture-fixes.yaml` — `validation_query.platform_overrides` + `AGGREGATE_PERSIST/MERGE` op types
- `_project/DONE/main/planning/write-primitives-sketch-clickhouse-and-storage-metrics.yaml` — ClickHouse 8/8 + storage-size validation
- `_project/DONE/main/planning/write-primitives-sketch-duckdb-cpc-req-families.yaml` — DuckDB CPC + REQ
- `_project/blind-spots/2026-05-02-084332-read-primitives-cant-test-sketch-persistence.md` — the framework-gap finding (this is the L2 audit insight to feature)
- `_project/blind-spots/2026-05-02-155448-validation-query-no-per-platform-override.md` — architectural gap surfaced + resolved
- `_project/blind-spots/2026-05-02-155524-duckdb-datasketches-extension-drift.md` — extension-drift caveat
- `_project/blind-spots/2026-05-02-163132-write-primitives-dataframe-execution-model-no-sketch-shape.md` — DataFrame op-shape gap + resolved
- `_project/blind-spots/2026-05-04-113747-blog-critique-currency-and-partisan-reader-axes.md` — rubric gap surfaced during this outline review
- `docs/benchmarks/read-primitives-approximate-functions.md` — public per-engine reference
- `docs/benchmarks/write-primitives-sketch-functions.md` — public per-engine reference

### Recent shipped work (commits to mention)
- PR #112 — sketch persistence + read_primitives approximate-aggregates landed together
- PR #114 — runtime bound enforcement + Snowflake/BigQuery overrides
- PR #134 — Redshift HLL-only coverage
- PR #135 — DataFrame approx_count_distinct + sketch-backed quantile coverage
- PR #176 — `validation_query.platform_overrides` + `AGGREGATE_PERSIST` / `AGGREGATE_MERGE` DataFrame op types (architecture fixes)
- PR #180 — ClickHouse 8/8 sketch coverage + storage-size validation
- PR #182 — DuckDB CPC + REQ sketch families

### Remaining deferrals (foreground briefly; don't dwell)
- `write-primitives-sketch-cloud-verification` — needs Snowflake / BigQuery / Databricks / Redshift creds (architecture-side blockers cleared in PR #176)
- `write-primitives-sketch-pyspark-dataframe-surface` — PySpark DataFrame sketch persist+merge ops
- `write-primitives-sketch-parameter-sweeps` — `lg_k` / `k` / `lg_max_map_size` parameter axis

---

## Outline status

- **Length target**: ~2,300-2,500 words (sits inside the 1,500-2,500 envelope; the cross-engine matrices push toward the upper end).
- **Conflicts checked**: no overlap with any planned outline. Posts #1-11 are unrelated topics. The benchbox-in-action series is methodology-driven (no overlap with this engineering-decision framing).
- **Next step**: gather the 6 in-scope benchmark runs (DuckDB approx-vs-exact, DuckDB sketch full cycle, multi-SF sketch merge, DataFrame matrix, chDB ClickHouse 8/8, CPC-vs-Theta size/latency) and slot the actual numbers in before drafting. Cloud verification stays deferred and is called out as a follow-up.
- **Series-plan update**: row #12 added.
- **Publication timing**: vendor-response posts have a 1-2 week shelf life; aim to draft and publish soon after the 6 runs land.

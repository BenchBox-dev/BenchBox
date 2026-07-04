# Spark Adaptive Query Execution: Claim Verification

> Evidence log for the platform-deep-dive post on Apache Spark's Adaptive Query
> Execution (AQE): what the three GA features do, why Spark's stage-boundary
> execution model makes runtime re-optimization practical there specifically, and
> how other engines approach the same class of problem (re-optimization under bad
> cardinality estimates and data skew). Every claim in the outline and eventual
> draft must trace to a dated entry here. BenchBox first-party source findings and
> external documentation claims are kept strictly separate and labeled with their
> real verification confidence.

## Objective

Ground the post in three tiers of evidence:

1. First-party: BenchBox source code, verified by reading the files at the cited
   commit (no external footnote needed, file and line cited instead).
2. Primary-source verified: verbatim quotes fetched directly from official
   documentation, with access dates.
3. Search-derived: claims where the primary page could not be fetched from this
   session's network environment. These are labeled "as reported by search
   summary, not diffed against the live page" and carry lower confidence. None of
   them are presented in quotation marks as verbatim text.

No BenchBox benchmark runs were performed for this research. No performance
result in this file or in the outline is a BenchBox result. The only performance
figures cited are Databricks' own published TPC-DS numbers, attributed to
Databricks.

## Dates and Network Environment

- Research access date: 2026-07-04 (all fetch and search attempts below).
- BenchBox source verified at commit `5fe58367` (tip of `develop`, 2026-07-04).
- Network constraint: direct fetches to spark.apache.org, databricks.com,
  docs.oracle.com, learn.microsoft.com, trino.io, trinodb.github.io,
  docs.snowflake.com, cloud.google.com, and cs.cmu.edu all returned HTTP 403
  from this session's egress policy (gateway CONNECT denial). The official
  Apache documentation mirrors at downloads.apache.org and archive.apache.org
  WERE reachable, so all Spark documentation quotes below are verbatim from
  official Apache-hosted copies. Everything else fell back to web search and is
  labeled accordingly.

---

## Part A: Spark AQE from official Apache documentation (verified, 2026-07-04)

Quotes in this part are verbatim from official Apache mirror copies of the Spark
documentation (downloads.apache.org and archive.apache.org host the same doc
bundles that spark.apache.org serves). Confidence: high, primary source.

### A1. What AQE is, and enabled by default since Spark 3.2.0

- Source: <https://downloads.apache.org/spark/docs/3.2.0/sql-performance-tuning.html>
  (official Apache mirror of the Spark 3.2.0 docs), fetched 2026-07-04.
- Verbatim: "Adaptive Query Execution (AQE) is an optimization technique in
  Spark SQL that makes use of the runtime statistics to choose the most
  efficient query execution plan, which is enabled by default since Apache
  Spark 3.2.0."
- The umbrella configuration is `spark.sql.adaptive.enabled` (default `true`
  since 3.2.0; AQE shipped GA but default-off in Spark 3.0.x and 3.1.x).
- The docs list three major features: coalescing post-shuffle partitions,
  converting sort-merge join to broadcast join, and skew join optimization.

### A2. Dynamic partition coalescing

- Source: same 3.2.0 page as A1, plus
  <https://archive.apache.org/dist/spark/docs/3.5.1/sql-performance-tuning.html>
  (official Apache archive of the Spark 3.5.1 docs), both fetched 2026-07-04.
- Verbatim (3.2.0): "This feature coalesces the post shuffle partitions based
  on the map output statistics when both spark.sql.adaptive.enabled and
  spark.sql.adaptive.coalescePartitions.enabled configurations are true."
- `spark.sql.adaptive.coalescePartitions.enabled` default: `true`.
- `spark.sql.adaptive.advisoryPartitionSizeInBytes` default: 64 MB (3.5.1 docs).

### A3. Sort-merge join to broadcast join conversion

- Source: 3.5.1 archive page as in A2, fetched 2026-07-04.
- Verbatim: "AQE converts sort-merge join to broadcast hash join when the
  runtime statistics of any join side is smaller than the adaptive broadcast
  hash join threshold."
- `spark.sql.adaptive.autoBroadcastJoinThreshold` default: "(none)", falling
  back to `spark.sql.autoBroadcastJoinThreshold`.
- Verbatim (local shuffle reader, same page): "Spark tries to use local shuffle
  reader to read the shuffle data when the shuffle partitioning is not needed"
  (`spark.sql.adaptive.localShuffleReader.enabled`, default `true`). This is
  the mitigation for the fact that the shuffle map side has already run by the
  time the join strategy is switched.

### A4. Skew join splitting

- Source: 3.2.0 mirror page (A1) and 3.5.1 archive page (A2), fetched 2026-07-04.
- Verbatim (3.2.0): "This feature dynamically handles skew in sort-merge join by
  splitting (and replicating if needed) skewed tasks into roughly evenly sized
  tasks. It takes effect when both spark.sql.adaptive.enabled and
  spark.sql.adaptive.skewJoin.enabled configurations are enabled."
- Defaults (3.5.1 config table): `spark.sql.adaptive.skewJoin.enabled` = `true`,
  `spark.sql.adaptive.skewJoin.skewedPartitionFactor` = 5.0,
  `spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes` = 256 MB,
  `spark.sql.adaptive.forceOptimizeSkewedJoin` = `false`.
- A partition is treated as skewed when it is both larger than the median
  partition size times the skew factor and larger than the absolute threshold
  (both conditions, per the config descriptions on the same page).

### A5. Spark 3.0 release framing and headline numbers

- Provenance: SEARCH-DERIVED. spark.apache.org returned HTTP 403; the release
  notes page (<https://spark.apache.org/releases/spark-release-3-0-0.html>) could
  not be fetched. As reported by search summary, not diffed against the live
  page. Confidence: medium; consistent across multiple independent results.
- As reported: AQE is one of the headline features of Spark 3.0 (2020), and the
  Spark 3.0 announcement material describes roughly 2x speedup over Spark 2.4
  on a TPC-DS 30TB benchmark for the release overall (not AQE alone).
- Draft handling: attribute the 2x figure to the Spark 3.0 announcement, note
  it covers the whole release, and do not present it as an AQE-only or
  BenchBox-measured number.

### A6. Databricks' AQE explanation and TPC-DS figures

- Provenance: SEARCH-DERIVED. databricks.com returned HTTP 403. Source page:
  "Adaptive Query Execution: Speeding Up Spark SQL at Runtime", Databricks
  blog, 2020-05-29,
  <https://www.databricks.com/blog/2020/05/29/adaptive-query-execution-speeding-up-spark-sql-at-runtime.html>.
  As reported by search summary, not diffed against the live page. Confidence:
  medium-high; the mechanism description matches the Apache docs (Part A1-A4)
  and the figures are widely and consistently reproduced.
- Mechanism, as reported: a shuffle or broadcast exchange breaks the operator
  pipeline; the blog calls these "materialization points" and uses "query
  stages" for the plan subsections bounded by them. When a stage finishes
  materializing, AQE updates the logical plan with runtime statistics, re-runs
  the optimizer with adaptive-execution rules, and then executes whichever new
  stages have all child stages materialized, repeating execute-reoptimize-execute
  until the query completes.
- Performance figures, as reported and ATTRIBUTED TO DATABRICKS (not BenchBox):
  on a 1TB TPC-DS benchmark run without pre-collected statistics, Databricks
  reported AQE giving about 8x on q77, about 2x on q5, and more than 1.1x on
  another 26 queries.
- Draft handling: every use of these numbers names Databricks as the source and
  states the no-statistics setup, since that setup is favorable to a runtime
  re-optimizer by construction.

---

## Part B: BenchBox first-party source verification (2026-07-04, commit 5fe58367)

Verified by reading the source files directly. No external citation needed;
cite file and line in the draft.

### B1. BenchBox enables all three AQE features for Spark by default

- `benchbox/platforms/spark.py:235`: `adaptive_enabled` defaults to `True`.
- `benchbox/platforms/spark.py:439-443`: when enabled, the session conf sets
  `spark.sql.adaptive.enabled`, `spark.sql.adaptive.coalescePartitions.enabled`,
  and `spark.sql.adaptive.skewJoin.enabled` to `"true"`.

### B2. The `--adaptive-enabled` CLI flag can never disable AQE

- `benchbox/platforms/spark.py:300`: the flag is declared
  `action="store_true", default=True`. Passing `--adaptive-enabled` sets `True`;
  omitting it leaves the default `True`. There is no CLI spelling that produces
  `False`. Disabling AQE from the command line is therefore not currently
  possible; it requires the Python API (`adaptive_enabled=False`) or a
  `spark_config` override.

### B3. `spark_config` merges last at session build time

- `benchbox/platforms/spark.py:486`: `conf.update(self.spark_config)` is the
  final step of `_get_spark_conf`, so user-provided keys (for example
  `spark.sql.adaptive.enabled: "false"`) override the adapter's defaults in the
  SparkSession builder configuration.

### B4. But `configure_for_benchmark` re-enables AQE for OLAP benchmarks at run time

- `benchbox/platforms/spark.py:653-669`: for benchmark types `olap`,
  `analytics`, `tpch`, `tpcds`, and `joinorder`, the adapter calls
  `spark.conf.set("spark.sql.adaptive.enabled", "true")` (plus the coalesce and
  skew-join keys) on the live session.
- `benchbox/platforms/base/adapter.py:493-494`: `run_benchmark` calls
  `configure_for_benchmark` before query execution, with `benchmark_type`
  defaulting to `"olap"`.
- Net effect: in the standard `benchbox run` pipeline, a session-level AQE
  disable (via B3) is overwritten before queries execute. A true AQE-off
  comparison run through the CLI pipeline currently requires a code change, not
  just configuration. The draft states this plainly as a harness limitation we
  found while researching the post, and the planned methodology (Part D of the
  outline) lists fixing it as a prerequisite.

### B5. TPC-H Skew presets

- `benchbox/core/tpch_skew/skew_config.py:29-37`: presets `none` (uniform),
  `light` (z=0.2), `moderate` (z=0.5, the `SkewConfiguration` default at
  line 146), `heavy` (z=0.8), `extreme` (z=1.0, Zipf's law), and `realistic`
  (e-commerce pattern, skew factor 0.6).
- `benchbox/core/tpch_skew/skew_config.py:74-100`: join skew configuration
  covers exactly the relationships that stress skewed joins:
  customer-to-orders, part-to-lineitem, supplier-to-lineitem, and
  lineitem-per-order variance.
- Zipfian distribution is the default generator (`distribution_type="zipfian"`,
  line 149).

### B6. Skew preset selection from the CLI

- `benchbox/cli/commands/run.py:2679`: `--benchmark-option skew_preset=heavy`
  is the documented CLI path for `tpch_skew`.
- `benchbox/tpch_skew.py:73-104`: the `TPCHSkew` benchmark accepts
  `skew_preset` directly in the Python API.

### B7. Plan capture eligibility

- `benchbox/platforms/spark.py:199`: `plan_capture_phase_eligible = True`. The
  Spark adapter participates in BenchBox's plan capture phase, which is the
  hook a future AQE post could use to show `EXPLAIN`-level plan differences
  (initial vs adaptively re-optimized plan) rather than timings alone.
- CORRECTION (2026-07-04, post-merge review on PR #954, fixed in the outline
  by PR #955): the capture hook is `get_spark_query_plan`
  (`benchbox/platforms/_spark_helpers.py:112-131`), which runs a fresh
  `EXPLAIN EXTENDED <query>`. That returns the static, pre-adaptive compile
  plan, not the executed plan with AQE's runtime decisions applied, so plan
  capture as it stands can show AQE-on vs AQE-off differences in the initial
  plan only. Showing the actual switched join operators and coalesced
  partition counts requires capturing the final adaptive plan (Spark event
  logs or the post-execution `executedPlan`), which is follow-up work, not
  an existing capability. The original expectation in the entry above is
  retained for the record; the outline's section 5/6 wording was corrected
  accordingly.

---

## Part C: Other engines (search-derived unless noted, 2026-07-04)

Direct fetches to every vendor documentation site in this part returned HTTP
403 (see Dates and Network Environment). All entries below are therefore
labeled: as reported by search summary, not diffed against the live page.
Claims that conflicted with better-established sources were dropped, and one
known search-summarizer artifact is flagged in C4.

### C1. Oracle Database: Adaptive Query Optimization (12c and later)

- Intended primary sources: Oracle Database SQL Tuning Guide, "Adaptive Query
  Optimization" chapter (docs.oracle.com), and the Oracle Optimizer team blog.
  Confidence: medium-high; the mechanism is consistently described across
  Oracle's own tuning guide summaries, oracle-base.com, and multiple
  practitioner writeups.
- As reported: an adaptive plan contains a default plan plus predetermined
  alternative subplans, with an "optimizer statistics collector" row source
  inserted at key points. During the first execution, the collector buffers
  rows and counts cardinality; if the actual row count crosses an inflection
  point, execution switches to the alternative subplan (the canonical example
  is nested loops switching to hash join). Once the choice is made, the
  collector stops buffering and the decision sticks for subsequent executions.
- Architectural contrast for the draft: the adaptation happens inside a single
  running rowsource tree, choosing among precompiled alternatives for specific
  operators. It does not re-run the whole optimizer mid-query the way AQE
  re-optimizes at stage boundaries. Related 12c features (statistics feedback,
  SQL plan directives) adapt future executions rather than the current one.

### C2. Microsoft SQL Server: Intelligent Query Processing and Batch Mode Adaptive Joins

- Intended primary sources: learn.microsoft.com "Intelligent query processing"
  and "Understanding Adaptive joins" pages, and the Microsoft SQL Server blog
  post "Enhancing query performance with Adaptive Query Processing in SQL
  Server 2017" (2017-09-28). Confidence: medium-high; consistent across
  Microsoft's own blog, Microsoft Learn summaries, and SQLPerformance.com.
- As reported: batch mode adaptive joins shipped in SQL Server 2017 (database
  compatibility level 140). The adaptive join operator defers the choice
  between a hash join and a nested loops join until after the first (build)
  input has been scanned; the optimizer computes a row-count threshold from the
  crossover point of the two alternatives' costs, and at run time the actual
  build-side row count picks the algorithm. Batch mode originally required a
  columnstore index; SQL Server 2019 added batch mode on rowstore. The wider
  IQP family also includes memory grant feedback (right-sizing grants between
  executions) and interleaved execution for multi-statement table-valued
  functions (pausing optimization to get a real cardinality, then resuming).
- Architectural contrast for the draft: like Oracle, this is operator-level
  adaptation between precompiled alternatives inside one plan, plus
  between-execution feedback. There is no mid-query global re-optimization
  step, and in a non-staged pipelined executor there is no natural point where
  the full intermediate result is materialized and can be re-planned around.

### C3. Trino: adaptive plan optimizations, gated behind fault-tolerant execution

- Intended primary sources: trino.io/docs/current/optimizer/adaptive-plan-optimizations.html
  and trino.io/docs/current/admin/fault-tolerant-execution.html. Confidence:
  medium-high; the docs pages are directly indexed and their summaries agree
  with the Trino project's own episode notes and GitHub issues.
- As reported: Trino's adaptive plan optimizations adjust plans during
  execution based on runtime statistics, and they are only available when
  fault-tolerant execution (FTE) is enabled; the umbrella switch is
  `fault-tolerant-execution-adaptive-query-planning-enabled`. Documented
  optimizations include adaptive join reordering (swapping build and probe
  sides based on actual input sizes, useful when table statistics are missing)
  and adaptive partitioning adjustments. FTE works by spooling intermediate
  exchange data through an exchange manager so tasks can be retried.
- Architectural contrast for the draft: this is the strongest supporting
  evidence for the stage-boundary thesis. Trino's default pipelined,
  all-stages-running-at-once executor streams data between stages and has no
  materialization point to re-plan at. Turning on FTE makes exchanges spooled
  and stage-like, and exactly then runtime re-optimization becomes available.
  The capability follows the execution model, in both directions.

### C4. Snowflake: cost-based optimization, decisions postponed but not re-planned mid-query

- Intended primary source: "The Snowflake Elastic Data Warehouse", SIGMOD 2016
  (dl.acm.org/doi/10.1145/2882903.2903741). Confidence: medium-high for the
  paper's optimizer description; the same sentences are quoted consistently
  across multiple independent summaries.
- As reported from the paper: Snowflake's optimizer is built on a
  Cascades-style approach with top-down cost-based optimization; statistics
  are automatically maintained on load and update; and the plan search space
  is reduced by postponing many decisions until execution time, for example
  the type of data distribution for joins.
- FLAGGED ARTIFACT (do not use): a prior research pass surfaced a search
  result claiming "Snowflake uses a rule-based query optimizer." This
  contradicts the SIGMOD paper's cost-based description and is treated as a
  search-summarizer artifact. It does not appear in the outline or draft.
- Architectural contrast for the draft: Snowflake reduces its exposure to bad
  compile-time estimates by keeping fresh metadata (per-micro-partition
  min/max and distinct-value metadata drives aggressive pruning) and by
  deferring some physical decisions into the execution layer, rather than by
  re-invoking the optimizer at runtime. Frame as a different architectural
  answer to the same estimation problem, not as an absence.

### C5. Google BigQuery: dynamic plan adjustment during execution

- Intended primary source: cloud.google.com/bigquery/docs/query-plan-explanation
  ("Query plan and timeline") and the Google Cloud blog "BigQuery Admin
  reference guide: Query processing". Confidence: medium-high; Google's own
  docs summaries are explicit.
- As reported: BigQuery can modify the query plan while a query is running.
  The engine introduces repartition and coalesce stages dynamically to
  rebalance data distribution across workers; these runtime-inserted stages
  are hidden from the displayed plan. Stages communicate through a distributed
  in-memory shuffle tier.
- IMPORTANT CORRECTION TO THE POST'S STARTING FRAME: the original framing
  grouped BigQuery with "compile-time optimization plus elastic scale." That
  is not accurate per Google's own documentation: BigQuery does adapt its plan
  at runtime, specifically around shuffle boundaries, much like Spark's
  coalescing. The outline places BigQuery in the "adapts at shuffle
  boundaries" group and reserves the compile-time-plus-metadata framing for
  Snowflake (which the SIGMOD paper supports). The honest generalization is:
  engines with a materializing or spooling shuffle tier (Spark, BigQuery,
  Trino under FTE) adapt between stages; engines without one adapt inside
  operators or not at all.

### C6. DuckDB: no shuffle boundary to re-optimize at

- Intended primary sources: DuckDB documentation and the DuckDB team's
  published execution-model material. Confidence: medium-high; consistent
  across the project's own docs and multiple independent architecture
  writeups.
- As reported: DuckDB is an in-process, single-node engine using vectorized
  execution (roughly 2,048-value vectors), push-based pipelines, and
  morsel-driven parallelism, parallelizing one pipeline at a time across
  threads. There is no distributed shuffle: pipeline breakers (hash tables for
  joins and aggregates) live in shared memory.
- Architectural contrast for the draft: the entire problem AQE solves at the
  200-partition shuffle boundary (wrong partition counts, stragglers from
  skewed partitions, choosing distributed join strategies) does not exist in
  the same form. Skew still affects hash-table build sizes and thread load
  balance, but morsel-driven scheduling absorbs much of it at a different
  granularity. Do not claim DuckDB "cannot" adapt; claim the stage-boundary
  adaptation point does not exist in its model.

### C7. ClickHouse: local runtime adaptivity inside operators

- Intended primary source: the ClickHouse architecture overview
  (clickhouse.com/docs/academic_overview, which mirrors the VLDB 2024 paper
  "ClickHouse - Lightning Fast Analytics for Everyone"). Confidence: medium;
  as reported by search summary.
- As reported: ClickHouse uses vectorized execution in the MonetDB/X100
  lineage, processing chunks of roughly 1,024 to 4,096 values, with
  multi-threaded parallelism on each server. Its plan operators can create
  other operators at run time, primarily to switch to external (spilling)
  aggregation or join implementations based on memory consumption.
- Architectural contrast for the draft: this is runtime adaptivity, but of a
  local, resource-driven kind (switch this operator's implementation when
  memory runs out), not cardinality-driven re-planning of downstream joins.
  Same neutral framing as DuckDB: a different execution model puts the
  adaptation point somewhere else.

---

## Part D: Cross-check (outline claim to evidence)

- Claim: "AQE re-optimizes using runtime statistics and is enabled by default
  since Spark 3.2.0." Evidence: A1 (verbatim, official mirror).
- Claim: "The three GA features are partition coalescing, sort-merge-to-broadcast
  join switching, and skew-join splitting, with defaults 64MB advisory
  partitions, 5.0 skew factor, 256MB skew threshold." Evidence: A2, A3, A4
  (verbatim, official mirror).
- Claim: "Shuffle and broadcast exchanges are materialization points; AQE
  re-plans when stages finish materializing." Evidence: A6 (search-derived,
  attributed to Databricks; mechanism corroborated by A1-A4).
- Claim: "Databricks reported 8x on q77, 2x on q5, and more than 1.1x on 26
  more queries, TPC-DS 1TB without statistics." Evidence: A6 (search-derived,
  attributed to Databricks; never presented as a BenchBox result).
- Claim: "BenchBox enables AQE for Spark by default; the CLI flag cannot
  disable it; run-time benchmark configuration re-enables it for OLAP
  benchmarks." Evidence: B1, B2, B3, B4 (first-party, file:line).
- Claim: "BenchBox's TPC-H Skew benchmark generates Zipfian join skew with
  presets from light (z=0.2) to extreme (z=1.0)." Evidence: B5, B6
  (first-party).
- Claim: "Oracle adapts by switching among precompiled subplans via a
  statistics collector; SQL Server defers the join algorithm choice behind a
  row-count threshold." Evidence: C1, C2 (search-derived).
- Claim: "Trino's adaptive optimizations exist only under fault-tolerant
  execution, which spools exchange data." Evidence: C3 (search-derived).
- Claim: "Snowflake is Cascades-style cost-based and postpones some physical
  decisions to execution time." Evidence: C4 (search-derived from the SIGMOD
  2016 paper).
- Claim: "BigQuery modifies plans during execution by inserting repartition
  and coalesce stages." Evidence: C5 (search-derived from Google's docs).
- Claim: "DuckDB and ClickHouse have no distributed shuffle boundary; their
  adaptivity is operator-local (memory-driven switching in ClickHouse,
  morsel-level load balancing in DuckDB)." Evidence: C6, C7 (search-derived).

## Limitations of this evidence

- No BenchBox benchmark was run. The outline's results-oriented section is a
  planned methodology only, and the draft must keep it in the future tense
  until runs exist.
- Every non-Spark vendor claim in Part C is search-derived because this
  session's network policy blocked direct fetches to the primary pages. Before
  the draft is published, each Part C quote-level claim should be re-verified
  against the live page from an environment that can reach it, and the
  provenance labels upgraded or the claims softened accordingly.
- The Spark documentation quotes are from the 3.2.0 and 3.5.1 doc bundles on
  official Apache mirrors, not from the current 4.x docs page (blocked). The
  quoted sentences and defaults should be spot-checked against the latest docs
  before publication in case defaults changed after 3.5.x.
- The Databricks TPC-DS figures date from 2020, describe a deliberately
  statistics-free setup, and are Databricks' own numbers; they characterize
  the opportunity AQE targets, not what any current reader should expect on
  their workload.

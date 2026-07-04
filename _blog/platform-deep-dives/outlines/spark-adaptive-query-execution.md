# Outline: Spark Adaptive Query Execution and the Stage-Boundary Advantage

**Post type:** Platform deep-dive / architecture (execution models, not platform verdicts).
**Target length:** 2,000-2,500 words.
**Editorial angle:** Not "Spark solved re-optimization and others have not."
Thesis: every engine faces the same problem (cardinality estimates go wrong,
data is skewed), and where an engine can adapt is determined by its execution
model, not by how advanced it is. Spark's blocking shuffle gives it a natural
mid-query re-optimization point, and AQE is the direct exploitation of that
point. Engines with pipelined executors adapt inside operators (Oracle, SQL
Server, ClickHouse), engines that add a spooling shuffle gain stage-level
adaptation exactly when they add it (Trino under fault-tolerant execution,
BigQuery), and single-node engines have no shuffle boundary for this problem to
live at (DuckDB). Architectural fit, not maturity.

**Evidence source:** `_blog/platform-deep-dives/research/spark-aqe-verification-2026-07-04.md`.
Every external claim cites a dated entry there, with its real provenance
(verbatim from official Apache mirrors vs search-derived, labeled). BenchBox
source findings cite file and line. No BenchBox benchmark run is claimed
anywhere: the performance figures quoted are Databricks' own published TPC-DS
numbers, attributed to Databricks, and the BenchBox measurement plan is written
explicitly as future work.

**Voice reminders:** "we", neutral on platforms, architectural fit not
maturity, data over superlatives, no em-dashes or en-dashes, define terms on
first use, footnote external facts, cite BenchBox source as file:line.

## Title + frontmatter

- Title (< 60 chars): "Spark AQE: Re-Optimizing Queries at Stage Boundaries"
- One-sentence summary: how Spark re-plans queries mid-flight, why its
  execution model makes that practical, and how other engines answer the same
  problem differently.
- TL;DR (2-3 sentences): optimizers guess cardinalities before execution and
  the guesses are often wrong. Spark's shuffle boundaries fully materialize
  intermediate results, so AQE can re-plan with exact sizes between stages.
  Other engines adapt too, but at the points their own execution models make
  available.
- meta_description (150-160 chars); tags: spark, adaptive-query-execution,
  query-optimization, data-skew, tpch-skew, benchmarking, architecture,
  execution-models.

## 1. Introduction (200-300 words)

- The hook: the optimizer's oldest problem. Cost-based optimizers pick plans
  from estimated cardinalities; estimates compound badly across joins, and a
  wrong join strategy or partition count is locked in before the first row
  moves. Define cardinality estimation in one parenthetical.
- The question we explore: what does it take, architecturally, to change your
  mind mid-query? Spark's AQE (GA in Spark 3.0, on by default since 3.2.0,
  research file A1) is the best-known answer; it is not the only one.
- Scope statement: this is an architecture post. We compare adaptation
  mechanisms, not engine performance. No BenchBox timings are claimed; we close
  with the measurement plan we intend to run.

## 2. What AQE actually does (450-550 words)

- 2a. The re-optimization loop. Shuffle and broadcast exchanges break the
  operator pipeline; Databricks calls these materialization points, and query
  stages are the plan sections between them. When a stage finishes, AQE feeds
  exact output statistics back into the logical plan, re-runs the optimizer,
  and launches whichever stages are now ready (A6, labeled as Databricks'
  description). Execute, re-optimize, execute.
- 2b. Feature 1: dynamic partition coalescing. The fixed
  `spark.sql.shuffle.partitions` (default 200) problem: too many small tasks
  for small intermediates, scheduling overhead. AQE merges post-shuffle
  partitions toward `advisoryPartitionSizeInBytes` (64 MB default) using map
  output statistics (A2).
- 2c. Feature 2: sort-merge join to broadcast join switching. If a join side
  turns out smaller than the adaptive broadcast threshold at run time, AQE
  swaps in a broadcast hash join; the local shuffle reader mitigates the
  already-paid shuffle write cost (A3, verbatim quote available).
- 2d. Feature 3: skew join splitting. A partition counts as skewed when it
  exceeds both 5x the median partition size and 256 MB (defaults); AQE splits
  the oversized partition into subpartitions and replicates the matching build
  side so the straggler becomes several evenly sized tasks (A4).
- 2e. What it bought, per Databricks: 8x on TPC-DS q77, 2x on q5, more than
  1.1x on 26 further queries at 1TB with statistics collection disabled.
  Attribute clearly to Databricks, note the no-statistics setup is the
  best-case scenario for a runtime re-optimizer, and note the Spark 3.0
  release's overall 2x TPC-DS claim covers the whole release, not AQE alone
  (A5, A6; both search-derived, labeled).

## 3. Why the stage boundary makes it practical (350-450 words)

- The load-bearing architectural fact: Spark's shuffle is blocking. The map
  side of an exchange runs to completion and materializes its output before
  the reduce side starts. That gives the scheduler (a) a natural pause point
  where nothing downstream has started, and (b) exact statistics (per-partition
  sizes from the map output) instead of estimates.
- Re-optimizing here is cheap and safe: no running operators to unwind, no
  partial results to discard. The plan for completed stages is frozen; only
  the not-yet-started remainder is re-planned (A6 mechanism description).
- The general principle we will reuse for every other engine: runtime
  adaptation needs a point where (1) accurate statistics exist and (2)
  changing course is cheap. Execution models differ mainly in where, and
  whether, such points exist.
- Honest cost note: the same blocking materialization that enables AQE is
  overhead a fully pipelined engine avoids; stage boundaries are a trade, not
  a free lunch. This keeps the comparison symmetric and neutral.

## 4. The same problem, other execution models (600-750 words)

Framing sentence up front: every engine below confronts misestimated
cardinalities and skew; each adapts where its execution model gives it a
foothold. Survey order groups by mechanism, not by vendor ranking.

- 4a. Operator-level adaptation inside a pipelined plan.
  <!-- content-ok: restricted_vendor -->
  - Oracle Database (12c+ Adaptive Query Optimization): adaptive plans embed a
    default subplan, precompiled alternatives, and a statistics collector row
    source that buffers rows during first execution; cross the row-count
    inflection point and the operator switches (nested loops to hash join is
    the canonical case), then the decision sticks (C1).
  - SQL Server (Intelligent Query Processing): batch mode adaptive joins
    (2017, compatibility level 140) defer the hash-vs-nested-loops choice
    until the build input has been scanned, comparing actual rows to a
    precomputed threshold; the IQP family adds between-execution feedback
    (memory grants) and interleaved execution for multi-statement
    table-valued functions (C2).
  - Common shape: choose among precompiled alternatives at specific operators
    while the plan runs. Fits a pipelined, single-system executor where a full
    stop-and-replan point does not exist.
- 4b. Stage-level adaptation where a materializing shuffle exists.
  - Trino: adaptive plan optimizations (adaptive join reordering, adaptive
    partitioning) exist only when fault-tolerant execution is enabled, which
    spools intermediate exchange data through an exchange manager. Trino's
    default executor pipelines all stages concurrently and streams exchanges,
    so there is nothing to re-plan around; add spooled exchanges and the
    adaptation point appears. Strongest single piece of evidence for the
    thesis (C3).
  - BigQuery: Google's docs state the plan can be modified while the query
    runs; repartition and coalesce stages are inserted dynamically around the
    in-memory shuffle tier and hidden from the displayed plan (C5). Note
    explicitly that this corrects a common framing of BigQuery as purely
    compile-time (our research file logs the correction).
- 4c. Reducing the need instead: Snowflake. Cascades-style top-down
  cost-based optimization over automatically maintained metadata; the SIGMOD
  2016 paper describes deliberately postponing some decisions (join data
  distribution type) to execution time and leaning on per-micro-partition
  metadata for aggressive pruning (C4). Frame precisely: a different
  architectural answer (keep estimates from mattering as much) rather than a
  missing feature. Also note our research file flags and discards a search
  artifact claiming Snowflake is rule-based.
- 4d. No shuffle boundary at all: single-node engines.
  - DuckDB: push-based vectorized pipelines with morsel-driven parallelism;
    pipeline breakers are shared-memory hash tables, not a distributed
    shuffle. The 200-partitions problem does not exist; skew shows up as
    thread load imbalance, absorbed at morsel granularity (C6).
  - ClickHouse: vectorized execution; plan operators can swap themselves for
    external (spilling) variants at run time based on memory pressure.
    Runtime adaptivity exists, but it is resource-driven and operator-local,
    not cardinality-driven re-planning (C7).
- 4e. One-paragraph synthesis table (mechanism, trigger, granularity, when it
  can act) with no winner column.

## 5. What we found wiring AQE into BenchBox (250-350 words)

First-party section, all file:line citations, no external footnotes.

- BenchBox's Spark adapter enables all three AQE features by default
  (`benchbox/platforms/spark.py:439-443`), matching upstream defaults.
- Honest harness findings from this research (stated as bugs/limitations we
  intend to fix, in the technical-challenge voice):
  - The `--adaptive-enabled` CLI flag is `action="store_true", default=True`
    (`spark.py:300`), so the command line can enable AQE but never disable it.
  - A `spark_config` override can turn AQE off at session build time because
    user config merges last (`spark.py:486`), but `configure_for_benchmark`
    re-enables AQE on the live session for OLAP benchmark types before
    queries run (`spark.py:653-669`, called from
    `benchbox/platforms/base/adapter.py:493-494`). A clean AQE-off run
    through `benchbox run` therefore currently requires a code change.
  - Fixing both is the prerequisite for the measurement plan below; tracked
    as a TODO.
- The asset side: the TPC-H Skew benchmark generates Zipfian skew with
  presets `none` through `extreme` (z=0.2 to z=1.0)
  (`benchbox/core/tpch_skew/skew_config.py:29-37`), selectable via
  `--benchmark-option skew_preset=heavy`, and its join-skew knobs target
  exactly the relationships skew-join splitting exists for
  (`skew_config.py:74-100`). The Spark adapter is plan-capture eligible
  (`spark.py:199`), so a static plan is capturable for both AQE on/off runs --
  but `get_query_plan()` delegates to `get_spark_query_plan()`
  (`_spark_helpers.py:113`), which runs a fresh `EXPLAIN EXTENDED <query>`
  after measurement, not the measured query's actual executed/adaptive plan.
  That captures the pre-adaptive plan shape, not runtime AQE decisions
  (switched join strategy, coalesced partition counts) -- those require
  Spark's final/executed-plan or event-log capture, which BenchBox does not
  currently do. Correct this in section 6's deliverable framing.

## 6. Planned methodology: measuring AQE with BenchBox (300-400 words)

Written entirely in the future tense. Nothing here has been run; say so in the
first sentence and again in Limitations.

- Design: AQE on vs AQE off (after the harness fix), same hardware, same data,
  cold cache, median of 5, plan capture enabled for both runs.
- Skew axis: TPC-H Skew at SF10, presets `none`, `moderate`, `heavy`,
  `extreme`. Candidate queries for skew-join splitting: Q21 and Q9 (largest
  multi-way joins over lineitem, where Zipfian supplier and part skew
  concentrates).
- Join-strategy axis: Q5, Q7, Q8 (join trees where a filtered dimension side
  can shrink below the broadcast threshold at run time).
- Coalescing axis: Q3, Q5, Q7, Q18 with deliberately oversized
  `spark.sql.shuffle.partitions` to give coalescing room to act.
- Negative control: uniform SF10 (preset `none`), where we expect AQE close to
  neutral; a large win there would indicate a methodology problem, not an AQE
  win. State this expectation up front as falsifiable.
- Deliverable: timings for every axis, plus BenchBox's captured static
  `EXPLAIN EXTENDED` plan diffs (AQE on vs off) alongside them. The captured
  plan is pre-adaptive, not the executed/adaptive plan, so it will NOT show
  the actual switched join operator or coalesced partition count Spark chose
  at runtime -- adding that requires Spark final-plan/event-log capture,
  which is out of scope for this post and tracked as a follow-up TODO instead.
  Readers get timings plus a caveat about what the plan diff can and cannot
  show, not a claim of directly observing AQE's runtime decisions.

## 7. Methodology notes + Limitations (150-250 words)

- All Spark documentation quotes verified against official Apache doc mirrors
  (access date 2026-07-04); all other vendor claims are search-derived because
  this research environment could not fetch the primary pages, and are labeled
  with that provenance in the research file. Re-verify before publishing the
  draft.
- Databricks' TPC-DS figures are Databricks' numbers from 2020 on a
  statistics-free setup; they bound the opportunity, not typical gains.
- No BenchBox measurements exist yet; section 6 is a plan.
- The survey covers documented GA behavior only; no engine's roadmap is
  speculated about.
- Plan-capture caveat: BenchBox's Spark plan capture is a post-measurement
  `EXPLAIN EXTENDED`, not the executed/adaptive plan, so the captured diffs
  cannot show AQE's actual runtime join-strategy switch or partition
  coalescing -- only that a static plan differs (or doesn't) between AQE
  on/off. State this explicitly rather than imply the plan diff proves what
  AQE did at runtime.

## 8. Conclusions + Next steps (150-250 words)

- Restate the thesis in one paragraph: where an engine can adapt is a property
  of its execution model. Spark re-plans between stages because its shuffle
  materializes; pipelined engines adapt inside operators; adding a spooling
  shuffle adds the capability; single-node engines relocate the problem.
- No engine ranking. The practical takeaway for benchmark users: know which
  adaptation your engine performs and design experiments (skewed data,
  disabled statistics, on/off toggles) that actually exercise it.
- Invite reproduction and contribution: the TPC-H Skew presets and the
  planned AQE experiment; link the research file; open an issue to discuss.

## References (footnotes)

- Apache Spark Performance Tuning docs, 3.2.0 (downloads.apache.org mirror)
  and 3.5.1 (archive.apache.org), accessed 2026-07-04: AQE definition,
  default-on since 3.2.0, all config keys and defaults.
- Spark 3.0.0 release notes (spark.apache.org), search-derived 2026-07-04.
- Databricks, "Adaptive Query Execution: Speeding Up Spark SQL at Runtime",
  2020-05-29, search-derived 2026-07-04.
- Oracle Database SQL Tuning Guide, Adaptive Query Optimization chapter,
  search-derived 2026-07-04.
- Microsoft Learn, Intelligent Query Processing and adaptive joins;
  Microsoft SQL Server blog 2017-09-28, search-derived 2026-07-04.
- Trino documentation, Adaptive plan optimizations and Fault-tolerant
  execution, search-derived 2026-07-04.
- Dageville et al., "The Snowflake Elastic Data Warehouse", SIGMOD 2016,
  search-derived 2026-07-04.
- Google Cloud, BigQuery query plan and timeline documentation,
  search-derived 2026-07-04.
- DuckDB documentation and execution-model material; ClickHouse architecture
  overview (VLDB 2024 paper mirror), search-derived 2026-07-04.

## TODOs before drafting

- [ ] Re-verify every search-derived claim (research file Part C, A5, A6)
      against the live primary pages from an unrestricted network, and
      upgrade or soften provenance labels accordingly.
- [ ] Spot-check Spark 3.5.1-quoted defaults against the current 4.x docs.
- [ ] File and fix the two AQE-toggle harness issues (research file B2, B4)
      so the AQE on/off comparison in section 6 is actually runnable.
- [ ] Run the section 6 plan; replace the future tense with measured results
      and move the resulting evidence into the research file with dates.
- [ ] Draft the synthesis table (4e) and check it reads neutrally with the
      content validation checklist in `_blog/STYLE_GUIDE.md`.

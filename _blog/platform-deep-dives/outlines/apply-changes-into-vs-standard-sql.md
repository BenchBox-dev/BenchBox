# Outline: AUTO CDC vs Standard SQL MERGE for SCD Type 2

**Post type:** Platform deep-dive / technical challenge (convenience vs portability).
**Target length:** 1,800-2,400 words.
**Editorial angle:** Not "declarative good, SQL bad" and not a Databricks teardown.
Thesis: declarative CDC genuinely removes boilerplate and a class of SCD2 bugs, and
that convenience is real, but it is a pipeline-bound, Databricks-only abstraction.
The right lens is convenience vs portability, with honest numbers and code side by
side. Let readers weigh the trade-off.

**Evidence source:** `_blog/platform-deep-dives/research/apply-changes-into-vs-merge-verification-2026-06-27.md`.
Every perf/behavior claim cites a dated entry there. BenchBox harness results and
Databricks doc/marketing claims are never conflated. No Databricks workspace was
available, so the declarative side is documentation-grounded only.

**Voice reminders:** "we", neutral on platforms, data over superlatives, no
em-dashes or en-dashes, define terms, footnote external facts.

## Title + frontmatter
- Title (< 60 chars): "SCD Type 2: Declarative CDC vs Portable SQL MERGE"
- One-sentence summary + TL;DR (the trade-off in 2-3 sentences).
- meta_description (150-160 chars); tags: databricks, delta-lake, scd-type-2, merge,
  cdc, write-primitives, benchmarking, portability.

## 1. Introduction (150-300 words)
- The hook: a widely shared claim that declarative CDC replaces ~200 lines of MERGE.
- What we test: reconstruct the real portable SQL, count it honestly, measure it in
  BenchBox, characterize the declarative form from primary docs.
- Define SCD Type 2 (close the current version, open a new one, keyed on a business
  key) in one parenthetical.
- State the two axes: ergonomics/maintainability and portability/lock-in, plus
  performance where measurable.

## 2. The two forms, side by side (main content)
- 2a. Declarative AUTO CDC (formerly APPLY CHANGES INTO): show the ~6-7 line SQL
  example from the docs (A2). Note current naming (A1) and the DLT to Lakeflow
  history briefly (A5).
- 2b. Portable MERGE / UPDATE+INSERT: show the BenchBox `merge_scd_type2_basic` form
  (close-old UPDATE + insert-new INSERT). Explain the two-statement reality.
- 2c. The honest line count: ~18 portable lines vs ~6-7 declarative for a basic
  Type 2. Correct the "200 lines" framing: official figure is 40-200+ for full
  custom pipeline logic (A6); the 1,500-line number is a customer quote, not an
  official metric. Databricks also removed its own SCD2 MERGE example (A7).

## 3. What the declarative form does for you (ergonomics)
- SEQUENCE BY (out-of-order events), APPLY AS DELETE, COLUMNS EXCEPT, automatic
  __START_AT/__END_AT versioning (A4). These are real and remove a class of bugs.
- Where the portable form makes you do the work: ordering, late data, deletes are
  on you (the BenchBox op is a single ordered batch by design). Be fair: this is the
  declarative form's genuine advantage.

## 4. Portability and lock-in
- AUTO CDC runs on a Lakeflow declarative pipeline (Pro/Advanced/serverless), now
  invocable from a SQL warehouse via standalone streaming tables, but always on
  Databricks/serverless pipelines, never on other engines, and not a standalone
  statement (A3, with the 2026 correction, stated carefully).
- The portable form runs unchanged across DuckDB, PostgreSQL, Snowflake, BigQuery,
  ClickHouse. Concrete proof: DuckDB rejects MERGE INTO entirely, yet runs the
  portable UPDATE+INSERT SCD2 op (C1).

## 5. What we measured (results, BenchBox, portable form only)
- Methodology: DuckDB 1.3.2, Apple M4, real TPC-H via dbgen, operation API (explain
  why not `benchbox run`: the DuckDB MERGE-category skip, C1).
- SF0.01 and SF0.1 tables (C3). The change-batch-bound observation (10x data, ~1.7x
  time).
- Explicit non-measurement: we did not run AUTO CDC (no workspace); no declarative
  timing or cost is claimed.

## 6. Analysis: convenience vs portability
- When declarative wins: Databricks-centric stack, streaming CDC with out-of-order
  and deletes, teams that value fewer lines and fewer SCD2 bugs.
- When portable wins: multi-engine benchmarking/portability, no pipeline runtime,
  full control, running on engines that lack MERGE INTO.
- No verdict; present the trade-off.

## 7. Methodology + Limitations
- Reproducible commands (dbgen + operation API snippet), versions, machine.
- Limitations: single machine, DuckDB-only, no Databricks run, basic Type 2 only,
  line-count compares one implementation to one documented example.

## 8. Conclusions + Next steps
- The "200 lines" claim is partly a strawman for a basic Type 2 (real portable form
  is ~18 lines) and partly fair for hardened production pipelines (40-200+).
- The honest axis is portability vs convenience.
- Invite reproduction; link the BenchBox operation and the verification file.

## References (footnotes)
- Databricks AUTO CDC / CDC docs, SQL ref, standalone streaming tables, where-is-dlt,
  delta/merge, the "Stop hand-coding CDC" blog. All accessed 2026-06-29.

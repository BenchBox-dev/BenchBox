---
title: "How the Results Explorer qualifies comparisons"
series: building-benchbox
post_number: 16
type: architecture-design
tags: [benchbox, results-explorer, benchmarking, comparability, validation, duckdb-wasm]
status: DRAFTED
---

# Outline: How the Results Explorer qualifies comparisons

## Purpose

Explain the engineering behind the Results Explorer preview named in v0.4.0.
Show how the site separates display, comparison, and ranking, and how recorded
differences stay inspectable. Companion to the v0.4.0 release overview; this
post is the eligibility and comparability deep dive, not a product tour.

Cover the four required threads in order: inspiration (Geekbench and AI eval
leaderboards), reason we built a standalone results site, how readers get
value today, and how to submit results via `benchbox submit`.

## Audience

- Data engineers reading public benchmark comparisons.
- Maintainers designing transparent results sites.
- BenchBox users who want to audit the published snapshot.

## Thesis

The Results Explorer decides what may be displayed, compared, and ranked, and
it leaves recorded differences visible. Two timings still have to earn a
comparison.

## Evidence boundary

- UI and eligibility behavior: `refs/tags/v0.4.0` source.
- Corpus corrections: tagged `results-data/CORPUS_NOTES.md`.
- Current figures: deployed snapshot read on August 28, 2026, captured as SHA-256
  `83cf3c7ffe56ad6f89c53944e66d9c18aa794d3985c89ae87588fb57a2398863`.
- Architecture: released static build and public DuckDB snapshot.
- Avoid calling warnings hard comparability gates. Benchmark, scale, phase, and timing coverage
  suppress winner claims; version, environment, validation, tuning, and cost differences are
  visible warnings.
- Do not write an unbounded future API. The shipped preview and planned
  pull-request path need no backend.

## Structure and word budget

Target: 1,800-2,200 words. Series beats from
`_blog/building-benchbox/outlines/series-plan.md`. H2s need not use the
template labels.

### 1. The problem - Which numbers belong together (~180 words)

- Open with two plausible timings (12s vs 31s) and the questions they omit.
- Screenshots and forum posts usually omit the context that determines
  comparability, such as scale factor, query coverage, tuning mode, hardware
  details, and validation status. BenchBox captures that context in each
  result bundle, and the Explorer presents it alongside the numbers so readers
  can assess whether a comparison is valid.
- Concrete case: TPC-H SF1 power, DataFusion SQL vs Polars DataFrame, both
  ranking-eligible on the August 28 snapshot.

### 2. What we tried (~220 words)

- Three architectures: pre-rendered JSON, hosted API, static DuckDB in the
  browser. We shipped the third.
- JSON would start faster; DuckDB gives a SQL workbench; an API would be
  another service. The curated preview and planned pull-request path need no
  backend. Do not promise a future API.
- Inspiration evaluated: Geekbench Browser for stable public result pages with
  a permanent URL, an obvious compare action, and clear separation between a
  local run and a hosted result; AI eval leaderboards (Open LLM Leaderboard,
  Chatbot Arena, HELM) for filterable, provenance-aware rankings where the
  table is useful because you can see what produced each row. Both informed
  per-benchmark tables that rank results only when they share the same
  benchmark, scale, and phase.
- The site presents ranked tables only where results share benchmark, scale,
  phase, and sufficient timing coverage, keeps ineligible rows visible with a
  named reason, and shows remaining differences (version, environment,
  validation, tuning, cost) as warnings on the comparability receipt so
  readers can judge the comparison. Environment and version are shown as
  warnings rather than hard gates, which keeps the August 28 snapshot usable
  (11 of 138 complete environments; no driver versions) while keeping context
  inspectable. Date that count where it is used.

### 3. What we built (~900 words, three H2s)

- Winner language with warnings, then a suppressed claim: live Compare
  walkthroughs (`e3aaa125` vs `9187e38f`; DuckDB TPC-DS SF1 vs SF10).
  Execution mode is a warning; scale factor is a hard gate. Screenshots and
  receipt table.
- Display, comparison, and ranking are separate decisions: admission, display,
  comparison coverage floor, ranking policy. Include the TypeScript excerpt and
  August 28 layer counts (138 / 134 / 105 / 55).
- A database in the browser: 8,400,896-byte DuckDB snapshot, JSON bundles,
  architecture diagram, CI thresholds as test budgets. A failed attach is an
  error, not an empty table.

### 4. What we learned - A validation pass on zero queries is a non-measurement (~360 words)

- August 24: withdraw 60 zero-query DataFrame non-measurements, then 17
  truthful SQL bundles to keep the three-platform group floor.
- List the exact affected scales. Lower-scale groups remain.
- August 25: 52 retained bundles with passed/partial summaries and `NOT_RUN`
  validation phase, normalized to `not_run`.
- Admission now requires proof of execution. After corrections: 56 passed, 30
  partial, 52 not run, 55 ranking-eligible.

### 5. Try it yourself - Query the same table the pages use, then submit your own (~300 words)

- Start at the Explorer root and open Query.
- SQL for the TPC-H SF1 power ranking split and for validation/ranking counts.
- Open Compare URLs or a result detail; download the JSON bundle.
- Direct imperative: run a local copy for independent corroboration.
- How to submit your own results: run a complete suite (`uv run -- benchbox
  run --platform duckdb --benchmark tpch --scale 0.01`), package with
  `uv run -- benchbox submit --last --output ./submission` (or pick a run via
  `benchbox results --paths`), fork `BenchBox-dev/BenchBox`, copy
  `submission/bundle/*` into `results-data/bundles/` (not `vendor/`), copy the
  per-bundle manifest alongside, regenerate inventory with
  `uv run -- python scripts/generate_corpus_inventory.py --write`, and open a
  PR against the `published-results` branch titled
  `results: <benchmark> <platform> sf<scale>`. CI validates schema, SHA-256
  hash, and inventory drift and posts a summary comment. Merge enters the
  Phase 2 archive; promotion to the curated Explorer snapshot is a separate
  maintainer-reviewed step, and community rows remain visible but excluded
  from ranked tables.
- Closing snapshot section: 138 maintainer-run rows, uneven platform coverage,
  dated August 28. Disclose the conflicting contribution surfaces.

## Editorial risks

- Do not use "reliable" as an unqualified property of the results.
- Do not say the Results Explorer launches, goes live, or is new in v0.4.0.
  The site has been reachable since April 2026; this release names the preview.
- Do not turn receipt warnings into eligibility gates.
- Do not call 34 inventory benchmark-scale groups ranking cohorts.
- Do not describe the static architecture as a security guarantee.
- Do not claim the 17 group-floor withdrawals were invalid. Avoid the
  coined term "cohort-aware"; describe the scope in plain language: results
  that share the same benchmark, scale, and phase.
- Do not infer an exact implementation root cause for the zero-query validation issue.
- Do not describe the public instructions as closed. Describe the conflicting submission surfaces
  and avoid promising that a submission automatically enters the Explorer.
- Satisfy negative bounds by omission or by stating the affirmative scope once.
  Do not render them as "This is Y. This is not X." Keep news-negation that is
  the finding (title, zero-query non-measurement, missing evidence).

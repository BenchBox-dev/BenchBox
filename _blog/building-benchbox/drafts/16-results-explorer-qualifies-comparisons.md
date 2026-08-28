---
title: "How the Results Explorer qualifies comparisons"
series: building-benchbox
post_number: 16
type: architecture-design
tags: [benchbox, results-explorer, benchmarking, comparability, validation, duckdb-wasm]
meta_description: "How BenchBox separates display, comparison, and ranking, exposes missing evidence, and lets readers audit the public Results Explorer snapshot directly."
status: draft
---

# How the Results Explorer qualifies comparisons

> BenchBox v0.4.0 launches a curated Results Explorer preview that separates what can be displayed, compared, and ranked, while leaving important differences visible.

**TL;DR**: Two timing numbers do not become comparable because they fit in the same chart. The Results Explorer suppresses winner claims when the benchmark, scale factor, phase, or timing coverage does not line up. Other recorded differences, including versions, validation, tuning, and environment, appear as warnings for the reader to judge. The preview makes evidence easier to inspect; it does not certify every result or comparison.

---

Suppose one benchmark result reports 12 seconds and another reports 31 seconds. Before treating that as a performance comparison, we need more information. Did both runs use the same benchmark and scale factor? Did they execute the same phase and enough of the same queries? Did any query fail? Other questions still affect interpretation: were the runs SQL or DataFrame executions, what hardware and software did they use, what tuning and validation evidence did they record, and who produced or funded them?

The [Results Explorer](https://benchbox.dev/results/) launched as a curated preview with BenchBox v0.4.0.[^release] Its main engineering job is not sorting numbers. It separates mismatches that automatically suppress winner claims from recorded differences that remain warnings for the reader. That boundary is narrower than full methodological equivalence.

## Launch snapshot

We read the deployed snapshot on August 28, 2026. It contained 138 results. Of those, 134 had timing evidence the Explorer could display, 105 were eligible for comparison, and 55 were eligible for ranking.[^snapshot]

The validation breakdown was 56 passed, 30 partial, and 52 not run. Only 11 results recorded a complete environment across operating system, architecture, CPU count, memory, and Python version. None recorded a driver version. Eight recorded the tuning value `notuning`; none recorded a tuned configuration. Every result was labeled `maintainer-run`, with funding `unspecified`.

Coverage was uneven too. DataFusion accounted for 48 results. Spark had 19; DuckDB and Polars had 18 each; PySpark had 17; SQLite had 16. ClickHouse Local and LakeSail had one each. Those counts describe this launch snapshot, not permanent support levels or a representative sample of the database market.

That is why the preview needs more than a leaderboard. A polished ranking without those limitations would make the corpus look more complete than it is. The useful part of the preview is that readers can inspect per-query evidence, reproduce aggregate counts with SQL, compare admitted cohorts, and download the underlying bundles rather than relying on a chart alone.

## Four decisions

The Explorer treats admission, display, comparison, and ranking as separate decisions.

```text
result bundle -> admission -> published evidence
                                  |-> display: can this timing be shown?
                                  |-> comparison: is there enough shared query evidence?
                                  `-> ranking: does this row satisfy ranking policy?
```

**Admission** happens before the browser build. A result bundle must satisfy schema, policy, and corpus checks before it enters the published input set. Admission answers whether the project can publish the evidence at all. It does not promise that the evidence belongs in a ranking.

**Display** asks whether a timing is valid enough to show. Missing, zero, non-finite, or otherwise excluded timings should not quietly become chart points. A result can still have useful provenance or capability evidence even when its primary timing is unavailable.

**Comparison** asks whether selected runs share enough valid query evidence. The released implementation requires at least two common valid query timings. It also requires each selected result to cover at least half of the query IDs present in the selection, with a minimum of two.[^eligibility] This blocks thin or nearly disjoint evidence from supporting a comparison claim. It does not guarantee identical query sets: the headline metric remains each result's own display geomean, so selected runs can still summarize different subsets.

The core coverage calculation is deliberately small:

```typescript
const queryIds = [...new Set(results.flatMap(
  (result) => result.display_timings.map((timing) => timing.query_id),
))];
const requiredValidQueriesPerResult = Math.max(2, Math.ceil(queryIds.length * 0.5));
const commonValidQueries = countCommonValidQueries(results, queryIds);

if (commonValidQueries < 2) {
  return {
    comparable: false,
    reason: EXCLUSION_LABELS.insufficient_common_valid_timings ??
      "Selected runs do not share enough valid timings.",
    totalQueries: queryIds.length,
    commonValidQueries,
    requiredValidQueriesPerResult,
  };
}
```

The implementation separately rejects a result whose valid timing count is below `requiredValidQueriesPerResult`. These checks establish a minimum evidence floor, not identical methodology.

**Ranking** applies a narrower policy. A result can be displayable and comparable but remain outside ranked tables because of failed queries, unclean validation, insufficient query coverage, or trust policy. The launch snapshot makes the difference concrete: 134 displayable results narrow to 55 rankable ones.

The interface attaches named reasons to exclusions. Examples include "One or more queries failed," "Validation status excludes this result from ranking," and "Selected runs do not share at least two valid query timings." A missing row should explain itself instead of disappearing without context.

## Hard gates and visible warnings

The Compare page has two kinds of qualification. Some mismatches suppress winner and ranking claims. Other differences remain visible in the Comparability Receipt but do not block those claims.

| Check | Explorer behavior |
| --- | --- |
| Canonical benchmark | A mismatch suppresses winner and ranking claims |
| Scale factor | A mismatch suppresses winner and ranking claims |
| Test phase | A mismatch suppresses winner and ranking claims |
| Shared valid timing coverage | Insufficient overlap suppresses the comparison claim |
| Platform and driver versions | Recorded differences appear as warnings |
| Validation and execution mode | Recorded differences appear as warnings |
| Environment and run date | Recorded differences appear as warnings |
| Tuning, physical mechanisms, and cost metadata | Recorded differences appear as warnings |
| Tuning-policy generation | Recorded differences appear as warnings when the field applies |
| A field missing for every selected result | Shown as "Not recorded," without increasing the warning count |

The severe cohort check canonicalizes the benchmark and phase before comparing them. That avoids both false matches and false mismatches caused by aliases or letter case. If benchmark, scale factor, or phase differs, the page suppresses the winner language.[^compare]

Timing coverage is another hard boundary. Even runs from the same named cohort do not support a comparison if they share too little valid query evidence. The comparison summary reports the total query IDs, the number common to every selected run, and the required coverage per result.

The Comparability Receipt then checks workload, date, platform version, driver version, execution mode, validation, environment, tuning, physical mechanisms, tuning-policy generation, and cost. A difference gets a warning. A field that nobody recorded gets a neutral missing status. This distinction matters: a platform-version warning may coexist with a displayed winner claim. The receipt does not certify that the comparison is methodologically equivalent. It gives the reader the recorded differences needed to decide whether the claim is useful.

That design is intentionally narrower than saying "comparable" means "same environment." It also does not require the same execution mode. In the captured TPC-H SF1 power cohort, ranking-eligible rows include DataFusion and Spark in SQL mode alongside Polars and PySpark in DataFrame mode. Winner language can still appear for that mixed-mode selection because execution mode is a receipt warning, not a hard gate.[^snapshot][^compare]

The launch corpus does not have enough complete environment records to enforce environment equivalence without removing most of the site. Instead, the Explorer blocks the mismatches it can define reliably and exposes the rest. Provenance and funding labels provide more context elsewhere in the interface; they do not turn the receipt into independent certification.

## Browser-local DuckDB

The Explorer has a static read path. The released site serves an 8,400,896-byte DuckDB snapshot, and DuckDB-WASM attaches it read-only in the visitor's browser.[^database] The application pages and SQL workbench query the same tables.

There is no application API, authentication service, or database server in that read path. That keeps the launch architecture small, but it is not a security guarantee. Static hosting, CDN behavior, the build pipeline, publication permissions, and the contents of the snapshot still matter.

The snapshot is also not the only published artifact. The launch site serves 138 downloadable JSON result bundles, one per snapshot row, alongside the DuckDB file. The database is the store for user-visible metrics; the JSON remains available for downloading and inspecting individual evidence bundles.

```text
admitted bundles -> static build -> results.duckdb -> DuckDB-WASM -> pages and SQL workbench
                              `-> JSON bundles ------------------> individual downloads
```

Running DuckDB in the browser has a cold-start cost that pre-rendered JSON would avoid. In return, visitors get a SQL workbench over the same read model used by the site. The browser tests enforce startup and rendering budgets as CI thresholds. Those thresholds are not measurements of production latency on every visitor's device or network.

The failure behavior is part of the contract. If the browser cannot attach the snapshot, the site reports an error rather than rendering a plausible empty leaderboard. An empty state and a failed data load mean different things.

## Corpus corrections

Eligibility rules are only as useful as the evidence entering them. Two corpus corrections immediately before the v0.4.0 release showed why admission and visible gaps matter.[^corpus]

On August 24, the project withdrew 60 legacy DataFrame bundles. Each reported `summary.validation=passed` after executing zero queries. These were non-measurements, not partial benchmark results.

Removing only those files would have left ten raw benchmark and scale-factor groups below the project's three-represented-platform corpus floor. The project therefore withdrew 17 additional SQL bundles from those groups. Those 17 had truthful measurements and were not classified as invalid. They were removed to avoid presenting thin groups as supported comparison coverage.

The cost was visible. AMPLab, CoffeeShop, and H2O-DB at SF 0.1 and 1.0, SSB at SF 1.0, and TSBS DevOps at SF 0.01, 0.1, and 1.0 left the published corpus. The SF 0.01 groups for AMPLab, CoffeeShop, and H2O-DB remain. A group can return when it has at least three truthful platform results. Fresh DataFrame results also need real validation evidence.

On August 25, a second review found 52 retained bundles whose summary claimed validation `passed` or `partial` while the recorded validation phase was `NOT_RUN`. The correction changed 23 passed claims and 29 partial claims to `not_run`. It did not rewrite timings or failure records, and it kept the bundles as non-ranking capability evidence.

Admission now rejects the same contradiction: a summary cannot claim passed or partial validation when the validation phase records no run. The broader lesson is useful outside BenchBox. A validation status should establish both that the checks passed and that the work being checked actually ran. When that evidence is absent, a visible gap is more accurate than a filled-in status.

## Auditing the snapshot

Start at the [Results Explorer root](https://benchbox.dev/results/) and open **Query** from the navigation. The workbench exposes `bench.results`, the same result table used by the application. This query reproduces the launch snapshot's validation and ranking split:

```sql
SELECT
  validation_status,
  is_ranking_eligible,
  COUNT(*) AS results
FROM bench.results
GROUP BY validation_status, is_ranking_eligible
ORDER BY validation_status, is_ranking_eligible;
```

When we ran the query on the captured August 28 snapshot, it returned 52 not-run and non-ranking results, 30 partial and non-ranking results, one passed but non-ranking result, and 55 passed and ranking-eligible results.[^snapshot]

From there, open a result detail. Check its methodology disclosure, provenance fields, validation state, query coverage, and environment. Download the JSON bundle if you need the evidence outside the browser. A fresh local run can provide independent corroboration, but it will not guarantee the same timing: hardware, software, configuration, background load, and data paths can all change the measurement.

The submission guidance is inconsistent at launch. The public contribution guide and the Explorer's **Submit a bundle** link describe a pull-request workflow, but the corpus README says community contributions are not yet open. The public guide also still points contributors to the old GitHub repository name. A submission therefore should not be read as automatic inclusion in the Explorer.[^contributions] For this preview, the dependable actions are to browse, audit, and [open an issue](https://github.com/BenchBox-dev/BenchBox/issues) when a result or explanation needs correction.

## Preview scope

The Explorer establishes a visible qualification process, not universal comparability. It does not cover every platform, benchmark, environment, or funding source. It does not make results from different hardware equivalent. It does not turn a warning-free receipt into independent certification.

What it can do is narrower and useful: refuse some unsupported winner claims, show why rows are excluded, expose recorded differences, and let readers query and download the same public evidence. For benchmark results, an honest missing field is more informative than precision the corpus cannot support.

---

## References

[^release]: [BenchBox 0.4.0 release](https://github.com/BenchBox-dev/BenchBox/releases/tag/v0.4.0), published August 28, 2026.
[^snapshot]: [Deployed Results Explorer DuckDB snapshot](https://benchbox.dev/results/data/results.duckdb), read August 28, 2026. Captured SHA-256: `83cf3c7ffe56ad6f89c53944e66d9c18aa794d3985c89ae87588fb57a2398863`.
[^eligibility]: [Display and comparison eligibility implementation at the v0.4.0 tag commit](https://github.com/BenchBox-dev/BenchBox/blob/f841b85f1d40cc2396f16fb185d1dfbb371ac1a3/results-explorer/src/lib/displayEligibility.ts).
[^compare]: [Compare page cohort and claim-suppression logic at the v0.4.0 tag commit](https://github.com/BenchBox-dev/BenchBox/blob/f841b85f1d40cc2396f16fb185d1dfbb371ac1a3/results-explorer/src/pages/Compare.tsx) and [Comparability Receipt implementation](https://github.com/BenchBox-dev/BenchBox/blob/f841b85f1d40cc2396f16fb185d1dfbb371ac1a3/results-explorer/src/components/ComparabilityReceipt.tsx).
[^database]: [Results Explorer database attachment at the v0.4.0 tag commit](https://github.com/BenchBox-dev/BenchBox/blob/f841b85f1d40cc2396f16fb185d1dfbb371ac1a3/results-explorer/src/db.ts).
[^corpus]: [Corpus generation and correction notes at the v0.4.0 tag commit](https://github.com/BenchBox-dev/BenchBox/blob/f841b85f1d40cc2396f16fb185d1dfbb371ac1a3/results-data/CORPUS_NOTES.md).
[^contributions]: [Public contribution guide](https://benchbox.dev/docs/contributing-results.html), [corpus contribution status at the v0.4.0 tag commit](https://github.com/BenchBox-dev/BenchBox/blob/f841b85f1d40cc2396f16fb185d1dfbb371ac1a3/results-data/README.md#contributing-via-pull-request-phase-2), and [Explorer submission link at the v0.4.0 tag commit](https://github.com/BenchBox-dev/BenchBox/blob/f841b85f1d40cc2396f16fb185d1dfbb371ac1a3/results-explorer/src/pages/Home.tsx).

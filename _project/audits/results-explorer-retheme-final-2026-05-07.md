---
develop_sha: ece7018ba80c0ff1359741b82aa08bc1269214a3
---
# Results Explorer Retheme — Release-Readiness Report

Date: 2026-05-07
TODO: `results-explorer-retheme-release-gate`
Follow-up branch: `fix/results-explorer-retheme-audit-followups`.

## Verdict

**READY for release behind the existing /results/ public route.**

The audit follow-up closes the previous release-gate gaps: Result Detail and
real Compare routes are now in the route matrix, Result Detail / Compare have a
page-level token retheme, Query scroll affordances are wired, and the capture
spec waits for route-specific loaded landmarks before taking screenshots.

## Route matrix (w1/w2)

| Route | Cold-load | Visible loaded landmark | Console / network |
|---|---|---|---|
| `/results/` | OK | "Cross-Benchmark Leaderboard" | clean |
| `/results/tpch/?sf=0.01&phase=standard` | OK | "TPC-H Results" | clean |
| `/results/star_schema/?sf=0.1&phase=power` | OK | "SSB Results" | clean |
| `/results/p/duckdb/` | OK | "DuckDB Results" | clean |
| `/results/p/datafusion/` | OK | "DataFusion Results" | clean |
| `/results/p/polars/` | OK | "Polars Results" | clean |
| `/results/r/tpch-duckdb-sf0.01-20260403-010ee756` | OK | "Query Timings" | clean |
| `/results/compare?ids=ba6a8c83,5e6c5eba` | OK | "TPC-H Comparison" | clean |
| `/results/compare?ids=ba6a8c83,0f0add9f` | OK | "Mixed Benchmark Comparison" | clean |
| `/results/compare` (empty) | OK | "Cannot compare" | clean |
| `/results/query` | OK | "matching result bundle" | clean |
| `/results/clickbench/` (supported but empty corpus) | OK | "No published results yet" | clean |

Cold-load evidence logged at
`_project/audits/screenshots/results-explorer-retheme-final-2026-05-07/console-network-2026-05-07.log`.
The log records every `console.error|warning`, every HTTP ≥400 response, and
every `pageerror` across 48 viewport-route loads (12 routes × 4 widths). The
log file contains only its header line — i.e. **zero console errors, warnings,
page errors, or non-2xx responses** were observed during the cold-load matrix.

## Screenshot index (w3)

48 fullPage screenshots committed under
`_project/audits/screenshots/results-explorer-retheme-final-2026-05-07/`:

```text
home-{390,768,1280,1600}.png
benchmark-tpch-sf001-{390,768,1280,1600}.png
benchmark-star-schema-sf01-{390,768,1280,1600}.png
platform-duckdb-{390,768,1280,1600}.png
platform-datafusion-{390,768,1280,1600}.png
platform-polars-{390,768,1280,1600}.png
result-detail-tpch-duckdb-{390,768,1280,1600}.png
compare-same-cohort-{390,768,1280,1600}.png
compare-mismatch-benchmark-{390,768,1280,1600}.png
compare-empty-{390,768,1280,1600}.png
query-{390,768,1280,1600}.png
not-found-{390,768,1280,1600}.png
```

The capture spec (`results-explorer/e2e/captures/release-final.spec.ts`) is
gated on `RETHEME_CAPTURE=1` so it does not run on every CI invocation; it can
be replayed by future reviewers with a single environment variable.

## Console / network summary (w2)

```text
$ wc -l _project/audits/screenshots/results-explorer-retheme-final-2026-05-07/console-network-2026-05-07.log
1  # only the header line
```

## Interaction QA summary (w4)

Interactive paths covered by the existing chromium e2e suite and/or the final
capture matrix:

| Path | Evidence |
|---|---|
| Home leaderboard mode/sort SegmentedControl + cohort link | `e2e/routes/home.spec.ts`, `responsive.spec.ts`, final home screenshots |
| Benchmark scale/phase URL sync, matrix/ranks/list view, sortable headers | `routes/benchmark-index.spec.ts`, `routes/index-sort-headers.spec.ts`, final benchmark screenshots |
| Platform table/trend route readiness | final DuckDB/DataFusion/Polars screenshots |
| Result-detail receipt, chart/table sections, tuning sidecar failure | `routes/result-detail.spec.ts`, `failures/result-detail-failures.spec.ts`, final result-detail screenshots |
| Same-cohort Compare, baseline selector, share URL, query diff | `routes/compare.spec.ts`, final same-cohort screenshots |
| Mismatch Compare guardrails | `failures/compare-hard-block.spec.ts`, final mismatch screenshots |
| Query Workbench facets, row-limit, exports, SQL read-only error | `routes/query.spec.ts`, final query screenshots |
| Mobile / desktop ordering across home, benchmark, query, compare | `responsive.spec.ts`, final 390/768/1280/1600 screenshots |

## Automated checks (w5)

Follow-up verification on this branch:

```text
$ cd results-explorer && npm run typecheck
clean

$ cd results-explorer && npm test -- --run
Test Files 45 passed (45)
Tests 506 passed (506)

$ cd results-explorer && npm run build
✓ built in 1.76s

$ cd results-explorer && npx playwright test --project=chromium --workers=1 --grep-invert @performance
53 passed (6 skipped — opt-in capture/performance specs)

$ cd results-explorer && RETHEME_CAPTURE=1 npx playwright test --project=chromium e2e/captures/release-final.spec.ts
1 passed
```

Broader project preflight is still expected before merge.

## Accessibility / responsive summary (w6)

| Concern | Evidence | Status |
|---|---|---|
| Focus ring appears on `:focus-visible` only | `MetaLeaderboard.tsx`, global `*:focus-visible` rule in `index.css` | OK |
| Mobile secondary nav keeps `Query` on-canvas | `Layout.tsx`, final 390px screenshots | OK |
| Query/result/compare horizontal tables expose scroll cues | `.bb-scroll-affordance` in `Query.tsx`, `ResultDetail.tsx`, `QueryDiffTable.tsx` | OK |
| Chart SVGs stay container-bound | `.bb-chart-svg` adopted by chart SVG components | OK |
| Trust / validation / computed / comparison badge tones differentiated | `StatusBadge` roles/tones in Trust, validation, CompareSummary, ComparabilityReceipt, QueryDiffTable | OK |
| Cohort header metric/unit/direction visible | `MetaLeaderboard.tsx` `cohortMetricSublabel` | OK |
| SQL and load errors expose alert semantics | Query SQL error `role="alert"`; failure e2e targets `[role='alert']` | OK |

## Residual items (severity / owner)

1. **(Minor / product UX) Deeper Query Workbench workflow split.**
   The token/accessibility pass keeps Visible Columns and Build SQL From
   Filters in their existing positions. The DONE TODO notes now state this as a
   deferral instead of a completed redesign. Not a release blocker because the
   route is functional, keyboard-accessible, and no longer uses legacy color
   assertions.

2. **(Minor / product UX) Browse compare-bar copy and mobile-card strategy.**
   Browse pages remain coherent after the token pass, but deeper selected-count
   language and per-surface mobile behavior are future UX iterations. Not a
   release blocker because the current compare flow remains visible and tested.

## Anti-pattern check

- "DO NOT substitute unit tests for visual and interaction QA" — route-specific
  final screenshots now cover 12 public states × 4 widths, including Result
  Detail and real Compare routes.
- "DO NOT ignore console or network errors because the page looks acceptable" —
  observed clean across the expanded matrix.
- "DO NOT mark the retheme ready while any raw internal error is visible" — none
  observed.
- "DO NOT bury residual defects in prose" — residuals above are minor product
  UX iterations; no blocker or unowned major finding remains.

## How to replay

```text
cd results-explorer
npm run test:e2e:fixtures
npm run build

npm run typecheck
npm test -- --run
npx playwright test --project=chromium --workers=1 --grep-invert @performance

RETHEME_CAPTURE=1 npx playwright test --project=chromium \
  e2e/captures/release-final.spec.ts
```

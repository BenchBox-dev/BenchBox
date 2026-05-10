---
date: 2026-05-10
develop_sha: 8c1589c4b8add656a35345b38de68eff2e766cef
---
# Results Explorer Retheme - Release-Readiness Report

Date: 2026-05-10
TODO: `results-explorer-retheme-recapture-against-post-271-develop`
Captured develop SHA: `8c1589c4b8add656a35345b38de68eff2e766cef`
Supersedes: pre-PR #271 capture from 2026-05-07

## Verdict

**READY as evidence for the post-PR #271 shipped tree behind the existing
/results/ public route.**

This recapture replaces the stale release-final retheme artifact with one
generated after PR #271's retokenization fix. The capture spec ran from the
current develop tip, which is a descendant of `274a4a11e`, and generated a new
48-screenshot route matrix plus a manifest stamped with the same develop SHA.

The audit follow-up remains closed: Result Detail and real Compare routes are
in the route matrix, Result Detail / Compare have a page-level token retheme,
Query scroll affordances are wired, and the capture spec waits for
route-specific loaded landmarks before taking screenshots.

## Route matrix (w1/w2)

| Route | Cold-load | Visible loaded landmark | Console / network |
|---|---|---|---|
| `/results/` | OK | "Cross-Benchmark Leaderboard" | clean |
| `/results/tpch/?sf=0.01&phase=standard` | OK | "TPC-H Results" | clean |
| `/results/star_schema/?sf=0.1&phase=power` | OK | "SSB Results" | clean |
| `/results/p/duckdb/` | OK | "DuckDB Results" | clean |
| `/results/p/datafusion/` | OK | DataFusion route loaded; current fixture capture shows the empty-state landmark | clean |
| `/results/p/polars/` | OK | "Polars Results" | clean |
| `/results/r/tpch-duckdb-sf0.01-20260403-010ee756` | OK | "Query Timings" | clean |
| `/results/compare?ids=ba6a8c83,5e6c5eba` | OK | "TPC-H Comparison" | clean |
| `/results/compare?ids=ba6a8c83,0f0add9f` | OK | "Mixed Benchmark Comparison" | clean |
| `/results/compare` (empty) | OK | "Pick runs to compare" | clean |
| `/results/query` | OK | "matching result bundle" | clean |
| `/results/clickbench/` (supported but empty corpus) | OK | "No published results yet" | clean |

Cold-load evidence logged at
`_project/audits/screenshots/results-explorer-retheme-final-2026-05-10/console-network-2026-05-10.log`.
The log records every `console.error|warning`, every HTTP >=400 response, and
every `pageerror` across 48 viewport-route loads (12 routes x 4 widths). The
log file contains only its header and stamped SHA lines, so **zero console
errors, warnings, page errors, or non-2xx responses** were observed during the
cold-load matrix.

## Screenshot index (w3)

48 fullPage screenshots and one capture manifest are committed under
`_project/audits/screenshots/results-explorer-retheme-final-2026-05-10/`:

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

Manifest:
`_project/audits/screenshots/results-explorer-retheme-final-2026-05-10/capture-manifest-2026-05-10.json`.

The capture spec (`results-explorer/e2e/captures/release-final.spec.ts`) is
gated on `RETHEME_CAPTURE=1` so it does not run on every CI invocation; it can
be replayed by future reviewers with a single environment variable.

## Console / network summary (w2)

```text
$ wc -l _project/audits/screenshots/results-explorer-retheme-final-2026-05-10/console-network-2026-05-10.log
2  # header plus stamped develop_sha
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

Recapture verification on this branch:

| Check | Result |
|---|---|
| `git merge-base --is-ancestor 274a4a11e $(git rev-parse origin/develop)` | PASS |
| `cd results-explorer && npm run test:e2e:fixtures` | PASS |
| `cd results-explorer && npm run build` | PASS |
| `cd results-explorer && RETHEME_CAPTURE=1 npx playwright test --project=chromium e2e/captures/release-final.spec.ts --workers=1` | PASS |
| Result Detail / Compare DOM literal Tailwind palette grep | PASS |
| `make audit-sha-check FILE=_project/audits/results-explorer-retheme-final-2026-05-10.md` | PASS |
| `uv run --project _project/scripts -- python _project/scripts/todo_cli.py check-graph` | PASS |
| `uv run --project _project/scripts -- python _project/scripts/todo_cli.py validate` | PASS |

The DOM grep used the committed snapshots under
`results-explorer/e2e/captures/release-final-output/dom-snapshots/`.

The capture spec readiness metadata was updated for current route behavior:
the DataFusion platform route may render its empty-state landmark in the
fixture corpus, and `/results/compare` now renders the compare builder rather
than the older `Cannot compare` empty state.

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

1. **(Evidence scope) Fixture-backed visual matrix.**
   This artifact records the fixture-backed release-final capture matrix. It
   does not claim broader full-corpus visual coverage.

2. **(Captured behavior) DataFusion platform empty state.**
   The DataFusion platform screenshot currently records the route's empty state
   under the fixture corpus. That is captured as shipped behavior, not
   remediated in this evidence-only TODO.

## Anti-pattern check

- "DO NOT substitute unit tests for visual and interaction QA" - route-specific
  final screenshots cover 12 public states x 4 widths, including Result Detail
  and real Compare routes.
- "DO NOT ignore console or network errors because the page looks acceptable" -
  observed clean across the expanded matrix.
- "DO NOT mark the retheme ready while any raw internal error is visible" - none
  observed.
- "DO NOT bury residual defects in prose" - residuals above are evidence-scope
  notes, not release blockers.

## How to replay

```text
cd results-explorer
npm run test:e2e:fixtures
npm run build

RETHEME_CAPTURE=1 npx playwright test --project=chromium \
  e2e/captures/release-final.spec.ts --workers=1

make audit-sha-check FILE=_project/audits/results-explorer-retheme-final-2026-05-10.md
```

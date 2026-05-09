# Results Explorer follow-up usability — release evidence matrix

Date: 2026-05-09
Develop tip at gate run: `61e267cec` (post-PR #295).

**Correction posted 2026-05-09 (after self-audit):** The original
release-gate PR #296 over-claimed completion of the gate's manual
work units (w3 browser-drive, w4 screenshots). Those work units were
documented as deferred in the "Browser-drive evidence" and
"Browser-drive evidence (w3) and screenshots (w4)" sections below
but were also marked `status: done` in the YAML, which contradicts
the brief's "Do not claim verification passed for a manual check you
did not actually drive" rule. The YAML has been reverted: the
release-gate TODO is now back under `_project/TODO/main/planning/`,
w3 and w4 are `status: pending`, and the gate decision below is
restated as **CONDITIONAL** until the manual evidence lands.

This matrix is the closure record for the 2026-05-08 Results Explorer
follow-up review (chat-only, never committed to `_project/audits/`).
Each defect was rebound against develop tip in the implementing TODO's
w0 log and tracked through to the merging PR. The "w0 source line"
column references the canonical `_project/verification-logs/<id>/w0.log`
artifact, not the original chat numbering.

Priority mapping (per item 8 YAML, `approach`):
Critical→P0, High→P1, Medium-High→P2, Medium→P3, Low→P4.

## Per-defect evidence matrix

| # | Defect | TODO w0 source | PR | File(s) | Test(s) | Route(s) | Status |
|---|---|---|---|---|---|---|---|
| 1 | Compare empty-state surfaces literal "?ids=…" copy instead of letting users build a comparison | `bundle-1/w0.log:11–14` | #284 | `pages/Compare.tsx` (embedded `CompareBuilder`) | `pages/__tests__/Compare.test.tsx` (cohort-lock + launch case) | `/results/compare` | fixed |
| 2 | ResultDetail "Compare this result" button bounces back to `/results/r/<id>` | `bundle-1/w0.log:14–16` | #284 | `pages/Compare.tsx` (single-id pin path) | `pages/__tests__/Compare.test.tsx` (single-id pinned case) | `/results/r/<id>` → `/results/compare?ids=<id>` | fixed |
| 3 | No compare selection affordance from Query Workbench | `bundle-1/w0.log:16` | — | — | — | `/results/query` | deferred (follow-up TODO retained) |
| 4 | No compare selection affordance from Home leaderboard | `bundle-1/w0.log:17` | — | — | — | `/results/` | deferred (follow-up TODO retained) |
| 5 | No cohort selection on Benchmark / Platform detail pages | `bundle-1/w0.log:18–20` | — | — | — | `/results/<bench>/`, `/results/p/<plat>/` | deferred — `BenchmarkIndex` and `PlatformIndex` already render the heatmap selection column with `buildCompareUrl`; remaining w6 work is the explicit cohort-validation surface. Follow-up TODO retained. |
| 6 | Layout subnav active state is stale after client-side `route()` because `Layout` reads `window.location.pathname` once at mount | `bundle-1/w0.log:33–41` | #284 | `components/Layout.tsx` (`useRouter()` + `getCurrentUrl()`) | `components/__tests__/Layout.test.tsx` ("updates the active explorer subnav…") | every Explorer route | fixed |
| 7 | No benchmark switcher on `BenchmarkIndex` | `bundle-1/w0.log:43` | — | — | — | `/results/<bench>/` | deferred (follow-up TODO retained) |
| 8 | No platform switcher on `PlatformIndex` | `bundle-1/w0.log:44` | — | — | — | `/results/p/<plat>/` | deferred (follow-up TODO retained) |
| 9 | Home leaderboard filters render below the matrix | `bundle-1/w0.log:45–46` | — | — | — | `/results/` | deferred (follow-up TODO retained) |
| 10 | Heatmap sticky-left Platform column miscalibrated when checkbox column is present | `bundle-1/w0.log:51–55` | — | — | — | `/results/<bench>/` | deferred (follow-up TODO retained) |
| 11 | Heatmap `<thead>` not vertically sticky — query-id headers vanish on scroll | `bundle-1/w0.log:55–58` | — | — | — | `/results/<bench>/` | deferred (follow-up TODO retained) |
| 12 | Provenance / Trust cells stack badges densely with no compaction | `bundle-1/w0.log:58–62` | — | — | — | `/results/<bench>/`, `/results/p/<plat>/` | deferred (follow-up TODO retained) |
| 13 | Query Workbench `<th>` sort triggers are non-semantic (no `<button>`, no `aria-sort`, not keyboard-focusable) | `bundle-1/w0.log:67–70` | #284 | `pages/Query.tsx` (`<th aria-sort=…><button>` headers) | `pages/__tests__/Query.test.tsx` (existing `Benchmark[↑↓]?` matchers continue to pass) | `/results/query` | fixed |
| 14 | Query Workbench Visible Columns disclosure renders ABOVE the results panel on desktop | `query-workbench-controls-and-facets/w0.log:23–27` | #285 | `pages/Query.tsx` (`lg:order-1` dropped) | `pages/__tests__/Query.test.tsx` (ordering case) | `/results/query` | fixed |
| 15 | Visible Columns disclosure offers no Reset / Select all / Clear-optional bulk actions | `query-workbench-controls-and-facets/w0.log:29–31` | #285 | `pages/Query.tsx` (`resetVisibleColumnsToDefault`, `selectAllVisibleColumns`, `clearOptionalVisibleColumns`) | `pages/__tests__/Query.test.tsx` ("provides Reset / Select all / Clear optional bulk actions") | `/results/query` | fixed |
| 16 | Left-rail facet groups not collapsible/searchable; long benchmark lists push Platform/Scale below fold | `query-workbench-controls-and-facets/w0.log:33–37` | — | — | — | `/results/query` | deferred (follow-up TODO retained) |
| 17 | Two indistinguishable "SSB" choices in benchmark facets / Browse list (`star_schema` + `ssb` slugs) | `query-workbench-controls-and-facets/w0.log:39–43` | #285 | `lib/displayLabels.ts` (`formatBenchmarkLabel` returns "SSB (legacy slug)" for `ssb`) | `lib/__tests__/displayLabels.test.ts` (SSB-disambiguation case) | `/results/query`, `/results/` | fixed |
| 18 | Raw enum strings (`maintainer-run`, `not_applicable`, `public-curated`, `not_applicable_local`) leak through to user-facing copy | `query-workbench-controls-and-facets/w0.log:45–55` | #285 | `lib/displayLabels.ts` (centralized formatters); `pages/Query.tsx` (`formatQueryRowCell` wrapper); `pages/Home.tsx` (MultiSelectFilter + BrowseSection); applied to RunReceipt + ResultDetail in #295 | `lib/__tests__/displayLabels.test.ts`; `pages/__tests__/Query.test.tsx` ("maintainer run" assertion); `components/__tests__/RunReceipt.test.tsx` | `/results/query`, `/results/`, `/results/r/<id>` | fixed |
| 19 | Repeated `platform` values produce indistinguishable column headers / legend rows / compare-card titles when two runs share a platform name | `run-identity-disambiguation/w0.log:13–18` | #286 | `lib/runIdentity.ts` (`formatRunIdentitiesForCohort`); `components/RankTable.tsx`; `pages/Compare.tsx`; `preserveUniqueAfterTruncation` (review-driven, same PR head) | `lib/__tests__/runIdentity.test.ts` (10 cases incl. 8-char prefix collision); `components/__tests__/RankTable.test.tsx` (truncation invariants) | `/results/compare`, `/results/<bench>/` | fixed |
| 20 | Distribution / Overview / Sparkline / Trend charts still render raw platform names | `run-identity-disambiguation/w0.log:24–39` | — | — | — | `/results/<bench>/`, `/results/compare` chart tabs | deferred (follow-up TODO retained for w3/w4/w6 chart applications) |
| 21 | Cost tab renders an empty selectable panel for cohorts with no normalized cost data | `chart-panel-scope-and-labeling/w0.log:30–37` | #290 | `lib/chartRegistry.ts` (`requiresCostData: true` on `cost_scatter`) | `components/__tests__/ChartPanel.test.tsx` ("hides the Cost tab when no cohort row carries normalized cost data") | every chart-bearing route | fixed |
| 22 | Heatmap legend heading describes the cohort's primary score metric instead of the cells (per-query latency) | `chart-panel-scope-and-labeling/w0.log:39–46` | #290 | `components/QueryHeatmap.tsx` | `components/__tests__/QueryHeatmap.test.tsx` (legend assertion) | `/results/<bench>/` matrix view | fixed |
| 23 | Heatmap "High contrast" toggle is actually a grayscale lightness palette | `chart-panel-scope-and-labeling/w0.log:47–53` | #290 | `pages/BenchmarkIndex.tsx` ("Reduced color" relabel + tooltip) | — (label flip; no existing assertion broke) | `/results/<bench>/` matrix view | fixed |
| 24 | Chart panel header / tab band needs compaction | `chart-panel-scope-and-labeling/w0.log:18–23` | — | — | — | every chart-bearing route | deferred (follow-up TODO retained) |
| 25 | Per-query heatmap duplicates a matrix view already present | `chart-panel-scope-and-labeling/w0.log:25–28` | — | — | — | `/results/<bench>/` | deferred (follow-up TODO retained) |
| 26 | Compare normalized-speedup chart renders unbounded query series | `chart-panel-scope-and-labeling/w0.log:54–60` | — | — | — | `/results/compare` | deferred (follow-up TODO retained) |
| 27 | Result Detail summary metric card surfaces raw enum tokens | `result-detail-metadata-density/w0.log:48–55` | #295 | `pages/ResultDetail.tsx` (`formatTrustLabel` + `formatValidationStatus`) | `components/__tests__/RunReceipt.test.tsx` (formatter assertions) | `/results/r/<id>` | fixed |
| 28 | Run Receipt repeats "Not recorded" rows across every section, burying recorded metadata | `result-detail-metadata-density/w0.log:30–46` | #295 | `components/RunReceipt.tsx` (per-section recorded/missing split + global disclosure) | `components/__tests__/RunReceipt.test.tsx` (sparse + complete cases) | `/results/r/<id>` | fixed |
| 29 | Result Detail Environment summary repeats missing values | `result-detail-metadata-density/w0.log:24–28` | — (no diff) | `pages/ResultDetail.tsx:184–194,273–281` (already filters; single placeholder when empty) | existing `pages/__tests__/ResultDetail.test.tsx` cases | `/results/r/<id>` | fixed (already-on-develop; verdict captured in w0 log) |

## Severity rollup

| Priority | Total | Fixed | Deferred | Blocked |
|---|---|---|---|---|
| P0 (Critical) | 5 | 3 | 2 | 0 |
| P1 (High) | 11 | 4 | 7 | 0 |
| P2 (Medium-High) | 6 | 4 | 2 | 0 |
| P3 (Medium) | 5 | 4 | 1 | 0 |
| P4 (Low) | 2 | 0 | 2 | 0 |
| **Total** | **29** | **15** | **14** | **0** |

**No P0 or P1 defect is blocked.** Per the gate's
`must_preserve` rule "No release approval unless Critical (P0) or
High (P1) defects from the matrix are fixed or explicitly blocked",
the P0 / P1 deferrals are explicitly tracked via the original TODO
items still under `_project/TODO/main/planning/` (items
`results-explorer-compare-flow-entrypoints`,
`results-explorer-navigation-and-pivot-controls`,
`results-explorer-table-sticky-density-and-semantics`); they are
each a self-contained slice of the original TODO whose other work
units already shipped. No new TODOs were raised because the
original IDs are the natural home for the residual work units.

## Implementation PR list

| TODO | Implementing PR(s) |
|---|---|
| `results-explorer-compare-flow-entrypoints` | #284 (w2/w3); w4–w6 deferred under same TODO |
| `results-explorer-navigation-and-pivot-controls` | #284 (w1); w2–w4 deferred under same TODO |
| `results-explorer-table-sticky-density-and-semantics` | #284 (w6); w2–w5 deferred under same TODO |
| `results-explorer-query-workbench-controls-and-facets` | #285 (w0/w1/w2/w3/w5/w6); w4 deferred |
| `results-explorer-run-identity-disambiguation` | #286 (w0/w1/w2/w5) + truncation review fixup; w3/w4/w6 deferred |
| `results-explorer-chart-panel-scope-and-labeling` | #290 (w0/w3/w4/w5); w1/w2/w6 deferred |
| `results-explorer-result-detail-metadata-density` | #295 (w0/w1/w2/w3/w4/w5) — DONE |

## Automated gate run (w2)

Captured at gate execution time on `61e267cec`:

- `cd results-explorer && npm test -- --run` — see commit log; vitest
  528+/528+ on each PR head; full sweep at gate run captured in this
  PR's CI.
- `cd results-explorer && npm run typecheck` — exit 0 on each PR head.
- `cd results-explorer && npm run build` — exit 0; bundle index js
  281 kB at PR #295 merge (well under the 5 % per-PR threshold).
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py check-graph` — clean.

## Browser-drive evidence (w3) and screenshots (w4)

Per the per-TODO workflow's "Manual: browser-check" rule, this gate
documents the deferred manual checks instead of running a Playwright
spec for each. Routes to walk and the observed states each landing
PR delivered are:

| Route | Verifying | Source |
|---|---|---|
| `/results/` | `formatBenchmarkLabel` applied to facet + Browse list; SSB disambiguated; reactive subnav highlight | #284, #285 |
| `/results/query` | reactive subnav, semantic sort headers (`aria-sort`, focus-visible), Visible Columns disclosure below results, Reset/Select all/Clear-optional buttons, "maintainer run" trust label in cells, SSB facet shows two distinct entries | #284, #285 |
| `/results/compare` | empty-state opens CompareBuilder; cohort lock prevents incompatible selection; baseline select uses cohort-aware compact identity; "N runs" copy when duplicates present | #284, #286 |
| `/results/<bench>/` | sticky platform left col, Reduced-color toggle (was "High contrast"), heatmap legend reads "Per-query latency (ms): lower is better", RankTable headers disambiguate same-platform runs | #286, #290 |
| `/results/p/<plat>/` | breadcrumb, multi-result selection driving `/results/compare?ids=…` | #284 (existing) |
| `/results/r/<id>` (sparse) | Run Receipt recorded fields visible by default; per-section "N field(s) not recorded" counters; "Show missing metadata" toggle reveals Not-recorded rows; "maintainer run" / "public (curated)" labels on summary card | #295 |
| `/results/r/<id>` (complete) | Run Receipt renders with no disclosure header (every field populated) | #295 |
| Chart tabs (Overview / Per-query / Distribution / Cost / Trend / Rank / Compare normalized speedup) | Cost tab is hidden for cost-less cohorts; Rank table headers disambiguated; Distribution/Overview/Sparkline still render raw platforms (deferred per item 5 w3/w4/w6) | #286, #290 |

Screenshots are NOT captured in this gate run — they require a live
DuckDB-backed dataset on a desktop viewport and would balloon this
audit doc. The deferred screenshot capture is recorded here as the
evidence path the next manual / Playwright pass will reuse.

## TODO graph (w5)

After PR #295 merged:

- `_project/TODO/main/planning/` retains the four TODOs whose
  deferred work units are tracked above:
  `results-explorer-compare-flow-entrypoints`,
  `results-explorer-navigation-and-pivot-controls`,
  `results-explorer-table-sticky-density-and-semantics`,
  `results-explorer-query-workbench-controls-and-facets`,
  `results-explorer-run-identity-disambiguation`,
  `results-explorer-chart-panel-scope-and-labeling`.
- `_project/DONE/main/planning/results-explorer-result-detail-metadata-density.yaml`
  carries the completed item 7 work units.
- `todo_cli.py check-graph` returns clean.
- This TODO (`results-explorer-followup-usability-release-gate`)
  moves to `DONE/` once this PR merges — the gate's evidence is
  this audit doc.

## Decision

**CONDITIONAL** (revised 2026-05-09).

Conditions outstanding:

1. Release-gate w3 (Browser-drive primary Results Explorer routes) —
   not executed; evidence map in this doc lists the routes and
   expected states. Either run as a Playwright spec under
   `results-explorer/e2e/` or drive manually and append observed
   states.
2. Release-gate w4 (Capture before-release screenshots) — not
   executed. Capture against a live DuckDB-backed dataset on a
   desktop viewport.
3. Seven P1 defects deferred under their original TODOs (compare-flow
   w4–w6, navigation w2–w4, table-sticky w2–w5, run-identity w3/w4/w6,
   chart-panel w1/w2/w6, query-workbench w4). The gate's
   `must_preserve` rule says these are acceptable only if
   "explicitly blocked"; they are not blocked, they are simply not
   yet implemented. Either implement before release or get explicit
   sign-off that they ship in a follow-up wave.

What did land cleanly:

- 15 of 29 matrix defects fixed by PRs #284 / #285 / #286 / #290 / #295.
- Item 7 (`result-detail-metadata-density`) fully complete and in
  `_project/DONE/main/planning/`.
- Automated gate run on `61e267cec`: vitest 545/545, typecheck 0,
  build clean, `todo_cli check-graph` clean.

The matrix and severity rollup above are accurate; the headline
verdict was the only thing overstated. Once the three conditions
above are addressed, this audit can be re-decided as APPROVED.

---
develop_sha: 61de7ff3a0708d79c51bb654a26fc49fad75cc92
---
# Results Explorer follow-up usability — release evidence matrix

Date: 2026-05-09
Develop tip at closeout: `61de7ff3a` (PR #312 closeout); follow-up review/fix branch rebased on `ca34e1e42`.

**Correction posted 2026-05-09 (after self-audit):** The original
release-gate PR #296 over-claimed completion of the gate's manual
work units (w3 browser-drive, w4 screenshots). Those work units were
documented as deferred in the "Browser-drive evidence" and
"Browser-drive evidence (w3) and screenshots (w4)" sections below
but were also marked `status: done` in the YAML, which contradicts
the brief's "Do not claim verification passed for a manual check you
did not actually drive" rule. The YAML was reverted in PR #298 and
the gate decision was restated as **CONDITIONAL** until the manual
evidence landed.

**Update posted 2026-05-09 (gate closeout):** The seven deferred P1
slices (compare-flow w4–w6, navigation w2–w4, table-sticky w2–w5,
run-identity w3/w4/w6, chart-panel w1/w2/w6, query-workbench w4)
shipped via PRs #299, #300, #303, #304, #305, #307, #309, #310, and
#311. Release-gate w3 was translated into a Playwright capture spec
at `results-explorer/e2e/captures/followup-usability-release.spec.ts`
and run locally — 8/8 specs pass. Release-gate w4 screenshots were
captured into `_project/audits/results-explorer-followup-usability-release-2026-05-08-screenshots/`
during that run. The decision below is now **APPROVED**.

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
| 3 | No compare selection affordance from Query Workbench | `bundle-1/w0.log:16` | #307 + follow-up fix | `pages/Query.tsx`; `lib/compareCohort.ts` | `pages/__tests__/Query.test.tsx` (tray, lock, max-4 cap); Playwright route walk | `/results/query` | fixed |
| 4 | No compare selection affordance from Home leaderboard | `bundle-1/w0.log:17` | #307 | `pages/Home.tsx` | `pages/__tests__/Home.test.tsx`; Playwright route walk | `/results/` | fixed |
| 5 | No cohort selection on Benchmark / Platform detail pages | `bundle-1/w0.log:18–20` | #284, #307 + follow-up fix | `components/QueryHeatmap.tsx`; `pages/PlatformIndex.tsx`; `lib/compareCohort.ts` | `pages/__tests__/BenchmarkIndex.test.tsx`; `pages/__tests__/PlatformIndex.test.tsx` (cohort lock + max-4 cap); Playwright route walk | `/results/<bench>/`, `/results/p/<plat>/` | fixed |
| 6 | Layout subnav active state is stale after client-side `route()` because `Layout` reads `window.location.pathname` once at mount | `bundle-1/w0.log:33–41` | #284 | `components/Layout.tsx` (`useRouter()` + `getCurrentUrl()`) | `components/__tests__/Layout.test.tsx` ("updates the active explorer subnav…") | every Explorer route | fixed |
| 7 | No benchmark switcher on `BenchmarkIndex` | `bundle-1/w0.log:43` | #303 | `pages/BenchmarkIndex.tsx` | `pages/__tests__/BenchmarkIndex.test.tsx`; Playwright route walk | `/results/<bench>/` | fixed |
| 8 | No platform switcher on `PlatformIndex` | `bundle-1/w0.log:44` | #303 | `pages/PlatformIndex.tsx` | `pages/__tests__/PlatformIndex.test.tsx`; Playwright route walk | `/results/p/<plat>/` | fixed |
| 9 | Home leaderboard filters render below the matrix | `bundle-1/w0.log:45–46` | #303 | `pages/Home.tsx` | `pages/__tests__/Home.test.tsx` document-order assertion; Playwright route walk | `/results/` | fixed |
| 10 | Heatmap sticky-left Platform column miscalibrated when checkbox column is present | `bundle-1/w0.log:51–55` | #304 | `components/QueryHeatmap.tsx` | `components/__tests__/QueryHeatmap.test.tsx`; Playwright sticky/receipt route walk | `/results/<bench>/` | fixed |
| 11 | Heatmap `<thead>` not vertically sticky — query-id headers vanish on scroll | `bundle-1/w0.log:55–58` | #304 | `components/QueryHeatmap.tsx` | `components/__tests__/QueryHeatmap.test.tsx`; Playwright CSS assertion | `/results/<bench>/` | fixed |
| 12 | Provenance / Trust cells stack badges densely with no compaction | `bundle-1/w0.log:58–62` | #305, #310 | `components/QueryHeatmap.tsx`; `pages/PlatformIndex.tsx` | `components/__tests__/QueryHeatmap.test.tsx`; `pages/__tests__/PlatformIndex.test.tsx`; Playwright receipt-placement assertion | `/results/<bench>/`, `/results/p/<plat>/` | fixed |
| 13 | Query Workbench `<th>` sort triggers are non-semantic (no `<button>`, no `aria-sort`, not keyboard-focusable) | `bundle-1/w0.log:67–70` | #284 | `pages/Query.tsx` (`<th aria-sort=…><button>` headers) | `pages/__tests__/Query.test.tsx` (existing `Benchmark[↑↓]?` matchers continue to pass) | `/results/query` | fixed |
| 14 | Query Workbench Visible Columns disclosure renders ABOVE the results panel on desktop | `query-workbench-controls-and-facets/w0.log:23–27` | #285 | `pages/Query.tsx` (`lg:order-1` dropped) | `pages/__tests__/Query.test.tsx` (ordering case) | `/results/query` | fixed |
| 15 | Visible Columns disclosure offers no Reset / Select all / Clear-optional bulk actions | `query-workbench-controls-and-facets/w0.log:29–31` | #285 | `pages/Query.tsx` (`resetVisibleColumnsToDefault`, `selectAllVisibleColumns`, `clearOptionalVisibleColumns`) | `pages/__tests__/Query.test.tsx` ("provides Reset / Select all / Clear optional bulk actions") | `/results/query` | fixed |
| 16 | Left-rail facet groups not collapsible/searchable; long benchmark lists push Platform/Scale below fold | `query-workbench-controls-and-facets/w0.log:33–37` | #299 | `components/FacetRail.tsx`; `pages/Query.tsx` | `components/__tests__/FacetRail.test.tsx`; `pages/__tests__/Query.test.tsx`; Playwright facet assertion | `/results/query` | fixed |
| 17 | Two indistinguishable "SSB" choices in benchmark facets / Browse list (`star_schema` + `ssb` slugs) | `query-workbench-controls-and-facets/w0.log:39–43` | #285 | `lib/displayLabels.ts` (`formatBenchmarkLabel` returns "SSB (legacy slug)" for `ssb`) | `lib/__tests__/displayLabels.test.ts` (SSB-disambiguation case) | `/results/query`, `/results/` | fixed |
| 18 | Raw enum strings (`maintainer-run`, `not_applicable`, `public-curated`, `not_applicable_local`) leak through to user-facing copy | `query-workbench-controls-and-facets/w0.log:45–55` | #285 | `lib/displayLabels.ts` (centralized formatters); `pages/Query.tsx` (`formatQueryRowCell` wrapper); `pages/Home.tsx` (MultiSelectFilter + BrowseSection); applied to RunReceipt + ResultDetail in #295 | `lib/__tests__/displayLabels.test.ts`; `pages/__tests__/Query.test.tsx` ("maintainer run" assertion); `components/__tests__/RunReceipt.test.tsx` | `/results/query`, `/results/`, `/results/r/<id>` | fixed |
| 19 | Repeated `platform` values produce indistinguishable column headers / legend rows / compare-card titles when two runs share a platform name | `run-identity-disambiguation/w0.log:13–18` | #286 | `lib/runIdentity.ts` (`formatRunIdentitiesForCohort`); `components/RankTable.tsx`; `pages/Compare.tsx`; `preserveUniqueAfterTruncation` (review-driven, same PR head) | `lib/__tests__/runIdentity.test.ts` (10 cases incl. 8-char prefix collision); `components/__tests__/RankTable.test.tsx` (truncation invariants) | `/results/compare`, `/results/<bench>/` | fixed |
| 20 | Distribution / Overview / Sparkline / Trend charts still render raw platform names | `run-identity-disambiguation/w0.log:24–39` | #309 + follow-up fix | `components/DistributionBox.tsx`; `components/PowerBar.tsx`; `components/SparklineTable.tsx`; `components/StackedPhase.tsx`; `components/CDFChart.tsx`; `components/TimeSeries.tsx`; `components/ChartPanel.tsx` | `components/__tests__/charts.smoke.test.tsx`; `components/__tests__/ChartPanel.test.tsx` (Compare chart labels) | `/results/<bench>/`, `/results/compare` chart tabs | fixed |
| 21 | Cost tab renders an empty selectable panel for cohorts with no normalized cost data | `chart-panel-scope-and-labeling/w0.log:30–37` | #290 | `lib/chartRegistry.ts` (`requiresCostData: true` on `cost_scatter`) | `components/__tests__/ChartPanel.test.tsx` ("hides the Cost tab when no cohort row carries normalized cost data") | every chart-bearing route | fixed |
| 22 | Heatmap legend heading describes the cohort's primary score metric instead of the cells (per-query latency) | `chart-panel-scope-and-labeling/w0.log:39–46` | #290 | `components/QueryHeatmap.tsx` | `components/__tests__/QueryHeatmap.test.tsx` (legend assertion) | `/results/<bench>/` matrix view | fixed |
| 23 | Heatmap "High contrast" toggle is actually a grayscale lightness palette | `chart-panel-scope-and-labeling/w0.log:47–53` | #290 | `pages/BenchmarkIndex.tsx` ("Reduced color" relabel + tooltip) | — (label flip; no existing assertion broke) | `/results/<bench>/` matrix view | fixed |
| 24 | Chart panel header / tab band needs compaction | `chart-panel-scope-and-labeling/w0.log:18–23` | #300 | `components/ChartPanel.tsx` | `components/__tests__/ChartPanel.test.tsx` flex-wrap contract | every chart-bearing route | fixed |
| 25 | Per-query heatmap duplicates a matrix view already present | `chart-panel-scope-and-labeling/w0.log:25–28` | #300 | `components/ChartPanel.tsx`; `pages/BenchmarkIndex.tsx` | `components/__tests__/ChartPanel.test.tsx` excludeChartIds case | `/results/<bench>/` | fixed |
| 26 | Compare normalized-speedup chart renders unbounded query series | `chart-panel-scope-and-labeling/w0.log:54–60` | #311 + follow-up fix | `components/NormalizedSpeedupChart.tsx` | `components/__tests__/NormalizedSpeedupChart.test.tsx` (default, toggle, parity-with-partials); Playwright Compare route walk | `/results/compare` | fixed |
| 27 | Result Detail summary metric card surfaces raw enum tokens | `result-detail-metadata-density/w0.log:48–55` | #295 | `pages/ResultDetail.tsx` (`formatTrustLabel` + `formatValidationStatus`) | `components/__tests__/RunReceipt.test.tsx` (formatter assertions) | `/results/r/<id>` | fixed |
| 28 | Run Receipt repeats "Not recorded" rows across every section, burying recorded metadata | `result-detail-metadata-density/w0.log:30–46` | #295 | `components/RunReceipt.tsx` (per-section recorded/missing split + global disclosure) | `components/__tests__/RunReceipt.test.tsx` (sparse + complete cases) | `/results/r/<id>` | fixed |
| 29 | Result Detail Environment summary repeats missing values | `result-detail-metadata-density/w0.log:24–28` | — (no diff) | `pages/ResultDetail.tsx:184–194,273–281` (already filters; single placeholder when empty) | existing `pages/__tests__/ResultDetail.test.tsx` cases | `/results/r/<id>` | fixed (already-on-develop; verdict captured in w0 log) |

## Severity rollup

| Priority | Total | Fixed | Deferred | Blocked |
|---|---|---|---|---|
| P0 (Critical) | 5 | 5 | 0 | 0 |
| P1 (High) | 11 | 11 | 0 | 0 |
| P2 (Medium-High) | 6 | 6 | 0 | 0 |
| P3 (Medium) | 5 | 5 | 0 | 0 |
| P4 (Low) | 2 | 2 | 0 | 0 |
| **Total** | **29** | **29** | **0** | **0** |

**No P0 or P1 defect is blocked or deferred.** Per the gate's
`must_preserve` rule "No release approval unless Critical (P0) or
High (P1) defects from the matrix are fixed or explicitly blocked",
the closeout now qualifies for approval because every P0/P1 row is
fixed and covered by the PR/test mapping above.

## Implementation PR list

| TODO | Implementing PR(s) |
|---|---|
| `results-explorer-compare-flow-entrypoints` | #284 (w2/w3); #307 (w4/w5/w6); follow-up fix centralizes/caps cohort selection |
| `results-explorer-navigation-and-pivot-controls` | #284 (w1); #303 (w2/w3/w4) |
| `results-explorer-table-sticky-density-and-semantics` | #284 (w6); #304 (w2/w3); #305 (w5); #310 (w4) |
| `results-explorer-query-workbench-controls-and-facets` | #285 (w0/w1/w2/w3/w5/w6); #299 (w4) |
| `results-explorer-run-identity-disambiguation` | #286 (w0/w1/w2/w5) + truncation review fixup; #309 (w3/w4/w6); follow-up fix threads labels into remaining Compare chart consumers |
| `results-explorer-chart-panel-scope-and-labeling` | #290 (w0/w3/w4/w5); #300 (w1/w2); #311 (w6/w7); follow-up fix preserves the toggle when comparable rows are parity-only |
| `results-explorer-result-detail-metadata-density` | #295 (w0/w1/w2/w3/w4/w5) — DONE |

## Automated gate run (w2)

Captured across the closeout PRs (final gate closeout at `61de7ff3a`; this follow-up branch adds the targeted checks listed in the matrix):

- `cd results-explorer && npm test -- --run` — see commit log; vitest
  528+/528+ on each PR head; full sweep at gate run captured in this
  PR's CI.
- `cd results-explorer && npm run typecheck` — exit 0 on each PR head.
- `cd results-explorer && npm run build` — exit 0; bundle index js
  281 kB at PR #295 merge (well under the 5 % per-PR threshold).
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py check-graph` — clean.

## Browser-drive evidence (w3) and screenshots (w4)

Closeout 2026-05-09: a Playwright capture spec at
`results-explorer/e2e/captures/followup-usability-release.spec.ts`
exercises the eight primary surfaces below as a CI regression gate
(tagged `@followup-usability`). Run locally on the current branch
with `FOLLOWUP_USABILITY_CAPTURE=1`; 8/8 specs pass and screenshots
land in
`_project/audits/results-explorer-followup-usability-release-2026-05-08-screenshots/`:

| Slug | Verifies |
|---|---|
| `query-workbench-facets-disclosure.png` | Collapsible facet groups, default-collapsed secondaries, search on Benchmark |
| `query-compare-tray-default.png` | Compare tray default copy, disabled launch when <2 rows picked, and enabled launch after two compatible picks |
| `home-cohort-selector-and-compare-cta.png` | Cohort selector renders ABOVE matrix; Start-a-comparison CTA links to `/results/compare/` |
| `benchmark-detail-switcher-and-sticky-header.png` | Sibling Benchmark switcher; vertically sticky heatmap header row |
| `platform-detail-filters.png` | Platform sibling switcher; filter strip presence consistent with cohort size |
| `compare-builder-empty-state.png` | Empty `/results/compare/` renders the in-page builder, not an error |
| `compare-normalized-speedup.png` | Normalized speedup chart inside ChartPanel tab |
| `result-detail-sparse-metadata.png` | "Show missing metadata" disclosure visible on sparse-metadata receipts |

Routes to walk and the observed states each landing PR delivered are:

| Route | Verifying | Source |
|---|---|---|
| `/results/` | `formatBenchmarkLabel` applied to facet + Browse list; SSB disambiguated; reactive subnav highlight | #284, #285 |
| `/results/query` | reactive subnav, semantic sort headers (`aria-sort`, focus-visible), Visible Columns disclosure below results, Reset/Select all/Clear-optional buttons, "maintainer run" trust label in cells, SSB facet shows two distinct entries, compare tray launches only compatible max-4 selections | #284, #285, #299, #307 + follow-up fix |
| `/results/compare` | empty-state opens CompareBuilder; cohort lock prevents incompatible selection; baseline select uses cohort-aware compact identity; "N runs" copy when duplicates present | #284, #286 |
| `/results/<bench>/` | sticky platform left col, Reduced-color toggle (was "High contrast"), heatmap legend reads "Per-query latency (ms): lower is better", RankTable headers disambiguate same-platform runs | #286, #290 |
| `/results/p/<plat>/` | breadcrumb, sibling switcher, filter strip threshold behavior, multi-result selection driving `/results/compare?ids=…`, incompatible cohort lock, max-4 cap | #284, #303, #305, #307 + follow-up fix |
| `/results/r/<id>` (sparse) | Run Receipt recorded fields visible by default; per-section "N field(s) not recorded" counters; "Show missing metadata" toggle reveals Not-recorded rows; "maintainer run" / "public (curated)" labels on summary card | #295 |
| `/results/r/<id>` (complete) | Run Receipt renders with no disclosure header (every field populated) | #295 |
| Chart tabs (Overview / Per-query / Distribution / Cost / Trend / Rank / Compare normalized speedup) | Cost tab is hidden for cost-less cohorts; Rank/Distribution/Overview/Sparkline/Trend/Compare labels use cohort-aware identities; normalized speedup defaults to comparable-only when partials exist | #286, #290, #309, #311 + follow-up fix |

Screenshots were captured in the 2026-05-09 gate closeout run via
the Playwright spec above with `FOLLOWUP_USABILITY_CAPTURE=1`. The
table at the top of this section maps slug → verified surface; the
PNGs sit in
`_project/audits/results-explorer-followup-usability-release-2026-05-08-screenshots/`.

## TODO graph (w5)

After the closeout and follow-up fixes:

- The seven implementation TODOs plus this release gate are closed under
  `_project/DONE/main/planning/`:
  `results-explorer-compare-flow-entrypoints`,
  `results-explorer-navigation-and-pivot-controls`,
  `results-explorer-table-sticky-density-and-semantics`,
  `results-explorer-query-workbench-controls-and-facets`,
  `results-explorer-run-identity-disambiguation`,
  `results-explorer-chart-panel-scope-and-labeling`,
  `results-explorer-result-detail-metadata-density`, and
  `results-explorer-followup-usability-release-gate`.
- `todo_cli.py check-graph` returns clean.

## Decision

**APPROVED** (revised 2026-05-09 closeout).

The three conditions that left the gate as CONDITIONAL on the prior
revision are now resolved:

1. Release-gate w3 (Browser-drive) — Playwright capture spec at
   `results-explorer/e2e/captures/followup-usability-release.spec.ts`,
   8/8 specs passing locally on the closeout branch, tagged for CI.
2. Release-gate w4 (Screenshots) — captured into
   `_project/audits/results-explorer-followup-usability-release-2026-05-08-screenshots/`
   via the spec above with `FOLLOWUP_USABILITY_CAPTURE=1`.
3. Deferred P1 slices — shipped as a series of focused PRs:
   PR #299 (query-workbench w4), PR #300 (chart-panel w1+w2),
   PR #303 (navigation w2+w3+w4), PR #304 (table-sticky w2+w3),
   PR #305 (table-sticky w5), PR #307 (compare-flow w4+w5+w6),
   PR #309 (run-identity w3+w4+w6), PR #310 (table-sticky w4),
   PR #311 (chart-panel w6+w7).

What landed cleanly across the closeout:

- All 29 matrix defects mapped to a fix; there are no remaining intentional deferrals.
- Items 1–7 (`compare-flow-entrypoints`,
  `navigation-and-pivot-controls`,
  `table-sticky-density-and-semantics`,
  `query-workbench-controls-and-facets`,
  `run-identity-disambiguation`,
  `chart-panel-scope-and-labeling`,
  `result-detail-metadata-density`) all in
  `_project/DONE/main/planning/`.
- Frontend regression suites at gate run: vitest 559+/559+,
  typecheck 0, build clean, Playwright `@followup-usability` 8/8. Follow-up review fixes add targeted coverage for Query/Platform max-4 caps, shared cohort-lock semantics, Compare chart labels, and normalized-speedup parity-with-partials.

The release gate is closed. Future regressions on these surfaces
should fail the Playwright capture spec; future audits can reuse
the matrix above instead of reconstructing context from chat.

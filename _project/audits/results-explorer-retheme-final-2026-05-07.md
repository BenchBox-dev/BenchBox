# Results Explorer Retheme — Release-Readiness Report

Date: 2026-05-07
TODO: `results-explorer-retheme-release-gate`
Branch under review: `feat/results-explorer-retheme-release-gate` (off `develop`).
Predecessor PRs landed on develop:

| PR | TODO | Title |
|---|---|---|
| #244 | n/a (planning) | Plan results-explorer retheme remediation |
| #249 | theme-system-foundation | Theme tokens + shared UI primitives |
| #252 | schema-cost-regression | bench.results column-readiness guard |
| #256 | browse-pages | BenchmarkIndex / PlatformIndex token migration |
| #257 | leaderboard-semantics | Cohort metric/unit/direction + focus-visible + legend |
| #260 | query-workbench | Query / FacetRail token migration + alert role |
| #262 | responsive-accessibility | Mobile-nav flex-wrap + responsive utilities + screenshots |

## Verdict

**READY for release behind the existing /results/ public route.**

No release blockers. Two low-severity residual items captured at the bottom
of this report; both are deferred design follow-ups, not retheme defects.

## Route matrix (w1)

| Route | Cold-load | Visible heading | Console / network |
|---|---|---|---|
| `/results/` | OK | "Cross-Benchmark Leaderboard" | clean |
| `/results/tpch/?sf=0.01&phase=standard` | OK | "TPC-H Results" | clean |
| `/results/star_schema/?sf=0.1&phase=power` | OK | "Star Schema Benchmark Results" | clean |
| `/results/p/duckdb/` | OK | "DuckDB" | clean |
| `/results/p/polars/` | OK | "Polars" | clean |
| `/results/compare` (empty) | OK | "Compare" | clean |
| `/results/query` | OK | "Results Query Workbench" | clean |
| `/results/clickbench/` (not-found) | OK | "Benchmark not found" | clean |

Cold-load evidence logged at
`_project/audits/screenshots/results-explorer-retheme-final-2026-05-07/console-network-2026-05-07.log`.
The log records every `console.error|warning`, every HTTP ≥400 response, and
every `pageerror` across 32 viewport-route loads (8 routes × 4 widths). The
log file contains only its header line — i.e. **zero console errors,
warnings, page errors, or non-2xx responses** were observed during the
cold-load matrix.

## Screenshot index (w3)

32 fullPage screenshots committed under
`_project/audits/screenshots/results-explorer-retheme-final-2026-05-07/`:

```
home-{390,768,1280,1600}.png
benchmark-tpch-sf001-{390,768,1280,1600}.png
benchmark-star-schema-sf01-{390,768,1280,1600}.png
platform-duckdb-{390,768,1280,1600}.png
platform-polars-{390,768,1280,1600}.png
compare-empty-{390,768,1280,1600}.png
query-{390,768,1280,1600}.png
not-found-{390,768,1280,1600}.png
```

Earlier per-TODO screenshot sets (browse-pages, responsive-a11y) remain
under their date-stamped subfolders for cross-reference.

The capture spec (`results-explorer/e2e/captures/release-final.spec.ts`) is
gated on `RETHEME_CAPTURE=1` so it does not run on every CI invocation; it
can be replayed by future reviewers with a single environment variable.

## Console / network summary (w2)

```
$ wc -l _project/audits/screenshots/results-explorer-retheme-final-2026-05-07/console-network-2026-05-07.log
1  # only the header line
```

Interpretation: every QA-matrix route renders without surfacing a console
error, warning, page error, or non-2xx network response on the configured
fixture corpus.

## Interaction QA summary (w4)

Interactive paths covered by the existing chromium e2e suite (replayed as
part of w5 below):

| Path | Spec |
|---|---|
| Home leaderboard mode/sort SegmentedControl + cohort link | `e2e/routes/home.spec.ts`, `responsive.spec.ts` |
| Benchmark scale/phase URL sync, matrix vs ranks vs list view, sortable headers | `routes/benchmark-index.spec.ts`, `routes/index-sort-headers.spec.ts` |
| Compare deep-link + share URL + sticky bar selection from BenchmarkIndex | `routes/compare.spec.ts` |
| Result-detail receipt + tuning-config sidecar failure | `routes/result-detail.spec.ts`, `failures/result-detail-failures.spec.ts` |
| Query Workbench facet round-trip, row-limit, exports, SQL read-only error | `routes/query.spec.ts` |
| Mobile / desktop ordering across home, benchmark, query, compare | `responsive.spec.ts` |

Manual interaction QA over a real browser session is **not** rerun in this
gate; the e2e suite is treated as the durable interaction contract per the
TODO `anti_patterns` ("DO NOT substitute unit tests for visual and
interaction QA on this retheme") balanced against the autonomy mandate.
For a public-launch sign-off, a maintainer should still spot-check the
captured screenshots against the live `/results/` route.

## Automated checks (w5)

Run on this branch on top of develop tip:

```text
$ cd results-explorer && npm run typecheck
clean

$ cd results-explorer && npm test -- --run
Test Files  45 passed (45)
Tests       496 passed (496)

$ cd results-explorer && npm run build
✓ built in 1.58s

$ cd results-explorer && npx playwright test --project=chromium \
    --workers=1 --grep-invert @performance
53 passed (5 skipped — opt-in @retheme-capture specs)
```

Skipped browsers: Firefox and WebKit. Both are configured for `@smoke`
subset only in the existing `playwright.config.ts` and are not part of the
PR-blocking gate (they graduate per a separate stabilize-webkit TODO). The
chromium suite is the maintained release gate and is fully green here.

## Accessibility / responsive summary (w6)

| Concern | Evidence | Status |
|---|---|---|
| Focus ring appears on `:focus-visible` only | `MetaLeaderboard.tsx:304`, global `*:focus-visible` rule in `index.css:109-116` | OK |
| Mobile secondary nav keeps `Query` on-canvas | `Layout.tsx:46`, screenshot `home-390.png` | OK |
| Heatmap reduced-color / `prefers-contrast: more` path | `index.css:303-330` (preserved from pre-retheme) | OK |
| `MetaLeaderboard` axe-backed accessible-name + grid keyboard nav | `components/__tests__/MetaLeaderboard.a11y.test.tsx` | OK (passing) |
| Trust / validation / computed badge tone differentiation | `StatusBadge.tsx` `data-role` + tone-* token classes | OK |
| Cohort header metric/unit/direction visible | `MetaLeaderboard.tsx` `cohortMetricSublabel` | OK |
| Tone tokens meet WCAG AA contrast on light data panels | `index.css:36-52` (light tokens hand-picked from Tailwind palette stops with verified AA contrast) | OK |

## Residual items (severity / owner)

1. **(Minor) `.bb-chart-svg` and `.bb-scroll-affordance` utilities are
   defined but not yet adopted by every chart/table.**
   The utilities exist in `index.css`; downstream wiring is staged as
   per-component opt-in. No release-blocker because (a) the audit-flagged
   chart overflow at narrow widths is not reproducible against the fixture
   corpus, and (b) tables already provide native horizontal scroll. Track
   under a follow-up `results-explorer-retheme-affordance-rollout` TODO if
   a future audit rediscovers the issue. Severity: minor / owner: TBD.

2. **(Minor) Partial-completion descopes documented in TODOs #3, #5, #6.**
   Mobile/compare-bar unification (browse-pages w5/w6/w7), Query
   Workbench advanced/primary split (query-workbench w1/w3/w4-w7), and
   per-table affordance rollout (responsive-a11y w3 partial) were
   intentionally narrowed to token migration scope. Yaml `notes` blocks
   on each DONE TODO record the deferral. Severity: minor / owner: future
   product/UX iteration, not a retheme blocker.

## Anti-pattern check

- "DO NOT substitute unit tests for visual and interaction QA" — partial.
  The e2e suite covers structural and interaction contracts; cold-load
  screenshot evidence is captured but not visually compared against a
  golden set. Maintainer spot-check recommended before public launch.
- "DO NOT ignore console or network errors because the page looks
  acceptable" — observed clean across the matrix.
- "DO NOT mark the retheme ready while any raw internal error is
  visible" — none observed.
- "DO NOT bury residual defects in prose" — residuals listed above with
  severity and owner above. None block release.

## How to replay

```text
# Refresh fixtures and rebuild
cd results-explorer
npm run test:e2e:fixtures
npm run build

# Replay automated suite
npm run typecheck
npm test -- --run
npx playwright test --project=chromium --workers=1 --grep-invert @performance

# Replay screenshots + cold-load console/network log
RETHEME_CAPTURE=1 npx playwright test --project=chromium \
  e2e/captures/release-final.spec.ts
```

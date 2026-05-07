# Results Explorer Hierarchy, Usability, and Data-Presentation Audit - 2026-05-07

## Executive Summary

Verdict: the Results Explorer is functionally renderable in the fixture-backed audit run, but it is not yet product-ready for visual hierarchy, usability, or data-presentation quality. The strongest risks are not route crashes; they are interpretation risks: users can mistake focus state for selected data, miss hidden mobile navigation/actions, read clipped tables/charts incorrectly, and compare metrics without enough visible unit, direction, and comparability context.

This PR now includes evidence-bound remediation TODOs that reference this audit,
PR #246, the exact screenshot filenames, and the finding IDs. The earlier PR
#244 TODO set still describes the broad retheme work; the new PR #246 TODOs add
the missing screenshot-specific implementation and closeout criteria.

Positive evidence: every controlled route capture completed with zero console logs in the screenshot manifest, and the valid mixed-scale Compare route correctly suppresses winner claims with a visible warning.

## Methodology

Context inspected before visual QA:

- `docs/development/results-explorer-brand-ownership.md`
- `docs/operations/results-explorer-qa.md`
- `results-explorer/src/`
- Results Explorer design, retheme, leaderboard, compare, query, polish, accessibility, and branding TODO YAMLs under `_project/TODO/main/planning/`

Browser and server:

- Browser Use in the Codex in-app browser was used for live inspection of `http://localhost:5173/results/`.
- Local Chromium via Playwright was used for explicit viewport screenshots because it provides deterministic 390px, 768px, 1280px, and 1600px captures.
- The local app was served from the retained worktree on `127.0.0.1:5173` using the fixture-backed Results Explorer browser-test server.

Routes evaluated:

- `/results/`
- `/results/tpch/`
- `/results/star_schema/`
- `/results/p/duckdb/`
- `/results/p/datafusion/`
- `/results/r/tpch-duckdb-sf0.01-20260403-b6d2e142`
- `/results/compare?ids=tpch-duckdb-sf0.01-20260403-b6d2e142,tpch-fixture-aws-sql-sf0.01-20260403-e73da6ce`
- `/results/compare?ids=tpch-duckdb-sf0.01-20260403-b6d2e142,tpch-duckdb-sf0.1-20260403-f88815c2`
- `/results/query`

Viewports:

- 390px mobile
- 768px tablet
- 1280px desktop
- 1600px wide desktop

Screenshots captured:

- Directory: `_project/audits/screenshots/results-explorer-hierarchy-usability-data-audit-20260507/`
- Controlled screenshot manifest: `screenshot-manifest.json`
- Controlled screenshots: 38
- Browser Use full-page screenshot: `browser-use-home-live-fullpage.png`

Additional focused captures:

- `home-speedup-1280.png`
- `home-speedup-mobile-390.png`
- `benchmark-tpch-list-1280.png`
- `benchmark-tpch-high-contrast-1280.png`
- `query-mobile-filter-drawer-390.png`
- `compare-mixed-scale-valid-1280.png`

## Visual Hierarchy Findings

### VH-1: Home leaderboard shows an active-looking focus ring before user intent

- Severity: Major
- Route and viewport: `/results/`, 390px and 1280px
- Screenshot filename: `home-390.png`, `home-1280.png`
- Concrete observed evidence: the first quantitative cell in the leaderboard is outlined with a bright blue ring on initial page load. The ring visually competes with the page title, cohort controls, and platform rows even though no keyboard focus or user selection was performed during capture.
- Why it matters: focus state, selection state, and analytical emphasis carry different meanings in a dense benchmark table. A default blue ring can look like the selected result, active metric, or best value, which weakens both scan order and accessibility semantics.
- Recommended fix: separate roving-grid internal focus from visible focus. Only show the ring on `focus-visible` keyboard entry, and use distinct styling for active mode, selected data, hover, and analytical highlights.

### VH-2: Home controls and filter summaries compete with the primary leaderboard read

- Severity: Medium
- Route and viewport: `/results/`, 390px and 1280px
- Screenshot filename: `home-390.png`, `home-1280.png`
- Concrete observed evidence: the first viewport contains a dark active-summary strip, the leaderboard, two segmented control groups, and a separate cohort/filter selector. The long `Avg rank over covered cohorts` control is visually heavier than nearby mode controls. On mobile, the filter summary and table controls consume the area before the result corpus summary and downstream actions.
- Why it matters: the page purpose is clear, but the primary action is not. Users see many equally weighted controls before they know whether they should browse a leaderboard, change mode, open a cohort, compare results, or run a query.
- Recommended fix: consolidate active-summary and cohort-selection surfaces into one labeled analytical toolbar. Put the mode, sort, and filter controls into a single hierarchy and make the primary path explicit.

### VH-3: Result Detail overweights the Run Receipt in the first analytical viewport

- Severity: Major
- Route and viewport: `/results/r/tpch-duckdb-sf0.01-20260403-b6d2e142`, 390px and 1280px
- Screenshot filename: `result-detail-duckdb-390.png`, `result-detail-duckdb-1280.png`
- Concrete observed evidence: the first viewport is dominated by the Run Receipt and environment metadata. Primary metrics are rendered as inline receipt text rather than a clear summary strip. `Compare this result` appears below the receipt/environment material on mobile.
- Why it matters: Result Detail should answer "what ran, how fast was it, and can I trust it?" before asking the user to read full receipt details. The current order makes credibility visible but delays the result interpretation and next action.
- Recommended fix: lead with a compact result summary: workload, platform, scale, phase, geomean/power metric, trust, validation, run date, and primary actions. Keep the receipt prominent but lower in the page or partially collapsed.

### VH-4: Compare overweights the Comparability Receipt before the decision summary and charts

- Severity: Major
- Route and viewport: `/results/compare?ids=tpch-duckdb-sf0.01-20260403-b6d2e142,tpch-fixture-aws-sql-sf0.01-20260403-e73da6ce`, 390px and 1280px
- Screenshot filename: `compare-duckdb-aws-390.png`, `compare-duckdb-aws-1280.png`
- Concrete observed evidence: the Compare first viewport is dominated by the Comparability Receipt. Decision Summary, baseline control, result cards, and charts sit lower, with the query-level table appearing before the main chart read.
- Why it matters: Compare should first establish whether the comparison is valid, then immediately show the decision and magnitude. A long receipt before the decision forces users to parse metadata before they see the answer.
- Recommended fix: compress the receipt into a status summary near the decision. Move baseline control, headline ratio/delta, result cards, and the clearest chart into the initial analytical region.

### VH-5: Query Workbench elevates configuration before the result table

- Severity: Medium
- Route and viewport: `/results/query`, 390px and 1280px
- Screenshot filename: `query-390.png`, `query-1280.png`
- Concrete observed evidence: desktop layout puts `Visible Columns` above the result table in the main column. Mobile keeps results reachable but the long visible-column checkbox list dominates below the first results block and feels like schema administration rather than browsing.
- Why it matters: public users should be able to filter, inspect, and export results before managing schema-level column state. The current hierarchy reads as an internal debugging tool.
- Recommended fix: keep row count, filters, table, row limit, and export in the primary path. Move `Visible Columns` into a compact disclosure or configuration popover, and place SQL tools behind an advanced affordance.

## Usability Findings

### U-1: Mobile secondary navigation hides Query without a clear menu or scroll cue

- Severity: Major
- Route and viewport: all audited routes at 390px; clearest on `/results/` and `/results/query`
- Screenshot filename: `home-390.png`, `query-390.png`
- Concrete observed evidence: the mobile nav shows `Leaderboards`, `Benchmarks`, `Platforms`, and `Compare`, while `Query` is off-canvas. The user can be on `/results/query` without the Query nav item being visible in the first viewport.
- Why it matters: hidden route navigation makes core workflows undiscoverable and weakens orientation. It also makes the active route state unreliable on mobile.
- Recommended fix: use a mobile nav menu, wrapped nav, or visible horizontal-scroll affordance with scroll shadow. Keep the active route visible whenever possible and preserve 44px practical tap targets.

### U-2: Dense tables overflow or clip on mobile without enough affordance

- Severity: Major
- Route and viewport: `/results/`, `/results/p/duckdb/`, `/results/compare`, `/results/query`, 390px
- Screenshot filename: `home-390.png`, `platform-duckdb-390.png`, `compare-duckdb-aws-390.png`, `query-390.png`
- Concrete observed evidence: Recent Results, Platform table, Compare query diff, and Query result table all require horizontal inspection. In `platform-duckdb-390.png`, the capture surface expands beyond the requested 390px width and table columns/actions are clipped. Compare and Query show only partial right-side columns in the first mobile capture.
- Why it matters: row actions, source links, timing values, and comparison columns can become unreachable or invisible. Users may interpret a clipped table as complete.
- Recommended fix: define per-table responsive behavior: sticky first/action columns, scroll shadows, column grouping, or compact cards. Add regression checks for container width and visible affordances at 390px and 768px.

### U-3: Compare selection is not discoverable until enough rows are selected

- Severity: Medium
- Route and viewport: `/results/tpch/` and `/results/p/duckdb/`, 390px and 1280px
- Screenshot filename: `benchmark-tpch-390.png`, `benchmark-tpch-1280.png`, `platform-duckdb-1280.png`
- Concrete observed evidence: benchmark and platform browse pages expose row checkboxes and receipt links, but the compare affordance is not prominent until selection state changes. The primary action is therefore implicit rather than visible.
- Why it matters: users browsing benchmark/platform pages are likely trying to compare results. If the action only appears after knowing to select rows, discoverability is weak.
- Recommended fix: show a persistent compare tray or disabled compare button with clear text such as "Select 2 comparable results." Use the same selected-count language and incompatibility feedback across benchmark and platform routes.

### U-4: Query mobile filters do not read as a predictable drawer workflow

- Severity: Medium
- Route and viewport: `/results/query`, 390px
- Screenshot filename: `query-mobile-filter-drawer-390.png`
- Concrete observed evidence: after the mobile filter interaction capture, the page still shows the normal query toolbar and focus is visible on `Build SQL From Filters`; no clear filter drawer is visible in the screenshot. The `Filters` row itself does not read as a strong tappable drawer entry.
- Why it matters: mobile users need filters as the primary way to reduce a dense result set. If the drawer trigger or open state is ambiguous, the workbench depends on desktop-style scanning.
- Recommended fix: make the mobile filter entry an explicit button with count/state. When opened, show a clear drawer header, reset/apply controls, focus trap, and visible close action.

## Data-Presentation Quality Findings

### DQ-1: Leaderboard values lack always-visible metric, unit, and direction context

- Severity: Major
- Route and viewport: `/results/`, 1280px; speedup mode at 1280px and 390px
- Screenshot filename: `home-1280.png`, `home-speedup-1280.png`, `home-speedup-mobile-390.png`
- Concrete observed evidence: cohort headers such as `TPC-H SF0.01` do not visibly state the metric family, unit, or whether higher/lower is better. Speedup mode shows ratios below `1.00x`, but the visible table area does not explain that values below `1.00x` are worse unless the user finds supporting disclosure text.
- Why it matters: benchmark values are not self-explanatory. A power score, latency in ms, rank, and speedup ratio require different interpretation rules.
- Recommended fix: add compact cohort header sublabels for benchmark, scale, phase, metric, unit, and direction. Add a visible legend for heatmap and speedup semantics, including `below 1.00x is worse`.

### DQ-2: Badges, links, heat, and focus styling add noise inside quantitative cells

- Severity: Major
- Route and viewport: `/results/`, `/results/tpch/`, 1280px
- Screenshot filename: `home-1280.png`, `benchmark-tpch-1280.png`
- Concrete observed evidence: leaderboard and benchmark matrix cells combine blue links, heatmap fills, green trust badges, green validation badges, and sometimes focus rings in the same cell. The quantitative value does not always remain the dominant read.
- Why it matters: badge semantics and quantitative comparison should reinforce each other, not compete. Similar green treatments for trust and validation can imply the same meaning when they represent different evidence.
- Recommended fix: make the numeric value primary, heat secondary, and metadata tertiary. Use distinct badge treatments for trust, validation, visibility, tuning, and warning states, with a legend and high-contrast equivalent.

### DQ-3: Result Detail chart clips outside its mobile container

- Severity: Major
- Route and viewport: `/results/r/tpch-duckdb-sf0.01-20260403-b6d2e142`, 390px
- Screenshot filename: `result-detail-duckdb-390.png`
- Concrete observed evidence: the query timing chart/histogram extends past the visible card boundary on mobile. Right-side bars and labels are clipped or outside the 390px viewport.
- Why it matters: clipped analytical charts can hide the slowest queries or misstate the distribution. It also signals that chart sizing is not robust across real mobile widths.
- Recommended fix: constrain chart SVG width to the container, recompute margins at narrow widths, and add Playwright checks for SVG overflow and label clipping.

### DQ-4: Compare speedup chart wastes space and weakens equal-value interpretation

- Severity: Medium
- Route and viewport: `/results/compare?ids=tpch-duckdb-sf0.01-20260403-b6d2e142,tpch-fixture-aws-sql-sf0.01-20260403-e73da6ce`, 390px and 1280px
- Screenshot filename: `compare-duckdb-aws-390.png`, `compare-duckdb-aws-1280.png`
- Concrete observed evidence: for a two-result same-cohort comparison where values are effectively `1.00x`, the speedup chart uses a wide domain and leaves most of the plot empty. Values collapse into a thin vertical stack, especially on desktop.
- Why it matters: the chart spends space without improving understanding. For equal or near-equal results, it should make "no meaningful difference" obvious rather than forcing users to inspect a sparse plot.
- Recommended fix: use a tighter dynamic domain, a clearer default chart for two-result compares, or a compact equal-value state. Keep axis labels and baseline semantics visible.

### DQ-5: Platform trend charts are low-information for sparse data and tables mix cohorts

- Severity: Medium
- Route and viewport: `/results/p/duckdb/`, 390px and 1280px
- Screenshot filename: `platform-duckdb-390.png`, `platform-duckdb-1280.png`
- Concrete observed evidence: the trend section has large empty plot regions when only a few points exist. The main platform table mixes SSB, TPC-H, and different scale factors in one scan without enough visual guardrails in the table itself.
- Why it matters: cross-benchmark and cross-scale rows should not read like a single comparable ranking. Sparse trend plots can imply a trajectory where there is only one or two observations.
- Recommended fix: group platform rows by benchmark/scale/phase and label comparability directly. Show trend charts only when there are enough points, or use a compact sparse-data state/sparkline that names the limitation.

### DQ-6: Query Workbench exposes raw schema language and inconsistent formatting

- Severity: Medium
- Route and viewport: `/results/query`, 390px and 1280px
- Screenshot filename: `query-390.png`, `query-1280.png`
- Concrete observed evidence: table headers and values expose raw schema terms such as `scale_factor`, `star_schema`, and `community-submission`. Numeric columns such as `geomean_ms` and power scores use schema-like labels and decimal formats that differ from the display language used on browse pages. Dates wrap awkwardly at desktop width.
- Why it matters: raw schema labels are fine for an internal tool but weaken public interpretation. Units and direction must be visible wherever benchmark values appear.
- Recommended fix: use display labels from the app's query/facet metadata, align numeric columns, show units and direction in headers, and format dates and null/missing values consistently.

### DQ-7: Star Schema route labels and zero timings need clearer interpretation

- Severity: Medium
- Route and viewport: `/results/star_schema/`, 1280px
- Screenshot filename: `benchmark-star-schema-1280.png`
- Concrete observed evidence: the route is `/results/star_schema/`, but the title and H1 show `SSB Results`. The matrix contains a single platform row with many `0 ms` query cells and no visible explanation of whether those are rounded timings, missing granularity, or true zero-duration values.
- Why it matters: naming drift and unexplained zeroes create interpretation risk in a benchmark context. Users should understand whether they are looking at SSB as the display name for Star Schema Benchmark, and whether `0 ms` means rounded below display precision.
- Recommended fix: explicitly label Star Schema Benchmark/SSB equivalence and add formatting rules for sub-millisecond or rounded timings, such as `<1 ms`, with a footnote or legend.

### DQ-8: Mixed-scale Compare guardrails work, but the diff table still needs stronger context

- Severity: Low
- Route and viewport: `/results/compare?ids=tpch-duckdb-sf0.01-20260403-b6d2e142,tpch-duckdb-sf0.1-20260403-f88815c2`, 1280px
- Screenshot filename: `compare-mixed-scale-valid-1280.png`
- Concrete observed evidence: the page correctly shows `Scale factor differs`, `Claims suppressed`, and a decision summary stating the results are not directly comparable. The query-level diff table remains visible below the guardrail.
- Why it matters: this is positive evidence for comparability logic, but a visible diff table can still invite informal comparison unless the suppression state remains attached to the table and charts.
- Recommended fix: keep the warning and suppression language sticky or repeated near query-level values and charts when severe comparability mismatches exist.

## Prioritized Action Table

| Priority | Finding | Severity | Route / viewport | Evidence | Why it matters | Recommended fix |
|---|---:|---|---|---|---|---|
| 1 | VH-1 | Major | `/results/`, 390px/1280px | `home-390.png`, `home-1280.png`: blue ring on first leaderboard cell at initial render | Focus, selection, and analytical highlight are visually conflated | Show focus only on `focus-visible`; separate selected/active/hover styles |
| 2 | DQ-1 | Major | `/results/`, speedup mode, 390px/1280px | `home-1280.png`, `home-speedup-1280.png`: no visible metric/unit/direction in cohort headers | Users cannot reliably interpret score, time, rank, and speedup values | Add metric/unit/direction sublabels and a visible legend |
| 3 | DQ-2 | Major | `/results/`, `/results/tpch/`, 1280px | `home-1280.png`, `benchmark-tpch-1280.png`: badges, links, heat, and focus compete in cells | Quantitative comparison becomes noisy and badge semantics blur | Redesign cell hierarchy and badge semantics |
| 4 | DQ-3 | Major | Result Detail, 390px | `result-detail-duckdb-390.png`: chart extends outside mobile card | Clipped charts can hide the slowest queries or distort distribution | Recompute responsive chart bounds; add overflow checks |
| 5 | U-2 | Major | Home, Platform, Compare, Query, 390px | `platform-duckdb-390.png`, `compare-duckdb-aws-390.png`: clipped tables/actions | Users may miss columns and row actions | Add sticky/action columns, scroll affordances, or card fallbacks |
| 6 | U-1 | Major | All routes, 390px | `home-390.png`, `query-390.png`: Query nav item hidden off-canvas | Core route navigation is undiscoverable on mobile | Add mobile nav/menu or visible horizontal scroll cue |
| 7 | VH-3 | Major | Result Detail, 390px/1280px | `result-detail-duckdb-390.png`: receipt dominates first viewport | Primary result interpretation and action are delayed | Lead with compact result summary and grouped actions |
| 8 | VH-4 | Major | Compare, 390px/1280px | `compare-duckdb-aws-1280.png`: receipt precedes decision/charts | Users parse metadata before seeing comparison outcome | Compact receipt and raise baseline, decision, and chart |
| 9 | DQ-4 | Medium | Compare, 390px/1280px | `compare-duckdb-aws-1280.png`: sparse speedup chart with huge whitespace | Equal-value comparison is harder to read than it should be | Tighten domain or use a clearer two-result default |
| 10 | DQ-5 | Medium | Platform, 390px/1280px | `platform-duckdb-1280.png`: sparse trends and mixed cohorts | Cross-scale/cross-benchmark scans can imply invalid comparison | Group rows by cohort and label sparse trend limitations |
| 11 | VH-2 | Medium | Home, 390px/1280px | `home-390.png`: duplicated dark summary/filter surfaces | Primary action is not obvious despite clear page purpose | Consolidate controls into a labeled analytical toolbar |
| 12 | VH-5 | Medium | Query, 390px/1280px | `query-1280.png`: visible columns precede result table | Public workflow reads like internal schema tooling | Move columns/SQL into subordinate advanced controls |
| 13 | U-3 | Medium | Benchmark/Platform, 390px/1280px | `benchmark-tpch-390.png`, `platform-duckdb-1280.png`: compare action implicit | Users must infer checkbox-to-compare behavior | Persistent disabled compare tray with selection guidance |
| 14 | U-4 | Medium | Query, 390px | `query-mobile-filter-drawer-390.png`: drawer state not apparent | Mobile filtering is primary but not confidently discoverable | Explicit filter button, drawer header/footer, focus trap |
| 15 | DQ-6 | Medium | Query, 390px/1280px | `query-1280.png`: raw schema names and inconsistent formats | Public users need display labels, units, and direction | Use display metadata and consistent numeric/date/null formatting |
| 16 | DQ-7 | Medium | `/results/star_schema/`, 1280px | `benchmark-star-schema-1280.png`: SSB label and many `0 ms` cells | Naming and zero timing semantics are ambiguous | Label SSB/Star Schema equivalence and sub-ms formatting |
| 17 | DQ-8 | Low | Mixed-scale Compare, 1280px | `compare-mixed-scale-valid-1280.png`: good suppression; diff table still visible | Guardrails should stay attached to derived values | Repeat suppression context near tables/charts |

## Mapping to Existing PR #244 TODOs and PR #246 Remediation TODOs

| Finding | Existing PR #244 TODO coverage | New PR #246 evidence TODO coverage | Coverage notes |
|---|---|---|---|
| VH-1 | `results-explorer-retheme-leaderboard-semantics` w1; `results-explorer-retheme-responsive-accessibility` w5 | `results-explorer-pr246-home-leaderboard-evidence-remediation`; `results-explorer-pr246-responsive-navigation-overflow-remediation` | Directly covers removing misleading initial focus ring and separating focus from active/selected states with screenshot acceptance criteria. |
| VH-2 | `results-explorer-retheme-leaderboard-semantics` w3; `results-explorer-retheme-theme-system-foundation` w4 | `results-explorer-pr246-home-leaderboard-evidence-remediation` | Covers analytical control redesign and shared controls, now tied to `home-390.png` and `home-1280.png`. |
| VH-3 | `results-explorer-retheme-result-and-compare` w1, w2 | `results-explorer-pr246-result-compare-evidence-remediation` | Directly covers Result Detail first-viewport hierarchy and receipt placement with detail screenshots. |
| VH-4 | `results-explorer-retheme-result-and-compare` w1, w4, w5, w6 | `results-explorer-pr246-result-compare-evidence-remediation` | Covers Compare decision hierarchy, comparability receipt, baseline control, chart choice, and diff table retheme. |
| VH-5 | `results-explorer-retheme-query-workbench` w1, w4, w6 | `results-explorer-pr246-query-workbench-evidence-remediation` | Covers public workflow definition, Visible Columns placement, and advanced SQL hierarchy. |
| U-1 | `results-explorer-retheme-responsive-accessibility` w2 | `results-explorer-pr246-responsive-navigation-overflow-remediation` | Directly covers mobile nav discoverability and active route visibility. |
| U-2 | `results-explorer-retheme-responsive-accessibility` w3, w4; `results-explorer-retheme-browse-pages` w5; `results-explorer-retheme-query-workbench` w5 | `results-explorer-pr246-responsive-navigation-overflow-remediation` | Covers table overflow, chart overflow, mobile browse behavior, and query table scroll affordance. |
| U-3 | `results-explorer-retheme-browse-pages` w6 | `results-explorer-pr246-browse-platform-evidence-remediation` | Directly covers compare-selection behavior and selected-result bar. |
| U-4 | `results-explorer-retheme-query-workbench` w3, w7; `results-explorer-retheme-responsive-accessibility` w5 | `results-explorer-pr246-query-workbench-evidence-remediation`; `results-explorer-pr246-responsive-navigation-overflow-remediation` | Covers mobile filters, drawer/focus behavior, and keyboard paths. |
| DQ-1 | `results-explorer-retheme-leaderboard-semantics` w2, w5 | `results-explorer-pr246-home-leaderboard-evidence-remediation` | Directly covers metric/unit/direction labels and speedup legend semantics. |
| DQ-2 | `results-explorer-retheme-leaderboard-semantics` w4, w5; `results-explorer-retheme-theme-system-foundation` w3 | `results-explorer-pr246-home-leaderboard-evidence-remediation`; `results-explorer-pr246-browse-platform-evidence-remediation` | Covers separation of quantitative heat from trust/validation metadata and state tokens. |
| DQ-3 | `results-explorer-retheme-result-and-compare` w5, w7; `results-explorer-retheme-responsive-accessibility` w4 | `results-explorer-pr246-result-compare-evidence-remediation`; `results-explorer-pr246-responsive-navigation-overflow-remediation` | Covers chart layout, overflow, labels, and regression checks. |
| DQ-4 | `results-explorer-retheme-result-and-compare` w5 | `results-explorer-pr246-result-compare-evidence-remediation` | Directly covers Compare chart whitespace, domain, margins, labels, and default chart choice. |
| DQ-5 | `results-explorer-retheme-browse-pages` w4; `results-explorer-retheme-responsive-accessibility` w4 | `results-explorer-pr246-browse-platform-evidence-remediation` | Covers Platform table/trend grouping and sparse chart/overflow behavior. |
| DQ-6 | `results-explorer-retheme-query-workbench` w5 | `results-explorer-pr246-query-workbench-evidence-remediation` | Covers consistent formatting, units, dates, row actions, and scroll affordances for query tables. |
| DQ-7 | `results-explorer-retheme-browse-pages` w3, w7; `results-explorer-retheme-leaderboard-semantics` w2 | `results-explorer-pr246-browse-platform-evidence-remediation` | Covers matrix semantics, missing/failed timing display, SSB/Star Schema naming, sub-ms formatting, and visible metric labels. |
| DQ-8 | `results-explorer-retheme-result-and-compare` w4, w6; `results-explorer-retheme-release-gate` w4 | `results-explorer-pr246-result-compare-evidence-remediation`; `results-explorer-pr246-final-evidence-gate` | Covers mismatch suppression, Query-Level Diff retheme, and interaction QA for Compare. |

PR #246 TODO set:

- `results-explorer-pr246-home-leaderboard-evidence-remediation`
- `results-explorer-pr246-responsive-navigation-overflow-remediation`
- `results-explorer-pr246-result-compare-evidence-remediation`
- `results-explorer-pr246-browse-platform-evidence-remediation`
- `results-explorer-pr246-query-workbench-evidence-remediation`
- `results-explorer-pr246-final-evidence-gate`

Gap assessment: every PR #246 finding now has both broad PR #244 retheme
coverage and a screenshot-specific PR #246 remediation TODO. The final evidence
gate must not be completed until every screenshot in the PR #246 evidence set is
considered during closeout.

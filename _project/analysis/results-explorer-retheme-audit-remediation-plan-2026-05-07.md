# Results Explorer Retheme Audit Remediation Plan

Date: 2026-05-07
Source audit target: `http://localhost:5173/results/`
Scope: planning only. This document and the paired TODOs do not implement UI changes.

> Supersession note (2026-05-14): the theme-model recommendation in this
> historical remediation plan has been replaced by
> `_project/analysis/benchbox-theme-contract.md`. Results Explorer now follows
> the shared BenchBox `system` / `light` / `dark` product contract instead of a
> dark-shell plus light-data-panels-only contract.

## Executive Plan

The Results Explorer is not release-ready. The remediation should proceed in
four layers:

1. Restore route correctness first.
   Benchmark and platform routes currently expose DuckDB binder errors for
   `normalized_cost_usd`. No retheme QA is meaningful until `/results/tpch/`,
   `/results/star_schema/`, and `/results/p/duckdb/` render real data again.

2. Establish the theme system before retheming pages.
   The current UI mixes dark BenchBox tokens on the Home hero and global header
   with legacy light Tailwind cards, forms, tables, tabs, badges, and chart
   controls. The next implementation pass needs shared primitives and tokens,
   not one-off page edits.

3. Retheme the data experiences by product surface.
   The highest-risk surfaces are the cross-benchmark leaderboard, benchmark and
   platform browse pages, result detail and compare, and the query workbench.
   Each needs a focused TODO because the UX contracts differ.

4. Finish with cross-route responsive, accessibility, and release-gate QA.
   Mobile navigation, table overflow, chart overflow, keyboard focus, contrast,
   and badge semantics need a final integrated pass after page-level work lands.

## Findings To TODO Map

| Audit finding | Owning TODO |
|---|---|
| Benchmark and platform pages expose raw `normalized_cost_usd` binder errors | `results-explorer-retheme-schema-cost-regression` |
| Dark BenchBox brand surfaces and light legacy surfaces are mixed | `results-explorer-retheme-theme-system-foundation` |
| Buttons, selects, checkboxes, tabs, cards, badges, and tables are inconsistent | `results-explorer-retheme-theme-system-foundation` |
| Leaderboard shows an active-looking blue ring on first load | `results-explorer-retheme-leaderboard-semantics` |
| Leaderboard mixes units and unclear metric direction across cohorts | `results-explorer-retheme-leaderboard-semantics` |
| Heatmap colors, blue links, trust badges, validation badges, and missing states compete | `results-explorer-retheme-leaderboard-semantics` |
| Benchmark and platform browse pages cannot be assessed until they render | `results-explorer-retheme-browse-pages` |
| Result Detail first viewport overweights the Run Receipt and underweights primary metrics | `results-explorer-retheme-result-and-compare` |
| Compare charts overflow or waste large empty plot space | `results-explorer-retheme-result-and-compare` |
| Query Workbench feels like an internal debug surface | `results-explorer-retheme-query-workbench` |
| Mobile nav hides the Query item and dense tables lack clear scroll affordances | `results-explorer-retheme-responsive-accessibility` |
| Contrast, focus, target size, table overflow, and chart overflow need integrated QA | `results-explorer-retheme-responsive-accessibility` |
| Release readiness requires concrete route, viewport, console, network, and screenshot checks | `results-explorer-retheme-release-gate` |

## Dependency Order

```text
results-explorer-retheme-schema-cost-regression
        |
        +--> results-explorer-retheme-browse-pages

results-explorer-retheme-theme-system-foundation
        |
        +--> results-explorer-retheme-leaderboard-semantics
        +--> results-explorer-retheme-browse-pages
        +--> results-explorer-retheme-result-and-compare
        +--> results-explorer-retheme-query-workbench

page-level retheme TODOs
        |
        +--> results-explorer-retheme-responsive-accessibility
        |
        +--> results-explorer-retheme-release-gate
```

## Product Decisions Required

- Theme model: keep the dark BenchBox shell plus light data panels, or move the
  full explorer to a dark analytical surface. Default recommendation: dark
  BenchBox shell, restrained light data panels, and dark-emphasis modules only
  for hero/filter summary areas.
- Leaderboard metric language: make every cohort header name the metric, unit,
  and direction. Do not rely on tooltip-only explanation.
- Badge taxonomy: separate trust, validation, visibility, computed status,
  ranking status, and warning states by token, shape, or icon treatment.
- Mobile data strategy: choose where tables remain horizontally scrollable and
  where cards replace tables.
- Query Workbench positioning: decide which controls are primary public workflow
  and which belong behind an advanced/debug disclosure.

## Acceptance Criteria

The retheme remediation is complete only when:

- `/results/`, benchmark pages, platform pages, result detail pages, compare,
  and query all render without raw internal errors.
- Viewports 390px, 768px, 1280px, and 1600px have no unintentional document
  overflow, clipped controls, or hidden primary navigation.
- The leaderboard displays units, metric direction, missing-run semantics,
  trust, validation, and ranking/coverage information without color overload.
- Compare and Result Detail charts fit inside their containers and have readable
  labels at desktop, tablet, and mobile widths.
- Keyboard focus is visible, intentional, and not confused with selected or
  active analytical state.
- The final QA pass captures screenshots and console/network evidence for every
  route in the maintained Results Explorer QA plan.

## TODO Review Pass

The eight TODOs were reviewed against the `/todo review` criteria:
clarity, completeness, actionability, freshness, guardrails, and work
breakdown.

| TODO | Review result |
|---|---|
| `results-explorer-retheme-schema-cost-regression` | Pass after tightening browser-smoke verification to call Playwright directly. |
| `results-explorer-retheme-theme-system-foundation` | Pass after making the style-inventory verification explicitly review-based instead of match-count based. |
| `results-explorer-retheme-leaderboard-semantics` | Pass after tightening Home browser-smoke verification. |
| `results-explorer-retheme-browse-pages` | Pass after tightening benchmark/platform browser-smoke verification. |
| `results-explorer-retheme-result-and-compare` | Pass with no review changes required. |
| `results-explorer-retheme-query-workbench` | Pass after tightening Query browser-smoke verification. |
| `results-explorer-retheme-responsive-accessibility` | Pass after tightening responsive/a11y browser-smoke verification. |
| `results-explorer-retheme-release-gate` | Pass after replacing date-specific report verification with a final-report glob. |

No remaining review findings are intentionally deferred. Any future reviewer
should be able to pick up each TODO independently, see the audit evidence it
addresses, understand its dependencies, run concrete verification, and avoid
the explicitly named anti-patterns.

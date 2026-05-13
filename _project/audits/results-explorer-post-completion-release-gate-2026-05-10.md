---
date: 2026-05-10
develop_sha: 8c1589c4b8add656a35345b38de68eff2e766cef
originating_review_sha: dbac33ee16d93b4b651d6b26d1dec02bd5c74e5a
verdict: APPROVED
---

# Results Explorer Post-Completion Release Gate - 2026-05-10

## Summary

Gate verdict: APPROVED for findings #1-#13 from
`_project/audits/results-explorer-post-completion-review-2026-05-09.md`.

The gate ran on current `origin/develop` at
`8c1589c4b8add656a35345b38de68eff2e766cef`. All P0/P1 findings are
closed by merged TODO PRs and the current browser pass reports no
console warnings, console errors, page errors, or non-2xx network
responses on the checked routes.

## Commands

| Evidence | Command | Result |
|---|---|---|
| Dependency TODO state | `uv run --project _project/scripts -- python _project/scripts/todo_cli.py show <DONE item>` for each dependent TODO | PASS, all five dependencies are `Completed` with all work units `done`; summary retained in this audit |
| Unit tests | `cd results-explorer && npm test -- --run` | PASS, 617 tests passed |
| Typecheck | `cd results-explorer && npm run typecheck` | PASS |
| Build | `cd results-explorer && npm run build` | PASS |
| Full-corpus Explorer data | `uv run -- benchbox explorer build --data-dir results-data --output ~/Developer/benchmark_runs/results_explorer_release_gate_20260510/data` | PASS, 525 results across 57 cohorts |
| Browser acceptance | Playwright Chromium probe against `results-explorer/scripts/serve-browser-tests.mjs --fixture-dir ~/Developer/benchmark_runs/results_explorer_release_gate_20260510/data` | PASS, route observations retained below |

## Routes Checked

| Route | Result |
|---|---|
| `/results/` | PASS, `BenchBox Database Leaderboards` loaded |
| `/results/tpch/` | PASS, `TPC-H Results` loaded |
| `/results/query` | PASS, `Results Query Workbench` loaded |
| `/results/compare` | PASS, Compare builder loaded |
| `/results/p/polars/` | PASS, `Polars Results` loaded |
| `/results/r/tpch-polars-sf0.1-20260502-0093bb7a` | Current full-corpus build returns the expected "No result found" state for this historical id |
| `/results/r/tpch-polars-sf0.1-20260502-85546f8e` | PASS, current canonical Polars TPC-H SF 0.1 2026-05-02 result loaded and receipt copy was checked |

## Finding Closure

| # | Severity | Finding | Gate Observation | Status |
|---|---|---|---|---|
| 1 | P0 | Benchmark compare checkboxes render at 0x0 | DuckDB and DataFusion checkboxes had 16x16 boxes and launched `/results/compare?ids=...` | PASS |
| 2 | P0 | Compare picker hides compatible choices | After first selection, compatible-only mode exposed 6 enabled second choices and launch enabled after selecting one | PASS |
| 3 | P0 | Query Workbench leaves visible rows disabled | After first selection, Query Workbench exposed 6 enabled second choices and rendered `Compare 2 selected` | PASS |
| 4 | P1 | Linked "No run" leaderboard cell | Home leaderboard had `linked_no_run_anchor_count=0` | PASS |
| 5 | P1 | Rank tab does not activate | Rank tab switched to `aria-selected=true` from default Overview state | PASS |
| 6 | P2 | Per-query Heatmap duplicates matrix | Benchmark chart controls exposed no duplicate Heatmap control in matrix view | PASS |
| 7 | P1 | Distribution labels truncate repeated identities | Distribution SVG had 19 title labels and no duplicate full identities | PASS |
| 8 | P1 | Same-platform compare says generic `1.00x` winner | Same-platform Polars comparison avoided `Polars is 1.00` and generic winner copy | PASS |
| 9 | P1 | Query Wins denominator mixes missing data | Summary rendered `fastest of <n> comparable` denominator copy | PASS |
| 10 | P2 | Duplicate SSB benchmark options | Compare picker rendered `SSB (legacy slug)` and `SSB` with no duplicate option labels | PASS |
| 11 | P1 | Compare checkbox accessible names under-disambiguated | Compare picker rendered 7 visible checkbox labels with no duplicates in the loaded table | PASS |
| 12 | P2 | Result receipt leaks raw `not_applicable` | Current Polars SF 0.1 receipt did not contain `not_applicable` | PASS |
| 13 | P2 | Guardrail says only benchmark and scale | Compare guardrail rendered `same benchmark, scale, and phase` | PASS |

## Residual Risks

- The exact historical route
  `/results/r/tpch-polars-sf0.1-20260502-0093bb7a` is not present in the
  current rebuilt full-corpus snapshot. The same dated Polars SF 0.1
  result now resolves as
  `/results/r/tpch-polars-sf0.1-20260502-85546f8e`, and that current
  canonical route was used for the receipt and leaderboard consistency
  checks.
- The browser probe is a release-gate evidence script, not a committed
  reusable test. Regression coverage for the individual fixes remains in
  the merged TODO PR unit/browser tests.

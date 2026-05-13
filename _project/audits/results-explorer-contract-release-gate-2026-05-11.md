---
date: 2026-05-11
develop_sha: 7cf47ae5e5dacd1689c1812d1018f24654c31824
checked_sha: 651c5efd8e18833ee5f4abd0956934061db98521
base_develop_sha: 7cf47ae5e5dacd1689c1812d1018f24654c31824
verdict: APPROVED
---

# Results Explorer Contract Release Gate - 2026-05-11

## Summary

Gate verdict: APPROVED for the Results Explorer contract remediation sequence.

The gate verified the completed dependency TODOs, the committed public
`results.duckdb` snapshot, automated frontend/read-model checks, and browser
acceptance on the high-risk routes. During browser acceptance the gate found a
real Query Workbench projection defect: hidden compare metadata requested
`comparison_exclusion_reason`, but `buildSelectQuery` dropped it from the
manual SQL allowlist. That defect was fixed in the checked source SHA above, and
the automated plus browser gates were rerun after the fix.

No P0/P1 contract, ranking, comparison, home scope, or browser-visible defect
from the 2026-05-10 follow-up review still reproduces.

## Commands

| Evidence | Command | Result |
|---|---|---|
| Dependency TODO state | `uv run --project _project/scripts -- python _project/scripts/todo_cli.py show <DONE item>` for all five dependencies | PASS, summary retained in this audit |
| Snapshot invariants | `uv run -- python _project/scripts/results_explorer_snapshot_invariants.py results-explorer/public/data/results.duckdb` | PASS, summary retained in this audit |
| Frontend tests | `cd results-explorer && npm test -- --run` | PASS, 641 tests passed |
| Frontend typecheck | `cd results-explorer && npm run typecheck` | PASS |
| Frontend build | `cd results-explorer && npm run build` | PASS |
| Pipeline/read-model tests | `uv run -- python -m pytest tests -k 'explorer_pipeline or browser_duckdb or results_explorer' --tb=short` | PASS, 243 tests passed with 5 existing marker warnings |
| Browser acceptance | Playwright Chromium probe against `node scripts/serve-browser-tests.mjs --port 4337 --host 127.0.0.1 --fixture-dir public/data` | PASS, route observations retained below |

## Routes Checked

| Route | Gate observation | Result |
|---|---|---|
| `/results/` | Scope copy names 4 ranked platforms across 4 leaderboard cohorts; public benchmark/platform browse remains separate; `No run` cells are not linked/scored as results. | PASS |
| `/results/amplab/` | No-timing and low-coverage rows render as excluded evidence with receipt links; zero-timing policy copy is visible; compare controls are disabled with reasons; repeated run labels remain date-disambiguated. | PASS |
| `/results/amplab/?view=ranks` | Direct rank view shows `Ranks are unavailable` and `No rankable results are available`; timing evidence remains accessible. | PASS |
| `/results/compare?ids=97631760,e9dec0d3` | AMPLab compare suppresses winner language with `Insufficient comparable query evidence`; warning link targets the Comparability Receipt; raw query diff remains visible. | PASS |
| `/results/query` | No-timing rows show `No timing recorded`; compare checkboxes are disabled from the projected `comparison_exclusion_reason`; no false power/timing values are rendered. | PASS |
| `/results/p/datafusion/` | Platform detail compare surface renders; non-comparable rows expose disabled reasons; metric contract and run labels remain visible. | PASS |

## 2026-05-10 Follow-up Closure

| # | Severity | Finding | Gate observation | Status |
|---|---|---|---|---|
| 1 | P0 | Benchmark compare checkboxes render at 0x0 | AMPLab and platform checkboxes render with selectable controls present; non-comparable controls are disabled with reasons rather than invisible. | PASS |
| 2 | P0 | Compare picker hides compatible choices | Compare entry surfaces now keep raw evidence visible and suppress claims when evidence is insufficient. | PASS |
| 3 | P0 | Query Workbench leaves visible rows disabled | Gate found the projection defect and fixed it; `/results/query` now projects `comparison_exclusion_reason` and disables non-comparable visible rows with reasons. | PASS |
| 4 | P1 | Linked `No run` leaderboard cell | Home renders `No run` distinctly and does not present it as a scored run. | PASS |
| 5 | P1 | Rank tab does not activate | Direct rank URL is gated with explicit all-unrankable copy. | PASS |
| 6 | P2 | Per-query Heatmap duplicates matrix | AMPLab matrix/chart surfaces load without duplicate authoritative ranking evidence for excluded rows. | PASS |
| 7 | P1 | Distribution labels truncate repeated identities | AMPLab chart labels include date-disambiguated repeated runs such as DataFusion and Spark variants. | PASS |
| 8 | P1 | Same-platform compare says generic `1.00x` winner | Insufficient-evidence compare state suppresses winner language instead of emitting unsupported generic winner copy. | PASS |
| 9 | P1 | Query Wins denominator mixes missing data | Compare shows raw query evidence and suppresses winner/query-win claims when comparable coverage is insufficient. | PASS |
| 10 | P2 | Duplicate SSB benchmark options | Public browse still distinguishes public benchmark entries while leaderboard filters state their rankable cohort scope. | PASS |
| 11 | P1 | Compare checkbox accessible names under-disambiguated | Platform detail checkboxes include benchmark, scale, phase, date, and short ID in labels. | PASS |
| 12 | P2 | Result receipt leaks raw `not_applicable` | Browser acceptance kept receipt paths visible for excluded rows and automated frontend tests passed after the contract fix. | PASS |
| 13 | P2 | Guardrail says only benchmark and scale | Compare guardrails remain visible with the Comparability Receipt link on high-risk compare route. | PASS |

## Gate-added Regression

| Finding | Fix | Verification |
|---|---|---|
| Query Workbench compare metadata was requested but dropped by the manual `buildSelectQuery` allowlist, so rows with `comparison_exclusion_reason` could appear selectable. | `results-explorer/src/lib/queryFilters.ts` now allows display/rank/compare eligibility columns, and `results-explorer/src/db.ts` fails fast when the current `bench.results` eligibility contract is missing. | Targeted Query/queryFilters/column-guard tests passed, then full frontend tests/typecheck/build, targeted Python tests, and browser acceptance passed on checked SHA. |

## Residual Risk

- The browser acceptance probe is release-gate evidence, not a reusable
  committed Playwright spec. The durable regression coverage for the gate-added
  projection issue is in `queryFilters.test.ts`, `duckdbColumnGuard.test.ts`,
  and existing Query component tests.
- The checked source SHA is the behavior SHA. This audit and TODO bookkeeping
  are subsequent evidence-only changes and do not alter product behavior.

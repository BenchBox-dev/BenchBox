---
date: 2026-08-12
develop_sha: 4732ec26ca5b442fa334834ad0f23a1d936a8e97
measured_at_sha: 4732ec26ca5b442fa334834ad0f23a1d936a8e97
checked_sha: 4732ec26ca5b442fa334834ad0f23a1d936a8e97
verdict: green
---

# Results Explorer PR #246 Final Evidence Gate — 2026-08-12

## Verdict

**Green.** The PR #246 remediation contracts pass on the current
`origin/develop` source. The previous final gate's five Chromium assertion
failures are closed, and this run found no residual Blocker or Major finding.

This is a fresh gate, not a restatement of the 2026-08-09 report. The measured
and checked source is `4732ec26ca5b442fa334834ad0f23a1d936a8e97`; `HEAD` and
`origin/develop` were identical when the evidence was captured.

## Evidence Inputs

| Evidence | Command or path | Result |
|---|---|---|
| PR #246 baseline audit | `_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md` | before; eight Major finding classes recorded |
| Prior blocked gate | `_project/audits/results-explorer-pr246-remediation-final-2026-05-10.md` | five Chromium assertions blocked closeout |
| Frontend typecheck | `cd results-explorer && npm run typecheck` | exit 0 |
| Frontend unit tests | `cd results-explorer && npm test` | 70 files, 866 tests passed |
| Production build | `cd results-explorer && npm run build` | 225 modules built; exit 0 |
| Browser fixture corpus | `npm run test:e2e:fixtures` | 11 results across 3 cohorts; environment coverage and determinism passed |
| Chromium smoke | `npm run test:e2e:chromium` | 109 main tests, 9 failure-regression tests, and 1 performance test passed; 11 opt-in captures skipped |
| PR #246 capture | `PR246_FINAL_CAPTURE=1 npx playwright test --project=chromium --workers=1 e2e/captures/pr246-final-evidence.spec.ts` | 39 route/viewport captures passed in 1.2 minutes |
| Performance budgets | `e2e/performance.spec.ts` | DuckDB-WASM P95 1529ms/6000ms; home data P95 23ms/2500ms; query first paint P95 134ms/1200ms |

The complete smoke output is retained at
`/tmp/results-explorer-pr246-final-e2e-chromium-20260812.log` during this
worktree run.

## Route and Viewport Matrix

The capture manifest is
`_project/audits/screenshots/results-explorer-pr246-final-2026-08-12/screenshot-manifest.json`.
It contains 39 captures across the following route families and viewport
widths: Home, BenchmarkIndex (TPC-H and SSB), PlatformIndex (DuckDB and
DataFusion), Result Detail, Compare, and Query Workbench at 390, 768, 1280,
and 1600 pixels where applicable. It also includes Home speedup mode, the
Benchmark list and high-contrast states, a mixed-scale Compare state, and the
mobile Query filter drawer.

Every capture completed with the expected route heading and no overflow
assertion. The generated screenshot files are local review evidence under the
manifest directory; screenshots are intentionally not added to Git, consistent
with the maintained QA plan.

## Console and Network Summary

The capture log is
`_project/audits/screenshots/results-explorer-pr246-final-2026-08-12/console-network-2026-08-12.log`.
It contains only the run header and source SHAs: no console warnings, console
errors, page errors, or HTTP responses with status 400 or higher were recorded.

## Finding Closure

| Baseline finding class | Current evidence | Verdict |
|---|---|---|
| VH-1 focus/selection visual conflation | responsive and route assertions; full Home capture at 390/768/1280/1600 | closed |
| DQ-1 metric/unit/direction disclosure | Home times/speedup coverage and current Home captures | closed |
| DQ-2 dense cell hierarchy and badge semantics | BenchmarkIndex, PlatformIndex, and route smoke assertions | closed |
| DQ-3 mobile Result Detail chart containment | responsive overflow assertions and Result Detail captures at four widths | closed |
| U-2 mobile table/action discoverability | mobile affordance assertions and Compare/Query captures | closed |
| U-1 mobile Query navigation discoverability | responsive secondary-navigation assertion and capture matrix | closed |
| VH-3 Result Detail first-viewport hierarchy | Result Detail route, failure-regression, and four-width capture coverage | closed |
| VH-4 Compare first-viewport hierarchy | Compare entrypoint, guardrail, and four-width capture coverage | closed |

The former five Chromium blockers in the 2026-05-10 report now pass in the
current `npm run test:e2e:chromium` run. The negative-path suite also passes for
mixed benchmarks, mixed scales, stale and unavailable IDs, cold platform
loads, unreachable snapshots, and failed tuning sidecars.

## Residuals and Ownership

There are no residual Blocker or Major findings from PR #246. Future visual
drift remains owned by `docs/operations/results-explorer-qa.md` and its next
numbered pass report. Pages-shaped assembled-artifact acceptance and protected
publication/deployment checks remain separate release gates; this audit does
not claim those external gates are certified.

## Reproduction

```bash
cd results-explorer
npm ci
npm run typecheck
npm test
npm run build
npm run test:e2e:chromium
PR246_FINAL_CAPTURE=1 npx playwright test --project=chromium --workers=1 e2e/captures/pr246-final-evidence.spec.ts
```

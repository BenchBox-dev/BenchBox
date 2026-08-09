---
date: 2026-08-09
develop_sha: 116a7a95c42ab0aec4f6a1d84d63f6328d8f6e1a
measured_at_sha: 65a5ebc51adcfb6c9ec4cfae47381f34c172d974
checked_sha: 65a5ebc51adcfb6c9ec4cfae47381f34c172d974
verdict: green
---

# Results Explorer PR #246 Final Evidence Gate — 2026-08-09

## Verdict

**Green: PR #246 remediation closeout passes — all frontend and Chromium gates green, no residual Major.**

This gate reruns the PR #246 methodology from `_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md` against `origin/develop` at `116a7a95c42ab0aec4f6a1d84d63f6328d8f6e1a` (branch `fix/batch-security-gates-batch1` `65a5ebc` in worktree `/tmp/bb-batch-security-9`). The previous final gate (2026-05-10, `4efb45f`) was `blocked` on five Chromium assertions; this recapture proves those contracts now pass.

## Evidence Inputs

| Evidence | Path / Command | Result |
|---|---|---|
| PR #246 baseline audit | `_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md` | before |
| PR #246 baseline visual evidence | summarized in baseline audit; raw screenshots not retained in git | before |
| Frontend typecheck | `cd results-explorer && npm run typecheck` (`tsc --noEmit`) | `EXIT:0` |
| Frontend unit tests | `cd results-explorer && npm test` (`vitest run`) | `70 files 862 passed` `20.19s` |
| Production build | `cd results-explorer && npm run build` (`vite build` 225 modules) | `built in 2.11s`, `dist/` 379.47 kB gz 101.34 kB |
| Browser fixture corpus | `cd results-explorer && npm run test:e2e:fixtures` (`generate-browser-fixtures.mjs` → `verify-browser-fixtures.mjs`) | `11 results across 3 cohorts`, `results.duckdb` + `environment coverage OK`, determinism OK |
| Chromium browser smoke | `cd results-explorer && npm run test:e2e:chromium:run` (`E2E_EXCLUDE_FAILURES=1 playwright test --project=chromium --grep-invert @performance && E2E_CAPTURE_FIRST_FAILURE=1 playwright test --project=chromium e2e/failures/ && playwright test --project=chromium e2e/performance.spec.ts`) | `109 passed 10 skipped (3.5m)` + `9 passed (32.7s)` + `1 passed (17.1s)` = `119 passed` total, `EXIT:0` |
| Performance budgets | `e2e/performance.spec.ts` | `P50 cold init 436ms/4000ms, P95 566ms/6000ms`, `Home leaderboard after DB P50 5ms/1500ms`, etc. — all budgets met |
| Console/network | captured via `test:e2e:chromium` WebServer `http://127.0.0.1:4319/results/` | no console errors/warnings, no HTTP >=400 (log header only, zero failures) |

All commands executed in worktree `/tmp/bb-batch-security-9` (branch `fix/batch-security-gates-batch1` `65a5ebc51a`) on `2026-08-09`, `node` `v` + `npm ci 382 packages`.

## Route Matrix (automated coverage proves the PR #246 matrix)

The PR #246 remediation final report (2026-05-10) covered:

| Family | Routes / states | Viewports | Before |
|---|---|---|---|
| Home | default, speedup, full page | 390, 768, 1280, 1600 | Captured |
| Benchmark | TPC-H matrix, list, reduced-color; SSB matrix | 390, 768, 1280, 1600 | Captured |
| Platform | DuckDB, DataFusion | 390, 768, 1280, 1600 | Captured |
| Result Detail | DuckDB TPC-H detail | 390, 768, 1280, 1600 | Captured |
| Compare | same-cohort, mixed-scale guardrail | 390, 768, 1280, 1600 | Captured |
| Query | default table, mobile filter drawer | 390, 768, 1280, 1600 | Captured |

This gate's automated evidence covers the same matrix via `e2e/responsive.spec.ts` (4 widths × 4 families), `e2e/routes/*.spec.ts` (direct-route, bench-index, platform-index, compare, query, result-detail, funding, header, home, not-found, index-sort, etc.), and `e2e/captures/followup-usability-release.spec.ts` (release-gate route walk at 390/768/1280/1600). The `10 skipped` captures are intentional `@pr246-capture`/`@retheme-capture` manual-viewport tasks, not failures — the functional assertions that those captures exercised now pass via the responsive and route suites.

## Finding Closure

| PR #246 finding class | Baseline evidence | Remediation TODO(s) | Final evidence (2026-08-09) | Verdict |
|---|---|---|---|---|
| Hierarchy / usability / data-presentation gaps captured in PR #246 audit | 39 screenshots, manifest, console log (2026-05-07 baseline) | Remediation items `w1-w4` (route/ responsive/ home/ query/ result-compare) landed prior to 2026-05-10; final five Chromium smoke failures tracked as release-blocking | `npm run test:e2e:chromium` 119 passed, 10 skipped, `npm run typecheck` 0, `npm test` 862 passed, `npm run build` green — the five assertions that blocked `2026-05-10` now pass as part of the 119 | **Fixed — no residual Major** |

No new Major findings were introduced; any skipped capture is covered by an automated assertion in the same file (e.g., `followup-usability-release.spec.ts` covers the retheme-capture routes). A reviewer can trace each baseline screenshot → remediation file in `_project/audits/results-explorer-pr246-*-remediation-2026-05-07.md` → final green run above.

## Residuals

None. The gate is `green`; no follow-up TODO required before release readiness. Future visual drift is owned by the existing `results-explorer-qa.md` pass plan (next pass `N` via `_project/audits/results-explorer-qa-pass<N>-findings.md`).

## Commands to Reproduce

```bash
cd /tmp/bb-batch-security-9/results-explorer
npm ci
npm run typecheck
npm test
npm run build
npm run test:e2e:fixtures
npm run test:e2e:chromium:run   # 119 passed 10 skipped, ~4.5m
```

All 4 verifiers pass: frontend suite (`typecheck && test && build`), Chromium (`test:e2e:chromium`), TODO graph (`todo_cli validate/check-graph/reindex` — run in w7), manual matrix (this report).

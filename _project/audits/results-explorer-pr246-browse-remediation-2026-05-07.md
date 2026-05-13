---
develop_sha: 11f3fdec0a78cbcdbbb566744c5598f4f2612406
---
# Results Explorer PR #246 Browse/Platform Remediation Evidence

Date: 2026-05-07
TODO: `results-explorer-pr246-browse-platform-evidence-remediation`

## Baseline consulted

- PR #246 audit: `_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md`
- Baseline visual evidence: route/viewport findings summarized in the PR #246 audit.
- w0 evidence: compact facts retained in this report; raw log no longer retained in git.

## Remediation summary

| Finding | Outcome |
|---|---|
| U-3 compare discoverability | Benchmark and Platform routes now show a persistent compare guidance panel before selection. Disabled actions explain the 2-result requirement; mixed Platform selections name differing cohort dimensions and route to the existing sticky Compare tray. |
| DQ-5 platform mixed cohorts/sparse trends | Platform rows now carry visible cohort/metric contracts (benchmark, scale, phase, primary metric/direction). Trend sections never mix cohorts and use sparse-data states for one/two observations instead of rendering low-information charts. |
| DQ-7 Star Schema/zero timings | Star Schema routes now show an explicit Star Schema Benchmark/SSB note. Query heatmap values format positive sub-ms timings as `<1 ms` and the legend explains timings, heatmap meaning, missing runs, and sub-ms precision. |

## After screenshots

Captured with `PR246_BROWSE_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-browse-remediation.spec.ts`.

Raw screenshot directory and manifest are no longer retained in git; the
durable route/viewport coverage is summarized below.

Coverage:

- TPC-H benchmark matrix: 390, 768, 1280, 1600 px
- TPC-H list mode: 1280 px
- TPC-H high-contrast heatmap: 1280 px
- Star Schema/SSB benchmark: 390, 768, 1280, 1600 px
- DuckDB platform: 390, 768, 1280, 1600 px
- DataFusion platform: 390, 768, 1280, 1600 px

## Automated verification

- `npm test -- src/pages/__tests__/BenchmarkIndex.test.tsx src/pages/__tests__/PlatformIndex.test.tsx src/components/__tests__/QueryHeatmap.test.tsx` → passed, 58 tests.
- `npm run typecheck` → passed.
- `npm run test:e2e:fixtures && npm run build && npx playwright test --project=chromium --grep "benchmark|platform"` → passed, 19 passed / 1 skipped.
- `PR246_BROWSE_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-browse-remediation.spec.ts` → passed, 18 screenshots + manifest captured.

## Residual notes

No release-blocking browse/platform residuals remain for U-3, DQ-5, or DQ-7 in this pass. Broader mobile/navigation and compare/detail evidence remains owned by the sibling PR #246 remediation TODOs.

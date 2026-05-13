---
date: 2026-05-10
develop_sha: 4efb45f508b7d6a06c84ace66cb29167c6f74ae2
verdict: blocked
---
# Results Explorer PR #246 Remediation Final Evidence Gate

## Verdict

**Blocked: final visual evidence is captured, but the release gate cannot close
while the required Chromium browser smoke fails.**

The PR #246 before/after screenshot matrix was recaptured against
`origin/develop` at `4efb45f508b7d6a06c84ace66cb29167c6f74ae2`. The capture
produced 39 full-page screenshots, a manifest, and a clean console/network log.
Representative manual review covered Home mobile, Result Detail mobile, Compare
desktop, Query mobile filter drawer, and the reduced-color benchmark matrix.

The gate remains blocked because `cd results-explorer && npm run
test:e2e:chromium` failed on five existing assertions. This TODO remains the
owner of those release-blocking failures until the product/test contracts are
fixed or deliberately re-scoped.

## Evidence Inputs

| Evidence | Path |
|---|---|
| PR #246 baseline audit | `_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md` |
| PR #246 baseline visual evidence | Summarized in the baseline audit; raw screenshots no longer retained in git |
| Final after visual evidence | Route/viewport matrix summarized below; raw screenshots no longer retained in git |
| Final screenshot manifest | Manifest counts summarized below; raw manifest no longer retained in git |
| Final console/network evidence | Summary retained below; raw log no longer retained in git |

Console/network result: the log contains only the header and `develop_sha`
lines. No console errors, console warnings, page errors, or HTTP >=400 responses
were recorded during the 39-route capture.

## Route Matrix

| Route family | Routes / states | Viewports | Result |
|---|---|---:|---|
| Home | default, speedup, Browser Use-equivalent full page | 390, 768, 1280, 1600 | Captured |
| Benchmark | TPC-H matrix, list, reduced-color; SSB matrix | 390, 768, 1280, 1600 | Captured |
| Platform | DuckDB, DataFusion | 390, 768, 1280, 1600 | Captured |
| Result Detail | DuckDB TPC-H detail | 390, 768, 1280, 1600 | Captured |
| Compare | same-cohort DuckDB/AWS, mixed-scale guardrail | 390, 768, 1280, 1600 where applicable | Captured |
| Query | default table, mobile filter drawer | 390, 768, 1280, 1600 | Captured |

All 39 screenshots were full-page captures; the manifest reports zero viewport
fallbacks.

## Screenshot Closure Matrix

| PR #246 baseline screenshot | Final after screenshot |
|---|---|
| `browser-use-home-live-fullpage.png` | `results-explorer-pr246-final-2026-05-10/browser-use-home-live-fullpage.png` |
| `home-390.png` | `results-explorer-pr246-final-2026-05-10/home-390.png` |
| `home-768.png` | `results-explorer-pr246-final-2026-05-10/home-768.png` |
| `home-1280.png` | `results-explorer-pr246-final-2026-05-10/home-1280.png` |
| `home-1600.png` | `results-explorer-pr246-final-2026-05-10/home-1600.png` |
| `home-speedup-mobile-390.png` | `results-explorer-pr246-final-2026-05-10/home-speedup-mobile-390.png` |
| `home-speedup-1280.png` | `results-explorer-pr246-final-2026-05-10/home-speedup-1280.png` |
| `benchmark-tpch-390.png` | `results-explorer-pr246-final-2026-05-10/benchmark-tpch-390.png` |
| `benchmark-tpch-768.png` | `results-explorer-pr246-final-2026-05-10/benchmark-tpch-768.png` |
| `benchmark-tpch-1280.png` | `results-explorer-pr246-final-2026-05-10/benchmark-tpch-1280.png` |
| `benchmark-tpch-1600.png` | `results-explorer-pr246-final-2026-05-10/benchmark-tpch-1600.png` |
| `benchmark-tpch-list-1280.png` | `results-explorer-pr246-final-2026-05-10/benchmark-tpch-list-1280.png` |
| `benchmark-tpch-high-contrast-1280.png` | `results-explorer-pr246-final-2026-05-10/benchmark-tpch-high-contrast-1280.png` |
| `benchmark-star-schema-390.png` | `results-explorer-pr246-final-2026-05-10/benchmark-star-schema-390.png` |
| `benchmark-star-schema-768.png` | `results-explorer-pr246-final-2026-05-10/benchmark-star-schema-768.png` |
| `benchmark-star-schema-1280.png` | `results-explorer-pr246-final-2026-05-10/benchmark-star-schema-1280.png` |
| `benchmark-star-schema-1600.png` | `results-explorer-pr246-final-2026-05-10/benchmark-star-schema-1600.png` |
| `platform-duckdb-390.png` | `results-explorer-pr246-final-2026-05-10/platform-duckdb-390.png` |
| `platform-duckdb-768.png` | `results-explorer-pr246-final-2026-05-10/platform-duckdb-768.png` |
| `platform-duckdb-1280.png` | `results-explorer-pr246-final-2026-05-10/platform-duckdb-1280.png` |
| `platform-duckdb-1600.png` | `results-explorer-pr246-final-2026-05-10/platform-duckdb-1600.png` |
| `platform-datafusion-390.png` | `results-explorer-pr246-final-2026-05-10/platform-datafusion-390.png` |
| `platform-datafusion-768.png` | `results-explorer-pr246-final-2026-05-10/platform-datafusion-768.png` |
| `platform-datafusion-1280.png` | `results-explorer-pr246-final-2026-05-10/platform-datafusion-1280.png` |
| `platform-datafusion-1600.png` | `results-explorer-pr246-final-2026-05-10/platform-datafusion-1600.png` |
| `result-detail-duckdb-390.png` | `results-explorer-pr246-final-2026-05-10/result-detail-duckdb-390.png` |
| `result-detail-duckdb-768.png` | `results-explorer-pr246-final-2026-05-10/result-detail-duckdb-768.png` |
| `result-detail-duckdb-1280.png` | `results-explorer-pr246-final-2026-05-10/result-detail-duckdb-1280.png` |
| `result-detail-duckdb-1600.png` | `results-explorer-pr246-final-2026-05-10/result-detail-duckdb-1600.png` |
| `compare-duckdb-aws-390.png` | `results-explorer-pr246-final-2026-05-10/compare-duckdb-aws-390.png` |
| `compare-duckdb-aws-768.png` | `results-explorer-pr246-final-2026-05-10/compare-duckdb-aws-768.png` |
| `compare-duckdb-aws-1280.png` | `results-explorer-pr246-final-2026-05-10/compare-duckdb-aws-1280.png` |
| `compare-duckdb-aws-1600.png` | `results-explorer-pr246-final-2026-05-10/compare-duckdb-aws-1600.png` |
| `compare-mixed-scale-valid-1280.png` | `results-explorer-pr246-final-2026-05-10/compare-mixed-scale-valid-1280.png` |
| `query-390.png` | `results-explorer-pr246-final-2026-05-10/query-390.png` |
| `query-768.png` | `results-explorer-pr246-final-2026-05-10/query-768.png` |
| `query-1280.png` | `results-explorer-pr246-final-2026-05-10/query-1280.png` |
| `query-1600.png` | `results-explorer-pr246-final-2026-05-10/query-1600.png` |
| `query-mobile-filter-drawer-390.png` | `results-explorer-pr246-final-2026-05-10/query-mobile-filter-drawer-390.png` |
| `screenshot-manifest.json` | `results-explorer-pr246-final-2026-05-10/screenshot-manifest.json` |

## Finding Closure Table

| Finding | Remediation owner | Status from final evidence | Evidence |
|---|---|---|---|
| VH-1 | `results-explorer-pr246-home-leaderboard-evidence-remediation` | Resolved visually; no initial active-looking grid focus ring observed | `home-390.png`, `home-1280.png` |
| VH-2 | `results-explorer-pr246-home-leaderboard-evidence-remediation` | Residual medium concern; Home rows now render loaded data, but Chromium smoke still flags first row below the historical 1200px mobile threshold | `home-390.png`, failed `responsive.spec.ts` |
| VH-3 | `results-explorer-pr246-result-compare-evidence-remediation` | Resolved visually; primary metric/actions precede the full Run Receipt | `result-detail-duckdb-390.png` |
| VH-4 | `results-explorer-pr246-result-compare-evidence-remediation` | Resolved visually; Compare leads with decision summary, baseline, chart state, and cards before full receipt | `compare-duckdb-aws-1280.png` |
| VH-5 | `results-explorer-pr246-query-workbench-evidence-remediation` | Resolved visually; results and exports precede advanced SQL/visible-column controls | `query-1280.png` |
| U-1 | `results-explorer-pr246-responsive-navigation-overflow-remediation` | Resolved visually; Query nav is visible at 390px and active on Query route | `home-390.png`, `query-390.png` |
| U-2 | `results-explorer-pr246-responsive-navigation-overflow-remediation` | Resolved visually for audited screenshots; scroll hints and table affordances are visible | `home-390.png`, `result-detail-duckdb-390.png`, `query-390.png` |
| U-3 | `results-explorer-pr246-browse-platform-evidence-remediation` | Resolved visually; browse pages expose persistent compare guidance before selection | `benchmark-tpch-1280.png`, `platform-duckdb-1280.png` |
| U-4 | `results-explorer-pr246-query-workbench-evidence-remediation` | Resolved visually; mobile filter drawer has header, reset, done, grouped facets, and visible table context | `query-mobile-filter-drawer-390.png` |
| DQ-1 | `results-explorer-pr246-home-leaderboard-evidence-remediation` | Resolved visually; metric family, unit, and direction are visible in Home cohort context | `home-390.png`, `home-speedup-1280.png` |
| DQ-2 | `results-explorer-pr246-home-leaderboard-evidence-remediation`; `results-explorer-pr246-browse-platform-evidence-remediation` | Resolved visually; value, heat, trust, and validation treatments are separated | `home-1280.png`, `benchmark-tpch-1280.png` |
| DQ-3 | `results-explorer-pr246-result-compare-evidence-remediation`; `results-explorer-pr246-responsive-navigation-overflow-remediation` | Resolved visually; Result Detail charts stay inside the mobile card | `result-detail-duckdb-390.png` |
| DQ-4 | `results-explorer-pr246-result-compare-evidence-remediation` | Resolved visually; same-cohort equal comparison renders a no-material-difference chart state | `compare-duckdb-aws-1280.png` |
| DQ-5 | `results-explorer-pr246-browse-platform-evidence-remediation` | Resolved visually for final evidence; platform pages show grouped result context and sparse-data states | `platform-duckdb-1280.png`, `platform-datafusion-1280.png` |
| DQ-6 | `results-explorer-pr246-query-workbench-evidence-remediation` | Resolved visually; public labels, units, row actions, and exports are visible | `query-1280.png` |
| DQ-7 | `results-explorer-pr246-browse-platform-evidence-remediation` | Resolved visually; SSB route uses SSB display and timing legend explains zero/sub-ms semantics | `benchmark-star-schema-1280.png` |
| DQ-8 | `results-explorer-pr246-result-compare-evidence-remediation` | Resolved visually; mixed-scale compare suppresses claims and keeps guardrail context attached | `compare-mixed-scale-valid-1280.png` |

## Browser Smoke Blockers

`npm run test:e2e:chromium` failed with:

| Failing check | Current failure | Gate impact |
|---|---|---|
| `responsive.spec.ts` Home mobile first row position | First leaderboard row top was `1508.5`, above the historical `1200` threshold | Blocks final closeout; decide whether to reduce Home vertical chrome or revise the responsive contract |
| `compare.spec.ts` single-id compare URL | URL remains `/results/compare?ids=ba6a8c83` instead of redirecting to Result Detail | Blocks final closeout; likely stale test contract after compare-selection recovery work |
| `index-sort-headers.spec.ts` platform heading wait | Test waits for `DuckDB Results`; current route exposes `duckdb Results` in one heading path | Blocks final closeout; normalize product heading or relax the test contract |
| `query.spec.ts` environment facet rows | Test cannot find the `Deployment: cloud` checkbox in the desktop filter panel | Blocks final closeout; verify whether facet ordering/collapse changed or facet rendering regressed |
| `result-detail.spec.ts` single-id compare link | `Compare this result` now stays on `/results/compare?ids=<id>` instead of redirecting back | Blocks final closeout; likely same single-id compare contract as `compare.spec.ts` |

## Verification

| Command | Result |
|---|---|
| `cd results-explorer && npm run test:e2e:fixtures` | PASS |
| `cd results-explorer && npm run build` before capture | PASS |
| `cd results-explorer && PR246_FINAL_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-final-evidence.spec.ts --workers=1` | PASS, 39 screenshots |
| `cd results-explorer && npm run typecheck` | PASS |
| `cd results-explorer && npm test` | PASS, 617 tests |
| `cd results-explorer && npm run build` | PASS |
| `cd results-explorer && npm run test:e2e:chromium` | FAIL, 5 failures listed above |

## Replay

```text
cd results-explorer
npm run test:e2e:fixtures
npm run build
PR246_FINAL_CAPTURE=1 npx playwright test --project=chromium \
  e2e/captures/pr246-final-evidence.spec.ts --workers=1
```

# Browser Acceptance Matrix

Checked source state: parent `c3ce0c9a1` plus local release-gate test edits on
`fix/results-explorer-release-gate-reconciliation`.

Command:

```bash
cd results-explorer && npx playwright test --project=chromium \
  e2e/captures/followup-usability-release.spec.ts \
  e2e/routes/benchmark-index.spec.ts \
  e2e/routes/platform-index.spec.ts \
  e2e/routes/compare.spec.ts \
  e2e/routes/compare-entrypoints.spec.ts \
  e2e/routes/query.spec.ts \
  e2e/routes/result-detail.spec.ts \
  e2e/responsive.spec.ts
```

Result: PASS, `64 passed`.

## Route/Control Coverage

| Route | Controls exercised | Evidence |
|---|---|---|
| `/results/` | Leaderboard cohort selector, compare entrypoint, secondary nav, responsive density, no-overflow guard. | `followup-usability-release.spec.ts`, `home.spec.ts` via full gate, `responsive.spec.ts`. |
| `/results/tpch/` | Benchmark switcher, scale/phase URL sync, Matrix/Ranks/List controls, heatmap sticky header, receipt disclosure/link, compare selection and sticky compare entrypoint. | `followup-usability-release.spec.ts`, `benchmark-index.spec.ts`, `compare.spec.ts`, `responsive.spec.ts`. |
| `/results/p/duckdb/` | Platform switcher, platform table rows, enabled/disabled compare selection, filter-strip contract, receipt links, duplicate-day trend state in full gate. | `followup-usability-release.spec.ts`, `platform-index.spec.ts`, `direct-route.spec.ts` via full gate. |
| `/results/compare/` and `?ids=...` | Empty builder, filters, compatible-only toggle, share URL, baseline selector, warning/guardrail rendering, chart tabs/buttons, result links, short/long ID canonicalization. | `compare.spec.ts`, `compare-entrypoints.spec.ts`, `compare-hard-block.spec.ts` via full gate. |
| `/results/query` | Facets, visible columns, row-limit toggle, SQL disclosure/starter/run, exports, sorting, compare tray and launch path. | `query.spec.ts`, `compare-entrypoints.spec.ts`, `followup-usability-release.spec.ts`, `responsive.spec.ts`. |
| `/results/r/<id>` | Breadcrumb, compare action, receipt/audit metadata, missing-metadata disclosure, metric labels, timings sort, missing-result error path. | `result-detail.spec.ts`, `followup-usability-release.spec.ts`, `result-detail-failures.spec.ts` via full gate. |

Remaining defects: none observed. External/documentation links and download
side effects are covered only where the e2e harness has deterministic download
assertions; no destructive controls are present.

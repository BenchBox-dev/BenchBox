# Results Explorer PR #246 Query Workbench Remediation Evidence

Date: 2026-05-07
TODO: `results-explorer-pr246-query-workbench-evidence-remediation`

## Baseline consulted

- PR #246 audit: `_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md`
- Baseline screenshots: `_project/audits/screenshots/results-explorer-hierarchy-usability-data-audit-20260507/`
- w0 evidence durability log: `_project/verification-logs/results-explorer-pr246-query-workbench-evidence-remediation/w0.log`

## Remediation summary

| Finding | Outcome |
|---|---|
| VH-5 Visible Columns hierarchy | Visible Columns is now a collapsed `Configure visible columns` disclosure after the results table and before Advanced SQL. The default desktop/mobile path leads with result summary, filters, table rows, row limit, row details, and visible-column exports. |
| U-4 mobile filter drawer clarity | Mobile filters open as an explicit `Filter results` drawer with a header, close/Done control, Escape/focus-trap behavior, and bottom `Reset filters` / `Apply filters` actions. |
| DQ-6 raw labels and formatting | Default table headers, facet labels, and chips use public display names; benchmark, scale, date, geomean, score, cost, and missing values are formatted consistently with the browse pages while raw schema names remain available only as advanced/schema hints. |

## After screenshots

Captured with `PR246_QUERY_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-query-remediation.spec.ts`.

Output directory: `_project/audits/screenshots/results-explorer-pr246-query-remediation-2026-05-07/`

Manifest: `_project/audits/screenshots/results-explorer-pr246-query-remediation-2026-05-07/screenshot-manifest.json`

Coverage:

- Query Workbench default route: 390, 768, 1280, 1600 px
- Query Workbench mobile filter drawer: 390 px

## Automated verification

- `npm test -- src/pages/__tests__/Query.test.tsx src/components/__tests__/FacetRail.test.tsx` → passed, 21 tests.
- `npm run typecheck` → passed.
- `npm run test:e2e:fixtures && npm run build && npx playwright test --project=chromium --grep query` → passed, 16 tests / 1 skipped capture.
- `PR246_QUERY_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-query-remediation.spec.ts` → passed, 5 screenshots + manifest captured.

## Residual notes

No release-blocking Query Workbench residuals remain for VH-5, U-4, or DQ-6 in this pass. Cross-route responsive/mobile navigation evidence remains owned by the PR #246 responsive-navigation TODO.

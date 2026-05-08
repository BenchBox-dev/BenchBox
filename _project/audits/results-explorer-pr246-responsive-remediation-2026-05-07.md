# Results Explorer PR #246 responsive/navigation/overflow remediation

Date: 2026-05-07
TODO: `results-explorer-pr246-responsive-navigation-overflow-remediation`

## Responsive contracts implemented

| Route/surface | 390px / 768px contract |
| --- | --- |
| Explorer shell | Secondary nav wraps instead of clipping; `Query` remains a visible route link with `aria-current` on `/results/query`. |
| Home recent results | Table sits in an intentional horizontal scroll container with a visible scroll affordance and sticky right action column. |
| Meta leaderboard | Dense grid keeps the platform context column sticky while the metric matrix scrolls horizontally. |
| Benchmark heatmap/list | Mobile keeps card summaries; tablet/desktop heatmap scrolls intentionally with a query-column cue and sticky query context. |
| Platform index | Compare/result rows are in an intentional scroll container with sticky compare/action columns and cohort/source affordance copy. |
| Result detail | Timing and sample rows expose scroll cues and sticky first/action context; chart SVGs are capped to their cards. |
| Compare | Decision summary precedes detailed evidence; Query-Level Diff scrolls intentionally with sticky query/platform/action context. |
| Query workbench | Results table, SQL output, and downloads remain reachable; mobile filters use the drawer and visible result-count trigger. |

## Evidence recapture

- Capture spec: `results-explorer/e2e/captures/pr246-responsive-remediation.spec.ts`
- Screenshot manifest: `_project/audits/screenshots/results-explorer-pr246-responsive-remediation-2026-05-07/screenshot-manifest.json`
- Captured mobile/tablet routes: home, TPC-H benchmark, SSB benchmark, DuckDB platform, DataFusion platform, DuckDB result detail, DuckDB/DataFusion compare, Query workbench, Query filter drawer.

## Verification

- `cd results-explorer && npm test -- src/components/__tests__ src/pages/__tests__ && npm run typecheck` — pass.
- `cd results-explorer && npm run test:e2e:fixtures && npm run build && npx playwright test --project=chromium --grep "responsive|layout|a11y|mobile"` — pass, 24 passed / 2 skipped captures.
- `cd results-explorer && PR246_RESPONSIVE_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-responsive-remediation.spec.ts` — pass, 17 screenshots plus manifest.

## Notes

Intentional horizontal scroll is now paired with either an explicit cue, sticky context, or a mobile card fallback. The responsive Playwright smoke asserts route navigation, viewport matrix reachability, intentional-overflow containment, and mobile/tablet table affordances so future PRs cannot silently regress the PR #246 evidence set.

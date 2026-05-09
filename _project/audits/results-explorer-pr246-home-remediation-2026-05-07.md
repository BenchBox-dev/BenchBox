---
develop_sha: 45be4908a77eea5eef1fa72ca2539ad5e11cbe27
---
# Results Explorer PR #246 Home Leaderboard Remediation Evidence

Date: 2026-05-07
TODO: `results-explorer-pr246-home-leaderboard-evidence-remediation`

## Baseline consulted

- PR #246 audit: `_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md`
- Baseline screenshots: `_project/audits/screenshots/results-explorer-hierarchy-usability-data-audit-20260507/`
- w0 evidence durability log: `_project/verification-logs/results-explorer-pr246-home-leaderboard-evidence-remediation/w0.log`

## Remediation summary

| Finding | Outcome |
|---|---|
| VH-1 focus/selection confusion | MetaLeaderboard still keeps roving tabindex, but the first cell is not focused on initial render and visual focus remains tied to `focus-visible` keyboard focus. |
| VH-2 filter/control hierarchy | Leaderboard sort and display mode now share one labelled control group; the visually long average-rank sort copy is shortened while the full contract remains on the average-rank column and tooltip. |
| DQ-1 metric/unit/direction context | Each cohort header now includes visible phase, metric, unit where applicable, and direction. Speedup mode explains below-`1.00x` values in the visible legend. |
| DQ-2 heatmap/badge semantics | Validation-success badges now use an info tone rather than the same success tone as maintainer trust; numeric cell values remain primary, with badges subordinate below the value. |

## After screenshots

Captured with `PR246_HOME_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-home-remediation.spec.ts`.

Output directory: `_project/audits/screenshots/results-explorer-pr246-home-remediation-2026-05-07/`

Manifest: `_project/audits/screenshots/results-explorer-pr246-home-remediation-2026-05-07/screenshot-manifest.json`

Coverage:

- Home times mode: 390, 768, 1280, 1600 px
- Home ranks mode: 390, 768, 1280, 1600 px
- Home speedup mode: 390, 768, 1280, 1600 px

## Automated verification

- `npm test -- src/components/__tests__/MetaLeaderboard.test.tsx src/components/__tests__/MetaLeaderboard.a11y.test.tsx src/pages/__tests__/Home.test.tsx` → passed, 36 tests.
- `npm test -- src/components/__tests__/TrustBadge.test.tsx` was included during focused badge verification → passed.
- `npm run typecheck` → passed.
- `npm run test:e2e:fixtures && npm run build && npx playwright test --project=chromium --grep home` → passed, 4 passed / 1 skipped capture.
- `PR246_HOME_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-home-remediation.spec.ts` → passed, 12 screenshots + manifest captured.

## Residual notes

No release-blocking Home residuals remain for VH-1, VH-2, DQ-1, or DQ-2 in this pass. Cross-route responsive/mobile evidence remains owned by the PR #246 responsive-navigation TODO.

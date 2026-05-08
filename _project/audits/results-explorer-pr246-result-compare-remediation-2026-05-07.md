---
develop_sha: 8eae1290703831f4cb640df18a5141929befca91
---
# Results Explorer PR #246 Result Detail / Compare Remediation Evidence

Date: 2026-05-07
TODO: `results-explorer-pr246-result-compare-evidence-remediation`

## Baseline consulted

- PR #246 audit: `_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md`
- Baseline screenshots: `_project/audits/screenshots/results-explorer-hierarchy-usability-data-audit-20260507/`
- w0 evidence durability log: `_project/verification-logs/results-explorer-pr246-result-compare-evidence-remediation/w0.log`

## Remediation summary

| Finding | Outcome |
|---|---|
| VH-3 Result Detail receipt dominates | Result Detail now leads with a compact result summary, primary metric direction, trust/validation badges, and compare/download actions. Run Receipt remains visible, but moves below chart evidence instead of owning the first analytical viewport. |
| VH-4 Compare receipt dominates | Compare now leads with compact comparability guardrails, Decision Summary, baseline control, and chart evidence. The full Comparability Receipt remains available below the decision/chart/query evidence path. |
| DQ-3 Result Detail chart clips | Query histogram SVGs now use responsive `width="100%"` with a mobile-safe viewBox fallback instead of forcing a 400px minimum width. |
| DQ-4 equal-value speedup chart whitespace | Normalized Speedup renders a compact parity state when all per-query speedups are effectively `1.00×`, avoiding a sparse chart with empty domain space. |
| DQ-8 mixed-scale guardrail context | Query-Level Diff now repeats the suppression reason beside raw query evidence whenever winner claims are suppressed. |

## After screenshots

Captured with `PR246_RESULT_COMPARE_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-result-compare-remediation.spec.ts`.

Output directory: `_project/audits/screenshots/results-explorer-pr246-result-compare-remediation-2026-05-07/`

Manifest: `_project/audits/screenshots/results-explorer-pr246-result-compare-remediation-2026-05-07/screenshot-manifest.json`

Coverage:

- Result Detail DuckDB route: 390, 768, 1280, 1600 px
- Compare DuckDB vs AWS route: 390, 768, 1280, 1600 px
- Mixed-scale Compare guardrail: 1280 px

## Automated verification

- `npm test -- src/pages/__tests__/ResultDetail.test.tsx src/pages/__tests__/Compare.test.tsx src/components/__tests__/CompareSummary.test.tsx src/components/__tests__/ComparabilityReceipt.test.tsx src/components/__tests__/QueryDiffTable.test.tsx src/components/__tests__/NormalizedSpeedupChart.test.tsx src/components/__tests__/charts.smoke.test.tsx src/components/__tests__/ChartPanel.test.tsx` → passed, 91 tests.
- `npm run typecheck` → passed.
- `npm run test:e2e:fixtures && npm run build && npx playwright test --project=chromium e2e/routes/result-detail.spec.ts e2e/routes/compare.spec.ts e2e/failures/compare-hard-block.spec.ts` → passed, 13 tests.
- `PR246_RESULT_COMPARE_CAPTURE=1 npx playwright test --project=chromium e2e/captures/pr246-result-compare-remediation.spec.ts` → passed, 9 screenshots + manifest captured.

## Residual notes

No release-blocking Result Detail / Compare residuals remain for VH-3, VH-4, DQ-3, DQ-4, or DQ-8 in this pass. Cross-route responsive/navigation evidence remains owned by the PR #246 responsive-navigation TODO.

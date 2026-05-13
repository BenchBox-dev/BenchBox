# Stale Test Reconciliation Summary

Checked source state: parent `c3ce0c9a1` plus local release-gate test edits on
`fix/results-explorer-release-gate-reconciliation`.

## Contract-Aligned Edits

| File | Change | Contract |
|---|---|---|
| `results-explorer/e2e/captures/followup-usability-release.spec.ts` | Uses `/results/tpch/?sf=0.01&phase=standard`; opens matrix row `Receipt and metadata`; selects the first enabled platform compare row and compares against the baseline disabled count. | Fixture route must use a valid cohort; dense matrix receipt reachability is behind the per-row disclosure; disabled compare rows remain disabled while compatible siblings stay selectable. |
| `results-explorer/e2e/failures/platform-index-cold-load.spec.ts` | Counts only `tr[data-testid]` product rows. | Cold-load regression concerns result table rows, not duplicate-day evidence rows. |
| `results-explorer/e2e/routes/direct-route.spec.ts` | Counts only `main table tbody tr[data-testid]`. | Direct-route parity compares product result rows across hard-load and in-app switcher paths. |
| `results-explorer/e2e/routes/compare-entrypoints.spec.ts` | Expects `selected outside filters` without parentheses. | Origin/status chips are separate copy surfaces from row identity. |
| `results-explorer/e2e/routes/index-sort-headers.spec.ts` | Reads the visible `.font-medium` platform label before checking sort order. | Platform sort order is by display name, not by concatenated version/receipt metadata text. |
| `results-explorer/e2e/routes/result-detail.spec.ts` | Expects `Median latency`. | Result detail display label is `Median latency`; units are carried by formatted metric values. |

## Targeted Verification

Command:

```bash
cd results-explorer && npx playwright test --project=chromium \
  e2e/captures/followup-usability-release.spec.ts \
  e2e/failures/platform-index-cold-load.spec.ts \
  e2e/routes/compare-entrypoints.spec.ts \
  e2e/routes/direct-route.spec.ts \
  e2e/routes/index-sort-headers.spec.ts \
  e2e/routes/result-detail.spec.ts
```

Result: PASS, `28 passed`.

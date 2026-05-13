# Results Explorer Release Gate Classification

Checked SHA: `c3ce0c9a1` on `fix/results-explorer-release-gate-reconciliation`.

## Reproduction

Commands:

- `cd results-explorer && npm run test:e2e:fixtures`
- `cd results-explorer && npm test -- --run`
- `cd results-explorer && npm run build`
- `cd results-explorer && npx playwright test --project=chromium`

Results before test reconciliation:

- Fixture refresh: PASS.
- Unit/component tests: PASS, 64 files, 695 tests.
- Build: PASS.
- Chromium e2e: FAIL, 79 passed, 7 failed, 10 skipped, 5 did not run.

## Failure Classification

| Test | Failure | Classification | Contract |
|---|---|---|---|
| `e2e/captures/followup-usability-release.spec.ts` benchmark detail | Requested `phase=power`, then asserted matrix header on a no-data `standard` page | Stale test | TPC-H fixture phase is `standard`; release-gate tests must use a valid cohort route before checking matrix controls. |
| `e2e/captures/followup-usability-release.spec.ts` platform detail | Clicked the first platform checkbox, which is now disabled by coverage eligibility | Stale test | Disabled-row compare contract requires disabled controls to remain disabled with recovery copy; tests must choose an enabled row before asserting cohort locking. |
| `e2e/failures/platform-index-cold-load.spec.ts` | Counted every table row, including duplicate-day trend-state rows | Stale test | Cold-load regression concerns result table rows, identified by `tr[data-testid]`, not secondary evidence tables. |
| `e2e/routes/direct-route.spec.ts` | Counted every table row, including duplicate-day trend-state rows | Stale test | Direct-route row-count parity concerns result table rows, identified by `tr[data-testid]`. |
| `e2e/routes/compare-entrypoints.spec.ts` | Expected `(selected outside filters)` but status chip now renders `selected outside filters` without parentheses | Stale test | Compare origin and filter-state chips are separate from platform identity; the status copy is visible without being concatenated into the identity. |
| `e2e/routes/index-sort-headers.spec.ts` | Sorted full platform cell text including version/metadata instead of platform labels | Stale test | Matrix platform sort is by platform display name; tests should read the visible platform label element, not the whole metadata cell. |
| `e2e/routes/result-detail.spec.ts` | Expected legacy `Median (ms)` column label | Stale test | Result detail uses the accepted display label `Median latency`; units are carried by formatted values and surrounding metric copy. |

No product defect was identified in this pass. All edits in w2 are test assertions/selectors aligned to existing documented contracts.

## Post-Edit Recheck

After the stale assertions above were updated, the first full Chromium rerun
showed one additional compare failure:

- `e2e/routes/compare.spec.ts` reported `Cannot compare` for
  `tpch-duckdb-sf0.01-20260403-010ee756`.
- Fixture inspection showed both the short-id mapping and
  `result_detail_metrics` row were present in
  `results-explorer/test-fixtures/.generated/data/results.duckdb`.
- A focused fresh-server rerun of `e2e/routes/compare.spec.ts` passed
  (`6 passed`), and the exact default full Chromium command passed afterward
  (`91 passed, 10 skipped`).

Classification: environment/server-state artifact during the intermediate
rerun, not a product defect and not a stale test edit.

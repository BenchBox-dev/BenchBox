# Full Release Gate Evidence

Checked source state: parent `c3ce0c9a1` plus local release-gate test edits on
`fix/results-explorer-release-gate-reconciliation`.

## Commands

| Command | Result |
|---|---|
| `cd results-explorer && npm run test:e2e:fixtures` | PASS |
| `cd results-explorer && npm test -- --run` | PASS, `64 passed` files and `695 passed` tests |
| `cd results-explorer && npm run build` | PASS, Vite built production assets |
| `cd results-explorer && npx playwright test --project=chromium` | PASS, `91 passed`, `10 skipped`, zero unexpected failures |

## Notes

- The intermediate full Chromium rerun after the first stale-test edits failed
  once in `e2e/routes/compare.spec.ts`. The fixture DB contained the expected
  short-id and detail rows; a focused fresh-server compare rerun passed
  (`6 passed`), and the exact default full Chromium command passed afterward.
- Raw stdout remains in `/tmp`:
  - `/tmp/results-explorer-release-fixtures.log`
  - `/tmp/results-explorer-release-unit.log`
  - `/tmp/results-explorer-release-build.log`
  - `/tmp/results-explorer-release-targeted-e2e.log`
  - `/tmp/results-explorer-release-compare-e2e.log`
  - `/tmp/results-explorer-release-chromium-exact.log`

PASS: release gate is green after stale-test reconciliation.

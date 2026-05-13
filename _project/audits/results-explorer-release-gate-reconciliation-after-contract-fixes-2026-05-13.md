---
develop_sha: c3ce0c9a1463f925e3607be3aad794d4c6039edc
---

# Results Explorer Release Gate Reconciliation

Checked source state: parent `c3ce0c9a1` plus local release-gate test edits on
`fix/results-explorer-release-gate-reconciliation`.

## Executive Summary

Recommendation: ship the reconciled Results Explorer gate. The original red
Chromium gate was stale-test drift after the contract fixes, not active product
regression. The exact release gate now passes with `91 passed`, `10 skipped`,
and zero unexpected failures.

## Command Summary

| Gate | Command | Result |
|---|---|---|
| Fixture refresh | `cd results-explorer && npm run test:e2e:fixtures` | PASS |
| Unit/component | `cd results-explorer && npm test -- --run` | PASS, `64` files / `695` tests |
| Build | `cd results-explorer && npm run build` | PASS |
| Targeted stale-test set | `cd results-explorer && npx playwright test --project=chromium ...` | PASS, `28 passed` |
| Chromium release gate | `cd results-explorer && npx playwright test --project=chromium` | PASS, `91 passed`, `10 skipped` |
| Browser route matrix | `cd results-explorer && npx playwright test --project=chromium ...` | PASS, `64 passed` |

## Closed Issue Mapping

| Original failure | Resolution |
|---|---|
| Benchmark route used invalid `phase=power` fixture state. | Route now uses `/results/tpch/?sf=0.01&phase=standard`. |
| Matrix receipt assertion expected receipt link in the old dense cell position. | Test opens `Receipt and metadata` and asserts the visible receipt link. |
| Platform detail clicked the first checkbox even when disabled. | Test selects the first enabled checkbox and verifies disabled-count recovery after uncheck. |
| Platform/direct-route row counts included duplicate-day trend evidence rows. | Tests count product rows via `tr[data-testid]`. |
| Compare builder expected parentheses around `selected outside filters`. | Test asserts current status-chip copy without conflating identity and chip punctuation. |
| Benchmark sort test read full platform cell metadata. | Test reads the visible platform label before checking sort order. |
| Result detail expected legacy `Median (ms)`. | Test asserts accepted `Median latency` label. |

## Browser Acceptance

| Route | Covered controls |
|---|---|
| Home | Leaderboard filters, display/sort modes, compare entrypoint, secondary nav, mobile density. |
| Benchmark detail | Switcher, scale/phase sync, Matrix/Ranks/List, sticky heatmap, receipt disclosure, compare selection. |
| Platform detail | Switcher, row table, compare selection/disabled recovery, filter-strip contract, receipts, trend evidence. |
| Compare | Empty builder, filters, compatible-only behavior, share URL, baseline selector, guardrails, charts, result links. |
| Query Workbench | Facets, visible columns, SQL disclosure/run, exports, sorting, row detail links, compare tray/launch. |
| Result detail | Breadcrumb, compare action, receipt/audit metadata, metric labels, timings/samples sorting, related navigation. |

## Remaining Follow-Ups

None. No unresolved P0/P1 product defect remains from this release gate. The
only transient finding was an intermediate compare rerun that rendered
`Cannot compare` despite the fixture DB containing the short-id and detail
rows; a fresh compare rerun and the exact final Chromium gate both passed.

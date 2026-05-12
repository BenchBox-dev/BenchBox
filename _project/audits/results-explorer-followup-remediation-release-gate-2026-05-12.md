---
develop_sha: 2c65387c3637f19bfaca6ddc1ef0afb8ee804489
---

# Results Explorer Follow-Up Remediation Release Gate

Date: 2026-05-12
Checked SHA: `2c65387c3637f19bfaca6ddc1ef0afb8ee804489`
Status: PASS

## Snapshot

- Snapshot used: `results-explorer/test-fixtures/.generated/data/results.duckdb`
- Fixture generation: PASS, see `_project/verification-logs/results-explorer-followup-remediation-release-gate/w1-final-e2e-fixtures.log`
- Public snapshot command: `results-explorer/public/data/results.duckdb` is absent in this checked tree; the exact command and skip reason are captured in `w1-final-public-snapshot-command.log`.
- Snapshot invariants: PASS, see `w1-final-snapshot-invariants.log`
- SQL smoke: PASS, see `w1-final-sql-smoke.log`

Key counts:

| Check | Result |
|---|---:|
| Compare-eligible display rows | 10 |
| Cohorts with 2+ comparable rows | 1 |
| Ambiguous unranked leaderboard rows | 0 |
| Ranked rows carrying exclusion reasons | 0 |
| Excluded matrix cells without reason | 0 |
| Valid matrix timing cells | 225 |
| Power chart rows | 10 |
| Latency chart rows | 11 |
| Public result rows in fixture snapshot | 11 |
| Compare warning input reasons | 1 insufficient_query_coverage |

## Automated Checks

| Command | Status | Evidence |
|---|---|---|
| `cd results-explorer && npm run test:e2e:fixtures` | PASS | `w1-final-e2e-fixtures.log` |
| `uv run -- python _project/scripts/results_explorer_snapshot_invariants.py results-explorer/test-fixtures/.generated/data/results.duckdb` | PASS | `w1-final-snapshot-invariants.log` |
| SQL smoke against regenerated fixture snapshot | PASS | `w1-final-sql-smoke.log` |
| `uv run -- python -m pytest tests/unit/core/explorer_pipeline tests/unit/cli/test_explorer_build_contract.py -q` | PASS, 253 tests | `w2-final-backend-explorer-tests.log` |
| `cd results-explorer && npm test -- --run` | PASS, 687 tests | `w2-final-frontend-tests-rerun.log` |
| `cd results-explorer && npm run typecheck` | PASS | `w2-final-typecheck.log` |
| `cd results-explorer && npm run build` | PASS | `w2-final-build.log` |
| `make audit-sha-check FILE=_project/audits/results-explorer-followup-remediation-release-gate-2026-05-12.md AUDIT_SHA_TARGET_REF=origin/develop` | PASS | `w4-final-audit-sha-check.log` |
| `rg -n "Leaderboards|Benchmark|Platform|Query Workbench|Compare|Result detail|PASS|FAIL" _project/verification-logs/results-explorer-followup-remediation-release-gate/w3-final-browser.log` | PASS | `w4-final-verification-grep.log` |
| `uv run --project _project/scripts -- python _project/scripts/todo_cli.py reindex` | PASS | `w5-final-todo-reindex.log` |
| `uv run --project _project/scripts -- python _project/scripts/todo_cli.py validate` | PASS | `w5-final-todo-validate.log` |
| `uv run --project _project/scripts -- python _project/scripts/todo_cli.py check-graph` | PASS | `w5-final-todo-check-graph.log` |

## Browser Acceptance

Fixture-backed server:

- Command: `cd results-explorer && node scripts/serve-browser-tests.mjs --port 4353 --host 127.0.0.1`
- Evidence: `w3-final-server.log`

Serial Chromium acceptance passed with 31 PASS / 0 FAIL. Evidence:
`w3-final-browser.log`.

Route matrix:

| Route | Status | Evidence Checked |
|---|---|---|
| `/results/` | PASS | Leaderboards, Benchmarks, Platforms, Compare, and Query navigation rendered. |
| `/results/tpch/?phase=standard` | PASS | Matrix, Ranks, List, chart tabs, reduced-color toggle, and compare tray selection worked. |
| `/results/p/duckdb/` | PASS | Platform table, disabled compare reason, sorting, and same-cohort compare selection worked. |
| `/results/query` | PASS | Filters, visible columns, SQL disclosure, JSON/CSV exports, and compare selection worked. |
| `/results/compare` | PASS | Empty builder rendered selectable runs and recovery states. |
| `/results/compare?ids=d28345e6,ba6a8c83` | PASS | Explicit IDs rendered TPC-H comparison, Query-Level Diff, and Share URL affordance. |
| `/results/compare?ids=a8225285,ba6a8c83` | PASS | Partial-coverage warning affordance remained visible. |
| `/results/r/tpch-duckdb-sf0.01-20260403-010ee756` | PASS | Result summary, exact score evidence, latency tables, receipt route, and Compare-this-result entrypoint worked. |

## Closure Matrix

| Issue Area | Status | Evidence |
|---|---|---|
| Comparison eligibility contract | Closed | DONE dependency plus snapshot invariants and SQL smoke. |
| Compare entrypoint happy paths | Closed | Compare route, benchmark/platform/query selection, and explicit IDs passed browser acceptance. |
| Compare disabled recovery states | Closed | Query/platform disabled reason and Compare builder recovery states remained visible. |
| Leaderboard rank evidence semantics | Closed | SQL smoke reports 0 ambiguous unranked rows and 0 ranked rows carrying exclusion reasons. |
| Leaderboard scope filter contract | Closed | Browser acceptance covered benchmark/platform scope; SQL smoke reports 2 benchmarks, 7 platforms, 11 public rows. |
| Chart run identity labels | Closed | SQL smoke retained duplicate-label pressure evidence; browser chart tabs rendered without duplicate-label release blocker. |
| Chart dataset eligibility | Closed | SQL smoke reports nonempty power and latency datasets with no unexplained excluded matrix cells. |
| Metric formatting | Closed | SQL smoke captured large score, latency, coverage, and speedup samples; Result Detail exact score evidence remained visible. |
| Compare warning affordance | Closed | SQL smoke reports warning input counts; browser acceptance covered partial-coverage warning route. |
| Theme/density | Closed | Browser acceptance covered dense route controls and exports without layout-blocking failures. |
| Direct route/copy hardening | Closed | Direct benchmark, platform, query, compare, and result detail routes loaded from the production build. |
| Result Detail metric-formatting regression | Closed | Full frontend suite passed after PR #373; browser acceptance verified `Median latency`, exact score evidence, and Compare-this-result. |

## Defect Register

No unresolved P0/P1 defects reproduced on the checked SHA. The prior P1 Result Detail
metric-formatting regression is closed by PR #373 and verified here by the full
frontend suite plus browser route acceptance.

## Closure

The release gate passes. `results-explorer-followup-remediation-release-gate`
has been moved to `_project/DONE`, TODO metadata has been reindexed, and the
verification logs linked above are the final evidence for the follow-up
remediation batch.

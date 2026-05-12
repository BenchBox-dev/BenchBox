---
develop_sha: b9f4f3531d74a4f3a64ae6405620e30fcf294144
---

# Results Explorer Follow-Up Remediation Release Gate

Date: 2026-05-12
Checked SHA: `b9f4f3531`
Status: FAIL / BLOCKED

## Snapshot

- Snapshot used: `results-explorer/test-fixtures/.generated/data/results.duckdb`
- Fixture generation: PASS, see `_project/verification-logs/results-explorer-followup-remediation-release-gate/w1-e2e-fixtures.log`
- Public snapshot command: `results-explorer/public/data/results.duckdb` is absent in this checked tree; the exact command is captured in `w1-public-snapshot-command.log`.
- Snapshot invariants: PASS, see `w1-snapshot-invariants.log`
- SQL smoke: PASS, see `w1-sql-smoke.log`

Key counts:

| Check | Result |
|---|---:|
| Compare-eligible display rows | 10 |
| Cohorts with 2+ comparable rows | 1 |
| Ambiguous unranked leaderboard rows | 0 |
| Excluded matrix cells without reason | 0 |
| Valid matrix timing cells | 225 |
| Public result rows in fixture snapshot | 11 |

## Automated Checks

| Command | Status | Evidence |
|---|---|---|
| `uv run -- python -m pytest tests/unit/core/explorer_pipeline tests/unit/cli/test_explorer_build_contract.py -q` | PASS | `w2-backend-explorer-tests.log` |
| `cd results-explorer && npm test -- --run` | FAIL | `w2-frontend-tests.log`, `w2-frontend-failure-summary.log` |
| `cd results-explorer && npm run typecheck` | PASS | `w2-typecheck.log` |
| `cd results-explorer && npm run build` | PASS | `w2-build.log` |

## Blocking Defect

Severity: P1

Defect: Result Detail metric-formatting regression after the shared formatter rollout.

Evidence:

- `src/pages/__tests__/ResultDetail.test.tsx` has 3 failing tests in the full frontend suite.
- The default median table no longer matches the expected `Median (ms)` contract.
- The expanded raw table no longer matches the expected `Duration (ms)` contract.
- The canonical result summary renders compact `3,000` rather than preserving exact `3,000.42` score evidence.

Root cause:

The metric-formatting remediation correctly centralized compact formatting for dense tables and charts, but it applied compact score text to Result Detail, which is a receipt/detail surface where exact evidence is expected. It also changed duration headers without closing the test/product contract for raw millisecond evidence versus dynamic latency units.

Blind spot:

The metric-formatting TODO ran targeted route/component tests but did not run the full Results Explorer frontend suite. CI for PR #370 also did not catch the full `ResultDetail` suite, so the release gate found the regression only after merge.

Follow-up:

Created `_project/TODO/results-explorer-followup-todo-review/planning/results-explorer-result-detail-metric-formatting-regression.yaml`.

## Browser Acceptance

Not run. The gate stopped at w2 because the automated frontend suite failed. Running browser acceptance would not unblock the release decision while the full suite has a P1 detail-route regression.

## Closure

Release gate remains open and blocked. Do not move `results-explorer-followup-remediation-release-gate` to DONE until `results-explorer-result-detail-metric-formatting-regression` is complete and the release-gate automated/browser evidence is rerun.

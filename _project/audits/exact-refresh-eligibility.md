---
date: 2026-09-08
baseline: _project/analysis/ci-lifecycle-baseline.json (349 in-window PRs, frozen window 2026-08-11 through 2026-09-08)
---

# Exact-refresh eligibility: shadow distribution and timing analysis

Scope: measurement only. No workflow, ruleset, or classifier change; no reduced
refresh is activated and no dropped path is revived. Reason codes are owned by
`scripts/pr_refresh_certification.py` (`REASON_CODES`); this audit does not
redefine them.

## 1. Refresh distribution reconciled with the frozen baseline

From `avoidable_refresh_analysis` in the frozen lifecycle baseline (classifier
method: two-parent head whose files(P1...M) are a subset of files(B...P2)):

| Push kind over 28 days | Count |
|---|---|
| Ancestry-only refresh (exact two-parent, no feature-side edits) | 284 |
| Refresh carrying feature edits | 7 |
| Externally-based merges (first parent outside PR history) | 3 |
| Ordinary single-parent feature pushes | remainder |

284 ancestry-only refreshes occurred across 141 of 349 PRs. The 7
refreshes-with-feature-edits and 3 externally-based merges stay outside the
avoidable count (conservative). Denominator: the 349 in-window baseline PRs;
window start/end match the baseline cohort exactly.

## 2. Timing analysis

From baseline `merged_at` ordering and final-head `required_gate_seconds`:

- Merge interarrival: p50 41.1 min, p90 283.6 min (n = 349).
- Final-head required-gate wall: p50 21.6 min, p95 33.3 min (n = 267 heads
  with an observed gate).

The gate wall (p50 21.7) fits inside one typical interarrival gap (p50 41.1),
so a refreshed PR usually finishes before the next merge lands; starvation
needs a merge cluster inside the ~22–33 minute gate window, consistent with
the 108 PRs that show superseded-head cancellations in the concurrency audit
correction. Timing alone does not make a refresh eligible: the classifier
still requires the prior gate green on the exact parent (`prior_check_not_success`
otherwise), the check bound to that parent (`prior_check_unbound` otherwise),
and a non-merge parent (`chained_refresh` otherwise).

## 3. Recorded insufficiency: per-observation reason codes

No `refresh_audit_v1` observations block is embedded in this audit. The block
validator requires one observation identity (pr/head/run/attempt) per
denominator head with a classifier reason code, and the frozen lifecycle
baseline retains per-head aggregates only — no run IDs, attempt numbers, or
per-context check conclusions. Reconstructing `prior_check_not_success` vs
`prior_check_unbound` vs `chained_refresh` per historical refresh would need
prior-gate conclusions at refresh time, which only the develop-refresh-shadow
lane artifacts record as they are emitted.

Next condition: the shadow lane accrues verdict-bearing artifacts prospectively;
a later audit pass embeds the observations block once run/attempt identities
exist for a complete denominator, and `--validate-refresh-audit` reconciliation
(seq 3) remains pending until then. Owner: the merge-queue/refresh-measurement
follow-up, not this implementation batch.

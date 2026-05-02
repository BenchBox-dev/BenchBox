---
id: 2026-04-30-114720-pr-ci-cost-leverage
date: 2026-04-30
status: actioned
finding_kind: missed-axis
review_context: "L2 merge-loop audit / dev-loop simplification planning (2026-04-30)"
related_paths:
  - .github/workflows/test.yml
  - .github/workflows/lint.yml
suggested_sweep: "Compare PR-tier wall time before and after CI rebalancing; keep required checks distinct from jobs that merely run."
todo_id: null
---

# PR CI cost is the highest-leverage move

## Finding
PR CI on develop is already heavy today; reducing it is the highest-leverage standalone move

## Why this matters
Reviewing only branch protection misses the separate cost of non-required jobs that still run on every PR and consume queue time.

## Suggested next steps
- [ ] In Step 3, distinguish required status checks from all PR-triggered workflow jobs.
- [ ] Preserve a before/after CI-duration baseline so the rebalancing outcome is measurable.

## Triage log

- 2026-05-02: actioned — Sweep 2026-05-02: PR CI rebalance shipped. .github/workflows/pr.yml is the required lightweight 'Develop PR' gate with path-based classification (ci-paths job + .ci-paths/, content-only PRs skip Python tests); broader OS/Python/security/integration/parity coverage runs on schedule via .github/workflows/nightly.yml. Required vs non-required job split done in dev-loop-step-3 + step-3a (both Done). Before/after measurement is tracked separately in dev-loop-step-5-measurement-window (Blocked, in 30-day window).

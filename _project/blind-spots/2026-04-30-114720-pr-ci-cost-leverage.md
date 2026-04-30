---
id: 2026-04-30-114720-pr-ci-cost-leverage
date: 2026-04-30
status: open
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

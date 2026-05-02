---
id: 2026-04-30-114719-separable-dev-loop-decisions
date: 2026-04-30
status: actioned
finding_kind: framework-gap
review_context: "L2 merge-loop audit / dev-loop simplification planning (2026-04-30)"
related_paths:
  - AGENTS.md
  - CLAUDE.md
  - Makefile
suggested_sweep: "Check future dev-loop plans for bundled policy and workflow decisions before implementation."
todo_id: null
---

# Dev-loop plan bundled separable decisions

## Finding
Original plan bundled "stop babysitting PRs" with "promote develop to release-grade gating" — separable decisions

## Why this matters
Bundling local-loop friction fixes with release-grade gating changes can make a useful small change look dependent on a larger policy shift.

## Suggested next steps
- [ ] During dev-loop TODO review, split local ergonomics, CI policy, and release policy into separate decisions.
- [ ] Re-check any queue or gating plan against the Step 0 decision record before implementation.

## Triage log

- 2026-05-02: actioned — Sweep 2026-05-02: dev-loop plan was split into Steps 0-6 (verify/local/pool/CI-rebalance/strict-base/post-merge/measurement/queue-gate) per the advice. Local ergonomics, CI policy, and release policy each own a separate TODO; Step 6 queue gate is explicitly Blocked on Step 5 measurement. Rule embedded as project structure.

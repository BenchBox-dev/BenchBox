---
id: 2026-04-30-114719-separable-dev-loop-decisions
date: 2026-04-30
status: open
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

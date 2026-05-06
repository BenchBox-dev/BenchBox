---
id: 2026-04-30-114724-post-merge-safety-tension
date: 2026-04-30
status: open
finding_kind: framework-gap
review_context: "L2 merge-loop audit / dev-loop simplification planning (2026-04-30)"
related_paths:
  - .github/workflows/develop-post-merge.yml
  - .github/workflows/auto-merge-on-open.yml
suggested_sweep: "During Step 4, decide whether post-merge auto-revert replaces or complements any queue-like safety mechanism."
todo_id: null
---

# Post-merge safety net tension was unresolved

## Finding
develop-post-merge.yml is the actual safety net; queue plan kept it as belt-and-suspenders without resolving the tension

## Why this matters
If the post-merge workflow is the real protection layer, adding a queue may duplicate safety machinery without improving recovery.

## Suggested next steps
- [ ] In Step 4, define the exact failure that post-merge auto-revert handles.
- [ ] Do not add a queue unless Step 5 metrics show a separate pre-merge ordering problem.

## Triage log

- 2026-05-02: verified actionable (architectural rule still load-bearing).
  Step 4 is Done — `.github/workflows/develop-post-merge.yml` is the
  declared safety net (revert PR labeled `incident:develop-red`, or
  `incident:develop-red-revert-conflict` issue on conflict). Step 5
  measurement is `Blocked`/in-progress (30-day window after Step 3a +
  Step 4 merge), and Step 6 queue gate is explicitly blocked on Step 5.
  The "do not add a queue unless Step 5 metrics show a pre-merge ordering
  problem" rule is currently being respected by the planning DAG rather
  than by enforcement; revisit after Step 5 publishes the go/no-go
  decision record.
- 2026-05-05: actionable (sweep). State unchanged: post-merge revert
  workflow shipped; Step 5 still `Blocked`. Architectural rule remains
  load-bearing by inertia, not enforcement. Carry forward.

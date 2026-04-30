---
id: 2026-04-30-143505-pool-lock-claim-only
date: 2026-04-30
status: actioned
finding_kind: assumption
review_context: "/code review of PR #73 (Step 2: worktree pool)"
related_paths:
  - Makefile
suggested_sweep: "If pool corruption ever occurs after concurrent ops, revisit the assumption and consider adding lock coverage to release/reset"
todo_id: null
---

# Pool file lock is claim-only; release/reset assume single-operator serial use

## Finding

The portable file lock at `.git/pool.lock` serializes only
`worktree-claim` calls against each other. It does NOT prevent
`worktree-claim` from racing with `worktree-release` or
`worktree-pool-reset` on the same slot. The implementation is correct
for a single-user workstation where humans/agents serialize their own
actions, but the constraint wasn't documented and the framework-gap
"lock scope is narrower than intended" was easy to miss.

## Why this matters

The original Step 2 spec specified atomic claim semantics. Atomic claim
satisfies the literal requirement, but it doesn't fully prevent
slot corruption — only one specific class. As the pool sees more
concurrent automation (cron sweeps, background reset triggers), the
narrow scope might leak.

## Suggested next steps

- [x] Document the concurrency assumption in a comment at the
      `worktree-claim` lock acquisition site (this PR).
- [x] Update the operator-facing docs to call out that pool ops
      assume single-workstation serial use.
- [ ] If automation is ever added that races claim/release/reset
      (e.g. cron-driven sweep-stale running while a user claims a
      slot), extend the lock to cover all three operations or
      introduce per-slot read-write locks.

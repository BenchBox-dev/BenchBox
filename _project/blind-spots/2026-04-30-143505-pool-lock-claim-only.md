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

- [x] Extract the lock-acquisition logic into a reusable helper
      (`scripts/_with_pool_lock.sh`) and acquire the same
      `.git/pool.lock` from every pool-mutating target:
      `worktree-claim`, `worktree-release`, `worktree-pool-reset`,
      and `worktree-pool-sweep-stale`. They now serialize against
      each other rather than only `worktree-claim` against itself.
      Read-only `worktree-pool-status` is intentionally lock-free.
- [x] Update the operator-facing comment at the lock acquisition
      site to describe the new (broader) coverage and what is
      explicitly NOT covered (status reads).
- [ ] Optional: if per-slot independence ever matters (e.g. operator
      wants to claim a free slot while sweep-stale resets a
      different slot), introduce per-slot read-write locks. Not
      worth the complexity for current single-workstation usage.

---
id: 2026-04-30-143503-no-pool-stale-sweep
date: 2026-04-30
status: actioned
finding_kind: framework-gap
review_context: "/code review of PR #73 (Step 2: worktree pool)"
related_paths:
  - Makefile
suggested_sweep: "Watch for sweep-stale being run frequently; if it is, claim's trap rollback may not be firing or releases are being skipped — investigate"
todo_id: null
---

# Pool exhaustion has no automatic recovery for stale slots

## Finding

If 10 sessions all crash leaving stale claims (PRs merged but worktrees
still on the branch), the 11th claim attempt fails with "No free pool
worktree available." The user has to manually run `worktree-pool-status`
and reset slots one at a time. The bookkeeping analog of `worktree-prune`
for the pool was missing.

## Why this matters

The pool's value is "set and forget" — agents claim slots without
ceremony. That contract breaks the moment recovery requires manual
intervention. Long-lived systems need a boring sweep that handles the
common cleanup case automatically.

## Suggested next steps

- [x] Add `make worktree-pool-sweep-stale` (this PR) that finds slots
      with MERGED PRs + clean trees and auto-releases them. Idempotent.
- [x] Update the pool-exhausted error message to point at sweep-stale
      and pool-reset as the recovery hierarchy.
- [ ] Optional: schedule sweep-stale via a developer's local cron or a
      pre-claim hook so it runs automatically before claim ever sees
      pool exhaustion.

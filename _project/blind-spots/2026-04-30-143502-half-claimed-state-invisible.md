---
id: 2026-04-30-143502-half-claimed-state-invisible
date: 2026-04-30
status: actioned
finding_kind: framework-gap
review_context: "/code review of PR #73 (Step 2: worktree pool)"
related_paths:
  - Makefile
suggested_sweep: "If pool-status reports venv=missing or venv=stale repeatedly, investigate whether claim's trap rollback is firing without leaving evidence"
todo_id: null
---

# Half-claimed-and-broken pool slots were undetectable

## Finding

If `worktree-claim` succeeded at `git checkout -b` but then `uv sync`
failed (network blip, corrupted uv cache, etc.), the worktree was left
on the feature branch with a missing or broken `.venv`.
`worktree-pool-status` reported it as `claimed` with no indication of
brokenness. The next session that claimed it would discover the broken
venv only by trying to use it.

## Why this matters

Lifecycle state machines for long-lived infrastructure need explicit
representation of partial-failure intermediates, not just the success
path. The five-axis review caught the missing rollback (Required #2)
but missed the broader pattern: there was no observability for slots
that were "claimed but broken" even before the rollback gap.

## Suggested next steps

- [x] Add a `venv` health column (`ok` / `stale` / `missing`) to
      `make worktree-pool-status` (this PR).
- [x] Add a trap-on-failure rollback to `worktree-claim-locked` so
      partial failures return the slot to detached origin/develop
      (this PR).
- [ ] Optional: consider a `claim_started_at` marker file that
      `worktree-claim` writes before mutation and removes on success;
      pool-status would surface lingering markers as `claim-aborted`
      state for slots that died without trap firing (e.g. SIGKILL).

---
id: 2026-04-30-143500-pool-disk-accounting
date: 2026-04-30
status: actioned
finding_kind: missed-axis
review_context: "/code review of PR #73 (Step 2: worktree pool)"
related_paths:
  - Makefile
suggested_sweep: "Watch for disk-pressure failures during busy multi-claim sessions; consider a soft cap or pre-claim free-space check if it becomes an issue"
todo_id: null
---

# Pool worktrees consume ~30 GB of disk silently

## Finding

The five-axis review of PR #73 caught code-quality issues but missed a
physical-state dimension: 10 retained worktrees × ~2 GB each (repo + `.venv` +
caches) = ~20 GB minimum, with `.benchbox/` scratch state and pytest caches
pushing toward 30 GB during active use. Nothing in the original PR accounted
for monitoring or capping disk usage. A workstation that runs out of disk
will see claims fail in confusing ways (uv sync mid-claim → trap rollback,
but the underlying filesystem error is the actual cause).

## Why this matters

Long-lived pool infrastructure has a slow-leak failure mode that
code-quality reviews don't catch: the pool itself is fine, but the
host's free-space budget shrinks over time as pytest caches, build
artifacts, and per-worktree venvs accumulate. Without surfacing the
size, the operator only learns about it when something breaks.

## Suggested next steps

- [x] Add `size` column to `make worktree-pool-status` (this PR).
- [ ] Optional: pre-claim free-space check that refuses with a clear
      "host has < 2 GB free; clean caches before claiming" message
      rather than letting `uv sync` fail mid-claim.
- [ ] Optional: a `make worktree-pool-disk-clean` that removes
      pytest/coverage caches in pool-NN slots without touching `.venv`
      or git state.

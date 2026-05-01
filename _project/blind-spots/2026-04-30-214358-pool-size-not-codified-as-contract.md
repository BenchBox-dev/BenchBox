---
id: 2026-04-30-214358-pool-size-not-codified-as-contract
date: 2026-04-30
status: open
finding_kind: missed-axis
review_context: "/docs review of dev-loop worktree pool / chore/worktree-pool-docs-review / PR #84"
related_paths:
  - Makefile
  - docs/operations/dev-loop-worktree-pool.md
  - _project/DONE/main/planning/dev-loop-step-2-worktree-pool.yaml
suggested_sweep: "consider adding `make worktree-pool-check` that asserts count == POOL_SIZE, every slot is in a known-good state (no `aborted`, no `missing`, no orphaned `pool.lock`); decide whether to gate it on release or leave purely advisory"
todo_id: null
---

# Pool size of 10 is convention, not a contract

## Finding

`POOL_SIZE = 10` lives only as a Makefile default and a documented
expectation in CLAUDE.md / AGENTS.md / the new operations guide. There
is no test, lint, or release-gate target that fails if a slot goes
missing, an extra slot appears, or `POOL_SIZE` is changed away from 10
without a coordinated update of the docs. `worktree-pool-status` would
*surface* a `missing` slot but does not exit non-zero on it — so a
silent drift can persist indefinitely between sessions.

The dev-loop-step-2 spec's `must_preserve` invariants (idempotent init,
atomic claim, retained `.venv/`) are guarded by behavior, but the
**count and presence of slots** is not.

## Why this matters

The pool model only delivers its value (predictable session start, no
churn, retained venvs) when all 10 slots are present and in a known
state. Silent drift — a slot manually removed, a stale `pool.lock`, a
half-claimed `.benchbox/claim_in_progress` marker on a "free" slot —
degrades the system gracefully and invisibly: claims still succeed
against fewer slots, and the symptom only surfaces under contention.

Making the pool a checked invariant (rather than convention + visual
inspection of `pool-status`) would let the system fail fast when drift
happens, instead of failing slow under load.

## Suggested next steps
- [ ] Decide whether the pool count is worth codifying as a contract,
      or whether `pool-status` visibility is sufficient.
- [ ] If yes: add `make worktree-pool-check` — exit non-zero on any of
      `count != POOL_SIZE`, slot in `aborted` / `missing`, orphaned
      `pool.lock` older than the lock timeout. Use it as a pre-release
      sanity check or a periodic local cron, not a PR-CI blocker.
- [ ] If no: write a one-line note in the operations doc that the count
      is "by convention, run `pool-status` to inspect" — so future
      readers don't assume it's enforced.

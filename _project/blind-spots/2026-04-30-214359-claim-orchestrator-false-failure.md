---
id: 2026-04-30-214359-claim-orchestrator-false-failure
date: 2026-04-30
status: open
finding_kind: bug-class
review_context: "/docs review of dev-loop worktree pool / chore/worktree-pool-docs-review — observed during make worktree-claim BRANCH=chore/worktree-pool-docs-review"
related_paths:
  - Makefile
suggested_sweep: "trace `worktree-claim-attempt` exit-status flow; the first attempt printed `WORKTREE_PATH=...` (success indicator) yet `worktree-claim-locked` fell through to the auto-sweep retry path"
todo_id: null
---

# `worktree-claim` orchestrator triggers retry path after a successful first attempt

## Finding

A successful first-pass `worktree-claim` (which printed
`WORKTREE_PATH=/Users/joe/Developer/BenchBox.pool-03` and switched the
slot to the requested feature branch) was followed by:

```
No free pool worktree on first pass — auto-sweeping stale slots...
skip pool-01: dirty (branch=fix/results-explorer-qa-pass2)
skip pool-02: dirty (branch=fix/dev-loop-classifier-runbook)
skip pool-03: PR not merged (state=none)
Swept 0 pool slot(s).
fatal: a branch named 'chore/worktree-pool-docs-review' already exists
claim of pool-04 failed; slot returned to detached origin/develop
make[2]: *** [worktree-claim-attempt] Error 128
```

The orchestrator (`worktree-claim-locked`) interpreted the first
`worktree-claim-attempt` as having failed, ran `worktree-pool-sweep-stale`,
then attempted a second claim — which collided with the branch the first
(actually-successful) attempt created. Final exit code from the make
target was non-zero even though the slot is correctly claimed. The pool
ended in the right state (pool-03 on the branch, clean tree), but:

1. The user (and any wrapping automation) sees a non-zero exit and
   error noise after a successful claim.
2. The second attempt's "branch already exists" rollback (`claim of
   pool-04 failed; slot returned to detached origin/develop`) is
   wasted IO.
3. CI scripts or shell pipelines that key off make's exit code will
   treat the success as a failure.

## Why this matters

`worktree-claim` is the canonical entry point for every agent and
maintainer session start. A flaky exit code on the most-used target
erodes trust in the auto-sweep retry behavior — the next time it
*does* legitimately retry, the operator may assume the prior run
"already worked" and skip investigation.

The bug class is "orchestrator misreads a child make target's success
signal." The same pattern likely exists in any other Make target that
dispatches a sub-make and inspects only the exit code (e.g.
`worktree-pool-sweep-stale-locked`).

## Suggested next steps
- [ ] Reproduce: run `make worktree-claim BRANCH=<new>` against a pool
      with at least one free slot; capture the first
      `worktree-claim-attempt`'s exit status explicitly.
- [ ] Compare: is `worktree-claim-attempt` returning non-zero on
      success because of a trailing `uv sync` or `pre-commit install`
      step that exited with a warning? Or is the silent
      `$(MAKE) -s` swallowing stdout but propagating an inner error?
- [ ] Fix the exit-status path so the first attempt's success
      short-circuits the orchestrator cleanly. The user-visible
      contract is "WORKTREE_PATH=… printed → claim succeeded → exit 0".
- [ ] Add a regression test that asserts `make worktree-claim BRANCH=…`
      exits 0 on a fresh free pool.

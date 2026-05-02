---
id: 2026-04-30-214359-claim-orchestrator-false-failure
date: 2026-04-30
status: actioned
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

## Triage log

- 2026-05-02: reproduced during this very sweep. `make -s
  worktree-claim BRANCH=chore/blind-spot-sweep` printed
  `WORKTREE_PATH=/Users/joe/Developer/BenchBox.pool-10`, then ran the
  auto-sweep retry path ("No free pool worktree on first pass —
  auto-sweeping stale slots..."), `Swept 0 pool slot(s)`, and exited
  the make target with `Error 1` / `Error 2` (`worktree-claim-attempt`
  → `worktree-claim-locked` → `worktree-claim`). Final state was
  correct: pool-10 cleanly claimed on the requested branch, working
  tree clean. The bug class — orchestrator misreads child make
  target's success — is still live. Verified actionable.
- 2026-05-02: actioned — Sweep 2026-05-02: fixed by chaining worktree-claim-locked recipe into a single shell with line continuations (the @-prefixed if/exit was running in a per-line subshell, so 'exit 0' exited only that subshell while make walked to the auto-sweep retry path). Added regression test tests/integration/worktree/test_worktree_claim_orchestrator_exit.py — verified it fails on the unfixed recipe and passes after the fix.

---
id: 2026-04-30-114721-global-test-lock-cpu-protection
date: 2026-04-30
status: actionable
finding_kind: assumption
review_context: "L2 merge-loop audit / dev-loop simplification planning (2026-04-30)"
related_paths:
  - tests/conftest.py
  - tests/README.md
suggested_sweep: "Revisit only if BENCHBOX_TEST_LOCK_DIR usage proves per-worktree locks are safe under real workstation load."
todo_id: null
---

# Global test lock protects workstation CPU

## Finding
Test-lock localization is not a pure win at scale; the global lock has a real CPU-protection job (10 worktrees × xdist auto)

## Why this matters
Removing the global lock by default can shift pain from blocked pushes to CPU saturation and timing flakes when several worktrees test concurrently.

## Suggested next steps
- [ ] Track whether developers actually need `BENCHBOX_TEST_LOCK_DIR` outside isolated debug sessions.
- [ ] Keep the default lock global unless measurement shows concurrent xdist runs are safe.

## Triage log

- 2026-05-02: verified actionable (advice still load-bearing). Default
  lock path remains `$HOME/.benchbox/test.lock`
  (`tests/conftest.py:_get_test_lock_path`, `Makefile:test-unlock`). The
  override knob `BENCHBOX_TEST_LOCK_DIR` is still opt-in and now
  expanduser-correct on both sides (codex w2 / commit fe393e748). No
  measurement of concurrent-xdist safety has been collected yet, so the
  rule "keep default global" is preserved by inertia rather than
  evidence — the survey/measurement work item below is still owed.
  Re-evaluate when dev-loop-step-5-measurement-window completes.
- 2026-05-05: actionable (sweep). `tests/conftest.py:_get_test_lock_path`
  still defaults to `$HOME/.benchbox/test.lock` and `BENCHBOX_TEST_LOCK_DIR`
  remains opt-in. `dev-loop-step-5-measurement-window` is still `Blocked`,
  so no concurrent-xdist measurement has been collected. Carry forward the
  two next-steps; do not flip the default until measurement lands.
- 2026-05-06: actionable — 2026-05-06 sweep: tests/conftest.py:_get_test_lock_path still defaults to $HOME/.benchbox/test.lock; dev-loop-step-5-measurement-window still Blocked, no concurrent-xdist measurement collected — keep default global lock until Step 5 lands

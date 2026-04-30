---
id: 2026-04-30-114721-global-test-lock-cpu-protection
date: 2026-04-30
status: open
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

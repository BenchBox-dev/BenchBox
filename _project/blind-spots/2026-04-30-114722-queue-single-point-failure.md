---
id: 2026-04-30-114722-queue-single-point-failure
date: 2026-04-30
status: open
finding_kind: scope-creep
review_context: "L2 merge-loop audit / dev-loop simplification planning (2026-04-30)"
related_paths:
  - Makefile
  - .github/workflows/auto-merge-on-open.yml
suggested_sweep: "Before any queue TODO is promoted, identify queue steward failure modes and fallback commands."
todo_id: null
---

# Queue steward can become a single point of failure

## Finding
A queue creates a single point of failure with no analog in current setup

## Why this matters
Replacing decentralized auto-merge with a queue can make one local process or workflow responsible for all progress.

## Suggested next steps
- [ ] Require an explicit failure-mode analysis before adding a steward queue.
- [ ] Prefer native GitHub features if they become available and meet the repository's ownership constraints.

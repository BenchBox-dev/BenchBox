---
id: 2026-04-30-114722-queue-single-point-failure
date: 2026-04-30
status: actionable
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

## Triage log

- 2026-05-02: verified actionable (advice still load-bearing). The
  decentralized auto-merge model is live (`auto-merge-on-open.yml` +
  `develop-post-merge.yml` are both shipped). The queue itself is
  intentionally NOT built — `dev-loop-step-6-queue-decision-gate.yaml`
  is `Blocked` on `dev-loop-step-5-measurement-window`, with explicit
  Path A (native MQ) vs Path B (steward) handoff. If Step 5 returns
  BUILD QUEUE, this finding's failure-mode-analysis requirement is
  the gate that must clear before any steward implementation TODO
  unblocks.
- 2026-05-05: actionable (sweep). State unchanged: Step 5/6 still
  `Blocked`; no failure-mode-analysis artifact authored. Carry forward
  the next-steps. Do not promote to a steward TODO until Step 5 returns
  BUILD QUEUE.
- 2026-05-06: actionable — 2026-05-06 sweep: decentralized auto-merge live (auto-merge-on-open.yml + develop-post-merge.yml present); dev-loop-step-6-queue-decision-gate still Blocked on Step 5 — failure-mode-analysis remains the gate before any steward TODO
- 2026-05-08: actionable — sweep: auto-merge-on-open.yml + develop-post-merge.yml still shipped; dev-loop-step-6-queue-decision-gate still Blocked (waiting on Step 5 measurement window through ~2026-05-30) — failure-mode-analysis pre-condition stands

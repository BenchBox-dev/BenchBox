---
id: 2026-04-30-114723-queue-dwell-contract
date: 2026-04-30
status: merged-to-todo
finding_kind: assumption
review_context: "L2 merge-loop audit / dev-loop simplification planning (2026-04-30)"
related_paths:
  - AGENTS.md
  - CLAUDE.md
  - Makefile
suggested_sweep: "Measure branch dwell time before considering a queue; update agent docs if expected dwell changes."
todo_id: dev-loop-queue-acceptance-criteria-from-blind-spots
---

# Queue dwell time changes the agent contract

## Finding
Dwell time silently changes the agent contract (5 min today vs hours under a queue)

## Why this matters
Agents can walk away after auto-merge only because the current dwell time is short; a longer queue changes expectations for monitoring, refreshes, and handoff.

## Suggested next steps
- [ ] Treat dwell-time targets as part of any queue acceptance criteria.
- [ ] Update agent handoff guidance if queue dwell becomes materially longer than current CI time.

## Triage log

- 2026-05-02: verified actionable. Dwell time on `develop` PRs is
  still short by design (auto-merge + lightweight `pr.yml` gate;
  `make dev-loop-metrics` measures PR-to-merge P50/P95). The agent
  contract in CLAUDE.md ("walk away — don't poll") still holds.
  This finding becomes load-bearing only when Step 5 measurement
  surfaces dwell-time symptoms that justify Step 6 (queue); at that
  point the dwell-target acceptance criteria below must be folded
  into the queue spec before any implementation TODO ships.
- 2026-05-05: actionable (sweep). `make dev-loop-metrics` exists; Step
  5 still `Blocked` (no published P50/P95 dwell numbers yet). Agent
  walk-away contract in CLAUDE.md still holds. Carry forward the
  next-steps; revisit when Step 5 publishes measurements.
- 2026-05-06: actionable — 2026-05-06 sweep: make dev-loop-metrics still present; Step 5 Blocked, no published P50/P95 dwell numbers — agent walk-away contract in CLAUDE.md still load-bearing
- 2026-05-08: actionable — sweep: `make dev-loop-metrics` still defined (Makefile:959); Step 5 still calendar-blocked through ~2026-05-30; CLAUDE.md walk-away contract (commit→push→PR auth, no polling) intact — carry forward dwell-target acceptance criteria
- 2026-05-11: promoted to TODO `dev-loop-queue-acceptance-criteria-from-blind-spots`

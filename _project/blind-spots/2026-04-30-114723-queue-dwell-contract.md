---
id: 2026-04-30-114723-queue-dwell-contract
date: 2026-04-30
status: open
finding_kind: assumption
review_context: "L2 merge-loop audit / dev-loop simplification planning (2026-04-30)"
related_paths:
  - AGENTS.md
  - CLAUDE.md
  - Makefile
suggested_sweep: "Measure branch dwell time before considering a queue; update agent docs if expected dwell changes."
todo_id: null
---

# Queue dwell time changes the agent contract

## Finding
Dwell time silently changes the agent contract (5 min today vs hours under a queue)

## Why this matters
Agents can walk away after auto-merge only because the current dwell time is short; a longer queue changes expectations for monitoring, refreshes, and handoff.

## Suggested next steps
- [ ] Treat dwell-time targets as part of any queue acceptance criteria.
- [ ] Update agent handoff guidance if queue dwell becomes materially longer than current CI time.

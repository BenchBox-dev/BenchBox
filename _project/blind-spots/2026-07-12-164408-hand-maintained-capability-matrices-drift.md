---
id: 2026-07-12-164408-hand-maintained-capability-matrices-drift
date: 2026-07-12
status: open
finding_kind: bug-class
review_context: "tuning-system deep review / claude/tuning-system-review-7mzapy"
related_paths:
  - benchbox/core/tuning/interface.py
  - benchbox/core/tuning/ddl_generator.py
  - benchbox/core/tuning/platform_capabilities.py
suggested_sweep: "find other N-way hand-maintained platform matrices (format capabilities, external-table support, dialect features) and check for cross-consistency tests"
todo_id: null
---

# Parallel hand-maintained capability matrices drift with no consistency test

## Finding
"What tuning does platform X support" is answered independently by six artifacts: the hardcoded
compat map in `interface.py`, the `get_ddl_generator` registry, `platform_capabilities.py`
mappings, per-adapter mixin implementations, the `benchbox tuning platforms` CLI prose tables,
and the `examples/tunings/` + coverage.yaml matrix. They disagree today (e.g. generators exist
for platforms the registry doesn't map; the compat map rejects platforms that ship tuning
mixins) and no test cross-checks any pair.

## Why this matters
When capability knowledge is duplicated per consumer, each new platform or tuning type must be
added in every location, and the failure mode of missing one is silent (NoOp fallback, empty
set, UNSUPPORTED default) rather than loud. The bug class recurs anywhere the repo keeps
per-platform feature matrices by hand.

## Suggested next steps
- [ ] Add a cross-consistency unit test over the existing sources as a stopgap (fails on new drift).
- [ ] Evaluate a single capability registry that the other five artifacts derive from.

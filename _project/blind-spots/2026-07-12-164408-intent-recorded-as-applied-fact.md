---
id: 2026-07-12-164408-intent-recorded-as-applied-fact
date: 2026-07-12
status: open
finding_kind: bug-class
review_context: "tuning-system deep review / claude/tuning-system-review-7mzapy"
related_paths:
  - benchbox/platforms/base/adapter.py
  - benchbox/platforms/base/result_capture.py
  - benchbox/core/results/schema.py
suggested_sweep: "for each bundle field, ask: is this derived from what we asked the engine to do, or from observing what it did? List the intent-derived ones."
todo_id: null
---

# Result-bundle fields record intent and label it as applied fact

## Finding
`tunings_applied` is `effective_tuning_config.to_dict()` — the requested configuration — and
`tuning_validation_status = "APPLIED"` is gated on a metadata-table write succeeding, not on any
observation of the database. The base `apply_unified_tuning` is a silent no-op, so a platform can
skip the entire tuning while the bundle asserts it was applied. The same intent-as-fact pattern
plausibly affects other self-reported bundle fields (session settings applied in
`configure_for_benchmark` are recorded nowhere; sorted-ingestion and constraint enforcement are
reported from config, not introspection).

## Why this matters
Published bundles are compared by third parties; every field that is actually "what we intended"
but reads as "what happened" silently corrupts cross-submission comparison — the same failure
class as a broken comparator, but invisible to tests that only check serialization round-trips.

## Suggested next steps
- [ ] Inventory bundle fields by provenance (intent vs observation) and mark intent-only ones in the schema docs.
- [ ] Design an applied-statement ledger in the adapter execution path so capture can record observations.

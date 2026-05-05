---
id: 2026-05-05-080138-uat-end-to-end-semantic-test-gap
date: 2026-05-05
status: open
finding_kind: missed-axis
review_context: "/code review of PR #205 (UAT framework W2-W11)"
related_paths:
  - tests/uat/test_replay_2026_05_02.py
  - tests/uat/orchestrator.py
  - tests/uat/phases/execute.py
suggested_sweep: "audit other multi-phase orchestrators in the repo (release pipeline, CI metrics rollup) for the same gap: unit tests of math + dry-run E2E, but no E2E with non-trivial fake state."
todo_id: null
---

# Unit tests + dry-run E2E ≠ semantic E2E

## Finding
The five-axis review framework checks each module's correctness in
isolation but does not catch missing integration-style coverage. PR #205
has 96 fast tests covering ladder math, parse_rollup math, regex
extraction, frozen-config hashing, etc. — and a slow-marked replay test
that runs the full sweep, but only with `dry_run=True` (which short-
circuits every phase to exit 0). There is no test that walks a non-
trivial fake matrix end-to-end — multiple platforms and benchmarks,
ladder pruning, cleanup graph traversal, JSONL emission, report
round-trip — and asserts the cleanup pruned the right directories at
the right times.

## Why this matters
Multi-phase orchestrators have emergent behavior: each phase passes
state to the next via files (cells.jsonl → report TSV) and shared
filesystem state (databases/, logs/). A test that only exercises one
phase at a time misses contract drift between phases. The replay-as-
dry-run pattern looks like coverage but is actually closer to a
"does it import?" check, because `dry_run` is a kill switch that
bypasses the very logic the test is named after.

## Suggested next steps
- [ ] Add a `run_execute → orchestrator → report` integration test
      using a stubbed runner that drives ladder pruning and validator
      results, with assertions on cells.jsonl content, TSV column
      shape AND row contents, and prune calls observed via a fake
      filesystem.
- [ ] Audit other multi-phase orchestrators (release pipeline, CI
      metrics rollup, ralph-loop) for the same shape: unit tests of
      individual stages plus a dry-run E2E that doesn't actually
      exercise the wiring.

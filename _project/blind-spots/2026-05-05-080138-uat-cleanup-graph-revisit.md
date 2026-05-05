---
id: 2026-05-05-080138-uat-cleanup-graph-revisit
date: 2026-05-05
status: open
finding_kind: bug-class
review_context: "/code review of PR #205 (UAT framework W2-W11)"
related_paths:
  - tests/uat/phases/execute.py
  - tests/uat/cleanup.py
suggested_sweep: "search for prune-once-only patterns in cleanup graphs across the repo (e.g. results-explorer datagen retention, snapshot-bundle cleanup) — reuse-aware DAGs that don't re-check after consumer completion are likely a recurring class."
todo_id: null
---

# Reuse-aware cleanup that never re-checks the source

## Finding
The cleanup loop in `run_execute` runs once per `(platform, benchmark)` pair
and only attempts to prune the directory matching the benchmark that JUST
completed. When `(p1, tpch)` finishes, `can_prune("tpch", ...)` correctly
blocks because read_primitives (a tpch consumer) is still pending. Later,
when `(p1, read_primitives)` completes, the code prunes
`databases/p1/read_primitives/<scale>` — NOT `databases/p1/tpch/<scale>`.
The tpch loaded DB is therefore never pruned during the sweep, even
though the safe-to-prune condition becomes true the moment the last
consumer completes. The five-axis frame caught this because I was
already tracing the cleanup ordering — but the underlying pattern (a
reuse-graph traversal that defers a prune attempt and never re-tries)
is general.

## Why this matters
Reuse-aware cleanup is a recurring shape in benchmarking infrastructure:
preserve a costly artefact while it still has consumers, prune at safe
boundaries. The "safe boundary" is "all consumers done", which is a
property that becomes true *over time* — but a cleanup loop indexed on
"the thing I just ran" only checks pruneability at the wrong moment.
The bug class is "single-pass cleanup over a DAG, indexed on the just-
completed node, with no retry when downstream nodes finish".

## Suggested next steps
- [ ] Restructure the cleanup loop in execute.py to either (a) prune
      sources at end-of-platform after all benchmarks for the platform
      finish, or (b) on each consumer completion, re-check pruneability
      of every upstream source for that (platform, scale).
- [ ] Add an integration-style fast test that walks a small fake matrix
      with `tpch → read_primitives` and asserts the tpch DB directory is
      gone by sweep end.
- [ ] Sweep the codebase for similar shapes: results-explorer datagen
      retention, snapshot bundle cleanup, anything with a SOURCE_REUSE_GRAPH
      analogue.

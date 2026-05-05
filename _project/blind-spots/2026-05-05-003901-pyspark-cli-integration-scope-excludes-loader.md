---
id: 2026-05-05-003901-pyspark-cli-integration-scope-excludes-loader
date: 2026-05-05
status: open
finding_kind: scope-creep
review_context: "/todo implement write-primitives-sketch-pyspark-cli-integration W1 (catalog entries for AGGREGATE_PERSIST/MERGE)"
related_paths:
  - _project/TODO/main/planning/write-primitives-sketch-pyspark-cli-integration.yaml
  - benchbox/core/write_primitives/catalog/loader.py
  - benchbox/core/write_primitives/catalog/operations.yaml
  - benchbox/core/write_primitives/benchmark.py
suggested_sweep: "Audit `scope_limit.only_modify` against the implementation shape every TODO requires before committing it. Catch contradiction earlier, like the resolved 2026-05-04 mismatch did."
todo_id: write-primitives-sketch-pyspark-cli-integration
---

# pyspark-cli-integration scope_limit excludes loader.py, but new op shape needs loader changes

## Finding

The pyspark-cli-integration TODO's `scope_limit.only_modify` is:

  - benchbox/core/write_primitives/catalog/operations.yaml
  - benchbox/core/write_primitives/benchmark.py
  - tests/integration/core/write_primitives/
  - docs/benchmarks/write-primitives-sketch-functions.md
  - _project/blind-spots/2026-05-04-011321-pyspark-sketch-todo-scope-vs-verification-mismatch.md
  - CHANGELOG.md

W1 wants two new catalog entries with the AGGREGATE_PERSIST/MERGE op
shape. The catalog loader (`loader.py`) requires every op to have a
non-empty `write_sql` string, has no concept of a `dispatch:
aggregate_state` marker, and silently drops unknown yaml fields. So
the new shape can be expressed in `operations.yaml` only one of two
ways:

1. **Extend `loader.py`** to add an optional `aggregate_state` block
   and relax the `write_sql` requirement when that block is present.
   This mirrors how `architecture-fixes` shipped
   `validation_query.platform_overrides`. **But `loader.py` is
   neither in `only_modify` nor in `do_not_modify` — strict reading
   of `only_modify` means it cannot be touched.**

2. **Sentinel-based hack**: set `write_sql:
   "__AGGREGATE_STATE__"` (or equivalent placeholder) plus extra
   yaml fields the loader ignores; have `benchmark.py` re-parse the
   yaml file directly to extract the aggregate-state config and
   detect the dispatch case via the sentinel. This fits scope_limit
   but produces a maintenance hazard — the catalog truth is now
   half in `WriteOperation` and half in raw yaml; future readers
   have to know about the sentinel.

Both options are bad. Option 1 violates scope_limit. Option 2
violates the architecture-fixes pattern of first-class loader
support and contradicts the TODO's own anti-pattern note "DO NOT
make DataFrame sketch support a … special case buried in query
code".

## Why this matters

This is exactly the same class of contradiction that the
2026-05-04 blind-spot
(`pyspark-sketch-todo-scope-vs-verification-mismatch`) flagged on
the predecessor TODO — and the cli-integration TODO was supposed
to resolve it. The resolution narrowed the verification command
into scope but did not widen the file allowlist enough to make the
implementation feasible. The same TODO-authoring failure mode
recurred one revision later.

## Suggested next steps

- [ ] Decide intent: expand `scope_limit.only_modify` on
  `write-primitives-sketch-pyspark-cli-integration` to include
  `benchbox/core/write_primitives/catalog/loader.py` plus
  `tests/unit/core/write_primitives/test_catalog_loader.py`, then
  resume. Recommended path because it matches the
  architecture-fixes precedent.
- [ ] Or: redesign the catalog op shape to fit the existing loader
  by reusing `category` + naming-convention dispatch (no new
  fields). Document the convention and accept the discoverability
  cost.
- [ ] Update the TODO file to record whichever decision is made.
  Either change is small.
- [ ] After unblocking, the rest of W1–W5 is large but tractable:
  catalog entries (W1), platform-aware dispatch fork in
  `_execute_dataframe_sql_parity_workload` (W2), real Spark 3.5+
  integration test (W3 — PySpark 4.1.1 is installed locally),
  doc + blind-spot + CHANGELOG (W4–W5).

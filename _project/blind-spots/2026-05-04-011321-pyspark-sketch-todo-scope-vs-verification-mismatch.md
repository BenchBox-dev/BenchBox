---
id: 2026-05-04-011321-pyspark-sketch-todo-scope-vs-verification-mismatch
date: 2026-05-04
status: open
finding_kind: scope-creep
review_context: "/code review w2 prep / write-primitives-sketch-pyspark-dataframe-surface"
related_paths:
  - _project/TODO/main/planning/write-primitives-sketch-pyspark-dataframe-surface.yaml
  - benchbox/core/write_primitives/benchmark.py
  - benchbox/core/write_primitives/catalog/operations.yaml
  - benchbox/core/write_primitives/dataframe_operations.py
suggested_sweep: "decide whether the pyspark-dataframe-surface TODO is a 'primitives layer only' deliverable (current scope_limit) or includes the benchbox CLI wire-up (current verification commands); update one or the other so they agree"
todo_id: write-primitives-sketch-pyspark-dataframe-surface
---

# pyspark-dataframe-surface TODO: scope_limit vs verification command contradict

## Finding
The TODO's `scope_limit.only_modify` lists exactly four paths:
`benchbox/core/write_primitives/dataframe_operations.py`,
`docs/benchmarks/write-primitives-sketch-functions.md`,
`tests/unit/core/write_primitives/`, and `CHANGELOG.md`. Its
`do_not_modify` explicitly forbids
`benchbox/core/write_primitives/catalog/operations.yaml` and
`benchbox/core/write_primitives/benchmark.py`.

But the verification block expects:

    uv run -- benchbox run --platform pyspark --benchmark write_primitives \
      --scale 0.01 --queries sketch_df_hll_persist_merge

Reading the current code:

- `_execute_dataframe_sql_parity_workload` (benchmark.py) routes every
  DataFrame-mode op through embedded DuckDB SQL — it never invokes the
  AGGREGATE_PERSIST/MERGE dispatch that architecture-fixes shipped.
- The catalog has no entry for `sketch_df_hll_persist_merge`.
  `--queries sketch_df_hll_persist_merge` would fail at op lookup.
- Even with a catalog entry, the workload runner has no engine-aware
  dispatch fork that would route to `manager.execute_aggregate_persist`.

So the verification command can't pass without changes to both
operations.yaml and benchmark.py — both forbidden by scope_limit.

## Why this matters
The TODO promises an `benchbox run`-level deliverable but only allows
the dispatch primitives to be wired (in `dataframe_operations.py`). The
review framework would mark the work "done" against scope_limit while
the verification command silently fails — a half-shipped feature that
nobody can actually invoke.

This is a TODO-authoring failure mode worth recording: when a TODO's
scope and verification disagree, the implementer is forced to pick one
to honor. Picking scope means the verification is wrong; picking
verification means the scope was too narrow and a follow-up has to land
the integration. Either choice surfaces something the planning step
should have caught.

## Suggested next steps
- [ ] Decide intent: is pyspark-dataframe-surface a "primitives layer
      only" deliverable (current scope) or a full CLI-runnable feature
      (current verification)?
- [ ] If primitives-layer: update verification to use direct
      `manager.execute_aggregate_persist(...)` calls in tests, not
      `benchbox run --queries ...`.
- [ ] If full feature: add operations.yaml + benchmark.py to scope_limit
      and budget for the engine-aware dispatch fork in the workload
      runner.
- [ ] Either way, file a follow-up TODO for the missing piece (CLI
      wire-up) so the gap is tracked.

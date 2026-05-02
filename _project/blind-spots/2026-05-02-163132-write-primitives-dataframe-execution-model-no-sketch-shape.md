---
id: 2026-05-02-163132-write-primitives-dataframe-execution-model-no-sketch-shape
date: 2026-05-02
status: merged-to-todo
finding_kind: framework-gap
review_context: "TODO write-primitives-sketch-pyspark-dataframe-surface w1 research spike"
related_paths:
  - benchbox/core/write_primitives/dataframe_operations.py
  - benchbox/core/write_primitives/catalog/loader.py
  - benchbox/core/dataframe/maintenance_interface.py
suggested_sweep: "Audit whether any future DataFrame-side benchmark op (sketch persistence, materialized view refresh, window-state checkpoint, etc.) fits the operation-typed CRUD model. If not, the next aggregate-style op surfaces the same gap. Likely sites for a structural extension: WriteOperationType enum, DataFrameWriteOperationsManager dispatch, catalog WriteOperation schema, validation contracts, cleanup handling, and partition-aware durable state paths."
todo_id: write-primitives-architecture-fixes
---

# write_primitives DataFrame Execution Model Has No Sketch-Shaped Op Type

## Finding

`benchbox/core/write_primitives/dataframe_operations.py` is structured
around a closed set of row-level CRUD operation types:

- `WriteOperationType.INSERT` — append rows
- `WriteOperationType.BULK_LOAD` — file-format read+write
- `WriteOperationType.UPDATE` — modify rows by condition
- `WriteOperationType.DELETE` — remove rows by condition
- `WriteOperationType.MERGE` — upsert
- `WriteOperationType.TRANSACTION` — ACID wrapper

`DataFrameWriteOperationsManager` exposes one `execute_<op>` method
per enum value. All ops route through `_maintenance_ops`, which is
itself the row-level maintenance interface from
`benchbox/core/dataframe/maintenance_interface.py`. There is no
extension point for ops that produce or consume aggregate-state
columns (sketches, accumulators, materialised summaries, etc.) — the
manager's vocabulary is row CRUD, not compute.

Sketch persistence is structurally different: it builds a per-group
aggregate state column (HLL bytes, KLL bytes, top-K accumulator),
persists those bytes to a durable store, then later merges those
states across groups and extracts a final scalar. None of `INSERT` /
`BULK_LOAD` / `UPDATE` / `DELETE` / `MERGE` describes what's
happening — the row identities aren't changing, the column type is
binary aggregate state, and the meaningful unit of measurement is
the build+merge cycle latency, not the row count.

## Why this matters

TODO `write-primitives-sketch-pyspark-dataframe-surface` w1 is the
research spike that surfaced this gap. The TODO is hard-blocked
because every plausible implementation path requires extending the
DataFrame execution model — and the TODO's anti-patterns and
hard-block protocol explicitly forbid silently doing so:

> "DO NOT extend BenchBox's DataFrame execution model beyond what
> dataframe_operations.py already supports — because that's a
> structural change with broader scope implications — surface the
> need to the user before extending."

The same gap applies to the sister TODO
`write-primitives-sketch-clickhouse-and-storage-metrics` if it ever
gets a DataFrame-mode component, and to any future TODO that wants
to measure DataFrame-side aggregate-state persistence (materialised
views, summary tables, ML feature stores, cube refresh).

## Suggested next steps

- [x] Promote to fix-class TODO `write-primitives-architecture-fixes`.
- [ ] Design and implement an aggregate-state op shape that fits the existing
      `WriteOperationType` / `DataFrameWriteOperationsManager` /
      catalog-entry contract. Likely shape:
      `WriteOperationType.AGGREGATE_PERSIST` and
      `WriteOperationType.AGGREGATE_MERGE`, each with a build-fn
      / merge-fn / extract-fn registration inspired by read_primitives'
      `expression_impl` / `pandas_impl`. Do not copy that pattern
      blindly: write_primitives also needs validation contracts, cleanup
      phases, partition awareness, and durable intermediate-state paths.
- [x] Add the dependency edge from
      `write-primitives-sketch-pyspark-dataframe-surface` to the fix TODO.
- [ ] Once the aggregate-op shape lands, unblock TODO
      `write-primitives-sketch-pyspark-dataframe-surface`.
- [ ] Consider whether the SQL sketch ops (already merged in PR
      #112) should also re-target the aggregate-op shape rather
      than the current `write_sql` + `validation_query` shape — they
      have the same conceptual structure (build, merge, extract) and
      the current shape papers over that.
- [ ] Cross-link to the validation_query no-per-platform-override
      blind-spot (2026-05-02-155448) — both are write_primitives
      architecture gaps that surfaced in the same sketch-TODO batch
      and probably want the same architectural pass.

## Why it didn't get caught earlier

The DataFrame write surface shipped to handle row-level maintenance
operations on tabular data — that's its real-world use case. Sketch
persistence is a recent benchmark category (PR #112) and was
SQL-only at landing. The DataFrame execution model and the SQL
catalog evolved in separate PRs without anyone asking "could the
DataFrame model handle the SQL catalog's full op set?". The answer
turns out to be "no for sketches" — surfaced by the first TODO that
tried to bridge the two.

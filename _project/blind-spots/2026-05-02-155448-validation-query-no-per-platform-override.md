---
id: 2026-05-02-155448-validation-query-no-per-platform-override
date: 2026-05-02
status: open
finding_kind: framework-gap
review_context: "TODO write-primitives-sketch-clickhouse-and-storage-metrics implementation attempt"
related_paths:
  - benchbox/core/write_primitives/catalog/loader.py
  - benchbox/core/write_primitives/benchmark.py
  - benchbox/core/write_primitives/catalog/operations.yaml
suggested_sweep: "Audit every write_primitives op whose validation_query uses dialect-specific syntax (datasketch_*, theta_sketch_*, KLL_QUANTILES.*, APPROX_TOP_K_*, HLL_COMBINE, etc.) — those validation_queries cannot succeed on engines other than the one whose syntax was used to author them. Likely false-PASS or hard-FAIL across the cloud overrides for the 8 sketch ops + any future ops that follow the same pattern."
todo_id: null
---

# Write-Primitives validation_query Has No Per-Platform Override

## Finding

`WriteOperation.validation_queries[]` are sent **raw** to
`connection.execute(val_sql)` with no per-platform override mechanism — the
loader (`loader.py`) defines `ValidationQuery` as a single SQL string, and the
runner (`benchmark.py:_run_operation_validation`) does not call any dialect
translator before executing.

Meanwhile `WriteOperation.platform_overrides` *does* let `write_sql` differ
per engine. So the existing 8 sketch ops have ClickHouse/Snowflake/Databricks/
BigQuery `write_sql` variants but a single DuckDB-syntax `validation_query`.
On every non-DuckDB engine, the validation step will raise an "unknown
function" exception and mark the op FAILED.

This is structurally invisible today because:

- Cloud overrides for these ops have never been verified end-to-end (cloud
  credentials gap, deferred to `write-primitives-sketch-cloud-verification`).
- `clickhouse: null` skips the op entirely, so validation is never attempted.

The TODO `write-primitives-sketch-clickhouse-and-storage-metrics` would have
been the first PR to actually run a sketch-merge validation_query on a
non-DuckDB engine (chDB), which surfaced this gap immediately. Even a perfect
ClickHouse `write_sql` override fails because the validation_query
`SELECT datasketch_theta_estimate(datasketch_theta(user_sketch))...` is
DuckDB-only syntax.

## Why this matters

Three downstream TODOs depend on this gap being closed first or worked
around:

- `write-primitives-sketch-clickhouse-and-storage-metrics` (this finding's
  origin) — w3 + w5 cannot be implemented in operations.yaml alone.
- `write-primitives-sketch-cloud-verification` — when Snowflake/BigQuery/
  Databricks credentials become available, cloud runs will fail validation
  even though the writes succeed.
- `write-primitives-sketch-pyspark-dataframe-surface` — DataFrame mode has
  its own validation contract path; SQL-mode equivalents would hit this
  same wall.

PR #114 added scalar-bounds enforcement to gate ops at validation time,
which made this gap actually break ClickHouse runs (previously it would
have silently returned wrong values).

## Suggested next steps

- [ ] Promote to a fix-class TODO: extend `ValidationQuery` schema +
      loader + runner to support `validation_query.platform_overrides`,
      mirroring the existing `write_sql.platform_overrides` shape.
- [ ] Once the override mechanism lands, unblock the four sketch TODOs
      and add an explicit dependency edge from each to the new fix TODO.
- [ ] Audit existing 8 sketch ops' validation_queries: confirm
      DuckDB-syntax-only assumption was intentional and document the
      cross-engine gap inline alongside the cloud platform_overrides.
- [ ] Consider whether sqlglot dialect translation in
      `_run_operation_validation` would be a smaller-blast alternative
      (probably no — sketch function names are semantic, not syntactic,
      mappings).

## Why it didn't get caught earlier

- PR #112 + #114 reviewers smoke-verified on DuckDB only ("DuckDB SF=0.01:
  theta 14836.89 ∈ [14000, 16000]" — note: this no longer reproduces; see
  related blind-spot on the datasketches extension drift).
- The cloud `write_sql` overrides shipped with the assumption that
  validation would just-work, but the existing validation_query SQL bodies
  (`datasketch_*` family) are non-portable.
- The sketch TODOs all share the same author and the same blind spot.

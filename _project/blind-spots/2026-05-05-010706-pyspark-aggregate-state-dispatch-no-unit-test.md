---
id: 2026-05-05-010706-pyspark-aggregate-state-dispatch-no-unit-test
date: 2026-05-05
status: open
finding_kind: missed-axis
review_context: "/code review of pyspark-cli-integration W2 (aggregate-state dispatch fork)"
related_paths:
  - benchbox/core/write_primitives/benchmark.py
  - tests/unit/core/write_primitives/test_pyspark_sketch_factories.py
  - tests/unit/core/write_primitives/test_aggregate_state_catalog.py
suggested_sweep: "audit other live-Spark-only integration paths in BenchBox to see whether unit tests with stubbed managers would catch dispatch-layer regressions earlier"
todo_id: null
---

# Aggregate-state dispatch fork has no stubbed-manager unit test

## Finding

`WritePrimitivesBenchmark._execute_aggregate_state_op` is exercised today
by exactly one path: the real `benchbox run --platform pyspark
--benchmark write_primitives --queries sketch_df_hll_persist_merge`
command run during the cli-integration TODO. Unit tests cover:

- The catalog loader for `aggregate_state` blocks (7 tests in
  `test_aggregate_state_catalog.py`).
- The PySpark factories with MagicMock spark sessions (existing
  `test_pyspark_sketch_factories.py`).
- The `DataFrameWriteOperationsManager.execute_aggregate_persist` /
  `execute_aggregate_merge` methods (existing
  `test_dataframe_aggregate_state_ops.py`).

What is **not** covered by unit tests:

- The dispatch fork itself — the partitioning of ops into "aggregate-
  state vs SQL parity" branches, the `_resolve_platform_name` /
  `_extract_spark_session` helpers, the per-op result envelope shape,
  the SKIPPED-on-unsupported-platform path, the SKIPPED-on-Spark-version
  path, the validation-bound check on `aggregate_value`, the cleanup
  of state directories between iterations, and the bridging of
  `manager.execute_aggregate_persist` / `merge` results into the
  benchmark row format.

If PySpark's API shifts in a way that affects only the dispatch path
(not the loader or factories), unit tests will stay green while
`benchbox run --platform pyspark --queries sketch_df_*` regresses
silently. The factory unit tests use MagicMock objects that auto-chain
attribute access, so they pass against any API shape.

## Why this matters

The cli-integration TODO predicted that real-Spark integration would
surface "type-shape bugs the mocks missed." It did — the `F.approx_top_k_*`
symbols are missing from the PySpark 4.1.1 Python wheel. The skip path
caught that gracefully, but the *finding* of the gap was a manual debug
session, not an automated regression alarm. A stubbed-manager unit test
that exercises the dispatch fork against a mock `DataFrameWriteOperationsManager`
(returning a fixed aggregate_value) would close the loop: future API
changes that break dispatch but not the underlying primitives would be
caught before the next CLI run.

## Suggested next steps

- [ ] Add unit tests for `WritePrimitivesBenchmark._execute_aggregate_state_op`
  using a mock manager that returns `DataFrameWriteResult` objects with
  controllable `success` / `error` / `metrics`. Cover at least: SUCCESS
  with bound-passing aggregate_value, FAILED on persist failure, FAILED
  on merge failure, FAILED on bound violation, SKIPPED on unsupported
  platform, SKIPPED on Spark version guard.
- [ ] Add a unit test for `_resolve_aggregate_source_path` that uses a
  pre-existing Parquet directory (cache-hit path) so the conversion
  branch isn't the only path covered.
- [ ] Consider whether the live-Spark CLI command should be wired into
  a nightly CI lane so dispatch-layer regressions surface within a day
  of merge, not at the next ad-hoc run.

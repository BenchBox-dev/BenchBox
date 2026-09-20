# ADR: Concurrency Utility APIs — Remove the Quarantined Executors

## Status

Accepted. Implements `concurrency-public-api-semantic-reconciliation`.

## Date

2026-09-19

## Context

`concurrency-executor-consolidation` quarantined `PowerRunExecutor` and
`ConcurrentQueryExecutor` (`benchbox/utils/execution_manager.py`): nothing
in `benchbox` calls either class, after the only two routings turned out
to terminate in a non-executing stub. The classes survived only through
the `benchbox.utils` re-export. This item reassesses them by behavior
against the canonical paths.

### Inventory

| Dimension | `ConcurrentQueryExecutor` | Canonical: `StreamRunner` + `TPCHThroughputTest` / `TPCDSThroughputTest` |
|---|---|---|
| Entry | `execute_concurrent_queries(query_executor_factory, num_streams)` — factory returns per-stream executors | `TPCHThroughputTest(benchmark, connection_factory, ...).run()` — factory returns connections; streams run inside one test |
| Config | `execution.concurrent_queries.*` (`enabled` gate raising `ValueError` when off, `max_concurrent`, timeouts, `retry_failed_queries`) | Benchmark config (`num_streams`, `max_workers`, `stream_timeout`); no enabled-gate, no retries (TPC forbids retrying measured queries) |
| Warmup/iterations | None (single pass over N streams) | Seeds per stream (`base_seed + stream_id`); iterations belong to the caller's power loop, not the throughput path |
| Failure | Per-stream dicts, `queries_failed` counts, optional retries | Fail-closed accounting (`streams_successful`, `errors`, forced-failed partial streams; see `test_runner.py`) |
| Statistics | `throughput_queries_per_second`, stream dicts | `ThroughputResult` with per-stream `ThroughputStreamResult` (durations, per-query results) |
| Result shape | `ConcurrentQueryResult` | `ThroughputResult` — not interchangeable |

| Dimension | `PowerRunExecutor` | Canonical: `TPCHPowerTest` / `TPCDSPowerTest` via benchmark runners |
|---|---|---|
| Entry | `execute_power_runs(power_test_factory, scale_factor)` — factory takes optional `stream_id` | `TPCHPowerTest(benchmark, connection, scale_factor, stream_id, warm_up, validation, ...).run()` — bound to one real connection |
| Config | `execution.power_run.*` (`iterations`, `warm_up_iterations`, per-iteration timeouts, `fail_fast`) | Per-harness config (`TPCHPowerTestConfig`: `warm_up`, `validation`, `validation_mode`, `timeout`, `query_subset`) |
| Warmup/iterations | Framework-owned warm-up + iteration loop with stream permutations | Harness-owned warm-up; iterations are the caller's loop over stream IDs |
| Failure | `PowerRunResult` aggregates, `fail_fast` flag | Per-query results with errors; `RuntimeError` on preflight/execution failure |
| Statistics | `power_at_size` mean/median/stdev over iterations | `power_at_size` per run; statistics over runs belong to the caller |
| Result shape | `PowerRunResult` / `PowerRunIteration` | `TPCHPowerTestResult` — not interchangeable |

No mapping preserves semantics: the executors' config keys, retry
behavior, enabled-gate, and result shapes have no canonical counterpart,
and the canonical paths' connection-bound execution, validation modes,
and fail-closed accounting have no executor counterpart. A "tested
compatibility adapter" would be new code serving no caller — the only
in-tree callers are tests of the executors themselves and two guides.

## Decision

**Remove `benchbox/utils/execution_manager.py` entirely** (both
executors plus `PowerRunIteration`, `PowerRunResult`,
`ConcurrentQueryResult`), prune the `benchbox/utils/__init__.py`
re-export, and rewrite the two guides that teach the removed surface:

- `docs/advanced/power-run-concurrent-queries.md`
- `docs/usage/examples.md` (power-run and concurrent sections)

to the canonical APIs with migration examples. Migration:

- Power iterations/statistics → construct `TPCHPowerTest` /
  `TPCDSPowerTest` per stream ID in a plain loop and aggregate
  `power_at_size` with `statistics`; warm-up, validation, and timeouts
  are harness parameters.
- Concurrent streams → `TPCHThroughputTest` / `TPCDSThroughputTest`
  with a connection factory and `num_streams`; `StreamRunner` owns
  concurrency, timeout, and failure accounting.

No beta compatibility shim: the surface was quarantined as do-not-use
since the consolidation, has no benchmark callers, and the guides are
corrected in the same change. `ExecutionConfigHelper`
(`benchbox/utils/config_helpers.py`) is unaffected and stays.

## Alternatives considered

- **Adapt as compatibility shims.** Rejected: shims would need to invent
  semantics for unmappable dimensions (retries, enabled-gate, foreign
  result shapes) with zero callers to serve.
- **Deprecate with a removal version.** Rejected over removal because the
  quarantine already served as the deprecation notice and no production
  path can import these names; a shim cycle would prolong the ambiguity
  this item closes.

## Consequences

- `tests/unit/utils/test_execution_manager.py` is deleted with the
  module; TPC-H compliance tests that exercised the removed classes are
  repointed at the canonical harnesses' stream-permutation behavior.
- Retained-path regression coverage (StreamRunner failure accounting in
  `tests/unit/core/throughput/test_runner.py`, plus a new power-harness
  failure test) proves no retained path reports success without
  executing the requested SQL.

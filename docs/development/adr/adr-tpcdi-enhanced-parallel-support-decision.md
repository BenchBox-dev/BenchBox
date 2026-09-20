# ADR: TPC-DI Enhanced Parallel Surface — Remove the Second Scheduler

## Status

Accepted. Implements `tpcdi-enhanced-parallel-support-decision` and resolves
the TPC-DI portion of `decide-fate-of-documented-unimplemented-surfaces`
(the admin and explorer portions of that item are untouched).

## Date

2026-09-19

## Context

After false-success containment (`tpcdi-parallel-phase-truthful-outcome`),
the TPC-DI tree carries two parallel-execution stories:

1. **Canonical path.** `TPCDIBenchmark(enable_parallel: bool, max_workers: int)`
   drives `run_etl_pipeline`, whose `_transform_source_data_parallel`
   executes real per-file transforms (`_transform_csv_file`,
   `_transform_xml_file`, `_transform_fixed_width_file`,
   `_transform_json_file` — genuine pandas transforms with defined inputs,
   outputs, and staged-data accumulation) concurrently through a
   `ThreadPoolExecutor` sized by `max_workers`. The exported
   `TPCDIETLPipeline` (`benchbox/core/tpcdi/etl/pipeline.py`) provides the
   historical/incremental/SCD orchestration over real backends.

2. **Enhanced parallel surface.** `run_enhanced_etl_pipeline` Phase 3
   (`_run_parallel_batch_processing`) submits three tasks to
   `ParallelBatchProcessor` (`benchbox/core/tpcdi/etl/parallel_batch_processor.py`,
   ~900 lines: dependency scheduler, worker pools, retry machinery) whose
   task functions only echo their input counts back:
   `{"batch_type": ..., "records": data.get("records", 0), "processed": True}`.
   No task reads, transforms, or writes any data. The phase reports
   `batches_processed` and `workers_used` for work that never happened.

Caller inventory (2026-09-19): the scheduler is imported only by
`benchbox/core/tpcdi/benchmark.py` and its dedicated unit tests; the
enhanced pipeline is invoked only by integration and performance tests.
No CLI command, MCP tool, or documented public import (`etl/__init__.py`
does not export the scheduler) reaches either. There is no benchmark
evidence that the canonical path cannot meet a parallel-ETL requirement —
no measured gap, no maintenance owner, no performance budget for a second
scheduler.

The deployment guide compounds the confusion: its `parallel_processing:`
YAML block (`mode: adaptive`, `workload_type`, `enable_parallel_etl`,
`enable_parallel_extract`, …) names knobs no loader or config class
consumes (`TPCDIConfig` carries only `enable_parallel`, `max_workers`,
`chunk_size`, and siblings), teaching readers a surface that cannot run.

## Decision

**Remove the second scheduler; parallel ETL lives in the canonical flags.**

1. Delete `benchbox/core/tpcdi/etl/parallel_batch_processor.py`
   (`ParallelBatchProcessor`, `BatchProcessingTask`,
   `ParallelProcessingConfig`, and supporting machinery).
2. Remove Phase 3 (`_run_parallel_batch_processing`) from
   `run_enhanced_etl_pipeline` and the `enable_parallel_processing`
   parameter that existed only to gate it. The remaining phases
   (FinWire/CustomerMgmt processing, SCD Type 2, incremental loading,
   quality monitoring) are real and stay.
3. Parallel TPC-DI ETL is `TPCDIConfig(enable_parallel=True,
   max_workers=N)` on the canonical `run_etl_pipeline` path. That is the
   migration: there is nothing to port, because the removed phase never
   performed ETL.
4. Correct the deployment guide's `parallel_processing:` YAML block to the
   real `TPCDIConfig` fields and document the canonical flags as the
   parallel interface.

No beta compatibility cycle applies: the removed surface had no
production callers, no CLI/MCP exposure, and no package export, so
nothing external can depend on it. The tracker portion for admin/explorer
surfaces stays with `decide-fate-of-documented-unimplemented-surfaces`.

## Alternatives considered

- **Route Phase 3 to canonical real transforms.** Rejected: it would wrap
  the canonical transforms in a redundant dependency scheduler to
  preserve a phase boundary that exists only to host synthetic tasks.
  The canonical path already parallelizes the real work directly.
- **Rebuild a distinct scheduler on measured evidence.** Rejected: no
  capability gap was demonstrated. A new scheduler needs affirmative
  benchmark evidence, which does not exist.
- **Keep the scheduler as a generic utility.** Rejected: a generic
  task-runner without a production consumer is the same second scheduler
  with a different justification, and its only in-tree use was
  fabricating batch counts.

## Consequences

- `tests/unit/tpcdi/test_phase3_etl_enhanced.py` (dedicated scheduler
  tests) is deleted with the module.
- Integration/performance tests that asserted the synthetic
  `parallel_batch_processing` phase keys or passed
  `enable_parallel_processing` are updated to the real interface.
- The manifest-level rule stands: no placeholder or synthetic task may
  enter production data mutation under any outcome — this decision
  removes the one in-tree violator rather than legitimizing it.

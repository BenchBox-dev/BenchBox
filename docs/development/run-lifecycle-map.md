<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Run Lifecycle Branch Map

```{tags} contributor, architecture
```

This document records the current `benchbox run` lifecycle and export branches before the
single-path refactor.

## Canonical Runtime Today

For real benchmark execution, `benchbox/cli/commands/run.py` delegates to:

1. `BenchmarkOrchestrator.execute_benchmark(...)` in `benchbox/cli/orchestrator.py`
2. `run_benchmark_lifecycle(...)` in `benchbox/core/runner/runner.py`


## Branch Matrix (`benchbox/cli/commands/run.py`)

| Branch | Entry condition | Runtime path | Export path |
| --- | --- | --- | --- |
| Dry run | `if dry_run:` | `DryRunExecutor.execute_dry_run(...)` | `DryRunExecutor.save_dry_run_results(...)` |
| Direct non-interactive SQL/DataFrame | `test_execution_type` not data/load-only and platform+benchmark provided | `BenchmarkOrchestrator` -> `run_benchmark_lifecycle` | Inline `ResultExporter` block with directory-manager filename override |
| Data-only / load-only | `if test_execution_type in [\"data_only\", \"load_only\"]` | `BenchmarkOrchestrator` -> `run_benchmark_lifecycle` (phase-limited) | Separate inline `ResultExporter` block with mode-specific status rendering |
| Interactive | fallback TTY-guided path | `BenchmarkOrchestrator` -> `run_benchmark_lifecycle` | Third inline export block (`config.get(\"output.formats\", [\"json\"])`) |

## Duplicate Export Logic Identified

`run.py` currently contains three non-dry-run export blocks with drift in:

- format selection (`[\"json\"]` vs config-driven),
- output filename/output_dir handling,
- status output formatting.

These blocks are the target for unification in the refactor.

## Metadata Wiring Gap — Resolved

Driver/runtime metadata enrichment previously existed in `ExecutionEngine._enrich_driver_metadata(...)`
and was wired only in `benchbox/cli/execution_pipeline.py`. With the pipeline module deleted
(`benchbox/cli/execution_pipeline.py` removed, `ExecutionPipeline`/`ExecutionEngine` no longer retained),
enrichment now runs on the canonical path via `benchbox/core/run_service.py::execute_run` → `apply_driver_metadata(...)` (see `benchbox/core/results/driver_metadata.py`), so all run modes inherit it.

## Refactor Baseline Decisions

- Canonical runtime path: `run.py` -> `BenchmarkOrchestrator` -> `run_benchmark_lifecycle`.
- `ExecutionPipeline` must not remain a parallel behavior-bearing runtime path.
- Export policy must be centralized and called by all non-dry-run branches.
- Metadata enrichment must run on the canonical path before result export.

## Single-Path Architecture (Post-Refactor)

### Runtime path

1. `benchbox/cli/commands/run.py` builds validated CLI config and execution context.
2. `_execute_orchestrated_run(...)` executes through `BenchmarkOrchestrator`.
3. `BenchmarkOrchestrator.execute_benchmark(...)` delegates to `run_benchmark_lifecycle(...)`.
4. `apply_driver_metadata(...)` enriches results on the canonical path.
5. `_export_orchestrated_result(...)` performs export with directory-manager naming.

### Extension points

- Add lifecycle behavior in `benchbox/core/runner/runner.py`, not in CLI branch-specific code.
- Add result metadata wiring in `benchbox/core/results/driver_metadata.py` so all run modes inherit it.
- Add export behavior in `benchbox/cli/commands/run.py` helper `_export_orchestrated_result(...)`.

## Alpha Release Notes (Execution Refactor)

- Removed legacy `quick` branch logic from `benchbox run`.
- Removed legacy `no_regenerate` option wiring from run-command benchmark options.
- Unified non-dry-run execution through shared run-command helpers:
  - `_execute_orchestrated_run(...)`
  - `_export_orchestrated_result(...)`
- Deleted `benchbox/cli/execution_pipeline.py` (`ExecutionPipeline`/`ExecutionEngine`) — it was superseded by `benchbox/core/run_service.py::execute_run` + `run_benchmark_lifecycle(...)`; enrichment and export are now on the canonical path (see *Single-Path Architecture* above).

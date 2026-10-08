<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Run Lifecycle Branch Map

```{tags} contributor, architecture
```

This document maps the `benchbox run` lifecycle and its export path.

## Canonical runtime

For real benchmark execution, `benchbox/cli/commands/run.py` delegates to:

1. `BenchmarkOrchestrator.execute_benchmark(...)` in `benchbox/cli/orchestrator.py`
2. `execute_run(...)` in `benchbox/core/run_service.py`
3. `run_benchmark_lifecycle(...)` in `benchbox/core/runner/runner.py`

The CLI path is therefore `run.py` -> `BenchmarkOrchestrator` -> `execute_run`
-> `run_benchmark_lifecycle`. The MCP sync and durable-job surfaces converge on
the same core primitive through `_execute_mcp_run_via_core(...)` in
`benchbox/mcp/tools/benchmark.py` and its durable caller in `benchbox/mcp/jobs.py`.

## Run branches (`benchbox/cli/commands/run.py`)

| Branch | Entry condition | Runtime path | Export path |
| --- | --- | --- | --- |
| Dry run | `--dry-run` given (`_run_dry_run`) | `DryRunExecutor.execute_dry_run(...)` | `DryRunExecutor.save_dry_run_results(...)` |
| Direct non-interactive SQL/DataFrame | platform and benchmark provided, not data-only or load-only | `_execute_orchestrated_run(...)` | `_export_orchestrated_result(...)` |
| Data-only / load-only | `test_execution_type` is `data_only` or `load_only` | `_execute_orchestrated_run(...)` (phase-limited) | `_export_orchestrated_result(...)` |
| Interactive | fallback TTY-guided path | `_execute_orchestrated_run(...)` | `_export_orchestrated_result(...)` |

Driver and runtime metadata are applied on the canonical path by
`benchbox/core/run_service.py::execute_run` through `apply_driver_metadata(...)`
(`benchbox/core/results/driver_metadata.py`), so every run mode inherits them.

## Single-path architecture

### Runtime path

1. `benchbox/cli/commands/run.py` builds validated CLI config and execution context.
2. `_execute_orchestrated_run(...)` executes through `BenchmarkOrchestrator`.
3. `BenchmarkOrchestrator.execute_benchmark(...)` delegates to `execute_run(...)`.
4. `execute_run(...)` invokes `run_benchmark_lifecycle(...)` and applies driver metadata.
5. `_export_orchestrated_result(...)` performs export with directory-manager naming.

### Extension points

- Add lifecycle behavior in `benchbox/core/runner/runner.py`, not in CLI branch-specific code.
- Add result metadata wiring in `benchbox/core/results/driver_metadata.py` so all run modes inherit it.
- Add export behavior in `benchbox/cli/commands/run.py` helper `_export_orchestrated_result(...)`.

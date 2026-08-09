# Runtime Module Architecture Overview

```{tags} contributor, reference
```

This guide summarizes the organization of the runtime-focused modules after the modularization refactor. It highlights the primary entry points, extension boundaries, and the locations of shared utilities.

## CLI package

- `benchbox/cli/app.py`: constructs the root Click application and registers commands.
- `benchbox/cli/commands/`: one file per public command (`run`, `profile`, `benchmarks`, etc.). Each module only exports a Click command function and related helper types.
- `benchbox/cli/presentation/`: light-weight presentation helpers (currently `system.py`).
- `benchbox/cli/shared.py`: shared console helpers (`console`, `set_quiet_output`, `silence_output`).
- `benchbox/cli/main.py`: thin compatibility layer that re-exports the new modules for legacy imports and tests.
- `benchbox/cli/orchestrator.py`: canonical runtime bridge from CLI to core lifecycle (`run_benchmark_lifecycle`).

### Extension notes

- New commands should live in `benchbox/cli/commands/` and only import shared utilities from `benchbox.cli.shared` or other command modules.
- Presentation-only helpers should live under `benchbox/cli/presentation/` to keep command modules focused on business logic.

## TPC-DS package

- `benchbox/core/tpcds/benchmark/`: `config.py`, `results.py`, `phases.py`, and `runner.py` implement the benchmark orchestration. `__init__.py` re-exports `TPCDSBenchmark` and data classes.
- `benchbox/core/tpcds/generator/`: mixin-based split between `manager.py`, `runner.py`, `streaming.py`, and `filesystem.py` to keep responsibilities focused (execution, streaming chunking, file handling).
- `benchbox/core/tpcds/schema/`: `models.py`, `tables.py`, and `registry.py` provide a declarative schema catalog that mirrors the official specification.

### Extension notes

- New benchmark behaviors should extend the relevant mixin (`runner.py` for orchestration, `streaming.py` for table generation variations, `filesystem.py` for file/mount logic).
- Schema changes should modify the declarative tables in `schema/tables.py` with supporting helpers in `schema/registry.py`.

## TPC-DI package

- `benchbox/core/tpcdi/etl/pipeline.py`: contains `TPCDIETLPipeline` with clear dependencies on ETL sub-modules.
- `benchbox/core/tpcdi/etl/results.py`: shared dataclasses for ETL pipeline phases.
- `benchbox/core/tpcdi/generator/`: modular generator broken into `data.py` (orchestrator), `dimensions.py`, `facts.py`, `manifest.py`, and `monitoring.py` for dedicated responsibilities.

### Extension notes

- New pipeline behaviors should either extend `pipeline.py` or live in the specialized modules under `benchbox/core/tpcdi/etl/` (e.g., `batch`, `incremental_loader`).
- Generator extensions inherit from the mixins in `benchbox/core/tpcdi/generator/` to keep orchestration and domain-specific logic separated.

## ClickHouse platform

- `benchbox/platforms/clickhouse/__init__.py`: re-exports a modularized adapter.
- `adapter.py`: core `ClickHouseAdapter` that now inherits from individual mixins.
- Mixins: `metadata.py`, `setup.py`, `diagnostics.py`, `workload.py`, and `tuning.py` encapsulate discrete responsibilities; `_dependencies.py` centralizes optional imports; `client.py` contains `ClickHouseLocalClient`.

### Extension notes

- Connection/setup changes should live in `setup.py`; diagnostics and metadata reporting belongs in `diagnostics.py`/`metadata.py`.
- Workload-specific adaptations (schema creation, load pipeline, query execution) should extend `workload.py`.

## Validation utilities

- `benchbox/core/validation/shared/`: new shared utilities (`logging.py`) host logic reused by `DataValidator` and future validation engines.
- `benchbox/core/validation/data.py` now delegates to the shared logging helper for consistent reporting.

### Extension notes

- Additional shared helpers should be placed in `benchbox/core/validation/shared/` to keep engines thin and consistently reusable.

## File size guardrails

A new automated test (`tests/system/test_module_size_thresholds.py`) watches the size of runtime-critical modules (CLI commands, benchmark orchestration, generators, and platform adapters). The guardrail enforces a default 1,200 line limit with an allowlist for modules that are intentionally larger. See the test file for configuration details.

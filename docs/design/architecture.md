<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# BenchBox Architecture

```{tags} contributor, concept
```

## Overview

BenchBox is a modular SQL and DataFrame benchmarking framework for OLAP databases. The architecture separates concerns into four layers:

1. **Benchmarks** — dataset definitions, schemas, queries, and data generation
2. **Platforms** — database adapters for SQL and DataFrame execution
3. **Core** — shared infrastructure (runner, results, validation, visualization, etc.)
4. **CLI** — user-facing commands and execution orchestration

## Execution Model

BenchBox uses a **lifecycle-based** execution model (not Template Method). A benchmark run progresses through phases orchestrated by `run_benchmark_lifecycle()` in `benchbox.core.runner.runner`:

```
generate → load → warmup → power → throughput → maintenance
```

### Key Types

| Type | Location | Purpose |
|------|----------|---------|
| `LifecyclePhases` | `core.runner.runner` | Controls which phases to run |
| `BenchmarkResults` | `core.results.models` | Complete run output with phase results |
| `BenchmarkConfig` | `core.schemas` | Benchmark name, scale, query selection (Pydantic) |
| `DatabaseConfig` | `core.schemas` | Connection and platform configuration (Pydantic) |
| `PlatformAdapter` | `platforms.base.adapter` | Abstract base for all SQL platform adapters |

### SQL Execution Path

```
CLI (run command)
  → BenchmarkOrchestrator (cli/orchestrator.py)
    → run_benchmark_lifecycle() (core/runner/runner.py)
      → PlatformAdapter.execute_query() for each query
        → BenchmarkResults
```

The `PlatformAdapter` base class (`benchbox/platforms/base/adapter.py`) provides the interface that all 33 SQL platform adapters implement. Each adapter handles connection management, DDL generation, data loading, and query execution for its target database.

### DataFrame Execution Path

DataFrame benchmarks use a parallel execution path:

```
CLI (run command with --platform *-df)
  → run_dataframe_benchmark() (core/runner/dataframe_runner.py)
    → DataFrameContext (core/dataframe/context.py)
      → ExpressionFamilyAdapter or PandasFamilyAdapter
        → BenchmarkResults
```

| Type | Location | Purpose |
|------|----------|---------|
| `DataFrameContext` | `core.dataframe.context` | Protocol for table access and column references |
| `ExpressionFamilyAdapter` | `platforms.dataframe.expression_family` | Base for Polars, PySpark, DataFusion, LakeSail |
| `PandasFamilyAdapter` | `platforms.dataframe.pandas_family` | Base for Pandas, Modin, cuDF, Dask |

The **family-based** adapter architecture means adding a new expression-style platform (e.g., Polars-like API) requires only implementing a thin adapter on top of `ExpressionFamilyAdapter`, inheriting query translation, tuning, and execution logic.

## Benchmark Layer

Each benchmark (TPC-H, TPC-DS, SSB, ClickBench, etc.) lives under `benchbox/core/<benchmark_id>/` and provides:

- **Schema** — table definitions and DDL generation via `get_create_tables_sql(dialect, tuning_config)`
- **Queries** — SQL templates with dialect translation via sqlglot
- **Data generation** — using official TPC tools (dbgen/dsdgen) or built-in generators
- **Validation** — expected result counts and answer verification

All benchmarks inherit from `BaseBenchmark` (`benchbox/base.py`). Benchmarks are registered in `benchbox/core/benchmark_registry.py` which maps CLI names (e.g., `tpch`) to class names and metadata.

There are currently 20 benchmarks across TPC standards, academic, industry, and primitives categories.

## Platform Layer

### SQL Platforms (33 adapters)

All SQL adapters inherit from `PlatformAdapter` and implement:
- `get_connection_from_pool()` / `close_connection()` — connection lifecycle
- `execute_query()` — query execution with timing
- `get_create_tables_sql()` — platform-specific DDL
- `load_data()` — bulk data loading

Platforms span local engines (DuckDB, SQLite, DataFusion), cloud warehouses (Snowflake, BigQuery, Databricks, Redshift), and specialized systems (ClickHouse, StarRocks, QuestDB, TimescaleDB, etc.).

### DataFrame Platforms (8 adapters)

DataFrame adapters are organized by API family:
- **Expression family**: Polars, PySpark, DataFusion, LakeSail
- **Pandas family**: Pandas, Modin, cuDF, Dask

## Core Infrastructure

The `benchbox/core/` directory contains 39 subsystems:

| Subsystem | Purpose |
|-----------|---------|
| `runner/` | Benchmark lifecycle orchestration |
| `results/` | Result models, serialization, aggregation |
| `validation/` | Answer validation, data verification |
| `visualization/` | ASCII chart generation and result rendering |
| `dataframe/` | DataFrame execution context, profiling, tuning |
| `query_plans/` | Query plan capture and analysis |
| `tuning/` | Unified tuning configuration system |
| `data_organization/` | Sorted ingestion, clustering strategies |
| `comparison/` | Result comparison and regression detection |
| `cost/` | Cloud cost estimation |
| `analysis/` | Statistical analysis of benchmark results |
| `contracts/` | Interface contracts and type validation |

## CLI Layer

The CLI (`benchbox/cli/`) uses Click and provides 25+ commands. The main `run` command orchestrates the full benchmark lifecycle through `BenchmarkOrchestrator` (`cli/orchestrator.py`) → `run_benchmark_lifecycle()`.

Key command groups: `run`, `compare`, `visualize`, `report`, `metrics`, `tuning`, `platforms`, `shell`, `datagen`, `setup`.

## Visualization

BenchBox provides ASCII chart visualization via `core/visualization/`:
- **ASCII charts** (`core/visualization/ascii/`) — 15+ chart types rendered as terminal text (bar, box plot, heatmap, histogram, scatter, CDF, sparkline, etc.)
- **ResultPlotter** (`core/visualization/result_plotter.py`) — normalizes JSON results and orchestrates chart rendering
- **Templates** (`core/visualization/templates.py`) — named chart combinations (e.g., `flagship`, `comparison`, `executive_summary`)

## MCP Integration

The `benchbox/mcp/` package exposes BenchBox functionality as MCP (Model Context Protocol) tools, enabling AI assistants to discover, run, and analyze benchmarks.

## Key Design Decisions

1. **Lifecycle over Template Method** — execution phases are data-driven, not inheritance-driven
2. **Family-based DataFrame adapters** — minimize code duplication across similar platforms
3. **Official TPC tools** — use dbgen/dsdgen for specification-compliant data generation
4. **sqlglot translation** — single query definition with automatic dialect translation
5. **Lazy platform loading** — heavy SDK imports deferred until platform is actually used
6. **ASCII visualization** — terminal-rendered charts for CI/CD and MCP integration

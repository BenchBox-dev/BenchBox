# Adapter Base Refactor Map

> **Status: COMPLETED (2026-04-13)**
>
> The refactor described in this document has been executed. `benchbox/platforms/base/adapter.py`
> is now a ~600-line thin facade that composes nine mixin classes extracted into:
> `connection.py`, `connection_lifecycle.py`, `connection_wrappers.py`, `data_loading.py`,
> `dialect_translation.py`, `execution.py`, `result_capture.py`, `tuning.py`, `tuning_config.py`.
> All public symbols and import paths are preserved for backward compatibility.
>
> The line ranges below reference the **original monolithic file (5,178 lines)** and are
> intentionally preserved for archaeological reference - they describe the pre-refactor state
> and the rationale behind each extraction decision.

This document is the extraction map that gated the `PlatformAdapter` refactor tracked by
TODO id `quality-refactor-adapter-base-into-cohesive-modules`. `benchbox/platforms/base/adapter.py`
was 5,178 lines and is inherited by ~73 concrete adapters. The refactor was staged in bounded
slices that each preserve import paths and public method signatures. This map enumerates every
public symbol, groups them into candidate target modules, identifies coupling hotspots from
subclass override data, and documents the slice order followed during execution.

All line ranges reference `benchbox/platforms/base/adapter.py` at the time of writing
(5,178 lines, pre-refactor). Override counts were gathered by AST-walking every
`Adapter`-suffixed class in `benchbox/platforms/**/*.py` and counting public-method
redefinitions.

---

## 1. Public symbol inventory

### 1.1 Module-level public symbols

| Symbol | Line range | Current responsibility | Proposed target module | Caller risk |
|--------|------------|------------------------|------------------------|-------------|
| `DriverIsolationCapability` (class/Enum) | 117-138 | Declares adapter driver-isolation capability | `connection` (driver runtime binding lives with connection lifecycle) | Medium - imported by adapter_factory and several adapters |
| `check_isolation_capability` (function) | 193-212 | Raises if adapter cannot honor requested isolation strategy | `connection` | Medium - called from adapter_factory |
| `PlatformAdapter` (class) | 215-4995 | Abstract base class for all adapters | stays in `benchbox.platforms.base.adapter` as a thin facade that composes helpers from target modules | **High** - 73 subclasses, pervasive imports |
| `PlatformAdapterConnection` (class) | 5040-5140 | DB-API-ish wrapper exposing `execute`/`commit`/`rollback`/`close` with benchmark query context | `connection` | Medium |
| `PlatformAdapterCursor` (class) | 5143-5178 | DB-API-ish cursor wrapper with `fetchall`/`fetchone` | `execution` (close to `execute_query`) | Medium |

### 1.2 `PlatformAdapter` public methods

Ordered by file position. Every row lists the exact public name referenced by the verification
script.

| Symbol | Line range | Current responsibility | Proposed target module | Caller risk |
|--------|------------|------------------------|------------------------|-------------|
| `add_cli_arguments` | 308-313 | Hook for registering CLI flags | stays in facade (classmethod surface) | Low |
| `from_config` | 317-325 | Classmethod constructor from ConnectionConfig | `connection` | **High** - 43 subclass overrides |
| `enable_dry_run` | 327-332 | Toggle dry-run mode | `execution` | Low |
| `disable_dry_run` | 334-337 | Toggle dry-run mode off | `execution` | Low |
| `capture_sql` | 339-361 | Append SQL + metadata to capture buffer | `execution` (tied to `execute_query` dry-run path) | Low |
| `get_captured_sql` | 779-785 | Return captured SQL list | `execution` | Low |
| `platform_name` | 788-795 | Short platform identifier | stays in facade (abstract) | Medium - 35 overrides |
| `get_platform_info` | 797-825 | Return platform metadata dict | stays in facade | **High** - 41 overrides |
| `dialect` | 828-830 | Dialect name used for translation | `dialect_translation` | Medium |
| `translate_sql` | 832-861 | Translate SQL from base dialect to adapter dialect | `dialect_translation` | Medium |
| `test_connection` | 863-878 | Smoke-test the configured connection | `connection` | Low |
| `validate_platform_dependencies` | 881-894 | Check installed driver packages | `connection` | Low |
| `require_dependencies` | 923-952 | Raise if required imports missing | `connection` | Low |
| `get_connection_from_pool` | 974-982 | Pool-aware connection fetch | `connection` | Low |
| `create_connection` | 985-993 | Abstract connection constructor | `connection` | **High** - 38 overrides |
| `create_schema` | 996-1005 | Abstract schema creation | `data_loading` | **High** - 37 overrides |
| `apply_table_tunings` | 1007-1023 | Apply per-table tuning options | `tuning` | Medium - 18 overrides |
| `supports_tuning_type` | 1025-1038 | Capability check per TuningType | `tuning` | Medium - 22 overrides |
| `generate_tuning_clause` | 1040-1057 | Render DDL clause for tuning hint | `tuning` | Medium - 19 overrides |
| `apply_unified_tuning` | 1059-1081 | Apply UnifiedTuningConfiguration | `tuning` | Medium - 20 overrides |
| `get_sorted_ingestion_capability` | 1083-1103 | Capability for sorted-ingestion strategies | `tuning` | Low |
| `resolve_sorted_ingestion_strategy` | 1105-1130 | Pick sorted-ingestion path | `tuning` | Low |
| `get_sorted_ingestion_metadata` | 1132-1160 | Metadata for sorted ingestion | `tuning` | Low |
| `apply_ctas_sort` | 1162-1185 | CTAS-with-sort helper | `tuning` (touches `data_loading`) | Low |
| `apply_platform_optimizations` | 1278-1284 | Hook for session-level optimizations | `tuning` | Medium - 26 overrides |
| `apply_constraint_configuration` | 1287-1299 | Apply PK/FK configuration | `tuning` | Medium - 27 overrides |
| `get_effective_tuning_configuration` | 1301-1309 | Resolve effective tunings for a benchmark | `tuning` | Low |
| `validate_tuning_configuration_for_platform` | 1311-1321 | Platform-specific tuning validation | `tuning` | Low |
| `load_data` | 1324-1337 | Abstract data load entrypoint | `data_loading` | **High** - 37 overrides |
| `create_external_tables` | 1339-1356 | External-table registration | `data_loading` | Medium |
| `upload_manifest` | 1358-1370 | Persist upload manifest | `data_loading` | Low |
| `configure_for_benchmark` | 1373-1379 | Hook called before benchmark run | `tuning` (session-level) | **High** - 32 overrides |
| `execute_query` | 1382-1416 | Core query execution entrypoint | `execution` | **High** - 33 overrides |
| `close_connection` | 1418-1425 | Close the adapter connection | `connection` | Medium - 21 overrides |
| `validate_loaded_data` | 1427-1460 | Post-load validation summary | `result_capture` (data-integrity leg) | Medium |
| `validate_platform_capabilities` | 1462-1490 | Pre-flight capability check | stays in facade | Low |
| `get_database_path` | 1492-1503 | Filesystem DB path if any | `connection` | Low |
| `check_database_exists` | 1505-1523 | Local DB existence check | `connection` | Low |
| `check_server_database_exists` | 1525-1536 | Remote DB existence check | `connection` | Medium - 16 overrides |
| `handle_existing_database` | 1557-1650 | Decide drop/reuse policy | `connection` (calls `drop_database`) | Medium |
| `drop_database` | 1674-1682 | Drop the target database | `connection` | Medium - 17 overrides |
| `display_query_plan_if_enabled` | 1889-1911 | Render plan when capture flag is set | `result_capture` | Low |
| `get_query_plan` | 1913-1925 | Return the last captured plan | `result_capture` | Medium - 18 overrides |
| `get_query_plan_parser` | 1927-1935 | Return plan parser for this platform | `result_capture` | Low |
| `capture_query_plan` | 1973-2114 | Execute EXPLAIN, parse, store | `result_capture` | Medium |
| `get_tpc_base_dialect` | 2116-2132 | Source dialect for TPC translation | `dialect_translation` | Low |
| `validate_tuning_configuration` | 2134-2146 | Validate a tuning config document | `tuning` | Low |
| `save_tuning_metadata` | 2206-2228 | Persist tuning metadata artifact | `tuning` | Low |
| `validate_row_counts` | 2230-2262 | Check row counts against expectations | `result_capture` (validation leg) | Low |
| `get_table_row_count` | 2587-2606 | Fetch a single table row count | `data_loading` / `execution` boundary | Low |
| `run_enhanced_benchmark` | 3100-3275 | Full benchmark orchestration | stays in facade (remains `execution` orchestrator) | **High** - top-level entrypoint |
| `run_benchmark` | 3277-3287 | Back-compat wrapper around `run_enhanced_benchmark` | stays in facade | **High** |
| `run_power_test` | 3837-3878 | Power-test driver | `execution` | Low |
| `run_throughput_test` | 3880-3930 | Throughput-test driver | `execution` | Low |
| `run_maintenance_test` | 3932-3958 | Maintenance-test driver | `execution` | Low |
| `log_verbose` | 4981-4983 | Verbosity passthrough | stays in facade (inherited mixin) | Low |
| `log_very_verbose` | 4985-4987 | Verbosity passthrough | stays in facade | Low |
| `log_operation_start` | 4989-4991 | Verbosity passthrough | stays in facade | Low |
| `log_operation_complete` | 4993-4995 | Verbosity passthrough | stays in facade | Low |

### 1.3 `PlatformAdapterConnection` / `PlatformAdapterCursor` / `_NoCloseProxy` members

| Symbol | Line range | Current responsibility | Proposed target module | Caller risk |
|--------|------------|------------------------|------------------------|-------------|
| `set_query_context` | 5073-5084 | Attach benchmark/query metadata to connection | `connection` | Low |
| `execute` (on `PlatformAdapterConnection`) | 5086-5125 | Execute SQL through adapter connection wrapper | `connection` / `execution` boundary | Medium |
| `commit` | 5127-5130 | Transaction commit | `connection` | Low |
| `rollback` | 5132-5135 | Transaction rollback | `connection` | Low |
| `close` (on `PlatformAdapterConnection`) | 5137-5140 | Close the wrapped connection | `connection` | Low |
| `fetchall` | 5172-5174 | Cursor fetchall passthrough | `execution` | Low |
| `fetchone` | 5176-5178 | Cursor fetchone passthrough | `execution` | Low |
| `close` (on `_NoCloseProxy`, private class but `close` name is public) | 5023-5026 | No-op close for proxy-wrapped connections | `connection` (keeps with proxy) | Low |

### 1.4 Nested public-named closures (NOT top-level API)

These appear in the symbol inventory because `ast.walk` recurses into function bodies; they are
nested helpers, not API surface, and move with their enclosing method.

- `signal_handler` (line 3715, inside `_execute_all_queries`): SIGINT guard - travels with
  `execution`.
- `connection_factory` (lines 4422, 4605, 4731, 4824, 4914): per-test-type connection factories
  defined inside `_execute_tpch_power_test`, `_execute_tpcds_power_test`,
  `_execute_tpch_throughput_test`, `_execute_tpcds_throughput_test`, `_execute_tpcds_maintenance_test`.
  They move with `execution` when those methods are extracted.

### 1.5 Heavy private helpers (> 50 lines)

Listed so the refactor can weigh them during slicing; not exhaustive of all `_`-helpers.

| Helper | Line range | Lines | Belongs with |
|--------|-----------|-------|--------------|
| `__init__` | 230-298 | 69 | stays in facade |
| `_collect_resource_utilization` | 363-563 | 201 | `result_capture` |
| `_summarize_performance_characteristics` | 565-777 | 213 | `result_capture` |
| `_build_query_result_with_validation` | 1739-1803 | 65 | `execution` |
| `_validate_database_tunings` | 2148-2204 | 57 | `tuning` |
| `_create_enhanced_data_generation_phase` | 2266-2349 | 84 | `data_loading` |
| `_create_failed_benchmark_result` | 2655-2728 | 74 | `execution` |
| `_create_throughput_phase` | 2730-2791 | 62 | `execution` |
| `_setup_fresh_database_phases` | 2916-2968 | 53 | `execution` |
| `_build_execution_phases` | 2989-3040 | 52 | `execution` |
| `_build_execution_metadata` | 3042-3098 | 57 | `execution` |
| `_execute_combined_test` | 3407-3475 | 69 | `execution` |
| `_apply_query_subset` | 3540-3591 | 52 | `execution` |
| `_execute_all_queries` | 3700-3775 | 76 | `execution` |
| `_create_schema_with_tuning` | 3960-4022 | 63 | bridges `tuning` ↔ `data_loading` - **do not extract yet** (see §6) |
| `_execute_schema_statements` | 4024-4099 | 76 | `data_loading` |
| `_execute_tpch_power_test` | 4133-4305 | 173 | `execution` |
| `_execute_generic_power_test` | 4307-4390 | 84 | `execution` |
| `_execute_tpcds_power_test` | 4392-4581 | 190 | `execution` |
| `_execute_tpcds_throughput_test` | 4583-4711 | 129 | `execution` |
| `_execute_tpch_throughput_test` | 4713-4805 | 93 | `execution` |
| `_execute_tpcds_maintenance_test` | 4807-4893 | 87 | `execution` |
| `_execute_tpch_maintenance_test` | 4895-4979 | 85 | `execution` |

Summary: ~700 lines of `result_capture` helpers and ~1,600 lines of `execution` helpers dominate
the file. These are the primary targets for volume reduction.

---

## 2. Proposed target modules

Six modules. Each paragraph describes scope, key belonging symbols (by name), and a
"do-not-extract-yet" note where the cluster still has unresolved coupling.

### 2.1 `connection`

Scope: adapter connection lifecycle - driver isolation checks, DB-API connection creation, pool
interaction, DB existence checks, drop/reuse decisions, and the `PlatformAdapterConnection` /
`_NoCloseProxy` wrappers. Factored as a mixin or helper module that `PlatformAdapter` delegates to.

Key symbols: `DriverIsolationCapability`, `check_isolation_capability`, `from_config`,
`create_connection`, `close_connection`, `get_connection_from_pool`, `test_connection`,
`validate_platform_dependencies`, `require_dependencies`, `get_database_path`,
`check_database_exists`, `check_server_database_exists`, `handle_existing_database`,
`drop_database`, `PlatformAdapterConnection`, `set_query_context`, `commit`, `rollback`,
`close`.

Do-not-extract-yet note: `handle_existing_database` calls `drop_database` and inspects
benchmark metadata; keep it paired with `drop_database` and extract both together.

### 2.2 `execution`

Scope: query dispatch (including `execute`, `execute_query`, and the per-benchmark power /
throughput / maintenance runners), timing capture, cursor handling, dry-run capture buffer,
and the result-builder / failure-result helpers that live adjacent to execution.

Key symbols: `execute_query`, `enable_dry_run`, `disable_dry_run`, `capture_sql`,
`get_captured_sql`, `run_enhanced_benchmark`, `run_benchmark`, `run_power_test`,
`run_throughput_test`, `run_maintenance_test`, `PlatformAdapterCursor`, `fetchall`, `fetchone`,
plus the heavy private helpers `_execute_tpch_power_test`, `_execute_tpcds_power_test`,
`_execute_generic_power_test`, `_execute_tpch_throughput_test`, `_execute_tpcds_throughput_test`,
`_execute_tpch_maintenance_test`, `_execute_tpcds_maintenance_test`, `_execute_combined_test`,
`_execute_all_queries`, `_build_query_result_with_validation`, `_build_query_failure_result`,
`_build_dry_run_result`, `_apply_query_subset`, `_create_failed_benchmark_result`,
`_create_throughput_phase`, `_build_execution_phases`, `_build_execution_metadata`.

Do-not-extract-yet note: `run_enhanced_benchmark` is the top-level orchestrator and must remain
callable as `PlatformAdapter.run_enhanced_benchmark` - extract its helpers into
`execution.py` while keeping `run_enhanced_benchmark`/`run_benchmark` on the facade class.

### 2.3 `data_loading`

Scope: table creation DDL, schema creation orchestration, data load from parquet / csv,
COPY-equivalent operations, external-table registration, manifest persistence, and row-count
probes.

Key symbols: `create_schema`, `load_data`, `create_external_tables`, `upload_manifest`,
`get_table_row_count`, and the heavy helpers `_create_enhanced_data_generation_phase`,
`_create_enhanced_schema_creation_phase`, `_create_enhanced_data_loading_phase`,
`_execute_schema_statements`.

Do-not-extract-yet note: `get_table_row_count` issues a SELECT COUNT(*) - it straddles
`data_loading` and `execution`. Leave it on the facade until `execution` is extracted and we can
decide whether it should live on either module or stay as a convenience pass-through.

### 2.4 `result_capture`

Scope: performance characteristics summary, resource utilization snapshots, query plan capture
and parsing, plan-display UX, and the validation-leg helpers that surface loaded-data integrity.

Key symbols: `display_query_plan_if_enabled`, `get_query_plan`, `get_query_plan_parser`,
`capture_query_plan`, `validate_loaded_data`, `validate_row_counts`, and the two very heavy
private helpers `_collect_resource_utilization` and `_summarize_performance_characteristics`.

Do-not-extract-yet note: `capture_query_plan` calls into `execute_query` (or platform-specific
EXPLAIN paths). Extract `result_capture` **after** `execution` has a stable seam, otherwise the
plan-capture module will have to import back into the facade.

### 2.5 `dialect_translation`

Scope: SQL dialect negotiation, identifier quoting, type mapping, and TPC-base-dialect source
selection. Already partially externalized; this module consolidates the adapter-facing surface.

Key symbols: `dialect`, `translate_sql`, `get_tpc_base_dialect`.

Do-not-extract-yet note: none. Smallest, most cohesive cluster in the file besides `tuning`.

### 2.6 `tuning`

Scope: `apply_platform_optimizations`, per-table tuning DDL, unified tuning configuration,
pragma / session configuration, sorted-ingestion strategy resolution, constraint configuration,
and tuning-metadata persistence / validation. Largely already backed by
`benchbox/platforms/base/tuning_utils.py` and `benchbox/core/tuning/interface.py`.

Key symbols: `apply_table_tunings`, `supports_tuning_type`, `generate_tuning_clause`,
`apply_unified_tuning`, `get_sorted_ingestion_capability`, `resolve_sorted_ingestion_strategy`,
`get_sorted_ingestion_metadata`, `apply_ctas_sort`, `apply_platform_optimizations`,
`apply_constraint_configuration`, `get_effective_tuning_configuration`,
`validate_tuning_configuration_for_platform`, `validate_tuning_configuration`,
`save_tuning_metadata`, `configure_for_benchmark`, plus `_validate_database_tunings` and
`_create_schema_with_tuning` (bridge; see §6).

Do-not-extract-yet note: `_create_schema_with_tuning` bridges `data_loading` and `tuning` -
leave it on the facade for the first slice and move it only after `data_loading` is extracted.

---

## 3. Caller coupling hotspots

`rg -l "from benchbox.platforms.base.adapter import"` returned 17 files: 7 production modules
(`benchbox/platforms/adapter_factory.py`, `benchbox/platforms/clickhouse_cloud.py`,
`benchbox/platforms/starburst.py`, `benchbox/platforms/starrocks/adapter.py`,
`benchbox/platforms/dataframe/benchmark_mixin.py`,
`benchbox/platforms/dataframe/datafusion_df.py`) and 10 test modules under
`tests/unit/platforms/**` and `tests/integration/**`.

`rg "class \w+Adapter\(PlatformAdapter\)"` returned 19 direct subclass definitions in a single
file each (other adapter subclasses inherit through intermediate bases such as
`ClickHouseBaseAdapter`, `SparkBaseAdapter`, `DatabricksAdapter`, etc.). Counting all
`*Adapter`-suffixed classes that redefine public base methods, the methods most frequently
overridden by concrete adapters are:

| Rank | Method | Overrides | Why it is a contract risk |
|------|--------|-----------|----------------------------|
| 1 | `__init__` | 46 | Platform-specific config plumbing; signature must remain `(**config)` |
| 2 | `from_config` | 43 | Every adapter's constructor entry; signature `(cls, config: ConnectionConfig) -> PlatformAdapter` |
| 3 | `get_platform_info` | 41 | Telemetry / result-header contract; return shape is consumed by result builder |
| 4 | `add_cli_arguments` | 39 | CLI extension hook; signature `(cls, parser) -> None` |
| 5 | `create_connection` | 38 | Core abstractmethod; any refactor must keep this name on the facade |
| 6 | `create_schema` | 37 | Core abstractmethod; same |
| 7 | `load_data` | 37 | Core abstractmethod; same |
| 8 | `platform_name` | 35 | Property / method returning the slug - tested widely |
| 9 | `execute_query` | 33 | Query dispatch centerpiece |
| 10 | `configure_for_benchmark` | 32 | Per-benchmark session config hook |

These ten names constitute the API contract the refactor must preserve on
`benchbox.platforms.base.adapter.PlatformAdapter` no matter how internals are split.

Additional overridden-but-lower-traffic methods worth watching: `apply_constraint_configuration`
(27), `apply_platform_optimizations` (26), `supports_tuning_type` (22), `close_connection` (21),
`apply_unified_tuning` (20), `generate_tuning_clause` (19), `get_query_plan` (18),
`apply_table_tunings` (18), `drop_database` (17), `check_server_database_exists` (16).

---

## 4. Proposed slice order

Each slice creates a new module under `benchbox/platforms/base/` (or augments an existing file
like `tuning_utils.py`), leaves `PlatformAdapter` as a facade that imports and delegates, and
must ship with the listed tests green.

### Slice 1 - `dialect_translation`

- Moves: `dialect`, `translate_sql`, `get_tpc_base_dialect`.
- Creates: `benchbox/platforms/base/dialect_translation.py` with a `DialectTranslationMixin`.
- Tests: `tests/unit/platforms/test_base_adapter.py`, any `tests/unit/**/test_*dialect*.py`.
- Must preserve: the three methods as attributes of `PlatformAdapter` with unchanged signatures
  and return types; module path `benchbox.platforms.base.adapter` continues to export them.

### Slice 2 - `tuning`

- Moves: all tuning / constraint / sorted-ingestion / CTAS-sort methods from §2.6 **except**
  `_create_schema_with_tuning` (see §6); also moves `_validate_database_tunings`.
- Creates: `benchbox/platforms/base/tuning.py` (distinct from `tuning_utils.py`) or extends
  `tuning_utils.py` with a `TuningMixin`.
- Tests: `tests/unit/platforms/test_adapter_validation_consistency.py`,
  tests exercising `apply_platform_optimizations` and `apply_constraint_configuration`,
  `tests/unit/platforms/test_base_adapter.py` tuning sections.
- Must preserve: every method name on `PlatformAdapter`, the `TuningType` /
  `UnifiedTuningConfiguration` import surface, the `configure_for_benchmark(...)` signature.

### Slice 3 - `connection`

- Moves: everything in §2.1, including `DriverIsolationCapability`,
  `check_isolation_capability`, the `PlatformAdapterConnection` class, and `_NoCloseProxy`.
- Creates: `benchbox/platforms/base/connection.py`.
- Tests: `tests/unit/platforms/test_base_adapter_database_management.py`,
  `tests/unit/platforms/test_platform_driver_runtime_contract.py`,
  `tests/integration/test_platform_driver_version_matrix.py`.
- Must preserve: `from benchbox.platforms.base.adapter import PlatformAdapterConnection,
  DriverIsolationCapability, check_isolation_capability` must keep working (re-export).
  `create_connection` and `close_connection` remain on `PlatformAdapter`. `from_config`
  signature stays `(cls, config: ConnectionConfig) -> PlatformAdapter`.

### Slice 4 - `data_loading`

- Moves: `create_schema`, `load_data`, `create_external_tables`, `upload_manifest`, and the
  `_create_enhanced_*` phase helpers plus `_execute_schema_statements`.
- Creates: `benchbox/platforms/base/data_loading.py` (augments the existing
  `data_loading.py` in the same package).
- Tests: tests under `tests/unit/platforms/base/` touching schema/load paths;
  `tests/unit/platforms/test_base_adapter_concrete.py`.
- Must preserve: `create_schema`, `load_data`, `create_external_tables`, `upload_manifest`
  abstract signatures; `get_table_row_count` stays on facade for now.

### Slice 5 - `result_capture`

- Moves: plan-capture methods (`display_query_plan_if_enabled`, `get_query_plan`,
  `get_query_plan_parser`, `capture_query_plan`), `validate_loaded_data`, `validate_row_counts`,
  and the two large helpers `_collect_resource_utilization` and
  `_summarize_performance_characteristics`.
- Creates: `benchbox/platforms/base/result_capture.py`.
- Tests: `tests/unit/platforms/test_plan_capture_errors.py`,
  `tests/unit/platforms/test_adapter_validation_consistency.py`.
- Must preserve: `get_query_plan`, `capture_query_plan`, `get_query_plan_parser` method names;
  `capture_query_plan` return shape consumed by result builder.

### Slice 6 - `execution` (last)

- Moves: everything in §2.2 except `run_enhanced_benchmark` / `run_benchmark`, which stay on
  the facade but delegate into `execution` helpers.
- Creates: `benchbox/platforms/base/execution.py`.
- Tests: nearly every test under `tests/unit/platforms/` and relevant integration tests; run
  the fast marker plus targeted slow-marked benchmark orchestration tests.
- Must preserve: `execute_query`, `run_enhanced_benchmark`, `run_benchmark`, `run_power_test`,
  `run_throughput_test`, `run_maintenance_test`, `PlatformAdapterCursor`, dry-run capture API
  (`enable_dry_run`, `disable_dry_run`, `capture_sql`, `get_captured_sql`).

---

## 5. Do-not-extract-yet exceptions

These look like they belong in a target module but move only in a later pass:

- `run_enhanced_benchmark` and `run_benchmark` - belong conceptually in `execution`, but they
  are the public orchestration entrypoints used by CLI and MCP. Keep them on
  `PlatformAdapter` (the facade) even after Slice 6; delegate their bodies into `execution`
  helpers. Moving their *names* risks breaking importers and test-patching.
- `_create_schema_with_tuning` - bridges `data_loading` (DDL emission) and `tuning` (tuning
  application). Leave on the facade until both Slice 2 and Slice 4 have landed, then move it
  into whichever module owns the call-graph root for schema DDL.
- `get_table_row_count` - issues SQL but is called by data-loading validation paths. Defer
  until Slice 6 determines whether it should live on `execution` or `data_loading`.
- `get_platform_info` - looks like metadata, but its return shape is consumed by result-builder
  code paths that assume it is an attribute of `PlatformAdapter`. Keep on the facade.
- `validate_platform_capabilities` - pre-flight check that composes calls into multiple
  mixins; keep on the facade as an orchestration method.
- `_collect_resource_utilization` / `_summarize_performance_characteristics` - volume-wise
  they dominate `result_capture`, but both reach into adapter state (e.g. `self._connection`,
  `self._tunings`) heavily. Extract only when `connection` and `tuning` mixins have stable
  seams.

---

## 6. Must-preserve contract

The following cannot change during the refactor:

- Class name `PlatformAdapter`, importable as
  `from benchbox.platforms.base.adapter import PlatformAdapter`.
- Module path `benchbox.platforms.base.adapter` remains a real module (not a stub) and continues
  to export every name currently exported: `PlatformAdapter`, `PlatformAdapterConnection`,
  `PlatformAdapterCursor`, `DriverIsolationCapability`, `check_isolation_capability`,
  `EnhancedBenchmarkResults` (alias of `BenchmarkResults`).
- Backward-compat re-export `EnhancedBenchmarkResults = BenchmarkResults` stays at module top
  level.
- Every public method listed in §1.2 remains callable on a `PlatformAdapter` instance / class
  with its current signature. In particular the ten contract methods from §3 (`__init__`,
  `from_config`, `get_platform_info`, `add_cli_arguments`, `create_connection`, `create_schema`,
  `load_data`, `platform_name`, `execute_query`, `configure_for_benchmark`) keep their exact
  signatures.
- `PlatformAdapterConnection.execute`, `.commit`, `.rollback`, `.close`, `.set_query_context`
  signatures unchanged.
- `PlatformAdapterCursor.fetchall` / `.fetchone` signatures unchanged.
- Abstract-method set is unchanged: subclasses that currently override `create_connection`,
  `create_schema`, `load_data`, `execute_query`, etc. must keep working without edits.
- Test invariants: every test under `tests/unit/platforms/` and the adapter-touching
  integration tests continue to pass under `uv run -- python -m pytest -m fast -q` and under
  the full slow-tier run. No test file should need import-path edits as part of a refactor
  slice - add re-exports instead.
- Driver-isolation capability discovery (`adapter_class.driver_isolation_capability` and
  `check_isolation_capability(adapter_class, ...)`) continues to work through the existing
  import path in `benchbox/platforms/adapter_factory.py`.

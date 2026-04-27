---
title: Duplication Residuals
status: living-document
owner: quality-consolidate-duplicate-code-clusters
last_reviewed: 2026-04-14 (quality-extract-throughput-runner)
---

# Duplication Residuals

This document catalogues duplicate-code clusters surfaced by
`pylint --disable=all --enable=duplicate-code --min-similarity-lines=15 benchbox/`
that have been **intentionally left unconsolidated**, along with the rationale.
New clusters should be added here only after confirming that extraction would
collapse meaningful platform differences or require cross-boundary refactors
owned by a different TODO.

The full ranked inventory lives at
[`duplication-inventory.csv`](./duplication-inventory.csv).

| Snapshot | Cluster pairs (≥15-line, full benchbox/) | Top cluster size |
|---|---|---|
| w1 baseline | ~110 | 632 lines (lakesail_df ↔ pyspark_df) |
| **w6 (post-w5)** | **102** | 334 lines (lakesail_df ↔ pyspark_df) |

The 102-pair count remains above the original ≤50 stretch goal. The
remaining clusters fall into two buckets, both blocked by larger
refactors that the source TODO scope_limit explicitly excluded:

1. **Cross-package refactors that need a shared abstraction layer**
   (transaction_primitives ↔ write_primitives benchmark+operations bases,
   expression_family ↔ pandas_family DataFrame base, throughput_test
   result-model alignment) - see R-06, R-08, R-09.
2. **Intentional forks/mirrors** (lakesail ↔ pyspark, tpch ↔ tpch_skew) -
   see R-03, R-05.

w5 cleared the 9 cluster pairs that admitted clean per-cluster
extraction (≤4 hours each). The remaining clusters need either a
dedicated multi-day TODO or are accepted residuals.

## Consolidation Log

| Cluster | Status | Helper | Commit |
|---|---|---|---|
| Azure fabric_spark ↔ synapse_spark credential/token (73 lines) | Partially consolidated | `benchbox/platforms/azure/_credentials.py` (`AzureTokenProvider`) | `68b0e1556` |
| GCP dataproc ↔ dataproc_serverless GCS path parsing (13 lines) | Consolidated | `benchbox/platforms/gcp/_gcs_path.py` (`parse_gcs_staging_dir`) | `3bc58b473` |
| Platforms base models ↔ core results models (97 lines) | Consolidated | `benchbox/platforms/base/models.py` re-exports from `benchbox/core/results/models.py` | `af5ab0623` |
| DataFrame expression/pandas family result dicts (4 sites) | Consolidated | `benchbox/platforms/dataframe/_result_helpers.py` | `610c5a02a` |
| .tbl compression consistency check (ssb + tpcdi) | Consolidated | `benchbox/utils/file_format.py::validate_tbl_compression_consistency` | `d46f8fea8` |
| Spark query-plan capture (lakesail + spark) | Consolidated | `benchbox/platforms/_spark_helpers.py::get_spark_query_plan` | `97efc8d58` |
| TPC-H ↔ TPC-DS ↔ Data Vault `Table` CREATE TABLE logic (75 lines × 3) | Consolidated | `benchbox/core/schema_primitives.py::BaseSchemaTable` | `eef4b362b` |
| Azure fabric_spark ↔ synapse_spark `_execute_statement`/`_wait_for_statement` (73 lines) | Consolidated | `benchbox/platforms/azure/_livy_mixin.py::LivyStatementMixin` | `f47a1855c` |
| Presto ↔ Trino `_escape_insert_value`/`_is_date_value`/`_normalize_existing_files` (21 lines) | Consolidated | `benchbox/platforms/presto_trino_utils.py` module helpers | `36c2e6d09` |
| Presto ↔ Trino `_load_file_batches` (30 lines) | Consolidated | `benchbox/platforms/presto_trino_utils.py::load_file_batches` | `aa14511a6` |
| Presto ↔ Trino `_resolve_data_files` (12 lines) | Consolidated | `benchbox/platforms/presto_trino_utils.py::resolve_data_files` | `d5cf543a2` |
| TPC-H ↔ TPC-DS concurrent executor + metrics (77 lines) | Consolidated | `benchbox/core/throughput/runner.py::StreamRunner` | `75e178fc6` |

## Deferred Residuals

### R-01: Databend ↔ Databricks `apply_platform_optimizations` dispatch

- **Pattern**: TODO originally flagged this as a ~20-line cluster around
  `apply_unified_tuning` → `apply_platform_optimizations` / `apply_table_tunings`
  dispatch.
- **Reality at 15-line threshold**: No direct Databend↔Databricks match. The
  dispatch bodies are 10-12 lines and diverge in intent: Databend logs
  "pre-optimized for analytics" (no-op informational), Databricks logs "stored
  for Spark session and Delta Lake management" (placeholder for future
  session-level config). The engines share no optimization semantics.
- **Rationale**: Extracting a shared base method would collapse a meaningful
  distinction (one platform genuinely has nothing to apply, the other defers
  to session config). Per anti-pattern in the source TODO: *"DO NOT extract an
  abstraction that collapses meaningful platform differences - false DRY hurts
  more than duplication."*
- **Status**: Deferred; no action recommended.

### R-02: Redshift ↔ Databend ↔ Databricks ↔ Snowflake query-validate+log wrapper

- **Pattern**: ~34-37 line block around `QueryValidator` invocation + verbose
  logging + `_build_query_result_with_validation` call.
- **Size**: `redshift.py` ↔ `databricks/adapter.py` 37 lines (1 occurrence);
  `redshift.py` ↔ `databend/adapter.py` 37 lines; `redshift.py` ↔
  `snowflake.py` 34 lines.
- **Rationale for deferral**: The natural destination is `benchbox/platforms/
  base/adapter.py` as a sibling to the existing
  `_build_query_result_with_validation` helper. That file is explicitly
  off-limits for the duplication TODO per its `scope_limit.do_not_modify`
  (owned by `quality-refactor-adapter-base-into-cohesive-modules`).
- **Recommended owner**: fold the extraction into the adapter-base refactor,
  specifically the "execution mixin" module split. Add a
  `_validate_row_count_and_log()` helper on the base adapter and migrate all
  four call sites as part of that TODO.
- **Status**: Deferred to adapter-base refactor.

### R-03: LakeSail ↔ PySpark DataFrame family (632 lines)

- **Pattern**: Both DataFrame families implement the same Spark DSL surface
  area via `pyspark.sql.functions` compatibility.
- **Rationale**: LakeSail is a drop-in PySpark replacement; the API surface
  deliberately mirrors PySpark, and consolidation would require building a
  shared module that both families import from - which reintroduces a
  single-point-of-failure for dialect-compatible code paths that the two
  implementations are designed to exercise independently.
- **Status**: Accepted; intrinsic to the PySpark-compat design.

### R-04: Presto ↔ Trino adapter (78 lines)

- **Pattern**: Presto and Trino share ancestry; JDBC connection + SQL dialect
  paths remain near-identical.
- **Rationale**: Already scoped to the adapter-base refactor - Presto and
  Trino are on the list of adapters expected to migrate to the JDBC mixin
  once the base refactor lands. Extracting a third location now would be
  rework.
- **Status**: Deferred to adapter-base refactor.

### R-05: TPC-H ↔ TPC-H skew generator (108 lines)

- **Pattern**: Data generators share pre- and post-generation scaffolding.
- **Rationale**: TPC-H skew is a research benchmark that intentionally forks
  the canonical TPC-H generator so it can evolve independently. Consolidating
  now risks entangling an experimental variant with the compliance-critical
  canonical generator.
- **Status**: Accepted; fork is intentional.

### R-06: TPC-DS ↔ TPC-H throughput test harness (77 lines) - RESOLVED

- **Pattern**: Shared concurrent-stream executor + metrics calculation inside
  `throughput_test.py` `run()` methods.
- **Resolution**: Extracted to `benchbox/core/throughput/` package
  (`quality-extract-throughput-runner` TODO). `ThroughputStreamResult` /
  `ThroughputResult` base dataclasses live in `core.throughput.result`;
  `StreamRunner.execute()` and `StreamRunner.compute_metrics()` live in
  `core.throughput.runner`. Both spec modules carry backward-compat aliases
  (`TPCHThroughputStreamResult`, `TPCDSThroughputStreamResult`) and thin
  `ThroughputResult` subclasses adding their spec-specific `config` field.
  Success-rate gating is spec-local to preserve TPC-H's configurable
  `min_success_rate` and TPC-DS's 70% contract.
- **Pylint verification**: `pylint R0801` count at `--min-similarity-lines=15`
  over both throughput_test modules = **0** (was 1 cluster, 77 lines).
- **Status**: Resolved 2026-04-14.

### R-07: AI primitives ↔ metadata primitives query catalogs (75 lines)

- **Pattern**: Two catalog classes with identical `__init__`, category-index
  building, and getter protocol.
- **Rationale**: Candidate for extraction into a shared
  `BaseQueryCatalogMixin` (already partially used per docstring references).
  Blocked behind Protocol migration work in
  `quality-migrate-unified-frame-any-to-protocol`, which clarifies catalog
  typing first.
- **Status**: Deferred to Protocol migration TODO.

### R-08: transaction_primitives ↔ write_primitives benchmark + operations (3 clusters: 101, 93, 71 lines) - RESOLVED

- **Pattern**: Both benchmark families share near-identical
  `Benchmark` and `Operations` base classes - operation registry, dispatch,
  reporting scaffolding - but with type signatures parameterized over
  benchmark-specific result/operation types.
- **Resolution**: Extracted to `benchbox/core/transactional/` package
  (`quality-extract-transactional-benchmark-base` TODO).
  `OperationsRegistryBase[OperationT]` lives in `core.transactional.operations_registry_base`;
  `TransactionalBenchmarkBase[ResultT]` lives in `core.transactional.benchmark_base`.
  Both spec modules retain spec-specific `execute_operation`, `setup`, `is_setup`,
  schema methods, and `OperationResult` dataclasses.  `_prepare_operation` helper
  on the base eliminates the shared `execute_operation` preamble (C1 cluster).
- **Pylint verification**: `pylint R0801` count at `--min-similarity-lines=15`
  over all four target files = **0** (was 3 clusters, 311 lines total).
- **Status**: Resolved 2026-04-14.

### R-09: expression_family ↔ pandas_family DataFrame adapters (79 lines)

- **Pattern**: Two DataFrame family base classes both implement
  `_run_query_phase`, `_load_table_data`, and `_persist_results` with
  the same control flow but different per-backend operations (Polars
  Expression API vs Pandas/Modin/cuDF).
- **Inspected in w5**: w5 already extracted the per-call result-dict
  builders (`_result_helpers.py`). The remaining 79-line cluster covers
  the orchestration shells. Extracting them needs a shared
  `DataFrameFamilyBase` ABC with backend-specific hooks for "compute",
  "scan", and "select-like" operations - overlaps with the broader
  protocol migration in `quality-migrate-unified-frame-any-to-protocol`.
- **Status**: Deferred to Protocol migration TODO.

## Next Review

After the following TODOs land, re-run the inventory:
- `quality-refactor-adapter-base-into-cohesive-modules` → resolves R-02, R-04
- `quality-migrate-unified-frame-any-to-protocol` → resolves R-07, R-09

R-06 and R-08 are already resolved (see above).

Realistic post-refactor target: 30-40 cluster pairs across `benchbox/`,
mostly intentional R-03 / R-05 forks.

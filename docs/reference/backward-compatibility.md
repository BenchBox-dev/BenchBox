<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Backward Compatibility Registry

This page lists the backward-compatibility surfaces BenchBox keeps, and the ones it has removed.

## Release Stage Policy

BenchBox is currently in **beta**.

BenchBox uses `MAJOR.MINOR.PATCH` release numbers as a practical guide rather
than a promise of strict semantic versioning before 1.0:

- A **major** release can change compatibility or significantly change the
  project's scope.
- A **minor** release can add compatible features or substantially expand
  existing capabilities.
- A **patch** release contains fixes or documentation changes. Before 1.0, a
  fix can still require a migration when preserving the old behavior would be
  misleading or unsafe.

The release notes and migration guidance remain the authority for a specific
version. The policy below defines the compatibility expectations for each
development stage.

- Alpha:
  - Prioritize canonical API cleanup over compatibility.
  - Breaking changes are allowed with a direct migration.
  - Shims should be short-lived and removed quickly.
- Beta:
  - Minimize breaking public API changes.
  - New shims require a target removal version and a migration path.
  - Deprecation windows should span at least one beta cycle.
- GA (1.x):
  - Preserve public API compatibility by default.
  - Breaking changes require a documented migration guide and major-version policy alignment.
  - Compatibility shims must include sunset criteria and timeline.

## Scope

Public surface tiers and support status vocabulary live in
[`public-contracts.md`](public-contracts.md). This registry is narrower: it
tracks compatibility shims and deprecated/internal lifecycle surfaces that keep
old behavior working.

A code element belongs in this registry if it keeps old behavior working, including:
- Legacy parameter or field handling
- Backward-compatible aliases or re-exports
- Legacy schema or format handling
- Compatibility fallbacks for prior API or result shapes

## Lifecycle States

- `active`: currently retained for compatibility.
- `deprecate`: retained temporarily and scheduled for removal.
- `remove`: approved for removal in the next compatible breaking window.

## Current Inventory

| Location | Compatibility Marker | Status | Target Removal | Rationale |
| --- | --- | --- | --- | --- |
| `benchbox/base.py` | `BaseBenchmark.create_enhanced_benchmark_result()` continues accepting legacy kwargs (`table_statistics`, `data_loading_time`, `phases`, `execution_metadata`) while delegating to shared result factory | active | Beta compatibility review | Preserve stable result-shape behavior for adapters and wrapper benchmarks while runtime internals are unified |
| `benchbox/core/base_benchmark.py` | Deprecated internal base class retained after `datavault` and `tpcds_obt` migrated to `benchbox.base.BaseBenchmark`; no remaining production implementation imports it | deprecate | Deletion-only compatibility item after the beta review window and any remaining internal imports are migrated | Keep the old internal import path observable until its explicit removal gate; it is not a public extension path for new benchmark families |
| `benchbox/cli/benchmark_hooks.py`, `benchbox/cli/platform_hooks.py` | Thin re-export shims for the benchmark/platform CLI-option hook registries relocated to `benchbox.core.hooks.benchmark_hooks` / `benchbox.core.hooks.platform_hooks` (fixes a `core`/`platforms` -> `cli` layering inversion) | active | Beta compatibility review; these paths are internal-only (not listed in `public-contracts.md`), so the shim is a courtesy rather than a guaranteed compatibility window | Avoid breaking any internal or external caller still importing the old `benchbox.cli.*` path while `benchbox.core`/`benchbox.platforms` are updated to import the registries directly |

## Removed Compatibility Surfaces

These compatibility shims were removed during the alpha API cleanup. Use the
canonical replacements:

- Platform adapter naming: use `FabricWarehouseAdapter` (and platform key
  `fabric-warehouse`) instead of the removed `MicrosoftFabricAdapter` alias.
- Data loading source contract: use `benchmark.tables`,
  `benchmark._impl.tables`, or `_datagen_manifest.json` (v1/v2). The
  `benchmark.get_tables()` loading fallback (`LegacyGetTablesSource`) was
  removed.

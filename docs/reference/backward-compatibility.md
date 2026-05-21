<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Backward Compatibility Registry

This document is the canonical process and registry for tracking backward-compatibility surfaces in BenchBox.

## Release Stage Policy

BenchBox is currently in **beta**.

- Alpha:
  - Prioritize canonical API cleanup over compatibility.
  - Breaking changes are allowed with direct migration in the same PR.
  - Shims should be short-lived and removed quickly.
- Beta:
  - Minimize breaking public API changes.
  - New shims require explicit owner, target removal version, and migration path.
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

## Registry Process

- Every new compatibility shim must add or update a row in this registry in the same PR.
- Every removal must delete or update the corresponding row in the same PR.
- Every row must include:
  - `Location`
  - `Compatibility Marker`
  - `Status` (`active`, `deprecate`, `remove`)
  - `Target Removal`
  - `Rationale`
  - `Owner`

## Lifecycle States

- `active`: currently retained for compatibility.
- `deprecate`: retained temporarily and scheduled for removal.
- `remove`: approved for removal in the next compatible breaking window.

## Update Procedure

1. Run scan:

```bash
rg -n "backward compatibility|Backward compatibility|legacy compatibility|for backward compatibility|Legacy|backward-compatible|Backward-compatible" benchbox
```

2. Reconcile scan output with registry entries.
3. Add missing rows for newly introduced shims.
4. Remove or update rows for shims removed in the PR.
5. Validate:

```bash
make ci-lint
make ci-test
```

## Current Inventory

Maintain live rows below. Do not leave compatibility changes untracked.

| Location | Compatibility Marker | Status | Target Removal | Rationale | Owner |
| --- | --- | --- | --- | --- | --- |
| `benchbox/base.py` | `BaseBenchmark.create_enhanced_benchmark_result()` continues accepting legacy kwargs (`table_statistics`, `data_loading_time`, `phases`, `execution_metadata`) while delegating to shared result factory | active | Beta compatibility review | Preserve stable result-shape behavior for adapters and wrapper benchmarks while runtime internals are unified | core-runtime |
| `benchbox/core/base_benchmark.py` | Internal base class retained for existing benchmarks, with result creation delegated to shared result factory | deprecate | After all core benchmarks migrate to `benchbox.base.BaseBenchmark` | Avoid breaking remaining internal benchmark classes during staged runtime harmonization | core-runtime |

## Runtime Harmonization Notes (2026-02-26)

- Loader benchmark-set definitions are now registry-backed (`list_loader_benchmark_ids` + `get_core_benchmark_class_name`) to prevent loader/registry drift.
- `transaction_primitives` is now part of the core loader-supported benchmark set; stale loader-only entries were removed.
- Runtime contract coverage now runs against loader benchmark IDs sourced from the shared registry contract.
- Cleanup boundary for this workstream:
  - Keep top-level wrapper classes in `benchbox/*.py` as-is.
  - Keep `benchbox.core.base_benchmark.BaseBenchmark` until a dedicated migration/removal item is approved.

## Final Removal Report (2026-02-18)

### Before/After Inventory Diff

- Baseline at kickoff: 89 compatibility markers tracked (67 active, 22 deprecate).
- Current active compatibility registry rows: 0.
- Final status: all registry-tracked compatibility shims removed for alpha-stage API cleanup.

### Final Removals In This Closing Wave

- Removed platform alias export: `MicrosoftFabricAdapter` (canonical: `FabricWarehouseAdapter`).
- Removed legacy data loading provider: `LegacyGetTablesSource` and `legacy_get_tables` source path.
- Removed compatibility-only tests asserting `benchmark.get_tables()` loading path in SQLite adapter coverage.

### Canonical Replacement Paths

- Platform adapter naming:
  - Use `FabricWarehouseAdapter` (and platform key `fabric-warehouse`) instead of alias names.
- Data loading source contract:
  - Use `benchmark.tables`, `benchmark._impl.tables`, or `_datagen_manifest.json` (v1/v2).
  - Do not rely on `benchmark.get_tables()` compatibility fallback.

### Verification Summary

- Registry row scan (`rg -n '^\\| \\`benchbox/' docs/reference/backward-compatibility.md`): no active benchbox rows.
- Compatibility alias/shim scan for final-wave removals:
  - `MicrosoftFabricAdapter`: no matches.
  - `LegacyGetTablesSource` / `legacy_get_tables`: no matches.
- CI fast profile (`make ci-test`): passing.
- CI lint (`make ci-lint`): still blocked by pre-existing global `ty` warning backlog outside this TODO's closing-wave diffs.

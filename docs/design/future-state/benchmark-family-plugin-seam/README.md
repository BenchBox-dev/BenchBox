<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Benchmark Family Plugin Seam Future State

```{tags} contributor, architecture
```

Related TODO: `benchmark-api-and-core-boundary-cleanup`

## Decision

Benchmark family logic should move behind an explicit family-plugin seam before
any broad `benchbox/core` split. The seam is a design boundary first, not a
mechanical package move: public wrappers and the CLI keep their current user
contracts while internal family implementations converge on a shared interface.

## Current Surface Classification

| Surface | Tier | Current role |
|---|---|---|
| Top-level wrappers such as `benchbox.TPCH(...)` | `beta-public` | User-facing convenience facades with direct tests. |
| `benchbox.base.BaseBenchmark` | `beta-public` | Public base for wrappers and orchestration helpers. |
| `BaseBenchmark.run_with_platform()` | `beta-public` | Programmatic adapter execution hook used by CLI-adjacent tools and MCP. |
| `benchbox.core.benchmark_loader` | `internal` | Registry-backed runtime loader for core orchestration. |
| `benchbox.core.base_benchmark.BaseBenchmark` | `deprecated` | Internal compatibility base retained for `datavault` and `tpcds_obt`. |
| Benchmark registry metadata | `beta-public` | Source of truth for benchmark identity, discovery, public/internal surface, and class-name mappings. |

## Target Seam

A benchmark family plugin owns:

- benchmark metadata fields needed for discovery;
- the core benchmark class and default constructor policy;
- data generation and manifest behavior for its family;
- query catalog, query IDs, streams or maintenance phases when relevant;
- optional DataFrame query implementations for the same family;
- family-specific scale validation beyond registry defaults;
- result metadata extensions that are explicitly shared through the result
  schema policy.

The shared runtime owns:

- platform adapter execution;
- result bundle construction and schema-version policy;
- validation mode selection and cross-platform comparison;
- lifecycle phase orchestration;
- registry publication and public/internal surface filtering.

## Interface Shape

The first interface should be small and registry-backed:

| Method or field | Purpose |
|---|---|
| `benchmark_id` | Stable registry key. |
| `core_class` | Class used by the internal loader. |
| `public_class_name` | Optional top-level wrapper facade class. |
| `surface` | Public or internal discovery visibility. |
| `default_scale(scale_factor)` | Scale validation and default constructor policy. |
| `create(config, system_profile)` | Construct a family instance without CLI imports. |
| `phases()` | Declare supported generate/load/execute/maintenance phases. |
| `result_metadata()` | Family-owned result fields that are accepted by schema policy. |

This interface should be introduced with one pilot family before extraction.
TPC-H or JoinOrder are better pilots than TPC-DS because TPC-DS has more
compliance and stream-specific behavior that would obscure the seam.

## Non-Goals

- Removing top-level wrapper facades.
- Making `benchbox.core.benchmark_loader` public.
- Creating a third benchmark base class.
- Moving all benchmark directories in one PR.
- Changing result bundle shape as part of the seam definition.

## Migration Gates

1. Keep wrapper facade tests green, or add a compatibility registry row plus a
   migration path.
2. Keep registry, public discovery, top-level facade, and loader counts under a
   focused drift test.
3. Keep core API files free of concrete platform adapter imports.
4. Migrate `datavault` and `tpcds_obt` off
   `benchbox.core.base_benchmark.BaseBenchmark` before removing that class.
5. Land one pilot family through the seam before any package-level split.

## Rejected Alternatives

| Alternative | Reason rejected |
|---|---|
| Remove wrapper facades now | Existing tests assert wrapper behavior and users have documented imports. |
| Promote the loader as public API | The loader has constructor heuristics and internal fallback behavior that should not become an external contract. |
| Add a new base class | This would increase base-class ambiguity instead of resolving it. |
| Mechanically split `benchbox/core` | File movement without a dependency-direction boundary would only relocate drift. |

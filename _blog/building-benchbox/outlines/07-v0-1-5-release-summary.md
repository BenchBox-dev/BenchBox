---
title: "BenchBox v0.1.5: release summary"
series: building-benchbox
post_number: 7
type: release-notes
tags: [benchbox, release, changelog, textcharts, table-formats, test-quality]
status: OUTLINE
---

# Outline: BenchBox v0.1.5 release summary

---

## Theme

v0.1.5 is about **separation and cleanup**: pulling the chart library out of the monorepo,
landing real table format loading, and replacing hollow test coverage with tests that catch
actual bugs.

The textcharts extraction (covered in depth in post #6) ships in this release as a consumer-
facing change: BenchBox now depends on textcharts as a standalone package. The test quality
overhaul is the less visible but equally important half: 13 coverage-theater files deleted,
mutation testing added, and pytest lanes restructured from timing heuristics to explicit markers.

---

## TL;DR (draft bullets)

- **Textcharts is now a standalone library**. All 15 ASCII chart types extracted into
  `packages/textcharts/` with zero BenchBox dependencies. BenchBox imports through compatibility
  shims; existing code is unaffected.
- **Open table format loading** lands for Delta Lake, Iceberg, and Hudi across Spark, cloud SQL,
  Snowflake, and ClickHouse adapters.
- Format capability registry expanded to cover Hudi, Presto/Trino, BigQuery, Redshift, and
  cloud lakehouse platforms. Inaccurate registrations removed.
- **Test quality overhaul**: 13 hollow test files deleted, replaced with behavior-verifying
  adapter tests and mutation testing via mutmut.
- Pytest lanes converted from implicit timing heuristics to explicit source markers.
- CLI recursive import fix, CoffeeShop SA2 query correction, textcharts v0.1.2 API migration.

---

## At a glance table

| Area | What changed in v0.1.5 | Why it matters |
| --- | --- | --- |
| Textcharts extraction | 15 chart types in standalone package; BenchBox depends via path dep | Charts are reusable outside BenchBox; coupling removed |
| Table format loading | Delta/Iceberg/Hudi load support on Spark, cloud SQL, Snowflake, ClickHouse | Benchmarks can load data in native table formats |
| Format registry | Capabilities registered for 10+ additional platforms; inaccurate entries removed | Registry reflects what actually works, not aspirational support |
| Test quality | 13 hollow files deleted, mutation testing added, 150 assertions strengthened | Tests catch real bugs instead of inflating coverage numbers |
| Pytest lanes | Explicit source markers replace timing-based bucketing | Lane assignment is deterministic and auditable |
| Fixes | CLI recursive import, CoffeeShop query, textcharts API migration | Fewer startup failures, correct query results |

---

## Section breakdown

### 1. Textcharts standalone extraction (~350 words)

Post #6 told the extraction story in detail. This section covers what shipped and what it means
for BenchBox users.

**What changed**: `packages/textcharts/` is a standalone Python package with its own
`pyproject.toml`, README, and test suite. BenchBox depends on it as a path dependency. All 15
chart types (`BarChart`, `Histogram`, `Heatmap`, etc.) are exported with clean standalone names
alongside BenchBox-compatible aliases (`ASCIIBarChart`, `ASCIIQueryHistogram`).

**What users see**: nothing breaks. Existing imports resolve through compatibility shims. The
`benchbox visualize` command and MCP chart tools work exactly as before.

**What changed internally**:
- ~316 pure-rendering tests migrated to the textcharts test suite
- Shim import smoke tests retained in BenchBox to verify re-export paths
- `ASCII*`-prefixed class names renamed in 10 source and test files
- 3 deprecated factory imports removed
- Golden snapshots regenerated for textcharts v0.1.2 API changes
- Magic numbers extracted to named constants in visualization modules

**Why this matters**: textcharts can now be used independently of BenchBox. The extraction also
forced API cleanup (covered in post #6) that we wouldn't have done otherwise.

Reference: post #6 ("Extracting textcharts from BenchBox") for the full extraction narrative.

### 2. Open table format loading (~300 words)

**Before**: BenchBox could generate data in table format layouts (delta-sorted, iceberg-sorted
from v0.1.4), but adapter-level `load_table` implementations were incomplete. The format
capability registry listed platforms that didn't actually have loading code.

**Now**: runtime loading support for Delta Lake, Iceberg, and Hudi is implemented across:
- Spark mixin platforms (EMR, Dataproc, Glue, Fabric Spark, Synapse Spark)
- Cloud SQL platforms (Snowflake, ClickHouse)
- Format support is gated on adapter configuration, so platforms without loading code don't
  advertise capabilities they can't deliver.

The registry was also cleaned up: LakeSail removed from delta/iceberg/hudi capabilities,
platform display names normalized to match registry keys, and platforms without loading code
removed from format registrations entirely.

### 3. Test suite quality overhaul (~350 words)

This is the release where we addressed coverage theater. The test suite looked healthy by line
coverage metrics, but many tests were hollow: `assert result is not None`, `isinstance` checks,
`MagicMock` objects that never verified behavior.

**What we deleted**: 13 test files that existed primarily to inflate coverage numbers. These
files tested that constructors returned non-None values and that objects had expected types,
but never exercised actual behavior.

**What we added**:
- Behavior-verifying tests for DuckDB, SQLite, and DataFusion adapters (real file-based
  operations, not mocked)
- Real file-based credential tests replacing mock-only paths
- Mutation testing via mutmut targeting 5 critical modules
- 150 `is-not-None` assertions rewritten as behavioral checks across 5 files
- `isinstance` assertions replaced with behavioral checks in 3 files
- `MagicMock` replaced with `SimpleNamespace` for attribute-only test objects

Coverage threshold changed from per-file enforcement to suite-wide 60%.

### 4. Pytest lane restructure (~200 words)

**Before**: test lanes (fast, medium, slow) were assigned based on measured execution timings.
This meant lane assignment could shift between machines or after unrelated code changes.

**Now**: lanes use explicit source markers. Each test file declares its lane. Rebucketing was
done from measured timings, but the assignment is now static and auditable.

Additional changes:
- Fast lane restored to lightweight tests only
- Stress tests explicitly serialized
- Cloud adapter tests re-laned to `slow+cloud_import`
- pytest-xdist safety documented and worker title patch tightened

### 5. Quick upgrade checks (~150 words)

Standard checks matching v0.1.2/0.1.3/0.1.4 template:
1. `benchbox --version`
2. Smoke run
3. Confirm chart output still renders (textcharts shims working)
4. If using table format loading: verify format support on target platform

### 6. Other fixes (brief)

- CLI recursive import in benchmarks module (caused `RecursionError` on startup)
- CoffeeShop SA2 query: `group_by` column name corrected (`'name'` -> `'product_name'`)
- Chart subtitle migrated from metadata dict to plain string
- Verbose logging config extracted from `run.py` to `cli/verbose_logging.py`

---

## Word count target

~1,400 words (consistent with v0.1.2, v0.1.3, and v0.1.4 length)

---

## Post structure (following release post template)

```
# BenchBox v0.1.5: release summary

{one-sentence intro}

![{image placeholder}]

## TL;DR
## At a glance
## What changed for typical workflows
  ### 1. Textcharts is now a standalone library
  ### 2. Open table format loading
  ### 3. Test suite quality overhaul
## Major additions
## Major fixes and stability work
## Changed behavior to be aware of
## Quick upgrade checks
## Bottom line
## Reference
```

---

## Changed behavior to be aware of

- **Import paths**: existing `benchbox.core.visualization.ascii.*` imports still work through
  shims, but the canonical import path is now `textcharts.*`. No migration is required; shims
  are not deprecated in this release.
- **Test lane markers**: if you have custom pytest marker filters, the marker names haven't
  changed, but lane membership may have shifted for some tests.

---

## Image placeholders (to generate before publishing)

- `textcharts_standalone.png` - textcharts package structure or import path diagram
- `format_loading_flow.png` - table format loading flow diagram (optional)
- `mutation_testing_output.png` - mutmut output showing caught mutations (optional)

---

## Narrative angle

This release has two stories:

1. **Textcharts extraction ships**: the work described in post #6 is now part of a release. The
   post can reference #6 for the detailed story and focus on what users see (nothing breaks,
   charts work the same, textcharts is independently usable).

2. **Test quality over test quantity**: this is the first release where we explicitly deleted
   tests to improve quality. The coverage number went down; the mutation survival rate went down
   too (which is what matters). This is worth a few sentences in the bottom line.

The bottom line should connect these: v0.1.5 is a housekeeping release. We separated a library,
cleaned up the registry, and replaced coverage theater with tests that catch mutations. None of
these are new user-facing features, but they make the next set of features easier to build
correctly.

---

## Reference

- Changelog entry: `CHANGELOG.md` (`[0.1.5] - 2026-03-10`)
- Post #6: `_blog/building-benchbox/drafts/06-extracting-textcharts.md`

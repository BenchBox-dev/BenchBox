<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Development Roadmap

```{tags} contributor, advanced
```

This document describes planned platform and benchmark additions for BenchBox. Items are organized by priority and implementation phase. For detailed specifications, see the corresponding TODO items in `_project/TODO/`.

> **Note**: This roadmap reflects current planning. Timelines are not committed, and scope may evolve with community feedback and sponsorship opportunities.

## Overview

BenchBox's expansion roadmap focuses on three strategic areas:

1. **Platform Coverage**: Adding high-performance and cloud-native analytical platforms
2. **Benchmark Diversity**: Real-world datasets and specialized workloads
3. **DataFrame Support**: Extending programmatic DataFrame benchmarking to all benchmarks

### Current Statistics

| Category | Current | Planned |
|----------|---------|---------|
| SQL Platforms | 39 | +0 |
| DataFrame Platforms | 9 | +0 |
| Benchmarks | 22 | +4 |
| DataFrame-enabled Benchmarks | 21 | +1 (Geospatial) |

---

## Platform Additions

All previously planned platform additions through Phase 4 have shipped. The platform expansion roadmap is complete pending new sponsorship or community requests.

### Completed Platforms

| Platform | Shipped | Modes |
|----------|---------|-------|
| LakeSail Sail | v0.2.1 | SQL + DataFrame |
| Apache Doris | v0.2.1 | SQL |
| StarRocks | v0.2.1 | SQL |
| ClickHouse Cloud | v0.2.1 | SQL |
| Firebolt Cloud | v0.2.1 | SQL |
| QuestDB | v0.2.1 | SQL |
| Databend | v0.2.1 | SQL |
| Microsoft Fabric Spark | v0.2.x | SQL + DataFrame |
| Starburst | v0.2.x | SQL |
| TimescaleDB | v0.2.x | SQL |

---

## Benchmark Additions

### Completed Benchmarks

| Benchmark | Shipped | Notes |
|-----------|---------|-------|
| Flight Data (US aviation on-time) | v0.3.0 | 20 queries, SQL + DataFrame |
| NYC Taxi Expansion | v0.3.0 | Green, FHV, HVFHV vehicle types |

### Planned Benchmarks

#### Geospatial Primitives

**Status**: Not Started | **Effort**: Medium | **Priority**: Medium

Dedicated benchmark for spatial SQL operations (`ST_*` functions) across platforms. NYC Taxi already includes some spatial queries; this would be a standalone primitives suite covering the full spatial SQL surface.

**Scope**:
- Point-in-polygon, distance, bounding box
- Spatial indexing and predicate pushdown
- Cross-platform dialect coverage (PostGIS, DuckDB spatial, ClickHouse, BigQuery)

---

#### GitHub Archive

**Status**: Not Started | **Effort**: Medium | **Priority**: Low

Developer activity analytics over the public GitHub event archive.

---

#### Stack Overflow Dataset

**Status**: Not Started | **Effort**: Medium | **Priority**: Low

Q&A and engagement analytics over the Stack Exchange data dump.

---

#### Wikipedia Pageviews

**Status**: Not Started | **Effort**: Medium | **Priority**: Low

Web traffic time-series patterns from Wikimedia pageview dumps.

---

## DataFrame Support Initiative

### Current State

DataFrame benchmarking is supported for 21 benchmarks across two API families:

**Expression Family** (Polars, PySpark, DataFusion, LakeSail):
- TPC-H, TPC-DS, TPC-DS OBT, TPC-DI, TPC-H Skew, TPC-Havoc, DataVault
- SSB, ClickBench, AMPLab, CoffeeShop, H2ODB, TSBS DevOps
- NYC Taxi, Flight Data, JoinOrder, JoinOrder Synthetic
- Read Primitives, Write Primitives, AI Primitives, Metadata Primitives, Transaction Primitives

**Pandas Family** (Pandas, Modin, cuDF, Dask):
- Full coverage matching the Expression Family above

### Remaining Expansion

The DataFrame initiative is substantially complete. The one remaining gap is:

| Benchmark | Status | Notes |
|-----------|--------|-------|
| Geospatial Primitives | Not Started | Blocked on the benchmark itself existing |

---

## Implementation Timeline

### Phase 1: Foundation (Completed)

- ~~MotherDuck adapter~~ ✓
- ~~Platform deployment infrastructure~~ ✓
- ~~Core infrastructure improvements~~ ✓
- ~~Onehouse Quanton adapter~~ ✓ (multi-format: Hudi, Iceberg, Delta)
- ~~Apache Hudi maintenance operations~~ ✓

### Phase 2: High-Impact Platforms (Completed)

- ~~LakeSail Sail (SQL + DataFrame)~~ ✓
- ~~Apache Doris~~ ✓
- ~~StarRocks~~ ✓
- ~~Cloud deployment modes (ClickHouse Cloud, Firebolt Cloud)~~ ✓

### Phase 3: Benchmark Diversity (Completed)

- ~~Flight Data Benchmark~~ ✓
- ~~NYC Taxi Expansion~~ ✓
- ~~DataFrame Tier 1 (SSB, ClickBench, NYC Taxi)~~ ✓

### Phase 4: Extended Coverage (Completed)

- ~~Microsoft Fabric Spark~~ ✓
- ~~Starburst~~ ✓
- ~~TimescaleDB~~ ✓
- ~~QuestDB~~ ✓
- ~~DataFrame Tiers 2–4~~ ✓

### Phase 5: Specialized Workloads

- Geospatial Primitives benchmark
- Real-world datasets (GitHub Archive, Stack Overflow, Wikipedia)

---

## How to Contribute

### Requesting Platforms or Benchmarks

Open an issue with:
- Use case description
- Scale factors needed
- Platform/benchmark specifics
- Compliance requirements (if applicable)

### Sponsoring Development

Enterprise users can sponsor specific platform or benchmark development. Contact the maintainers for details.

### Contributing Implementations

See the [Platform Development Guide](platform-development.md) and [Adding New Platforms](adding-new-platforms.md) for implementation patterns.

---

## Related Documentation

- {doc}`adding-new-platforms` - Platform implementation guide
- {doc}`platform-development` - Platform adapter architecture

---

*Last updated: 2026-06-05*

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
| SQL Platforms | 33 | +6 |
| DataFrame Platforms | 8 | +0 |
| Benchmarks | 12 | +6 |
| DataFrame-enabled Benchmarks | 2 (TPC-H, TPC-DS) | +13 |

---

## Platform Additions

### High Priority

#### LakeSail Sail (Rust-based Spark Replacement)

**Status**: Not Started | **Effort**: Large | **Modes**: SQL + DataFrame

LakeSail Sail is a Rust-based, drop-in replacement for Apache Spark built on DataFusion. It claims 4x faster execution with 94% lower hardware costs versus Apache Spark (TPC-H SF100 benchmarks).

**Key Characteristics**:
- Spark Connect protocol compatibility (existing PySpark code works unchanged)
- Multi-threaded single-host or distributed cluster execution
- DataFusion query optimizer with Rust workers

**Why it matters**: Growing interest in Spark alternatives with improved cost efficiency. Direct comparison validates vendor performance claims with independent TPC-H/TPC-DS benchmarks.

**Implementation**:
- `benchbox/platforms/lakesail.py` - SQL adapter via Spark Connect
- `benchbox/platforms/dataframe/lakesail_df.py` - DataFrame adapter

**Reference**: [LakeSail Official Site](https://lakesail.com/) | [GitHub](https://github.com/lakehq/sail)

---

### Medium-High Priority

#### Apache Doris (MPP OLAP Engine)

**Status**: Not Started | **Effort**: Medium

Apache top-level project with 12,000+ GitHub stars, used by Xiaomi, ByteDance, Baidu, JD.com, and 4,000+ enterprises.

**Key Characteristics**:
- MySQL protocol (port 9030)
- Stream Load for high-throughput data ingestion
- Multiple table models (Duplicate, Aggregate, Unique, Primary Key)
- Real-time analytics focus

**Managed Options**: VeloDB Cloud, SelectDB Cloud, ApsaraDB for SelectDB

---

#### StarRocks (Linux Foundation MPP OLAP)

**Status**: Not Started | **Effort**: Medium

Linux Foundation project with 11,000+ GitHub stars, used by Airbnb, Alibaba, Coinbase, Pinterest, Tencent.

**Key Characteristics**:
- MySQL protocol with Stream Load HTTP API
- Native data lake support (Iceberg, Hudi, Delta Lake)
- Competitive performance versus ClickHouse and Trino
- Sub-second analytics on real-time data

---

#### ClickHouse Cloud & Firebolt Cloud

**Status**: Not Started | **Effort**: Small

Cloud deployment modes for existing ClickHouse and Firebolt adapters.

**Key Characteristics**:
- Cloud-specific authentication and endpoint handling
- Managed infrastructure configuration
- Usage-based billing model support

---

### Medium Priority

#### QuestDB (Time-Series Database)

**Status**: Not Started | **Effort**: Medium

High-performance time-series database optimized for real-time analytics.

**Key Characteristics**:
- InfluxDB line protocol support
- SQL interface with time-series extensions
- Columnar storage with time-based partitioning

---

#### Databend (Cloud-Native Data Warehouse)

**Status**: Not Started | **Effort**: Medium | **Priority**: Low

Rust-based cloud-native data warehouse with DataFrame and data lake focus.

---

### Platform Infrastructure (In Progress)

These foundational improvements enable cleaner platform expansion:

| Item | Status | Purpose |
|------|--------|---------|
| Deployment Factory Integration | In Progress | Dynamic platform initialization with deployment modes |
| Deployment Registry Extensions | In Progress | Enhanced registry for cloud variants |
| Deployment CLI Integration | In Progress | CLI support for cloud credentials/endpoints |
| Configuration Inheritance | In Progress | Base config inheritance for deployment variants |

---

## Benchmark Additions

### Real-World Dataset Benchmarks

#### Flight Data Benchmark (US Aviation On-Time Performance)

**Status**: Not Started | **Effort**: Medium (2-3 weeks) | **Priority**: Medium

BTS TranStats flight data (1987-present, ~200M flights, free public data).

**Key Characteristics**:
- Scale factors from 0.01 (10MB, 1 week) to 100 (full dataset, 15-20GB)
- Multi-dimensional analysis: temporal, geographic, carrier, aircraft
- 20+ analytical queries across categories:
  - On-time performance (5+ queries)
  - Delay analysis (4+ queries)
  - Route analytics (4+ queries)
  - Temporal patterns (4+ queries)
  - Carrier comparisons (3+ queries)

**Why it matters**: Realistic OLAP workload with intuitive domain, complements TPC-H synthetic data.

---

#### NYC Taxi Benchmark Expansion

**Status**: Not Started | **Effort**: Medium (2-3 weeks) | **Priority**: Medium

Expand existing Yellow Taxi benchmark to include all TLC vehicle types.

**Current**: Yellow Taxi only
**Planned Additions**:
- Green Taxi (~500K trips/month, outer boroughs)
- FHV (~1M trips/month, traditional car services)
- HVFHV (Uber/Lyft, ~25M+ trips/month, since Feb 2019)

**New Query Categories**:
- Cross-type comparisons
- Market share analysis
- Price sensitivity across vehicle types

---

### Analytical Workload Benchmarks

| Benchmark | Status | Description |
|-----------|--------|-------------|
| Geospatial Primitives | Not Started | ST_* functions and spatial operations |
| GitHub Archive | Not Started | Developer activity analytics |
| Stack Overflow Dataset | Not Started | Q&A and engagement analytics |
| Wikipedia Pageviews | Not Started | Web traffic time-series patterns |

---

## DataFrame Support Initiative

### Current State

DataFrame benchmarking is currently supported for:
- TPC-H (22 queries)
- TPC-DS (99 queries)

### Expansion Plan

Extend DataFrame support to 15+ additional benchmarks (~700 new query implementations).

#### Implementation Tiers

**Tier 1 - High Value (Recommended First)**

| Benchmark | Queries | Rationale |
|-----------|---------|-----------|
| SSB | 13 | Simple star-schema, good starter |
| ClickBench | 43 | Popular industry benchmark |
| NYC Taxi | 25 | Real-world, high user interest |
| **Total** | **81** | |

**Tier 2 - Strong DataFrame Fit**

| Benchmark | Operations | Rationale |
|-----------|------------|-----------|
| TPC-DI | 38 | ETL transformations |
| Write Primitives | 109 | INSERT/UPDATE/DELETE/MERGE |
| TSBS DevOps | 18 | Time-series aggregations |
| H2ODB | 10 | Data science workloads |
| AMPLab | 8 | Established benchmark |
| CoffeeShop | 11 | Analytics patterns |
| **Total** | **194** | |

**Tier 3 - Variants/Experimental**

| Benchmark | Queries | Notes |
|-----------|---------|-------|
| TPC-H Skew | 22 | Skewed distributions |
| TPC-DS-OBT | 17 | One Big Table variant |
| TPC-Havoc | 220 | Query variants |
| DataVault | 22 | Data Vault modeling |
| **Total** | **281** | |

**Tier 4 - Complex**

| Benchmark | Queries | Notes |
|-----------|---------|-------|
| JoinOrder | 113 | High complexity joins |
| Read Primitives | 136 | Foundation testing |
| **Total** | **249** | |

### Dual-Family Architecture

Each DataFrame benchmark requires implementations for two API families:

- **Expression Family**: Polars, PySpark, DataFusion (lazy evaluation, expression chains)
- **Pandas Family**: Pandas, Modin, cuDF, Dask (eager evaluation, method chaining)

**Estimated Effort**: 4-6 weeks for full coverage

---

## Implementation Timeline

### Phase 1: Foundation (Completed)

- ~~MotherDuck adapter~~ ✓
- ~~Platform deployment infrastructure~~ ✓
- ~~Core infrastructure improvements~~ ✓
- ~~Onehouse Quanton adapter~~ ✓ (multi-format: Hudi, Iceberg, Delta)
- ~~Apache Hudi maintenance operations~~ ✓

### Phase 2: High-Impact Platforms

- LakeSail Sail (SQL + DataFrame)
- Apache Doris
- StarRocks
- Cloud deployment modes (ClickHouse Cloud, Firebolt Cloud)

### Phase 3: Benchmark Diversity

- Flight Data Benchmark
- NYC Taxi Expansion
- DataFrame Tier 1 (SSB, ClickBench, NYC Taxi)

### Phase 4: Extended Coverage

- ~~Microsoft Fabric Spark~~ ✓
- ~~Starburst~~ ✓
- ~~TimescaleDB~~ ✓
- Time-series platforms (QuestDB)
- DataFrame Tier 2

### Phase 5: Specialized Workloads

- Geospatial benchmarks
- Real-world datasets (GitHub Archive, Stack Overflow, Wikipedia)
- DataFrame Tier 3-4

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

*Last updated: 2026-01-20*

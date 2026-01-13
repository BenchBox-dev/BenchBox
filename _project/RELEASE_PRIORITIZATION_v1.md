# BenchBox Release Prioritization - 26-Week Rollout

**Status:** ACTIVE
**Related:** [RELEASE_ROADMAP_6_MONTH.md](RELEASE_ROADMAP_6_MONTH.md)
**Updated:** January 2026

---

## Overview

This document defines release prioritization for the 26-week rollout from v0.1.0 to v1.0.0. All features are implemented; this focuses on **release packaging**, **documentation**, and **quality assurance** priorities.

---

## Pre-Launch Checklist (Before Week 1)

### Critical Path Items

These must be complete before v0.1.0 release:

| Item | Priority | Status | Owner |
|------|----------|--------|-------|
| PyPI package configuration | Critical | Complete | - |
| GitHub repository public | Critical | Pending | - |
| README.md finalized | Critical | Complete | - |
| LICENSE file present | Critical | Complete | - |
| Basic documentation | Critical | Complete | - |
| CI/CD pipeline operational | Critical | Complete | - |
| Test suite passing | Critical | Complete | - |

### Week 1 Release Content Validation

Before publishing v0.1.0:

- [ ] DuckDB adapter tested on all platforms (macOS, Linux, Windows)
- [ ] TPC-H data generation works at SF 0.01, 0.1, 1.0
- [ ] All 22 TPC-H queries execute successfully
- [ ] CLI `benchbox run` command functional
- [ ] JSON export produces valid output
- [ ] Installation via `pip install benchbox` works
- [ ] Installation via `uv add benchbox` works
- [ ] `benchbox --version` returns correct version

---

## Weekly Release Preparation

### Release Week Checklist Template

Copy for each weekly release:

```markdown
## Week X: v0.X.Y Release Checklist

### Monday (Release Day)
- [ ] Version bumped in pyproject.toml
- [ ] CHANGELOG.md updated
- [ ] Git tag created (vX.Y.Z)
- [ ] PyPI release published
- [ ] GitHub release created with notes
- [ ] Documentation site updated

### Tuesday (Announcement)
- [ ] Blog post published
- [ ] LinkedIn post live
- [ ] Twitter thread posted
- [ ] Email to subscribers (if applicable)

### Wednesday (Technical Content)
- [ ] Demo GIF/video published
- [ ] Code examples tested
- [ ] How-to content live

### Thursday (Community)
- [ ] Reddit posts (where appropriate)
- [ ] HN submission (major releases only)
- [ ] Engage with comments/questions

### Friday (Review)
- [ ] All comments replied to
- [ ] Metrics captured
- [ ] Issues triaged
- [ ] Next week content prepared
```

---

## Feature Gating by Release

### Phase 1: Foundation (Weeks 1-4)

| Version | Platforms | Benchmarks | Features Hidden |
|---------|-----------|------------|-----------------|
| 0.1.0 | DuckDB, ClickHouse-local | TPC-H, TPC-DS | Cloud, DataFrame, Industry benchmarks |
| 0.1.1 | + SQLite | — | Cloud, DataFrame, Industry benchmarks |
| 0.1.2 | + DataFusion | — | Cloud, DataFrame, Industry benchmarks |
| 0.1.3 | — | — | Cloud, DataFrame, Industry benchmarks |

**Documentation Priority:**
- Getting started guide
- DuckDB + ClickHouse quick start
- TPC-H and TPC-DS overview
- CLI reference (basic)

### Phase 2: Industry + Academic + Optimizer Stress (Weeks 5-8)

| Version | Platforms | Benchmarks (Category) | Features Hidden |
|---------|-----------|----------------------|-----------------|
| 0.2.0 | — | + ClickBench, H2ODB, CoffeeShop (Industry) | Cloud, DataFrame |
| 0.2.1 | — | + SSB, AMPLab, JoinOrder (Academic) | Cloud, DataFrame |
| 0.2.2 | — | + TPC-Havoc (Experimental - Optimizer Stress) | Cloud, DataFrame |
| 0.2.3 | — | + TPC-H Skew (Experimental - Optimizer Stress) | Cloud, DataFrame |

**Documentation Priority:**
- Industry benchmark guides (ClickBench, H2ODB, CoffeeShop)
- Academic benchmark guides (SSB, AMPLab, JoinOrder)
- Experimental benchmarks guide (optimizer stress)
- Benchmark category overview

### Phase 3: Cloud I + Primitives + TPC-DI (Weeks 9-12)

| Version | Platforms | Benchmarks (Category) | Features Hidden |
|---------|-----------|----------------------|-----------------|
| 0.3.0 | + Snowflake | + Read, Write (Primitives Essential) | DataFrame, remaining cloud |
| 0.3.1 | + Databricks | + Metadata, Transactions (Primitives Extra) | DataFrame, remaining cloud |
| 0.3.2 | + BigQuery | + TPC-DI (TPC ETL) | DataFrame, remaining cloud |
| 0.3.3 | + Redshift | — | DataFrame, remaining cloud |

**Documentation Priority:**
- Cloud platform guides (Snowflake, Databricks, BigQuery, Redshift)
- Primitives reference (Read, Write, Metadata, Transactions)
- TPC-DI ETL guide
- Authentication setup
- Cloud storage integration

### Phase 4: Cloud II + Data Modelling + Time Series + Real World (Weeks 13-16)

| Version | Platforms | Benchmarks (Category) | Features Hidden |
|---------|-----------|----------------------|-----------------|
| 0.4.0 | + ClickHouse Cloud | + TPC-DS OBT, TPC-H Data Vault (Experimental - Data Modelling) | DataFrame, query engines |
| 0.4.1 | + PostgreSQL, TimescaleDB | + TSBS DevOps, TSBS IoT (Time Series) | DataFrame, query engines |
| 0.4.2 | — | + NYC Taxi (Real World) | DataFrame, query engines |
| 0.4.3 | — | — | DataFrame, query engines |

**Documentation Priority:**
- ClickHouse guide
- PostgreSQL + TimescaleDB guide
- Cost tracking guide
- Tuning configuration reference
- Data Modelling/Time Series/Real World benchmark guides
- **Milestone: All 20 benchmarks documented**

**Future Real World Datasets** (post-1.0): Stack Overflow, Flight Data, GitHub Archive, Wikipedia Pageviews

### Phase 5: DataFrame (Weeks 17-20)

| Version | Platforms | Benchmarks | Features Hidden |
|---------|-----------|------------|-----------------|
| 0.5.0 | + Polars-DF, Pandas-DF | — | Query engines, Azure |
| 0.5.1 | + DataFusion-DF, DuckDB-DF | — | Query engines, Azure |
| 0.5.2 | + PySpark-DF, Dask-DF | — | Query engines, Azure |
| 0.5.3 | + Modin-DF, cuDF-DF | — | Query engines, Azure |

**Documentation Priority:**
- DataFrame mode guide
- SQL vs DataFrame comparison
- Distributed DataFrame guide
- GPU acceleration guide

### Phase 6: Query Engines + Azure (Weeks 21-24)

| Version | Platforms | Benchmarks | Features Hidden |
|---------|-----------|------------|-----------------|
| 0.6.0 | + Trino, Presto, Spark | — | — |
| 0.6.1 | + Azure Synapse, Fabric | — | — |
| 0.6.2 | + Athena, Firebolt | — | — |
| 0.6.3 | — | — | — |

**Documentation Priority:**
- Query engine guide
- Azure platform guides
- Serverless analytics guide
- Complete platform selection guide

### Phase 7: Stable (Weeks 25-26)

| Version | Features Enabled |
|---------|------------------|
| 0.9.0 | All features, RC status |
| 1.0.0 | All features, stable |

**Documentation Priority:**
- Complete API reference
- Migration guide (alpha → stable)
- Production deployment guide
- Troubleshooting guide

---

## Quality Gates

### Per-Release Quality Requirements

| Version Range | Test Coverage | Doc Coverage | Example Coverage |
|---------------|---------------|--------------|------------------|
| 0.1.x | 70% | Core docs | Basic examples |
| 0.2.x | 75% | + Benchmark docs | + Benchmark examples |
| 0.3.x | 78% | + DataFrame docs | + DataFrame examples |
| 0.4.x | 80% | + Cloud docs | + Cloud examples |
| 0.5.x | 82% | + Enterprise docs | + Enterprise examples |
| 0.6.x | 85% | + Advanced docs | + Advanced examples |
| 1.0.0 | 85%+ | Complete | Complete |

### Release Blocking Issues

A release is blocked if:
- Test suite fails
- Critical security vulnerability exists
- Documentation for revealed features incomplete
- Installation fails on any major platform
- Core functionality (run benchmark, export results) broken

---

## Dependency Management

### Core Dependencies (All Versions)

```
duckdb>=0.9.0
sqlglot>=20.0.0
click>=8.0.0
rich>=13.0.0
pydantic>=2.0.0
pyyaml>=6.0.0
```

### Feature-Specific Dependencies

| Version | New Dependencies |
|---------|------------------|
| 0.3.0 | polars, pandas |
| 0.3.2 | pyspark, dask |
| 0.3.3 | modin, cudf (optional) |
| 0.4.0 | snowflake-connector-python |
| 0.4.1 | databricks-sql-connector |
| 0.4.2 | google-cloud-bigquery |
| 0.4.3 | redshift-connector, boto3 |
| 0.5.0 | clickhouse-driver |
| 0.5.2 | psycopg2 |

---

## Risk Assessment

### High Risk Releases

| Version | Risk | Mitigation |
|---------|------|------------|
| 0.1.0 | First public release | Extensive testing, soft launch |
| 0.3.0 | DataFrame paradigm shift | Clear documentation, comparison guides |
| 0.4.0 | First cloud platform | Authentication troubleshooting guide |
| 1.0.0 | Stability commitment | Extensive RC testing, community feedback |

### Rollback Plan

If a release has critical issues:

1. **Immediate:** Publish patch release (0.x.y+1) within 24-48 hours
2. **Communication:** Announce issue and fix timeline on all channels
3. **Documentation:** Update docs to warn about affected versions
4. **PyPI:** Consider yanking severely broken releases (rare)

---

## Metrics to Track

### Per-Release Metrics

| Metric | Target | Tracking Method |
|--------|--------|-----------------|
| PyPI downloads (7-day) | 100+ | pypistats |
| GitHub issues (new) | <20 | GitHub API |
| GitHub issues (critical) | 0 | Manual triage |
| Documentation page views | 500+ | Analytics |
| Social engagement | 1000+ impressions | Platform analytics |

### Cumulative Targets

| Milestone | Downloads | Stars | Contributors |
|-----------|-----------|-------|--------------|
| 0.2.0 (Week 5) | 500 | 100 | 3 |
| 0.4.0 (Week 13) | 5,000 | 500 | 10 |
| 0.6.0 (Week 21) | 25,000 | 1,500 | 20 |
| 1.0.0 (Week 26) | 50,000 | 3,000 | 30 |

---

## Appendix: Original v1.0 Blockers (Historical)

For reference, the original release prioritization (November 2025) identified these blockers. All have been addressed:

| Original Item | Original Status | Current Status |
|---------------|-----------------|----------------|
| Guard TPC-DS Fractional Scale | Identified | Fixed |
| Stabilize Optional-Dependency Tests | Identified | Fixed |
| Prepare Project for Publication | In Progress | Complete |
| Secure Credential Handling | In Progress | Complete |
| Security Audit | In Progress | Complete |
| Curate Release Branch | Identified | Superseded by roadmap |

---

*This document is the active release prioritization guide. See RELEASE_ROADMAP_6_MONTH.md for the complete weekly schedule.*

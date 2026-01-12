# BenchBox 6-Month Release Roadmap

**Version Range:** 0.1.0 → 1.0.0
**Duration:** 26 weeks (6 months)
**Release Cadence:** Weekly
**Strategy:** Phased feature revelation of completed functionality

---

## Executive Summary

BenchBox has **21 platform adapters**, **18+ benchmarks**, and comprehensive CLI/API features already implemented. This roadmap defines a deliberate 26-week rollout strategy to:

1. **Maximize exposure** - Each week announces new capabilities, creating sustained visibility
2. **Build confidence** - Consistent weekly releases demonstrate project health and momentum
3. **Absorb feedback** - Gradual rollout allows incorporating user input before revealing dependent features

### Version Progression

| Phase | Weeks | Versions | Theme |
|-------|-------|----------|-------|
| Foundation | 1-4 | 0.1.0 - 0.1.3 | Core local benchmarking (DuckDB, ClickHouse, TPC-H/DS) |
| TPC + Primitives + Experimental | 5-8 | 0.2.0 - 0.2.3 | Complete TPC, micro-benchmarks, experimental variants |
| Cloud I + Academic | 9-12 | 0.3.0 - 0.3.3 | Major cloud platforms + SSB, JoinOrder, AMPLab |
| Cloud II + Industry/TimeSeries/RealWorld | 13-16 | 0.4.0 - 0.4.3 | Extended cloud + ClickBench, TSBS, NYC Taxi, H2ODB, CoffeeShop |
| DataFrame | 17-20 | 0.5.0 - 0.5.3 | DataFrame paradigm |
| Query Engines + Azure | 21-24 | 0.6.0 - 0.6.3 | Trino, Presto, Spark, Azure |
| Stable | 25-26 | 0.9.0, 1.0.0 | Production ready |

**Key Design Principle:** All 19 SQL-based benchmarks are revealed before DataFrame mode (Week 17) using BenchBox's native category groupings:
- **TPC** (3): TPC-H, TPC-DS, TPC-DI
- **Primitives** (3): Read, Write, Transaction
- **Experimental** (4): TPC-Havoc, TPC-H Skew, TPC-DS OBT, TPC-H Data Vault
- **Academic** (3): SSB, JoinOrder, AMPLab
- **Industry** (3): ClickBench, H2ODB, CoffeeShop
- **Time Series** (1): TSBS DevOps
- **Real World** (1): NYC Taxi

---

## Weekly Release Schedule

### Phase 1: Foundation (Weeks 1-4)

**Theme:** "Useful from Day 1"

#### Week 1 - v0.1.0 (Initial Public Release)
**Headline:** "BenchBox: Python-Native Database Benchmarking"

**Features Revealed:**
- DuckDB platform adapter
- ClickHouse-local platform adapter (embedded mode)
- TPC-H benchmark (22 queries)
- TPC-DS benchmark (99 queries)
- Basic CLI (`benchbox run`, `benchbox --version`)
- Data generation at scale factors 0.01-1.0
- JSON result export

**Marketing Angle:** "Compare DuckDB vs ClickHouse on TPC-H and TPC-DS in minutes"
```bash
pip install benchbox
benchbox run --platform duckdb --benchmark tpch --scale 0.01
benchbox run --platform clickhouse-local --benchmark tpcds --scale 1
```

**Blog Post:** "Introducing BenchBox: Two Platforms, Two Benchmarks, Infinite Insights"

**Why This Launch Configuration:**
- **Two platforms** (DuckDB + ClickHouse-local): Enables meaningful comparisons from Day 1
- **Two benchmarks** (TPC-H + TPC-DS): Covers both simple (22 queries) and complex (99 queries) analytics
- **Zero cloud dependencies**: Users can benchmark immediately without accounts or credentials

---

#### Week 2 - v0.1.1
**Headline:** "SQLite Support + Improved Data Generation"

**Features Revealed:**
- SQLite platform adapter (memory and file modes)
- Parallel data generation
- `--output` flag for custom output paths
- Improved progress indicators

**Marketing Angle:** "Compare DuckDB vs SQLite with identical benchmarks"

**Blog Post:** "BenchBox Week 2: SQLite and the Importance of Baseline Comparisons"

---

#### Week 3 - v0.1.2
**Headline:** "Apache DataFusion + Dry-Run Mode"

**Features Revealed:**
- DataFusion platform adapter
- `--dry-run` mode (preview without execution)
- Query plan export
- Schema inspection commands

**Marketing Angle:** "Preview your benchmark configuration before committing cloud resources"

**Blog Post:** "Dry-Run Mode: Test Your Benchmark Setup Without Spending a Dime"

---

#### Week 4 - v0.1.3
**Headline:** "Compression Support + Multi-Format Export"

**Features Revealed:**
- Compression options (zstd, gzip, none)
- Configurable compression levels
- CSV export format
- HTML report generation
- `benchbox export` command

**Marketing Angle:** "Generate publication-ready benchmark reports"

**Blog Post:** "From Raw Results to Shareable Reports"

---

### Phase 2: TPC + Primitives + Experimental (Weeks 5-8)

**Theme:** "Complete TPC Suite + Deep Performance Analysis"

*This phase completes the TPC standards, adds micro-benchmarks, and introduces experimental variants.*

#### Week 5 - v0.2.0
**Headline:** "TPC-DI: Benchmark Your ETL Pipelines"

**Features Revealed:**
- TPC-DI benchmark (ETL/integration workflows)
- Multi-phase data integration testing
- Historical data loading patterns
- Incremental update benchmarking

**Marketing Angle:** "Complete TPC coverage: H, DS, and now DI"

**Blog Post:** "TPC-DI: Finally, a Benchmark for ETL"

**Category:** TPC (completing the official standards)

---

#### Week 6 - v0.2.1
**Headline:** "Primitives: Micro-Benchmarks for Deep Analysis"

**Features Revealed:**
- Read Primitives (90+ queries)
- Write Primitives (117 operations)
- Transaction Primitives (8 ACID tests)
- Operation-level performance isolation

**Marketing Angle:** "Identify exactly which operations are slow"

**Blog Post:** "Primitives: When You Need to Know WHY It's Slow"

**Category:** Primitives (fundamental database operations)

---

#### Week 7 - v0.2.2
**Headline:** "Experimental: TPC-Havoc + TPC-H Skew"

**Features Revealed:**
- TPC-Havoc benchmark (220 query variants)
- TPC-H Skew (configurable data distributions)
- Optimizer robustness testing
- Query plan stability analysis

**Marketing Angle:** "Stress test your optimizer with query variants and skewed data"

**Blog Post:** "Experimental Benchmarks: Beyond Standard TPC"

**Category:** Experimental (specialized testing)

---

#### Week 8 - v0.2.3
**Headline:** "Experimental: TPC-DS OBT + Data Vault"

**Features Revealed:**
- TPC-DS OBT (One Big Table denormalized)
- TPC-H Data Vault (dimensional modeling)
- Alternative schema patterns
- Denormalization performance testing

**Marketing Angle:** "Test your database with alternative schema designs"

**Blog Post:** "Schema Variants: When Denormalization Wins"

**Category:** Experimental (alternative schema patterns)

---

### Phase 3: Cloud I + Academic Benchmarks (Weeks 9-12)

**Theme:** "Enterprise Cloud + Research Benchmarks"

*Each cloud platform release is paired with an Academic benchmark (SSB, JoinOrder, AMPLab) from research institutions.*

#### Week 9 - v0.3.0
**Headline:** "Snowflake + Star Schema Benchmark"

**Features Revealed:**
- Snowflake platform adapter
- Warehouse configuration
- Result cache handling
- Clustering support
- `[snowflake]` extra installation
- **Star Schema Benchmark (SSB)** - 13 queries

**Marketing Angle:** "Benchmark Snowflake with the classic star schema workload"

**Blog Post:** "Snowflake + SSB: Star Schema Performance"

**Category:** Academic (research benchmark from academia)

---

#### Week 10 - v0.3.1
**Headline:** "Databricks + JoinOrder Benchmark"

**Features Revealed:**
- Databricks platform adapter
- SQL Warehouses + Unity Catalog
- Photon engine support
- AQE and Z-ordering
- DBFS integration
- **JoinOrder Benchmark** - 113 queries for optimizer testing

**Marketing Angle:** "Test Databricks optimizer with 113 join order challenges"

**Blog Post:** "Databricks: How Good Is Your Query Optimizer?"

**Category:** Academic (query optimizer research)

---

#### Week 11 - v0.3.2
**Headline:** "BigQuery + AMPLab Benchmark"

**Features Revealed:**
- BigQuery platform adapter
- Clustering and partitioning
- Slot-based execution
- GCS staging integration
- Regional deployment
- **AMPLab Big Data Benchmark** - 8 queries (scan/aggregate/join)

**Marketing Angle:** "BigQuery benchmarking with Berkeley's big data patterns"

**Blog Post:** "BigQuery + AMPLab: Big Data Performance"

**Category:** Academic (Berkeley research benchmark)

---

#### Week 12 - v0.3.3
**Headline:** "Amazon Redshift"

**Features Revealed:**
- Redshift platform adapter
- Distribution keys
- Sort keys
- S3 COPY integration
- Spectrum support

**Marketing Angle:** "Redshift benchmarking with proper distribution strategy"

**Blog Post:** "Redshift: Distribution Keys Make or Break Performance"

*Note: Academic benchmarks complete. Industry benchmarks begin in Phase 4.*

---

### Phase 4: Cloud II + Industry/TimeSeries/RealWorld (Weeks 13-16)

**Theme:** "Complete Cloud + Practitioner Benchmarks"

*This phase completes cloud coverage and adds Industry, Time Series, and Real World benchmarks.*

#### Week 13 - v0.4.0
**Headline:** "ClickHouse Cloud + ClickBench"

**Features Revealed:**
- ClickHouse platform adapter (Cloud mode)
- TLS support
- Native protocol
- Multi-node cluster support
- **ClickBench** - 43 analytical queries (web analytics patterns)

**Marketing Angle:** "ClickHouse Cloud with real-world web analytics patterns"

**Blog Post:** "ClickHouse Cloud: Real-Time Analytics at Scale"

**Category:** Industry (real-world benchmark from practitioners)

*Note: ClickHouse-local was released in Week 1. This release adds cloud connectivity.*

---

#### Week 14 - v0.4.1
**Headline:** "PostgreSQL + TimescaleDB + TSBS DevOps"

**Features Revealed:**
- PostgreSQL platform adapter
- TimescaleDB platform adapter
- Hypertable support
- Time-series optimizations
- Tuning configurations
- **TSBS DevOps Benchmark** - time-series workload patterns

**Marketing Angle:** "Time-series benchmarking with TSBS DevOps workloads"

**Blog Post:** "PostgreSQL Family: From OLTP to Time-Series Analytics"

**Category:** Time Series (temporal data workloads)

---

#### Week 15 - v0.4.2
**Headline:** "Cost Tracking + NYC Taxi + H2ODB"

**Features Revealed:**
- Per-query cost estimation
- Platform cost tracking (Snowflake, Databricks, BigQuery, Redshift, Athena)
- Cost comparison reports
- **NYC Taxi Benchmark** - real-world trip data analysis
- **H2ODB Benchmark** - data science groupby/join patterns

**Marketing Angle:** "Real-world data meets real cost tracking"

**Blog Post:** "Cost-Aware Benchmarking: Performance Per Dollar"

**Categories:** Real World (NYC Taxi), Industry (H2ODB)

---

#### Week 16 - v0.4.3
**Headline:** "Tuning + Validation + CoffeeShop"

**Features Revealed:**
- Tuning modes (tuned, notuning, auto, custom YAML)
- 5 validation modes (exact, loose, range, disabled, full)
- PK/FK/index configuration
- Platform-specific tuning (clustering, distribution)
- **CoffeeShop Benchmark** - CRUD transaction patterns

**Marketing Angle:** "All 19 benchmarks, fully configurable"

**Blog Post:** "The Tuning Gap: Default vs Optimized Performance"

**Category:** Industry (order line benchmark)

**Milestone:** *All SQL-based benchmarks now available (19 total). DataFrame mode begins next phase.*

---

### Phase 5: DataFrame Mode (Weeks 17-20)

**Theme:** "SQL vs DataFrame: Same Benchmark, Different Paradigm"

#### Week 17 - v0.5.0
**Headline:** "DataFrame Mode with Polars + Pandas"

**Features Revealed:**
- Polars-DF platform adapter
- Pandas-DF platform adapter
- DataFrame execution mode (`--platform polars-df`)
- Streaming mode support (Polars)
- Multiple dtype backends (Pandas)

**Marketing Angle:** "Compare SQL execution vs native DataFrame APIs"

**Blog Post:** "DataFrame Benchmarking: Why Paradigm Matters"

---

#### Week 18 - v0.5.1
**Headline:** "DataFusion-DF + DuckDB-DF"

**Features Revealed:**
- DataFusion-DF adapter (pushdown optimization)
- DuckDB-DF adapter (hybrid mode)
- Partition-aware execution
- Expression language support

**Marketing Angle:** "The best of both worlds: SQL engines with DataFrame interfaces"

**Blog Post:** "Hybrid Engines: When SQL Meets DataFrame"

---

#### Week 19 - v0.5.2
**Headline:** "Distributed DataFrames: PySpark + Dask"

**Features Revealed:**
- PySpark-DF platform adapter
- Dask-DF platform adapter
- Distributed execution support
- Multi-worker scheduler configuration

**Marketing Angle:** "Scale your DataFrame benchmarks beyond a single machine"

**Blog Post:** "Distributed DataFrame Benchmarking"

---

#### Week 20 - v0.5.3
**Headline:** "Modin + cuDF: Parallel and GPU Execution"

**Features Revealed:**
- Modin-DF adapter (Ray/Dask backends)
- cuDF-DF adapter (NVIDIA GPU)
- GPU memory management
- Spill-to-host support

**Marketing Angle:** "GPU-accelerated analytics benchmarking"

**Blog Post:** "GPU DataFrames: When Speed Really Matters"

---

### Phase 6: Query Engines + Azure (Weeks 21-24)

**Theme:** "Complete Platform Coverage"

*This phase adds federated query engines and completes Microsoft Azure platform coverage.*

#### Week 21 - v0.6.0
**Headline:** "Trino + Presto + Spark SQL"

**Features Revealed:**
- Trino platform adapter
- Presto platform adapter (legacy API)
- Spark SQL platform adapter
- Table format support (Iceberg, Delta, Hive)

**Marketing Angle:** "Federated query engine benchmarking"

**Blog Post:** "Query Federation: One Benchmark, Multiple Engines"

---

#### Week 22 - v0.6.1
**Headline:** "Azure Synapse + Microsoft Fabric"

**Features Revealed:**
- Azure Synapse platform adapter
- Microsoft Fabric platform adapter
- Multiple auth methods
- Service principal support
- Resource class configuration

**Marketing Angle:** "Microsoft analytics stack benchmarking"

**Blog Post:** "Azure Analytics: Synapse vs Fabric Performance"

---

#### Week 23 - v0.6.2
**Headline:** "AWS Athena + Firebolt"

**Features Revealed:**
- AWS Athena platform adapter
- Firebolt platform adapter (Core + Cloud)
- S3 query federation
- Serverless analytics benchmarking

**Marketing Angle:** "Serverless analytics benchmarking"

**Blog Post:** "Serverless Analytics: Pay-Per-Query Economics"

---

#### Week 24 - v0.6.3
**Headline:** "Complete Platform Matrix"

**Features Revealed:**
- All 21 SQL platform adapters available
- Cross-platform comparison guides
- Platform selection wizard
- Benchmark recommendation engine

**Marketing Angle:** "21 platforms, 18 benchmarks, one tool"

**Blog Post:** "BenchBox Platform Guide: Choosing the Right Engine"

---

### Phase 7: Stable Release (Weeks 25-26)

**Theme:** "Production Ready"

#### Week 25 - v0.9.0 (Release Candidate)
**Headline:** "BenchBox RC: Feature Complete"

**Features Revealed:**
- Complete documentation
- Full example suite
- Interactive shell (`benchbox shell`)
- System profiling (`benchbox profile`)
- `benchbox platforms` and `benchbox benchmarks` commands
- Migration guide from alpha

**Marketing Angle:** "The complete analytical benchmarking toolkit"

**Blog Post:** "BenchBox 0.9: Call for Testers"

---

#### Week 26 - v1.0.0 (Stable Release)
**Headline:** "BenchBox 1.0: Production Ready"

**Features Revealed:**
- Stability commitment
- API freeze for 1.x series
- Long-term support
- Complete platform matrix (21 SQL + 8 DataFrame)
- Production deployment guides

**Marketing Angle:** "BenchBox 1.0: 21 platforms, 18 benchmarks, production ready"

**Blog Post:** "BenchBox 1.0: From Alpha to Production"

---

## Feature Revelation Matrix

### Platforms by Week

| Week | Version | Platforms Added | Cumulative |
|------|---------|-----------------|------------|
| 1 | 0.1.0 | DuckDB, ClickHouse-local | 2 |
| 2 | 0.1.1 | SQLite | 3 |
| 3 | 0.1.2 | DataFusion | 4 |
| 9 | 0.3.0 | Snowflake | 5 |
| 10 | 0.3.1 | Databricks | 6 |
| 11 | 0.3.2 | BigQuery | 7 |
| 12 | 0.3.3 | Redshift | 8 |
| 13 | 0.4.0 | ClickHouse Cloud | 9 |
| 14 | 0.4.1 | PostgreSQL, TimescaleDB | 11 |
| 17 | 0.5.0 | Polars-DF, Pandas-DF | 13 |
| 18 | 0.5.1 | DataFusion-DF, DuckDB-DF | 15 |
| 19 | 0.5.2 | PySpark-DF, Dask-DF | 17 |
| 20 | 0.5.3 | Modin-DF, cuDF-DF | 19 |
| 21 | 0.6.0 | Trino, Presto, Spark | 22 |
| 22 | 0.6.1 | Azure Synapse, Microsoft Fabric | 24 |
| 23 | 0.6.2 | AWS Athena, Firebolt | 26 |

### Benchmarks by Week

| Week | Version | Category | Benchmarks Added | Cumulative |
|------|---------|----------|------------------|------------|
| 1 | 0.1.0 | TPC | TPC-H, TPC-DS | 2 |
| 5 | 0.2.0 | TPC | TPC-DI | 3 |
| 6 | 0.2.1 | Primitives | Read, Write, Transaction | 6 |
| 7 | 0.2.2 | Experimental | TPC-Havoc, TPC-H Skew | 8 |
| 8 | 0.2.3 | Experimental | TPC-DS OBT, TPC-H Data Vault | 10 |
| 9 | 0.3.0 | Academic | SSB | 11 |
| 10 | 0.3.1 | Academic | JoinOrder | 12 |
| 11 | 0.3.2 | Academic | AMPLab | 13 |
| 13 | 0.4.0 | Industry | ClickBench | 14 |
| 14 | 0.4.1 | Time Series | TSBS DevOps | 15 |
| 15 | 0.4.2 | Real World + Industry | NYC Taxi, H2ODB | 17 |
| 16 | 0.4.3 | Industry | CoffeeShop | 18 |

**BenchBox Benchmark Categories:**
- **TPC** (3): TPC-H, TPC-DS, TPC-DI — Official industry standards
- **Primitives** (3): Read, Write, Transaction — Fundamental operations
- **Experimental** (4): TPC-Havoc, TPC-H Skew, TPC-DS OBT, TPC-H Data Vault — Specialized testing
- **Academic** (3): SSB, JoinOrder, AMPLab — Research benchmarks from academia
- **Industry** (3): ClickBench, H2ODB, CoffeeShop — Real-world from practitioners
- **Time Series** (1): TSBS DevOps — Temporal data workloads
- **Real World** (1): NYC Taxi — Real-world datasets

### CLI Features by Week

| Week | Version | CLI Features Added |
|------|---------|-------------------|
| 1 | 0.1.0 | `benchbox run`, `--version`, `--platform`, `--benchmark`, `--scale` |
| 2 | 0.1.1 | `--output`, progress indicators |
| 3 | 0.1.2 | `--dry-run`, query plan export |
| 4 | 0.1.3 | `benchbox export`, `--compression` |
| 5 | 0.2.0 | `--phases` (generate, load, power) |
| 8 | 0.2.3 | `--queries` (subset selection) |
| 9 | 0.3.0 | `--platform-option`, `benchbox check-deps` |
| 15 | 0.4.2 | Cost reporting in results |
| 16 | 0.4.3 | `--tuning`, `--validation` |
| 25 | 0.9.0 | `benchbox shell`, `benchbox profile`, `benchbox platforms`, `benchbox benchmarks` |

---

## Marketing Calendar

### Weekly Content Rhythm

Each release week follows this pattern:

**Monday:** Release day
- Tag and publish new version to PyPI
- Update documentation
- Merge release notes

**Tuesday:** Announcement
- Blog post published
- LinkedIn long-form post
- Twitter/X thread (8-10 tweets)

**Wednesday:** Technical deep-dive
- Demo GIF or video
- Code examples
- How-to content

**Thursday:** Community engagement
- Reddit posts (r/Python, r/dataengineering, r/database)
- HN submission (for major releases only)
- Quote tweets and replies

**Friday:** Engagement review
- Reply to all comments
- Track metrics
- Prepare next week's content

### Major Announcement Weeks

These weeks warrant extra marketing effort:

| Week | Version | Event | Extra Activities |
|------|---------|-------|------------------|
| 1 | 0.1.0 | Initial Launch (DuckDB + ClickHouse, TPC-H + TPC-DS) | Show HN, Product Hunt, all channels |
| 5 | 0.2.0 | TPC-DI (Complete TPC Suite) | Database/ETL community focus |
| 6 | 0.2.1 | Primitives (Micro-benchmarks) | Performance engineering audience |
| 9 | 0.3.0 | Snowflake + SSB (Cloud + Academic) | Enterprise/cloud audience |
| 13 | 0.4.0 | ClickHouse Cloud + ClickBench | Real-time analytics community |
| 16 | 0.4.3 | All 18 Benchmarks Complete | "Complete benchmark suite" messaging |
| 17 | 0.5.0 | DataFrame Mode | Python/data science community |
| 25 | 0.9.0 | RC | Full press, call for testers |
| 26 | 1.0.0 | Stable Release | Maximum coverage, all channels |

---

## Success Metrics

### Release Health

| Metric | Target per Release |
|--------|-------------------|
| PyPI downloads (week 1) | 100+ |
| GitHub stars (cumulative) | +25/week |
| GitHub issues opened | 5-10 (engagement indicator) |
| Blog post views | 500+ |
| Social impressions | 5,000+ |

### Cumulative Targets

| Milestone | Target |
|-----------|--------|
| Week 4 (0.1.3) | 500 downloads, 100 stars |
| Week 8 (0.2.3) | 2,000 downloads, 300 stars |
| Week 12 (0.3.3) | 5,000 downloads, 600 stars |
| Week 16 (0.4.3) | 10,000 downloads, 1,000 stars |
| Week 20 (0.5.3) | 20,000 downloads, 1,500 stars |
| Week 24 (0.6.3) | 35,000 downloads, 2,500 stars |
| Week 26 (1.0.0) | 50,000 downloads, 3,000 stars |

---

## Risk Mitigation

### Release Risks

| Risk | Mitigation |
|------|------------|
| Critical bug in release | Patch release within 48 hours (0.x.y+1) |
| Feature not working as documented | Hot-fix + documentation update |
| Low engagement on release | Adjust marketing angle, boost content |
| Negative community feedback | Address publicly, incorporate changes |
| Dependency conflicts | Pin dependencies, test matrix |

### Schedule Risks

| Risk | Mitigation |
|------|------------|
| Unable to maintain weekly cadence | Bank 2-3 releases ahead |
| Marketing content not ready | Pre-write content 2 weeks ahead |
| Unexpected feature issues | Features are already tested; this is documentation/packaging work |
| External platform changes | Adapters are already working; pin versions |

---

## Pre-Release Checklist

### Per-Release Tasks

Before each Monday release:

- [ ] Version bumped in `pyproject.toml`
- [ ] CHANGELOG updated
- [ ] Documentation for new features complete
- [ ] Examples added/updated
- [ ] Tests passing
- [ ] Blog post drafted and scheduled
- [ ] Social media content queued
- [ ] Release notes written

### Major Release Additional Tasks

For 0.x.0 releases:

- [ ] Migration guide (if breaking changes)
- [ ] Video demo recorded
- [ ] HN/Reddit posts prepared
- [ ] Email to early users
- [ ] Press outreach (for 1.0.0)

---

## Appendix A: Complete Version History

| Week | Version | Primary Feature | New Platforms | New Benchmarks (Category) |
|------|---------|-----------------|---------------|---------------------------|
| 1 | 0.1.0 | **Initial Launch** | DuckDB, ClickHouse-local | TPC-H, TPC-DS (TPC) |
| 2 | 0.1.1 | SQLite | SQLite | — |
| 3 | 0.1.2 | DataFusion + Dry-Run | DataFusion | — |
| 4 | 0.1.3 | Compression + Export | — | — |
| 5 | 0.2.0 | **TPC-DI** | — | TPC-DI (TPC) |
| 6 | 0.2.1 | **Primitives** | — | Read, Write, Transaction (Primitives) |
| 7 | 0.2.2 | Experimental | — | TPC-Havoc, TPC-H Skew (Experimental) |
| 8 | 0.2.3 | Experimental | — | TPC-DS OBT, TPC-H Data Vault (Experimental) |
| 9 | 0.3.0 | **Snowflake + SSB** | Snowflake | SSB (Academic) |
| 10 | 0.3.1 | Databricks + JoinOrder | Databricks | JoinOrder (Academic) |
| 11 | 0.3.2 | BigQuery + AMPLab | BigQuery | AMPLab (Academic) |
| 12 | 0.3.3 | Redshift | Redshift | — |
| 13 | 0.4.0 | ClickHouse Cloud + ClickBench | ClickHouse Cloud | ClickBench (Industry) |
| 14 | 0.4.1 | PostgreSQL + TSBS | PostgreSQL, TimescaleDB | TSBS DevOps (Time Series) |
| 15 | 0.4.2 | Cost Tracking + NYC Taxi + H2ODB | — | NYC Taxi (Real World), H2ODB (Industry) |
| 16 | 0.4.3 | **All 18 Benchmarks Complete** | — | CoffeeShop (Industry) |
| 17 | 0.5.0 | **DataFrame Mode** | Polars-DF, Pandas-DF | — |
| 18 | 0.5.1 | DataFusion-DF + DuckDB-DF | DataFusion-DF, DuckDB-DF | — |
| 19 | 0.5.2 | PySpark-DF + Dask-DF | PySpark-DF, Dask-DF | — |
| 20 | 0.5.3 | Modin-DF + cuDF-DF | Modin-DF, cuDF-DF | — |
| 21 | 0.6.0 | **Query Engines** | Trino, Presto, Spark | — |
| 22 | 0.6.1 | Azure Synapse + Fabric | Azure Synapse, Microsoft Fabric | — |
| 23 | 0.6.2 | Athena + Firebolt | Athena, Firebolt | — |
| 24 | 0.6.3 | Complete Platform Matrix | — | — |
| 25 | 0.9.0 | **Release Candidate** | — | — |
| 26 | 1.0.0 | **Stable Release** | — | — |

---

## Appendix B: Social Media Hooks by Release

### Phase 1: Foundation (Weeks 1-4)

**0.1.0:** "Compare DuckDB vs ClickHouse on TPC-H and TPC-DS. Two platforms, two benchmarks, three commands."

**0.1.1:** "SQLite joins the comparison. Three local engines, identical benchmarks."

**0.1.2:** "Preview your benchmark before committing cloud resources. Dry-run mode is here."

**0.1.3:** "From JSON results to shareable HTML reports. One command."

### Phase 2: TPC + Primitives + Experimental (Weeks 5-8)

**0.2.0:** "TPC-DI: The complete TPC suite. H, DS, and now DI for ETL pipelines."

**0.2.1:** "Which exact operation is slow? Read, Write, Transaction Primitives isolate the answer."

**0.2.2:** "Experimental: TPC-Havoc + TPC-H Skew. Stress test your optimizer."

**0.2.3:** "More experimental: TPC-DS OBT + Data Vault. Alternative schema patterns."

### Phase 3: Cloud I + Academic (Weeks 9-12)

**0.3.0:** "Snowflake + Star Schema Benchmark. Cloud meets academia's classic benchmark."

**0.3.1:** "Databricks + JoinOrder. 113 queries to test your optimizer."

**0.3.2:** "BigQuery + AMPLab. Berkeley's big data patterns in the cloud."

**0.3.3:** "Redshift benchmarking. Distribution keys make or break performance."

### Phase 4: Cloud II + Industry/TimeSeries/RealWorld (Weeks 13-16)

**0.4.0:** "ClickHouse Cloud + ClickBench. Real-time analytics meets real-world patterns."

**0.4.1:** "PostgreSQL family + TSBS DevOps. Time-series benchmarking done right."

**0.4.2:** "NYC Taxi + H2ODB + Cost Tracking. Real-world data meets real costs."

**0.4.3:** "CoffeeShop + Tuning. 18 benchmarks, all 7 categories, fully configurable."

### Phase 5: DataFrame (Weeks 17-20)

**0.5.0:** "SQL vs DataFrame: Same benchmark, different paradigm. Compare Polars and Pandas."

**0.5.1:** "When SQL engines grow DataFrame APIs. Benchmark the hybrid approach."

**0.5.2:** "Scale beyond one machine. PySpark and Dask DataFrame benchmarking."

**0.5.3:** "GPU-accelerated DataFrames. cuDF benchmarks are here."

### Phase 6: Query Engines + Azure (Weeks 21-24)

**0.6.0:** "One benchmark, three query engines. Trino, Presto, and Spark compared."

**0.6.1:** "Microsoft analytics stack: Synapse vs Fabric. Independent benchmarks."

**0.6.2:** "Serverless analytics economics. Athena and Firebolt benchmarking."

**0.6.3:** "21 SQL platforms, complete coverage. The platform selection guide."

### Phase 7: Stable (Weeks 25-26)

**0.9.0:** "BenchBox RC: 21 platforms, 18 benchmarks, one tool. Call for testers."

**1.0.0:** "BenchBox 1.0: Production ready. The benchmarking tool the industry needed."

---

*Document Version: 1.0*
*Created: 2026-01-12*
*Status: ACTIVE - Primary rollout planning document*

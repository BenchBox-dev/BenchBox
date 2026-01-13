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
| Industry + Academic + Optimizer Stress | 5-8 | 0.2.0 - 0.2.3 | Practitioner and research benchmarks |
| Cloud I + Primitives + TPC-DI | 9-12 | 0.3.0 - 0.3.3 | Major cloud platforms + micro-benchmarks + ETL |
| Cloud II + Data Modelling + Time Series + Real World | 13-16 | 0.4.0 - 0.4.3 | Extended cloud + schema variants + temporal + real data |
| DataFrame | 17-20 | 0.5.0 - 0.5.3 | DataFrame paradigm |
| Query Engines + Azure | 21-24 | 0.6.0 - 0.6.3 | Trino, Presto, Spark, Azure |
| Stable | 25-26 | 0.9.0, 1.0.0 | Production ready |

**Key Design Principle:** All 20 SQL-based benchmarks are revealed before DataFrame mode (Week 17):
1. **TPC Essentials** (2): TPC-H, TPC-DS
2. **Industry** (3): ClickBench, H2ODB, CoffeeShop
3. **Academic** (3): SSB, AMPLab, JoinOrder
4. **Experimental - Optimizer Stress** (2): TPC-Havoc, TPC-H Skew
5. **Primitives Essential** (2): Read, Write
6. **Primitives Extra** (2): Metadata, Transactions
7. **TPC ETL** (1): TPC-DI
8. **Experimental - Data Modelling** (2): TPC-DS OBT, TPC-H Data Vault
9. **Time Series** (2): TSBS DevOps, TSBS IoT
10. **Real World** (1): NYC Taxi

**Future Real World Datasets** (post-1.0): Stack Overflow, Flight Data, GitHub Archive, Wikipedia Pageviews

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

### Phase 2: Industry + Academic + Optimizer Stress (Weeks 5-8)

**Theme:** "Practitioner and Research Benchmarks"

*This phase adds real-world industry benchmarks, academic research benchmarks, and optimizer stress tests.*

#### Week 5 - v0.2.0
**Headline:** "Industry Benchmarks: ClickBench, H2ODB, CoffeeShop"

**Features Revealed:**
- **ClickBench** - 43 analytical queries (web analytics patterns)
- **H2ODB Benchmark** - data science groupby/join patterns
- **CoffeeShop Benchmark** - CRUD transaction patterns
- Industry workload profiles

**Marketing Angle:** "Real-world benchmarks from practitioners who run databases in production"

**Blog Post:** "Industry Benchmarks: Beyond TPC Standards"

**Category:** Industry (benchmarks from practitioners)

---

#### Week 6 - v0.2.1
**Headline:** "Academic Benchmarks: SSB, AMPLab, JoinOrder"

**Features Revealed:**
- **Star Schema Benchmark (SSB)** - 13 queries (OLAP patterns)
- **AMPLab Big Data Benchmark** - 8 queries (scan/aggregate/join)
- **JoinOrder Benchmark** - 113 queries for optimizer testing
- Research-grade workload analysis

**Marketing Angle:** "Research benchmarks from academia for rigorous analysis"

**Blog Post:** "Academic Benchmarks: Research-Grade Performance Testing"

**Category:** Academic (research benchmarks from academia)

---

#### Week 7 - v0.2.2
**Headline:** "Experimental: TPC-Havoc Optimizer Stress"

**Features Revealed:**
- TPC-Havoc benchmark (220 query variants)
- Optimizer robustness testing
- Query plan stability analysis
- Cardinality estimation stress tests

**Marketing Angle:** "Stress test your optimizer with 220 query variants"

**Blog Post:** "TPC-Havoc: Breaking Your Query Optimizer"

**Category:** Experimental - Optimizer Stress

---

#### Week 8 - v0.2.3
**Headline:** "Experimental: TPC-H Skew Data Distributions"

**Features Revealed:**
- TPC-H Skew benchmark (configurable data distributions)
- Zipfian and power-law distributions
- Join skew testing
- Statistics accuracy validation

**Marketing Angle:** "Test how your database handles skewed real-world data"

**Blog Post:** "TPC-H Skew: When Uniform Data Is a Lie"

**Category:** Experimental - Optimizer Stress

---

### Phase 3: Cloud I + Primitives + TPC-DI (Weeks 9-12)

**Theme:** "Enterprise Cloud + Micro-Benchmarks + ETL"

*Each cloud platform release is paired with Primitives or TPC-DI benchmarks for deep analysis.*

#### Week 9 - v0.3.0
**Headline:** "Snowflake + Primitives Essential"

**Features Revealed:**
- Snowflake platform adapter
- Warehouse configuration
- Result cache handling
- Clustering support
- `[snowflake]` extra installation
- **Read Primitives** (90+ queries) - scan, filter, aggregation isolation
- **Write Primitives** (117 operations) - insert, update, delete patterns

**Marketing Angle:** "Benchmark Snowflake at the operation level"

**Blog Post:** "Snowflake + Primitives: Finding the Bottleneck"

**Category:** Primitives Essential (fundamental database operations)

---

#### Week 10 - v0.3.1
**Headline:** "Databricks + Primitives Extra"

**Features Revealed:**
- Databricks platform adapter
- SQL Warehouses + Unity Catalog
- Photon engine support
- AQE and Z-ordering
- DBFS integration
- **Metadata Primitives** - catalog, schema, table operations
- **Transaction Primitives** (8 ACID tests) - isolation level testing

**Marketing Angle:** "Test Databricks metadata and transaction handling"

**Blog Post:** "Databricks: Metadata and ACID Under the Microscope"

**Category:** Primitives Extra (metadata and transactions)

---

#### Week 11 - v0.3.2
**Headline:** "BigQuery + TPC-DI ETL Benchmark"

**Features Revealed:**
- BigQuery platform adapter
- Clustering and partitioning
- Slot-based execution
- GCS staging integration
- Regional deployment
- **TPC-DI benchmark** (ETL/integration workflows)

**Marketing Angle:** "BigQuery ETL benchmarking with TPC-DI"

**Blog Post:** "BigQuery + TPC-DI: ETL Performance at Scale"

**Category:** TPC ETL (data integration benchmark)

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

*Note: Primitives and TPC-DI complete. Data Modelling benchmarks begin in Phase 4.*

---

### Phase 4: Cloud II + Data Modelling + Time Series + Real World (Weeks 13-16)

**Theme:** "Complete Cloud + Schema Variants + Temporal + Real Data"

*This phase completes cloud coverage and adds data modelling experiments, time series, and real-world datasets.*

#### Week 13 - v0.4.0
**Headline:** "ClickHouse Cloud + Data Modelling Experiments"

**Features Revealed:**
- ClickHouse platform adapter (Cloud mode)
- TLS support
- Native protocol
- Multi-node cluster support
- **TPC-DS OBT** (One Big Table denormalized) - alternative schema
- **TPC-H Data Vault** (dimensional modeling) - schema pattern testing

**Marketing Angle:** "ClickHouse Cloud with experimental schema patterns"

**Blog Post:** "ClickHouse + Data Modelling: When Denormalization Wins"

**Category:** Experimental - Data Modelling (alternative schema patterns)

*Note: ClickHouse-local was released in Week 1. This release adds cloud connectivity.*

---

#### Week 14 - v0.4.1
**Headline:** "PostgreSQL + TimescaleDB + Time Series Benchmarks"

**Features Revealed:**
- PostgreSQL platform adapter
- TimescaleDB platform adapter
- Hypertable support
- Time-series optimizations
- Tuning configurations
- **TSBS DevOps Benchmark** - infrastructure monitoring workload
- **TSBS IoT Benchmark** - sensor data ingestion patterns

**Marketing Angle:** "Time-series benchmarking: DevOps and IoT workloads"

**Blog Post:** "PostgreSQL Family: Time-Series at Scale"

**Category:** Time Series (temporal data workloads)

---

#### Week 15 - v0.4.2
**Headline:** "Cost Tracking + NYC Taxi Real World Dataset"

**Features Revealed:**
- Per-query cost estimation
- Platform cost tracking (Snowflake, Databricks, BigQuery, Redshift, Athena)
- Cost comparison reports
- **NYC Taxi Benchmark** - real-world trip data analysis (1B+ records)

**Marketing Angle:** "Real-world data meets real cost tracking"

**Blog Post:** "Cost-Aware Benchmarking: Performance Per Dollar"

**Category:** Real World (actual production datasets)

---

#### Week 16 - v0.4.3
**Headline:** "Tuning + Validation Modes"

**Features Revealed:**
- Tuning modes (tuned, notuning, auto, custom YAML)
- 5 validation modes (exact, loose, range, disabled, full)
- PK/FK/index configuration
- Platform-specific tuning (clustering, distribution)

**Marketing Angle:** "All 20 benchmarks, fully configurable"

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
| 1 | 0.1.0 | TPC Essentials | TPC-H, TPC-DS | 2 |
| 5 | 0.2.0 | Industry | ClickBench, H2ODB, CoffeeShop | 5 |
| 6 | 0.2.1 | Academic | SSB, AMPLab, JoinOrder | 8 |
| 7 | 0.2.2 | Experimental - Optimizer Stress | TPC-Havoc | 9 |
| 8 | 0.2.3 | Experimental - Optimizer Stress | TPC-H Skew | 10 |
| 9 | 0.3.0 | Primitives Essential | Read, Write | 12 |
| 10 | 0.3.1 | Primitives Extra | Metadata, Transactions | 14 |
| 11 | 0.3.2 | TPC ETL | TPC-DI | 15 |
| 13 | 0.4.0 | Experimental - Data Modelling | TPC-DS OBT, TPC-H Data Vault | 17 |
| 14 | 0.4.1 | Time Series | TSBS DevOps, TSBS IoT | 19 |
| 15 | 0.4.2 | Real World | NYC Taxi | 20 |

**Benchmark Release Order:**
1. **TPC Essentials** (2): TPC-H, TPC-DS — Core analytical benchmarks
2. **Industry** (3): ClickBench, H2ODB, CoffeeShop — Practitioner benchmarks
3. **Academic** (3): SSB, AMPLab, JoinOrder — Research benchmarks
4. **Experimental - Optimizer Stress** (2): TPC-Havoc, TPC-H Skew — Query optimizer testing
5. **Primitives Essential** (2): Read, Write — Fundamental operations
6. **Primitives Extra** (2): Metadata, Transactions — Extended operations
7. **TPC ETL** (1): TPC-DI — Data integration benchmark
8. **Experimental - Data Modelling** (2): TPC-DS OBT, TPC-H Data Vault — Schema variants
9. **Time Series** (2): TSBS DevOps, TSBS IoT — Temporal workloads
10. **Real World** (1): NYC Taxi — Production datasets

**Future Real World Datasets** (post-1.0): Stack Overflow, Flight Data, GitHub Archive, Wikipedia Pageviews

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
| 5 | 0.2.0 | Industry Benchmarks (ClickBench, H2ODB, CoffeeShop) | Practitioner community focus |
| 6 | 0.2.1 | Academic Benchmarks (SSB, AMPLab, JoinOrder) | Research/database community |
| 9 | 0.3.0 | Snowflake + Primitives (Cloud launch) | Enterprise/cloud audience |
| 11 | 0.3.2 | TPC-DI (Complete TPC Suite) | ETL/data engineering community |
| 13 | 0.4.0 | ClickHouse Cloud + Data Modelling | Real-time analytics community |
| 15 | 0.4.2 | All 20 Benchmarks Complete | "Complete benchmark suite" messaging |
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
| 1 | 0.1.0 | **Initial Launch** | DuckDB, ClickHouse-local | TPC-H, TPC-DS (TPC Essentials) |
| 2 | 0.1.1 | SQLite | SQLite | — |
| 3 | 0.1.2 | DataFusion + Dry-Run | DataFusion | — |
| 4 | 0.1.3 | Compression + Export | — | — |
| 5 | 0.2.0 | **Industry Benchmarks** | — | ClickBench, H2ODB, CoffeeShop (Industry) |
| 6 | 0.2.1 | **Academic Benchmarks** | — | SSB, AMPLab, JoinOrder (Academic) |
| 7 | 0.2.2 | Optimizer Stress | — | TPC-Havoc (Experimental) |
| 8 | 0.2.3 | Optimizer Stress | — | TPC-H Skew (Experimental) |
| 9 | 0.3.0 | **Snowflake + Primitives Essential** | Snowflake | Read, Write (Primitives) |
| 10 | 0.3.1 | Databricks + Primitives Extra | Databricks | Metadata, Transactions (Primitives) |
| 11 | 0.3.2 | BigQuery + TPC-DI | BigQuery | TPC-DI (TPC ETL) |
| 12 | 0.3.3 | Redshift | Redshift | — |
| 13 | 0.4.0 | ClickHouse Cloud + Data Modelling | ClickHouse Cloud | TPC-DS OBT, TPC-H Data Vault (Experimental) |
| 14 | 0.4.1 | PostgreSQL + Time Series | PostgreSQL, TimescaleDB | TSBS DevOps, TSBS IoT (Time Series) |
| 15 | 0.4.2 | **All 20 Benchmarks Complete** | — | NYC Taxi (Real World) |
| 16 | 0.4.3 | Tuning + Validation | — | — |
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

**Future Real World Datasets** (post-1.0): Stack Overflow, Flight Data, GitHub Archive, Wikipedia Pageviews

---

## Appendix B: Social Media Hooks by Release

### Phase 1: Foundation (Weeks 1-4)

**0.1.0:** "Compare DuckDB vs ClickHouse on TPC-H and TPC-DS. Two platforms, two benchmarks, three commands."

**0.1.1:** "SQLite joins the comparison. Three local engines, identical benchmarks."

**0.1.2:** "Preview your benchmark before committing cloud resources. Dry-run mode is here."

**0.1.3:** "From JSON results to shareable HTML reports. One command."

### Phase 2: Industry + Academic + Optimizer Stress (Weeks 5-8)

**0.2.0:** "Beyond TPC: ClickBench, H2ODB, CoffeeShop. Industry benchmarks from practitioners who run databases in production."

**0.2.1:** "Research-grade benchmarks: SSB star schemas, AMPLab big data patterns, 113 JoinOrder optimizer tests."

**0.2.2:** "Your optimizer passed TPC-H. Can it handle 220 query variants? TPC-Havoc finds out."

**0.2.3:** "Real data is skewed. Now your benchmarks can be too. TPC-H Skew with Zipfian distributions."

### Phase 3: Cloud I + Primitives + TPC-DI (Weeks 9-12)

**0.3.0:** "Snowflake + Primitives. Benchmark cloud platforms at the operation level. Read, Write, isolated."

**0.3.1:** "Databricks + Metadata/Transactions. Test catalog operations and ACID guarantees."

**0.3.2:** "BigQuery + TPC-DI. Complete TPC suite with ETL benchmarking on cloud scale."

**0.3.3:** "Redshift benchmarking with proper distribution keys. Cloud coverage continues."

### Phase 4: Cloud II + Data Modelling + Time Series + Real World (Weeks 13-16)

**0.4.0:** "ClickHouse Cloud + Data Modelling. TPC-DS OBT vs normalized. When denormalization wins."

**0.4.1:** "PostgreSQL + TimescaleDB + Time Series. TSBS DevOps and IoT workloads."

**0.4.2:** "NYC Taxi: 1 billion real trips benchmarked. Performance per dollar with cost tracking."

**0.4.3:** "20 benchmarks, fully configurable. Tuning modes and validation. The complete suite before DataFrame."

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

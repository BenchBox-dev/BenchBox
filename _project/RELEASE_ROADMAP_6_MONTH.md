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
| Academic Benchmarks | 5-8 | 0.2.0 - 0.2.3 | TPC benchmark suite expansion |
| Cloud I + Industry | 9-12 | 0.3.0 - 0.3.3 | Major cloud platforms + SSB, ClickBench |
| Cloud II + Industry | 13-16 | 0.4.0 - 0.4.3 | Extended cloud + remaining benchmarks |
| DataFrame | 17-20 | 0.5.0 - 0.5.3 | DataFrame paradigm |
| Advanced | 21-24 | 0.6.0 - 0.6.3 | Query engines + Azure |
| Stable | 25-26 | 0.9.0, 1.0.0 | Production ready |

**Key Design Principle:** All 18+ SQL-based benchmarks are revealed before DataFrame mode (Week 17) to ensure maximum utility on SQL platforms from launch.

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

### Phase 2: Academic Benchmarks (Weeks 5-8)

**Theme:** "The Complete TPC Suite"

*All TPC and academic benchmarks are revealed in this phase, establishing BenchBox as a comprehensive TPC benchmarking tool.*

#### Week 5 - v0.2.0
**Headline:** "TPC-DI: Benchmark Your ETL Pipelines"

**Features Revealed:**
- TPC-DI benchmark (ETL/integration workflows)
- Multi-phase data integration testing
- Historical data loading patterns
- Incremental update benchmarking

**Marketing Angle:** "The benchmark for data integration workloads"

**Blog Post:** "TPC-DI: Finally, a Benchmark for ETL"

---

#### Week 6 - v0.2.1
**Headline:** "TPC-Havoc: Stress Test Your Query Optimizer"

**Features Revealed:**
- TPC-Havoc benchmark (220 query variants)
- 10 structural variants per TPC-H query
- Optimizer robustness testing
- Query plan stability analysis

**Marketing Angle:** "Discover how your optimizer handles query variations"

**Blog Post:** "TPC-Havoc: The Benchmark That Breaks Optimizers"

---

#### Week 7 - v0.2.2
**Headline:** "TPC Variants: Skew, OBT, and Data Vault"

**Features Revealed:**
- TPC-H Skew (configurable data distributions)
- TPC-DS OBT (One Big Table denormalized)
- TPC-H Data Vault (dimensional modeling)
- Alternative schema patterns

**Marketing Angle:** "Test your database with realistic data distributions"

**Blog Post:** "Beyond Standard TPC: Real-World Data Patterns"

---

#### Week 8 - v0.2.3
**Headline:** "JoinOrder + Primitives: Deep Performance Analysis"

**Features Revealed:**
- JoinOrder benchmark (join optimization stress test)
- Read Primitives (90+ queries)
- Write Primitives (117 operations)
- Transaction Primitives (8 ACID tests)

**Marketing Angle:** "Identify exactly which operations are slow"

**Blog Post:** "Micro-Benchmarks: When You Need to Know WHY It's Slow"

---

### Phase 3: Cloud I + Industry Benchmarks (Weeks 9-12)

**Theme:** "Enterprise Cloud Benchmarking + Real-World Workloads"

*Each cloud platform release is paired with an industry benchmark, enabling immediate real-world testing on cloud infrastructure.*

#### Week 9 - v0.3.0
**Headline:** "Snowflake + Star Schema Benchmark"

**Features Revealed:**
- Snowflake platform adapter
- Warehouse configuration
- Result cache handling
- Clustering support
- `[snowflake]` extra installation
- **Star Schema Benchmark (SSB)** - 13 queries

**Marketing Angle:** "Benchmark Snowflake with TPC and real-world star schema workloads"

**Blog Post:** "Snowflake Benchmarking: TPC-H, TPC-DS, and SSB Compared"

---

#### Week 10 - v0.3.1
**Headline:** "Databricks + ClickBench"

**Features Revealed:**
- Databricks platform adapter
- SQL Warehouses + Unity Catalog
- Photon engine support
- AQE and Z-ordering
- DBFS integration
- **ClickBench** - 43 analytical queries (web analytics patterns)

**Marketing Angle:** "Databricks benchmarking with real-world web analytics queries"

**Blog Post:** "Databricks: From TPC to ClickBench"

---

#### Week 11 - v0.3.2
**Headline:** "BigQuery + NYC Taxi Benchmark"

**Features Revealed:**
- BigQuery platform adapter
- Clustering and partitioning
- Slot-based execution
- GCS staging integration
- Regional deployment
- **NYC Taxi Benchmark** - real-world trip data analysis

**Marketing Angle:** "BigQuery benchmarking with 1B+ row real-world data"

**Blog Post:** "BigQuery: Synthetic vs Real-World Benchmarks"

---

#### Week 12 - v0.3.3
**Headline:** "Amazon Redshift + AMPLab Benchmark"

**Features Revealed:**
- Redshift platform adapter
- Distribution keys
- Sort keys
- S3 COPY integration
- Spectrum support
- **AMPLab Big Data Benchmark** - scan/aggregate/join patterns

**Marketing Angle:** "Redshift benchmarking with Berkeley's big data patterns"

**Blog Post:** "Redshift: Distribution Keys Make or Break Performance"

---

### Phase 4: Cloud II + Industry Benchmarks (Weeks 13-16)

**Theme:** "Complete Cloud Coverage + Complete Benchmark Suite"

*This phase completes both cloud platform coverage and the industry benchmark suite, ensuring all 18+ benchmarks are available before DataFrame mode.*

#### Week 13 - v0.4.0
**Headline:** "ClickHouse Cloud + H2ODB Benchmark"

**Features Revealed:**
- ClickHouse platform adapter (Cloud mode)
- TLS support
- Native protocol
- Multi-node cluster support
- **H2ODB Benchmark** - groupby/join patterns from H2O.ai

**Marketing Angle:** "ClickHouse Cloud benchmarking with H2O's data science patterns"

**Blog Post:** "ClickHouse Cloud: Real-Time Analytics at Scale"

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

---

#### Week 15 - v0.4.2
**Headline:** "Cost Tracking + CoffeeShop Benchmark"

**Features Revealed:**
- Per-query cost estimation
- Platform cost tracking (Snowflake, Databricks, BigQuery, Redshift, Athena)
- Cost comparison reports
- TCO analysis support
- **CoffeeShop Benchmark** - CRUD transaction patterns

**Marketing Angle:** "Performance AND cost: The complete picture"

**Blog Post:** "Cost-Aware Benchmarking: Performance Per Dollar"

---

#### Week 16 - v0.4.3
**Headline:** "Tuning + Validation: Complete Benchmark Configuration"

**Features Revealed:**
- Tuning modes (tuned, notuning, auto, custom YAML)
- 5 validation modes (exact, loose, range, disabled, full)
- PK/FK/index configuration
- Platform-specific tuning (clustering, distribution)

**Marketing Angle:** "All 18 benchmarks, fully configurable"

**Blog Post:** "The Tuning Gap: Default vs Optimized Performance"

**Milestone:** *All SQL-based benchmarks now available (18 total). DataFrame mode begins next phase.*

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
| 1 | 0.1.0 | Academic | TPC-H, TPC-DS | 2 |
| 5 | 0.2.0 | Academic | TPC-DI | 3 |
| 6 | 0.2.1 | Academic | TPC-Havoc | 4 |
| 7 | 0.2.2 | Academic | TPC-H Skew, TPC-DS OBT, TPC-H Data Vault | 7 |
| 8 | 0.2.3 | Academic + Primitives | JoinOrder, Read/Write/Transaction Primitives | 11 |
| 9 | 0.3.0 | Industry | SSB | 12 |
| 10 | 0.3.1 | Industry | ClickBench | 13 |
| 11 | 0.3.2 | Industry | NYC Taxi | 14 |
| 12 | 0.3.3 | Industry | AMPLab | 15 |
| 13 | 0.4.0 | Industry | H2ODB | 16 |
| 14 | 0.4.1 | Industry | TSBS DevOps | 17 |
| 15 | 0.4.2 | Industry | CoffeeShop | 18 |

**Benchmark Categories:**
- **Academic (TPC):** TPC-H, TPC-DS, TPC-DI, TPC-Havoc, TPC-H Skew, TPC-DS OBT, TPC-H Data Vault, JoinOrder
- **Industry:** SSB, ClickBench, NYC Taxi, AMPLab, H2ODB, TSBS DevOps, CoffeeShop
- **Primitives:** Read, Write, Transaction (micro-benchmarks)

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
| 5 | 0.2.0 | TPC-DI (Complete Academic Suite) | Database/ETL community focus |
| 9 | 0.3.0 | Snowflake + SSB (Cloud + Industry) | Enterprise/cloud audience |
| 13 | 0.4.0 | ClickHouse Cloud + H2ODB | Real-time analytics community |
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

| Week | Version | Primary Feature | New Platforms | New Benchmarks |
|------|---------|-----------------|---------------|----------------|
| 1 | 0.1.0 | **Initial Launch** | DuckDB, ClickHouse-local | TPC-H, TPC-DS |
| 2 | 0.1.1 | SQLite | SQLite | — |
| 3 | 0.1.2 | DataFusion + Dry-Run | DataFusion | — |
| 4 | 0.1.3 | Compression + Export | — | — |
| 5 | 0.2.0 | **TPC-DI** | — | TPC-DI |
| 6 | 0.2.1 | TPC-Havoc | — | TPC-Havoc |
| 7 | 0.2.2 | TPC Variants | — | TPC-H Skew, TPC-DS OBT, TPC-H Data Vault |
| 8 | 0.2.3 | JoinOrder + Primitives | — | JoinOrder, Primitives |
| 9 | 0.3.0 | **Snowflake + SSB** | Snowflake | SSB |
| 10 | 0.3.1 | Databricks + ClickBench | Databricks | ClickBench |
| 11 | 0.3.2 | BigQuery + NYC Taxi | BigQuery | NYC Taxi |
| 12 | 0.3.3 | Redshift + AMPLab | Redshift | AMPLab |
| 13 | 0.4.0 | ClickHouse Cloud + H2ODB | ClickHouse Cloud | H2ODB |
| 14 | 0.4.1 | PostgreSQL + TSBS | PostgreSQL, TimescaleDB | TSBS DevOps |
| 15 | 0.4.2 | Cost Tracking + CoffeeShop | — | CoffeeShop |
| 16 | 0.4.3 | **All 18 Benchmarks Complete** | — | — |
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

### Phase 2: Academic Benchmarks (Weeks 5-8)

**0.2.0:** "TPC-DI: Finally, a benchmark for ETL pipelines. Data integration workloads now testable."

**0.2.1:** "Your optimizer passed TPC-H. Can it handle 220 query variants? TPC-Havoc finds out."

**0.2.2:** "Real data is skewed. Now your benchmarks can be too. TPC-H Skew, TPC-DS OBT, Data Vault."

**0.2.3:** "Which exact operation is slow? Primitives + JoinOrder isolate the answer."

### Phase 3: Cloud I + Industry (Weeks 9-12)

**0.3.0:** "Snowflake + Star Schema Benchmark. Cloud benchmarking with real-world star schemas."

**0.3.1:** "Databricks + ClickBench. Test Photon with web analytics patterns."

**0.3.2:** "BigQuery + NYC Taxi. 1 billion real trips benchmarked."

**0.3.3:** "Redshift + AMPLab. Berkeley's big data patterns on AWS."

### Phase 4: Cloud II + Industry (Weeks 13-16)

**0.4.0:** "ClickHouse Cloud + H2ODB. Real-time analytics with data science workloads."

**0.4.1:** "PostgreSQL family + TSBS DevOps. Time-series benchmarking done right."

**0.4.2:** "Performance per dollar. Cost tracking + CoffeeShop CRUD benchmark."

**0.4.3:** "18 benchmarks, fully configurable. The complete suite before DataFrame mode."

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

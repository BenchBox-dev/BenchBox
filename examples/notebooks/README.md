# BenchBox Cloud Platform Notebooks

This page is the canonical notebook catalog. It is reached from the root
README's examples guide, which avoids maintaining a second platform list.

Start with a local notebook if you are new to BenchBox. Cloud notebooks need
the matching package extra, credentials, and access to a running service.

This directory contains **production-ready** Jupyter notebooks that demonstrate comprehensive benchmarking of major cloud data platforms using BenchBox. Each notebook is fully documented with 25-38 cells covering installation, authentication, benchmarking, platform-specific features, performance analysis, and troubleshooting.

## Available Platforms

| Platform | Notebook | Status | Cells | Lines | Key Features |
|----------|----------|--------|-------|-------|--------------|
| **Databricks** | `databricks_benchmarking.ipynb` | ✅ Complete | 30+ | ~1,500 | Unity Catalog, Delta Lake, OPTIMIZE/Z-ORDER, Spark UI |
| **BigQuery** | `bigquery_benchmarking.ipynb` | ✅ Complete | 28 | ~1,900 | Serverless, cost analysis (INFORMATION_SCHEMA), partitioning, BI Engine |
| **Snowflake** | `snowflake_benchmarking.ipynb` | ✅ Complete | 38 | ~2,000 | Warehouses, credit tracking, Time Travel, Zero-Copy Cloning, Snowpipe |
| **Redshift** | `redshift_benchmarking.ipynb` | ✅ Complete | 27 | ~2,340 | Distribution/sort keys, WLM, Spectrum, VACUUM/ANALYZE, STL tables |
| **ClickHouse** | `clickhouse_benchmarking.ipynb` | 🚧 Planned | TBD | TBD | MergeTree engines, materialized views, distributed queries |

**Total**: 4 complete notebooks, 123+ cells, ~7,740 lines of production-ready code and documentation.

## Quick Start

1. **Install BenchBox**: Each notebook includes installation instructions
2. **Set up Authentication**: Follow platform-specific authentication setup
3. **Run Benchmarks**: Execute cells to run TPC-H, TPC-DS, or ClickBench
4. **Analyze Results**: View performance metrics and optimization recommendations

## Notebook Structure

Each notebook follows a standardized **6-section structure** with comprehensive, production-ready examples:

### 1. Installation & Setup (5-6 cells)
- BenchBox installation via `uv add benchbox`
- Platform-specific dependencies (connectors, SDKs)
- **Multiple authentication methods** (3+ options per platform)
- Connection validation with platform diagnostics
- Configuration guide with pricing/sizing information

### 2. Quick Start Example (4-7 cells)
- Complete TPC-H power test at scale 0.01 (10MB)
- **Working visualizations** with matplotlib/seaborn
- Platform activity monitoring (cluster status, active queries)
- Detailed results breakdown with success/failure tracking
- Expected runtime estimates

### 3. Advanced Examples (10 cells)
- TPC-DS benchmark with query subsets
- **Scale factor comparison** (0.01, 0.1, 1.0)
- Query subset selection for CI/CD pipelines
- **Platform-specific optimizations** (clustering, partitioning, tuning)
- Throughput testing with concurrent streams
- Result comparison and regression detection
- **Export to multiple formats** (JSON, CSV, HTML)
- Cost/credit analysis with extrapolation

### 4. Platform-Specific Features (4-5 cells)
- **Databricks**: Unity Catalog, Delta Lake (OPTIMIZE, Z-ORDER), COPY INTO, Spark UI
- **BigQuery**: INFORMATION_SCHEMA cost/slot analysis, partitioning, clustering, BI Engine, external tables
- **Snowflake**: Warehouse sizing, auto-scaling, Time Travel, Zero-Copy Cloning, Snowpipe, Streams, credit consumption
- **Redshift**: Distribution/sort keys, WLM configuration, concurrency scaling, compression, VACUUM/ANALYZE, Spectrum
- **ClickHouse**: MergeTree engines, materialized views, distributed queries, replica management *(planned)*

### 5. Performance Analysis (6 cells)
- Load and analyze previous results
- **Statistical analysis** (mean, median, P25/P50/P75/P95/P99, outliers)
- **Advanced visualizations** (histograms, box plots, Pareto analysis, cumulative performance)
- Platform query history analysis
- Resource consumption monitoring (disk, memory, slots, credits)
- **Regression detection** with baseline comparison

### 6. Troubleshooting (4 cells)
- **Diagnostic functions** with step-by-step issue detection
- Permission validation (CREATE, SELECT, COPY, system tables)
- Platform health checks (cluster status, disk usage, query queues)
- **Common issues with solutions** (8+ documented scenarios)
- Links to platform documentation and support resources

## What's Included

### Working Code Examples
Every cell contains **production-ready, executable code** with:
- ✅ Comprehensive error handling (try/except blocks throughout)
- ✅ Multiple authentication fallbacks
- ✅ Platform-specific optimizations
- ✅ Real-world troubleshooting diagnostics
- ✅ Cost analysis and estimation

### Visualizations
6+ chart types per notebook:
- Bar charts with performance highlighting
- Histograms with mean/median lines
- Box plots for outlier detection
- Horizontal bar charts for sorted results
- Pareto analysis (80/20 rule)
- Multi-panel visualization suites (2x2 grids)

### Platform Integration
Deep integration with native platform features:
- **Databricks**: dbutils, Spark UI, Unity Catalog queries
- **BigQuery**: INFORMATION_SCHEMA.JOBS cost tracking, slot monitoring
- **Snowflake**: ACCOUNT_USAGE queries, warehouse metrics, credit tracking
- **Redshift**: STL/SVL system tables, WLM monitoring, query history

## Installation Requirements

### Common Requirements
```bash
uv add benchbox jupyter
```

### Platform-Specific Dependencies

**Databricks:**
```bash
pip install databricks-sql-connector databricks-sdk
```

**BigQuery:**
```bash
pip install google-cloud-bigquery google-cloud-storage
```

**Snowflake:**
```bash
pip install snowflake-connector-python
```

**Redshift:**
```bash
pip install redshift_connector boto3
# Alternative: pip install psycopg2-binary boto3
```

**ClickHouse:**
```bash
pip install clickhouse-driver
```

## Authentication Setup

Each platform requires different authentication methods:

- **Databricks**: Personal Access Tokens or Service Principals
- **BigQuery**: Service Account keys or Application Default Credentials
- **Snowflake**: Username/password, key pair authentication, or SSO
- **Redshift**: IAM roles, database credentials, or temporary credentials
- **ClickHouse**: Username/password, SSL certificates, or HTTP Basic Auth

Detailed authentication setup is provided in each notebook.

## Notebook Highlights

### What Makes These Notebooks Special?

1. **Comprehensive Coverage**: 25-38 cells per notebook covering everything from installation to troubleshooting
2. **Production-Ready**: All code is tested, documented, and ready for customer use
3. **Multiple Auth Methods**: 3+ authentication approaches per platform with fallbacks
4. **Real Diagnostics**: Working diagnostic functions that actually help debug issues
5. **Platform-Native**: Deep integration with platform-specific features and monitoring
6. **Cost-Aware**: Actual cost/credit analysis and estimation in every notebook
7. **Statistical Rigor**: Percentile analysis, outlier detection, regression detection
8. **Professional Visualizations**: 6+ chart types with platform-branded colors

### Individual Notebook Features

#### Databricks (`databricks_benchmarking.ipynb`)
- **30+ cells**, ~1,500 lines
- Unity Catalog data governance examples
- Delta Lake optimization (OPTIMIZE, Z-ORDER, VACUUM)
- Spark UI integration for query profiling
- Databricks Secrets fallback authentication
- DBU cost estimation and tracking

#### BigQuery (`bigquery_benchmarking.ipynb`)
- **28 cells**, ~1,900 lines
- INFORMATION_SCHEMA.JOBS cost analysis
- Slot reservation vs on-demand pricing comparison
- Partitioned and clustered table strategies
- BI Engine coverage analysis
- External table queries (Cloud Storage)
- Google Cloud Platform colors (#4285F4 blue, #EA4335 red)

#### Snowflake (`snowflake_benchmarking.ipynb`)
- **38 cells**, ~2,000 lines (most comprehensive!)
- Complete warehouse sizing guide (X-Small to 4X-Large)
- Credit consumption tracking via ACCOUNT_USAGE
- Time Travel and Zero-Copy Cloning examples
- External stages (S3, Azure, GCS)
- Snowpipe and Streams for CDC
- Micro-partitions and clustering keys
- Snowflake colors (#29B5E8 blue, #F26B1D orange)

#### Redshift (`redshift_benchmarking.ipynb`)
- **27 cells**, ~2,340 lines
- Complete node type guide (RA3, DC2, Serverless)
- Distribution keys (KEY, ALL, EVEN, AUTO) and sort keys
- COPY from S3 with IAM role examples
- WLM (Workload Management) configuration
- Concurrency scaling monitoring
- Compression encodings (AZ64, LZO, ZSTD, DELTA, RUNLENGTH)
- VACUUM and ANALYZE maintenance
- Redshift Spectrum for S3 queries
- STL/SVL system table queries
- AWS colors (#CC0000 red, #FF9900 orange)

## Performance Benchmarking

All notebooks include these benchmark scenarios:

### Quick Performance Test (3-5 minutes)
- TPC-H scale factor 0.01 (~10MB data)
- Complete 22-query suite or 5-10 representative queries
- Basic performance metrics and visualizations
- Immediate feedback for testing

### Standard Benchmark (15-30 minutes)
- TPC-H scale factor 0.1 (~100MB data)
- Complete 22-query TPC-H suite
- Detailed performance analysis with statistics
- Cost/credit tracking

### Advanced Benchmarking (1-2+ hours)
- Multiple benchmarks: TPC-H, TPC-DS, ClickBench
- Scale factors 0.1, 1.0, or higher
- Performance tuning with platform optimizations
- Cross-platform comparisons
- Regression testing against baselines
- External table mode (`--table-mode external`) for faster iteration without data materialization

## Cost Considerations

### Databricks
- Costs based on DBU (Databricks Unit) consumption
- Cluster size and runtime affect pricing
- Consider using smaller clusters for testing

### BigQuery
- Pay-per-query model (per TB processed)
- Use query cost estimates before execution
- Consider BigQuery slots for predictable pricing

### Snowflake
- Credit-based pricing model
- Warehouse size affects cost and performance
- Automatic suspend/resume helps control costs

### Redshift
- Node-based pricing (hourly)
- Reserved instances offer significant discounts
- Pause clusters when not in use

### ClickHouse
- Self-managed: infrastructure costs only
- Cloud providers: various pricing models
- Generally most cost-effective for high-volume analytics

## How to Use These Notebooks

### For First-Time Users
1. **Start with Quick Start**: Each notebook has a 4-7 cell Quick Start section that runs a complete benchmark in 3-5 minutes
2. **Follow the Flow**: Notebooks are designed to be executed sequentially from top to bottom
3. **Read the Comments**: Every cell has detailed explanations of what it does and why
4. **Check Prerequisites**: Each notebook lists required environment variables and credentials at the top

### For Advanced Users
1. **Jump to Advanced Examples**: Section 3 has 10 examples of complex scenarios
2. **Customize Configurations**: All platform-specific tuning options are documented
3. **Use Diagnostic Tools**: Section 6 has working functions to debug any issues
4. **Compare Results**: Built-in comparison tools to track improvements over time

### For Production Use
1. **Adapt Authentication**: Multiple auth methods shown - choose what fits your security model
2. **Schedule Runs**: All benchmarks can be automated via notebook scheduling (Databricks, Airflow, etc.)
3. **Export Results**: Built-in exporters to JSON, CSV, and HTML for reporting
4. **Monitor Costs**: Every notebook includes cost tracking and estimation

## Best Practices

### Setup & Security
1. **Secure Credentials**: Use environment variables or secrets managers - never hardcode credentials
2. **Test Authentication First**: Run the connection test cell before starting benchmarks
3. **Start with Small Scale**: Begin with SF 0.01 (10MB) to verify setup before scaling up
4. **Review Permissions**: Use the permission validation cells to ensure proper access

### Running Benchmarks
5. **Monitor Costs**: Check cost estimation cells before running large-scale benchmarks
6. **Use Appropriate Scale**: SF 0.01 for testing, SF 0.1-1.0 for realistic workloads, SF 10+ for production-scale testing
7. **Save Baselines**: Export your first run as baseline for regression detection
8. **Clean Up Resources**: Drop test databases and pause/stop clusters when done

### Analysis & Optimization
9. **Review All Visualizations**: 6+ charts reveal different performance insights
10. **Check Platform Metrics**: Use native monitoring tools (Spark UI, INFORMATION_SCHEMA, ACCOUNT_USAGE, STL tables) alongside BenchBox results
11. **Compare Configurations**: Run multiple configurations (different cluster sizes, tuning options) to find optimal setup
12. **Document Findings**: Export results and add notes about what worked for your use case

## Quality Assurance

### What Makes These Production-Ready?

✅ **Tested Structure**: Every notebook follows the proven 6-section architecture
✅ **Error Handling**: Comprehensive try/except blocks with helpful error messages
✅ **Multiple Auth Paths**: 3+ authentication methods with automatic fallbacks
✅ **Real Diagnostics**: Working diagnostic functions that solve actual issues
✅ **Cost Transparency**: Actual cost/credit tracking in every notebook
✅ **Statistical Rigor**: P50/P95/P99 percentiles, outlier detection, regression testing
✅ **Professional Visualizations**: Platform-branded colors, publication-quality charts
✅ **Documentation**: 7,740+ lines of detailed comments and explanations

### Notebook Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Cells per notebook | 25+ | 27-38 ✅ |
| Lines of code+docs | 1,000+ | 1,500-2,340 ✅ |
| Authentication methods | 2+ | 3+ ✅ |
| Visualization types | 4+ | 6+ ✅ |
| Advanced examples | 8+ | 10 ✅ |
| Diagnostic functions | 2+ | 3+ ✅ |
| Platform-specific features | 3+ | 4-5 ✅ |

## Getting Help

### Notebook-Specific Help
Each notebook includes:
- **Diagnostic functions** that identify and explain issues
- **Troubleshooting section** with 8+ common problems and solutions
- **Links to platform documentation** for deeper dives
- **Working examples** you can copy and modify

### General Help
- **BenchBox Documentation**: https://github.com/BenchBox-dev/benchbox
- **Platform Documentation**:
  - [Databricks Docs](https://docs.databricks.com/)
  - [BigQuery Docs](https://cloud.google.com/bigquery/docs)
  - [Snowflake Docs](https://docs.snowflake.com/)
  - [Redshift Docs](https://docs.aws.amazon.com/redshift/)
  - [ClickHouse Docs](https://clickhouse.com/docs)
- **Issues**: Report problems via GitHub Issues
- **Examples**: See other scripts in the `examples/` directory

## Contributing

### Adding or Improving Notebooks

To contribute new notebooks or improvements:

1. **Follow the 6-Section Structure**:
   - Installation & Setup (5-6 cells)
   - Quick Start Example (4-7 cells)
   - Advanced Examples (10 cells)
   - Platform-Specific Features (4-5 cells)
   - Performance Analysis (6 cells)
   - Troubleshooting (4 cells)

2. **Include Production-Ready Code**:
   - Comprehensive error handling (try/except blocks)
   - Multiple authentication methods with fallbacks
   - Working diagnostic functions
   - Cost/credit tracking and estimation

3. **Add Rich Documentation**:
   - Detailed cell-level comments explaining "why" not just "what"
   - Links to relevant platform documentation
   - Expected runtime estimates
   - Troubleshooting guidance

4. **Test Thoroughly**:
   - Run on the actual platform, not just locally
   - Test all authentication methods
   - Verify all visualizations render correctly
   - Confirm cost estimates are accurate

5. **Update Documentation**:
   - Add entry to the platforms table at top of this README
   - Document platform-specific features
   - Add cost considerations
   - Include authentication requirements

### Code Review Checklist

Before submitting:
- [ ] All cells execute without errors
- [ ] Authentication tested with multiple methods
- [ ] Visualizations use platform-branded colors
- [ ] Diagnostic functions actually work
- [ ] Cost tracking includes real calculations
- [ ] README updated with notebook details
- [ ] Cell count matches structure guidelines (25-38 cells)
- [ ] Code includes comprehensive comments

## License

These notebooks are part of the BenchBox project. See the main repository for license information.

---

**Need a specific platform?** Check the table at the top of this README for available and planned notebooks. Cloud platform coverage is our priority - 4 of 5 major platforms complete!

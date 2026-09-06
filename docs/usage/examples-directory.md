# Examples Directory Guide

```{tags} beginner, reference
```

The BenchBox repository includes a comprehensive `examples/` directory with over 40 practical examples, organized to help you get started quickly and learn advanced patterns progressively.

## Quick Navigation

| I want to... | Start here |
|--------------|-----------|
| Get started in 5 minutes | [`examples/getting_started/local/`](../../examples/getting_started/) |
| Test on a cloud platform | [`examples/getting_started/cloud/`](../../examples/getting_started/) |
| Learn a specific feature | [`examples/features/`](../../examples/features/) |
| Solve a real-world problem | [`examples/use_cases/`](../../examples/use_cases/) |
| Use interactive notebooks | [`examples/notebooks/`](../../examples/notebooks/) |
| Find configuration templates | [`examples/config/`](../../examples/config/) |
| Learn proven patterns | [`examples/PATTERNS.md`](../../examples/PATTERNS.md) |

## Directory Structure

```
examples/
├── getting_started/          # Zero to working in minutes
│   ├── local/               # DuckDB examples (no config needed)
│   │   ├── duckdb_tpch_power.py      # TPC-H benchmark
│   │   ├── duckdb_tpcds_power.py     # TPC-DS benchmark
│   │   ├── duckdb_nyctaxi.py         # NYC Taxi analytics
│   │   └── duckdb_tsbs_devops.py     # TSBS DevOps time-series
│   ├── cloud/               # Databricks & BigQuery examples
│   └── intermediate/        # Targeted patterns
│
├── features/                # Single-feature examples (8 examples)
│   ├── test_types.py       # Power, Throughput, Maintenance tests
│   ├── query_subset.py     # Run specific queries only
│   ├── tuning_comparison.py
│   ├── result_analysis.py
│   ├── multi_platform.py
│   ├── export_formats.py
│   ├── data_validation.py
│   └── performance_monitoring.py
│
├── use_cases/               # Real-world patterns (4 examples)
│   ├── ci_regression_test.py
│   ├── platform_evaluation.py
│   ├── incremental_tuning.py
│   └── cost_optimization.py
│
├── notebooks/               # Interactive examples (11 notebooks)
│   ├── databricks_benchmarking.ipynb
│   ├── bigquery_benchmarking.ipynb
│   ├── snowflake_benchmarking.ipynb
│   ├── platform_comparison.ipynb
│   └── ... (7 more)
│
├── config/                  # Platform configuration templates (15 files)
│   ├── duckdb.yaml
│   ├── databricks.yaml
│   ├── snowflake.yaml
│   └── ... (12 more)
│
├── tunings/                 # Benchmark tuning configurations (34 files)
│   ├── duckdb/             # 24 configs
│   └── databricks/         # 10 configs
│
├── INDEX.md                 # Detailed multi-level navigation
├── PATTERNS.md              # 8 proven workflow patterns
├── unified_runner.py        # Advanced multi-platform tool
└── duckdb_coffeeshop.py    # Minimal "Hello World" example
```

## Which Example Should I Use?

### By Experience Level

**Beginner** (Never used BenchBox):
- Start: `examples/getting_started/local/duckdb_tpch_power.py`
- Zero configuration, runs in seconds
- Uses DuckDB (embedded database, no setup required)

**Intermediate** (Used BenchBox CLI):
- Explore: `examples/features/` for specific capabilities
- Try: `examples/getting_started/cloud/` for cloud platforms
- Read: `examples/PATTERNS.md` for best practices

**Advanced** (Building production workflows):
- Study: `examples/use_cases/` for real-world patterns
- Use: `examples/unified_runner.py` for multi-platform execution
- Reference: `examples/notebooks/` for interactive analysis

### By Goal

**Goal: Test performance locally**
→ `examples/getting_started/local/duckdb_tpch_power.py`

**Goal: Compare platforms**
→ `examples/use_cases/platform_evaluation.py`
→ `examples/notebooks/platform_comparison.ipynb`

**Goal: Set up CI/CD testing**
→ `examples/use_cases/ci_regression_test.py`
→ `examples/use_cases/ci_regression_test_github.yml`

**Goal: Optimize cloud costs**
→ `examples/use_cases/cost_optimization.py`
→ `examples/notebooks/cost_analysis.ipynb`

**Goal: Run specific queries only**
→ `examples/features/query_subset.py`

**Goal: Configure a platform**
→ `examples/config/<platform>.yaml`

## Detailed Guides

For comprehensive documentation of each category:

- **[Getting Started Examples](../../examples/getting_started/README.md)** - Step-by-step beginner guides
- **[Feature Examples](../../examples/features/README.md)** - Learn individual BenchBox capabilities
- **[Use Case Patterns](../../examples/use_cases/README.md)** - Real-world problem solutions
- **[Notebook Examples](../../examples/notebooks/README.md)** - Interactive platform guides
- **[Configuration Templates](../../examples/tunings/README.md)** - Platform setup and tuning
- **[Workflow Patterns](../../examples/programmatic/README.md)** - 8 proven patterns for common tasks

## Example Categories Explained

### 1. Getting Started (7 examples)
**Purpose:** Get from zero to working benchmark in 5 minutes

**Local Examples (no config required):**
- `duckdb_tpch_power.py` - TPC-H analytical benchmark
- `duckdb_tpcds_power.py` - TPC-DS complex queries
- `duckdb_nyctaxi.py` - Real NYC taxi trip analytics
- `duckdb_tsbs_devops.py` - DevOps time-series monitoring

**Progression:**
1. **Local** - DuckDB examples (no config required)
2. **Cloud** - Databricks & BigQuery with credentials
3. **Intermediate** - Query subsets and custom workflows

**Start here if:** You're new to BenchBox

### 2. Feature Examples (8 examples)
**Purpose:** Learn specific BenchBox capabilities in isolation

**Topics covered:**
- Test types (Power, Throughput, Maintenance)
- Query subsetting
- Tuning comparison
- Result analysis
- Multi-platform execution
- Export formats
- Data validation
- Performance monitoring

**Start here if:** You know the basics and want to learn a specific feature

### 3. Use Case Patterns (4 examples)
**Purpose:** Solve real-world problems with proven patterns

**Use cases:**
- CI/CD regression testing
- Platform evaluation and comparison
- Incremental tuning workflows
- Cost optimization

**Start here if:** You're building production workflows

### 4. Notebooks (11 notebooks)
**Purpose:** Interactive exploration and analysis

**Platforms covered:**
- Databricks, BigQuery, Snowflake, Redshift, ClickHouse
- DuckDB, SQLite
- Platform comparison, cost analysis, results visualization

**Start here if:** You prefer interactive exploration

### 5. Configuration Templates (15 files)
**Purpose:** Platform setup references

**Includes:**
- Connection configuration for each platform
- Authentication methods (OAuth, service accounts, key pairs)
- Platform-specific options

**Start here if:** You need to configure a platform

### 6. Tuning Configurations (34 files)
**Purpose:** Benchmark-specific optimizations

**Includes:**
- Tuned vs. notuning configurations
- Platform-specific optimizations
- DuckDB (24 configs), Databricks (10 configs)

**Start here if:** You want to optimize query performance

## Running the Examples

### Prerequisites

```bash
# Install BenchBox
uv add benchbox

# For specific platforms, install extras
uv add benchbox --extra databricks  # Databricks examples
uv add benchbox --extra bigquery    # BigQuery examples
uv add benchbox --extra snowflake   # Snowflake examples
```

### Run a Getting Started Example

```bash
# DuckDB (no configuration needed)
cd examples/getting_started/local
python duckdb_tpch_power.py

# Cloud platform (requires credentials)
cd examples/getting_started/cloud
python databricks_tpch_power.py  # Set DATABRICKS_* env vars first
```

### Run a Feature Example

```bash
cd examples/features
python query_subset.py --queries 1,3,6 --platform duckdb
```

### Use a Notebook

```bash
cd examples/notebooks
jupyter notebook databricks_benchmarking.ipynb
```

## Additional Resources

- **[`examples/INDEX.md`](../../examples/INDEX.md)** - Detailed multi-level navigation with descriptions
- **[`examples/PATTERNS.md`](../../examples/PATTERNS.md)** - 8 complete workflow patterns with code
- **[`examples/unified_runner.py`](../../examples/unified_runner.py)** - Advanced multi-platform tool
- **Individual README files** - Each subdirectory has a detailed README

## See Also

- [Getting Started Guide](getting-started.md) - BenchBox fundamentals
- [Configuration Guide](configuration.md) - Platform configuration details
- [CLI Reference](../reference/cli/index.md) - Command-line usage
- [Python API Reference](../reference/api-reference.md) - Programmatic usage

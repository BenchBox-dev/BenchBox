(cli-run)=
# `run` - Run Benchmarks

```{tags} reference, cli, intermediate
```

The primary command for executing benchmarks. Supports interactive mode, direct execution, and various execution phases.

## Basic Syntax

```bash
benchbox run [OPTIONS]
```

## Core Options

**Platform and Benchmark Selection:**
- `--platform TEXT`: Platform type
  - SQL platforms: `duckdb`, `sqlite`, `databricks`, `bigquery`, `snowflake`, `redshift`, `clickhouse`, `datafusion`, `polars`, `trino`, `presto`
  - DataFrame platforms: `polars-df`, `pandas-df`, `pyspark-df`, `datafusion-df` (see [DataFrame Platforms](../../platforms/dataframe.md))
- `--benchmark TEXT`: Benchmark name (tpch, tpcds, tpcdi, ssb, clickbench, h2odb, etc.)
- `--scale FLOAT`: Scale factor for data generation (default: 0.01)

**Execution Control:**
- `--phases TEXT`: Benchmark phases to run (default: "power")
  - Available phases:
    - `generate` - Generate benchmark data files
    - `load` - Load data into database
    - `warmup` - Run warmup queries (optional, prepares caches)
    - `power` - Sequential query execution (Power Test)
    - `throughput` - Concurrent query execution (Throughput Test)
    - `maintenance` - **Data modification operations (DATABASE RELOAD REQUIRED AFTER)** - See [TPC-H Maintenance](../../guides/tpc/tpc-h-official-guide.md#maintenance-test) or [TPC-DS Maintenance](../../guides/tpc/tpc-ds-official-guide.md#3-maintenance-test)
  - Use comma-separated list: `--phases generate,load,power`
  - **Warning:** Maintenance phase permanently modifies data; reload database before running power/throughput again
- `--force [MODE]`: Force regeneration of data (modes: `all`, `datagen`, `upload`, or `datagen,upload`)
- `--non-interactive`: Use defaults for all prompts (useful for automation)

**Output and Paths:**
- `--output TEXT`: Output directory (supports local paths and cloud storage: s3://, gs://, abfss://)
- `--dry-run OUTPUT_DIR`: Preview configuration and queries without execution

**Query Configuration:**
- `--seed INTEGER`: An RNG seed for query parameter generation (power/throughput tests)
- `--queries TEXT`: Run specific queries in specified order (comma-separated IDs: "1,6,17")
  - **Constraints**:
    - Max 100 queries per run
    - Alphanumeric IDs only (letters, numbers, dash, underscore; max 20 chars each)
    - Only works with `power` and `standard` phases (errors if used with ONLY incompatible phases)
    - Duplicates automatically removed
    - Order preserved as specified
  - **TPC Compliance**: Breaks official TPC-H/TPC-DS compliance (overrides stream permutations)
  - **Valid Ranges**: TPC-H (1-22), TPC-DS (1-99), SSB (1-13)
  - **Examples**:
    ```bash
    # Single query for debugging
    benchbox run --platform duckdb --benchmark tpch --queries "Q6"

    # Multiple queries in specific order
    benchbox run --platform postgres --benchmark tpch --queries "Q1,Q6,Q17"

    # With verbose logging for development
    benchbox run --platform duckdb --benchmark tpcds --queries "Q42" --verbose --phases power
    ```

**Tuning and Optimization:**
- `--tuning TEXT`: Tuning mode (default: "notuning")
  - `tuned`: Enable optimizations (constraints for SQL, parallelism for DataFrame)
  - `notuning`: Disable for baseline comparison
  - `auto`: Auto-detect optimal settings based on system profile
  - Path to config file: Custom tuning configuration (YAML)

**Data Compression (Advanced):**
- `--compression TEXT`: Compression configuration (e.g., `zstd`, `zstd:9`, `gzip:6`, `none`)
  - Format: `TYPE` or `TYPE:LEVEL`
  - Types: `zstd` (default), `gzip`, `none`
  - Levels: 1-9 for gzip, 1-22 for zstd

**Validation (Advanced):**
- `--validation TEXT`: Validation mode
  - `exact`: Exact row count validation (default)
  - `loose`: Loose validation (±5% tolerance)
  - `range`: Min/max bounds validation
  - `disabled`: No validation
  - `full`: All validation checks enabled (preflight, postgen, postload, platform check)
  - `preflight`, `postgen`, `postload`, `check-platforms`: Individual validation types

**Platform-Specific Configuration:**
- `--platform-option KEY=VALUE`: Platform-specific option (can be used multiple times)
- Use `benchbox platforms status <name>` to view platform details
- Universal keys available on all platforms:
  - `driver_version` - pin the Python driver package version (e.g. `1.2.0`)
  - `driver_auto_install` - auto-install the requested driver via uv if missing (`true`/`false`)
- Athena Spark only: `engine_version` - select Spark engine version (e.g. `PySpark engine version 3`); auto-detected on all other cloud platforms

**Benchmark-Specific Configuration:**
- `--benchmark-option KEY=VALUE`: Benchmark-specific option (can be used multiple times)
- Run `benchbox run --help-topic benchmarks` to see all available options per benchmark
- Selected benchmarks and their options:

  | Benchmark | Option | Default | Description |
  |-----------|--------|---------|-------------|
  | `nyctaxi` | `taxi_types` | - | Taxi types to load: `yellow`, `green`, `hvfhv` (comma-separated) |
  | `nyctaxi` | `year` | `2019` | Year of TLC data (2019-2025) |
  | `nyctaxi` | `months` | - | Months to include, comma-separated (1-12) |
  | `nyctaxi` | `seed` | - | Random seed for reproducibility |
  | `nyctaxi` | `force_regenerate` | - | Force data regeneration (`true`/`false`) |
  | `tpch_skew` | `skew_preset` | `moderate` | Skew distribution: `none`, `light`, `moderate`, `heavy`, `extreme`, `realistic` |
  | `tpch_skew` | `force_regenerate` | - | Force data regeneration |
  | `tsbs_devops` | `num_hosts` | - | Number of simulated hosts |
  | `tsbs_devops` | `duration_days` | - | Duration in days for data generation |
  | `tsbs_devops` | `interval_seconds` | `10` | Measurement interval in seconds |
  | `tsbs_devops` | `start_time` | - | Start time ISO format (e.g. `2019-01-01T00:00:00`) |
  | `tsbs_devops` | `seed` | - | Random seed for reproducibility |
  | `tsbs_devops` | `force_regenerate` | - | Force data regeneration (`true`/`false`) |
  | `datavault` | `hash_algorithm` | `md5` | Hash algorithm for hub/link keys: `md5`, `sha256` |
  | `datavault` | `record_source` | `TPCH` | Record source identifier for audit columns |
  | `datavault` | `force_regenerate` | - | Force data regeneration (`true`/`false`) |
  | `flightdata` | `end_year` | latest | Last year of flight data to include |
  | `flightdata` | `seed` | - | Random seed for reproducibility |
  | `flightdata` | `force_regenerate` | - | Force data regeneration (`true`/`false`) |
  | `joinorder` | `queries_dir` | - | Directory containing custom query files; defaults to the embedded 113 canonical JOB queries |
  | `joinorder` | `force_regenerate` | - | Clear and refetch verified canonical data (`true`/`false`); `joinorder` still requires `--scale 1` |
  | `tpcdi` | `enable_parallel` | `false` | Enable parallel processing for ETL |
  | `tpcdi` | `max_workers` | - | Maximum number of parallel workers |
  | `tpcds_obt` | `dimension_mode` | `full` | OBT dimension mode: `full`, `minimal` |
  | `tpcds_obt` | `channels` | - | Sales channels: `store`, `web`, `catalog` (comma-separated) |
  | `tpcds_obt` | `output_format` | `parquet` | Output format: `dat`, `parquet` |
  | `tpcds_obt` | `tpcds_source_dir` | - | Directory containing TPC-DS source data |
  | `tpcds_obt` | `force_regenerate` | - | Force data regeneration (`true`/`false`) |
  | `vector_search` | `dimensions` | `1536` | Embedding vector dimensions |

  Most options also accept a hyphenated alias (e.g. `taxi-types` for `taxi_types`).

**Logging and Output:**
- `--verbose`, `-v`: Enable verbose logging (use `-vv` for very verbose)
- `--quiet`, `-q`: Suppress all output (overrides verbose flags)

**Help System:**
- `-h, --help`: Show common options
- `--help-topic all`: Show all options including advanced
- `--help-topic examples`: Show categorized usage examples
- `--help-topic benchmarks`: Show benchmark-specific options (see `--benchmark-option` below)

## Usage Examples

### Basic Local Benchmark

```bash
# Simple TPC-H benchmark on DuckDB
benchbox run --platform duckdb --benchmark tpch --scale 0.01

# With default settings
benchbox run --platform duckdb --benchmark tpch
```

### Cloud Platform Examples

```bash
# Databricks with custom output location
benchbox run --platform databricks --benchmark tpch --scale 0.1 \
  --output dbfs:/Volumes/workspace/raw/benchmarks/

# BigQuery with verbose logging
benchbox run --platform bigquery --benchmark tpcds --scale 0.01 \
  --verbose --phases power

# Snowflake with tuning enabled
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning tuned
```

### DataFrame Platform Examples

```bash
# Polars DataFrame with auto-tuning
benchbox run --platform polars-df --benchmark tpch --scale 1 \
  --tuning auto

# Pandas DataFrame with PyArrow backend
benchbox run --platform pandas-df --benchmark tpch --scale 0.1 \
  --platform-option dtype_backend=pyarrow

# PySpark DataFrame (local mode)
benchbox run --platform pyspark-df --benchmark tpch --scale 1 \
  --platform-option driver_memory=8g

# Compare SQL vs DataFrame on same workload
benchbox run --platform polars --benchmark tpch --scale 0.1     # SQL mode
benchbox run --platform polars-df --benchmark tpch --scale 0.1  # DataFrame mode
```

### Advanced Phase Control

```bash
# Data generation only
benchbox run --benchmark tpch --scale 0.1 --phases generate \
  --output ./tpch-data

# Load data into database
benchbox run --platform duckdb --benchmark tpch --scale 0.1 \
  --phases load

# Full TPC-DS power and throughput test
benchbox run --platform duckdb --benchmark tpcds --scale 0.01 \
  --phases power,throughput --seed 42
```

### Dry Run and Preview

```bash
# Preview configuration without execution
benchbox run --platform duckdb --benchmark tpch --scale 0.1 \
  --dry-run ./preview

# Preview with specific seed for reproducible queries
benchbox run --platform snowflake --benchmark tpcds \
  --phases power --dry-run ./debug --seed 7
```

### Benchmark-Specific Options

```bash
# NYC Taxi: load only yellow and green trips from 2022
benchbox run --platform duckdb --benchmark nyctaxi \
  --benchmark-option taxi_types=yellow,green \
  --benchmark-option year=2022

# TPC-H Skew: use heavy skew distribution
benchbox run --platform duckdb --benchmark tpch_skew --scale 1 \
  --benchmark-option skew_preset=heavy

# TSBS Devops: custom host count and interval
benchbox run --platform duckdb --benchmark tsbs_devops \
  --benchmark-option num_hosts=100 \
  --benchmark-option interval_seconds=30

# TPC-DI: enable parallel ETL with 4 workers
benchbox run --platform duckdb --benchmark tpcdi \
  --benchmark-option enable_parallel=true \
  --benchmark-option max_workers=4

# Data Vault: use SHA-256 hashing
benchbox run --platform duckdb --benchmark datavault \
  --benchmark-option hash_algorithm=sha256

# List all benchmark options
benchbox run --help-topic benchmarks
```

### Platform-Specific Options

```bash
# ClickHouse with local mode and TLS
benchbox run --platform clickhouse --benchmark tpch \
  --platform-option mode=local \
  --platform-option secure=true

# Pin driver version (any platform)
benchbox run --platform duckdb --benchmark tpch \
  --platform-option driver_version=1.2.0 \
  --platform-option driver_auto_install=true

# Athena Spark: select Spark engine version
benchbox run --platform athena-spark --benchmark tpch --scale 1.0 \
  --platform-option workgroup=my-spark-workgroup \
  --platform-option s3_staging_dir=s3://my-bucket/benchbox \
  --platform-option "engine_version=PySpark engine version 3"

# Show platform details and capabilities
benchbox platforms status clickhouse
```

## Table Storage Options

**Table Mode:**
- `--table-mode [native|external]`: How tables are created (default: `native`)
  - `native`: Standard materialized tables in the target database
  - `external`: External table or view references (e.g., Parquet-backed)
  - **Note:** Incompatible with `--tuning tuned` when set to `external`

**Table Format:**
- `--table-format TEXT`: Open table format for data files
  - Format: `FORMAT[:COMPRESSION[:PARTITION:COLS...]]`
  - Examples: `parquet`, `delta:snappy`, `iceberg:zstd`, `vortex`
  - Supported formats depend on the platform adapter

**Pre-sorted Data:**
- `--presort [parquet-sorted|delta-sorted|iceberg-sorted]`: Pre-sort data into open table formats
  - Only valid for TPC-H and TPC-DS benchmarks
  - TPC-H sorts on `lineitem.l_shipdate`; TPC-DS sorts on `store_sales.ss_sold_date_sk`

## Cloud Sorted Ingestion Options

These flags control cloud data-organization strategy selection across supported cloud warehouses. They are advanced options - use `--help-topic all` to see them in the CLI help.

- `--sorted-ingestion-mode [off|auto|force]`: Cloud sorted-ingestion strategy mode
- `--sorted-ingestion-method [auto|ctas|z_order|hilbert|liquid_clustering|vacuum_sort]`: Override the clustering method used during sorted ingestion

```bash
# Snowflake with forced CTAS-based sorted ingestion
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --sorted-ingestion-mode force \
  --sorted-ingestion-method ctas
```

## Databricks Clustering Options

These overrides are Databricks-specific and are passed via `--platform-option`.

- `--platform-option databricks_clustering_strategy=[z_order|liquid_clustering|none]`: SQL tuning strategy for Databricks tables
- `--platform-option liquid_clustering_columns=col1,col2`: Comma-separated liquid clustering columns

```bash
# Databricks with Z-order clustering
benchbox run --platform databricks --benchmark tpch --scale 1 \
  --platform-option databricks_clustering_strategy=z_order

# Databricks with liquid clustering on specific columns
benchbox run --platform databricks --benchmark tpch --scale 1 \
  --platform-option databricks_clustering_strategy=liquid_clustering \
  --platform-option liquid_clustering_columns=l_shipdate,l_orderkey
```

## Execution Control Options

These flags control monitoring, progress display, memory handling, and caching behavior. They are advanced options - use `--help-topic all` to see them in the CLI help.

- `--mode [sql|dataframe]`: Force execution mode (validates against platform capabilities)
- `--no-monitoring`: Disable metrics collection during benchmark execution
- `--no-progress`: Disable progress bars
- `--ignore-memory-warnings`: Proceed with execution despite low memory warnings
- `--global-cache`: Use shared data cache at `~/.benchbox/datagen/` instead of project-local `benchmark_runs/` directory

## Query Plan Capture Options

- `--plan-config TEXT`: Fine-grained control over query plan capture
  - Format: comma-separated key:value pairs
  - Keys:
    - `sample:FLOAT` - fraction of queries to capture plans for (e.g., `sample:0.1` for 10%)
    - `first:INT` - capture plans for the first N queries only
    - `queries:ID1,ID2,...` - capture plans for specific query IDs
    - `strict:true|false` - fail if plan capture encounters errors
  - Requires `--capture-plans` to also be set
  - Example: `--capture-plans --plan-config "sample:0.1,strict:true"`
  - **Note:** On DuckDB, plan capture uses `EXPLAIN (ANALYZE, FORMAT JSON)` which roughly doubles query execution time. Use `--platform-option analyze_plans=false` for estimated plans without the overhead.

## Related

- [Configuration](configuration.md) - Configuration files and environment variables
- [Platform Options](configuration.md#platform-specific-options) - Platform-specific settings
- [Tuning Commands](tuning.md) - Generate and manage tuning configurations

<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# PySpark Platform (SQL & DataFrame)

```{tags} intermediate, guide, pyspark, dataframe-platform
```

PySpark is the Python API for Apache Spark, providing distributed analytics through both SQL and DataFrame interfaces. BenchBox now supports PySpark in dual execution modes:

- **SQL mode** (new): `benchbox run --platform pyspark --mode sql ...`
- **DataFrame mode** (existing): `benchbox run --platform pyspark-df ...`

## Overview

| Attribute | Value |
|-----------|-------|
| CLI Names | `pyspark` (SQL) / `pyspark-df` (DataFrame) |
| Families | SQL (PlatformAdapter) / Expression (DataFrame) |
| Execution | Lazy, distributed |
| Best For | Large datasets, distributed processing, Spark infrastructure |
| Min Version | 3.5.0 (Java 17/21 required) |

## Execution Modes

| Mode | CLI | Default | Description |
|------|-----|---------|-------------|
| SQL | `benchbox run --platform pyspark --mode sql ...` | ❌ | Spark SQL adapter backed by the shared `SparkSessionManager`. Ideal when benchmarking SQL dialect compatibility or comparing against other SQL engines. |
| DataFrame | `benchbox run --platform pyspark-df ...` or `--platform pyspark --mode dataframe` | ✅ | Expression-family adapter that uses PySpark's DataFrame API for query construction and execution. |

BenchBox defaults to DataFrame mode for historical compatibility. Use `--mode sql` explicitly for PySpark SQL benchmarks or append `-df` to force DataFrame mode from the CLI.

## Features

- **Distributed execution** - Scale from local mode to cluster
- **Lazy evaluation** - Catalyst optimizer for query planning
- **Adaptive Query Execution** - Runtime optimization (AQE)
- **Unified analytics** - Same API for batch and streaming
- **Enterprise ecosystem** - Integration with Hadoop, Hive, Delta Lake

## Installation

```bash
# Install PySpark DataFrame support
uv add benchbox --extra pyspark

# Or with pip
pip install "benchbox[pyspark]"

# Or install PySpark directly
pip install pyspark pyarrow

# Verify installation
python -c "from pyspark.sql import SparkSession; print('PySpark available')"
```

## Quick Start

> **Java runtime**: Wrap PySpark benchmarks with `scripts/with_supported_java.sh` so BenchBox automatically exports a Java 17/21 `JAVA_HOME`. The helper probes `/usr/libexec/java_home` (macOS) or any already-set `JAVA_HOME`, falling back to `java` on `PATH` if it already points at a supported runtime.

### DataFrame Mode

```bash
# Run TPC-H on PySpark DataFrame (local mode)
scripts/with_supported_java.sh benchbox run --platform pyspark-df --benchmark tpch --scale 0.01

# With custom memory allocation
scripts/with_supported_java.sh benchbox run --platform pyspark-df --benchmark tpch --scale 1 \
  --platform-option driver_memory=8g
```

### SQL Mode

```bash
# Run TPC-H power phase via Spark SQL
scripts/with_supported_java.sh benchbox run --platform pyspark --mode sql --benchmark tpch --scale 0.01 \
  --phases power --non-interactive

# Create a warehouse directory and Delta tables
scripts/with_supported_java.sh benchbox run --platform pyspark --mode sql --benchmark tpch --scale 1 \
  --platform-option warehouse_dir=./spark_warehouse \
  --platform-option table_format=delta
```

## Configuration Options (DataFrame Mode)

| Option | Default | Description |
|--------|---------|-------------|
| `master` | `local[*]` | Spark master URL |
| `app_name` | `BenchBox-TPC-H` | Application name |
| `driver_memory` | `4g` | Memory for driver process |
| `executor_memory` | None | Memory for executors (cluster mode) |
| `shuffle_partitions` | CPU count | Partitions for shuffle operations |
| `enable_aqe` | `true` | Enable Adaptive Query Execution |

### master

Specifies the Spark cluster to connect to:

```bash
# Local mode with all cores
--platform-option master="local[*]"

# Local mode with 4 cores
--platform-option master="local[4]"

# Standalone cluster
--platform-option master="spark://hostname:7077"

# YARN cluster
--platform-option master="yarn"
```

### driver_memory

Memory allocated to the driver process:

```bash
# Increase for large scale factors
benchbox run --platform pyspark-df --benchmark tpch --scale 10 \
  --platform-option driver_memory=16g
```

### shuffle_partitions

Number of partitions for shuffle operations (joins, aggregations):

```bash
# Match to CPU cores for local mode
benchbox run --platform pyspark-df --benchmark tpch --scale 1 \
  --platform-option shuffle_partitions=8

# Higher for cluster mode
--platform-option shuffle_partitions=200
```

### enable_aqe

Adaptive Query Execution optimizes queries at runtime:

```bash
# Disable for deterministic benchmarking
benchbox run --platform pyspark-df --benchmark tpch --scale 1 \
  --platform-option enable_aqe=false
```

## SQL Mode Configuration Highlights

PySpark SQL mode reuses most of the DataFrame configuration flags and adds SQL-specific tuning:

| Option | Default | Description |
|--------|---------|-------------|
| `warehouse_dir` | Spark default | Catalog warehouse directory used for managed tables. |
| `database` | `benchbox_benchmark` | Spark database/schema name. Shared across SQL/DataFrame adapters through the session manager. |
| `table_format` | `parquet` | File format for managed tables (`parquet` or `delta`). |
| `partitioning` | None | Optional `table=col1,col2` CLI entries to inject `PARTITIONED BY` clauses. |

Example CLI overrides:

```bash
benchbox run --platform pyspark --mode sql --benchmark tpcds --scale 0.1 \
  --platform-option database=benchbox_pyspark_tpcds \
  --platform-option warehouse_dir=./spark_warehouse \
  --platform-option table_format=delta \
  --platform-option partition=lineitem:l_shipdate
```

## Java Requirements

PySpark 4.x requires **Java 17 or Java 21**. Java 23+ is currently incompatible due to upstream PySpark limitations. BenchBox enforces Java detection in the shared `SparkSessionManager`:

- Java 17/21: ✅ supported
- Java 23+: ❌ blocked with actionable error
- Unknown Java version: ❌ prompts to install a supported JDK

On macOS, BenchBox automatically attempts to locate a compatible JDK via `/usr/libexec/java_home` when a newer Java (e.g., 23+) is active, so you can keep multiple versions installed without manual switching.

Set `JAVA_HOME` to the desired JDK before running BenchBox. Verify with:

```bash
java -version
# openjdk version "21.0.2" 2024-01-16
```

## Scale Factor Guidelines

PySpark can handle very large datasets due to distributed execution:

| Scale Factor | Data Size | Memory Required | Notes |
|--------------|-----------|-----------------|-------|
| 0.01 | ~10 MB | 2 GB driver | Quick testing |
| 0.1 | ~100 MB | 4 GB driver | Development |
| 1.0 | ~1 GB | 8 GB driver | Full TPC-H |
| 10.0 | ~10 GB | 16 GB driver | Large workload |
| 100.0 | ~100 GB | Cluster recommended | Production scale |

## Performance Characteristics

### Strengths

- **Scalability** - Scales from laptop to 1000+ node clusters
- **Fault tolerance** - Automatic recovery from failures
- **Rich ecosystem** - Delta Lake, Hive, JDBC connectors
- **Query optimization** - Catalyst optimizer + AQE
- **Memory management** - Tungsten engine

### Limitations

- **JVM overhead** - Higher startup time than native Python
- **Local mode limits** - Single-node performance lower than Polars
- **Complexity** - More configuration than simpler tools
- **Resource requirements** - Higher baseline memory usage

### Performance Tips

1. **Optimize shuffle partitions** for your workload:
   ```bash
   # For local mode, match CPU cores
   --platform-option shuffle_partitions=8
   ```

2. **Enable AQE** for adaptive optimization (default):
   ```bash
   --platform-option enable_aqe=true
   ```

3. **Allocate sufficient driver memory**:
   ```bash
   --platform-option driver_memory=8g
   ```

4. **Use Parquet format** for best performance (default for BenchBox)

## SQL Mode Examples

### CLI

```bash
# TPC-H smoke run with SQL mode
benchbox run --platform pyspark --mode sql --benchmark tpch --scale 0.01 \
  --phases power --non-interactive

# Generate + load data without executing queries
benchbox run --platform pyspark --mode sql --benchmark tpch --scale 0.1 \
  --phases generate,load --output ./tpch_sf01 --non-interactive
```

### Python API

```python
from benchbox.platforms.pyspark import PySparkSQLAdapter

adapter = PySparkSQLAdapter(
    master="local[4]",
    database="benchbox_tpch_sql",
    driver_memory="8g",
    table_format="delta",
)
conn = adapter.create_connection()
adapter.configure_for_benchmark(conn, "tpch")

# Run SQL directly
result = adapter.execute_query(conn, "SELECT COUNT(*) FROM lineitem", "Qcount", benchmark_type="tpch")
print(result["rows_returned"])

adapter.close()
```

## Deployment Modes

### Local Mode

Best for development and small-scale testing:

```python
from benchbox.platforms.dataframe import PySparkDataFrameAdapter

adapter = PySparkDataFrameAdapter(
    master="local[*]",  # All local cores
    driver_memory="4g",
)
```

### Standalone Cluster

For dedicated Spark clusters:

```python
adapter = PySparkDataFrameAdapter(
    master="spark://master:7077",
    driver_memory="8g",
    executor_memory="16g",
    shuffle_partitions=200,
)
```

### YARN Cluster

For Hadoop-integrated deployments:

```python
adapter = PySparkDataFrameAdapter(
    master="yarn",
    driver_memory="8g",
    executor_memory="16g",
)
```

## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| `Detected Java 24...` | Install Temurin/OpenJDK 17 or 21 and export `JAVA_HOME` before running BenchBox. |
| `SparkSession already created with a different configuration` | Ensure SQL/DataFrame adapters share identical Spark options (master, memory, shuffle partitions). |
| `PySpark not installed` | Run `uv add benchbox --extra pyspark` or `pip install pyspark pyarrow`. |
| Cloud storage read errors | Include required Spark packages via `--platform-option spark.hadoop.fs.s3a.impl=...` and supply credentials through environment variables. |

## Query Implementation

PySpark queries use expression-based operations:

```python
from pyspark.sql import functions as F

# TPC-H Q6: Forecasting Revenue Change
def q6_pyspark_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")

    # Date range filter
    start_date = ctx.cast_date(ctx.lit("1994-01-01"))
    end_date = ctx.cast_date(ctx.lit("1995-01-01"))

    # Apply filters
    result = (
        lineitem
        .filter(ctx.col("l_shipdate") >= start_date)
        .filter(ctx.col("l_shipdate") < end_date)
        .filter(ctx.col("l_discount") >= ctx.lit(0.05))
        .filter(ctx.col("l_discount") <= ctx.lit(0.07))
        .filter(ctx.col("l_quantity") < ctx.lit(24))
        .select(
            (ctx.col("l_extendedprice") * ctx.col("l_discount")).alias("revenue")
        )
        .agg(F.sum("revenue").alias("revenue"))
    )

    return result
```

## Comparison: PySpark vs Other Platforms

| Aspect | PySpark (`pyspark-df`) | Polars (`polars-df`) | DataFusion (`datafusion-df`) |
|--------|----------------------|---------------------|----------------------------|
| Execution | Distributed | Single-node | Single-node |
| Startup | ~3-5 seconds | Instant | Instant |
| Scale | TB+ data | GB data | GB data |
| Memory | Higher overhead | Efficient | Efficient |
| Best for | Large/distributed | Medium/local | Medium/Arrow |

## Window Functions

PySpark supports SQL-style window functions:

```python
from benchbox.platforms.dataframe import PySparkDataFrameAdapter

adapter = PySparkDataFrameAdapter(master="local[4]")

# Create window expressions
row_num = adapter.window_row_number(
    order_by=[("sale_date", True)],
    partition_by=["category"]
)

running_total = adapter.window_sum(
    column="amount",
    partition_by=["category"],
    order_by=[("sale_date", True)]
)

rank = adapter.window_rank(
    order_by=[("revenue", False)],  # Descending
    partition_by=["region"]
)
```

## Troubleshooting

### JVM Memory Issues

```
java.lang.OutOfMemoryError: Java heap space
```

**Solutions:**
1. Increase driver memory: `--platform-option driver_memory=8g`
2. Reduce shuffle partitions: `--platform-option shuffle_partitions=4`
3. Reduce scale factor: `--scale 1`

### Slow Startup

PySpark has JVM startup overhead (~3-5 seconds). For rapid iteration:

```bash
# Use Polars for quick tests
benchbox run --platform polars-df --benchmark tpch --scale 0.01

# Use PySpark for production scale
benchbox run --platform pyspark-df --benchmark tpch --scale 10
```

### Port Conflicts

If you see port binding errors:

```python
adapter = PySparkDataFrameAdapter(
    master="local[*]",
    # Configure different ports
    **{"spark.ui.port": "4050"}
)
```

### Session Management

Always close the adapter when done:

```python
adapter = PySparkDataFrameAdapter(master="local[4]")
try:
    # Run queries...
    pass
finally:
    adapter.close()  # Stops SparkSession
```

Or use context manager pattern in your code.

## Python API

```python
from benchbox.platforms.dataframe import PySparkDataFrameAdapter

# Create adapter with custom configuration
adapter = PySparkDataFrameAdapter(
    working_dir="./benchmark_data",
    master="local[*]",
    app_name="MyBenchmark",
    driver_memory="8g",
    shuffle_partitions=8,
    enable_aqe=True,
    verbose=True,
)

# Create context and load tables
ctx = adapter.create_context()
adapter.load_tables(ctx, data_dir="./tpch_data")

# Execute SQL query directly
df = adapter.sql("SELECT * FROM lineitem WHERE l_quantity > 10")
result = adapter.collect(df)

# Execute DataFrame query
from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES
query = TPCH_DATAFRAME_QUERIES.get_query("Q1")
result = adapter.execute_query(ctx, query)
print(result)

# Convert to pandas for analysis
pandas_df = adapter.to_pandas(df)

# Get query plan for debugging
plan = adapter.get_query_plan(df)
print(plan["physical"])

# Always close when done
adapter.close()
```

## Related Documentation

- [Spark SQL Platform](spark.md) - Spark SQL mode
- [Polars Platform](polars.md) - Alternative expression-family adapter
- [DataFusion DataFrame Platform](datafusion-dataframe.md) - Arrow-native adapter
- [Getting Started](../usage/getting-started.md) - BenchBox quick start

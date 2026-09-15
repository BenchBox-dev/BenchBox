<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Apache Spark Platform

```{tags} intermediate, guide, spark, dataframe-platform
```

Apache Spark is the most widely deployed distributed computing framework for large-scale data processing. It provides a unified analytics engine supporting batch processing, streaming, and machine learning workloads.

## Features

- **Distributed execution** - Scale across thousands of nodes
- **Multiple deployment modes** - Local, standalone, YARN, Kubernetes
- **Rich format support** - Parquet, ORC, CSV, Delta Lake, Iceberg
- **Adaptive Query Execution** - Dynamic runtime optimization
- **Catalyst optimizer** - Sophisticated query planning
- **DataFrame and SQL APIs** - Flexible programming models

## Installation

```bash
# Install PySpark
pip install pyspark

# Or with specific version
pip install pyspark==3.5.0

# For Delta Lake support
pip install delta-spark
```

## Configuration

### Environment Variables

```bash
# Spark configuration
export SPARK_HOME=/path/to/spark
export PYSPARK_PYTHON=python3

# For distributed mode
export SPARK_MASTER=spark://master:7077
```

### CLI Options

```bash
benchbox run --platform spark --benchmark tpch --scale 1.0 \
  --platform-option master=local[*] \
  --platform-option driver_memory=4g \
  --platform-option executor_memory=8g
```

### Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `master` | local[*] | Spark master URL |
| `app_name` | BenchBox | Spark application name |
| `driver_memory` | 4g | Driver memory allocation |
| `executor_memory` | 8g | Executor memory allocation |
| `executor_cores` | 4 | Cores per executor |
| `num_executors` | auto | Number of executors |
| `warehouse_dir` | /tmp/spark-warehouse | Hive warehouse location |
| `catalog` | spark_catalog | Catalog name |
| `table_format` | parquet | Default table format |

## Usage Examples

### Local Mode

```bash
# Run locally with all cores
benchbox run --platform spark --benchmark tpch --scale 0.1 \
  --platform-option master="local[*]"
```

### Cluster Mode

```bash
# Run on Spark cluster
benchbox run --platform spark --benchmark tpch --scale 10.0 \
  --platform-option master=spark://master:7077 \
  --platform-option num_executors=10 \
  --platform-option executor_memory=16g
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.spark import SparkAdapter

# Initialize adapter
adapter = SparkAdapter(
    master="local[*]",
    driver_memory="4g",
    app_name="TPC-H Benchmark",
)

# Load and run benchmark
benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

### Delta Lake Integration

```python
from benchbox.platforms.spark import SparkAdapter

# Initialize with Delta Lake
adapter = SparkAdapter(
    master="local[*]",
    table_format="delta",
    spark_config={
        "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
        "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
    }
)
```

## Deployment Modes

### Local Mode

Best for development and small datasets:

```bash
benchbox run --platform spark --benchmark tpch --scale 0.1 \
  --platform-option master="local[4]"  # 4 cores
```

### Standalone Cluster

```bash
# Start master
$SPARK_HOME/sbin/start-master.sh

# Start workers
$SPARK_HOME/sbin/start-worker.sh spark://master:7077

# Run benchmark
benchbox run --platform spark --benchmark tpch --scale 10.0 \
  --platform-option master=spark://master:7077
```

### Kubernetes

```bash
benchbox run --platform spark --benchmark tpch --scale 10.0 \
  --platform-option master=k8s://https://kubernetes:443 \
  --platform-option deploy_mode=cluster
```

## Performance Tuning

### Adaptive Query Execution (AQE)

Enable AQE for dynamic optimization:

```python
adapter = SparkAdapter(
    spark_config={
        "spark.sql.adaptive.enabled": "true",
        "spark.sql.adaptive.coalescePartitions.enabled": "true",
        "spark.sql.adaptive.skewJoin.enabled": "true",
    }
)
```

### Memory Configuration

```python
adapter = SparkAdapter(
    driver_memory="8g",
    executor_memory="16g",
    spark_config={
        "spark.memory.fraction": "0.8",
        "spark.memory.storageFraction": "0.3",
    }
)
```

### Shuffle Optimization

```python
adapter = SparkAdapter(
    spark_config={
        "spark.sql.shuffle.partitions": "200",
        "spark.sql.files.maxPartitionBytes": "128m",
    }
)
```

## Benchmark Recommendations

### Scale Factor Guidelines

| Scale Factor | Recommended Mode | Executors | Memory |
|--------------|------------------|-----------|--------|
| 0.1 | Local | 1 | 4 GB |
| 1.0 | Local/Small cluster | 2-4 | 8 GB each |
| 10.0 | Cluster | 10+ | 16 GB each |
| 100.0 | Large cluster | 50+ | 32 GB each |

### Best Practices

1. **Use columnar formats** - Parquet or ORC for best performance
2. **Enable AQE** - Adaptive execution handles skew automatically
3. **Right-size partitions** - 128 MB to 1 GB per partition
4. **Cache wisely** - Only cache frequently accessed data

## Query Plan Analysis

```bash
benchbox run --platform spark --benchmark tpch \
  --capture-plans
```

Spark provides detailed physical and logical plans:

```python
# Get query plan
spark.sql("SELECT ...").explain(extended=True)
```

## Limitations

- **Infrastructure overhead** - Requires cluster for large datasets
- **Startup time** - JVM warm-up affects small benchmarks
- **Memory management** - Complex tuning for optimal performance

## Troubleshooting

### Out of Memory

```python
# Increase memory
adapter = SparkAdapter(
    driver_memory="8g",
    executor_memory="16g",
    spark_config={
        "spark.sql.shuffle.partitions": "400",
    }
)
```

### Shuffle Spill

```python
# Reduce shuffle partition size
adapter = SparkAdapter(
    spark_config={
        "spark.sql.shuffle.partitions": "400",
        "spark.shuffle.spill.compress": "true",
    }
)
```

### Connection to Master Failed

```bash
# Verify master is running
curl http://master:8080  # Web UI

# Check firewall rules
```

## Related Documentation

- [Databricks Platform](databricks.md) - Managed Spark service
- [Trino Platform](trino.md) - Alternative distributed SQL
- [Presto Platform](presto.md) - Alternative distributed SQL

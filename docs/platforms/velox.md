<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Apache Gluten + Velox Platform

```{tags} intermediate, guide, velox, gluten, sql-platform, spark-compatible, accelerated, local
```

Apache Gluten is a plugin to Apache Spark that offloads physical operators to [Velox](https://velox-lib.io/) - a vectorized, SIMD-optimized C++ query engine with unified off-heap memory. Spark retains its distributed scheduler, fault tolerance, and SQL/DataFrame APIs; Gluten intercepts the post-Catalyst physical plan and runs it natively in Velox. Reference performance (Gluten community, March 2024): **~3.3x faster** overall on TPC-H vs. Apache Spark, with individual queries up to **~23x** faster.

## Features

- **Native C++ execution** - Gluten routes Spark physical operators through Velox; unsupported operators transparently fall back to JVM execution.
- **Columnar shuffle** - `ColumnarShuffleManager` is mandatory for meaningful acceleration (the adapter enforces this).
- **Velox activity probe** - `get_platform_info()` runs `EXPLAIN SELECT count(*) FROM range(10)` and returns `velox_active: true/false` so you can confirm the plugin is live.
- **Plan annotation** - `get_query_plan()` labels every plan with `Velox native execution: YES/NOT DETECTED` and flags real JVM fallbacks (without false-positives on `VeloxColumnarToRow`).
- **Two deployment modes** - `local` (in-process SparkSession) and `remote` (connect to a pre-started Gluten-enabled Spark-Connect server).
- **Docker-first** on macOS / Windows - the provided image tracks the official Apache release tarball and defaults to `linux/amd64`.

## Platform Requirements - Linux Only

The Gluten Velox bundle jar is **Linux-only**. There are no prebuilt jars for macOS or Windows, and native builds on those hosts are **not supported**.

- **Linux x86_64:** fully supported with the official Apache Gluten 1.6.0 release jar.
- **Linux aarch64:** BenchBox can use a self-built/custom jar, but Apache Gluten 1.6.0 does not ship an official prebuilt arm64 Spark 4.0 jar.
- **macOS (Apple Silicon or Intel):** use Docker or a remote Linux host. The checked-in Docker workflow defaults to `linux/amd64`; on Apple Silicon that means emulation, which is acceptable for smoke testing but invalid for benchmark timings.
- **Windows:** use Docker Desktop with the Linux-container backend.

## Quick Start

### Option A - Docker (recommended on macOS/Windows)

```bash
# Build the image
cd docker/velox
docker build \
    --platform linux/amd64 \
    -t benchbox-velox:dev ../..

# (a) All-in-one: run the benchmark inside the container
docker compose run --rm velox-runner --benchmark tpch --scale 0.1

# (b) Host-driver / container-backend: start a Gluten-enabled Spark-Connect server
docker compose up -d velox-connect
benchbox run --platform velox --velox-deployment remote \
    --velox-endpoint sc://localhost:50051 \
    --benchmark tpch --scale 0.1
```

See [Velox Docker Dev Workflow](velox_docker_dev.md) for a full walkthrough of both Docker workflows, arch selection, memory sizing, and CI integration. See [Velox Jar Setup](velox_jar_setup.md) for the published release tarball and verification steps.

### Option B - Native Linux

```bash
# Install the Velox extra (pulls pyspark[connect]>=3.5.0)
uv add benchbox --extra velox

# Download the Gluten Velox bundle jar for your Spark 4.0 / Scala 2.13 / arch
# (see docs/platforms/velox_jar_setup.md for release tarballs and verification steps)

# Run locally with Gluten wired into an in-process SparkSession
benchbox run --platform velox --benchmark tpch --scale 0.1 \
    --platform-option gluten_jar_path=/opt/gluten-velox-bundle-spark4.0_2.13-linux_amd64-1.6.0.jar \
    --offheap-size 8g
```

## Configuration

### CLI Options

```bash
benchbox run --platform velox --benchmark tpch --scale 1.0 \
    --velox-deployment local \
    --platform-option gluten_jar_path=/opt/gluten.jar \
    --velox-version 1.6.0 \
    --offheap-size 16g \
    --driver-memory 8g \
    --shuffle-partitions 200 \
    --table-format parquet
```

### Configuration Options

| Option | CLI Flag | Default | Description |
|--------|----------|---------|-------------|
| `deployment` | `--velox-deployment` | `local` | `local` (in-process SparkSession, Linux only) or `remote` (connect to Spark-Connect) |
| `endpoint` | `--velox-endpoint` | `sc://localhost:50051` | Spark-Connect endpoint for `remote` mode |
| `gluten_jar_path` | `--platform-option gluten_jar_path=…` (alias: `jar=…`) | - | Absolute path to the Gluten bundle jar (required for `local` mode) |
| `gluten_version` | `--velox-version` | `1.6.0` | Gluten version (informational, surfaced in `platform_info`) |
| `offheap_size` | `--offheap-size` | `8g` | `spark.memory.offHeap.size` for Velox (sized separately from JVM heap) |
| `driver_memory` | `--driver-memory` | `4g` | JVM driver heap |
| `shuffle_partitions` | `--shuffle-partitions` | `200` | `spark.sql.shuffle.partitions` |
| `table_format` | `--table-format` | `parquet` | `parquet` or `orc` |
| `adaptive_enabled` | `--adaptive-enabled` / `--no-adaptive-enabled` | `true` | Enable Adaptive Query Execution (AQE) |
| `app_name` | `--app-name` | `BenchBox-Velox` | Spark application name |
| `spark_config` | - | `{}` | Extra Spark configuration (dict). `spark.shuffle.manager` cannot be overridden in `local` mode. |
| `disable_cache` | - | `true` | Disables `spark.sql.inMemoryColumnarStorage.enabled` for clean timings |

### Mandatory Gluten Configuration (Local Mode)

The adapter sets these automatically when `deployment="local"`:

- `spark.plugins = org.apache.gluten.GlutenPlugin`
- `spark.memory.offHeap.enabled = true`
- `spark.memory.offHeap.size = <offheap_size>`
- `spark.shuffle.manager = org.apache.spark.shuffle.sort.ColumnarShuffleManager`
- `spark.jars = <gluten_jar_path>`
- `spark.driver.extraClassPath = <gluten_jar_path>`
- `spark.executor.extraClassPath = <gluten_jar_path>`

The `extraClassPath` entries are required because the Gluten plugin class is loaded by `SparkContext.initializeSparkContext` before `spark.jars` promotions reach the executor classpath. Without them the plugin silently no-ops.

Overriding `spark.shuffle.manager` via `spark_config` raises `ValueError` - `ColumnarShuffleManager` is required for shuffle acceleration.

## Usage Examples

### Local Mode (Linux or inside Docker)

```bash
# TPC-H SF1 with 16 GB off-heap
benchbox run --platform velox --benchmark tpch --scale 1.0 \
    --platform-option gluten_jar_path=/opt/gluten.jar --offheap-size 16g

# TPC-DS SF10, specific queries
benchbox run --platform velox --benchmark tpcds --scale 10.0 \
    --queries Q1,Q6,Q17 \
    --platform-option gluten_jar_path=/opt/gluten.jar --offheap-size 24g \
    --driver-memory 12g --shuffle-partitions 400

# Dry-run preview
benchbox run --dry-run ./preview --platform velox --benchmark tpch --scale 1.0
```

### Remote Mode (Spark-Connect)

```bash
# 1. Start a Gluten-enabled Spark-Connect server
cd docker/velox
docker compose up -d velox-connect

# 2. Run benchbox on the host, connecting to the container
benchbox run --platform velox --benchmark tpch --scale 1.0 \
    --velox-deployment remote \
    --velox-endpoint sc://localhost:50051
```

The adapter does **not** auto-start a server - if `sc://host:port` is unreachable, connection fails with a clear error.

### Accelerated-Spark Tier Comparison

```bash
# Apache Spark baseline
benchbox run --platform spark --benchmark tpch --scale 10.0

# Same workload with Gluten + Velox
benchbox run --platform velox --benchmark tpch --scale 10.0 \
    --platform-option gluten_jar_path=/opt/gluten.jar --offheap-size 24g

# LakeSail Sail (Rust / DataFusion)
benchbox run --platform lakesail --benchmark tpch --scale 10.0

# Compare
benchbox results compare spark_tpch_sf10.json velox_tpch_sf10.json lakesail_tpch_sf10.json
```

## Python API

```python
from benchbox import TPCH
from benchbox.platforms.velox import VeloxAdapter

adapter = VeloxAdapter(
    deployment="local",
    gluten_jar_path="/opt/gluten-velox-bundle-spark4.0_2.13-linux_amd64-1.6.0.jar",
    offheap_size="16g",
    driver_memory="8g",
    shuffle_partitions=200,
    table_format="parquet",
)

benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)

# Confirm native execution happened
info = adapter.get_platform_info(connection=adapter._spark_session)
print("Velox active:", info["velox_active"])
```

## Architecture

```
┌────────────────────┐
│  PySpark Client     │  (user-facing SQL / DataFrame API)
└──────────┬─────────┘
           │
┌──────────▼─────────┐
│  Spark Catalyst     │  (parse, analyze, logical optimize)
└──────────┬─────────┘
           │   physical plan
┌──────────▼─────────┐       fallback
│  Gluten Plugin      │─────────────────┐
│  (plan translation) │                 │
└──────────┬─────────┘                 │
           │                           │
┌──────────▼─────────┐       ┌─────────▼──────────┐
│  Velox (C++)        │       │  Spark JVM Engine   │
│  Vectorized exec    │       │  (unsupported ops)  │
└────────────────────┘       └────────────────────┘
```

- **Plan translation:** Gluten intercepts the physical plan after Catalyst and rewrites supported operators into `VeloxColumnar*` nodes.
- **Shuffle:** `ColumnarShuffleManager` exchanges Arrow-format columnar batches, avoiding per-row serialization.
- **Off-heap memory:** Velox allocates from a separate native pool (`spark.memory.offHeap.size`), independent of the JVM heap.
- **Fallback:** Operators that Gluten can't translate run in the JVM, with `ColumnarToRow` / `RowToColumnar` nodes bridging format boundaries. Fallback is functional but forfeits acceleration.

### Tuning Support

| Tuning Type | Supported | Notes |
|-------------|-----------|-------|
| Partitioning | Yes | `PARTITIONED BY` added to `CREATE TABLE` |
| Sorting | No | Plain Parquet/ORC tables have no DDL sort key; handled at query time via AQE/CBO |
| Clustering | No | |
| Primary Keys | Informational | Not enforced (Spark behavior) |
| Foreign Keys | Informational | Not enforced (Spark behavior) |

## Comparison: Velox vs. Spark vs. LakeSail

| Dimension | Apache Gluten + Velox | Apache Spark | LakeSail Sail |
|-----------|-----------------------|--------------|---------------|
| Execution engine | Velox (C++, vectorized, SIMD) | JVM (Scala/Java) | DataFusion (Rust) |
| API | PySpark SQL / DataFrame | PySpark SQL / DataFrame | PySpark SQL / DataFrame |
| SQL dialect | Spark SQL | Spark SQL | Spark SQL |
| Performance (TPC-H community numbers) | ~3.3x vs. Spark | Baseline | ~4x vs. Spark (SF100) |
| Protocol | In-process or Spark-Connect | Native | Spark-Connect only |
| Fault tolerance / scheduling | Spark's (unchanged) | Native | Sail |
| Operator coverage | Most OLAP ops; JVM fallback for unsupported | Full | DataFusion catalogue |
| Local platform support | Linux only (Docker elsewhere) | All | All |
| Maturity | Apache project | Battle-tested | Emerging |

### When to Use Velox

**Use Velox when:**
- You already run Spark and want native acceleration without leaving the Spark API.
- Your workload is OLAP-shaped (scans, filters, joins, aggregations on Parquet/ORC).
- You want to benchmark the "accelerated-Spark" tier against Spark, LakeSail, DataFusion, and cloud engines.
- Linux hosts (or Docker) are acceptable.

**Use Apache Spark instead when:**
- You need Delta Lake / Iceberg / Hudi write paths Gluten doesn't yet accelerate.
- You rely on UDFs or Spark operators without Velox equivalents (the JVM fallback will remove the acceleration benefit).
- You're on a non-Linux host and can't run Docker.

**Use LakeSail instead when:**
- You want a pure-Rust replacement rather than a Spark plugin.
- You need DataFrame-mode benchmarks on the same engine (Velox adapter is SQL-only).

## Troubleshooting

### `velox_active` is `false`

The probe `EXPLAIN SELECT count(*) FROM range(10)` did not produce `VeloxColumnar*` nodes. Most likely causes:

1. The Gluten jar is not on the classpath - check `platform_info.gluten_jar` points to the right filename and the file exists.
2. `spark.plugins` was overridden via `spark_config`. Remove the override.
3. `spark.shuffle.manager` was overridden - the adapter rejects this in local mode but a pre-started remote server may have it mis-configured.
4. You are running on macOS/Windows natively rather than Linux/Docker. The jar will load but Velox will crash or silently fall back.

### `JVM fallback: DETECTED` in query plan

`ColumnarToRow` or `RowToColumnar` nodes appeared in the plan (excluding `VeloxColumnarToRow`, which is the native result-materialization node - not a fallback). Some operators in your query aren't supported by Velox and ran in the JVM. Check [Gluten's operator support matrix](https://gluten.apache.org/) and consider rewriting the query, or accept partial acceleration.

### `gluten_jar_path is required for local deployment mode`

Pass `--platform-option gluten_jar_path=/path/to/gluten-velox-bundle-*.jar` (alias: `--platform-option jar=…`) or set the `gluten_jar_path` config key. On macOS/Windows, use the Docker workflow instead.

### `Cannot connect to Spark-Connect server at sc://...`

The server isn't running or isn't reachable. The adapter does not auto-start servers.

```bash
cd docker/velox
docker compose up -d velox-connect
docker compose logs velox-connect   # check for startup errors
```

### Out-of-memory / excessive JVM fallback

Velox uses off-heap memory. Increase `--offheap-size` (default 8 GB). If you see `RowToColumnar` inserted before every operator, the Gluten plugin may not have loaded - check the probe above.

## See Also

- [Velox Docker Dev Workflow](velox_docker_dev.md) - Docker workflows, arch selection, memory sizing, CI integration
- [Velox Jar Setup](velox_jar_setup.md) - release tarball URLs, checksum verification, and extracted jar names
- [Apache Spark Platform](spark.md) - JVM baseline for comparison
- [LakeSail Sail Platform](lakesail.md) - Rust/DataFusion alternative
- [Apache Gluten](https://gluten.apache.org/) - upstream project documentation
- [Velox](https://velox-lib.io/) - upstream execution engine documentation

<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Apache Doris Platform

```{tags} intermediate, guide, doris, sql-platform, self-hosted, olap
```

Apache Doris is a high-performance real-time analytical database based on MPP (Massively Parallel Processing) architecture. Originally developed at Baidu as Palo, it graduated as an Apache Top-Level Project in 2022. BenchBox connects via the MySQL protocol using PyMySQL (port 9030) and supports Stream Load via the FE HTTP API (port 8030) for high-throughput data ingestion. SQLGlot provides official `doris` dialect support for SQL translation.

Apache Doris is used in production by Baidu, Xiaomi, ByteDance, JD.com, Meituan, and thousands of other enterprises globally. It delivers competitive performance against ClickHouse, StarRocks, and Trino on analytical workloads, with particularly strong support for real-time analytics and high-concurrency point queries.

## Features

- **MySQL protocol connectivity** - Standard MySQL wire protocol via PyMySQL (port 9030)
- **Stream Load HTTP API** - High-throughput data ingestion via FE HTTP port 8030
- **Full TPC-H support** - All 22 queries with row count validation
- **Full TPC-DS support** - All 99 queries with row count validation
- **Official SQLGlot dialect** - Native `doris` dialect for accurate SQL translation
- **Vectorized execution engine** - High-performance columnar processing (Doris 2.0+)
- **Multiple table models** - Duplicate, Aggregate, Unique, and Primary Key models
- **Distributed hash partitioning** - Automatic data distribution across Backend nodes
- **Tuning support** - Partitioning, sorting, and distribution tuning at table creation time

## Quick Start

```bash
# Install PyMySQL dependency
uv add pymysql

# Or install via the Doris extra
uv add benchbox --extra doris

# Configure connection (Doris must be running)
export DORIS_HOST=localhost
export DORIS_PORT=9030

# Run TPC-H benchmark
benchbox run --platform doris --benchmark tpch --scale 0.01
```

### Docker Quick Start

```bash
# Start Apache Doris with Docker (all-in-one FE + BE)
docker run -p 9030:9030 -p 8030:8030 -p 8040:8040 \
    apache/doris:doris-all-in-one-2.1

# Verify connectivity
mysql -h 127.0.0.1 -P 9030 -u root -e "SELECT 1"

# Run benchmark
benchbox run --platform doris --benchmark tpch --scale 1.0
```

## Configuration Options

| Option | CLI Argument | Environment Variable | Default | Description |
|--------|-------------|---------------------|---------|-------------|
| `host` | `--doris-host` | `DORIS_HOST` | `localhost` | Doris FE node hostname |
| `port` | `--doris-port` | `DORIS_PORT` | `9030` | MySQL protocol port (FE) |
| `username` | `--doris-username` | `DORIS_USER` / `DORIS_USERNAME` | `root` | Database username |
| `password` | `--doris-password` | `DORIS_PASSWORD` | `""` | Database password |
| `database` | `--doris-database` | `DORIS_DATABASE` | auto-generated | Target database name |
| `http_port` | `--doris-http-port` | `DORIS_HTTP_PORT` | `8030` | FE HTTP port for Stream Load |
| `use_tls` | `--doris-use-tls` | - | `false` | Use HTTPS for Stream Load API |

## Data Loading

BenchBox loads data into Apache Doris using the Stream Load HTTP API when the `requests` library is available. When `requests` is not installed, it falls back to batch INSERT statements via the MySQL protocol. The adapter handles both TPC pipe-delimited (`.tbl`) and standard CSV formats automatically.

### Loading Process

1. **Schema creation** - Tables are created with Doris-optimized DDL (Duplicate Key model, hash distribution)
2. **Type conversion** - DuckDB/standard SQL types are translated via the SQLGlot `doris` dialect
3. **Stream Load** (primary) - Data files are sent via HTTP PUT to the FE Stream Load endpoint on port 8030
4. **INSERT fallback** - If `requests` is not installed, data is loaded in batches of 1,000 rows using parameterized `INSERT INTO ... VALUES` statements
5. **Constraint handling** - Foreign keys are removed (Doris does not enforce them); primary keys map to Doris key models

### Stream Load (HTTP API)

Apache Doris provides a high-throughput Stream Load API on the FE HTTP port (default 8030). BenchBox uses this as the primary data loading method:

- **Endpoint**: `http://<fe_host>:8030/api/<database>/<table>/_stream_load`
- **Protocol**: HTTP PUT with CSV payload and `100-continue` header
- **Authentication**: HTTP Basic Auth using Doris credentials
- **TPC format handling**: Trailing delimiters are automatically stripped before loading
- **TLS support**: Enable `--doris-use-tls` to use HTTPS for encrypted Stream Load transfers
- **Throughput**: Significantly higher than row-by-row INSERT for large datasets

### INSERT Fallback

When the `requests` library is not available, the adapter falls back to batch INSERT:

- Rows are loaded in batches of 1,000 using `executemany()`
- TPC pipe-delimited format is handled automatically
- Suitable for small to medium datasets (up to SF 1)
- For larger datasets, install `requests` to enable Stream Load

## Table Models

Apache Doris supports four table models, each optimized for different workloads. BenchBox uses the **Duplicate Key** model by default for benchmark tables, as it preserves all rows without deduplication.

| Model | Use Case | Key Behavior | BenchBox Usage |
|-------|----------|-------------|----------------|
| **Duplicate Key** | Analytics, logs | All rows preserved, no deduplication | Default for benchmarks |
| **Aggregate** | Pre-aggregation | Rows with same key are merged by aggregate functions | Not used |
| **Unique Key** | Dimension tables | Last write wins for same key | Not used |
| **Primary Key** | Real-time updates | Last write wins with merge-on-read | Not used |

The Duplicate Key model is optimal for TPC-H and TPC-DS workloads because:
- No deduplication overhead during data loading
- All original rows are preserved for accurate query results
- Sort keys can be specified for scan optimization

## Usage Examples

### Basic Benchmarks

```bash
# TPC-H at scale factor 1
benchbox run --platform doris --benchmark tpch --scale 1.0

# TPC-DS at scale factor 10
benchbox run --platform doris --benchmark tpcds --scale 10.0

# Run specific queries only
benchbox run --platform doris --benchmark tpch --queries Q1,Q6,Q17
```

### Environment Variable Configuration

```bash
export DORIS_HOST=doris-fe.example.com
export DORIS_PORT=9030
export DORIS_USER=benchbox
export DORIS_PASSWORD=secret
export DORIS_DATABASE=benchmark_db
export DORIS_HTTP_PORT=8030

benchbox run --platform doris --benchmark tpch --scale 10.0
```

### CLI Argument Configuration

```bash
benchbox run --platform doris --benchmark tpch --scale 1.0 \
    --doris-host doris-fe.example.com \
    --doris-port 9030 \
    --doris-username benchbox \
    --doris-password secret \
    --doris-database my_benchmarks
```

### Dry Run (Preview)

```bash
# Preview execution plan without running
benchbox run --platform doris --benchmark tpch --scale 1.0 --dry-run ./preview
```

### TLS-Encrypted Stream Load

```bash
# Use HTTPS for Stream Load API (e.g., managed cloud deployments)
benchbox run --platform doris --benchmark tpch --scale 1.0 \
    --doris-use-tls
```

## Architecture

### Adapter Structure

The Doris adapter is a single-file implementation:

| Module | Class | Responsibility |
|--------|-------|---------------|
| `doris.py` | `DorisAdapter` | Connection management, schema creation, data loading, query execution, tuning |

### Connection Model

```
BenchBox CLI
    |
    v
DorisAdapter
    |
    +-- MySQL Protocol (PyMySQL) --> FE (port 9030)
    |       - Schema DDL
    |       - Query execution
    |       - Batch INSERT fallback
    |
    +-- HTTP API (Stream Load) --> FE (port 8030)
            - High-throughput CSV data ingestion
            - HTTP PUT with Basic Auth
```

### Doris Cluster Ports

| Port | Service | Protocol | Purpose |
|------|---------|----------|---------|
| 9030 | FE MySQL | TCP | SQL queries, DDL, DML via MySQL protocol |
| 8030 | FE HTTP | HTTP/HTTPS | Stream Load API, web UI, REST API |
| 8040 | BE HTTP | HTTP | BE web server, internal data transfer |
| 9010 | FE Edit Log | TCP | FE metadata replication (internal) |

### Platform Information

At runtime, BenchBox captures platform metadata:

```python
{
    "platform_type": "doris",
    "platform_name": "Apache Doris",
    "configuration": {
        "host": "localhost",
        "port": 9030,
        "database": "benchbox_tpch_sf1",
        "http_port": 8030,
        "stream_load_available": True
    },
    "platform_version": "2.1.x",
    "client_library_version": "1.x.x"
}
```

## Tuning and Optimization

### Automatic Benchmark Configuration

The adapter automatically applies session-level optimizations when running benchmarks:

- **SQL cache**: Disabled (`enable_sql_cache = false`) for accurate timing
- **Parallel execution**: Set to 8 fragment instances (`parallel_fragment_exec_instance_num = 8`)
- **Memory limit**: Set to 8 GB for OLAP workloads (`exec_mem_limit = 8589934592`)

### Supported Tuning Types

| Tuning Type | Support | Notes |
|-------------|---------|-------|
| Partitioning | Yes | `PARTITION BY RANGE` clause at table creation |
| Sorting | Yes | Sort keys via Duplicate Key model key ordering |
| Distribution | Yes | `DISTRIBUTED BY HASH` clause at table creation |
| Clustering | No | No CLUSTER command |
| Primary Keys | Yes | Unique/Primary Key table models |
| Foreign Keys | No | No FK enforcement in Doris |

### Distribution Keys

Choosing effective distribution keys is critical for Doris query performance:

```sql
-- Hash distribution on frequently joined columns
CREATE TABLE lineitem (
    l_orderkey BIGINT,
    l_partkey BIGINT,
    ...
) DUPLICATE KEY(l_orderkey)
DISTRIBUTED BY HASH(l_orderkey) BUCKETS 16;
```

**Guidelines:**
- Use high-cardinality columns for even data distribution
- Align distribution keys with common join predicates
- Start with 8-16 buckets and adjust based on data volume

### Bloom Filter and Bitmap Indexes

Doris supports secondary indexes for accelerating point queries and filter predicates:

```sql
-- Bloom filter index for high-cardinality columns
ALTER TABLE lineitem SET ("bloom_filter_columns" = "l_orderkey, l_partkey");

-- Bitmap index for low-cardinality columns
CREATE INDEX idx_shipmode ON lineitem (l_shipmode) USING BITMAP;
```

### Colocate Join Groups

For frequently joined tables, colocate groups ensure data locality:

```sql
-- Create colocate group for TPC-H tables
CREATE TABLE orders (
    o_orderkey BIGINT,
    ...
) DUPLICATE KEY(o_orderkey)
DISTRIBUTED BY HASH(o_orderkey) BUCKETS 16
PROPERTIES ("colocate_with" = "tpch_group");

CREATE TABLE lineitem (
    l_orderkey BIGINT,
    ...
) DUPLICATE KEY(l_orderkey)
DISTRIBUTED BY HASH(l_orderkey) BUCKETS 16
PROPERTIES ("colocate_with" = "tpch_group");
```

Colocate joins eliminate data shuffle across BE nodes for join operations on aligned distribution keys.

## Managed Cloud Options

Several vendors offer managed Apache Doris cloud services:

| Provider | Service | Description |
|----------|---------|-------------|
| **VeloDB Cloud** | [velodb.io](https://velodb.io) | Fully managed Doris by core contributors |
| **SelectDB Cloud** | [selectdb.com](https://selectdb.com) | Enterprise managed Doris with compute-storage separation |
| **ApsaraDB for SelectDB** | Alibaba Cloud | Managed Doris on Alibaba Cloud infrastructure |

When using managed cloud services:
- The host, port, and credentials are provided by the service
- Stream Load endpoints may use HTTPS (enable `--doris-use-tls`)
- HTTP port may differ from the default 8030

## Troubleshooting

### Connection Refused

```
Error: Failed to connect to Doris
```

**Solutions:**
1. Verify Doris FE is running and accessible on the configured host and port
2. Check that port 9030 (MySQL protocol) is open and not blocked by a firewall
3. For Docker deployments, ensure port mapping is correct (`-p 9030:9030`)
4. Test connectivity directly: `mysql -h <host> -P 9030 -u root`

### Missing PyMySQL Dependency

```
Error: Missing dependencies for doris platform: pymysql
```

**Solutions:**
1. Install PyMySQL: `uv add pymysql`
2. Or install the Doris extra: `uv add benchbox --extra doris`

### Stream Load Failures

```
Error: Stream Load failed with status 503
```

**Solutions:**
1. Verify the FE HTTP port (default 8030) is accessible from the BenchBox host
2. Check that BE nodes are alive: `SHOW BACKENDS;` via MySQL client
3. Ensure the target table exists before loading data
4. For large files (>1 GB), consider increasing the `timeout` or using smaller batch files
5. Install the `requests` library: `uv add requests`

### Schema Creation Failures

```
Error: critical CREATE TABLE statement(s) failed
```

**Solutions:**
1. Check that the Doris user has `CREATE TABLE` and `CREATE DATABASE` permissions
2. Verify the target database exists or the user has `CREATE DATABASE` privilege
3. Review Doris FE logs (`fe.log`) for detailed error messages
4. Ensure sufficient disk space and memory on BE nodes
5. Check for incompatible column types in the translated DDL

### Slow Data Loading

**Solutions:**
1. Install `requests` to enable Stream Load (the recommended bulk-ingest path; INSERT fallback is row-by-row and typically 10x or more slower for large datasets)
2. Ensure the FE HTTP port (8030) is accessible for Stream Load
3. Increase bucket count for better parallelism during loading
4. Check network latency between BenchBox host and Doris cluster
5. Monitor BE resource utilization during loading

### Query Timeout

```
Error: Query execution exceeded timeout
```

**Solutions:**
1. Check Doris resource utilization (CPU, memory, disk I/O) via `SHOW PROC '/backends';`
2. Verify data distribution is balanced across BE nodes
3. Run `ANALYZE TABLE` to update column statistics for the query optimizer
4. Review the query plan with `EXPLAIN` for performance bottlenecks
5. Consider increasing `exec_mem_limit` for memory-intensive queries

## See Also

- [Platform Comparison Matrix](comparison-matrix.md) - Compare all platforms
- [Platform Selection Guide](platform-selection-guide.md) - Choosing the right platform
- [StarRocks Platform](starrocks.md) - Similar MPP OLAP database (shared heritage with Doris)
- [TPC-H Benchmark](../benchmarks/tpch.md) - TPC-H benchmark guide
- [TPC-DS Benchmark](../benchmarks/tpcds.md) - TPC-DS benchmark guide
- [Deployment Modes Guide](deployment-modes.md) - Platform deployment architecture

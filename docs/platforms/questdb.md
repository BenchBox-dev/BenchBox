<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# QuestDB Platform

```{tags} intermediate, guide, questdb, sql-platform, self-hosted, timeseries
```

QuestDB is a high-performance open-source time-series database optimized for fast ingestion and SQL queries. It supports the PostgreSQL wire protocol (port 8812) for query execution and a REST API (port 9000) for efficient bulk data import. BenchBox connects via psycopg2 over the PG wire protocol and uses the REST API `/imp` endpoint for high-throughput CSV ingestion. SQL translation targets the `postgres` dialect via SQLGlot.

QuestDB is designed for time-series and event-driven workloads, with features like designated timestamps, automatic partitioning by time, and the SYMBOL type for low-cardinality string columns. It delivers competitive ingestion throughput against InfluxDB, TimescaleDB, and ClickHouse on time-series workloads.

## Features

- **PostgreSQL wire protocol** - Standard PG wire protocol via psycopg2 (port 8812)
- **REST API CSV import** - High-throughput bulk data loading via `/imp` endpoint (port 9000)
- **Full TPC-H support** - All 22 queries with row count validation
- **PostgreSQL dialect** - SQL translation via SQLGlot `postgres` dialect
- **Time-series optimized** - Designated timestamps, partitioning by time, SYMBOL type
- **Autocommit mode** - PG wire protocol operates in autocommit mode (required by QuestDB)
- **TPC file normalization** - Automatic handling of pipe-delimited `.tbl` files with trailing delimiter removal
- **Chunked parquet loading** - Large parquet inputs are streamed through `/imp` as CSV chunks, with `parquet_chunk_rows` controlling the row budget per request
- **TLS support** - Optional HTTPS for REST API endpoints via `--questdb-use-tls`

## Quick Start

```bash
# Install psycopg2 dependency
uv add psycopg2-binary

# Or install via the QuestDB extra
uv add benchbox --extra questdb

# Configure connection (QuestDB must be running)
export QUESTDB_HOST=localhost

# Run TPC-H benchmark
benchbox run --platform questdb --benchmark tpch --scale 0.01
```

### Docker Quick Start

```bash
# Start QuestDB with Docker (all ports exposed)
docker run -p 9000:9000 -p 8812:8812 -p 9009:9009 -p 9003:9003 \
    questdb/questdb:latest

# Verify PG wire protocol connectivity
psql -h 127.0.0.1 -p 8812 -U admin -d qdb -c "SELECT 1"

# Verify REST API
curl http://localhost:9000/exec?query=SELECT%201

# Run benchmark
benchbox run --platform questdb --benchmark tpch --scale 0.01
```

### QuestDB Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 9000 | HTTP | REST API for CSV import (`/imp`) and queries (`/exec`) |
| 8812 | TCP | PostgreSQL wire protocol for SQL queries |
| 9009 | TCP | InfluxDB Line Protocol (ILP) for high-throughput ingestion |
| 9003 | HTTP | Health check and metrics endpoint |

## Configuration Options

| Option | CLI Argument | Environment Variable | Default | Description |
|--------|-------------|---------------------|---------|-------------|
| `host` | `--questdb-host` | `QUESTDB_HOST` | `localhost` | QuestDB server hostname |
| `pg_port` | `--questdb-pg-port` | `QUESTDB_PG_PORT` | `8812` | PostgreSQL wire protocol port |
| `http_port` | `--questdb-http-port` | `QUESTDB_HTTP_PORT` | `9000` | REST API HTTP port |
| `username` | `--questdb-username` | - | `admin` | QuestDB username |
| `password` | `--questdb-password` | - | `quest` | QuestDB password |
| `database` | `--questdb-database` | - | `qdb` | QuestDB database name |
| `use_tls` | `--questdb-use-tls` | - | `false` | Use HTTPS for REST API endpoints |
| `connect_timeout` | - | - | `10` | Connection timeout in seconds |
| `parquet_chunk_rows` | `--platform-option parquet_chunk_rows=<N>` | - | `200000` | Rows per parquet batch when streaming wide tables through `/imp` |

## Data Loading

BenchBox loads data into QuestDB using the REST API `/imp` endpoint for bulk CSV import. For parquet inputs, the adapter converts each pyarrow batch into CSV and streams it through `/imp`; there is no `COPY FROM STDIN` fallback in the current adapter.

### Loading Process

1. **Schema creation** - Tables are created via PG wire protocol with QuestDB-compatible DDL
2. **Foreign key removal** - FK constraints are stripped (QuestDB does not support foreign keys)
3. **DROP TABLE adaptation** - `IF EXISTS` is added to DROP TABLE statements for idempotent schema creation
4. **TPC file normalization** - Pipe-delimited `.tbl` files are streamed through a normalizer that removes trailing delimiters
5. **REST API import** - CSV data is uploaded to the `/imp` endpoint with table name, delimiter, durability settings, and `forceHeader=true` for chunked parquet uploads
6. **Chunk sizing for wide parquet tables** - `--platform-option parquet_chunk_rows=<N>` lowers the number of rows per `/imp` request when a denormalized parquet file would otherwise exceed QuestDB's HTTP receive budget

### REST API Import (`/imp`)

The primary data loading mechanism uses QuestDB's REST API:

- **Endpoint**: `http://<host>:<http_port>/imp`
- **Method**: HTTP POST with multipart file upload
- **Parameters**: `name` (table), `delimiter`, `overwrite`, `durable` and `forceHeader=true` for chunked parquet uploads
- **Format**: CSV with configurable delimiter (auto-detected for TPC `.tbl` files)
- **Throughput**: Significantly higher than row-by-row INSERT for bulk datasets
- **Wide parquet tuning**: lower `--platform-option parquet_chunk_rows=50000` (or smaller) when a very wide table would make each CSV chunk too large for a single HTTP request

### InfluxDB Line Protocol (ILP)

QuestDB also supports the InfluxDB Line Protocol on port 9009 for high-throughput time-series ingestion. While BenchBox uses the REST API for benchmark data loading, ILP is available for custom ingestion workflows:

- **Port**: 9009 (TCP)
- **Protocol**: InfluxDB Line Protocol
- **Throughput**: Millions of rows per second for time-series data
- **Use case**: Real-time streaming ingestion

## Usage Examples

### Basic Benchmarks

```bash
# TPC-H at scale factor 0.01 (quick test)
benchbox run --platform questdb --benchmark tpch --scale 0.01

# TPC-H at scale factor 1
benchbox run --platform questdb --benchmark tpch --scale 1.0

# Run specific queries only
benchbox run --platform questdb --benchmark tpch --queries Q1,Q6,Q17
```

### Environment Variable Configuration

```bash
export QUESTDB_HOST=questdb.example.com
export QUESTDB_PG_PORT=8812
export QUESTDB_HTTP_PORT=9000

benchbox run --platform questdb --benchmark tpch --scale 1.0
```

### CLI Argument Configuration

```bash
benchbox run --platform questdb --benchmark tpch --scale 1.0 \
    --questdb-host questdb.example.com \
    --questdb-pg-port 8812 \
    --questdb-http-port 9000 \
    --questdb-username admin \
    --questdb-password quest
```

### TLS-Enabled REST API

```bash
benchbox run --platform questdb --benchmark tpch --scale 1.0 \
    --questdb-host questdb.example.com \
    --questdb-use-tls

# Lower parquet chunk size for wide denormalized tables such as tpcds_obt
benchbox run --platform questdb --benchmark tpcds_obt --scale 0.01 \
    --platform-option parquet_chunk_rows=50000
```

### Dry Run (Preview)

```bash
# Preview execution plan without running
benchbox run --platform questdb --benchmark tpch --scale 1.0 --dry-run ./preview
```

## Architecture

### Adapter Structure

The QuestDB adapter is a single-module adapter:

| Module | Class | Responsibility |
|--------|-------|---------------|
| `questdb.py` | `QuestDBAdapter` | Connection, schema, loading, query execution |

### Connection Model

```
BenchBox CLI
    |
    v
QuestDBAdapter
    |
    +-- PG Wire Protocol (psycopg2) --> QuestDB (port 8812)
    |       - Schema DDL (CREATE TABLE, DROP TABLE)
    |       - Query execution (SELECT, EXPLAIN)
    |       - Autocommit mode required
    |
    +-- REST API (requests) --> QuestDB (port 9000)
            - /imp endpoint for bulk CSV import
            - Chunked parquet → CSV uploads via /imp
            - /exec endpoint for row count verification
            - Optional TLS (HTTPS) support
```

### Platform Information

At runtime, BenchBox captures platform metadata:

```python
{
    "platform_type": "questdb",
    "platform_name": "QuestDB",
    "host": "localhost",
    "pg_port": 8812,
    "http_port": 9000,
    "dialect": "postgres",
    "configuration": {
        "database": "qdb"
    },
    "version": "7.x.x"
}
```

### Single Database Model

QuestDB uses a single database per instance. The adapter sets `skip_database_management = True` because:

- There is no `CREATE DATABASE` or `DROP DATABASE` support
- The `database` parameter (default: `qdb`) identifies the instance, not a user-created database
- `check_database_exists()` tests connectivity rather than database presence

## Time-Series Considerations

### Designated Timestamps

QuestDB tables can have a designated timestamp column that enables time-based partitioning and optimized time-range queries:

```sql
CREATE TABLE sensor_data (
    timestamp TIMESTAMP,
    device_id SYMBOL,
    temperature DOUBLE,
    humidity DOUBLE
) TIMESTAMP(timestamp) PARTITION BY DAY;
```

While TPC-H tables do not use designated timestamps, the adapter supports them for custom benchmarks and time-series workloads.

### Partitioning

QuestDB supports automatic time-based partitioning:

- `PARTITION BY NONE` - No partitioning (default)
- `PARTITION BY HOUR` - Hourly partitions
- `PARTITION BY DAY` - Daily partitions
- `PARTITION BY MONTH` - Monthly partitions
- `PARTITION BY YEAR` - Yearly partitions

Partitioning is specified at table creation time and cannot be changed after the fact.

### SYMBOL Type

QuestDB's `SYMBOL` type is optimized for low-cardinality string columns (e.g., status codes, country codes, device IDs). SYMBOLs are stored as integers internally with a symbol table for deduplication, providing significant storage and query performance benefits over VARCHAR for repeated string values.

### Constraints

QuestDB has a minimal constraint model:

- **No foreign keys** - The adapter automatically strips FK constraints from DDL
- **No traditional primary keys** - Uniqueness is not enforced at the database level
- **No ALTER TABLE ADD CONSTRAINT** - Constraints must be defined at table creation time

## Troubleshooting

### Connection Refused

```
Error: Failed to connect to QuestDB
```

**Solutions:**
1. Verify QuestDB is running and accessible on the configured host
2. Check that port 8812 (PG wire protocol) is open and not blocked by a firewall
3. For Docker deployments, ensure port mapping is correct (`-p 8812:8812`)
4. Test connectivity directly: `psql -h <host> -p 8812 -U admin -d qdb -c "SELECT 1"`

### Missing psycopg2 Dependency

```
Error: Missing dependencies for questdb platform: psycopg2
```

**Solutions:**
1. Install psycopg2: `uv add psycopg2-binary`
2. Or install the QuestDB extra: `uv add benchbox --extra questdb`

### REST API Import Failures

```
Error: REST API import failed
```

**Solutions:**
1. Verify the REST API is accessible on the HTTP port (default: 9000)
2. Check that `requests` is installed: `uv add requests`
3. Test the REST API directly: `curl http://<host>:9000/exec?query=SELECT%201`
4. Lower `--platform-option parquet_chunk_rows=<N>` for very wide parquet tables
5. If using TLS, ensure `--questdb-use-tls` is set and certificates are valid

### Schema Creation Failures

```
Error: critical CREATE TABLE statement(s) failed
```

**Solutions:**
1. Check QuestDB server logs for detailed error messages
2. Verify the QuestDB user has sufficient privileges
3. Ensure sufficient disk space on the QuestDB server
4. Review the translated DDL for QuestDB-incompatible syntax (e.g., unsupported column types)

### Autocommit Mode Errors

QuestDB requires autocommit mode on the PG wire protocol. The adapter sets `conn.autocommit = True` automatically. If you encounter transaction-related errors:

1. Ensure you are not wrapping queries in explicit `BEGIN`/`COMMIT` blocks
2. QuestDB does not support multi-statement transactions via PG wire protocol

### Slow Data Loading

**Solutions:**
1. Ensure the REST API port (9000) is accessible for bulk CSV import
2. If falling back to COPY, check network latency between BenchBox host and QuestDB
3. For large datasets, consider increasing the QuestDB server's memory allocation
4. Check disk I/O on the QuestDB server during loading

## See Also

- [Platform Comparison Matrix](comparison-matrix.md) - Compare all platforms
- [Platform Selection Guide](platform-selection-guide.md) - Choosing the right platform
- [TPC-H Benchmark](../benchmarks/tpch.md) - TPC-H benchmark guide
- [TPC-DS Benchmark](../benchmarks/tpcds.md) - TPC-DS benchmark guide
- [Deployment Modes Guide](deployment-modes.md) - Platform deployment architecture

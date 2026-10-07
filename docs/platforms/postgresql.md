<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# PostgreSQL Platform

```{tags} intermediate, guide, postgresql, sql-platform
```

PostgreSQL is a powerful open-source relational database that serves as an excellent baseline for benchmark comparisons. BenchBox supports PostgreSQL 12+ with optional TimescaleDB extensions for time-series workloads.

## Features

- **COPY-based bulk loading** - Efficient data loading using PostgreSQL's COPY command
- **EXPLAIN/EXPLAIN ANALYZE** - Full query plan capture support
- **TimescaleDB support** - Optional time-series extensions for TSBS DevOps benchmark
- **Standard SQL** - Excellent SQL standards compliance

## Installation

PostgreSQL support requires the `psycopg2` driver:

```bash
# Install with pip
pip install psycopg2-binary

# Or with system psycopg2 (recommended for production)
pip install psycopg2
```

## Configuration

### Environment Variables

```bash
# Connection configuration
export PGHOST=localhost
export PGPORT=5432
export PGUSER=postgres
export PGPASSWORD=your_password
export PGDATABASE=benchbox
```

### CLI Options

```bash
benchbox run --platform postgresql --benchmark tpch --scale 1.0 \
  --platform-option host=localhost \
  --platform-option port=5432 \
  --platform-option database=benchbox \
  --platform-option username=postgres \
  --platform-option password=yourpassword \
  --platform-option schema=public
```

### Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | localhost | PostgreSQL server hostname |
| `port` | 5432 | PostgreSQL server port |
| `database` | auto-generated | Database name |
| `username` | postgres | PostgreSQL username |
| `password` | (none) | PostgreSQL password |
| `schema` | public | Target schema |
| `work_mem` | 256MB | Working memory for sorts/hashes |
| `statement_timeout` | (unset) | Per-statement timeout in milliseconds; `0` disables |
| `enable_timescale` | false | Enable TimescaleDB features |
| `driver_version` | (latest) | Pin the psycopg2-binary package version (e.g. `2.9.11`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific psycopg2 Version

```bash
benchbox run --platform postgresql --benchmark tpch \
  --platform-option driver_version=2.9.11 \
  --platform-option driver_auto_install=true \
  --platform-option host=localhost
```

The driver package for PostgreSQL is `psycopg2-binary`.

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Usage Examples

### Basic Benchmark Run

```bash
# Run TPC-H on PostgreSQL
benchbox run --platform postgresql --benchmark tpch --scale 0.1 \
  --platform-option host=localhost \
  --platform-option database=tpch_benchmark
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.postgresql import PostgreSQLAdapter

# Initialize adapter
adapter = PostgreSQLAdapter(
    host="localhost",
    port=5432,
    database="benchbox",
    username="postgres",
    password="password",
)

# Load and run benchmark
benchmark = TPCH(scale_factor=0.1)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

### TimescaleDB Integration

For time-series benchmarks like TSBS DevOps, enable TimescaleDB:

```bash
benchbox run --platform postgresql --benchmark tsbs-devops --scale 1.0 \
  --platform-option enable_timescale=true \
  --platform-option host=localhost
```

## Performance Tuning

### Recommended Settings

For benchmark workloads, consider these PostgreSQL settings:

```sql
-- Connection-level settings (set via platform options)
SET work_mem = '256MB';
SET maintenance_work_mem = '1GB';
SET effective_cache_size = '8GB';

-- Server-level settings (postgresql.conf)
shared_buffers = 4GB
effective_io_concurrency = 200
random_page_cost = 1.1
```

### Tuning Mode

BenchBox supports automatic tuning configuration:

```bash
# Run with tuning enabled
benchbox run --platform postgresql --benchmark tpch \
  --tuning tuned

# Run baseline (no tuning)
benchbox run --platform postgresql --benchmark tpch \
  --tuning notuning
```

## Query Plan Capture

PostgreSQL provides detailed query plan analysis:

```bash
benchbox run --platform postgresql --benchmark tpch \
  --capture-plans
```

This captures EXPLAIN ANALYZE output including:
- Execution time per node
- Actual vs estimated rows
- Memory usage
- I/O statistics

## Limitations

- **No native columnar storage** - Row-oriented by default (consider Citus for columnar)
- **Single-node** - No built-in distributed query execution
- **Memory constraints** - Large datasets may require careful configuration

## Troubleshooting

### Connection Refused

```bash
# Verify PostgreSQL is running
pg_isready -h localhost -p 5432

# Check pg_hba.conf for access rules
```

### Permission Denied

```sql
-- Grant necessary permissions
GRANT CREATE ON DATABASE benchbox TO your_user;
GRANT USAGE ON SCHEMA public TO your_user;
```

### Memory Errors

```bash
# Increase work_mem for complex queries
benchbox run --platform postgresql --benchmark tpcds \
  --platform-option work_mem=512MB
```

## Related Documentation

- [Platform Selection Guide](platform-selection-guide.md)
- [TSBS DevOps Benchmark](../benchmarks/tsbs-devops.md) - Time-series benchmark with TimescaleDB
- [TPC-H Benchmark](../benchmarks/tpc-h.md)

# Benchmarking PostgreSQL Extensions

```{tags} guide, postgresql, extensions, pg-duckdb, pg-mooncake, timescaledb
```

BenchBox supports benchmarking PostgreSQL analytical extensions as first-class platforms. Each extension accelerates different workloads by adding specialized execution engines or storage formats to PostgreSQL.

## Supported Extensions

| Extension | Platform Name | Category | Storage | Execution |
|-----------|---------------|----------|---------|-----------|
| [pg_duckdb](../platforms/pg_duckdb.md) | `pg-duckdb` | OLAP acceleration | PostgreSQL heap | DuckDB vectorized |
| [pg_mooncake](../platforms/pg_mooncake.md) | `pg-mooncake` | OLAP columnstore | Parquet/Iceberg | DuckDB vectorized |
| [TimescaleDB](../platforms/timescaledb.md) | `timescaledb` | Time-series | Hypertables (chunked heap) | PostgreSQL planner |

## Quick Start

Each extension has a Docker Compose file for easy setup:

```bash
# Start one extension at a time:
cd docker/postgres-extensions/

# pg_duckdb - DuckDB-accelerated analytics on PostgreSQL heap tables
docker compose -f docker-compose.pg-duckdb.yaml up -d

# pg_mooncake - Native columnstore with DuckDB execution
docker compose -f docker-compose.pg-mooncake.yaml up -d

# TimescaleDB - Time-series hypertables with compression
docker compose -f docker-compose.timescaledb.yaml up -d
```

Then run benchmarks:

```bash
# pg_duckdb
benchbox run --platform pg-duckdb --benchmark tpch --scale 0.01 \
  --platform-option host=localhost --platform-option password=benchbox

# pg_mooncake
benchbox run --platform pg-mooncake --benchmark tpch --scale 0.01 \
  --platform-option host=localhost --platform-option password=benchbox

# TimescaleDB
benchbox run --platform timescaledb --benchmark tsbs-devops --scale 1.0 \
  --platform-option host=localhost --platform-option password=benchbox

# Vanilla PostgreSQL (for baseline comparison)
benchbox run --platform postgresql --benchmark tpch --scale 0.01 \
  --platform-option host=localhost --platform-option password=benchbox
```

## Extension Compatibility Matrix

Not all extensions can coexist in the same PostgreSQL instance:

| Extension | pg_duckdb | pg_mooncake | TimescaleDB | PostgreSQL |
|-----------|:---------:|:-----------:|:-----------:|:----------:|
| pg_duckdb | - | **CONFLICT** | OK | OK |
| pg_mooncake | **CONFLICT** | - | OK | OK |
| TimescaleDB | OK | OK | - | OK |

**pg_duckdb and pg_mooncake share `libduckdb.so`** and cannot be installed in the same PostgreSQL instance. Use separate Docker containers or server instances for each.

You can query conflicts programmatically:

```python
from benchbox.core.platform_registry import PlatformRegistry

conflicts = PlatformRegistry.get_platform_conflicts("pg-duckdb")
# Returns: ["pg-mooncake"]
```

## Architecture Pattern

All PostgreSQL extensions follow the same adapter pattern:

```
PostgreSQLAdapter (base)
├── TimescaleDBAdapter (hypertables, compression)
├── PgDuckDBAdapter (DuckDB execution, MotherDuck)
└── PgMooncakeAdapter (heap-load plus mooncake mirrors, S3 storage)
```

Each extension adapter inherits from `PostgreSQLAdapter` and overrides specific methods:

| Method | PostgreSQL | pg_duckdb | pg_mooncake | TimescaleDB |
|--------|-----------|-----------|-------------|-------------|
| `create_connection()` | Standard | + extension verify, GUCs | + extension verify, bucket | + extension verify |
| `create_schema()` | Standard DDL | Inherited | Standard heap DDL for COPY | + create_hypertable() |
| `configure_for_benchmark()` | PG settings | + force_execution | Inherited | + compression |
| `load_data()` | COPY | Inherited | COPY, then `mooncake.create_table` mirrors | Inherited |
| `get_target_dialect()` | postgres | postgres | postgres | postgres |

## Recommended Comparisons

### OLAP Performance (TPC-H / TPC-DS)

Compare analytical query performance across storage and execution strategies:

```bash
# Baseline: vanilla PostgreSQL
benchbox run --platform postgresql --benchmark tpch --scale 1.0

# pg_duckdb: DuckDB execution on heap tables (no storage change)
benchbox run --platform pg-duckdb --benchmark tpch --scale 1.0

# pg_mooncake: DuckDB execution on columnstore tables (storage + execution)
benchbox run --platform pg-mooncake --benchmark tpch --scale 1.0

# Native DuckDB: standalone columnar database
benchbox run --platform duckdb --benchmark tpch --scale 1.0
```

### Real-World Analytics (ClickBench)

Compare on real-world analytical query patterns:

```bash
benchbox run --platform pg-mooncake --benchmark clickbench
benchbox run --platform duckdb --benchmark clickbench
benchbox run --platform clickhouse --benchmark clickbench
```

### Time-Series (TSBS)

```bash
benchbox run --platform timescaledb --benchmark tsbs-devops --scale 1.0
benchbox run --platform postgresql --benchmark tsbs-devops --scale 1.0
```

## Key Differences Between Extensions

### pg_duckdb vs pg_mooncake

| Aspect | pg_duckdb | pg_mooncake |
|--------|-----------|-------------|
| **What changes** | Execution engine only | Storage format + execution engine |
| **Load path** | Standard `CREATE TABLE` + COPY | Standard `CREATE TABLE` + COPY, then mooncake mirror promotion |
| **Data format** | PostgreSQL heap (row-oriented) | Parquet (columnar) |
| **Compression** | None (heap tables) | 5-20x columnar compression |
| **Indexes** | B-tree available (but bypassed by DuckDB) | Not supported |
| **Constraints** | Full PK/FK support | Not supported |
| **Best for** | Adding analytics to existing PostgreSQL | New analytical workloads |
| **Cloud variant** | MotherDuck | S3/GCS object storage |

### When to Use Each

- **pg_duckdb**: You have an existing PostgreSQL database and want faster analytical queries without changing schema or data format.
- **pg_mooncake**: You want true columnar storage with maximum compression and analytical performance, and can use BenchBox's heap-load plus mirror-promotion path.
- **TimescaleDB**: Your workload is time-series data with time-based partitioning and compression needs.
- **Vanilla PostgreSQL**: You need a baseline comparison or your workload is OLTP-focused.

## Adding a New Extension

To add support for a new PostgreSQL extension:

1. Create `benchbox/platforms/<extension>.py` with a class extending `PostgreSQLAdapter`
2. Override `create_connection()` to verify the extension is installed
3. Override any methods that need extension-specific behavior
4. Register in `benchbox/core/platform_registry.py` (metadata + adapter)
5. Add to `benchbox/platforms/__init__.py` (import + hooks)
6. Create a DDL generator if the extension changes table structure
7. Write unit tests following the patterns in `tests/unit/platforms/`
8. Add Docker Compose file in `docker/postgres-extensions/`

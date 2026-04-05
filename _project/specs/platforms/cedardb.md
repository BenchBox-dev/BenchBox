# Specification: CedarDB Platform Adapter

## Overview

The CedarDB platform adapter extends the PostgreSQL adapter to support CedarDB (formerly Umbra),
a high-performance RDBMS that handles both OLAP and OLTP workloads using the PostgreSQL wire
protocol. CedarDB is not a PostgreSQL extension — it is a standalone database engine fully
compatible with PostgreSQL drivers (psycopg2/psycopg3) and tooling (psql, DBeaver, DataGrip).

Reference: https://cedardb.com/docs/

## Location

**File**: `benchbox/platforms/cedardb.py`
**Module**: `benchbox.platforms.cedardb`
**Inheritance**: `PlatformAdapter` → `PostgreSQLAdapter` → `CedarDBAdapter`

## Public Interface

### `CedarDBAdapter`

CedarDB platform adapter for high-performance OLAP/OLTP benchmarking.

**Attributes** (CedarDB-specific):

None beyond PostgreSQLAdapter — CedarDB uses standard PostgreSQL protocol without extensions.

**Inherited Attributes** (from PostgreSQLAdapter):

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `host` | `str` | Database server hostname | `"localhost"` |
| `port` | `int` | Database server port | `5432` |
| `database` | `str` | Target database name | `"benchbox"` |
| `username` | `str` | Database username | `"postgres"` |
| `password` | `str \| None` | Database password | `None` |
| `schema` | `str` | Target schema name | `"public"` |
| `sslmode` | `str` | SSL connection mode | `"prefer"` |
| `admin_database` | `str` | Admin database for DDL operations | `"postgres"` |
| `work_mem` | `str` | PostgreSQL work_mem setting | `"256MB"` |
| `maintenance_work_mem` | `str` | PostgreSQL maintenance_work_mem setting | `"512MB"` |
| `effective_cache_size` | `str` | PostgreSQL effective_cache_size setting | `"1GB"` |
| `max_parallel_workers_per_gather` | `int` | Parallel worker limit | `2` |

**Methods**:

| Method | Signature | Description |
| ------ | --------- | ----------- |
| `platform_name` | `@property → str` | Returns `"CedarDB"` |
| `get_target_dialect` | `() → str` | Returns PostgreSQL dialect identifier |
| `add_cli_arguments` | `@staticmethod (parser) → None` | Registers CedarDB CLI arguments |
| `from_config` | `@classmethod (config: dict) → CedarDBAdapter` | Factory method from configuration |
| `get_platform_info` | `(connection) → dict` | Returns CedarDB platform information including version string |
| `supports_tuning_type` | `(tuning_type) → bool` | Returns supported tuning types |

## Module-Level Functions

### `_build_cedardb_config(benchmark_config, platform_options) → dict`

Configuration builder registered with `PlatformHookRegistry` for `"cedardb"`. Merges
`platform_options` with `benchmark_config` (benchmark config takes precedence on key conflicts).

## Platform Registry Key

`"cedardb"` — accessed as `--platform cedardb` in the CLI.

## SQL Dialect

CedarDB uses the PostgreSQL SQL dialect (`"postgres"`). No dialect translation is needed.

## Bulk Loading

CedarDB supports the PostgreSQL `COPY` protocol for bulk data loading. The adapter inherits
`PostgreSQLAdapter.load_data()` unchanged — standard `COPY FROM STDIN` is used.

## Connection

Standard PostgreSQL wire protocol. Connect via psycopg2 or psycopg3 using standard
PostgreSQL connection parameters. No special extensions need to be created or verified.

```python
from benchbox.platforms.cedardb import CedarDBAdapter

adapter = CedarDBAdapter(
    host="localhost",
    port=5432,
    database="benchbox_tpch_sf1",
    username="postgres",
    password="mypassword",
)
```

## CLI Usage

```bash
benchbox run --platform cedardb --benchmark tpch --scale 1 \
    --platform-option host=localhost \
    --platform-option port=5432 \
    --platform-option username=postgres \
    --platform-option password=secret
```

## Tuning Support

| TuningType | Supported | Notes |
| ---------- | --------- | ----- |
| PARTITIONING | ✗ | Not verified — needs live CedarDB testing |
| SORTING | ✗ | No native sort keys |
| DISTRIBUTION | ✗ | Single-node only |
| CLUSTERING | ✗ | Not verified — CLUSTER is PG-specific |
| PRIMARY_KEYS | ✓ | Full constraint support |
| FOREIGN_KEYS | ✓ | Full constraint support |

## Known Limitations

- Single-node only (no distributed mode)
- Cloud-hosted CedarDB, if offered in future, would require a separate adapter variant
- CedarDB-specific GUC parameters (if any) are not yet mapped — relies on PostgreSQL-compatible settings

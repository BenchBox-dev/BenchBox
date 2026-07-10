<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# DuckLake Platform

```{tags} intermediate, guide, ducklake, sql-platform, experimental
```

DuckLake is an open lakehouse table format shipped as a DuckDB extension: table **data** is stored as Parquet files, while table **metadata** (the catalog) lives in a SQL database. BenchBox runs DuckLake through the same DuckDB engine used by the `duckdb` platform, inheriting DuckDB's SQL dialect and benchmark compatibility unchanged.

```{warning}
The DuckLake platform is **experimental**. This MVP supports the DuckDB-file catalog combined with local Parquet storage only. SQLite/Postgres catalogs and S3-backed `DATA_PATH` are a follow-on scope.
```

## Features

- **Lakehouse format** - Parquet table data, SQL-database catalog metadata
- **DuckDB dialect** - Inherits SQL dialect and query translation from DuckDB
- **Reused engine** - Schema creation, data loading, query execution, plan capture, and tuning are all inherited from `DuckDBAdapter` unchanged
- **Catalog reuse** - Re-attaches an existing catalog by default; `--force` wipes catalog + data for a clean rebuild

## Quick Start

```bash
# Install DuckDB >= 1.3 (required for the ducklake extension)
uv add "duckdb>=1.3,<2.0"

# Run benchmark (metadata/data paths default under benchmark_runs/databases/)
benchbox run --platform ducklake --benchmark tpch --scale 0.01
```

## Requirements

DuckLake requires a live **DuckDB >= 1.3** runtime — the `ducklake` extension is not available on earlier releases. This floor is enforced at connection time by the adapter itself, independent of the `duckdb` package version pinned by the global BenchBox `pyproject.toml` (which stays `<2.0` for `duckdb-wasm` on-disk-format compatibility). If the detected DuckDB version is too old, the adapter raises immediately with the detected version and a remediation hint (e.g. `uv add 'duckdb>=1.3,<2.0'` or `--driver-version 1.3.2`).

The first run also needs network access once, to `INSTALL` the `ducklake` extension.

## Configuration Options

| Option | CLI Flag | Default | Description |
|--------|----------|---------|--------------|
| `metadata_path` | `--ducklake-metadata-path` | Generated under `benchmark_runs/databases/` | Path to the DuckLake catalog metadata file (`.ducklake`) |
| `data_path` | `--ducklake-data-path` | Generated under `benchmark_runs/databases/.../ducklake_data/` | Path to the DuckLake Parquet data directory |

Both can also be set with `--platform-option`:

```bash
benchbox run --platform ducklake --benchmark tpch --scale 0.1 \
    --platform-option metadata_path=/path/to/catalog.ducklake \
    --platform-option data_path=/path/to/parquet_data
```

## Usage Examples

### Basic Benchmark

```bash
# TPC-H at scale factor 0.01 with default (generated) paths
benchbox run --platform ducklake --benchmark tpch --scale 0.01

# TPC-DS at scale factor 1
benchbox run --platform ducklake --benchmark tpcds --scale 1.0
```

### Explicit Catalog and Data Paths

```bash
benchbox run --platform ducklake --benchmark tpch --scale 0.1 \
    --ducklake-metadata-path ./ducklake_catalogs/tpch_sf0.1.ducklake \
    --ducklake-data-path ./ducklake_catalogs/tpch_sf0.1_data
```

### Clean Rebuild

Without `--force`, an existing catalog at `metadata_path` is reused: schema creation and data loading are skipped and queries run directly against the already-populated catalog.

```bash
# Wipe the existing catalog metadata file and Parquet data, then rebuild
benchbox run --platform ducklake --benchmark tpch --scale 0.1 --force
```

## Python API

```python
from benchbox import TPCH
from benchbox.platforms.ducklake import DuckLakeAdapter

# Initialize adapter
adapter = DuckLakeAdapter(
    metadata_path="benchmark_runs/databases/tpch_sf1.ducklake",
    data_path="benchmark_runs/databases/tpch_sf1_data",
)

# Load and run benchmark
benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## Architecture

DuckLake extends `DuckDBAdapter`, which means:

- **SQL Dialect**: Uses DuckDB's SQL dialect for query translation
- **Data Types**: Same data type mappings as DuckDB
- **Benchmark Compatibility**: Supports all benchmarks that DuckDB supports
- **Connection setup**: `create_connection()` runs `INSTALL ducklake; LOAD ducklake; ATTACH 'ducklake:<metadata_path>' AS lake (DATA_PATH '<data_path>'); USE lake;` before any benchmark DDL/DML, so subsequent unqualified `CREATE TABLE`/`INSERT INTO` statements resolve against the attached `lake` catalog

```python
from benchbox.core.platform_registry import PlatformRegistry

# Check platform family
family = PlatformRegistry.get_platform_family("ducklake")
# Returns: "duckdb"

# Check inheritance
parent = PlatformRegistry.get_inherited_platform("ducklake")
# Returns: "duckdb"
```

## Comparison: DuckLake vs DuckDB

| Feature | DuckLake | DuckDB |
|---------|----------|--------|
| Table data | Parquet files under `DATA_PATH` | DuckDB native storage format |
| Catalog | Separate SQL-database metadata file | Embedded in the database file |
| Deployment | Local (this MVP); catalog/storage backends are pluggable | Local embedded |
| Requirements | DuckDB >= 1.3 + `ducklake` extension | DuckDB (any supported version) |
| Support status | Experimental | Stable |
| Best For | Evaluating lakehouse table-format overhead on DuckDB | General local benchmarking |

## When to Use DuckLake

**Use DuckLake when:**
- You want to benchmark lakehouse table-format overhead (separate catalog + Parquet data) against plain DuckDB storage
- You are prototyping against DuckLake's Parquet-data/SQL-catalog split before adopting a non-DuckDB catalog backend
- You need results that stay directly comparable to `duckdb` because the underlying engine and dialect are identical

**Use DuckDB instead when:**
- You do not need a separate catalog/data-file split
- You are on a DuckDB runtime older than 1.3
- You want the most stable, non-experimental local platform

## Follow-On Scope

This MVP adapter supports only the DuckDB-file catalog with local Parquet `DATA_PATH`. The following are tracked as follow-on work, not yet supported:

- SQLite and Postgres catalog backends
- S3-backed (or other object storage) `DATA_PATH`

## Troubleshooting

### DuckDB Version Too Old

```
RuntimeError: DuckLake requires DuckDB >= 1.3 (the 'ducklake' extension is not
available on earlier releases). Detected DuckDB version: 1.2.x. ...
```

**Solution:** Upgrade the `duckdb` package, e.g. `uv add 'duckdb>=1.3,<2.0'`, or pin a compatible driver with `--driver-version 1.3.2 --platform-option driver_auto_install=true`.

### Catalog Attach Failure

```
RuntimeError: Failed to initialize the DuckLake catalog (INSTALL/LOAD/ATTACH 'ducklake' extension). ...
```

**Solutions:**
1. Confirm network access is available for the first `INSTALL ducklake` (extension download)
2. Verify `metadata_path`'s parent directory and `data_path` are writable
3. Re-run with `--force` if a previous run left a partially-initialized catalog

### Table Already Exists

If a benchmark run is interrupted mid-load, a subsequent run without `--force` reuses the existing (partially loaded) catalog. Pass `--force` to wipe the catalog metadata file and Parquet data directory and rebuild from scratch.

## Related Documentation

- [DuckDB Platform](duckdb.md) - Local DuckDB benchmarking
- [MotherDuck Platform](motherduck.md) - Serverless DuckDB cloud (also inherits the DuckDB dialect)
- [Deployment Modes Guide](deployment-modes.md) - Platform deployment architecture
- [Platform Selection Guide](platform-selection-guide.md) - Choose the right platform
- [Getting Started](../usage/getting-started.md) - Quick start guide

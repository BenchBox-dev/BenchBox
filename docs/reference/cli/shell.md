(cli-shell)=
# `shell` - Interactive SQL Shell

```{tags} reference, cli, intermediate
```

Launch an interactive SQL shell connected to a database platform. Useful for debugging queries, inspecting benchmark data, and exploring database state after benchmark execution.

## Basic Syntax

```bash
benchbox shell [OPTIONS]
```

## Core Options

**Database Discovery:**
- `--list`: List available databases and exit
- `--last`: Connect to last modified database
- `--benchmark TEXT`: Filter by benchmark name when discovering databases
- `--scale FLOAT`: Filter by scale factor when discovering databases
- `--output PATH`: Output directory to search for databases (default: benchmark_runs)

**Direct Connection:**
- `--platform TEXT`: Platform type (duckdb, sqlite, clickhouse) - auto-detected if not specified
- `--database PATH`: Database file path or connection string

**Remote Connection (ClickHouse):**
- `--host TEXT`: Database host
- `--port INTEGER`: Database port
- `--user TEXT`: Database username
- `--password TEXT`: Database password

## Supported Platforms

**Local Databases:**
- **DuckDB** - Full interactive shell with `.tables`, `.schema`, `.info` commands
- **SQLite** - Full interactive shell with SQLite-specific commands

**Remote Databases:**
- **ClickHouse** - Connection guidance (native client integration coming soon)

## Usage Examples

### Interactive Database Selection

```bash
# Discover and select from available databases
benchbox shell

# List all available databases without connecting
benchbox shell --list
```

### Quick Connection

```bash
# Connect to most recent database
benchbox shell --last

# Connect to most recent TPC-H database
benchbox shell --last --benchmark tpch

# Connect to specific scale factor
benchbox shell --benchmark tpch --scale 1.0
```

### Direct Connection

```bash
# Connect to specific DuckDB database
benchbox shell --platform duckdb --database benchmark.duckdb

# Connect to SQLite database
benchbox shell --platform sqlite --database benchmark.db

# Auto-detect platform from file extension
benchbox shell --database benchmark.duckdb  # Detects DuckDB
```

### Custom Output Directory

```bash
# Use database from specific benchmark run
benchbox shell --output benchmark_runs/results/tpch_20250101_120000

# Filter within custom directory
benchbox shell --output ./my-benchmarks --benchmark tpcds --scale 10
```

### Remote Database Connection

```bash
# ClickHouse connection
benchbox shell --platform clickhouse-server --host localhost --port 9000 \
  --user default --database benchbox
```

## Shell Features

### DuckDB Shell Commands

- `.tables` - List all tables with row counts
- `.schema [table]` - Show schema for table(s)
- `.info` - Display database information (size, table count)
- `.quit` / `.exit` - Exit the shell
- SQL queries - Execute any SQL query with timing information

### SQLite Shell Commands

- `.tables` - List all tables with row counts
- `.schema [table]` - Show schema for table(s)
- `.info` - Display database information
- `.quit` / `.exit` - Exit the shell
- SQL queries - Execute any SQL query with timing information

### Common Features

- **Command History**: Arrow keys to navigate previous commands (readline support)
- **Query Timing**: Automatic execution time measurement
- **Result Formatting**: Tabular output with column headers
- **Error Handling**: Clear error messages for invalid queries

## Common Workflows

### Debugging Query Results

```bash
# Connect to benchmark database
benchbox shell --last --benchmark tpch

# Verify data loaded correctly
duckdb> SELECT COUNT(*) FROM lineitem;
duckdb> .tables

# Test individual queries
duckdb> SELECT l_returnflag, COUNT(*) FROM lineitem GROUP BY l_returnflag;

# Exit when done
duckdb> .quit
```

### Exploring Schema

```bash
# Connect and explore
benchbox shell --database benchmark.duckdb

# Show all table schemas
duckdb> .schema

# Inspect specific table
duckdb> .schema customer
duckdb> SELECT * FROM customer LIMIT 5;
```

### Comparing Scale Factors

```bash
# List available databases to compare
benchbox shell --list

# Connect to SF 0.1
benchbox shell --benchmark tpch --scale 0.1
duckdb> SELECT COUNT(*) FROM orders;
duckdb> .quit

# Connect to SF 1.0
benchbox shell --benchmark tpch --scale 1.0
duckdb> SELECT COUNT(*) FROM orders;
```

## Database Discovery

BenchBox automatically discovers databases in standard locations:
- `{output}/datagen/**/*.{duckdb,db}` (recursive search)
- `{output}/databases/*.{duckdb,db}` (flat search)

Default output directory: `benchmark_runs/`

Discovery includes:
- Platform detection from file extension
- Metadata parsing from filename (benchmark, scale factor, tuning mode)
- File size and modification time
- Automatic sorting by most recent first

## Interactive Selection

When multiple databases match your criteria:
1. BenchBox displays a table with all matching databases
2. Shows: benchmark, scale factor, platform, tuning mode, size, modification date, path
3. Prompts you to select by number
4. Auto-selects if only one database matches

## Notes

- **Read-Only Mode**: By default, DuckDB shells open in read-write mode. Use caution when modifying benchmark databases.
- **Platform Auto-Detection**: File extensions map to platforms: `.duckdb` → DuckDB, `.db` → SQLite
- **Discovery Performance**: Large output directories may take a moment to scan
- **ClickHouse Support**: Currently provides connection guidance; native interactive shell coming in a future release

## Troubleshooting

**No databases found:**
```bash
# Verify databases exist
ls benchmark_runs/datagen/

# Run a benchmark first to create database
benchbox run --benchmark tpch --scale 0.1 --platform duckdb
```

**Wrong database selected:**
```bash
# Use more specific filters
benchbox shell --benchmark tpch --scale 1.0 --platform duckdb

# Or connect directly
benchbox shell --database /path/to/specific/database.duckdb
```

**Connection errors:**
- Ensure platform dependencies are installed (`benchbox check-deps`)
- Verify database file exists and is not corrupted
- Check file permissions

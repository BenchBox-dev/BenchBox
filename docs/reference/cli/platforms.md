(cli-platforms)=
# `platforms` - Platform Management

```{tags} reference, cli, sql-platform
```

Manage database platform adapters, check availability, and configure platforms for use with BenchBox.

The `platforms` command group provides tools for:
- Discovering available database platforms
- Enabling/disabling platforms for benchmark execution
- Checking platform dependencies and installation status
- Getting installation guidance for missing dependencies
- Interactive platform setup wizard

## Subcommands

### `platforms list` - List Available Platforms

List all database platforms with their current status and availability.

**Options:**
- `--all`: Show all platforms including those with missing dependencies
- `--format [table|simple]`: Output format (default: table)

**Usage Examples:**

```bash
benchbox platforms list

benchbox platforms list --all

benchbox platforms list --format simple
```

### `platforms status` - Show Platform Status

Display detailed status information for platforms, including library versions and configuration.

**Usage:**

```bash
benchbox platforms status

benchbox platforms status duckdb
benchbox platforms status databricks
```

### `platforms enable` - Enable a Platform

Enable a platform for use in benchmark execution.

**Options:**
- `--force`: Enable platform even if dependencies are missing (not recommended)

**Usage Examples:**

```bash
benchbox platforms enable clickhouse

benchbox platforms enable snowflake --force
```

### `platforms disable` - Disable a Platform

Disable a platform to prevent its use in benchmarks.

**Usage:**

```bash
benchbox platforms disable sqlite
```

### `platforms install` - Installation Guide

Get step-by-step installation guidance for platform dependencies.

**Options:**
- `--dry-run`: Show installation commands without explaining

**Usage Examples:**

```bash
benchbox platforms install clickhouse

benchbox platforms install databricks --dry-run
```

### `platforms check` - Check Platform Availability

Check platform availability and configuration status. Useful for CI/CD validation.

**Options:**
- `--enabled-only`: Check only enabled platforms

**Usage Examples:**

```bash
benchbox platforms check

benchbox platforms check --enabled-only

benchbox platforms check duckdb databricks bigquery
```

**Exit Codes:**
- `0`: All checked platforms are ready
- `1`: One or more platforms have issues

### `platforms setup` - Interactive Setup Wizard

Launch an interactive wizard to configure platforms. Guides you through enabling, disabling, and installing platforms.

**Options:**
- `--interactive` / `--non-interactive`: Setup mode (default: interactive)

**Usage Examples:**

```bash
benchbox platforms setup

benchbox platforms setup --non-interactive
```

## Common Workflows

### First-Time Setup

```bash
benchbox platforms list

benchbox platforms status

benchbox platforms install clickhouse

benchbox platforms enable clickhouse
benchbox platforms enable duckdb

benchbox platforms check --enabled-only
```

### Cloud Platform Setup

```bash
benchbox platforms enable databricks

benchbox setup --platform databricks

benchbox platforms status databricks
```

### Troubleshooting

```bash
benchbox platforms status <platform>

benchbox platforms install <platform>

benchbox platforms enable <platform>

benchbox platforms check <platform>
```

## Platform Categories

BenchBox supports platforms in several categories:

- **Analytical**: DuckDB, ClickHouse (columnar OLAP engines)
- **Cloud**: Databricks, Snowflake, BigQuery, Redshift (cloud warehouses)
- **Embedded**: SQLite (lightweight row-store database)

## Configuration

Platform configuration is stored in `~/.benchbox/platforms.yaml`:

```yaml
enabled:
  - duckdb
  - clickhouse
  - databricks
```

You can manually edit this file, but it's recommended to use the `platforms enable/disable` commands.

## Notes

- **Credentials vs. Availability**: The `platforms` commands manage platform *availability* (dependencies installed). For cloud platforms, you also need to configure *credentials* using `benchbox setup --platform <name>`.
- **Dependency Management**: Platform dependencies are installed via `pip` or `uv`. The `platforms install` command provides guidance but doesn't execute installations automatically.
- **Enabled by Default**: Most platforms are enabled by default if their dependencies are detected. You only need to explicitly enable platforms if you've previously disabled them.

## Related

- [Configuration](configuration.md) - Environment variables and platform authentication
- [Platform Documentation](../../platforms/index.md) - Detailed platform-specific guides

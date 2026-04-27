# Utility Commands

```{tags} reference, cli
```

This page covers smaller utility commands for dependency checking, system profiling, benchmark discovery, and configuration validation.

(cli-check-deps)=
## `check-deps` - Check Dependencies

Check dependency status and provide installation guidance for different platforms.

### Options

- `--platform TEXT`: Check dependencies for specific platform
- `--verbose`, `-v`: Show detailed dependency information
- `--matrix`: Show installation matrix and exit

### Usage Examples

```bash
# Overview of all platform dependencies
benchbox check-deps

# Check specific platform
benchbox check-deps --platform databricks

# Show detailed installation matrix
benchbox check-deps --matrix

# Verbose output with recommendations
benchbox check-deps --verbose
```

(cli-profile)=
## `profile` - System Profiling

Profile the current system to understand hardware capabilities and provide recommendations.

### Usage

```bash
benchbox profile
```

This command analyzes:
- CPU cores and architecture
- Memory capacity and availability
- Disk space
- Operating system details
- Python environment

Provides recommendations for:
- Appropriate scale factors
- Concurrency settings
- Platform selection

(cli-benchmarks)=
## `benchmarks` - Manage Benchmark Suites

Manage and browse available benchmark suites.

### Subcommands

#### `benchmarks list`

Display all available benchmark suites with descriptions.

```bash
benchbox benchmarks list
```

Shows information about:
- TPC-H, TPC-DS, TPC-DI (official TPC benchmarks)
- ClickBench, H2ODB (industry benchmarks)
- SSB, AMPLab (academic benchmarks)
- ReadPrimitives, WritePrimitives, TPC-Havoc (testing benchmarks)

(cli-validate)=
## `validate` - Validate Configuration

Validate BenchBox configuration files for syntax and completeness.

### Options

- `--config TEXT`: Configuration file path (optional)

### Usage Examples

```bash
# Validate default configuration
benchbox validate

# Validate specific configuration file
benchbox validate --config ./custom-config.yaml
```

(cli-validate-results)=
## `validate_results.py` - Result Integrity Validation

Validate benchmark result JSON files for structural integrity, completeness, and statistical believability. Runs 20 checks across three tiers against hardcoded benchmark specifications.

This is a standalone script (not a `benchbox` subcommand) located at `_project/scripts/validate_results.py`.

### Usage

```bash
uv run _project/scripts/validate_results.py <path> [options]
```

### Arguments

- `path`: Result file (`.json`) or directory containing result files

### Options

- `--json`: Machine-readable JSON output
- `--verbose`: Show all checks including PASSes (default: WARN+FAIL only)
- `--fail-on-warn`: Exit 1 if any WARNs present (default: only FAILs cause exit 2)
- `--benchmark STR`: Filter by benchmark ID or platform name (directory mode only)

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed (or WARN-only without `--fail-on-warn`) |
| 1 | Warnings present with `--fail-on-warn` |
| 2 | One or more FAILures detected |

### Examples

```bash
# Validate all results for a specific benchmark
uv run _project/scripts/validate_results.py benchmark_runs/results/ --benchmark tpch

# Validate a single result file with verbose output
uv run _project/scripts/validate_results.py benchmark_runs/results/tpch_duckdb_sf1.json --verbose

# Machine-readable JSON output for CI pipelines
uv run _project/scripts/validate_results.py benchmark_runs/results/ --json

# Strict mode - treat warnings as failures
uv run _project/scripts/validate_results.py benchmark_runs/results/ --fail-on-warn
```

### Output Format

Default output shows one block per file with a header line and a table of WARN/FAIL checks:

```
File: tpch_duckdb_sf1_20260401.json
Benchmark: tpch | Platform: DuckDB | SF: 1.0 | Status: PASS

CATEGORY         CHECK                          STATUS MESSAGE
```

With `--json`, outputs a JSON array of report objects suitable for programmatic consumption.

### What It Checks

The validator runs 20 checks in three tiers. See the [Result Integrity Validation](../../development/result-integrity-validation.md) developer guide for the full check list.

**Notes:**
- Automatically excludes `.plans.json` and `.tuning.json` companion files
- Specs cover 20 of 22 benchmarks with 8 legacy alias mappings (e.g., `star_schema` → `ssb`); `ai_primitives` and `vector_search` are not yet covered

## Related

- [Result Integrity Validation](../../development/result-integrity-validation.md) - Architecture and check details
- [Configuration](configuration.md) - Configuration file format and options
- [Platforms](platforms.md) - Platform management commands

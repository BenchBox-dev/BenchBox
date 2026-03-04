# CLI Dry Run Display Specification

## Overview

The CLI Dry Run Display module provides user-facing presentation of benchmark dry run results. It transforms structured dry run data into formatted console output, enabling users to preview benchmark configurations, queries, schemas, and resource estimates before actual execution.

## Purpose

This module serves as the presentation layer for dry run functionality:

- Renders structured dry run results as formatted console output
- Generates equivalent CLI commands from interactive wizard configurations
- Displays preview summaries for interactive benchmark sessions
- Adapts display formatting based on execution mode (SQL vs DataFrame)
- Provides visual feedback for configuration review and verification

## Capabilities

### CLI Command Generation

Generate a complete CLI command string from configuration parameters:

**Inputs**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| platform | string | Yes | Platform identifier (duckdb, snowflake, etc.) |
| benchmark | string | Yes | Benchmark name (tpch, tpcds, etc.) |
| scale | float | Yes | Scale factor for data generation |
| phases | list[string] | No | Execution phases (generate, load, power, etc.) |
| queries | list[string] | No | Query subset to run |
| tuning | string | No | Tuning mode or YAML path |
| seed | integer | No | RNG seed for reproducibility |
| output | string | No | Output directory path |
| table_format | string | No | Table format target (parquet, delta, iceberg) |
| compression | string | No | Compression configuration |
| mode | string | No | Execution mode (sql, dataframe) |
| force | string | No | Force mode (all, datagen, upload) |
| official | boolean | No | TPC-compliant mode flag |
| capture_plans | boolean | No | Query plan capture flag |
| validation | string | No | Validation mode |
| verbose | integer | No | Verbosity level (0-2) |

**Output**: Multi-line CLI command string with line continuation for readability

**Behavior**:
- Omits parameters with default values (scale=0.01, phases=["power"], tuning="notuning")
- Formats command with line continuation backslashes
- Maps verbosity level to CLI flags (-v, -vv)

### Interactive Preview Display

Display configuration summary before benchmark execution in interactive mode:

**Inputs**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| database_config | DatabaseConfig | Yes | Database/platform configuration |
| benchmark_config | BenchmarkConfig | Yes | Benchmark configuration |
| phases | list[string] | Yes | Phases to execute |
| output | string | No | Output directory |
| tuning | string | No | Tuning mode |
| seed | integer | No | RNG seed |
| force | string | No | Force mode |
| official | boolean | No | TPC-compliant mode |
| capture_plans | boolean | No | Plan capture flag |
| validation | string | No | Validation mode |
| verbose | integer | No | Verbosity level |
| console_obj | Console | No | Rich console for output |

**Display Elements**:
- Panel with "Configuration Preview" title
- Table with platform, benchmark, phases, queries, tuning, seed, output, compression settings
- Estimated time range (if available)
- Equivalent CLI command

### Dry Run Results Display

Present complete dry run results to the user:

**Sections**:

1. **Header Panel**: Visual indicator of dry run mode
2. **Configuration Summary**: Structured table showing benchmark, database, system, test execution, and constraint settings
3. **Query Preview**: Sample queries with syntax highlighting (SQL or Python based on execution mode)
4. **Schema Preview**: Database schema (SQL) or DataFrame schema (Python)
5. **Tuning Configuration**: Constraints, table tunings, platform optimizations
6. **Resource Estimates**: Data size, memory usage, runtime, CPU cores
7. **Warnings**: Any issues encountered during dry run

### Test Execution Type Formatting

Format test execution types for display:

| Internal Type | Display Format |
|---------------|----------------|
| standard | Standard (Sequential) |
| power | PowerTest (Stream Permutation) |
| throughput | ThroughputTest (Concurrent Streams) |
| maintenance | MaintenanceTest (Data Operations) |
| combined | Combined Test (All Phases) |
| load_only | Load Only (Data Generation) |
| data_only | Data Only (No Database) |

### Execution Context Messages

Generate context-appropriate descriptions:

| Benchmark | Test Type | Example Context |
|-----------|-----------|-----------------|
| TPC-DS | power | "TPC-DS PowerTest stream permutation (99 queries in randomized order)" |
| TPC-H | power | "TPC-H PowerTest stream 0 permutation (22 queries in a specific, randomized order)" |
| TPC-DS | throughput | "TPC-DS ThroughputTest (4 concurrent streams, N queries total)" |
| TPC-DS | maintenance | "TPC-DS MaintenanceTest (data operations: INSERT/UPDATE/DELETE)" |
| any | standard | "Standard sequential execution (N queries)" |

### Query Display Formatting

Format query identifiers and panel titles based on test type and query structure:

**Query ID Patterns**:
- Maintenance: "Operation {query_id}"
- Stream format (Stream_X_Position_Y_Query_Z): "Stream X Position Y: Query Z"
- Position format (Position_X_Query_Y): "Stream Position X: Query Y"
- Standard: "Query {query_id}"

**Display Limits**:
- Show first 3 queries as preview
- Truncate individual queries at 500 characters
- Indicate remaining query count

## Dependencies

| Component | Purpose |
|-----------|---------|
| Core DryRunExecutor | Inherits base dry run execution logic |
| DryRunResult | Data structure for dry run outputs |
| BenchmarkConfig | Benchmark configuration data |
| DatabaseConfig | Database/platform configuration data |
| Rich library | Console formatting (Panel, Syntax, Table, Text) |
| QuietConsoleProxy | Console output with quiet mode support |

## Configuration

### Console Configuration

The module uses a module-level console instance that supports:
- Quiet mode (suppresses output)
- Rich formatting capabilities
- Injectable console for testing

### Display Limits

| Setting | Value | Purpose |
|---------|-------|---------|
| Query preview count | 3 | Number of queries shown in preview |
| Query truncation | 500 chars | Maximum query length before truncation |
| Schema truncation | 1000 chars | Maximum schema length before truncation |

## Behavior Specification

### Preconditions
- DryRunResult must contain valid benchmark and database configuration dictionaries
- Rich console must be available for output

### Postconditions
- All display sections are rendered to console
- Truncation indicators shown when content is shortened
- Syntax highlighting applied based on execution mode

### Side Effects
- Console output written
- No filesystem modifications
- No state changes

### Error Handling

| Condition | Behavior |
|-----------|----------|
| No queries available | Display "No queries available for preview" message |
| Empty tuning config | Display "No tuning configuration available" message |
| Missing schema | Skip schema preview section |
| Memory usage > 90% available | Display warning message |

## Examples

### CLI Command Generation

```python
from benchbox.cli.dryrun import generate_cli_command

cmd = generate_cli_command(
    platform="snowflake",
    benchmark="tpch",
    scale=1.0,
    phases=["generate", "load", "power"],
    queries=["Q1", "Q6", "Q17"],
    tuning="tuned",
    verbose=1
)
# Output:
# benchbox run \
#     --platform snowflake \
#     --benchmark tpch \
#     --scale 1.0 \
#     --phases generate,load,power \
#     --queries Q1,Q6,Q17 \
#     --tuning tuned \
#     -v
```

### Dry Run Display

```python
from benchbox.cli.dryrun import DryRunDisplay
from benchbox.core.config import DryRunResult

display = DryRunDisplay()
display.display_dry_run_results(result)
# Renders formatted output to console
```

### Interactive Preview

```python
from benchbox.cli.dryrun import display_interactive_preview

display_interactive_preview(
    database_config=db_config,
    benchmark_config=bench_config,
    phases=["power"],
    tuning="tuned"
)
# Shows configuration summary and equivalent CLI command
```

## Notes

- The module extends the core DryRunExecutor to add CLI-specific display functionality
- Display formatting adapts automatically based on execution_mode (sql vs dataframe)
- Syntax highlighting uses "monokai" theme for code blocks
- The DryRunDisplay class and DryRunExecutor class share formatting methods for consistency
- Memory warning threshold is 90% of available memory
- Query previews show only non-error entries (entries starting with "_" are filtered)

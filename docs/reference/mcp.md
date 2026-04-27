<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# MCP Server Reference

```{tags} reference, advanced
```

Complete reference for the BenchBox MCP (Model Context Protocol) server, including all available tools, resources, and prompts.

## Running the Server

### Prerequisites

Install BenchBox with MCP dependencies:

```bash
uv sync --extra mcp
```

### Starting the Server

```bash
# Via Python module
uv run python -m benchbox.mcp

# Via entry point (if installed globally)
benchbox-mcp

# With explicit MCP path overrides
benchbox-mcp --results-dir /tmp/benchbox-results --charts-dir /tmp/benchbox-charts
```

The server communicates via stdio using JSON-RPC, compatible with Claude Code and other MCP clients.

### Testing Locally

To verify the server works, you can test it interactively:

```bash
# Start server and send a test request
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | uv run python -m benchbox.mcp
```

This should return a JSON response listing all available tools.

### Using the MCP Inspector

For interactive testing, use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
# Install the inspector
npx @anthropic-ai/inspector

# Connect to BenchBox
npx @anthropic-ai/inspector "uv run python -m benchbox.mcp"
```

The inspector provides a web UI to browse tools, test calls, and view responses.

### Server Options

`benchbox-mcp` supports explicit flags and environment-variable fallback.

**CLI flags**

| Flag | Description |
|------|-------------|
| `--results-dir` | Results root used by MCP result reads/writes |
| `--charts-dir` | Charts root used by MCP visualization paths |
| `--log-level` | Logging level (DEBUG, INFO, WARNING, ERROR) |

**Environment variables**

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCHBOX_RESULTS_DIR` | `benchmark_runs/results` | Results root when `--results-dir` is not provided |
| `BENCHBOX_CHARTS_DIR` | `benchmark_runs/charts` | Charts root when `--charts-dir` is not provided |
| `BENCHBOX_OUTPUT_DIR` | `benchmark_runs` | Base root used to derive results/charts when specific vars are unset |
| `BENCHBOX_LOG_LEVEL` | `INFO` | Logging level when `--log-level` is not provided |

**Precedence**

1. Explicit MCP flag (`--results-dir`, `--charts-dir`, `--log-level`)
2. Specific env var (`BENCHBOX_RESULTS_DIR`, `BENCHBOX_CHARTS_DIR`, `BENCHBOX_LOG_LEVEL`)
3. Derived from `BENCHBOX_OUTPUT_DIR` for paths
4. Built-in defaults (`benchmark_runs/results`, `benchmark_runs/charts`, `INFO`)

Example:

```bash
BENCHBOX_RESULTS_DIR=/tmp/results BENCHBOX_LOG_LEVEL=DEBUG benchbox-mcp
```

## Tools

Tools are executable actions that can be invoked by AI assistants.

### Discovery Tools

#### `list_platforms`

List all available database platforms.

**Returns:**
- `platforms`: List of platform objects with:
  - `name`: Platform identifier
  - `display_name`: Human-readable name
  - `category`: Platform category (analytical, cloud, embedded, dataframe)
  - `available`: Whether dependencies are installed
  - `supports_sql`: SQL query support
  - `supports_dataframe`: DataFrame API support
- `count`: Total number of platforms
- `summary`: Aggregated statistics

**Example:**
```json
{
  "platforms": [
    {
      "name": "duckdb",
      "display_name": "DuckDB",
      "category": "embedded",
      "available": true,
      "supports_sql": true,
      "supports_dataframe": false
    }
  ],
  "count": 15,
  "summary": {"available": 8, "sql_platforms": 12, "dataframe_platforms": 5}
}
```

---

#### `list_benchmarks`

List all available benchmarks.

**Returns:**
- `benchmarks`: List of benchmark objects with:
  - `name`: Benchmark identifier
  - `display_name`: Human-readable name
  - `query_count`: Number of queries
  - `scale_factors`: Supported scale factors
  - `dataframe_support`: Whether DataFrame mode is supported
- `count`: Total number of benchmarks
- `categories`: Benchmarks grouped by category

---

#### `get_benchmark_info`

Get detailed information about a specific benchmark.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `benchmark` | string | Yes | Benchmark name (e.g., 'tpch', 'tpcds') |

**Returns:**
- `name`: Benchmark identifier
- `queries`: Query information including IDs and count
- `schema`: Table information
- `scale_factors`: Supported scale factors with defaults

---

#### `system_profile`

Get system profile information for capacity planning.

**Returns:**
- `cpu`: Core count, thread count, architecture
- `memory`: Total and available memory in GB
- `disk`: Disk usage for key paths
- `python`: Python version and implementation
- `packages`: Versions of key packages (polars, pandas, duckdb, pyarrow)
- `benchbox`: BenchBox version
- `recommendations`: Suggested maximum scale factor based on resources

---

### Benchmark Tools

#### `run_benchmark`

Run a benchmark on a database platform.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `platform` | string | Yes | - | Target platform (e.g., 'duckdb', 'polars-df') |
| `benchmark` | string | Yes | - | Benchmark name (e.g., 'tpch', 'tpcds') |
| `scale_factor` | float | No | 0.01 | Data scale factor |
| `queries` | string | No | None | Comma-separated query IDs (e.g., "1,3,6") |
| `phases` | string | No | "load,power" | Comma-separated phases |

**Returns:**
- `execution_id`: Unique run identifier
- `status`: "completed", "failed", or "no_results"
- `execution_time_seconds`: Total runtime
- `summary`: Query counts and total runtime
- `queries`: Per-query results (limited to 20)

**Example:**
```json
{
  "execution_id": "mcp_a1b2c3d4",
  "status": "completed",
  "platform": "duckdb",
  "benchmark": "tpch",
  "scale_factor": 0.01,
  "execution_time_seconds": 5.23,
  "summary": {
    "total_queries": 22,
    "successful_queries": 22,
    "failed_queries": 0,
    "total_execution_time": 1.234
  }
}
```

---

#### `dry_run`

Preview what a benchmark run would do without executing.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `platform` | string | Yes | - | Target platform |
| `benchmark` | string | Yes | - | Benchmark name |
| `scale_factor` | float | No | 0.01 | Data scale factor |
| `queries` | string | No | None | Optional query subset |

**Returns:**
- `status`: Always "dry_run"
- `execution_mode`: Execution mode ("sql" or "dataframe")
- `execution_plan`: Phases and queries that would run
  - `phases`: List of phases (e.g., ["load", "power"])
  - `total_queries`: Number of queries to execute
  - `query_ids`: List of query IDs (truncated to 30)
  - `test_execution_type`: Execution type (e.g., "standard")
  - `execution_context`: Context description
- `resource_estimates`: Estimated resource requirements
  - `data_size_gb`: Estimated data size in GB
  - `memory_recommended_gb`: Recommended memory in GB
  - `disk_space_recommended_gb`: Recommended disk space in GB
  - `cpu_cores_available`: Available CPU cores on system
  - `memory_gb_available`: Available memory on system in GB
- `notes`: Important considerations
- `warnings`: Platform availability warnings (if any)

---

#### `validate_config`

Validate a benchmark configuration before running.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `platform` | string | Yes | - | Target platform |
| `benchmark` | string | Yes | - | Benchmark name |
| `scale_factor` | float | No | 1.0 | Data scale factor |

**Returns:**
- `valid`: Boolean indicating if configuration is valid
- `errors`: List of validation errors
- `warnings`: List of warnings
- `recommendations`: Configuration recommendations

---

### Results Tools

#### `list_recent_runs`

List recent benchmark runs.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `limit` | int | No | 10 | Maximum results to return |
| `platform` | string | No | None | Filter by platform |
| `benchmark` | string | No | None | Filter by benchmark |

**Returns:**
- `runs`: List of run metadata
- `count`: Number of runs returned
- `total_available`: Total runs in results directory

---

#### `get_results`

Get detailed results from a benchmark run.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `result_file` | string | Yes | - | Result filename from `list_recent_runs` |
| `include_queries` | bool | No | true | Include per-query details |

**Returns:**
- `platform`: Platform configuration
- `benchmark`: Benchmark name
- `summary`: Execution summary
- `queries`: Per-query timing details

---

#### `compare_results`

Compare two benchmark runs to identify performance changes.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file1` | string | Yes | - | Baseline result file |
| `file2` | string | Yes | - | Comparison result file |
| `threshold_percent` | float | No | 10.0 | Change threshold for highlighting |

**Returns:**
- `baseline`: Baseline run metadata
- `comparison`: Comparison run metadata
- `summary`: Regression/improvement counts
- `regressions`: Query IDs that regressed
- `improvements`: Query IDs that improved
- `query_comparisons`: Per-query delta details

---

#### `export_summary`

Export a formatted summary of benchmark results.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `result_file` | string | Yes | - | Result filename |
| `format` | string | No | "text" | Output format: 'text', 'markdown', or 'json' |

**Returns:**
- `format`: Output format used
- `content`: Formatted summary string

---

#### `export_results`

Export benchmark results to different formats.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `result_file` | string | Yes | - | Result filename |
| `format` | string | No | "json" | Output format: 'json', 'csv', or 'html' |
| `output_path` | string | No | None | File path to write output (relative to results dir) |

**Returns:**
- `status`: "exported"
- `format`: Format used
- `content`: Formatted content (if output_path not specified)
- `output_path`: Path to written file (if output_path specified)
- `size_bytes`: Size of exported content

---

#### `generate_data`

Generate benchmark data without running queries.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `benchmark` | string | Yes | - | Benchmark name (e.g., 'tpch', 'tpcds') |
| `scale_factor` | float | No | 0.01 | Data scale factor |
| `format` | string | No | "parquet" | Data format: 'parquet' or 'csv' |
| `force` | bool | No | false | Force regeneration if data exists |

**Returns:**
- `status`: "generated" or "exists"
- `data_path`: Path to generated data
- `file_count`: Number of files generated
- `total_size_mb`: Total data size in MB

---

#### `check_dependencies`

Check platform dependencies and installation status.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `platform` | string | No | None | Specific platform to check (checks all if not provided) |
| `verbose` | bool | No | false | Include detailed package information |

**Returns:**
- `platforms`: Dictionary of platform status with availability and missing packages
- `summary`: Total, available, and missing dependency counts
- `recommendations`: Installation suggestions
- `quick_status`: Quick status for single platform queries

---

### Analytics Tools

#### `get_query_plan`

Get query execution plan from benchmark results.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `result_file` | string | Yes | - | Result filename containing query plans |
| `query_id` | string | Yes | - | Query identifier (e.g., '1', 'Q1', 'q05') |
| `format` | string | No | "tree" | Output format: 'tree', 'json', or 'summary' |

**Returns:**
- `status`: "success" or "no_plan"
- `query_id`: Requested query ID
- `plan`: Query plan in requested format
- `runtime_ms`: Query runtime

**Note:** Query plans must be captured using `--capture-plans` during benchmark execution.

---

#### `detect_regressions`

Automatically detect performance regressions across recent runs.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `platform` | string | No | None | Filter by platform |
| `benchmark` | string | No | None | Filter by benchmark |
| `threshold_percent` | float | No | 10.0 | Regression threshold percentage |
| `lookback_runs` | int | No | 5 | Number of recent runs to analyze |

**Returns:**
- `comparison`: Baseline and current run metadata
- `summary`: Regression and improvement counts
- `regressions`: List of regressed queries with severity
- `improvements`: List of improved queries
- `recommendations`: Suggested actions

---

#### `validate_results`

Validate integrity, completeness, and believability of benchmark result JSON files. Runs a three-tier validation pipeline (structural, completeness, believability) with 20 checks total.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `result_file` | string | No* | "" | Path to a single result JSON file |
| `directory` | string | No* | "" | Path to a directory of result JSON files (batch mode) |
| `verbose` | bool | No | false | Include PASS checks in output (default: WARN+FAIL only) |

*One of `result_file` or `directory` must be provided.

**Returns (single file):**
- `file`: Result file path
- `benchmark_id`: Benchmark identifier
- `platform`: Platform name
- `scale_factor`: Scale factor
- `overall_status`: "PASS", "WARN", or "FAIL"
- `summary`: Check counts by status
- `checks`: List of check results with category, name, status, message, and details

**Returns (directory):**
- `total`: Number of files validated
- `pass`: Count of files with PASS status
- `warn`: Count of files with WARN status
- `fail`: Count of files with FAIL status
- `files`: List of per-file summaries (file, benchmark_id, platform, overall_status)

**Example:**
```json
{
  "file": "tpch_duckdb_sf1_20260401.json",
  "benchmark_id": "tpch",
  "platform": "DuckDB",
  "scale_factor": 1.0,
  "overall_status": "PASS",
  "summary": {"PASS": 20, "WARN": 0, "FAIL": 0},
  "checks": []
}
```

**Severity levels:**
- **FAIL**: Mathematical impossibility or data corruption (e.g., passed + failed != total)
- **WARN**: Suspicious but plausible (e.g., timing outlier > 30 minutes, missing tables)

---

### Visualization Tools

#### `suggest_charts`

Analyze results and suggest appropriate chart types.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `result_files` | string | Yes | Comma-separated list of result filenames |

**Returns:**
- `suggestions`: List of chart recommendations with priority and reasoning
- `primary`: Best chart type recommendation with reason
- `data_profile`: Analysis of result data (result_count, platforms, has_cost_data, etc.)
- `source_files`: Input files used

---

#### `generate_chart`

Generate charts from benchmark results.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `result_files` | string | Yes | - | Comma-separated list of result filenames |
| `chart_type` | string | No | "performance_bar" | Chart type: performance_bar, power_bar, distribution_box, query_heatmap, query_histogram, cost_scatter, time_series, comparison_bar, diverging_bar, summary_box, percentile_ladder, normalized_speedup, stacked_phase, sparkline_table, cdf_chart, rank_table |
| `template` | string | No | None | Template: default, flagship, head_to_head, trends, cost_optimization, comparison, latency_deep_dive, regression_triage, executive_summary |
| `output_dir` | string | No | None | Output directory (relative to charts dir) |
| `format` | string | No | "ascii" | Output format: 'ascii' for terminal-friendly text output |

**Returns:**
- `status`: "generated"
- `chart_type`: Generated chart type (or `template` if using template)
- `format`: "ascii"
- `content`: ASCII chart rendered inline
- `source_files`: Input files used
- `note`: Usage instructions

**Examples:**

```bash
# Single chart
generate_chart(result_files="run1.json", chart_type="performance_bar")

# Template (multiple charts combined with separators)
generate_chart(result_files="run1.json,run2.json", template="head_to_head")

# Platform comparison
generate_chart(result_files="duckdb.json,polars.json", chart_type="query_heatmap")
```

**Output Features:**
- ANSI colors for terminal display (copy-paste preserves formatting)
- Unicode box-drawing characters for clean visualization
- Best/worst highlighting, legends, and scale indicators
- Template output combines multiple charts with `────────` separators

---

### Historical Analysis Tools

#### `get_performance_trends`

Get performance trends over multiple benchmark runs.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `platform` | string | No | None | Filter by platform |
| `benchmark` | string | No | None | Filter by benchmark |
| `metric` | string | No | "geometric_mean" | Performance metric: 'geometric_mean', 'p50', 'p95', 'p99', 'total_time' |
| `limit` | int | No | 10 | Maximum runs to analyze |

**Returns:**
- `metric`: Metric used
- `summary`: Run count, first/last run timestamps, trend direction
- `data_points`: Time-series performance data

---

#### `aggregate_results`

Aggregate multiple benchmark results into summary statistics.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `platform` | string | No | None | Filter by platform |
| `benchmark` | string | No | None | Filter by benchmark |
| `group_by` | string | No | "platform" | Grouping dimension: 'platform', 'benchmark', or 'date' |

**Returns:**
- `group_by`: Grouping used
- `summary`: Total groups and runs
- `aggregates`: Statistical summaries per group (mean, std, min, max, percentiles)

---

## Prompts

Prompts are reusable templates for AI analysis. Invoke via slash commands in Claude Code.

### `analyze_results`

Analyze benchmark results and identify performance patterns.

**Arguments (positional):**
1. `benchmark` (default: "tpch")
2. `platform` (default: "duckdb")
3. `focus` (optional): Focus area like 'slowest_queries', 'memory', 'io'

**Usage:**
```
/mcp__benchbox__analyze_results tpch duckdb slowest_queries
```

---

### `compare_platforms`

Compare benchmark performance across multiple platforms.

**Arguments (positional):**
1. `benchmark` (default: "tpch")
2. `platforms` (default: "duckdb,polars-df"): Comma-separated platform names
3. `scale_factor` (default: 0.01)

**Usage:**
```
/mcp__benchbox__compare_platforms tpch "duckdb,polars-df,sqlite" 0.1
```

---

### `identify_regressions`

Identify performance regressions between benchmark runs.

**Arguments (positional):**
1. `baseline_run` (optional): Baseline result file
2. `comparison_run` (optional): Comparison result file
3. `threshold_percent` (default: 10.0)

**Usage:**
```
/mcp__benchbox__identify_regressions run1.json run2.json 5
```

---

### `benchmark_planning`

Help plan a benchmark strategy for a specific use case.

**Arguments (positional):**
1. `use_case` (default: "testing"): One of 'testing', 'production', 'comparison', 'regression'
2. `platforms` (optional): Comma-separated platform list
3. `time_budget_minutes` (default: 30)

**Usage:**
```
/mcp__benchbox__benchmark_planning comparison "duckdb,snowflake" 60
```

---

### `troubleshoot_failure`

Diagnose and resolve benchmark failures.

**Arguments (positional):**
1. `error_message` (optional): Error message from failed run
2. `platform` (optional): Platform where failure occurred
3. `benchmark` (optional): Benchmark that failed

**Usage:**
```
/mcp__benchbox__troubleshoot_failure "Connection refused" snowflake tpch
```

---

### `benchmark_run`

Execute a planned benchmark with validation and dependency checks.

**Arguments (positional):**
1. `platform` (default: "duckdb"): Target platform
2. `benchmark` (default: "tpch"): Benchmark to run
3. `scale_factor` (default: 0.01): Data scale factor
4. `queries` (optional): Query subset (e.g., "1,5,10")

**Usage:**
```
/mcp__benchbox__benchmark_run duckdb tpch 0.1
/mcp__benchbox__benchmark_run snowflake tpcds 1 "1,5,10"
```

This prompt:
1. Validates the configuration
2. Checks dependencies
3. Runs the benchmark
4. Provides execution summary and recommendations

---

### `platform_tuning`

Get tuning recommendations for a specific platform.

**Arguments (positional):**
1. `platform` (default: "duckdb"): Platform to tune
2. `workload` (optional): Workload characteristics description

**Usage:**
```
/mcp__benchbox__platform_tuning duckdb
/mcp__benchbox__platform_tuning snowflake "heavy aggregation workload"
```

This prompt provides:
1. Memory configuration recommendations
2. Parallelism settings
3. I/O optimization
4. Platform-specific tuning parameters

---

## Resources

Resources provide read-only access to BenchBox data. Currently, resources are accessed indirectly through tools.

## Error Handling

All tools return structured error information:

```json
{
  "error": "Description of the error",
  "error_type": "ExceptionClassName",
  "suggestion": "How to resolve the issue"
}
```

Common error types:
- **ConfigurationError**: Invalid platform or benchmark configuration
- **DependencyError**: Missing required dependencies
- **FileNotFoundError**: Result file not found

## Related Documentation

- [MCP Integration Guide](../guides/mcp-integration.md) - Setup and usage guide
- [CLI Reference](cli/index.md) - Command-line interface
- [API Reference](api-reference.md) - Python API

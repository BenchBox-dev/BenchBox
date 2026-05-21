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

Tools are executable actions that can be invoked by AI assistants. BenchBox MCP
is a **beta-public smoke/control-plane surface**, not a CLI-equivalent
execution surface. It exposes a documented subset of benchmark execution,
validation, dry-run preview, result reads, analytics, and chart generation
through public BenchBox APIs. MCP must not import `benchbox.cli` command
internals.

MCP run results are exported through `ResultExporter` as normal result JSON
bundles and include `execution_context.entry_point = "mcp"` when the result
object supports execution context metadata. They are schema-level comparable to
CLI result bundles, but MCP does not claim option parity with `benchbox run`.

### Actual Tool Inventory

| Tool | Category | Writes | Purpose |
|---|---|---:|---|
| `list_available` | discovery | No | List platforms, benchmarks, chart templates, or all discovery data. |
| `get_benchmark_info` | discovery | No | Return benchmark metadata, queries, schema, and scale-factor information. |
| `system_profile` | discovery | No | Return CPU, memory, disk, Python, package, and BenchBox environment facts. |
| `check_dependencies` | discovery | No | Report platform dependency availability and install guidance. |
| `run_benchmark` | execution | Yes | Run, dry-run, or validate a benchmark through the MCP control-plane subset. |
| `get_query_details` | execution aid | No | Return SQL or DataFrame query details for a benchmark/query/platform. |
| `get_results` | results | Optional | List result files, read one result, or export a result in another format. |
| `analyze_results` | analytics | No | Compare result files, detect regressions, calculate trends, or aggregate runs. |
| `get_query_plan` | analytics | No | Read captured query plans from a result bundle. |
| `validate_results` | analytics | No | Validate result JSON integrity, completeness, and believability. |
| `suggest_charts` | visualization | No | Suggest useful chart types for one or more result files. |
| `generate_chart` | visualization | Yes | Generate ASCII chart output from result files. |

### Run Surface Contract

`run_benchmark` is the only benchmark execution tool. Dry-run preview and
configuration validation are modes on this tool (`dry_run=true` and
`validate_only=true`), not separate MCP tools.

**MCP run parameter schema**

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `platform` | string | Yes | - | Target platform, for example `duckdb`, `snowflake`, or `polars-df`. |
| `benchmark` | string | Yes | - | Benchmark identifier, for example `tpch`, `tpcds`, or `joinorder`. |
| `scale_factor` | number | No | `0.01` | Data scale factor; benchmark-specific defaults and constraints may still apply. |
| `queries` | string or null | No | `null` | Comma-separated query IDs, for example `1,3,6`. |
| `phases` | string or null | No | `null` | Comma-separated phases; execution defaults to `load,power` when omitted. |
| `mode` | string or null | No | `null` | Execution mode: `sql`, `dataframe`, or `data_only`. |
| `capture_plans` | boolean | No | `false` | Capture query plans where the selected platform supports them. |
| `dry_run` | boolean | No | `false` | Preview the run plan without executing queries. |
| `validate_only` | boolean | No | `false` | Validate platform, benchmark, scale, and mode without executing. |

**Behavior**

- `validate_only=true` returns configuration validity, resolved execution mode,
  errors, and warnings.
- `dry_run=true` uses the core dry-run executor and returns the plan/resources
  preview the MCP subset can model; it currently reports the default
  load/power plan rather than applying the `phases` parameter.
- `mode=data_only` generates benchmark data without running queries.
- `phases` applies to normal execution and maps to the benchmark execution type
  used by `BaseBenchmark.run_with_platform()`.
- Normal execution uses `BaseBenchmark.run_with_platform()` through public
  benchmark and adapter APIs.
- MCP execution intentionally suppresses console output and returns structured
  JSON for agent clients.

**Intentionally omitted CLI-only controls**

These `benchbox run` options are currently product-scope omissions, not
undocumented MCP parameters. Adding any of them requires a new contract decision
or a shared non-CLI execution service below both CLI and MCP.

| CLI surface | MCP status | Reason |
|---|---|---|
| `--output` | Omitted | MCP result roots are server configuration (`--results-dir`, env vars). |
| `--platform-option` | Omitted | Platform-specific key/value plumbing is CLI orchestration surface. |
| `--benchmark-option` | Omitted | Benchmark-specific key/value plumbing is CLI orchestration surface. |
| `--tuning`, `--table-mode`, `--sorted-ingestion-*` | Omitted | Tuning/table layout workflows are CLI-equivalent scope. |
| `--force` | Omitted | Regeneration/upload forcing needs broader lifecycle service semantics. |
| `--official`, `--seed`, `--iterations` | Omitted | TPC compliance and repeated measurement policy remain CLI scope. |
| `--compression`, `--table-format`, `--presort` | Omitted | Output/data-format policy is not exposed through MCP run control. |
| `--validation`, `--plan-config` | Omitted | MCP exposes only `validate_only` and `capture_plans` booleans. |
| `--no-monitoring`, `--no-progress`, `--quiet`, `--verbose` | Omitted | MCP already runs as structured, quiet server-side execution. |
| `--global-cache`, `--publish`, `--publish-target`, `--publish-label` | Omitted | Cache and publication workflows are not MCP run controls. |
| interactive prompts and `--non-interactive` | Omitted | MCP requests are non-interactive by protocol. |

### Discovery Tools

#### `list_available`

List platforms, benchmarks, chart templates, or all discovery data.
Benchmark rows include `support_status` from
`benchbox.core.benchmark_registry`; MCP does not maintain a separate support
classification.

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `category` | string | No | `all` | `platforms`, `benchmarks`, `charts`, or `all`. |

#### `get_benchmark_info`

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `benchmark` | string | Yes | - | Benchmark identifier. |

Returns benchmark metadata including `support_status`, category, query/schema
information, scale-factor constraints, and DataFrame capability.

#### `system_profile`

No parameters. Returns host and package information useful for capacity
planning.

#### `check_dependencies`

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `platform` | string or null | No | `null` | Specific platform to check; omitted checks all platforms. |
| `verbose` | boolean | No | `false` | Include detailed package information. |

### Benchmark Query Tools

#### `get_query_details`

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `benchmark` | string | Yes | - | Benchmark identifier. |
| `query_id` | string | Yes | - | Query identifier, for example `1`, `Q1`, or `17`. |
| `platform` | string or null | No | `null` | Optional platform for dialect-specific query lookup. |
| `mode` | string or null | No | `null` | `sql` or `dataframe`; inferred from platform when omitted. |

### Results Tools

#### `get_results`

`get_results` combines recent-run listing, result reading, and result export.

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `result_file` | string or null | No | `null` | Result filename; omitted lists recent runs. |
| `format` | string | No | `details` | `list`, `details`, `json`, `csv`, `html`, `text`, or `markdown`. |
| `output_path` | string or null | No | `null` | Export path relative to the configured results dir. |
| `limit` | integer | No | `10` | Max recent runs when listing. |
| `platform` | string or null | No | `null` | Platform filter when listing. |
| `benchmark` | string or null | No | `null` | Benchmark filter when listing. |
| `include_queries` | boolean | No | `true` | Include query details when reading one result. |

### Analytics Tools

#### `analyze_results`

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `analysis` | string | No | `compare` | `compare`, `regressions`, `trends`, or `aggregate`. |
| `file1` | string or null | No | `null` | Baseline result file for `compare`. |
| `file2` | string or null | No | `null` | Comparison result file for `compare`. |
| `platform` | string or null | No | `null` | Platform filter for non-compare analyses. |
| `benchmark` | string or null | No | `null` | Benchmark filter for non-compare analyses. |
| `threshold_percent` | number | No | `10.0` | Regression/change threshold. |
| `metric` | string | No | `geometric_mean` | Trend metric: `geometric_mean`, `p50`, `p95`, `p99`, or `total_time`. |
| `group_by` | string | No | `platform` | Aggregate grouping: `platform`, `benchmark`, or `date`. |
| `limit` | integer | No | `10` | Max runs to analyze where applicable. |

#### `get_query_plan`

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `result_file` | string | Yes | - | Result filename containing captured query plans. |
| `query_id` | string | Yes | - | Query identifier. |
| `format` | string | No | `tree` | `tree`, `json`, or `summary`. |

#### `validate_results`

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `result_file` | string | No* | `""` | Path to one result JSON file. |
| `directory` | string | No* | `""` | Directory of result JSON files for batch validation. |
| `verbose` | boolean | No | `false` | Include PASS checks in output. |

*Provide either `result_file` or `directory`.

### Visualization Tools

#### `suggest_charts`

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `result_files` | string | Yes | - | Comma-separated result filenames. |

#### `generate_chart`

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `result_files` | string | Yes | - | Comma-separated result filenames. |
| `chart_type` | string | No | `performance_bar` | Chart type for single-chart output. |
| `template` | string or null | No | `null` | Template name for multi-chart output. |
| `output_dir` | string or null | No | `null` | Output directory relative to charts dir. |
| `format` | string | No | `ascii` | Output format; current MCP output is ASCII. |

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

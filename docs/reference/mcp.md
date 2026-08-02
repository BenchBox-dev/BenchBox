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

# Opt in to localhost Streamable HTTP
benchbox-mcp --transport streamable-http
```

The default server communicates via stdio using JSON-RPC, compatible with
Claude Code and other local MCP clients. Streamable HTTP is an explicit
localhost-only option at `http://127.0.0.1:8000/mcp`.

```json
{
  "mcpServers": {
    "benchbox": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Do not expose the unauthenticated localhost endpoint through a public bind,
port forward, or reverse proxy. Non-loopback binding requires a complete
`--security-config` policy. See [Remote MCP security and tenancy](../operations/mcp-remote-security.md)
for its threat model, token-digest provisioning, scopes, tenant workspaces,
shared admission store, and fail-closed proxy requirements. This capability is
not a production-readiness claim; keep shared endpoint publication disabled
until the [production-readiness gate](../operations/mcp-production-readiness.md)
has current evidence for the deployed revision.

### SDK Compatibility

BenchBox uses the Python MCP SDK 2.x `MCPServer` API and reports its own
`benchbox` server name and BenchBox package version during initialization.
The v2 migration preserves the public stdio contract: 12 tools, 4 static
resources, 2 resource templates, and 7 prompts. Tool names, input schemas,
annotations, resource URIs, prompt schemas, and handler behavior are unchanged;
only Python-side SDK model attributes use the v2 snake-case names.

An authenticated remote server adds four durable job tools. They use shared
storage and return immediately, so sessionless requests may reach different
workers without losing ownership or lifecycle state.

Streamable HTTP supports modern MCP `2026-07-28` as a sessionless protocol.
The only production-supported legacy handshake is `2025-11-25`; earlier
revisions are not covered by the acceptance matrix:
each request can reach any server process and no `Mcp-Session-Id` is issued.
The same endpoint retains the SDK's stateless compatibility path for supported
handshake-era clients. Protocol discovery, version negotiation, headers, and
DNS-rebinding checks are provided by the MCP SDK rather than reimplemented by
BenchBox. Responses remain streaming-capable; JSON-only mode is intentionally
disabled so progress and future request-scoped notifications remain possible.

### Testing Locally

To verify the server works, you can test it interactively:

```bash
# Start server and send a test request
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | uv run python -m benchbox.mcp
```

This should return a JSON response listing all available tools.

### Using the MCP Inspector

For interactive testing, use the pinned official
[MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
# Connect to an already-running localhost Streamable HTTP endpoint
npx --yes @modelcontextprotocol/inspector@2.0.0 --cli \
  http://127.0.0.1:8000/mcp --transport http --method tools/list --format json
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
| `--transport` | `stdio` (default) or opt-in `streamable-http` |
| `--host` | Streamable HTTP bind host; non-loopback requires `--security-config` (default `127.0.0.1`) |
| `--port` | Streamable HTTP bind port (default `8000`) |
| `--streamable-http-path` | Streamable HTTP endpoint path (default `/mcp`) |
| `--security-config` | Remote-only JSON policy for SDK auth, tenancy, authorization, admission, and audit |
| `--readiness-evidence` | Revision-bound evidence required for every non-loopback bind |

**Environment variables**

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCHBOX_RESULTS_DIR` | `benchmark_runs/results` | Results root when `--results-dir` is not provided |
| `BENCHBOX_CHARTS_DIR` | `benchmark_runs/charts` | Charts root when `--charts-dir` is not provided |
| `BENCHBOX_OUTPUT_DIR` | `benchmark_runs` | Base root used to derive results/charts when specific vars are unset |
| `BENCHBOX_LOG_LEVEL` | `INFO` | Logging level when `--log-level` is not provided |
| `BENCHBOX_BUILD_SHA` | none | Exact deployed revision matched by remote readiness evidence |
| `BENCHBOX_MCP_READINESS_SHA256` | none | Out-of-band digest of the readiness evidence file |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | none | Shared OTLP/HTTP trace endpoint required for remote publication |

Discovery and list responses carry a public five-minute cache hint. Resource
bodies, including recent results and system profiles, are always private and
immediately stale. BenchBox exports only bounded allow-listed MCP span fields;
tool arguments, result payloads, identities, authorization data, credentials,
and raw database URLs are excluded.

**Precedence**

1. Explicit MCP flag (`--results-dir`, `--charts-dir`, `--log-level`)
2. Specific env var (`BENCHBOX_RESULTS_DIR`, `BENCHBOX_CHARTS_DIR`, `BENCHBOX_LOG_LEVEL`)
3. Derived from `BENCHBOX_OUTPUT_DIR` for paths
4. Built-in defaults (`benchmark_runs/results`, `benchmark_runs/charts`, `INFO`)

Example:

```bash
BENCHBOX_RESULTS_DIR=/tmp/results BENCHBOX_LOG_LEVEL=DEBUG benchbox-mcp
```

Additional localhost examples:

```bash
# IPv4 loopback with a custom port and path
benchbox-mcp --transport streamable-http --port 8765 --streamable-http-path /benchbox-mcp

# IPv6 loopback
benchbox-mcp --transport streamable-http --host ::1
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

Authenticated remote mode additionally registers:

| Tool | Category | Writes | Purpose |
|---|---|---:|---|
| `start_benchmark` | durable execution | Yes | Queue a tenant-owned benchmark and return an `execution_id`. |
| `get_benchmark_status` | durable execution | No | Read owned job state, attempts, cancellation, and timestamps. |
| `get_benchmark_result` | durable execution | No | Read the owned result after atomic publication. |
| `cancel_benchmark` | durable execution | Yes | Cancel queued work or request cancellation at the next safe worker boundary. |

### Run Surface Contract

`run_benchmark` remains the synchronous local-compatible execution tool.
Dry-run preview and configuration validation are modes on it (`dry_run=true`
and `validate_only=true`), not separate MCP tools. Authenticated remote clients
should use `start_benchmark` for a normal long-running execution; the durable
tool accepts the same normal-run fields plus an optional `idempotency_key`, but
does not expose `dry_run` or `validate_only`. In remote mode, a normal
`run_benchmark` call is rejected immediately; its `dry_run` and `validate_only`
modes remain available because they do not hold the request for execution.

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
| `platform_options` | object or null | No | `null` | Typed, bounded, non-secret settings approved for the selected platform; credentials, endpoints, paths, and package-install controls are rejected. |

**Behavior**

- `validate_only=true` returns configuration validity, resolved execution mode,
  errors, and warnings.
- `dry_run=true` uses the core dry-run executor and returns the plan/resources
  preview the MCP subset can model; it currently reports the default
  load/power plan rather than applying the `phases` parameter.
- `mode=data_only` generates benchmark data without running queries.
- `phases` applies to normal execution and maps to the benchmark execution type
  used by `BaseBenchmark.run_with_platform()`.
- `platform_options` is normalized and validated before any adapter is built.
  The allow-list is intentionally narrower than the CLI's
  `--platform-option` surface: only bounded execution settings such as
  DuckDB `memory_limit`/`threads`, DataFusion partition settings, and selected
  DataFrame toggles are accepted. Unknown keys, credentials, DSNs, hosts,
  filesystem paths, unbounded values, and driver auto-install/version controls
  fail closed. Authenticated durable jobs persist only this normalized object,
  so retries and worker restarts cannot reintroduce raw request mappings.
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
| `--platform-option` | Narrow MCP subset | MCP accepts only its typed, non-secret allow-list; the full CLI key/value surface remains CLI-only. |
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

Public benchmark query details include registry `support_status` in
`benchmark_info`. Internal/repo-only benchmark details remain addressable by
explicit ID where previously supported, but do not expose support-status claims.
See the [Benchmark Visibility Policy](public-contracts.md#benchmark-visibility-policy)
for the full surface-by-surface matrix.

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

BenchBox MCP visualization is result-aware semantic charting. `suggest_charts`
and `generate_chart` read BenchBox result files and accept semantic chart IDs
from `benchbox.core.visualization.chart_types`, such as `performance_bar`,
`power_bar`, and `query_heatmap`. These IDs are distinct from raw
`textcharts_*` primitive MCP tools. BenchBox does not register or proxy the
external `textcharts-mcp` server; if a client configures that server separately,
its tools remain a separate raw rendering namespace.

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

Available `chart_type` values and template names are derived from the
visualization registries and are discoverable with `list_available(category="charts")`.

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

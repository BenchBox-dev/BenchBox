<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Result Export Formats

```{tags} reference, validation
```

BenchBox exports benchmark results in multiple formats for analysis, visualization, and integration with external tools.

## Export Commands

### Basic Export

```bash
# Run benchmark and export results
benchbox run --platform duckdb --benchmark tpch --scale 0.1

# Results are automatically saved to benchmark_runs/results/
ls benchmark_runs/results/
# tpch_duckdb_sf0.01_20251212_143021.json
```

### Export to Other Formats

```bash
# Export most recent result to CSV
benchbox export --last --format csv

# Export to multiple formats
benchbox export --last --format csv --format html

# Export a specific result file
benchbox export benchmark_runs/results/tpch_duckdb_sf0.01_20251212_143021.json --format csv --format html
```

### Custom Output Directory

```bash
# Local directory
benchbox run --platform duckdb --benchmark tpch --output ./my_results/

# Cloud storage
benchbox run --platform snowflake --benchmark tpch --output s3://bucket/results/
```

## JSON Format (Schema v2.1)

The JSON export is the canonical schema-v2 result bundle containing complete
benchmark details. BenchBox currently writes schema version `"2.1"` in the
top-level `version` field.

Consumer policy is intentionally split by use case:

| Consumer | Accepted versions | Behavior |
|---|---|---|
| Producer/exporter | `"2.1"` | New bundles are written with the current producer version. |
| Runtime loader and exporter listing | `"2.0"`, `"2.1"` | Unknown versions fail closed and should be re-exported. |
| Normalizer | `"2.0"`, `"2.1"` as v2; other shapes as legacy | Known v2 bundles use exact v2 field mapping; v1.x and unknown shapes use legacy best-effort extraction. |
| Public submission validator | Numeric `2.x` | Forward-compatible for schema-v2 minor versions, but missing or malformed versions are rejected. |
| Explorer pipeline input | `"2.0"`, `"2.1"` | Unsupported bundles are rejected before explorer read-model projection. |

### Schema Structure

```json
{
  "version": "2.1",
  "run": {
    "id": "tpch-duckdb-20260521",
    "timestamp": "2026-05-21T14:30:21.123456Z",
    "total_duration_ms": 45230,
    "query_time_ms": 39800
  },
  "benchmark": {
    "id": "tpch",
    "name": "TPC-H",
    "scale_factor": 0.1
  },
  "platform": {
    "name": "duckdb",
    "version": "1.2.0"
  },
  "config": {
    "execution_mode": "sql"
  },
  "summary": {
    "queries": {
      "total": 22,
      "passed": 22,
      "failed": 0
    },
    "timing": {
      "total_ms": 39800,
      "avg_ms": 1809.1
    },
    "validation": "passed",
    "tpc_metrics": {
      "power_at_size": 89.5
    }
  },
  "phases": {
    "data_generation": { "...": "..." },
    "schema_creation": { "...": "..." },
    "data_loading": { "...": "..." },
    "power_test": { "...": "..." }
  },
  "queries": [
    {
      "id": "Q1",
      "ms": 1520,
      "rows": 4,
      "iter": 1,
      "stream": 0,
      "run_type": "measurement",
      "status": "SUCCESS"
    }
  ],
  "environment": {
    "os": "macOS",
    "arch": "arm64"
  }
}
```

### Field Reference

#### Version
| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Result bundle schema version. Current producer version is `"2.1"`. |

#### Benchmark Block
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Benchmark identifier (tpch, tpcds, ssb, etc.) |
| `name` | string | Display name |
| `scale_factor` | float | Data scale factor |
| `test_type` | string | Optional run/test classification |

#### Platform Block
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Platform identifier |
| `version` | string | Platform/driver version |
| `deployment` | object | Optional normalized deployment metadata |
| `cloud`, `compute`, `storage` | object | Optional normalized environment facets |

#### Run Block
| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | Run start time (ISO 8601) |
| `id` | string | Run identifier |
| `total_duration_ms` | number | Total benchmark duration |
| `query_time_ms` | number | Total query execution duration |

#### Phases Block

Phases are keyed by lifecycle stage. Each phase block may carry status,
duration, counts, and stage-specific metadata.

```json
{
  "data_generation": {
    "duration_ms": 5230,
    "status": "SUCCESS",
    "tables_generated": 8,
    "total_rows_generated": 150000
  },
  "schema_creation": {
    "duration_ms": 120,
    "status": "SUCCESS",
    "tables_created": 8
  },
  "data_loading": {
    "duration_ms": 3500,
    "status": "SUCCESS",
    "tables_loaded": 8
  },
  "power_test": {
    "duration_ms": 39800,
    "status": "SUCCESS"
  }
}
```

#### Summary Block
| Field | Type | Description |
|-------|------|-------------|
| `queries.total` | int | Total query records represented in the bundle |
| `queries.passed` | int | Count of passed queries |
| `queries.failed` | int | Count of failed queries |
| `timing.total_ms` | number | Total query execution time in milliseconds |
| `timing.avg_ms` | number | Average query execution time in milliseconds |
| `validation` | string or object | Validation result summary |
| `tpc_metrics` | object | Optional TPC-style metrics such as `power_at_size` |

### Query Execution Details

Each query execution record contains:

```json
{
  "id": "Q6",
  "ms": 234,
  "rows": 1,
  "iter": 1,
  "stream": 0,
  "run_type": "measurement",
  "status": "SUCCESS"
}
```

## CSV Format

CSV export provides tabular query-level data for spreadsheet analysis.

### Query Results CSV

```csv
id,ms,rows,iter,stream,run_type,status
Q1,1520,4,1,0,measurement,SUCCESS
Q2,892,460,1,0,measurement,SUCCESS
Q3,1230,10,1,0,measurement,SUCCESS
...
```

### Summary CSV

```csv
metric,value
benchmark,tpch
scale_factor,0.1
platform,duckdb
total_time_ms,39800
avg_time_ms,1809.1
power_at_size,89.5
total_duration_ms,45230
```

## HTML Format

HTML export generates a standalone report with formatted tables.

```bash
# Generate HTML report from most recent result
benchbox export --last --format html

# Export a specific result file to HTML
benchbox export benchmark_runs/results/tpch_duckdb_sf0.01_20251212_143021.json --format html
```

The HTML report includes:
- Summary metrics card
- Query results table with timing data
- Phase duration breakdown
- Validation status table
- Platform and configuration details

## Visualizing Results

Use `benchbox visualize` to generate ASCII charts from any result file:

```bash
# Auto-detect latest result and render all applicable charts
benchbox visualize

# Visualize a specific result file
benchbox visualize benchmark_runs/results/tpch_duckdb_sf0.01_20251212_143021.json

# Specific chart type
benchbox visualize benchmark_runs/results/*.json --chart-type performance_bar

# Save plain-text output to file
benchbox visualize benchmark_runs/results/*.json --no-color > charts.txt
```

See the [Visualization Guide](../visualization/overview.md) for chart types, templates, and customization options.

## Loading Results in Python

### Load JSON Results

```python
import json
from pathlib import Path

# Load result file
result_file = Path("benchmark_runs/results/tpch_duckdb_sf0.01_20251212_143021.json")
with result_file.open() as f:
    results = json.load(f)

# Access metrics
print(f"Power at Size: {results['summary']['tpc_metrics']['power_at_size']}")
print(f"Total time: {results['summary']['timing']['total_ms']}ms")

# Access query details
for query in results['queries']:
    print(f"{query['id']}: {query['ms']}ms")
```

### Load into Pandas

```python
import pandas as pd
import json

# Load JSON
with open("benchmark_runs/results/tpch_duckdb_sf0.01_*.json") as f:
    results = json.load(f)

# Convert queries to DataFrame
queries = results['queries']
df = pd.DataFrame(queries)

# Analyze
print(df.describe())
print(df.groupby('id')['ms'].mean())
```

### Load CSV Results

```python
import pandas as pd

# Load query results
df = pd.read_csv("benchmark_runs/results/tpch_duckdb_sf0.01_queries.csv")

# Quick analysis
print(f"Total queries: {len(df)}")
print(f"Mean execution time: {df['ms'].mean():.2f}ms")
print(f"Slowest query: {df.loc[df['ms'].idxmax(), 'id']}")
```

## Visualization Examples

### CLI Visualization

```bash
# Render all applicable charts for a result file
benchbox visualize benchmark_runs/results/tpch_duckdb_sf0.01_*.json

# Compare multiple platforms
benchbox visualize duckdb_result.json sqlite_result.json --template head_to_head

# Per-query histogram (auto-splits for large benchmarks)
benchbox visualize tpcds_result.json --chart-type query_histogram
```

### Python API Visualization

```python
from benchbox.core.visualization import ResultPlotter
from benchbox.core.visualization.ascii import ASCIIBarChart
from benchbox.core.visualization.ascii.bar_chart import BarData

# Load results from JSON files
plotter = ResultPlotter.from_sources(["results/duckdb.json", "results/sqlite.json"])

# Render a bar chart
bar_data = [BarData(label=r.platform, value=r.total_time_ms or 0) for r in plotter.results]
chart = ASCIIBarChart(data=bar_data, title="Platform Comparison")
print(chart.render())

# Export to plain-text file
from benchbox.core.visualization.exporters import export_ascii

export_ascii(
    ascii_content=chart.render(),
    output_dir="./charts",
    base_name="platform_comparison",
    format="txt",
)
```

## Schema Versioning

### Current Version: 2.1

Schema v2.1 is the current producer version for BenchBox result bundles. It
uses top-level `version`, `run`, `benchmark`, `platform`, `summary`, `queries`,
and optional companion blocks such as `phases`, `environment`,
`normalized_cost`, `validation`, and `comparisons`.

Runtime loading and explorer generation intentionally accept only known v2
minor versions (`"2.0"` and `"2.1"`). The public submission validator accepts
numeric `2.x` versions to allow forward-compatible submissions, but it rejects
missing values and malformed strings such as `"2.x"`. Legacy v1.x result shapes
are not runtime-loadable; they are handled only by the normalizer's best-effort
compatibility path.

### Version History

| Version | Changes |
|---------|---------|
| 2.1 | Current producer schema for result bundles |
| 2.0 | First schema-v2 bundle contract consumed by loader, submissions, and explorer |
| 1.x | Legacy shape supported only by normalization helpers |

### Loading Legacy Results

```python
import json

from benchbox.core.results.normalizer import normalize_result_dict

with open("old_result.json") as f:
    result = normalize_result_dict(json.load(f))
print(f"Schema version family: {result.schema_version}")
```

## Anonymization

Results are anonymized by default to remove sensitive information:

- Connection strings → hashed
- Hostnames → generalized
- Usernames → removed
- API keys/tokens → stripped

### Disable Anonymization

Anonymization can be configured programmatically via the Python API:

### Anonymization Config

```python
from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.anonymization import AnonymizationConfig

config = AnonymizationConfig(
    anonymize_hostname=True,
    anonymize_username=True,
    anonymize_connection_string=True,
    preserve_platform_version=True
)

exporter = ResultExporter(anonymize=True, anonymization_config=config)
```

## Integration Examples

### Export to Data Warehouse

```python
import json
import pandas as pd

# Load results
with open("results.json") as f:
    results = json.load(f)

# Flatten to table
queries = []
for q in results['queries']:
    queries.append({
        'run_id': results['run']['id'],
        'benchmark': results['benchmark']['id'],
        'platform': results['platform']['name'],
        'scale_factor': results['benchmark']['scale_factor'],
        **q
    })

df = pd.DataFrame(queries)

# Upload to warehouse
# df.to_sql('benchmark_queries', engine, if_exists='append')
```

### CI/CD Integration

```bash
# Run benchmark and check threshold
benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
  --output ./results/

# Parse results in CI script
uv run -- python -c "
import json
import sys

with open('results/tpch_duckdb_sf0.01_*.json') as f:
    results = json.load(f)

power = results['summary']['tpc_metrics']['power_at_size']
if power < 50:  # Performance threshold
    print(f'FAIL: Power@Size {power} below threshold 50')
    sys.exit(1)
print(f'PASS: Power@Size {power}')
"
```

## Related Documentation

- [Getting Started](../usage/getting-started.md)
- [Python API](python-api/results.md)
- [Understanding Results](../tutorials/understanding-results.md)

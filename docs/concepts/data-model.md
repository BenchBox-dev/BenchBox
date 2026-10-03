<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Data Model

```{tags} concept, intermediate, validation
```

Understanding BenchBox's result schema, data structures, and serialization formats.

## Overview

BenchBox produces structured, machine-readable results that enable:
- **Reproducibility**: Complete execution metadata for result verification
- **Comparison**: Standardized format for cross-platform and temporal analysis
- **Integration**: JSON schema compatible with analysis tools and databases
- **Compliance**: TPC-compatible metric calculation and validation

## Result Schema Hierarchy

```
BenchmarkResults
├── Core Metadata (benchmark name, platform, scale factor, timestamp)
├── Execution Phases
│   ├── Setup Phase
│   │   ├── Data Generation
│   │   ├── Schema Creation
│   │   ├── Data Loading
│   │   └── Validation
│   ├── Power Test Phase (optional)
│   └── Throughput Test Phase (optional)
├── Query Results (list of QueryResult objects)
├── Query Definitions (SQL text and parameters)
├── System Profile (hardware, software, configuration)
├── Platform Info (driver versions, configuration)
└── Validation Results (correctness checks)
```

## Core Data Structures

### BenchmarkResults

Top-level object containing complete benchmark execution information.

**Key Fields**:
```python
{
    "benchmark_name": str,
    "platform": str,
    "execution_id": str,
    "timestamp": datetime,

    "scale_factor": float,
    "test_execution_type": str,

    "duration_seconds": float,
    "total_execution_time": float,
    "average_query_time": float,
    "data_loading_time": float,
    "schema_creation_time": float,

    "total_queries": int,
    "successful_queries": int,
    "failed_queries": int,

    "query_results": List[QueryResult],
    "query_definitions": Dict[str, QueryDefinition],
    "execution_phases": ExecutionPhases,

    "validation_status": str,
    "validation_details": dict,

    "system_profile": dict,
    "platform_info": dict,
    "tunings_applied": dict,
}
```

**Example**:
```json
{
  "benchmark_name": "TPC-H",
  "platform": "DuckDB",
  "scale_factor": 1.0,
  "execution_id": "tpch_1729613234",
  "timestamp": "2025-10-12T10:30:34Z",
  "duration_seconds": 47.3,
  "total_execution_time": 45.2,
  "average_query_time": 2.06,
  "total_queries": 22,
  "successful_queries": 22,
  "failed_queries": 0,
  "validation_status": "PASSED"
}
```

See: [Result Schema v1 Reference](../reference/result-schema-v1.md)

### QueryResult

Individual query execution details.

**Structure**:
```python
{
    "query_id": str,
    "stream_id": str,
    "execution_time": float,
    "status": str,
    "row_count": int,
    "data_scanned_bytes": int,
    "error_message": str | None,
    "query_text": str,
    "parameters": dict | None,
    "start_time": datetime,
    "end_time": datetime,
}
```

**Example**:
```json
{
  "query_id": "q1",
  "stream_id": "stream_1",
  "execution_time": 2.134,
  "status": "SUCCESS",
  "row_count": 4,
  "data_scanned_bytes": 104857600,
  "error_message": null,
  "start_time": "2025-10-12T10:30:35Z",
  "end_time": "2025-10-12T10:30:37Z"
}
```

### ExecutionPhases

Detailed timing breakdown for benchmark phases.

**Structure**:
```python
{
    "setup": SetupPhase,
    "power_test": PowerTestPhase,
    "throughput_test": ThroughputTestPhase,
}
```

#### SetupPhase

```python
{
    "data_generation": {
        "duration_ms": int,
        "status": str,
        "tables_generated": int,
        "total_rows_generated": int,
        "total_data_size_bytes": int,
        "per_table_stats": dict,
    },
    "schema_creation": {
        "duration_ms": int,
        "status": str,
        "tables_created": int,
        "constraints_applied": int,
        "indexes_created": int,
    },
    "data_loading": {
        "duration_ms": int,
        "status": str,
        "total_rows_loaded": int,
        "tables_loaded": int,
        "per_table_stats": dict,
    },
    "validation": {
        "duration_ms": int,
        "row_count_validation": str,
        "schema_validation": str,
        "data_integrity_checks": str,
    }
}
```

#### PowerTestPhase

```python
{
    "query_stream": List[QueryResult],
    "start_time": datetime,
    "end_time": datetime,
    "geometric_mean": float,
}
```

#### ThroughputTestPhase

```python
{
    "streams": List[QueryStream],
    "refresh_functions": List[RefreshFunction],
    "start_time": datetime,
    "end_time": datetime,
    "measurement_interval_seconds": float,
    "throughput_qph": float,
}
```

### QueryDefinition

SQL query template and parameters.

**Structure**:
```python
{
    "sql": str,
    "parameters": dict | None,
    "description": str | None,
}
```

**Example**:
```json
{
  "q1": {
    "sql": "SELECT l_returnflag, l_linestatus, ...",
    "parameters": {"date": "1998-09-02"},
    "description": "Pricing Summary Report"
  }
}
```

## System Profile

Hardware and software context for reproducibility.

```python
{
    "os": str,
    "os_version": str,
    "python_version": str,
    "benchbox_version": str,
    "cpu_model": str,
    "cpu_cores": int,
    "ram_gb": float,
    "anonymous_machine_id": str,
}
```

## Platform Info

Platform-specific metadata.

```python
{
    "platform_name": str,
    "driver_name": str,
    "driver_version": str,
    "configuration": dict,
    "warehouse_size": str | None,
    "cluster_id": str | None,
}
```

**Example (Snowflake)**:
```json
{
  "platform_name": "Snowflake",
  "driver_name": "snowflake-connector-python",
  "driver_version": "3.0.4",
  "configuration": {
    "account": "xy12345",
    "warehouse": "COMPUTE_WH",
    "warehouse_size": "LARGE",
    "database": "BENCHBOX",
    "schema": "TPCH_SF1"
  }
}
```

## Validation Results

Correctness verification details.

```python
{
    "validation_status": str,
    "validation_mode": str,
    "checks": {
        "row_count": {
            "status": str,
            "expected": dict,
            "actual": dict,
            "mismatches": list,
        },
        "result_checksum": {
            "status": str,
            "expected": dict,
            "actual": dict,
            "mismatches": list,
        },
        "data_integrity": {
            "status": str,
            "checks_performed": list,
            "failures": list,
        }
    }
}
```

## Serialization Formats

### JSON (Primary Format)

**Default output format** for all benchmark results.

**Features**:
- Human-readable
- Standard library support (Python `json` module)
- Compatible with analysis tools (jq, pandas, etc.)

**Example**:
```bash
cat results.json | jq '.query_results[] | {query_id, execution_time}'

import pandas as pd
df = pd.read_json("results.json")
```

### CSV (Export Format)

**Use case**: Simplified analysis in spreadsheets

```bash
benchbox export results.json --format csv --output-dir ./
```

**CSV Columns**:
```
query_id,execution_time,status,row_count
q1,2.134,SUCCESS,4
q2,3.421,SUCCESS,100
...
```

### Parquet (Archival Format)

**Use case**: Long-term storage, data lakes

```python
import pandas as pd
import json

with open("results.json") as f:
    data = json.load(f)

query_data = []
for q in data["results"]["queries"]["details"]:
    query_data.append({
        "query_id": q["id"],
        "execution_time_ms": q["timing"]["execution_ms"],
        "status": q["status"],
    })

df = pd.DataFrame(query_data)
df.to_parquet("results.parquet", compression="snappy")
```

**Benefits**:
- Compressed (smaller file size)
- Column-oriented (fast analytical queries)
- Schema evolution support

## Working with Results

### Python API

```python
from benchbox.core.results.models import BenchmarkResults

results = BenchmarkResults.from_json_file("results.json")

print(f"Benchmark: {results.benchmark_name}")
print(f"Duration: {results.duration_seconds:.2f}s")
print(f"Success rate: {results.successful_queries}/{results.total_queries}")

for qr in results.query_results:
    if qr.status == "SUCCESS":
        print(f"{qr.query_id}: {qr.execution_time:.3f}s")

results.to_json_file("results_copy.json")
```

### Command-Line Tools

```bash
jq '.query_results[] | select(.execution_time > 5)' results.json

jq '{benchmark: .benchmark_name, total_time: .total_execution_time, avg_time: .average_query_time}' results.json

benchbox compare baseline.json current.json
```

### Analysis Examples

#### Calculate Geometric Mean

```python
import math

query_times = [qr.execution_time for qr in results.query_results
               if qr.status == "SUCCESS"]
geomean = math.prod(query_times) ** (1.0 / len(query_times))
print(f"Geometric mean: {geomean:.3f}s")
```

#### Detect Regressions

```python
def compare_results(baseline, current, threshold=1.1):
    baseline_times = {qr.query_id: qr.execution_time
                      for qr in baseline.query_results}
    current_times = {qr.query_id: qr.execution_time
                     for qr in current.query_results}

    regressions = []
    for qid in baseline_times:
        if qid in current_times:
            ratio = current_times[qid] / baseline_times[qid]
            if ratio > threshold:
                regressions.append((qid, ratio))

    return regressions
```

#### Export to DataFrame

```python
import pandas as pd

df = pd.DataFrame([
    {
        "query_id": qr.query_id,
        "execution_time": qr.execution_time,
        "status": qr.status,
        "row_count": qr.row_count,
    }
    for qr in results.query_results
])

print(df.describe())
print(df.groupby("status").count())
```

## Schema Evolution

BenchBox uses schema versioning to manage result format evolution.

**Current Version**: v1 (result_schema_v1)

**Schema Rules**:
- New fields may be added (with defaults)
- Existing fields won't be removed or renamed
- Type changes are breaking (trigger major version)

## Best Practices

### Result Storage

1. **Version Control**: Store result JSON files in git for history tracking
2. **Naming Convention**: Use descriptive names: `{benchmark}_{sf}_{platform}_{timestamp}.json`
3. **Archival**: Compress old results with gzip or convert to Parquet
4. **Metadata**: Include git commit SHA in execution_id for traceability

### Result Analysis

1. **Geometric Mean**: Use for TPC benchmark reporting (not arithmetic mean)
2. **Outliers**: Investigate queries with >3x variance from baseline
3. **Validation**: Always check validation_status before trusting results
4. **Context**: Compare results with matching system_profile values

### Performance Monitoring

1. **Baseline**: Establish baseline results with known-good configuration
2. **Trending**: Track results over time to detect gradual degradation
3. **Alerting**: Set thresholds for acceptable regression (e.g., 10%)
4. **Root Cause**: Cross-reference system_profile for environmental changes

## Related Documentation

- [Result Schema v1 Reference](../reference/result-schema-v1.md) - Complete field documentation
- [Architecture](architecture.md) - How results fit into system design
- [Workflow](workflow.md) - Result collection in different workflows
- [Performance Monitoring](../advanced/performance.md) - Analyzing results over time
- [TPC Validation](../guides/tpc/tpc-validation-guide.md) - Validation for compliance

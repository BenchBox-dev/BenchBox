<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-H Official Benchmark Guide

```{tags} advanced, guide, tpc-h, validation
```

This guide provides systematic documentation for the TPC-H official benchmark implementation in BenchBox, including Power@Size and Throughput@Size. BenchBox does not export the composite QphH@Size; see [QphH@Size (not exported)](#qphh-size-not-exported).

## Overview

The TPC-H official benchmark implementation provides a complete, certification-ready TPC-H benchmark that coordinates all three test phases and reports Power@Size and Throughput@Size. It does not report the composite QphH@Size (Queries per Hour @ Size).

### What is TPC-H?

TPC-H is a decision support benchmark that consists of a suite of business-oriented ad-hoc queries and concurrent data modifications. The benchmark illustrates decision support systems that examine large volumes of data, execute queries with a high degree of complexity, and give answers to critical business questions.

### QphH@Size (not exported)

The QphH@Size metric is the official TPC-H performance measure. The specification defines Power@Size over the 22 queries plus the refresh functions RF1 and RF2, and requires the throughput test to run S pairs of RF1/RF2 in a refresh stream concurrently with the S query streams. QphH@Size is the geometric mean of Power@Size and Throughput@Size.

**Deviation from the specification.** BenchBox does not export QphH@Size. Its power test runs the 22 queries only, its throughput test has no refresh stream, and the maintenance test runs afterwards, not concurrently. A composite built from those values would overstate the specification metric, so results carry neither `qphh_at_size` nor a QphH label. Adding RF1/RF2 to the power and throughput tests is tracked as follow-up work.

BenchBox reports these two metrics instead:

- **Power@Size** = 3600 × Scale_Factor / geometric_mean(query times)
- **Throughput@Size** = (22 × Num_Streams) × 3600 × Scale_Factor / Throughput_Test_Time, where the time is the wall-clock interval from the first stream's first query to the last stream's last query (connection setup is excluded)

A result with any failed query, or whose throughput phase failed, carries no Throughput@Size.

## Key Features

- **Complete TPC-H Implementation**: All 22 queries with proper parameterization
- **Three Test Phases**: Power Test, Throughput Test, and Maintenance Test
- **Power@Size and Throughput@Size**: reported separately; no composite QphH@Size
- **Certification Ready**: Meets all TPC-H specification requirements
- **Comprehensive Reporting**: HTML, text, and CSV report generation
- **Result Validation**: Automatic validation against TPC-H specification
- **Audit Trail**: Complete audit trail for certification submissions
- **Performance Analysis**: Detailed performance metrics and analysis
- **Benchmark Comparison**: Compare results across different runs

## TPC-H Specification Compliance

The implementation follows the TPC-H specification requirements:

- **Query Execution**: All 22 TPC-H queries with proper parameterization
- **Stream Generation**: Query streams with official permutation matrix
- **Power Test**: Sequential execution of all queries
- **Throughput Test**: Concurrent execution of multiple query streams
- **Maintenance Test**: Concurrent data modification operations
- **Metric Calculation**: Power@Size and Throughput@Size (the QphH@Size composite is not exported)
- **Result Validation**: Validation against TPC-H specification requirements

## Installation and Setup

### Prerequisites

- Python 3.8 or higher
- Database system (SQLite, PostgreSQL, MySQL, etc.)
- TPC-H data generation tools (included with BenchBox)

### Installation

```bash
uv add benchbox
```

### Database Setup

The benchmark works with any database supported by Python. The examples below show a connection factory for SQLite (for testing), PostgreSQL, and MySQL:

```python
import sqlite3
def connection_factory():
    return sqlite3.connect("tpch.db")

import psycopg2
def connection_factory():
    return psycopg2.connect("host=localhost dbname=tpch user=postgres")

import mysql.connector
def connection_factory():
    return mysql.connector.connect(
        host="localhost",
        database="tpch",
        user="root",
        password="password"
    )
```

## Quick Start

Here's a minimal example to run the official TPC-H benchmark:

```python
from benchbox import TPCH
import sqlite3

benchmark = TPCH(
    scale_factor=1.0,
    output_dir="./tpch_benchmark",
    verbose=True
)

benchmark.generate_data()

def connection_factory():
    conn = sqlite3.connect("tpch.db")
    return conn

result = benchmark.run_official_benchmark(
    connection_factory=connection_factory,
    num_streams=2,
    validate_results=True,
    audit_trail=True
)

print(f"Power@Size: {result.power_test.power_at_size:.2f}")
print(f"Throughput@Size: {result.throughput_test.throughput_at_size:.2f}")
print(f"Certification Ready: {result.certification_ready}")
```

## Detailed Usage

### Creating a Benchmark Instance

The parameters are:
- `scale_factor`: the scale factor (1.0 is about 1 GB).
- `output_dir`: the output directory.
- `verbose`: enables verbose output.
- `parallel`: the number of parallel data generation workers.

```python
from benchbox import TPCH

benchmark = TPCH(
    scale_factor=1.0,
    output_dir="./output",
    verbose=True,
    parallel=4
)
```

### Running the Official Benchmark

The parameters are:
- `connection_factory`: the database connection factory.
- `num_streams`: the number of concurrent streams.
- `output_dir`: the results output directory.
- `verbose`: enables verbose logging.
- `validate_results`: enables result validation.
- `audit_trail`: enables the audit trail.

```python
result = benchmark.run_official_benchmark(
    connection_factory=connection_factory,
    num_streams=2,
    output_dir="./benchmark_results",
    verbose=True,
    validate_results=True,
    audit_trail=True
)
```

### Accessing Results

The result object holds the overall results, the Power Test results, the Throughput Test results, and the validation results:

```python
print(f"Success: {result.success}")
print(f"Total Time: {result.total_benchmark_time}")

print(f"Power Test Time: {result.power_test.total_time}")
print(f"Power@Size: {result.power_test.power_at_size}")
print(f"Query Times: {result.power_test.query_times}")

print(f"Throughput Test Time: {result.throughput_test.total_time}")
print(f"Throughput@Size: {result.throughput_test.throughput_at_size}")
print(f"Stream Times: {result.throughput_test.stream_times}")

print(f"Certification Ready: {result.certification_ready}")
print(f"Validation Errors: {result.validation_errors}")
```

## Test Phases

### Power Test

The Power Test measures single-stream performance by executing all 22 TPC-H queries sequentially. The Power Test runs automatically as part of the official benchmark. It executes queries 1-22 in order with fixed parameters.

**Key characteristics:**
- Sequential execution of all 22 queries
- Fixed seed for reproducible parameters
- Measures single-stream query processing capability
- Contributes to Power@Size calculation

### Throughput Test

The Throughput Test measures multi-stream performance by executing multiple concurrent query streams. The Throughput Test runs automatically as part of the official benchmark. Each stream contains all 22 queries in randomized order.

**Key characteristics:**
- Concurrent execution of multiple query streams
- Each stream uses TPC-H permutation matrix for query ordering
- Stream-specific parameter generation
- Measures multi-user concurrent processing capability
- Contributes to Throughput@Size calculation

### Maintenance Test

> **⚠️ CRITICAL: Database Reload Required After Maintenance Test**
>
> The Maintenance Test permanently modifies database contents by inserting and deleting data through
> Refresh Functions (RF1 and RF2). After running the maintenance phase, you **must reload the database**
> before running power or throughput tests again. Failure to reload will result in incorrect benchmark
> results because queries will execute against modified data.
>
> **Proper workflow:** `generate` → `load` → `power` → `throughput` → `maintenance` → **[RELOAD before next power/throughput]**

The Maintenance Test measures the system's ability to handle data modification operations while
maintaining query performance. It executes two Refresh Functions (RF1 and RF2) that simulate
real-world data warehouse operations.

#### Refresh Function 1 (RF1): Insert New Sales

RF1 simulates processing of new sales orders by inserting data into the database:

**Operations:**
- Inserts new ORDERS records (~0.1% of scale factor)
  - For SF=1: ~1,500 new orders with unique order keys
- Inserts corresponding LINEITEM records (1-7 items per order)
  - For SF=1: ~6,000-10,500 lineitems (average 4-6 per order)
- Uses TPC-H compliant data generation (proper dates, prices, quantities)
- All insertions are committed to the database

**Data Volume by Scale Factor:**

| Scale Factor | Orders Inserted | Lineitems Inserted (approx) |
|--------------|-----------------|------------------------------|
| 0.01         | 15              | 60-105                       |
| 0.1          | 150             | 600-1,050                    |
| 1            | 1,500           | 6,000-10,500                 |
| 10           | 15,000          | 60,000-105,000               |

#### Refresh Function 2 (RF2): Delete Old Sales

RF2 simulates purging of old sales data by deleting records:

**Operations:**
- Identifies oldest orders by `O_ORDERDATE`
- **CRITICAL:** Deletes LINEITEM records first (maintains referential integrity)
- Then deletes corresponding ORDERS records
- Deletes same volume as RF1 (~0.1% of scale factor)
- All deletions are committed to the database

**Referential Integrity:**
RF2 must delete LINEITEM rows before ORDERS rows to maintain foreign key constraints. This
reflects real-world database constraints where line items reference parent orders.

#### Why Database Reload Is Required

**The Maintenance Test permanently modifies database contents:**

1. **Data Changes Are Committed**
   - RF1 inserts ~1,500 orders + ~6,000-10,500 lineitems (at SF=1)
   - RF2 deletes ~1,500 orders + their corresponding lineitems
   - Changes are committed and permanent

2. **Query Results Will Differ**
   - `SELECT COUNT(*) FROM ORDERS` returns different count
   - Aggregate queries return different totals (e.g., `SUM(O_TOTALPRICE)`)
   - Join operations produce different row counts
   - Power/Throughput test results become invalid

3. **Not Idempotent**
   - Running maintenance again modifies different data
   - Second RF2 deletes different "oldest" orders (dates have changed)
   - Results become unpredictable and non-reproducible

4. **TPC Specification Requirement**
   - Official TPC-H specification requires fresh, unmodified dataset
   - Benchmark results are only valid on clean data
   - Certification requires strict adherence to data integrity

#### Code Example

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
from pathlib import Path

benchmark = TPCH(scale_factor=1.0, output_dir=Path("./tpch_data"))
benchmark.generate_data()

adapter = DuckDBAdapter(database_path="tpch.duckdb", force_recreate=True)

power_result = adapter.run_benchmark(benchmark, test_execution_type="power")
print(f"Power Test: {power_result.total_execution_time:.2f}s")

throughput_result = adapter.run_benchmark(benchmark, test_execution_type="throughput")
print(f"Throughput Test: {throughput_result.total_execution_time:.2f}s")

print("\n⚠️  Reloading database before maintenance test...")
adapter = DuckDBAdapter(database_path="tpch.duckdb", force_recreate=True)

maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")
print(f"Maintenance Test: {maintenance_result.total_execution_time:.2f}s")

print("\n⚠️  Database modified - reload required before additional tests!")
```

The example runs in three steps. Step 1 runs the power and throughput tests on clean data. Step 2 reloads the database before maintenance, which creates a fresh database. Step 3 runs the maintenance test. After step 3 the database contains modified data, so it must be reloaded before the power or throughput test runs again.

**Workflow Summary:**

```
Correct:   generate → load → power → throughput → maintenance
Correct:   generate → load → power → throughput → maintenance → [RELOAD] → power (if rerunning)
Incorrect: generate → load → power → maintenance → throughput  ❌ (throughput runs on modified data!)
Incorrect: generate → load → maintenance → power → throughput  ❌ (power/throughput run on modified data!)
```

**Key characteristics:**
- Executes real INSERT and DELETE SQL operations
- Modifies ~0.1% of database rows (insert and delete)
- Tests system's ability to handle concurrent data modifications
- Required for complete TPC-H compliance and certification

## Power@Size and Throughput@Size Calculation

BenchBox does not calculate QphH@Size (see [QphH@Size (not exported)](#qphh-size-not-exported)). It calculates the two component metrics.

### Component Calculations

**Power@Size:**
```
Power@Size = 3600 × Scale_Factor / geometric_mean(query times)
```

**Throughput@Size:**
```
Throughput@Size = 22 × Num_Streams × 3600 × Scale_Factor / Throughput_Test_Time
```

### Example Calculation

For a throughput test with:
- Scale Factor: 1.0
- Throughput Test Time: 150 seconds
- Number of Streams: 2

```python
throughput_at_size = 22 * 2 * 3600 * 1.0 / 150
```

The results are `power_at_size = 36.0`, `throughput_at_size = 48.0`, and `qphh_at_size = (36.0 * 48.0) ** 0.5 = 41.57`.

## Reporting and Validation

### Report Generation

The reports show Power@Size and Throughput@Size and contain no QphH@Size. They accept the object returned by `run_official_benchmark` directly.

```python
from benchbox.core.tpch.reporting import TPCHReportGenerator

report_generator = TPCHReportGenerator(output_dir="./reports")

html_report = report_generator.generate_detailed_report(
    result=result,
    report_title="TPC-H Benchmark Report",
    include_detailed_analysis=True,
    include_certification_info=True
)

cert_report = report_generator.generate_certification_report(result=result)

csv_report = report_generator.generate_performance_csv(result=result)
```

### Result Validation

The benchmark automatically validates results against TPC-H specification:

```python
if result.certification_ready:
    print("Benchmark is certification ready!")
else:
    print("Validation issues found:")
    for error in result.validation_errors:
        print(f"  - {error}")
```

### Benchmark Comparison

```python
comparison = report_generator.compare_results(
    baseline_result=baseline_result,
    current_result=current_result
)

print(f"Power@Size Change: {comparison.relative_change:+.1%}")
print(f"Significant Change: {comparison.significant_change}")

comparison_report = report_generator.generate_comparison_report(
    baseline_result=baseline_result,
    current_result=current_result
)
```

## Certification Workflow

For TPC-H certification, follow these steps:

### 1. Preparation

Use an appropriate, certified scale factor for certification:

```python
benchmark = TPCH(
    scale_factor=100.0,
    output_dir="./certification_data",
    verbose=True
)
```

### 2. Data Generation

```python
data_files = benchmark.generate_data()
```

### 3. Database Setup

Set up a production database with proper configuration. Use a database system appropriate for certification.

### 4. Benchmark Execution

Run with certification parameters, using an appropriate number of streams:

```python
result = benchmark.run_official_benchmark(
    connection_factory=connection_factory,
    num_streams=8,
    validate_results=True,
    audit_trail=True
)
```

### 5. Report Generation

```python
report_generator = TPCHReportGenerator(output_dir="./certification_reports")
cert_report = report_generator.generate_certification_report(result=result)
```

### 6. Validation

```python
if result.certification_ready:
    print("Ready for certification submission")
else:
    print("Address validation issues before certification")
```

## Best Practices

### Scale Factor Selection

- **Development/Testing**: Use scale factors 0.01-1.0
- **Performance Testing**: Use scale factors 1-10
- **Certification**: Use TPC-approved scale factors (100, 300, 1000, etc.)

### Database Configuration

- **Memory**: Ensure sufficient memory for the dataset
- **Storage**: Use appropriate storage configuration
- **Parallelism**: Configure database for concurrent query execution
- **Indexing**: Create appropriate indexes for TPC-H queries

### Benchmark Configuration

The examples below are, in order, for development, performance testing, and certification:

```python
benchmark = TPCH(scale_factor=0.01, verbose=True)

benchmark = TPCH(scale_factor=10.0, parallel=8)

benchmark = TPCH(scale_factor=100.0, verbose=True)
```

### Stream Configuration

- **Development**: Use 1-2 streams
- **Performance Testing**: Use 2-4 streams
- **Certification**: Use appropriate number based on system capabilities

## Troubleshooting

### Common Issues

#### Database Connection Issues

Issue: connection timeouts. Solution: increase the connection timeout.

```python
def connection_factory():
    conn = sqlite3.connect("tpch.db", timeout=30)
    return conn
```

#### Query Execution Failures

Issue: query syntax errors. Solution: check SQL dialect compatibility.

```python
query = benchmark.get_query(1, dialect="postgres")
```

#### Memory Issues

Issue: out of memory during execution. Solution: use a smaller scale factor or increase system memory.

```python
benchmark = TPCH(scale_factor=0.1)
```

#### Performance Issues

Issue: slow query execution. Solution: optimize the database configuration and indexing.

### Debugging

Enable verbose logging for detailed debugging:

```python
benchmark = TPCH(verbose=True)
result = benchmark.run_official_benchmark(
    connection_factory=connection_factory,
    verbose=True
)
```

Check audit trail logs. Audit trail files are created in `output_dir`. Check the `benchmark_audit_*.log` files for detailed execution logs.

### Performance Optimization

1. **Database Tuning**: Optimize database configuration
2. **Index Creation**: Create appropriate indexes for TPC-H queries
3. **Memory Allocation**: Ensure sufficient memory for concurrent streams
4. **Storage Configuration**: Use appropriate storage for data and logs
5. **Query Optimization**: Review query execution plans

## Advanced-level Usage

### Custom Connection Factory

```python
def custom_connection_factory():
    conn = sqlite3.connect("tpch.db")
    conn.execute("PRAGMA cache_size=100000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
```

### Custom Validation

```python
def custom_validate_result(result):
    if result.throughput_test.throughput_at_size < 100:
        result.validation_errors.append("Throughput@Size below minimum threshold")
    return result
```

### Batch Processing

```python
def run_multiple_benchmarks():
    scale_factors = [0.1, 0.5, 1.0]
    results = []

    for sf in scale_factors:
        benchmark = TPCH(scale_factor=sf)
        result = benchmark.run_official_benchmark(
            connection_factory=connection_factory,
            num_streams=2
        )
        results.append(result)

    return results
```

## API Reference

### TPCH Class

```python
class TPCH:
    def __init__(self, scale_factor=1.0, output_dir=None, verbose=False, parallel=1):
        pass

    def generate_data(self) -> List[Path]:
        pass

    def run_official_benchmark(self, connection_factory, num_streams=2, **kwargs) -> TPCHOfficialBenchmarkResult:
        pass

    def get_query(self, query_id, **kwargs) -> str:
        pass
```

### TPCHOfficialBenchmark Class

```python
class TPCHOfficialBenchmark:
    def __init__(self, benchmark, connection_factory, num_streams=2, **kwargs):
        pass

    def run_official_benchmark(self) -> TPCHOfficialBenchmarkResult:
        pass
```

### TPCHReportGenerator Class

```python
class TPCHReportGenerator:
    def __init__(self, output_dir=None):
        pass

    def generate_detailed_report(self, result, **kwargs) -> Path:
        pass

    def generate_certification_report(self, result) -> Path:
        pass

    def compare_results(self, baseline_result, current_result) -> ComparisonResult:
        pass
```

## Conclusion

The TPC-H official benchmark implementation provides a complete, certification-ready solution for TPC-H benchmarking. It includes all required test phases, Power@Size and Throughput@Size reporting, systematic reporting, and validation capabilities.

For more information, examples, and updates, visit the [BenchBox GitHub repository](https://github.com/joeharris76/benchbox).

<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-H Official Benchmark Guide

```{tags} advanced, guide, tpc-h, validation
```

This guide provides systematic documentation for the TPC-H official benchmark implementation in BenchBox, including the complete QphH@Size calculation that meets TPC-H specification requirements.

## Overview

The TPC-H official benchmark implementation provides a complete, certification-ready TPC-H benchmark that coordinates all three test phases and calculates the official QphH@Size (Queries per Hour @ Size) metric according to the TPC-H specification.

### What is TPC-H?

TPC-H is a decision support benchmark that consists of a suite of business-oriented ad-hoc queries and concurrent data modifications. The benchmark illustrates decision support systems that examine large volumes of data, execute queries with a high degree of complexity, and give answers to critical business questions.

### QphH@Size Metric

The QphH@Size metric is the official TPC-H performance measure that combines both single-stream (Power Test) and multi-stream (Throughput Test) performance:

```
QphH@Size = √(Power@Size × Throughput@Size)
```

Where:
- **Power@Size** = 3600 × Scale_Factor / Power_Test_Time
- **Throughput@Size** = Num_Streams × 3600 × Scale_Factor / Throughput_Test_Time

## Key Features

- **Complete TPC-H Implementation**: All 22 queries with proper parameterization
- **Three Test Phases**: Power Test, Throughput Test, and Maintenance Test
- **Official QphH@Size Calculation**: Geometric mean formula per TPC-H spec
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
- **Metric Calculation**: Official QphH@Size calculation formula
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

The benchmark works with any database supported by Python. Examples:

```python
# SQLite (for testing)
import sqlite3
def connection_factory():
    return sqlite3.connect("tpch.db")

# PostgreSQL
import psycopg2
def connection_factory():
    return psycopg2.connect("host=localhost dbname=tpch user=postgres")

# MySQL
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

# Create benchmark instance
benchmark = TPCH(
    scale_factor=1.0,
    output_dir="./tpch_benchmark",
    verbose=True
)

# Generate data
benchmark.generate_data()

# Setup database connection factory
def connection_factory():
    conn = sqlite3.connect("tpch.db")
    return conn

# Run official benchmark
result = benchmark.run_official_benchmark(
    connection_factory=connection_factory,
    num_streams=2,
    validate_results=True,
    audit_trail=True
)

# Display results
print(f"QphH@Size: {result.qphh_at_size:.2f}")
print(f"Power@Size: {result.power_test.power_at_size:.2f}")
print(f"Throughput@Size: {result.throughput_test.throughput_at_size:.2f}")
print(f"Certification Ready: {result.certification_ready}")
```

## Detailed Usage

### Creating a Benchmark Instance

```python
from benchbox import TPCH

benchmark = TPCH(
    scale_factor=1.0,           # Scale factor (1.0 = ~1GB)
    output_dir="./output",      # Output directory
    verbose=True,               # Enable verbose output
    parallel=4                  # Parallel data generation
)
```

### Running the Official Benchmark

```python
result = benchmark.run_official_benchmark(
    connection_factory=connection_factory,    # Database connection factory
    num_streams=2,                           # Number of concurrent streams
    output_dir="./benchmark_results",        # Results output directory
    verbose=True,                            # Enable verbose logging
    validate_results=True,                   # Enable result validation
    audit_trail=True                         # Enable audit trail
)
```

### Accessing Results

```python
# Overall results
print(f"Success: {result.success}")
print(f"QphH@Size: {result.qphh_at_size}")
print(f"Total Time: {result.total_benchmark_time}")

# Power Test results
print(f"Power Test Time: {result.power_test.total_time}")
print(f"Power@Size: {result.power_test.power_at_size}")
print(f"Query Times: {result.power_test.query_times}")

# Throughput Test results
print(f"Throughput Test Time: {result.throughput_test.total_time}")
print(f"Throughput@Size: {result.throughput_test.throughput_at_size}")
print(f"Stream Times: {result.throughput_test.stream_times}")

# Validation results
print(f"Certification Ready: {result.certification_ready}")
print(f"Validation Errors: {result.validation_errors}")
```

## Test Phases

### Power Test

The Power Test measures single-stream performance by executing all 22 TPC-H queries sequentially:

```python
# Power Test is automatically run as part of the official benchmark
# It executes queries 1-22 in order with fixed parameters
```

**Key characteristics:**
- Sequential execution of all 22 queries
- Fixed seed for reproducible parameters
- Measures single-stream query processing capability
- Contributes to Power@Size calculation

### Throughput Test

The Throughput Test measures multi-stream performance by executing multiple concurrent query streams:

```python
# Throughput Test runs multiple streams concurrently
# Each stream contains all 22 queries in randomized order
```

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

# Generate TPC-H data
benchmark = TPCH(scale_factor=1.0, output_dir=Path("./tpch_data"))
benchmark.generate_data()

# Step 1: Run power and throughput tests on clean data
adapter = DuckDBAdapter(database_path="tpch.duckdb", force_recreate=True)

power_result = adapter.run_benchmark(benchmark, test_execution_type="power")
print(f"Power Test: {power_result.total_execution_time:.2f}s")

throughput_result = adapter.run_benchmark(benchmark, test_execution_type="throughput")
print(f"Throughput Test: {throughput_result.total_execution_time:.2f}s")

# Step 2: RELOAD database before maintenance (creates fresh database)
print("\n⚠️  Reloading database before maintenance test...")
adapter = DuckDBAdapter(database_path="tpch.duckdb", force_recreate=True)

# Step 3: Run maintenance test
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")
print(f"Maintenance Test: {maintenance_result.total_execution_time:.2f}s")

# WARNING: Database now contains modified data
# Must reload before running power/throughput again
print("\n⚠️  Database modified - reload required before additional tests!")
```

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

## QphH@Size Calculation

The QphH@Size metric is calculated using the official TPC-H formula:

### Formula

```
QphH@Size = √(Power@Size × Throughput@Size)
```

### Component Calculations

**Power@Size:**
```
Power@Size = 3600 × Scale_Factor / Power_Test_Time
```

**Throughput@Size:**
```
Throughput@Size = Num_Streams × 3600 × Scale_Factor / Throughput_Test_Time
```

### Example Calculation

For a benchmark with:
- Scale Factor: 1.0
- Power Test Time: 100 seconds
- Throughput Test Time: 150 seconds
- Number of Streams: 2

```python
# Calculate components
power_at_size = 3600 * 1.0 / 100  # = 36.0
throughput_at_size = 2 * 3600 * 1.0 / 150  # = 48.0

# Calculate QphH@Size
qphh_at_size = (power_at_size * throughput_at_size) ** 0.5
# = (36.0 * 48.0) ** 0.5 = 41.57
```

## Reporting and Validation

### Report Generation

```python
from benchbox.core.tpch.reporting import TPCHReportGenerator

# Create report generator
report_generator = TPCHReportGenerator(output_dir="./reports")

# Generate systematic HTML report
html_report = report_generator.generate_systematic_report(
    result=result,
    report_title="TPC-H Benchmark Report",
    include_detailed_analysis=True,
    include_certification_info=True
)

# Generate certification report
cert_report = report_generator.generate_certification_report(result=result)

# Generate performance CSV
csv_report = report_generator.generate_performance_csv(result=result)
```

### Result Validation

The benchmark automatically validates results against TPC-H specification:

```python
# Validation is automatically performed
if result.certification_ready:
    print("Benchmark is certification ready!")
else:
    print("Validation issues found:")
    for error in result.validation_errors:
        print(f"  - {error}")
```

### Benchmark Comparison

```python
# Compare two benchmark results
comparison = report_generator.compare_results(
    baseline_result=baseline_result,
    current_result=current_result
)

print(f"Performance Change: {comparison.relative_change:+.1%}")
print(f"Significant Change: {comparison.significant_change}")

# Generate comparison report
comparison_report = report_generator.generate_comparison_report(
    baseline_result=baseline_result,
    current_result=current_result
)
```

## Certification Workflow

For TPC-H certification, follow these steps:

### 1. Preparation

```python
# Use appropriate scale factor for certification
benchmark = TPCH(
    scale_factor=100.0,  # Use certified scale factor
    output_dir="./certification_data",
    verbose=True
)
```

### 2. Data Generation

```python
# Generate certification data
data_files = benchmark.generate_data()
```

### 3. Database Setup

```python
# Setup production database with proper configuration
# Use appropriate database system for certification
```

### 4. Benchmark Execution

```python
# Run with certification parameters
result = benchmark.run_official_benchmark(
    connection_factory=connection_factory,
    num_streams=8,  # Use appropriate number of streams
    validate_results=True,
    audit_trail=True
)
```

### 5. Report Generation

```python
# Generate certification reports
report_generator = TPCHReportGenerator(output_dir="./certification_reports")
cert_report = report_generator.generate_certification_report(result=result)
```

### 6. Validation

```python
# Ensure certification readiness
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

```python
# For development
benchmark = TPCH(scale_factor=0.01, verbose=True)

# For performance testing
benchmark = TPCH(scale_factor=10.0, parallel=8)

# For certification
benchmark = TPCH(scale_factor=100.0, verbose=True)
```

### Stream Configuration

- **Development**: Use 1-2 streams
- **Performance Testing**: Use 2-4 streams
- **Certification**: Use appropriate number based on system capabilities

## Troubleshooting

### Common Issues

#### Database Connection Issues

```python
# Issue: Connection timeouts
# Solution: Increase connection timeout
def connection_factory():
    conn = sqlite3.connect("tpch.db", timeout=30)
    return conn
```

#### Query Execution Failures

```python
# Issue: Query syntax errors
# Solution: Check SQL dialect compatibility
query = benchmark.get_query(1, dialect="postgres")
```

#### Memory Issues

```python
# Issue: Out of memory during execution
# Solution: Use smaller scale factor or increase system memory
benchmark = TPCH(scale_factor=0.1)  # Reduce scale factor
```

#### Performance Issues

```python
# Issue: Slow query execution
# Solution: Optimize database configuration and indexing
```

### Debugging

Enable verbose logging for detailed debugging:

```python
# Enable verbose output
benchmark = TPCH(verbose=True)
result = benchmark.run_official_benchmark(
    connection_factory=connection_factory,
    verbose=True
)
```

Check audit trail logs:

```python
# Audit trail files are created in output_dir
# Check benchmark_audit_*.log files for detailed execution logs
```

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
    """Custom connection factory with specific configuration."""
    conn = sqlite3.connect("tpch.db")
    conn.execute("PRAGMA cache_size=100000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
```

### Custom Validation

```python
def custom_validate_result(result):
    """Custom result validation."""
    if result.qphh_at_size < 100:
        result.validation_errors.append("QphH@Size below minimum threshold")
    return result
```

### Batch Processing

```python
def run_multiple_benchmarks():
    """Run multiple benchmarks with different configurations."""
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
        """Initialize TPC-H benchmark."""

    def generate_data(self) -> List[Path]:
        """Generate TPC-H data files."""

    def run_official_benchmark(self, connection_factory, num_streams=2, **kwargs) -> QphHResult:
        """Run official TPC-H benchmark."""

    def get_query(self, query_id, **kwargs) -> str:
        """Get specific TPC-H query."""
```

### TPCHOfficialBenchmark Class

```python
class TPCHOfficialBenchmark:
    def __init__(self, benchmark, connection_factory, num_streams=2, **kwargs):
        """Initialize official benchmark runner."""

    def run_official_benchmark(self) -> QphHResult:
        """Run complete official benchmark."""
```

### TPCHReportGenerator Class

```python
class TPCHReportGenerator:
    def __init__(self, output_dir=None):
        """Initialize report generator."""

    def generate_systematic_report(self, result, **kwargs) -> Path:
        """Generate systematic HTML report."""

    def generate_certification_report(self, result) -> Path:
        """Generate certification report."""

    def compare_results(self, baseline_result, current_result) -> ComparisonResult:
        """Compare benchmark results."""
```

## Conclusion

The TPC-H official benchmark implementation provides a complete, certification-ready solution for TPC-H benchmarking. It includes all required test phases, proper QphH@Size calculation, systematic reporting, and validation capabilities.

For more information, examples, and updates, visit the [BenchBox GitHub repository](https://github.com/joeharris76/benchbox).
